"""
Flow actions — screen aur asli kaam ke beech ka pul.

Har action ek Result deta hai:
  ok=True  -> screen ka 'next'
  ok=False -> screen ka 'on_error' (aur user ko sach bataya jaata hai)

Yahan koi user-facing text hardcode nahi hai — sab flows/main.json se.
"""
import logging
import re
from dataclasses import dataclass, field

import httpx

from app.core.config import (
    LIMBU_API_BASE, LIMBU_CONNECT_URL, SUPPORT_PHONE, SUPPORT_EMAIL,
)
from app.flow import loader
from app.services import whatsapp_service as wa
from app.services.redis_service import save_session

log = logging.getLogger(__name__)

_HTTP_TIMEOUT = 15


@dataclass
class Ctx:
    user_id: str
    phone: str
    session: dict
    lang: str = "hi"
    text: str = ""        # user ne jo likha (input screens ke liye)
    button_id: str = ""   # kaunsa button dabaya


@dataclass
class Result:
    ok: bool = True
    params: dict = field(default_factory=dict)  # screen body ke {{...}} ke liye
    next_override: str = ""                     # flow ka 'next' badalna ho to
    stop: bool = False                          # yahin ruko — result baad mein async aayega


def render(tpl: str, params: dict) -> str:
    out = tpl
    for k, v in params.items():
        out = out.replace("{{" + k + "}}", str(v))
    return out


def _t(key: str, lang: str, params: dict) -> str:
    return render(loader.text(key)[lang], params)


def _base_params() -> dict:
    return {"support_phone": SUPPORT_PHONE, "support_email": SUPPORT_EMAIL}


def _place_params(place: dict) -> dict:
    rating = place.get("rating")
    count = place.get("userRatingCount", 0)
    return {
        "biz_name": place.get("displayName", {}).get("text", ""),
        "biz_address": place.get("formattedAddress", ""),
        "biz_rating": f"{rating}/5 ({count} reviews)" if rating else "No rating yet",
        "review_count": count,
        "photo_count": len(place.get("photos", []) or []),
    }


# ── SEARCH_BUSINESS ───────────────────────────────────────────────
_MAPS_URL = re.compile(
    r"https?://(?:maps\.app\.goo\.gl|maps\.google\.com|www\.google\.com/maps|"
    r"goo\.gl/maps|share\.google|g\.co)/\S+"
)


def _query_from_maps_url(url: str) -> str:
    """Maps link se business ka naam nikaalo (short link resolve karke)."""
    import urllib.parse

    resolved = url
    try:
        with httpx.Client(timeout=10, follow_redirects=True) as c:
            resolved = str(c.get(url).url)
    except Exception as e:
        log.warning("Maps link resolve fail: %s", e)

    m = re.search(r"[?&]q=([^&]+)", resolved)
    if m:
        return urllib.parse.unquote_plus(m.group(1))
    m = re.search(r"/place/([^/@?]+)", resolved)
    if m:
        return urllib.parse.unquote_plus(m.group(1)).replace("+", " ")
    return ""


def _run_search(ctx: Ctx, query: str) -> Result:
    """Google Places par query search karo aur pehla result CONFIRM_BUSINESS ko do."""
    from app.services.google_places import search_places

    if len(query) < 3:
        return Result(ok=False)

    try:
        places = search_places(query, "", page_size=5)
    except Exception as e:
        log.exception("Places search fail: %s", e)
        return Result(ok=False)

    if not places:
        return Result(ok=False)

    ctx.session["search_places"] = places
    ctx.session["result_index"] = 0
    ctx.session["found_place"] = places[0]
    ctx.session.pop("pending_biz_name", None)
    save_session(ctx.user_id, ctx.session)
    return Result(params=_place_params(places[0]))


def search_business(ctx: Ctx) -> Result:
    """
    User ne business bheja (naam, ya naam+city, ya Maps link).

    Pehle JO DIYA usi se search karo. Mil gaya -> dikhao. Kuch na mile -> TAB
    city poocho (ASK_CITY).

    NOTE: pehle comma se decide karte the ki city di ya nahi — galat tha.
    'RO Care India Gurgaon' mein city thi par comma nahi, to code city poochta
    tha aur user chidh jaata tha. Ab search khud decide karta hai: agar Places
    ko mil gaya to city thi hi (poori info thi); nahi mili tabhi poochte hain.
    """
    query = ctx.text.strip()

    maps_link = _MAPS_URL.search(query)
    if maps_link:
        q = _query_from_maps_url(maps_link.group(0).rstrip(".,!?)"))
        if not q:
            return Result(ok=False)
        log.info("Maps link -> query: %s", q)
        return _run_search(ctx, q)

    res = _run_search(ctx, query)
    if res.ok:
        return res

    # Kuch nahi mila -> ho sakta hai city missing thi. Ab city poocho.
    ctx.session["pending_biz_name"] = query
    save_session(ctx.user_id, ctx.session)
    return Result(next_override="ASK_CITY")


def search_with_city(ctx: Ctx) -> Result:
    """ASK_CITY se city aayi — pending business naam ke saath jodkar search."""
    name = ctx.session.get("pending_biz_name", "").strip()
    city = ctx.text.strip()
    if not name:
        return Result(ok=False, next_override="ASK_BUSINESS")
    return _run_search(ctx, f"{name}, {city}")


def next_result(ctx: Ctx) -> Result:
    """'Nahi, doosra' — agla search result dikhao."""
    places = ctx.session.get("search_places") or []
    idx = ctx.session.get("result_index", 0) + 1

    if idx >= len(places):
        return Result(ok=False, next_override="BUSINESS_NOT_FOUND")

    ctx.session["result_index"] = idx
    ctx.session["found_place"] = places[idx]
    save_session(ctx.user_id, ctx.session)
    return Result(params=_place_params(places[idx]))


# ── ANALYSE ───────────────────────────────────────────────────────
def analyse(ctx: Ctx) -> Result:
    """
    Confirmed business ka poora health report — profile completion, SEO,
    review rate, reply rate, overall score /100.

    User: 'jaise pehle nikalta tha wo hi use karo'. Isliye purana rich report
    (nodes/analyse.py ka handle_analyse) reuse kar rahe hain — nayi minimal
    wali nahi.
    """
    from app.nodes.analyse import handle_analyse
    from app.services.redis_service import get_session

    # BIZ_YES ka matlab hi business confirm — handle_analyse yahi expect karta hai
    ctx.session["confirmed"] = True
    save_session(ctx.user_id, ctx.session)

    report = ""
    if ctx.session.get("found_place"):
        try:
            report = handle_analyse(ctx.user_id, ctx.session)
        except Exception as e:
            log.exception("Analyse fail: %s", e)

    # Report ab ALAG text nahi jaata — CONNECT_ASK ki body ban kar buttons ke
    # SAATH jaata hai (user: 'analyse report me hi button aaye'). Fail ho to
    # ek chhota fallback.
    if not report:
        report = loader.text("analyse_fallback")[ctx.lang]

    # WhatsApp interactive body limit 1024 — bahut lamba ho to CTA line trim
    if len(report) > 1000:
        report = report[:1000].rstrip() + " …"

    ctx.session = get_session(ctx.user_id)  # handle_analyse ne 'analysis' likha
    return Result(params={"report": report})


# ── CONNECT ───────────────────────────────────────────────────────
def send_connect_link(ctx: Ctx) -> Result:
    # phone URL ke aakhir mein — saaf rehta hai aur dynamic-URL convention ke saath.
    url = f"{LIMBU_CONNECT_URL}?source=chatbot&phone={ctx.phone}"
    ctx.session["connect_link_sent"] = True
    save_session(ctx.user_id, ctx.session)

    # Video pehle (Connect Business dabane ke baad) — CONNECT_SEND screen ke
    # media se. Yahi ek jagah video URL badalna hai.
    media = loader.screen("CONNECT_SEND").get("media")
    if media and loader.media_ready(media):
        wa.send_media(ctx.phone, media["type"], media["url"])

    # URL button: tap par browser mein connect link khulta hai — koi ganda
    # URL text nahi. Session message hai, koi template/approval nahi.
    body = _t("connect_body", ctx.lang, {})
    btn = loader.text("connect_button")[ctx.lang]
    ok = wa.send_url_button(ctx.phone, body, btn, url)

    # Purane bot jaisa — background polling. User ko "Done" dabana nahi padta;
    # connect hote hi bot khud pata laga kar report bhej deta hai.
    _start_connection_poll(ctx.user_id, ctx.phone, ctx.lang)
    return Result(ok=ok, params={"connect_url": url})


def _start_connection_poll(user_id: str, phone: str, lang: str) -> None:
    import threading
    threading.Thread(target=_poll_connection, args=(user_id, phone, lang),
                     daemon=True).start()
    log.info("Connection poll started user=%s", user_id)


def verify_and_start(user_id: str, phone: str, lang: str = "en") -> bool:
    """
    gmb/status check karo; connect ho gaya to 'connected' message + auto full
    health report (CONNECT_SUCCESS -> START_HEALTH). True agar connect ho gaya.

    Poll aur webhook/connected dono yahi call karte hain. check_connection aur
    start_health dono guarded hain, isliye double message/report nahi hoga.
    """
    from app.services.redis_service import get_session

    session = get_session(user_id)
    if not session:
        return False
    ctx = Ctx(user_id=user_id, phone=phone, session=session,
              lang=session.get("lang", lang))
    res = check_connection(ctx)
    if not res.ok:
        return False
    from app.flow import engine
    engine._goto(ctx, "CONNECT_SUCCESS")  # auto health report
    return True


def _poll_connection(user_id: str, phone: str, lang: str) -> None:
    """Har 3s gmb/status check — connect hote hi khud report chalu."""
    import time

    from app.services.redis_service import get_session

    for attempt in range(100):  # ~5 min
        time.sleep(3)
        try:
            session = get_session(user_id)
            if not session:
                return
            if session.get("connect_verified"):
                return  # webhook ya manual ne pehle handle kar liya
            if verify_and_start(user_id, phone, lang):
                log.info("Poll: connected user=%s (attempt %d)", user_id, attempt + 1)
                return
        except Exception as e:
            log.warning("Conn poll error user=%s: %s", user_id, e)
    log.info("Conn poll timeout user=%s — connect nahi hua", user_id)


def check_connection(ctx: Ctx) -> Result:
    """
    Limbu se poocho ki GMB connect hua ya nahi.

    NOTE: purana code yahan background thread se 100 baar poll karta tha.
    Ab user button dabata hai to check hota hai — na thread, na restart par gayab.
    """
    try:
        res = httpx.get(f"{LIMBU_API_BASE}/gmb/status",
                        params={"phone": ctx.phone}, timeout=_HTTP_TIMEOUT)
        if res.status_code != 200:
            log.error("gmb/status HTTP %s", res.status_code)
            return Result(ok=False)
        data = res.json()
    except Exception as e:
        log.exception("gmb/status fail: %s", e)
        return Result(ok=False)

    if not (data.get("status") == "success" or data.get("success")):
        return Result(ok=False)   # abhi connect nahi hua -> CONNECT_NOT_YET

    # Pehle se verified? (poll aur webhook dono fire ho sakte hain) — dobara
    # "connected" message mat bhejo.
    already = ctx.session.get("connect_verified")

    locations = data.get("locationsData") or data.get("businesses") or []
    ctx.session["connect_verified"] = True
    ctx.session["connected_email"] = data.get("email", "")
    ctx.session["connected_businesses"] = locations
    if locations:
        first = locations[0]
        ctx.session["active_business_name"] = first.get("title", "")
        ctx.session["active_location_id"] = (
            first.get("locationResourceName") or first.get("locationId") or ""
        )
    save_session(ctx.user_id, ctx.session)

    if not already:
        biz_list = "\n".join(f"• {b.get('title', '')}" for b in locations[:10])
        wa.send_text(ctx.phone, _t("connected", ctx.lang, {"biz_list": biz_list}))
    return Result()


# ── FEATURES ──────────────────────────────────────────────────────
def start_health(ctx: Ctx) -> Result:
    """
    Connect hone ke baad Full Health Report AUTO trigger — user ke button
    dabaye bina. trigger_feature button_id se feature dhoondhta hai, isliye
    yahan VIEW_HEALTH set kar dete hain.

    Guard: poll aur webhook dono connect detect kar sakte hain — health sirf
    EK baar trigger ho.
    """
    if ctx.session.get("health_started"):
        return Result(stop=True)
    ctx.session["health_started"] = True
    save_session(ctx.user_id, ctx.session)
    ctx.button_id = "VIEW_HEALTH"
    return trigger_feature(ctx)


def trigger_feature(ctx: Ctx) -> Result:
    from app.services.actions_service import trigger_action

    feats = loader.features()
    feature = (feats.get("map") or {}).get(ctx.button_id)
    if not feature:
        log.error("button '%s' ka koi feature mapping nahi", ctx.button_id)
        return Result(ok=False)

    if not ctx.session.get("connect_verified"):
        return Result(ok=False, next_override="CONNECT_ASK")

    label_i18n = (feats.get("labels") or {}).get(feature, {})
    label = label_i18n.get(ctx.lang) or label_i18n.get("hi") or feature
    wa.send_text(ctx.phone, _t("feature_wait", ctx.lang, {"feature_label": label}))

    try:
        res = trigger_action(
            action=feature,
            phone=ctx.phone,
            location_id=ctx.session.get("active_location_id", ""),
            email=ctx.session.get("connected_email", ""),
            user_id=ctx.user_id,
        )
    except Exception as e:
        log.exception("trigger_action fail: %s", e)
        return Result(ok=False)

    if not res.get("success"):
        log.error("Feature '%s' trigger fail: %s", feature, res.get("message"))
        return Result(ok=False)

    offered = ctx.session.get("features_offered") or []
    if feature not in offered:
        offered.append(feature)
    ctx.session["features_offered"] = offered
    save_session(ctx.user_id, ctx.session)

    # Yahin ruko. Result async aayega (webhook ya poll se) — tab
    # actions_service.deliver() user ko FEATURE_DONE par le jaayega.
    # Abhi FEATURE_DONE bhej diya to "aur kuch dekhna hai?" report se
    # PEHLE pahunch jaayega.
    return Result(stop=True, params={"feature_label": label})


# ── PLANS ─────────────────────────────────────────────────────────
def load_plan(ctx: Ctx) -> Result:
    """
    Plan detail ek hi jagah se — plans API/service se.

    NOTE: pehle price 4 files mein hardcoded thi aur aapas mein alag thi
    (KB ₹3,500 vs baaki ₹2,500). Ab sirf yahi ek source hai.
    """
    from app.services.plans_service import get_plan_by_name

    screen = loader.screen("PLAN_DETAIL")
    plan_key = (screen.get("plan_map") or {}).get(ctx.button_id, "")
    if not plan_key:
        return Result(ok=False)

    try:
        plan = get_plan_by_name(plan_key)
    except Exception as e:
        log.exception("Plan load fail: %s", e)
        return Result(ok=False)

    if not plan:
        return Result(ok=False)

    ctx.session["selected_plan"] = plan_key
    save_session(ctx.user_id, ctx.session)

    feats = plan.get("features") or []
    return Result(params={
        "plan_title": plan.get("title", ""),
        "plan_price": plan.get("basePrice", ""),
        "plan_gst": plan.get("gst", ""),
        "plan_total": plan.get("totalAmount", ""),
        "plan_posts": plan.get("posts", ""),
        "plan_citations": plan.get("citations", ""),
        "plan_features": "\n".join(f"✅ {f}" for f in feats),
    })


def send_payment_link(ctx: Ctx) -> Result:
    from app.services.plans_service import get_plan_by_name

    plan_key = ctx.session.get("selected_plan", "")
    plan = get_plan_by_name(plan_key) if plan_key else None
    if not plan or not plan.get("paymentLink"):
        return Result(ok=False)

    url = f"{plan['paymentLink']}&phone={ctx.phone}"
    wa.send_text(ctx.phone, _t("payment_link", ctx.lang,
                               {"plan_title": plan.get("title", ""), "payment_url": url}))
    return Result()


# ── FRANCHISE ─────────────────────────────────────────────────────
def register_franchise(ctx: Ctx) -> Result:
    """
    NOTE: purana code fail hone par bhi user ko "Registration ho gaya" bolta tha
    aur session mein registered=True likh deta tha — lead chup-chaap gayab.
    Ab fail hone par ok=False -> FRANCHISE_FAILED screen, jo sach bolti hai.
    """
    raw = ctx.text.strip()
    if len(raw) < 3:
        return Result(ok=False)

    parts = [p.strip() for p in raw.replace("\n", ",").split(",") if p.strip()]
    name = parts[0] if parts else raw
    city = parts[1] if len(parts) > 1 else ""

    payload = {"name": name, "phone": ctx.phone, "city": city, "source": "chatbot"}
    try:
        res = httpx.post(f"{LIMBU_API_BASE}/franchise", json=payload, timeout=_HTTP_TIMEOUT)
        ok = res.status_code in (200, 201)
        if ok:
            try:
                body = res.json()
                if isinstance(body, dict) and body.get("success") is False:
                    ok = False  # 200 aaya par body ne mana kiya
            except Exception:
                pass
    except Exception as e:
        log.exception("Franchise register fail: %s", e)
        ok = False

    if not ok:
        log.error("FRANCHISE LEAD LOST — name=%s city=%s phone=%s", name, city, ctx.phone[-4:])
        return Result(ok=False)

    ctx.session["franchise_registered"] = True
    save_session(ctx.user_id, ctx.session)
    return Result(params={"name": name, "city": city})


# ── SOCIAL (Facebook / Instagram / YouTube / LinkedIn) ────────────
def _platform(ctx: Ctx) -> tuple:
    """(key, config) — button se ya session se."""
    from app.core.config import SOCIAL_PLATFORMS

    screen = loader.screen("SOCIAL_LINK")
    key = (screen.get("platform_map") or {}).get(ctx.button_id, "")
    key = key or ctx.session.get("social_platform", "")
    return key, SOCIAL_PLATFORMS.get(key, {})


def send_social_link(ctx: Ctx) -> Result:
    key, cfg = _platform(ctx)
    if not cfg:
        log.error("Anjaan social platform: button=%s", ctx.button_id)
        return Result(ok=False)

    ctx.session["social_platform"] = key
    ctx.session[f"{key}_link_sent"] = True
    save_session(ctx.user_id, ctx.session)

    url = f"{cfg['connect_url']}&phone={ctx.phone}" if "?" in cfg["connect_url"] \
        else f"{cfg['connect_url']}?phone={ctx.phone}"
    wa.send_text(ctx.phone, _t("social_link", ctx.lang,
                               {"platform_name": cfg["name"], "social_url": url}))
    return Result(params={"platform_name": cfg["name"]})


def check_social(ctx: Ctx) -> Result:
    """
    NOTE: purana code har link bhejne par ek nayi polling thread khol deta tha
    (5 baar 'facebook' likha = 5 threads = 5 duplicate message). Ab user button
    dabata hai tabhi check hota hai — koi thread nahi.
    """
    from app.core.config import LIMBU_META_STATUS_API

    key, cfg = _platform(ctx)
    if not cfg:
        return Result(ok=False)

    params = {"platform_name": cfg["name"], "page_name": ""}
    try:
        res = httpx.get(LIMBU_META_STATUS_API,
                        params={"phone": ctx.phone, "type": cfg["status_type"]},
                        timeout=_HTTP_TIMEOUT)
        if res.status_code != 200:
            return Result(ok=False, params=params)
        data = res.json()
    except Exception as e:
        log.exception("Social status fail: %s", e)
        return Result(ok=False, params=params)

    if not (data.get("connected") or data.get("success")):
        return Result(ok=False, params=params)

    page = data.get(cfg.get("page_key", "pageName"), "") or ""
    ctx.session[f"{key}_verified"] = True
    ctx.session[f"{key}_page"] = page
    save_session(ctx.user_id, ctx.session)

    params["page_name"] = page
    return Result(params=params)


# ── LOCATION SWITCH ───────────────────────────────────────────────
def switch_location(ctx: Ctx) -> Result:
    """Dynamic list se location chuni gayi (LOC_0, LOC_1, ...)."""
    dyn = loader.screen("BIZ_LIST")["dynamic_rows"]
    try:
        idx = int(ctx.button_id[len(dyn["id_prefix"]):])
    except ValueError:
        return Result(ok=False)

    items = ctx.session.get(dyn["source"]) or []
    if idx >= len(items):
        return Result(ok=False, next_override="BIZ_LIST")

    b = items[idx]
    ctx.session["active_business_name"] = b.get("title", "")
    ctx.session["active_location_id"] = (
        b.get("locationResourceName") or b.get("locationId") or b.get("id") or ""
    )
    ctx.session["features_offered"] = []  # nayi location = features dobara
    save_session(ctx.user_id, ctx.session)
    return Result(params={"active_business": b.get("title", "")})


# ── DEMO BOOKING ──────────────────────────────────────────────────
def demo_save_name(ctx: Ctx) -> Result:
    name = ctx.text.strip()
    if len(name) < 2:
        return Result(ok=False)
    ctx.session["demo_name"] = name
    save_session(ctx.user_id, ctx.session)
    return Result(params={"demo_name": name})


def _demo_date(offset: int) -> tuple:
    """(YYYY-MM-DD, label) — IST mein."""
    from datetime import datetime, timedelta

    import pytz

    from app.core.config import TIMEZONE

    d = datetime.now(pytz.timezone(TIMEZONE)) + timedelta(days=offset)
    return d.strftime("%Y-%m-%d"), d.strftime("%A, %d %b")


def demo_save_date(ctx: Ctx) -> Result:
    screen = loader.screen("DEMO_ASK_TIME")
    offset = (screen.get("date_map") or {}).get(ctx.button_id)
    if offset is None:
        return Result(ok=False)

    date_str, label = _demo_date(offset)
    ctx.session["demo_date"] = date_str
    ctx.session["demo_date_label"] = label
    save_session(ctx.user_id, ctx.session)
    return Result(params={"demo_date_label": label, "demo_name": ctx.session.get("demo_name", "")})


def book_demo(ctx: Ctx) -> Result:
    """
    NOTE: purana code date validate hi nahi karta tha — date_extractor parse
    fail hone par `return True` ('future hai') kar deta tha, aur booking API
    fail hone par bhi user ko 'booked' bol deta tha. Ab dono sach hain.
    """
    screen = loader.screen("DEMO_CONFIRM")
    time_str = (screen.get("time_map") or {}).get(ctx.button_id, "")
    if not time_str:
        return Result(ok=False)

    name = ctx.session.get("demo_name", "")
    date_str = ctx.session.get("demo_date", "")
    label = ctx.session.get("demo_date_label", "")
    if not (name and date_str):
        return Result(ok=False)

    payload = {"name": name, "phone": ctx.phone, "date": date_str,
               "time": time_str, "source": "chatbot"}
    try:
        res = httpx.post(f"{LIMBU_API_BASE}/demo/book", json=payload, timeout=_HTTP_TIMEOUT)
        ok = res.status_code in (200, 201)
        if ok:
            try:
                body = res.json()
                if isinstance(body, dict) and body.get("success") is False:
                    ok = False
            except Exception:
                pass
    except Exception as e:
        log.exception("Demo booking fail: %s", e)
        ok = False

    if not ok:
        log.error("DEMO BOOKING LOST — name=%s date=%s %s phone=%s",
                  name, date_str, time_str, ctx.phone[-4:])
        return Result(ok=False)

    ctx.session["demo_time"] = time_str
    ctx.session["demo_booked"] = True
    save_session(ctx.user_id, ctx.session)
    return Result(params={"demo_date_label": label, "demo_time": time_str})


# ── Registry ──────────────────────────────────────────────────────
ACTIONS = {
    "SEARCH_BUSINESS": search_business,
    "SEARCH_WITH_CITY": search_with_city,
    "NEXT_RESULT": next_result,
    "ANALYSE": analyse,
    "START_HEALTH": start_health,
    "SEND_CONNECT_LINK": send_connect_link,
    "CHECK_CONNECTION": check_connection,
    "TRIGGER_FEATURE": trigger_feature,
    "LOAD_PLAN": load_plan,
    "SEND_PAYMENT_LINK": send_payment_link,
    "REGISTER_FRANCHISE": register_franchise,
    "SEND_SOCIAL_LINK": send_social_link,
    "CHECK_SOCIAL": check_social,
    "SWITCH_LOCATION": switch_location,
    "DEMO_SAVE_NAME": demo_save_name,
    "DEMO_SAVE_DATE": demo_save_date,
    "BOOK_DEMO": book_demo,
}


def run(name: str, ctx: Ctx) -> Result:
    fn = ACTIONS.get(name)
    if not fn:
        log.error("Action '%s' registered nahi hai", name)
        return Result(ok=False)
    try:
        return fn(ctx)
    except Exception as e:
        log.exception("Action '%s' crash: %s", name, e)
        return Result(ok=False)
