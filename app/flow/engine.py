"""
Flow engine.

Do hi raaste hain:

  1. User ne BUTTON dabaya  -> button_payload se seedha agla screen.
     Koi LLM nahi, koi cost nahi, koi guess nahi. Hamesha same behaviour.

  2. User ne TEXT likha     -> agar current screen input maang raha tha to
     action chalao; warna AI fallback jawab de aur phir wahi buttons wapas.

Purana graph.py ka 560-line if-else ladder (spelling lists, yes/no matching,
LLM se intent poochna) is file se replace ho jaata hai.
"""
import logging

from app.flow import actions, loader
from app.flow.actions import Ctx, Result
from app.services import whatsapp_service as wa
from app.services.redis_service import get_session, save_message, save_session

log = logging.getLogger(__name__)

MAX_HOPS = 10  # action -> action chain ka guard (flow mein loop ho to bhi na atke)


import re

# Default English. User Hindi/regional bole tabhi switch.
DEFAULT_LANG = "en"

_INDIC = re.compile(
    r"[ऀ-ॿ"   # Devanagari (Hindi)
    r"઀-૿"    # Gujarati
    r"਀-੿"    # Gurmukhi (Punjabi)
    r"஀-௿"    # Tamil
    r"ఀ-౿"    # Telugu
    r"ಀ-೿"    # Kannada
    r"ഀ-ൿ]"   # Malayalam
)

# Romanized Hindi ke aam shabd — Latin script mein bhi Hindi pakadne ke liye.
_HINDI_HINTS = {
    "haan", "nahi", "nahin", "kya", "kyu", "kyun", "kaise", "kaisa", "aap",
    "mujhe", "mera", "meri", "chahiye", "batao", "bataye", "karo", "karna",
    "hai", "hain", "kar", "kripya", "namaste", "namaskar", "dhanyavaad",
    "shukriya", "acha", "accha", "theek", "thik", "matlab", "samajh",
}


def _lang(session: dict) -> str:
    return session.get("lang", DEFAULT_LANG)


def _detect_lang(text: str, current: str) -> str:
    """Text ki bhasha. Pakka na ho to current hi rehne do (sticky)."""
    if not text:
        return current
    if _INDIC.search(text):
        return "hi"  # flow ke paas sirf en/hi hain; Indic script -> hi
    low = text.lower()
    if "english" in low or "englis" in low:
        return "en"
    if "hindi" in low:
        return "hi"
    words = [w.strip(".,!?") for w in low.split()]
    if sum(1 for w in words if w in _HINDI_HINTS) >= 2:
        return "hi"
    return current


def _i18n(val, lang: str):
    """{'hi':..,'en':..} -> string. Pehle se string ho to waisa hi."""
    if isinstance(val, dict):
        return val.get(lang) or val.get("hi", "")
    return val


def _send_screen(ctx: Ctx, name: str, params: dict) -> None:
    """Screen ko WhatsApp par bhejo. Media alag message mein pehle jaati hai."""
    s = loader.screen(name)
    lang = ctx.lang
    body = actions.render(_i18n(s.get("body"), lang), params)

    media = s.get("media")
    if media and loader.media_ready(media):
        wa.send_media(ctx.phone, media["type"], media["url"])
    elif media:
        log.warning("%s: media URL abhi placeholder hai, skip kiya", name)

    stype = s.get("type")

    if stype == "buttons":
        btns = [{"id": b["id"], "title": _i18n(b["title"], lang)} for b in s["buttons"]]
        wa.send_buttons(ctx.phone, body, btns)

    elif stype == "list" and s.get("dynamic_rows"):
        dyn = s["dynamic_rows"]
        items = ctx.session.get(dyn["source"]) or []
        rows = []
        for i, item in enumerate(items[:loader.MAX_LIST_ROWS]):
            title = (item.get("title") or "")[:loader.MAX_ROW_TITLE]
            desc = (item.get("locality") or item.get("address") or "")[:70]
            row = {"id": f"{dyn['id_prefix']}{i}", "title": title or f"Location {i + 1}"}
            if desc:
                row["description"] = desc
            rows.append(row)
        wa.send_list(ctx.phone, body, _i18n(s["list_button"], lang),
                     [{"title": _i18n(s.get("section_title") or s["body"], lang)[:24],
                       "rows": rows}])

    elif stype == "list":
        sections = []
        for sec in s["sections"]:
            rows = []
            for row in sec["rows"]:
                r = {"id": row["id"], "title": _i18n(row["title"], lang)}
                if "description" in row:
                    r["description"] = _i18n(row["description"], lang)
                rows.append(r)
            sections.append({"title": _i18n(sec["title"], lang), "rows": rows})
        wa.send_list(ctx.phone, body, _i18n(s["list_button"], lang), sections)

    else:  # text | input
        wa.send_text(ctx.phone, body)

    save_message(ctx.user_id, "assistant", body)

    # Screen ka apna follow-up (jaise CONNECT_PENDING par 10 min baad nudge)
    if s.get("followup"):
        from app.services.followup_service import schedule
        schedule(ctx.user_id, ctx.phone, s["followup"])

    ctx.session["flow_screen"] = name
    # Params bhi yaad rakho — AI fallback ke baad yahi screen dobara dikhani
    # padti hai, aur tab {{biz_name}} jaise placeholder khaali nahi rehne chahiye.
    ctx.session["flow_params"] = {k: str(v) for k, v in params.items()}
    save_session(ctx.user_id, ctx.session)


def _goto(ctx: Ctx, name: str, params: dict = None) -> None:
    """
    Screen par jao. 'action' type screens khud chalte hain aur aage badh jaate hain,
    isliye chain ho sakti hai — MAX_HOPS us chain ko bound karta hai.
    """
    params = {**actions._base_params(), **(params or {})}

    for _ in range(MAX_HOPS):
        s = loader.screen(name)

        # Screen ki shart (jaise FEATURES_MENU ko connect_verified chahiye)
        req = s.get("requires")
        if req and not ctx.session.get(req):
            name = s.get("on_missing") or "SUPPORT"
            continue

        # Dynamic list khaali ho to khaali list mat bhejo
        dyn = s.get("dynamic_rows")
        if dyn and not ctx.session.get(dyn["source"]):
            name = dyn.get("empty") or "SUPPORT"
            continue

        if s.get("type") != "action":
            # buttons/list screen ka apna action bhi ho sakta hai (jaise
            # PLAN_DETAIL -> LOAD_PLAN) jo body ke {{...}} bharta hai.
            #
            # input screen ko chhod do: uska action tab chalta hai jab user
            # jawab likhta hai (_handle_text), screen dikhate waqt nahi.
            if s.get("action") and s.get("type") != "input":
                res = actions.run(s["action"], ctx)
                if not res.ok:
                    name = s.get("on_error") or "SUPPORT"
                    continue
                params = {**params, **res.params}
            _send_screen(ctx, name, params)
            return

        res = actions.run(s["action"], ctx)
        params = {**params, **res.params}

        if res.stop:
            ctx.session["flow_params"] = {k: str(v) for k, v in params.items()}
            save_session(ctx.user_id, ctx.session)
            return

        if res.next_override:
            name = res.next_override
        elif res.ok:
            name = s["next"]
        else:
            name = s.get("on_error") or "SUPPORT"

    log.error("Flow loop! '%s' par %d hops ke baad ruka", name, MAX_HOPS)
    _send_screen(ctx, "SUPPORT", params)


def _handle_button(ctx: Ctx, payload: str) -> bool:
    """Button click. True agar payload pehchana gaya."""
    target = loader.target_for(payload)
    if not target:
        log.warning("Anjaan button payload: %r", payload)
        return False

    ctx.button_id = payload

    # Button ke saath action juda ho sakta hai (jaise BIZ_NEXT -> NEXT_RESULT)
    current = ctx.session.get("flow_screen", "")
    btn_def = {}
    if current:
        for b in loader.screen(current).get("buttons", []):
            if b["id"] == payload:
                btn_def = b
                break

    if btn_def.get("action"):
        res = actions.run(btn_def["action"], ctx)
        if res.stop:
            return True
        if res.next_override:
            _goto(ctx, res.next_override, res.params)
        elif res.ok:
            _goto(ctx, btn_def["next"], res.params)
        else:
            _goto(ctx, btn_def.get("on_error") or "SUPPORT", res.params)
        return True

    _goto(ctx, target)
    return True


_GREETINGS = {
    "hi", "hii", "hiii", "hello", "helo", "hey", "hy", "start", "restart",
    "namaste", "namaskar", "hola", "shuru", "menu",
}


def _is_greeting(text: str) -> bool:
    t = text.strip().lower().strip("!., ")
    return t in _GREETINGS


def _handle_text(ctx: Ctx) -> None:
    """User ne text likha."""
    current = ctx.session.get("flow_screen", "")

    # "Hi" / "start" / "menu" -> hamesha WELCOME se shuru (GOODBYE ke baad bhi).
    # Input screen wait kar rahi ho to chhod do — wahan "hi" asli jawab ho sakta hai.
    if _is_greeting(ctx.text) and (not current or loader.screen(current).get("type") != "input"):
        _goto(ctx, loader.start_screen())
        return

    # 1. User ne button ka jawab TYPE kiya (click nahi) — jaise "Yes", "haan",
    # "plans". Current screen ke button se match karke waise hi chalao jaise
    # click kiya ho. Yahi hybrid: click ya type, dono barabar.
    # Button match PEHLE — taaki CONFIRM par "yes" button jaaye, search nahi.
    if current:
        matched = loader.match_typed_button(current, ctx.text)
        if matched and _handle_button(ctx, matched):
            return

    # 2. Input screen ka action, ya buttons screen jisme 'input_action' ho
    # (jaise CONFIRM_BUSINESS/BUSINESS_NOT_FOUND par user city/naam type kare
    # to AI nahi, dobara search chale).
    if current:
        s = loader.screen(current)
        action = s["action"] if s.get("type") == "input" else s.get("input_action")
        if action:
            nxt = s["next"] if s.get("type") == "input" else s.get("input_next")
            on_err = s.get("on_error") if s.get("type") == "input" else s.get("input_error")
            res = actions.run(action, ctx)
            if res.to_ai:
                # Action ne kaha "yeh samajh nahi aaya" (jaise ASK_BUSINESS par
                # junk/sawaal) -> AI intent samjhe, mechanical re-prompt nahi.
                _ai_respond(ctx, current)
                return
            if res.stop:
                return
            if res.next_override:
                _goto(ctx, res.next_override, res.params)
            elif res.ok:
                _goto(ctx, nxt, res.params)
            else:
                _goto(ctx, on_err or "SUPPORT", res.params)
            return

    # Maps link kisi bhi screen par bheja -> business search (AI ko mat bhejo,
    # warna "main link access nahi kar sakti" bolta hai). User ko bas business
    # dhoondhna hota hai.
    if actions._MAPS_URL.search(ctx.text):
        res = actions.run("SEARCH_BUSINESS", ctx)
        if res.next_override:
            _goto(ctx, res.next_override, res.params)
        elif res.ok:
            _goto(ctx, "CONFIRM_BUSINESS", res.params)
        else:
            _goto(ctx, "BUSINESS_NOT_FOUND", res.params)
        return

    # Kuch bhi flow se match nahi hua -> AI brain intent samjhe.
    _ai_respond(ctx, current)


def _ai_respond(ctx: Ctx, current: str) -> None:
    """
    AI intent samjhe: clear intent -> us screen par le jao; warna short jawab
    do aur wahi screen ke buttons wapas dikhao.
    """
    from app.ai.fallback import respond

    kind, val = respond(ctx.user_id, ctx.text, ctx.session)

    if kind == "goto":
        _goto(ctx, val)
        return

    wa.send_text(ctx.phone, val)
    save_message(ctx.user_id, "assistant", val)

    if current:
        _send_screen(ctx, current,
                     {**actions._base_params(), **(ctx.session.get("flow_params") or {})})
    else:
        _goto(ctx, loader.start_screen())


def handle(user_id: str, phone: str, text: str = "", button_payload: str = "") -> None:
    """
    Webhook ka entry point.

    button_payload -> deterministic flow
    text           -> input action ya AI fallback
    """
    session = get_session(user_id)

    # Bhasha: default English, user Hindi/regional bole to switch (sticky).
    # Sirf asli text par — button taps main.py mein id ban jaate hain (text="").
    lang = _lang(session)
    if text:
        detected = _detect_lang(text, lang)
        if detected != lang:
            session["lang"] = detected
            save_session(user_id, session)
            lang = detected

    ctx = Ctx(user_id=user_id, phone=phone, session=session,
              lang=lang, text=text)

    if text:
        save_message(user_id, "user", text)

    # User active hai — pending nudges hatao, warna use "aapne jawab nahi
    # diya" wala message reply ke turant baad mil jaayega.
    from app.services.followup_service import cancel as cancel_followups
    cancel_followups(user_id)

    try:
        # PEHLA message (nayi conversation) — chahe user kuch bhi bheje, hamesha
        # WELCOME dikhao. AI jawab nahi. Yeh sirf pehli baar (jab tak koi screen
        # nahi dikhi). flow_screen set hote hi normal routing chalu.
        if not ctx.session.get("flow_screen") and (text or button_payload):
            _goto(ctx, loader.start_screen())
            return

        if button_payload and _handle_button(ctx, button_payload):
            return
        if text:
            _handle_text(ctx)
            return
        # Anjaan button ya khaali message: user ko WELCOME par mat pheinko —
        # jahan tha wahin rakho, warna uski progress gayab ho jaati hai.
        current = ctx.session.get("flow_screen", "")
        _goto(ctx, current or loader.start_screen())
    except Exception as e:
        log.exception("Flow crash user=%s: %s", user_id, e)
        try:
            msg = actions.render(loader.text("error_generic")[ctx.lang],
                                 actions._base_params())
            wa.send_text(phone, msg)
        except Exception:
            log.exception("Error message bhi nahi bhej paye")
