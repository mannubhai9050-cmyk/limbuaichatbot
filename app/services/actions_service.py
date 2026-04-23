import httpx
from app.core.config import CHATBOT_ACTION_API, LIMBU_API_BASE


def trigger_action(action: str, session_id: str, location_id: str, email: str) -> dict:
    """
    Trigger a Limbu.ai dashboard action via API.
    
    Actions:
    - health_score: Generate full GMB health score report
    - magic_qr: Generate Magic QR code
    - website: Generate optimized website
    - insights: Get business insights/analytics
    - social_posts: Generate social media posts
    """
    try:
        with httpx.Client(timeout=30) as client:
            payload = {
                "action": action,
                "session_id": session_id,
                "locationId": location_id,
                "email": email
            }
            print(f"[Action] Triggering {action} for {email} location {location_id}")
            res = client.post(CHATBOT_ACTION_API, json=payload)
            print(f"[Action] Response {res.status_code}: {res.text[:200]}")
            return res.json()
    except Exception as e:
        print(f"[Action] Error: {e}")
        return {"success": False, "message": str(e)}


def get_action_status(action_id: str) -> dict:
    """Check status of a triggered action"""
    try:
        with httpx.Client(timeout=10) as client:
            res = client.get(
                f"{LIMBU_API_BASE}/chatbot/action-status",
                params={"action_id": action_id}
            )
            return res.json()
    except Exception as e:
        print(f"[Action] Status check error: {e}")
        return {}