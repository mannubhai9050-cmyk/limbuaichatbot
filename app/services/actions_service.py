import httpx
import threading
import time
from app.core.config import CHATBOT_ACTION_API, CHATBOT_ACTION_RESULT_API


def trigger_action(action: str, phone: str, location_id: str, email: str) -> dict:
    """Trigger Limbu.ai dashboard action"""
    try:
        with httpx.Client(timeout=30) as client:
            payload = {
                "action": action,
                "phone": phone,
                "locationId": location_id,
                "email": email
            }
            print(f"[Action] Triggering {action} phone={phone}")
            res = client.post(CHATBOT_ACTION_API, json=payload)
            print(f"[Action] Response {res.status_code}: {res.text[:300]}")
            data = res.json()

            # Start polling for result
            if data.get("success"):
                _poll_action_result(phone, action)

            return data
    except Exception as e:
        print(f"[Action] Error: {e}")
        return {"success": False, "message": str(e)}


def _poll_action_result(phone: str, action: str):
    """Poll GET API every 5 sec for result — max 3 min"""
    def poll():
        for attempt in range(36):  # 36 x 5sec = 3 min
            time.sleep(5)
            try:
                with httpx.Client(timeout=15) as client:
                    res = client.get(
                        CHATBOT_ACTION_RESULT_API,
                        params={"phone": phone, "action": action}
                    )
                    print(f"[ActionPoll] {phone} {action} attempt {attempt+1}: {res.status_code}")

                    if res.status_code != 200:
                        continue

                    data = res.json()
                    print(f"[ActionPoll] Response: {str(data)[:200]}")

                    # Check if result is ready
                    if not data.get("success"):
                        continue

                    result = data.get("result", {})
                    if not result:
                        continue

                    # Deliver result to user
                    _deliver_result(phone, action, result, data)
                    break

            except Exception as e:
                print(f"[ActionPoll] Error: {e}")

    t = threading.Thread(target=poll, daemon=True)
    t.start()
    print(f"[ActionPoll] Started for {phone} action={action}")


def _build_message(action: str, result: dict, full_data: dict) -> str:
    """Build rich message from API response"""
    action_labels = {
        "health_score": "GMB Health Score Report",
        "magic_qr": "Magic QR Code",
        "insights": "GMB Insights",
        "review_reply": "Review Reply",
        "keyword_planner": "Keyword Planner",
        "website": "Website",
        "social_posts": "Social Posts"
    }
    label = action_labels.get(action, action)

    # Start with text from result
    text = result.get("text", "") or result.get("message", "")
    msg = f"✅ *{label} ready hai!*\n\n{text}"

    # Add score for health_score
    if action == "health_score":
        data = result.get("data", {})
        if data:
            score = data.get("totalScore", "")
            status = data.get("status", "")
            if score:
                msg += f"\n\n📊 *Total Score: {score}/100 — {status}*"

            # Score breakdown
            breakdown = data.get("scoreBreakdown", [])
            if breakdown:
                msg += "\n\n*Score Breakdown:*"
                for item in breakdown:
                    factor = item.get("factor", "")
                    sc = item.get("score", 0)
                    out_of = item.get("outOf", 0)
                    msg += f"\n  • {factor}: {sc}/{out_of}"

            # Recommendations
            signals = data.get("recommendationSignals", {})
            high_priority = [v.get("reason", "") for v in signals.values() if v.get("severity") == "high"]
            if high_priority:
                msg += "\n\n*⚠️ High Priority Issues:*"
                for hp in high_priority:
                    msg += f"\n  • {hp}"

        # PDF link
        if result.get("pdf_url"):
            msg += f"\n\n📄 *Full PDF Report:*\n{result['pdf_url']}"

    # Magic QR
    elif action == "magic_qr":
        if result.get("qr_url"):
            msg += f"\n\n🔮 *QR Code:*\n{result['qr_url']}"
        if result.get("qr_image"):
            msg += f"\n\n🔮 *QR Image:*\n{result['qr_image']}"

    # Insights
    elif action == "insights":
        data = result.get("data", {})
        if data:
            msg += "\n\n*📈 Key Metrics:*"
            if data.get("views"):
                msg += f"\n  • Views: {data['views']}"
            if data.get("clicks"):
                msg += f"\n  • Clicks: {data['clicks']}"
            if data.get("calls"):
                msg += f"\n  • Calls: {data['calls']}"

    # Keywords
    elif action == "keyword_planner":
        keywords = result.get("keywords", [])
        if keywords:
            msg += "\n\n*🔑 Top Keywords:*"
            for kw in keywords[:10]:
                if isinstance(kw, dict):
                    word = kw.get("word", kw.get("keyword", ""))
                    vol = kw.get("volume", kw.get("searchVolume", "N/A"))
                    msg += f"\n  • {word} — {vol}/month"
                else:
                    msg += f"\n  • {kw}"

    # Website
    elif action == "website":
        if result.get("website_url"):
            msg += f"\n\n🌐 *Website:*\n{result['website_url']}"

    return msg


def _deliver_result(phone: str, action: str, result: dict, full_data: dict):
    """Deliver result to user chat + WhatsApp"""
    try:
        from app.services.redis_service import save_message
        from app.services.whatsapp_service import send_whatsapp

        user_id = f"wa_{phone}"
        msg = _build_message(action, result, full_data)

        # Save to chat
        save_message(user_id, "assistant", msg)
        print(f"[ActionPoll] ✅ Saved to chat: {user_id}")

        # Send WhatsApp
        send_whatsapp(phone, msg)
        print(f"[ActionPoll] ✅ WhatsApp sent to {phone}")

    except Exception as e:
        print(f"[ActionPoll] Deliver error: {e}")
        import traceback; traceback.print_exc()