import httpx
from app.services.redis_service import save_session, get_session, get_history
from app.core.config import LIMBU_CONNECT_URL, LIMBU_API_BASE


def _get_phone(user_id: str, session: dict = None) -> str:
    """
    Extract phone number. Priority:
    1. session["connect_phone"] — already saved
    2. user_id starts with wa_ → wa_917740847114
    3. user_id is pure digits → use directly
    """
    # Already saved in session
    if session and session.get("connect_phone"):
        return session["connect_phone"]

    # wa_ prefix format
    if user_id.startswith("wa_"):
        phone = user_id.replace("wa_", "").replace("+", "").replace(" ", "")
        if not phone.startswith("91") and len(phone) == 10:
            phone = "91" + phone
        return phone

    # Pure digits (some WhatsApp providers send raw number as user_id)
    digits = user_id.replace("+", "").replace(" ", "").replace("-", "")
    if digits.isdigit():
        if not digits.startswith("91") and len(digits) == 10:
            digits = "91" + digits
        return digits

    return ""


def handle_connect_link(user_id: str, session: dict) -> str:
    """Generate connect link using phone number"""
    phone = _get_phone(user_id, session)
    lang = session.get("lang", "hi")
    en = (lang == "en")

    session["connect_link_sent"] = True
    session["connect_verified"] = False
    if phone:
        session["connect_phone"] = phone
    save_session(user_id, session)

    if not phone:
        if en:
            return (
                f"Please use this link to connect your Google Business Profile:\n\n"
                f"🔗 {LIMBU_CONNECT_URL}\n\n"
                f"Open the link and sign in with your Gmail.\n"
                f"Or call us: 📞 9283344726"
            )
        return (
            f"Is link se connect karein:\n\n"
            f"🔗 {LIMBU_CONNECT_URL}\n\n"
            f"Link khol kar Gmail se login karein.\n"
            f"Ya call karein: 📞 9283344726"
        )

        connect_url = LIMBU_CONNECT_URL + "?phone=" + phone
    if en:
        return (
            "Use this link to connect your Google Business Profile:\n\n"
            "🔗 " + connect_url + "\n\n"
            "Open the link and login with Gmail.\n"
            "I'll notify you automatically once connected! 😊\n"
            "Need help? Call 📞 +91 9283344726"
        )
    return (
        "Is link se connect karein:\n\n"
        "🔗 " + connect_url + "\n\n"
        "Link khol kar Gmail se login karein.\n"
        "Connect hone ke baad main automatically bataa doongi! 😊\n"
        "Ya call karein: 📞 +91 9283344726"
    )


def handle_check_latest_connection(user_id: str, session: dict) -> str:
    """Check connection status via Limbu API using phone number"""
    phone = _get_phone(user_id, session)

    if not phone:
        return handle_connect_link(user_id, session)

    try:
        with httpx.Client(timeout=15) as client:
            res = client.get(
                f"{LIMBU_API_BASE}/gmb/status",
                params={"phone": phone}
            )
            print(f"[Connect] API {res.status_code}: {res.text[:200]}")
            data = res.json()
    except Exception as e:
        print(f"[Connect] Error: {e}")
        return "Technical problem aayi. Kripya 📞 9283344726 par call karein."

    if data.get("status") == "success" or data.get("success"):
        locations = (
            data.get("locationsData") or
            data.get("businesses") or
            data.get("data") or []
        )
        email = data.get("email", "")
        session["connect_verified"] = True
        session["connect_link_sent"] = True  # Mark as sent too for consistency
        session["connected_email"] = email
        session["connected_businesses"] = locations
        save_session(user_id, session)
        return _build_connected_response(session, locations, email)
    else:
        connect_url = LIMBU_CONNECT_URL + "?phone=" + phone
        lang = session.get("lang", "hi")
        if lang == "en":
            return (
                "Connection not found yet. 🤔\n\n"
                "Use this link to connect:\n"
                "🔗 " + connect_url + "\n\n"
                "Open the link and login with Gmail.\n"
                "Need help? Call 📞 +91 9283344726"
            )
        return (
            "Abhi connection nahi mila. 🤔\n\n"
            "Is link se dobara try karein:\n"
            "🔗 " + connect_url + "\n\n"
            "Link khol kar Gmail se login karein.\n"
            "Ya call karein: 📞 +91 9283344726"
        )

def _build_connected_response(session: dict, locations: list, email: str) -> str:
    """Build response showing all connected businesses, warn if mismatch"""
    if not locations:
        return (
            "🎉 *Account connect ho gaya!*\n\n"
            "Lekin " + email + " se koi GMB profile linked nahi mili.\n\n"
            "Ho sakta hai business kisi aur Gmail se registered ho.\n"
            "Sahi Gmail se dobara try karein ya call karein: 📞 9283344726"
        )

    # Check if confirmed business matches any connected business
    found_place = session.get("found_place") or {}
    searched_name = (found_place.get("displayName", {}).get("text", "") or
                     session.get("business_name", "")).lower()
    matched = any(searched_name in (b.get("title","").lower()) or
                  b.get("title","").lower() in searched_name
                  for b in locations) if searched_name else True

    # If mismatch, warn user
    mismatch_warning = ""
    if searched_name and not matched:
        mismatch_warning = (
            "\n⚠️ *Note:* Connected Gmail mein *" + (session.get("business_name","") or "your business") +
            "* nahi mili. Aap kisi ek connected business select karein ya sahi Gmail se connect karein.\n"
        )

    biz_lines = []
    for i, b in enumerate(locations, 1):
        name = b.get("title") or b.get("name") or "Business"
        address = b.get("address") or ""
        verified = "✅ Verified" if b.get("verified") else "⚠️ Not Verified"
        line = "  " + str(i) + ". *" + name + "* — " + verified
        if address:
            line += "\n     📍 {address}"
        biz_lines.append(line)

    return (
        "🎉 *Congrats! Account connect ho gaya!*\n\n"
        "📧 Email: " + email + "\n\n" +
        mismatch_warning +
        "*Aapke Connected Businesses:*\n" +
        chr(10).join(biz_lines) + "\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Kya main aapki *Full Health Report* nikal doon? (FREE hai) 😊"
    )


def handle_check_email(user_id: str, session: dict, email: str) -> str:
    session["connected_email"] = email
    save_session(user_id, session)
    return handle_check_latest_connection(user_id, session)



def _build_connected_response(session: dict, locations: list, email: str) -> str:
    """Build response showing all connected businesses, warn if mismatch"""
    if not locations:
        return (
            "🎉 *Account connect ho gaya!*\n\n"
            "Lekin " + email + " se koi GMB profile linked nahi mili.\n\n"
            "Ho sakta hai business kisi aur Gmail se registered ho.\n"
            "Sahi Gmail se dobara try karein ya call karein: 📞 9283344726"
        )

    # Check if confirmed business matches any connected business
    found_place = session.get("found_place") or {}
    searched_name = (found_place.get("displayName", {}).get("text", "") or
                     session.get("business_name", "")).lower()
    matched = any(searched_name in (b.get("title","").lower()) or
                  b.get("title","").lower() in searched_name
                  for b in locations) if searched_name else True

    # If mismatch, warn user
    mismatch_warning = ""
    if searched_name and not matched:
        mismatch_warning = (
            "\n⚠️ *Note:* Connected Gmail mein *" + (session.get("business_name","") or "your business") +
            "* nahi mili. Aap kisi ek connected business select karein ya sahi Gmail se connect karein.\n"
        )

    biz_lines = []
    for i, b in enumerate(locations, 1):
        name = b.get("title") or b.get("name") or "Business"
        address = b.get("address") or ""
        verified = "✅ Verified" if b.get("verified") else "⚠️ Not Verified"
        line = "  " + str(i) + ". *" + name + "* — " + verified
        if address:
            line += "\n     📍 {address}"
        biz_lines.append(line)

    return (
        f"🎉 *Badhaai ho! Account connect ho gaya!*\n\n"
        f"📧 Email: {email}\n\n"
        f"*Aapke Connected Businesses:*\n"
        f"{chr(10).join(biz_lines)}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Kya main aapki *Full Health Report* nikal doon? (FREE hai) 😊"
    )


def handle_check_email(user_id: str, session: dict, email: str) -> str:
    session["connected_email"] = email
    save_session(user_id, session)
    return handle_check_latest_connection(user_id, session)