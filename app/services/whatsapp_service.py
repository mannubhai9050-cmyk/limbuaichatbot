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
            print(f"[WA] Text sent to {phone}: {res.status_code}")
            return res.status_code in [200, 201]
    except Exception as e:
        print(f"[WA] Error sending text to {phone}: {e}")
        return False


def send_whatsapp_image(phone: str, image_url: str, caption: str = "") -> bool:
    """Send image message (QR code, etc.)"""
    try:
        phone = _normalize_phone(phone)
        with httpx.Client(timeout=15) as client:
            payload = {
                "phone": phone,
                "type": "image",
                "url": image_url,
            }
            if caption:
                payload["caption"] = caption
            res = client.post(
                WHATSAPP_API_URL,
                headers=_headers(),
                json=payload
            )
            print(f"[WA] Image sent to {phone}: {res.status_code}")
            if res.status_code in [200, 201]:
                return True
            # Fallback: send as text link
            print(f"[WA] Image fallback to text for {phone}")
            return send_whatsapp(phone, f"{caption}\n{image_url}" if caption else image_url)
    except Exception as e:
        print(f"[WA] Error sending image to {phone}: {e}")
        return False


def send_whatsapp_document(phone: str, doc_url: str, filename: str = "report.pdf", caption: str = "") -> bool:
    """Send PDF/document message"""
    try:
        phone = _normalize_phone(phone)
        with httpx.Client(timeout=15) as client:
            payload = {
                "phone": phone,
                "type": "document",
                "url": doc_url,
                "filename": filename,
            }
            if caption:
                payload["caption"] = caption
            res = client.post(
                WHATSAPP_API_URL,
                headers=_headers(),
                json=payload
            )
            print(f"[WA] Document sent to {phone}: {res.status_code}")
            if res.status_code in [200, 201]:
                return True
            # Fallback: send as text link
            print(f"[WA] Document fallback to text for {phone}")
            return send_whatsapp(phone, f"{caption}\n📄 {doc_url}" if caption else f"📄 {doc_url}")
    except Exception as e:
        print(f"[WA] Error sending document to {phone}: {e}")
        return False