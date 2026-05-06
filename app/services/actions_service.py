import httpx
import threading
import time
from app.core.config import CHATBOT_ACTION_API, CHATBOT_ACTION_RESULT_API

_delivered: dict = {}
_delivered_lock = threading.Lock()


def _mark_delivered(user_id: str, action: str) -> bool:
    key = f"{user_id}:{action}"
    now = time.time()
    with _delivered_lock:
        last = _delivered.get(key, 0)
        if now - last < 60:
            print(f"[Dedup] Blocked: {key}")
            return False
        _delivered[key] = now
        if len(_delivered) > 500:
            old = [k for k, v in _delivered.items() if now - v > 300]
            for k in old:
                del _delivered[k]
        return True


def trigger_action(action: str, phone: str, location_id: str, email: str, user_id: str) -> dict:
    try:
        with httpx.Client(timeout=30) as client:
            payload = {"action": action, "phone": phone, "locationId": location_id, "email": email}
            print(f"[Action] Triggering '{action}' phone={phone} locationId={location_id}")
            res = client.post(CHATBOT_ACTION_API, json=payload)
            data = res.json()
            print(f"[Action] Response {res.status_code}: success={data.get('success')} msg={data.get('message','')[:80]}")
            if data.get("success"):
                key = f"{user_id}:{action}"
                with _delivered_lock:
                    _delivered.pop(key, None)
                _start_poll(phone, action, user_id)
            return data
    except Exception as e:
        print(f"[Action] Error: {e}")
        return {"success": False, "message": str(e)}


def _start_poll(phone: str, action: str, user_id: str):
    t = threading.Thread(target=_poll_loop, args=(phone, action, user_id), daemon=True)
    t.start()
    print(f"[Poll] Started action={action} user={user_id}")


def _poll_loop(phone: str, action: str, user_id: str):
    for attempt in range(36):
        time.sleep(5)
        try:
            with httpx.Client(timeout=15) as client:
                res = client.get(CHATBOT_ACTION_RESULT_API, params={"phone": phone, "action": action})
                print(f"[Poll] {action} attempt {attempt+1}: HTTP {res.status_code}")
                if res.status_code != 200:
                    continue
                data = res.json()
                if not data.get("success"):
                    continue
                result = data.get("result", {})
                if not result:
                    continue
                if _mark_delivered(user_id, action):
                    _deliver(user_id, phone, action, result)
                return
        except Exception as e:
            print(f"[Poll] Error attempt {attempt+1}: {e}")
            time.sleep(3)
    print(f"[Poll] Timeout: action={action} user={user_id}")


def deliver_from_webhook(user_id: str, phone: str, action: str, result: dict, action_id: str = ""):
    if _mark_delivered(user_id, action):
        _deliver(user_id, phone, action, result)


def _deliver(user_id: str, phone: str, action: str, result: dict):
    try:
        from app.services.redis_service import save_message, get_session
        from app.services.whatsapp_service import send_whatsapp, send_whatsapp_image, send_whatsapp_document
        from app.nodes.features import FEATURE_NEXT_OFFER

        sess = get_session(user_id)
        lang = sess.get("lang", "hi") if sess else "hi"

        # Build text message
        text_msg = _build_text_message(action, result, lang)

        # Next offer
        next_offer_map = FEATURE_NEXT_OFFER.get(action, {})
        next_offer = next_offer_map.get(lang, next_offer_map.get("hi", "")) if isinstance(next_offer_map, dict) else str(next_offer_map)

        wa_phone = phone if phone.startswith("91") else "91" + phone

        # ── Send based on action type ─────────────────────────────
        if action == "health_score":
            # 1. Send text report
            save_message(user_id, "assistant", text_msg)
            send_whatsapp(wa_phone, text_msg)

            # 2. Send PDF as document (separate message)
            pdf_url = result.get("pdf_url", "")
            if pdf_url:
                biz_name = result.get("message", "").replace("Health score report generated for ", "")
                pdf_caption = f"📄 Full Health Report — {biz_name}"
                send_whatsapp_document(wa_phone, pdf_url, f"Health-Report.pdf", pdf_caption)
                save_message(user_id, "assistant", f"📄 Full PDF: {pdf_url}")

        elif action == "magic_qr":
            # 1. Send text with review link
            save_message(user_id, "assistant", text_msg)
            send_whatsapp(wa_phone, text_msg)

            # 2. Send QR as image (separate message)
            qr_url = result.get("url", "") or result.get("qr_url", "")
            if qr_url:
                biz = result.get("message", "").replace("QR code ready for ", "")
                qr_caption = f"🔮 Magic QR Code — {biz}\nScan to leave a Google review!"
                send_whatsapp_image(wa_phone, qr_url, qr_caption)
                save_message(user_id, "assistant", f"🔮 QR Code image: {qr_url}")

        elif action == "insights":
            # 1. Send text insights
            save_message(user_id, "assistant", text_msg)
            send_whatsapp(wa_phone, text_msg)

            # 2. Send PDF
            pdf_url = result.get("pdfUrl", "") or result.get("pdf_url", "")
            if pdf_url:
                send_whatsapp_document(wa_phone, pdf_url, "Performance-Report.pdf", "📊 Full Insights Report")
                save_message(user_id, "assistant", f"📊 Full PDF: {pdf_url}")

        elif action == "website":
            save_message(user_id, "assistant", text_msg)
            send_whatsapp(wa_phone, text_msg)

        elif action == "review_reply":
            save_message(user_id, "assistant", text_msg)
            send_whatsapp(wa_phone, text_msg)

        else:
            save_message(user_id, "assistant", text_msg)
            send_whatsapp(wa_phone, text_msg)

        # Send next offer
        if next_offer:
            time.sleep(1)
            save_message(user_id, "assistant", next_offer)
            send_whatsapp(wa_phone, next_offer)

        print(f"[Poll] Delivered {action} to {user_id}")

    except Exception as e:
        print(f"[Poll] Deliver error: {e}")
        import traceback; traceback.print_exc()


def _build_text_message(action: str, result: dict, lang: str = "hi") -> str:
    api_text = result.get("text", "").strip()

    if action == "health_score":
        if api_text:
            # Clean null services from API text
            import re
            api_text = re.sub(r'🛠️ \*Services:\* null.*?(?=\n\n|\Z)', '', api_text, flags=re.DOTALL)
            api_text = re.sub(r'\*Services:\* (?:null(?:,\s*)?)+.*?\n', '', api_text)
            return api_text.strip()
        score = result.get("score", "N/A")
        return f"✅ *GMB Health Report ready!*\n\nScore: *{score}/100*"

    elif action == "magic_qr":
        review_url = result.get("reviewUrl", "") or result.get("review_url", "")
        if api_text and review_url:
            return f"✅ *Magic QR ready hai!*\n\n⭐ Review Link:\n{review_url}"
        return api_text or "✅ *Magic QR ready hai!*"

    elif action == "insights":
        if api_text:
            return api_text
        return "✅ *Google Insights ready hai!*"

    elif action == "website":
        url = result.get("url", "") or result.get("website_url", "")
        msg = api_text or "✅ *Aapki Free Website ready hai!*"
        if url and url not in msg:
            msg += f"\n\n🌐 *Website URL:*\n{url}"
        return msg

    elif action == "review_reply":
        return api_text or "✅ *Review Reply ready hai!*"

    else:
        return api_text or f"✅ *{action.replace('_',' ').title()} ready hai!*"