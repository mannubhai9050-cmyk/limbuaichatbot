import httpx
from app.core.config import CHATBOT_ACTION_API


def trigger_action(action: str, phone: str, location_id: str, email: str) -> dict:
    """Trigger Limbu.ai dashboard action — uses phone, no session_id"""
    try:
        with httpx.Client(timeout=30) as client:
            payload = {
                "action": action,
                "phone": phone,
                "locationId": location_id,
                "email": email
            }
            print(f"[Action] Triggering {action} phone={phone} location={location_id}")
            res = client.post(CHATBOT_ACTION_API, json=payload)
            print(f"[Action] Response {res.status_code}: {res.text[:300]}")
            return res.json()
    except Exception as e:
        print(f"[Action] Error: {e}")
        return {"success": False, "message": str(e)}