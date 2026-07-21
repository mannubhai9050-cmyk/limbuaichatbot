"""
WhatsApp sender — whatsapp.limbu.ai /api/external/send

Ek hi endpoint saare message types leta hai; payload ka shape decide karta hai
ki text jaayega, buttons, list, media ya template.

WhatsApp ki hard limits (yeh code inhe enforce karta hai — Meta chupchaap
reject kar deta hai, isliye yahan pehle hi fail karte hain):
  • buttons: max 3, title max 20 chars
  • list: max 10 rows total, row title max 24 chars
  • buttons/list sirf 24h window ke andar; uske baad template
"""
import logging
import time

import httpx

from app.core.config import WHATSAPP_API_URL, WHATSAPP_API_KEY

log = logging.getLogger(__name__)

MAX_BUTTONS = 3
MAX_BUTTON_TITLE = 20
MAX_LIST_ROWS = 10
MAX_ROW_TITLE = 24
MAX_BODY = 1024   # WhatsApp interactive message body limit

_TIMEOUT = 15
_RETRIES = 3
_BACKOFF = 2  # seconds; 2, 4, 8


def normalize_phone(phone: str) -> str:
    """
    Ek hi jagah phone normalize hota hai.

    NOTE: pehle yeh logic 5 jagah alag-alag tha (connect.py, social_connect.py,
    franchise.py, main.py, entity_extractor.py) aur do alag convention follow
    karta tha (10-digit vs 91-prefixed). Naya code sirf yahi use kare.

    Output: 91XXXXXXXXXX
    """
    p = "".join(ch for ch in str(phone) if ch.isdigit())
    if len(p) == 10:
        p = "91" + p
    return p


def _headers() -> dict:
    return {"X-API-Key": WHATSAPP_API_KEY, "Content-Type": "application/json"}


def _post(payload: dict) -> bool:
    """
    Send with retry. Purana code ek bhi retry nahi karta tha — ek 429/503
    aur message hamesha ke liye gayab, bina kisi nishan ke.

    Status code ke saath body bhi check karta hai: provider 200 ke saath
    {"error": ...} bhej sakte hain.
    """
    if not WHATSAPP_API_KEY:
        log.error("WHATSAPP_API_KEY missing — message nahi bheja")
        return False

    phone = payload.get("phone", "")
    last_err = ""

    for attempt in range(1, _RETRIES + 1):
        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                res = client.post(WHATSAPP_API_URL, headers=_headers(), json=payload)

            if res.status_code in (200, 201):
                body = {}
                try:
                    body = res.json()
                except Exception:
                    pass  # body JSON nahi hai — status par bharosa kar lete hain
                if isinstance(body, dict) and body.get("error"):
                    log.error("WA rejected (200 but error): %s", body.get("error"))
                    return False
                log.info("WA sent to %s (attempt %d)", phone[-4:], attempt)
                return True

            # 4xx (429 ke alawa) retry karne se theek nahi hoga
            if 400 <= res.status_code < 500 and res.status_code != 429:
                log.error("WA %s to %s — payload galat, retry nahi: %s",
                          res.status_code, phone[-4:], res.text[:200])
                return False

            last_err = f"HTTP {res.status_code}: {res.text[:200]}"

        except Exception as e:
            last_err = repr(e)

        if attempt < _RETRIES:
            wait = _BACKOFF ** attempt
            log.warning("WA attempt %d/%d failed (%s) — %ss baad retry",
                        attempt, _RETRIES, last_err, wait)
            time.sleep(wait)

    log.error("WA FAILED to %s after %d attempts: %s", phone[-4:], _RETRIES, last_err)
    return False


# ── Text ──────────────────────────────────────────────────────────
def send_text(phone: str, message: str) -> bool:
    return _post({"phone": normalize_phone(phone), "message": message})


# ── Buttons (max 3) ───────────────────────────────────────────────
def send_buttons(phone: str, message: str, buttons: list) -> bool:
    """
    buttons: [{"id": "BIZ_YES", "title": "Haan, yahi hai"}, ...]

    `id` hi user ke click par `button_payload` ban kar wapas aata hai —
    isi par match karna hai, title par nahi.
    """
    if not buttons:
        return send_text(phone, message)

    if len(buttons) > MAX_BUTTONS:
        raise ValueError(
            f"WhatsApp max {MAX_BUTTONS} buttons deta hai, {len(buttons)} diye gaye. "
            f"Zyada options ke liye send_list() use karein."
        )

    clean = []
    for b in buttons:
        title = str(b["title"])
        if len(title) > MAX_BUTTON_TITLE:
            raise ValueError(
                f"Button title {MAX_BUTTON_TITLE} chars se lamba: {title!r} ({len(title)})"
            )
        clean.append({"id": str(b["id"]), "title": title})

    # WhatsApp 1024 se lamba body reject kar deta hai — safety trim
    if len(message) > MAX_BODY:
        message = message[:MAX_BODY - 2].rstrip() + " …"

    return _post({"phone": normalize_phone(phone), "message": message, "buttons": clean})


# ── List (max 10 rows) ────────────────────────────────────────────
def send_list(phone: str, message: str, button_text: str, sections: list) -> bool:
    """
    sections: [{"title": "Services",
                "rows": [{"id": "s1", "title": "RO Service", "description": "..."}]}]

    Note: list ke saath media header nahi chalta — sirf text.
    """
    total = sum(len(s.get("rows", [])) for s in sections)
    if total > MAX_LIST_ROWS:
        raise ValueError(f"WhatsApp max {MAX_LIST_ROWS} list rows deta hai, {total} diye gaye.")
    if total == 0:
        return send_text(phone, message)

    for s in sections:
        for row in s.get("rows", []):
            if len(str(row["title"])) > MAX_ROW_TITLE:
                raise ValueError(
                    f"Row title {MAX_ROW_TITLE} chars se lamba: {row['title']!r}"
                )

    return _post({
        "phone": normalize_phone(phone),
        "message": message,
        "button_text": button_text,
        "sections": sections,
    })


# ── URL button (session, no template/approval) ────────────────────
def send_url_button(phone: str, message: str, button_text: str, url: str) -> bool:
    """
    Ek URL button wala message — tap par browser mein link khulta hai.

    Platform shape:
        {"phone", "message", "button": {"text": ..., "url": ...}}

    NOTE: URL button tap par webhook ko kuch WAPAS NAHI aata (quick-reply se
    ulta). Isliye iske baad connection ka pata webhook/connected se ya user ke
    "Done" quick-reply se hi chalega — url button ke bharose mat baitho.
    """
    if not url or not button_text:
        return send_text(phone, message)
    if len(button_text) > MAX_BUTTON_TITLE:
        raise ValueError(
            f"URL button text {MAX_BUTTON_TITLE} chars se lamba: {button_text!r}"
        )
    return _post({
        "phone": normalize_phone(phone),
        "message": message,
        "button": {"text": button_text, "url": url},
    })


# ── Media ─────────────────────────────────────────────────────────
def send_media(phone: str, media_type: str, url: str,
               caption: str = "", filename: str = "") -> bool:
    """
    media_type: image | video | document | audio

    Purana code image/document ko sirf URL text banakar bhejta tha kyunki
    tab lagta tha provider media support nahi karta. Ab karta hai.
    """
    allowed = {"image", "video", "document", "audio"}
    if media_type not in allowed:
        raise ValueError(f"media_type '{media_type}' galat hai. Allowed: {sorted(allowed)}")

    media = {"type": media_type, "url": url}
    if caption:
        media["caption"] = caption
    if media_type == "document" and filename:
        media["filename"] = filename

    return _post({"phone": normalize_phone(phone), "type": "media", "media": media})


# ── Template (24h window ke baad) ─────────────────────────────────
def send_template(phone: str, name: str, language: str = "en", params: list = None,
                  header_type: str = "", header_media: str = "") -> bool:
    """
    Template tabhi chahiye jab user ke last message ko 24 ghante ho gaye hon.
    Window ke andar send_buttons/send_list free-form chalte hain.
    """
    template = {"name": name, "language": language, "params": params or []}
    if header_type:
        template["header_type"] = header_type
    if header_media:
        template["header_media"] = header_media

    return _post({"phone": normalize_phone(phone), "type": "template", "template": template})


# ── Backward compatibility ────────────────────────────────────────
# Purana code in naamo se call karta hai. Naya code upar wale use kare.
def send_whatsapp(phone: str, message: str) -> bool:
    return send_text(phone, message)


def send_whatsapp_image(phone: str, image_url: str, caption: str = "") -> bool:
    return send_media(phone, "image", image_url, caption=caption)


def send_whatsapp_document(phone: str, doc_url: str, filename: str = "report.pdf",
                           caption: str = "") -> bool:
    return send_media(phone, "document", doc_url, caption=caption, filename=filename)
