import httpx
from app.core.config import LIMBU_API_BASE, LIMBU_ADMIN_EMAIL


def book_demo(name: str, phone: str, date: str, time: str) -> bool:
    """Book a demo via Limbu.ai API"""
    try:
        with httpx.Client(timeout=15) as client:
            payload = {
                "name": name,
                "phone": phone,
                "seminarTime": time,
                "selectedDate": date
            }
            print(f"[LimbuAPI] Booking demo: {payload}")
            res = client.post(
                f"{LIMBU_API_BASE}/bookDemo",
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            print(f"[LimbuAPI] Response: {res.status_code} — {res.text}")
            return res.status_code in [200, 201]
    except Exception as e:
        print(f"[LimbuAPI] Book demo error: {e}")
        return False


def check_user_by_phone(phone: str) -> dict | None:
    """Check if user exists by phone number"""
    try:
        with httpx.Client(timeout=10) as client:
            res = client.get(
                f"{LIMBU_API_BASE}/users",
                params={"email": LIMBU_ADMIN_EMAIL, "search": phone}
            )
            data = res.json()
            if data.get("success") and data.get("users"):
                return data["users"][0]
    except Exception as e:
        print(f"[LimbuAPI] Check user error: {e}")
    return None


def check_business_by_email(email: str) -> dict:
    """Check if Google Business is connected for a given email"""
    try:
        with httpx.Client(timeout=10) as client:
            res = client.get(
                f"{LIMBU_API_BASE}/admin/saveBussiness",
                params={"userEmail": email}
            )
            return res.json()
    except Exception as e:
        print(f"[LimbuAPI] Check business error: {e}")
        return {}