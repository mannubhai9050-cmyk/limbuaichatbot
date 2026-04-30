from app.services.redis_service import save_session
from app.services.actions_service import trigger_action
from app.nodes.connect import _get_phone

# Order in which features are offered
FEATURE_SEQUENCE = ["health_score", "magic_qr", "insights", "website", "review_reply"]

FEATURE_LABELS = {
    "health_score": "Full Health Report",
    "magic_qr": "Magic QR Code",
    "insights": "Google Insights / Performance",
    "website": "Free Website",
    "review_reply": "Review Reply System"
}

# What to offer AFTER each feature result arrives (sent by polling thread)
FEATURE_NEXT_OFFER = {
    "health_score": "Kya main aapko *Magic QR Code* bhejoon? (FREE hai) — Yeh automatically reviews laata hai! 😊",
    "magic_qr": "Kya main aapki *Google Insights / Performance* data dikhaoon? (FREE hai) 📊",
    "insights": "Kya main aapki *Free Website* banaoon? (Bilkul FREE hai, koi charge nahi!) 🌐",
    "website": "Kya main aapke Google reviews ka *AI Reply* setup karoon? (FREE hai) ⭐",
    "review_reply": (
        "🎉 Bahut achha! Aapne saari FREE features try kar li hain!\n\n"
        "Ab aapka business Limbu.ai par fully setup hai.\n"
        "Ek plan leke in features ko regularly automate karein — "
        "ek customer ki booking se poora plan ka kharcha nikal aata hai! 😊\n"
        "📞 9283344726"
    )
}


def handle_feature(user_id: str, session: dict, feature_type: str) -> str:
    """
    Trigger a free feature action.
    Returns ONLY a brief acknowledgment.
    Actual result is delivered by polling thread — NO duplicate message.
    """
    businesses = session.get("connected_businesses", [])
    email = session.get("connected_email", "")

    if not businesses and not email:
        return "Pehle apna business connect karna hoga. Kya main connect link bhejoon? 😊"

    # ── Phone — always from session first, then user_id ──────────
    phone = _get_phone(user_id, session)

    if not phone:
        label = FEATURE_LABELS.get(feature_type, feature_type)
        return (
            f"*{label}* ke liye phone number required hai.\n\n"
            f"Kripya call karein: 📞 9283344726"
        )

    # ── Location ID ───────────────────────────────────────────────
    location_id = _get_location_id(session)

    # ── Track features offered ────────────────────────────────────
    offered = session.get("features_offered", [])
    if feature_type not in offered:
        offered.append(feature_type)
        session["features_offered"] = offered
        save_session(user_id, session)

    label = FEATURE_LABELS.get(feature_type, feature_type)
    print(f"[Feature] Triggering {feature_type} phone={phone} location={location_id} email={email}")

    result = trigger_action(feature_type, phone, location_id, email, user_id)

    lang = session.get("lang", "hi")
    en = (lang == "en")

    if result.get("success"):
        if en:
            return f"\u2705 *{label}* is being processed... I'll send the result shortly! \U0001f60a"
        return f"\u2705 *{label}* process ho rahi hai... thodi der mein result aayega! \U0001f60a"
    else:
        error_msg = result.get("message", "")
        next_offer = FEATURE_NEXT_OFFER.get(feature_type, "")
        if en:
            return (
                f"*{label}* ran into a small issue. \U0001f615\n"
                f"{f'({error_msg})' if error_msg else ''}\n\n"
                f"Please call: \U0001f4de 9283344726\n\n"
                f"{next_offer}"
            )
        return (
            f"*{label}* mein thodi problem aayi. \U0001f615\n"
            f"{f'({error_msg})' if error_msg else ''}\n\n"
            f"Kripya call karein: \U0001f4de 9283344726\n\n"
            f"{next_offer}"
        )


def _get_location_id(session: dict) -> str:
    """Get GMB location ID — only the CID number, no extra URL params"""
    import re as _re
    confirmed_place = session.get("found_place", {})
    if confirmed_place:
        maps_uri = confirmed_place.get("googleMapsUri", "")
        if "cid=" in maps_uri:
            # Extract ONLY the numeric CID — stop at & or end
            cid_part = maps_uri.split("cid=")[-1]
            cid = _re.match(r"(\d+)", cid_part)
            if cid:
                return cid.group(1)
        loc_id = confirmed_place.get("name", "") or confirmed_place.get("id", "")
        if loc_id:
            return loc_id

    businesses = session.get("connected_businesses", [])
    if businesses:
        b = businesses[0]
        return (
            b.get("locationId") or
            b.get("id") or
            b.get("name") or ""
        )
    return ""