import httpx
from app.services.redis_service import save_session, get_session
from app.core.config import LIMBU_CONNECT_URL, LIMBU_API_BASE


def _get_phone(user_id: str) -> str:
    """Extract phone from user_id"""
    if user_id.startswith("wa_"):
        return user_id.replace("wa_", "")
    return user_id.replace("u_", "")


def handle_connect_link(user_id: str, session: dict) -> str:
    """Generate connect link using phone number"""
    phone = _get_phone(user_id)
    connect_url = f"{LIMBU_CONNECT_URL}?phone={phone}"
    
    session["connect_link_sent"] = True
    session["connect_verified"] = False
    session["poll_msg_saved"] = False
    session["payment_notified"] = False
    session["features_offered"] = []
    save_session(user_id, session)

    return (
        f"Apna business Limbu.ai se connect karein:\n\n"
        f"🔗 {connect_url}\n\n"
        f"Link khol kar apni Gmail se login karein.\n"
        f"Connect hone ke baad main automatically notify kar doongi! 😊"
    )


def handle_check_latest_connection(user_id: str, session: dict) -> str:
    """Check connection status using phone number"""
    phone = _get_phone(user_id)

    try:
        with httpx.Client(timeout=15) as client:
            res = client.get(
                f"{LIMBU_API_BASE}/gmb/status",
                params={"phone": phone}
            )
            print(f"[Connect] API {res.status_code}: {res.text[:300]}")
            data = res.json()
    except Exception as e:
        print(f"[Connect] Error: {e}")
        return "Technical problem aayi. Kripya 📞 9283344726 par call karein."

    if data.get("status") == "success" or data.get("businessConnected"):
        locations = data.get("locationsData") or data.get("businesses") or []
        email = data.get("email", "")

        session["connect_verified"] = True
        session["connected_email"] = email
        session["connected_businesses"] = locations
        save_session(user_id, session)

        return _build_connected_response(session, locations, email)
    else:
        connect_url = f"{LIMBU_CONNECT_URL}?phone={phone}"
        return (
            f"Abhi connection nahi mila. 🤔\n\n"
            f"Kripya yeh link se dobara try karein:\n"
            f"🔗 {connect_url}\n\n"
            f"Gmail se login karke 'Allow' click karein.\n"
            f"Ya call karein: 📞 9283344726"
        )


def _build_connected_response(session: dict, locations: list, email: str) -> str:
    """Build connect success message + first feature offer"""
    found_place = session.get("found_place", {})
    confirmed_name = found_place.get("displayName", {}).get("text", "").lower()

    # Find the confirmed business
    confirmed_biz = None
    for b in locations:
        name = (b.get("title") or b.get("name") or "").lower()
        if confirmed_name and (confirmed_name in name or name in confirmed_name):
            confirmed_biz = b
            break
    if not confirmed_biz and locations:
        confirmed_biz = locations[0]

    if not confirmed_biz:
        return (
            f"🎉 **Account connect ho gaya!**\n\n"
            f"📧 Email: {email}\n\n"
            f"Koi GMB profile nahi mili. Sahi Gmail se try karein.\n"
            f"📞 9283344726"
        )

    name = confirmed_biz.get("title") or confirmed_biz.get("name") or ""
    address = confirmed_biz.get("address") or ""
    phone_num = confirmed_biz.get("primaryPhone") or ""
    verified = "✅ Verified" if confirmed_biz.get("verified") else "⚠️ Not Verified"
    website = confirmed_biz.get("websiteUri") or ""
    loc_id = confirmed_biz.get("locationResourceName") or ""

    # Save location_id for later use
    session["primary_location_id"] = loc_id
    save_session(session.get("user_id", ""), session)

    msg = f"🎉 **{name} connect ho gaya!**\n\n"
    msg += f"📧 {email}\n"
    msg += f"🏪 {name} — {verified}\n"
    if address:
        msg += f"📍 {address}\n"
    if phone_num:
        msg += f"📞 {phone_num}\n"
    if website:
        msg += f"🌐 {website}\n"
    if len(locations) > 1:
        msg += f"\n_(Is account se {len(locations)} profiles linked hain)_\n"

    msg += (
        f"\nAb main aapke liye FREE kaam karti hoon! 🎁\n\n"
        f"Pehle — kya main aapki GMB ki poori **Health Report** nikaal dun? 📊"
    )

    return msg


def handle_check_email(user_id: str, session: dict, email: str) -> str:
    session["connected_email"] = email
    save_session(user_id, session)
    return handle_check_latest_connection(user_id, session)