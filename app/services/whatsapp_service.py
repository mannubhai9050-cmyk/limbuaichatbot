import httpx
from app.core.config import WHATSAPP_API_URL, WHATSAPP_API_KEY


def send_whatsapp(phone: str, message: str) -> bool:
    """Send WhatsApp message via API"""
    try:
        # Clean phone number
        phone = phone.replace("+", "").replace("-", "").replace(" ", "")
        if not phone.startswith("91"):
            phone = "91" + phone

        with httpx.Client(timeout=15) as client:
            res = client.post(
                WHATSAPP_API_URL,
                headers={
                    "X-API-Key": WHATSAPP_API_KEY,
                    "Content-Type": "application/json"
                },
                json={"phone": phone, "message": message}
            )
            print(f"[WA] Sent to {phone}: {res.status_code}")
            return res.status_code in [200, 201]
    except Exception as e:
        print(f"[WA] Error: {e}")
        return False