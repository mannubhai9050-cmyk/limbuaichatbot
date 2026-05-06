import httpx
from app.core.config import WHATSAPP_API_URL, WHATSAPP_API_KEY


def _headers():
    return {
        "X-API-Key": WHATSAPP_API_KEY,
        "Content-Type": "application/json"
    }


def _normalize_phone(phone: str) -> str:
    phone = phone.replace("+", "").replace("-", "").replace(" ", "")
    if not phone.startswith("91"):
        phone = "91" + phone
    return phone


def send_whatsapp(phone: str, message: str) -> bool:
    """Send text message via WhatsApp API"""
    try:
        phone = _normalize_phone(phone)
        with httpx.Client(timeout=15) as client:
            res = client.post(
                WHATSAPP_API_URL,
                headers=_headers(),
                json={"phone": phone, "message": message}
            )
            print(f"[WA] Sent to {phone}: {res.status_code}")
            return res.status_code in [200, 201]
    except Exception as e:
        print(f"[WA] Error sending to {phone}: {e}")
        return False


def send_whatsapp_image(phone: str, image_url: str, caption: str = "") -> bool:
    """
    Send image as text URL — WhatsApp shows link preview automatically.
    Provider does not support type:image format.
    """
    phone = _normalize_phone(phone)
    # Just send as text with caption + URL
    msg = f"{caption}\n{image_url}" if caption else image_url
    return send_whatsapp(phone, msg)


def send_whatsapp_document(phone: str, doc_url: str, filename: str = "report.pdf", caption: str = "") -> bool:
    """
    Send document as text URL — WhatsApp shows link preview automatically.
    Provider does not support type:document format.
    """
    phone = _normalize_phone(phone)
    msg = f"{caption}\n{doc_url}" if caption else doc_url
    return send_whatsapp(phone, msg)