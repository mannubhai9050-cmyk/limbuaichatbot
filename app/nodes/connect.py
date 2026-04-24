import httpx
import uuid
from app.services.redis_service import save_session, get_session
from app.core.config import LIMBU_CONNECT_URL, LIMBU_API_BASE


def handle_connect_link(user_id: str, session: dict) -> str:
    """Generate fresh session_id and send connect link"""
    connect_session_id = uuid.uuid4().hex[:16]
    session["connect_session_id"] = connect_session_id
    session["connect_link_sent"] = True
    session["connect_verified"] = False
    save_session(user_id, session)

    connect_url = f"{LIMBU_CONNECT_URL}?session_id={connect_session_id}"
    return (
        f"Ji zaroor! Kripya is link se apna Google Business Profile connect karein:\n\n"
        f"🔗 {connect_url}\n\n"
        f"Link khol kar apni Gmail se login karein aur access de dein.\n"
        f"Connect hone ke baad main automatically notify kar doongi! 😊"
    )


def handle_check_latest_connection(user_id: str, session: dict) -> str:
    """Check connection using session_id"""
    connect_session_id = session.get("connect_session_id", "")

    if not connect_session_id:
        return handle_connect_link(user_id, session)

    try:
        with httpx.Client(timeout=15) as client:
            res = client.get(
                f"{LIMBU_API_BASE}/gmb/status",
                params={"session_id": connect_session_id}
            )
            print(f"[Connect] API {res.status_code}: {res.text[:300]}")
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
        session["connected_email"] = email
        session["connected_businesses"] = locations
        save_session(user_id, session)
        # Track connection
        try:
            from app.services.analytics_service import save_connection
            save_connection(user_id, {"email": email, "businesses": len(locations)})
        except: pass

        return _build_response(session, locations, email)
    else:
        connect_url = f"{LIMBU_CONNECT_URL}?session_id={connect_session_id}"
        return (
            f"Abhi connection nahi mila. 🤔\n\n"
            f"Kripya yeh link se dobara try karein:\n"
            f"🔗 {connect_url}\n\n"
            f"Gmail se login karke 'Allow' click karein. Ya call karein: 📞 9283344726"
        )


def _build_response(session: dict, locations: list, email: str) -> str:
    """Build smart response comparing with confirmed business"""
    confirmed_name = ""
    found_place = session.get("found_place", {})
    if found_place:
        confirmed_name = found_place.get("displayName", {}).get("text", "").lower()

    if not locations:
        return (
            f"🎉 **Badhaai ho!** Account connect ho gaya!\n\n"
            f"Lekin **{email}** se koi GMB profile linked nahi mili.\n\n"
            f"Ho sakta hai aapka business kisi aur Gmail se registered ho.\n"
            f"Sahi Gmail se dobara connect karein ya call karein: 📞 9283344726"
        )

    # Check if confirmed business is in the list
    confirmed_found = False
    confirmed_biz = None
    other_bizs = []

    for b in locations:
        name = b.get("title") or b.get("name") or ""
        if confirmed_name and confirmed_name in name.lower():
            confirmed_found = True
            confirmed_biz = b
        else:
            other_bizs.append(b)

    if confirmed_found and confirmed_biz:
        # Great — confirmed business is connected
        name = confirmed_biz.get("title") or confirmed_biz.get("name") or ""
        address = confirmed_biz.get("address") or ""
        verified = "✅ Verified" if confirmed_biz.get("verified") else "⚠️ Not Verified"
        phone = confirmed_biz.get("primaryPhone") or ""
        website = confirmed_biz.get("websiteUri") or ""

        msg = (
            f"🎉 **Badhaai ho! {name} successfully connect ho gaya!**\n\n"
            f"📧 Email: {email}\n"
            f"🏪 **{name}** — {verified}\n"
        )
        if address:
            msg += f"📍 {address}\n"
        if phone:
            msg += f"📞 {phone}\n"
        if website:
            msg += f"🌐 {website}\n"
        if len(locations) > 1:
            msg += f"\n**Is account se aur {len(locations)-1} profile(s) bhi linked hain.**\n"
        msg += (
            "\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🎁 **Aapke liye 5 FREE features:**\n\n"
            "1. 📊 **GMB Health Score** — Detailed profile health report\n"
            "2. 📈 **GMB Insights** — Analytics, views, clicks\n"
            "3. 🔮 **Magic QR Code** — Automatic review collection\n"
            "4. 💬 **Review Reply** — AI-powered review responses\n"
            "5. 🔑 **Keyword Planner** — Business keywords + search volume\n\n"
            "Kaunsa feature chahiye? (1/2/3/4/5 ya naam batayein) 😊"
        )
        if address:
            msg += f"📍 {address}\n"
        if phone:
            msg += f"📞 {phone}\n"
        if website:
            msg += f"🌐 {website}\n"

        # Show other businesses too
        if len(locations) > 1:
            msg += f"\n**Is account se aur {len(locations)-1} business(es) bhi linked hain:**\n"
            for b in locations:
                bname = b.get("title") or b.get("name") or ""
                if bname.lower() != name.lower():
                    bv = "✅" if b.get("verified") else "⚠️"
                    msg += f"  • {bv} {bname}\n"

        msg += f"\nAb Limbu.ai aapki profile manage karega.\nKya aap abhi plan lena chahenge? 😊\n📞 9283344726"
        return msg

    else:
        # Confirmed business NOT in list — show mismatch
        biz_lines = []
        for i, b in enumerate(locations, 1):
            name = b.get("title") or b.get("name") or "Business"
            address = b.get("address") or ""
            verified = "✅ Verified" if b.get("verified") else "⚠️ Not Verified"
            line = f"  {i}. **{name}** — {verified}"
            if address:
                line += f"\n     📍 {address}"
            biz_lines.append(line)

        confirmed_display = found_place.get("displayName", {}).get("text", "aapka business") if found_place else "aapka business"

        return (
            f"Hmm! 🤔 **{email}** se **{confirmed_display}** link nahi mila.\n\n"
            f"Is email se yeh businesses linked hain:\n\n"
            f"{chr(10).join(biz_lines)}\n\n"
            f"**{confirmed_display}** ko connect karne ke liye us Gmail se try karein "
            f"jisme yeh business registered hai. Main naya link bhejti hoon:\n\n"
            f"🔗 Kya aap sahi Gmail se dobara try karna chahenge?"
        )


def handle_check_email(user_id: str, session: dict, email: str) -> str:
    session["connected_email"] = email
    save_session(user_id, session)
    return handle_check_latest_connection(user_id, session)