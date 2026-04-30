import httpx
import threading
import time
from app.core.config import CHATBOT_ACTION_API, CHATBOT_ACTION_RESULT_API


def trigger_action(action: str, phone: str, location_id: str, email: str, user_id: str) -> dict:
    """
    POST to Limbu dashboard to trigger an action.
    Then start background polling for result.
    Actions: health_score | magic_qr | insights | website | review_reply
    """
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
            print(f"[Action] Response {res.status_code}: success={data.get('success')}")

            if data.get("success"):
                _start_poll(phone, action, user_id)

            return data
    except Exception as e:
        print(f"[Action] Trigger error for {action}: {e}")
        return {"success": False, "message": str(e)}


def _start_poll(phone: str, action: str, user_id: str):
    t = threading.Thread(
        target=_poll_loop,
        args=(phone, action, user_id),
        daemon=True
    )
    t.start()
    print(f"[Poll] Started for action={action} user={user_id}")


def _poll_loop(phone: str, action: str, user_id: str):
    """
    Poll GET every 5s, max 3 min (36 attempts).
    GET https://limbu.ai/api/chatbot/action/result?phone=91XXXXXXXXXX&action=health_score

    Response structure:
    {
      "success": true,
      "status": "success",
      "action": "health_score",
      "phone": "917740847114",
      "result": {
        "score": 65,
        "text": "...",       ← pre-formatted text
        "pdf_url": "...",
        "message": "...",
        "data": { ... }
      }
    }
    """
    for attempt in range(36):  # 36 x 5s = 3 min
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
                    print(f"[Poll] Not ready: {data.get('status')}")
                    continue

                result = data.get("result", {})
                if not result:
                    print(f"[Poll] Empty result, waiting...")
                    continue

                # Got result — deliver
                _deliver(user_id, phone, action, result)
                return

        except Exception as e:
            print(f"[Poll] Error attempt {attempt+1}: {e}")
            time.sleep(3)

    print(f"[Poll] Timeout 3min: action={action} user={user_id}")


def _deliver(user_id: str, phone: str, action: str, result: dict):
    """
    Build final message and deliver to Redis + WhatsApp.
    Also appends next feature offer.
    """
    try:
        from app.services.redis_service import save_message
        from app.services.whatsapp_service import send_whatsapp
        from app.services.redis_service import get_session
        from app.nodes.features import FEATURE_NEXT_OFFER

        msg = _build_message(action, result)

        # Append next feature offer — language aware
        sess = get_session(user_id)
        lang = sess.get("lang", "hi") if sess else "hi"
        next_offer_map = FEATURE_NEXT_OFFER.get(action, {})
        if isinstance(next_offer_map, dict):
            next_offer = next_offer_map.get(lang, next_offer_map.get("hi", ""))
        else:
            next_offer = next_offer_map
        if next_offer:
            msg = f"{msg}\n\n━━━━━━━━━━━━━━━━━━━━\n{next_offer}"

        # Save to Redis (dedup handles double-save protection)
        save_message(user_id, "assistant", msg)
        print(f"[Poll] ✅ Saved result to chat: user={user_id} action={action}")

        # Send via WhatsApp
        if phone:
            wa_phone = phone if phone.startswith("91") else "91" + phone
            send_whatsapp(wa_phone, msg)
            print(f"[Poll] ✅ WhatsApp sent to {wa_phone}")

    except Exception as e:
        print(f"[Poll] Deliver error: {e}")
        import traceback
        traceback.print_exc()


def _build_message(action: str, result: dict) -> str:
    """
    Build message from result.
    Uses 'text' field from API (pre-formatted) when available.
    Then appends extra URLs.
    """
    api_text = result.get("text", "").strip()

    if action == "health_score":
        msg = api_text if api_text else f"✅ *GMB Health Report ready hai!*\n\nScore: {result.get('score', 'N/A')}/100"
        pdf = result.get("pdf_url", "")
        if pdf and pdf not in msg:
            msg += f"\n\n📄 *Full PDF Report:*\n{pdf}"

    elif action == "magic_qr":
        msg = api_text if api_text else "✅ *Magic QR ready hai!*"
        qr_url = result.get("url", "") or result.get("qr_url", "") or result.get("qr_image", "")
        review_url = result.get("reviewUrl", "") or result.get("review_url", "")
        if qr_url and qr_url not in msg:
            msg += f"\n\n🔮 *QR Code:*\n{qr_url}"
        if review_url and review_url not in msg:
            msg += f"\n\n⭐ *Review Link:*\n{review_url}"

    elif action == "insights":
        msg = api_text if api_text else "✅ *Google Insights ready hai!*"
        pdf = result.get("pdfUrl", "") or result.get("pdf_url", "")
        if pdf and pdf not in msg:
            msg += f"\n\n📄 *Full Report (PDF):*\n{pdf}"

    elif action == "website":
        msg = api_text if api_text else "✅ *Aapki Free Website ready hai!*"
        url = result.get("url", "") or result.get("website_url", "")
        if url and url not in msg:
            msg += f"\n\n🌐 *Website URL:*\n{url}"

    elif action == "review_reply":
        msg = api_text if api_text else "✅ *Review Reply ready hai!*"
        replies = result.get("replies", [])
        if replies:
            msg += "\n\n*Sample Replies:*"
            for r in replies[:3]:
                msg += f"\n  • {r}"

    else:
        label = action.replace("_", " ").title()
        msg = api_text if api_text else f"✅ *{label} ready hai!*\n\n{result.get('message', '')}"

    return msg.strip()