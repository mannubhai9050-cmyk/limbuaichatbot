"""
Follow-up nudges — Redis-backed.

PURANA SYSTEM aur uski teen kharabiyan:
  • threading.Timer + daemon=True  -> har deploy/restart par saare pending
    follow-up chup-chaap mar jaate the. Redis mein koi nishan nahi tha ki
    koi follow-up due bhi tha, isliye recover karna namumkin tha.
  • _active_timers ek per-process dict tha -> 1 se zyada worker par, user ke
    reply karne par doosre worker ka timer cancel nahi hota tha. Nateeja:
    "aapne jawab nahi diya" wala nudge reply ke turant baad chala jaata tha.
  • timer thread session ka minutes purana snapshot wapas likh deta tha,
    jisse user ka connect_verified / features_offered roll back ho jaata tha.

NAYA SYSTEM:
  • Due follow-ups ek Redis sorted set mein (score = due timestamp).
  • Sweeper har 30s due wale uthata hai. Uthana ZREM se atomic hai, isliye
    ek nudge sirf EK worker bhejta hai — chahe 10 worker chal rahe hon.
  • Restart ke baad bhi sab queue mein pade rehte hain — kuch nahi khota.
  • Session bhejne ke waqt fresh padha jaata hai, purana snapshot nahi.
"""
import json
import logging
import threading
import time

log = logging.getLogger(__name__)

QUEUE = "followups"
SWEEP_EVERY = 30
MAX_FOLLOWUPS = 2

# kind -> (kitni der baad, kaunsi screen bhejni hai)
# Screen names flows/main.json ke saath match hone chahiye — warna nudge
# fire hone par _goto crash karega.
RULES = {
    "CONNECT_PENDING": (10 * 60, "CONNECT_NOT_YET"),
    "PLAN_PENDING": (60 * 60, "PLANS"),
}

# Re-engagement: user chup ho gaya to 2h aur ~5.5h baad, JIS TOPIC par baat ruki
# thi uska nudge. Har user message par re-arm hota hai (cancel + reschedule).
REENGAGE_DELAYS = {"REENGAGE_2H": 2 * 60 * 60, "REENGAGE_6H": int(5.5 * 60 * 60)}

# flow_screen -> reengage text key. Jo screen yahan nahi, uspar nudge nahi
# (jaise GOODBYE, DEMO_DONE, SUPPORT — inpar re-engage nahi).
_TOPIC = {
    "PLANS": "reengage_plans", "PLAN_DETAIL": "reengage_plans", "REVIEW_DONE": "reengage_plans",
    "CONNECT_ASK": "reengage_connect", "CONNECT_PENDING": "reengage_connect", "CONNECT_NOT_YET": "reengage_connect",
    "ASK_BUSINESS": "reengage_business", "CONFIRM_BUSINESS": "reengage_business",
    "BUSINESS_NOT_FOUND": "reengage_business", "ASK_LINK": "reengage_business", "BUSINESS_RETRY": "reengage_business",
    "HEALTH_DONE": "reengage_features", "QR_DONE": "reengage_features",
    "INSIGHTS_DONE": "reengage_features", "WEBSITE_DONE": "reengage_features", "FEATURES_MENU": "reengage_features",
    "DEMO_ASK_NAME": "reengage_demo", "DEMO_ASK_DAY": "reengage_demo", "DEMO_ASK_TIME": "reengage_demo",
    "ANALYSE_ASK": "reengage_connect", "LATER_MENU": "reengage_plans",
}


def schedule_reengage(user_id: str, phone: str) -> None:
    """2h aur ~5.5h baad topic nudge queue karo (har message par re-arm)."""
    try:
        now = time.time()
        for kind, delay in REENGAGE_DELAYS.items():
            payload = json.dumps({"user_id": user_id, "phone": phone, "kind": kind},
                                 sort_keys=True)
            _r().zadd(QUEUE, {payload: now + delay})
    except Exception as e:
        log.warning("Reengage schedule fail: %s", e)


def _send_reengage(user_id: str, phone: str) -> None:
    """Jis screen par baat ruki, uska topic-aware nudge bhejo."""
    from app.flow import actions, loader
    from app.services.redis_service import get_session
    from app.services.whatsapp_service import send_text

    session = get_session(user_id)
    if not session:
        return
    screen = session.get("flow_screen", "")
    key = _TOPIC.get(screen)
    if not key:
        return   # is topic par re-engage nahi
    # Connect ho chuka to connect nudge nahi — features wala do
    if key == "reengage_connect" and session.get("connect_verified"):
        key = "reengage_features"

    lang = session.get("lang", "en")
    try:
        msg = actions.render(loader.text(key)[lang], actions._base_params())
    except Exception as e:
        log.warning("reengage text fail: %s", e)
        return
    send_text(phone, msg)
    log.info("Reengage sent: %s screen=%s key=%s", user_id, screen, key)


def _r():
    from app.services.redis_service import r
    return r


def schedule(user_id: str, phone: str, kind: str) -> None:
    rule = RULES.get(kind)
    if not rule:
        log.error("Anjaan followup kind: %s", kind)
        return
    delay, _ = rule
    try:
        payload = json.dumps({"user_id": user_id, "phone": phone, "kind": kind},
                             sort_keys=True)
        _r().zadd(QUEUE, {payload: time.time() + delay})
        log.info("Followup scheduled: %s %s (%ds baad)", user_id, kind, delay)
    except Exception as e:
        log.exception("Followup schedule fail: %s", e)


def cancel(user_id: str) -> None:
    """
    User bol pada — uske saare pending nudges hatao.

    Purane code se ulta, yeh SAARE workers ke liye kaam karta hai, kyunki
    queue Redis mein hai, kisi process ki memory mein nahi.
    """
    try:
        r = _r()
        for raw in r.zrange(QUEUE, 0, -1):
            try:
                if json.loads(raw).get("user_id") == user_id:
                    r.zrem(QUEUE, raw)
            except Exception:
                continue
    except Exception as e:
        log.warning("Followup cancel fail: %s", e)


def _send(item: dict) -> None:
    from app.flow import engine
    from app.services.redis_service import get_session, save_session

    user_id, phone, kind = item["user_id"], item["phone"], item["kind"]

    # Re-engagement (2h / 5-6h) — topic-aware nudge
    if kind in REENGAGE_DELAYS:
        _send_reengage(user_id, phone)
        return

    # Purani/stale queue entry (flow badalne ke baad) — chup-chaap chhod do.
    if kind not in RULES:
        log.info("Followup skip (unknown kind '%s')", kind)
        return

    # Session ab padha ja raha hai — schedule ke waqt ka purana snapshot nahi.
    session = get_session(user_id)

    if session.get("followup_count", 0) >= MAX_FOLLOWUPS:
        log.info("Followup skip (limit): %s", user_id)
        return

    # Jo kaam ho chuka, uska nudge mat bhejo
    if kind == "CONNECT_PENDING" and session.get("connect_verified"):
        return
    if kind == "FEATURE_PENDING" and session.get("features_offered"):
        return

    session["followup_count"] = session.get("followup_count", 0) + 1
    save_session(user_id, session)

    _, screen = RULES[kind]
    ctx = engine.Ctx(user_id=user_id, phone=phone, session=session,
                     lang=session.get("lang", "hi"))
    engine._goto(ctx, screen)
    log.info("Followup sent: %s %s -> %s", user_id, kind, screen)


def sweep_once() -> int:
    """Due follow-ups bhejo. Bheje gaye count return karta hai."""
    r = _r()
    sent = 0
    for raw in r.zrangebyscore(QUEUE, 0, time.time()):
        # ZREM atomic hai: 1 sirf usi worker ko milega jisne pehle uthaya.
        # Yahi duplicate nudges rokta hai.
        if not r.zrem(QUEUE, raw):
            continue
        try:
            _send(json.loads(raw))
            sent += 1
        except Exception as e:
            log.exception("Followup send fail: %s", e)
    return sent


def _sweeper() -> None:
    while True:
        time.sleep(SWEEP_EVERY)
        try:
            sweep_once()
        except Exception as e:
            log.warning("Followup sweep fail: %s", e)


_started = False


def start_sweeper() -> None:
    """App startup par ek baar. Thread mar bhi jaaye to queue Redis mein safe hai."""
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_sweeper, daemon=True, name="followup-sweeper").start()
    log.info("Followup sweeper started (har %ds)", SWEEP_EVERY)
