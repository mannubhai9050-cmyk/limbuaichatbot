"""
Dashboard actions — trigger karo, result deliver karo.

Result do raaste se aata hai:
  1. Limbu /webhook/action-complete call kare  (normal)
  2. Poll thread (safety net, agar webhook na aaye)

Dono mein se jo pehle aaye wahi deliver karta hai — dedup Redis mein hai.
"""
import logging
import threading
import time

import httpx

from app.core.config import CHATBOT_ACTION_API, CHATBOT_ACTION_RESULT_API

log = logging.getLogger(__name__)

_POLL_ATTEMPTS = 36
_POLL_EVERY = 5
_DEDUP_TTL = 3600


def _claim(user_id: str, action: str) -> bool:
    """
    Deliver karne ka haq maango. True sirf ek baar milega.

    NOTE: purana code ek in-memory dict (60-second window) use karta tha. 1 se
    zyada worker par woh kaam nahi karta — webhook ek worker mein aata aur poll
    thread doosre mein chalti, dono deliver kar dete, user ko report DO baar
    milti. Redis SET NX atomic hai, saare workers ke liye ek hi sach.
    """
    try:
        from app.services.redis_service import r
        return bool(r.set(f"delivered:{user_id}:{action}", "1", nx=True, ex=_DEDUP_TTL))
    except Exception as e:
        log.warning("Dedup fail (deliver kar rahe hain): %s", e)
        return True


def _unclaim(user_id: str, action: str) -> None:
    try:
        from app.services.redis_service import r
        r.delete(f"delivered:{user_id}:{action}")
    except Exception:
        pass


def trigger_action(action: str, phone: str, location_id: str, email: str, user_id: str) -> dict:
    _unclaim(user_id, action)  # naya request = naya deliver allowed
    try:
        with httpx.Client(timeout=30) as client:
            res = client.post(CHATBOT_ACTION_API, json={
                "action": action, "phone": phone,
                "locationId": location_id, "email": email,
            })
        if res.status_code != 200:
            log.error("Action '%s' HTTP %s", action, res.status_code)
            return {"success": False, "message": f"HTTP {res.status_code}"}

        data = res.json()
        log.info("Action '%s' triggered: success=%s", action, data.get("success"))
        if data.get("success"):
            _start_poll(phone, action, user_id)
        return data
    except Exception as e:
        log.exception("Action '%s' trigger fail: %s", action, e)
        # NOTE: exception text user tak nahi jaana chahiye — usme URL/keys ho sakte hain
        return {"success": False, "message": "trigger failed"}


def _start_poll(phone: str, action: str, user_id: str) -> None:
    threading.Thread(target=_poll_loop, args=(phone, action, user_id), daemon=True).start()


def _poll_loop(phone: str, action: str, user_id: str) -> None:
    for attempt in range(_POLL_ATTEMPTS):
        time.sleep(_POLL_EVERY)
        try:
            with httpx.Client(timeout=15) as client:
                res = client.get(CHATBOT_ACTION_RESULT_API,
                                 params={"phone": phone, "action": action})
            if res.status_code != 200:
                log.info("Result poll '%s' attempt %d: HTTP %s", action, attempt + 1, res.status_code)
                continue
            data = res.json()
            if not data.get("success") or not data.get("result"):
                # Backend ne abhi result nahi banaya — dikhana zaroori hai taaki
                # pata chale bot poll kar raha hai par backend result nahi de raha.
                log.info("Result poll '%s' attempt %d: not ready yet (success=%s, has_result=%s)",
                         action, attempt + 1, data.get("success"), bool(data.get("result")))
                continue
            log.info("Result poll '%s' attempt %d: GOT RESULT -> delivering", action, attempt + 1)
            if _claim(user_id, action):
                deliver(user_id, phone, action, data["result"])
            return
        except Exception as e:
            log.warning("Poll '%s' attempt %d fail: %s", action, attempt + 1, e)
    log.error("Result poll TIMEOUT: action=%s user=%s — backend ne %d×%ds mein result nahi diya",
              action, user_id, _POLL_ATTEMPTS, _POLL_EVERY)


def deliver_from_webhook(user_id: str, phone: str, action: str,
                         result: dict, action_id: str = "") -> None:
    if _claim(user_id, action):
        deliver(user_id, phone, action, result)


# result ke URL kis key mein aate hain — provider consistent nahi hai
_URL_KEYS = {
    "health_score": [("pdf_url", "📄 Full Report (PDF)")],
    "insights": [("pdfUrl", "📄 Full Report (PDF)"), ("pdf_url", "📄 Full Report (PDF)")],
    "magic_qr": [("reviewUrl", "⭐ Google Review Link"), ("review_url", "⭐ Google Review Link"),
                 ("url", "🔮 QR Card"), ("qr_url", "🔮 QR Card")],
    "website": [("url", "🌐 Website URL"), ("website_url", "🌐 Website URL")],
}


def _build_message(action: str, result: dict) -> str:
    parts = []
    text = (result.get("text") or result.get("message") or "").strip()
    if text and text.lower() != "null":
        parts.append(text)

    seen = set()
    for key, label in _URL_KEYS.get(action, []):
        url = (result.get(key) or "").strip()
        if url and url not in seen:
            seen.add(url)
            parts.append(f"{label}:\n{url}")

    return "\n\n".join(parts)


def deliver(user_id: str, phone: str, action: str, result: dict) -> None:
    """Result bhejo, phir user ko wapas flow ke buttons dikhao."""
    from app.flow import engine
    from app.services.redis_service import get_session, save_message
    from app.services.whatsapp_service import send_text

    try:
        msg = _build_message(action, result)
        if not msg:
            log.error("Action '%s' ka result khaali hai: %s", action, result)
            return

        # send pehle, save baad mein: purana code ulta karta tha, isliye Redis
        # mein woh message likha jaata tha jo user tak pahuncha hi nahi.
        if send_text(phone, msg):
            save_message(user_id, "assistant", msg)
        else:
            log.error("Action '%s' ka result bhej nahi paye user=%s", action, user_id)
            return

        session = get_session(user_id)
        ctx = engine.Ctx(user_id=user_id, phone=phone, session=session,
                         lang=session.get("lang", "hi"))

        # Feature chain: is feature ke baad kaunsa screen (jaise health -> QR ka offer).
        # Mapping na mile to REVIEW_DONE (chain ka end) par le jao.
        from app.flow import loader
        next_screen = (loader.features().get("chain") or {}).get(action) or "REVIEW_DONE"
        engine._goto(ctx, next_screen)
        log.info("Delivered '%s' to %s -> %s", action, user_id, next_screen)

    except Exception as e:
        log.exception("Deliver '%s' fail: %s", action, e)
