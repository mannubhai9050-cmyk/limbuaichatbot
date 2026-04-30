import httpx
import threading
import time
from app.core.config import CHATBOT_ACTION_API, CHATBOT_ACTION_RESULT_API

# Track delivered action IDs to prevent duplicate delivery
_delivered: set = set()


def trigger_action(action: str, phone: str, location_id: str, email: str, user_id: str) -> dict:
    """POST to Limbu dashboard to trigger an action, then start polling."""
    try:
        with httpx.Client(timeout=30) as client:
            payload = {
                "action": action,
                "phone": phone,
                "locationId": location_id,
                "email": email
            }
            print(f"[Action] Triggering '{action}' phone={phone} locationId={location_id}")
            res = client.post(CHATBOT_ACTION_API, json=payload)
            data = res.json()
            print(f"[Action] Response {res.status_code}: success={data.get('success')} msg={data.get('message','')[:60]}")

            if data.get("success"):
                _start_poll(phone, action, user_id)

            return data
    except Exception as e:
        print(f"[Action] Trigger error: {e}")
        return {"success": False, "message": str(e)}


def _start_poll(phone: str, action: str, user_id: str):
    t = threading.Thread(target=_poll_loop, args=(phone, action, user_id), daemon=True)
    t.start()
    print(f"[Poll] Started action={action} user={user_id}")


def _poll_loop(phone: str, action: str, user_id: str):
    """Poll every 5s, max 3 min. Dedup by actionId."""
    for attempt in range(36):
        time.sleep(5)
        try:
            with httpx.Client(timeout=15) as client:
                res = client.get(
                    CHATBOT_ACTION_RESULT_API,
                    params={"phone": phone, "action": action}
                )
                print(f"[Poll] {action} attempt {attempt+1}: HTTP {res.status_code}")
                if res.status_code != 200:
                    continue
                data = res.json()
                if not data.get("success"):
                    continue
                result = data.get("result", {})
                if not result:
                    continue

                # Dedup by actionId
                action_id = data.get("actionId", "")
                dedup_key = f"{user_id}:{action}:{action_id}"
                if dedup_key in _delivered:
                    print(f"[Poll] Already delivered {dedup_key}, skipping")
                    return
                _delivered.add(dedup_key)
                if len(_delivered) > 1000:
                    _delivered.clear()

                _deliver(user_id, phone, action, result, action_id)
                return

        except Exception as e:
            print(f"[Poll] Error attempt {attempt+1}: {e}")
            time.sleep(3)

    print(f"[Poll] Timeout: action={action} user={user_id}")


def deliver_from_webhook(user_id: str, phone: str, action: str, result: dict, action_id: str = ""):
    """Called from webhook/action-complete — checks dedup before delivering."""
    dedup_key = f"{user_id}:{action}:{action_id}"
    if action_id and dedup_key in _delivered:
        print(f"[Webhook Action] Already delivered {dedup_key}, skipping")
        return
    if action_id:
        _delivered.add(action_id)
    _deliver(user_id, phone, action, result, action_id)


def _deliver(user_id: str, phone: str, action: str, result: dict, action_id: str = ""):
    """Build message and deliver to Redis + WhatsApp."""
    try:
        from app.services.redis_service import save_message, get_session
        from app.services.whatsapp_service import send_whatsapp
        from app.nodes.features import FEATURE_NEXT_OFFER

        msg = _build_message(action, result)

        # Language-aware next offer
        sess = get_session(user_id)
        lang = sess.get("lang", "hi") if sess else "hi"
        next_offer_map = FEATURE_NEXT_OFFER.get(action, {})
        if isinstance(next_offer_map, dict):
            next_offer = next_offer_map.get(lang, next_offer_map.get("hi", ""))
        else:
            next_offer = str(next_offer_map)

        if next_offer:
            msg = f"{msg}\n\n━━━━━━━━━━━━━━━━━━━━\n{next_offer}"

        save_message(user_id, "assistant", msg)
        print(f"[Poll] ✅ Delivered {action} to {user_id}")

        if phone:
            wa_phone = phone if phone.startswith("91") else "91" + phone
            send_whatsapp(wa_phone, msg)
            print(f"[Poll] ✅ WhatsApp sent to {wa_phone}")

    except Exception as e:
        print(f"[Poll] Deliver error: {e}")
        import traceback; traceback.print_exc()


def _build_message(action: str, result: dict) -> str:
    """Use pre-formatted 'text' from API, then append extra URLs."""
    api_text = result.get("text", "").strip()

    if action == "health_score":
        msg = api_text if api_text else f"✅ *GMB Health Report ready hai!*"
        # Clean up null services
        if "null" in msg:
            import re
            msg = re.sub(r'(?:null(?:,\s*)?)+\+?\d*\s*more', '', msg)
            msg = re.sub(r'\*Services:\*\s*\n', '', msg)
            msg = msg.strip()
        pdf = result.get("pdf_url", "")
        if pdf and pdf not in msg:
            msg += f"\n\n📄 *Full PDF Report:*\n{pdf}"

    elif action == "magic_qr":
        msg = api_text if api_text else "✅ *Magic QR ready hai!*"
        qr_url = result.get("url", "") or result.get("qr_url", "")
        review_url = result.get("reviewUrl", "") or result.get("review_url", "")
        if qr_url and qr_url not in msg:
            msg += f"\n\n🔮 *QR Code:*\n{qr_url}"
        if review_url and review_url not in msg:
            msg += f"\n⭐ *Review Link:*\n{review_url}"

    elif action == "insights":
        msg = api_text if api_text else "✅ *Google Insights ready hai!*"
        pdf = result.get("pdfUrl", "") or result.get("pdf_url", "")
        if pdf and pdf not in msg:
            msg += f"\n\n📄 *Full Report (PDF):*\n{pdf}"

    elif action == "website":
        url = result.get("url", "") or result.get("website_url", "")
        if api_text:
            msg = api_text
        else:
            msg = f"✅ *Aapki Free Website ready hai!*"
        if url and url not in msg:
            msg += f"\n\n🌐 *Website URL:*\n{url}"

    elif action == "review_reply":
        msg = api_text if api_text else "✅ *Review Reply ready hai!*"

    else:
        label = action.replace("_", " ").title()
        msg = api_text if api_text else f"✅ *{label} ready hai!*"

    return msg.strip()