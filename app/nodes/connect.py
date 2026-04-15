import httpx
from app.services.redis_service import save_session
from app.core.config import LIMBU_CONNECT_URL, LIMBU_API_BASE


def handle_connect_link(user_id: str, session: dict) -> str:
    """Send connect link — no email asking"""
    return (
        f"Ji zaroor! Yeh link se aap apna Google Business Profile connect kar sakte hain:\n\n"
        f"🔗 **{LIMBU_CONNECT_URL}**\n\n"
        f"Link khol kar apni Gmail se login karein. Jab ho jaye toh mujhe batayein — "
        f"main verify kar doongi! 😊"
    )


def handle_check_latest_connection(user_id: str, session: dict) -> str:
    """
    Check latest connected business automatically.
    GET /api/admin/saveBussiness?userEmail=<email>
    Email is captured from session or fetched from latest connection.
    """
    # Try to get email from session
    connected_email = session.get("connected_email", "")

    # If no email in session, try to get from business search context
    if not connected_email:
        # Try fetching latest connection without email (if API supports it)
        result = _fetch_latest_connection()
        if result and result.get("email"):
            connected_email = result["email"]
            session["connected_email"] = connected_email
            save_session(user_id, session)

    if not connected_email:
        return (
            "Ji, connection verify karne ke liye apni registered email batayein?\n"
            "(Jo Gmail aapne link pe use ki thi) 😊"
        )

    return _verify_and_report(user_id, session, connected_email)


def handle_check_email(user_id: str, session: dict, email: str) -> str:
    """Verify specific email"""
    session["connected_email"] = email
    save_session(user_id, session)
    return _verify_and_report(user_id, session, email)


def _fetch_latest_connection() -> dict:
    """Try to get latest connection from API"""
    try:
        with httpx.Client(timeout=10) as client:
            res = client.get(f"{LIMBU_API_BASE}/admin/saveBussiness/latest")
            if res.status_code == 200:
                return res.json()
    except Exception as e:
        print(f"[Connect] Latest connection error: {e}")
    return {}


def _verify_and_report(user_id: str, session: dict, email: str) -> str:
    """Fetch business data by email and generate report"""
    try:
        with httpx.Client(timeout=10) as client:
            res = client.get(
                f"{LIMBU_API_BASE}/admin/saveBussiness",
                params={"userEmail": email}
            )
            data = res.json()
    except Exception as e:
        print(f"[Connect] Verify error: {e}")
        data = {}

    if not data or not data.get("success"):
        return (
            f"Ji, **{email}** se koi connected business nahi mila abhi. 🤔\n\n"
            f"Kripya dobara try karein:\n"
            f"🔗 {LIMBU_CONNECT_URL}\n\n"
            f"Koi problem ho toh call karein: 📞 9283344726"
        )

    # ── Business connected — build detailed report ────────────────
    businesses = (data.get("businesses") or
                  data.get("accounts") or
                  data.get("data") or [])

    if not businesses:
        # Connected but no businesses found
        session["connected_email"] = email
        save_session(user_id, session)
        return (
            f"🎉 **Badhaai ho!** Aapka account **{email}** Limbu.ai se connect ho gaya hai!\n\n"
            f"Abhi koi business profile linked nahi dikh raha. "
            f"Kya aap chahenge ki main aapke liye GMB profile setup karoon?\n"
            f"📞 9283344726"
        )

    # Build business list
    biz_lines = []
    for i, b in enumerate(businesses, 1):
        name = b.get("name") or b.get("businessName") or b.get("title") or "Business"
        address = b.get("address") or b.get("location") or b.get("formattedAddress") or ""
        rating = b.get("rating") or b.get("averageRating") or "N/A"
        reviews = b.get("userRatingCount") or b.get("totalReviews") or 0
        status = b.get("status") or b.get("businessStatus") or ""

        line = f"  {i}. **{name}**"
        if address:
            line += f"\n     📍 {address}"
        if rating != "N/A":
            line += f"\n     ⭐ {rating}/5 ({reviews} reviews)"
        if status:
            line += f"\n     Status: {status}"
        biz_lines.append(line)

    biz_text = "\n\n".join(biz_lines)

    session["connected_email"] = email
    session["connected_businesses"] = businesses
    save_session(user_id, session)

    return (
        f"🎉 **Badhaai ho!** Connection successful!\n\n"
        f"**{email}** se yeh GMB profiles linked hain:\n\n"
        f"{biz_text}\n\n"
        f"Kya aap chahte hain ki main inki detailed analysis karoon aur "
        f"bataaon ki Limbu.ai se kaise aur grow kar sakte hain? 😊"
    )