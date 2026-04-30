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

FEATURE_NEXT_OFFER = {
    "health_score": {
        "hi": "Kya main aapko *Magic QR Code* bhejoon? (FREE hai) — Yeh automatically reviews laata hai! 😊",
        "en": "Shall I send you the *Magic QR Code*? (FREE) — It automatically collects reviews! 😊"
    },
    "magic_qr": {
        "hi": "Kya main aapki *Google Insights / Performance* data dikhaoon? (FREE hai) 📊",
        "en": "Shall I show your *Google Insights / Performance* data? (FREE) 📊"
    },
    "insights": {
        "hi": "Kya main aapki *Free Website* banaoon? (Bilkul FREE hai, koi charge nahi!) 🌐",
        "en": "Shall I create your *Free Website*? (Absolutely FREE, no charge!) 🌐"
    },
    "website": {
        "hi": "Kya main aapke Google reviews ka *AI Reply* setup karoon? (FREE hai) ⭐",
        "en": "Shall I set up *AI Review Replies* for your Google reviews? (FREE) ⭐"
    },
    "review_reply": {
        "hi": (
            "🎉 Bahut achha! Aapne saari FREE features try kar li hain!\n\n"
            "Ek plan leke in features ko regularly automate karein.\n"
            "📞 9283344726"
        ),
        "en": (
            "🎉 Great! You've tried all FREE features!\n\n"
            "Get a plan to automate these features regularly.\n"
            "📞 9283344726"
        )
    }
}


def handle_feature(user_id: str, session: dict, feature_type: str) -> str:
    businesses = session.get("connected_businesses", [])
    email = session.get("connected_email", "")
    lang = session.get("lang", "hi")
    en = (lang == "en")

    if not businesses and not email:
        return "Please connect your business first. Shall I send the connect link? 😊" if en else \
               "Pehle apna business connect karna hoga. Kya main connect link bhejoon? 😊"

    phone = _get_phone(user_id, session)
    if not phone:
        label = FEATURE_LABELS.get(feature_type, feature_type)
        return f"Please call: 📞 9283344726" if en else f"Kripya call karein: 📞 9283344726"

    # ── Get locationResourceName from connected businesses ─────────
    location_id = _get_location_resource_name(session)

    # Track features offered
    offered = session.get("features_offered", [])
    if feature_type not in offered:
        offered.append(feature_type)
        session["features_offered"] = offered
        save_session(user_id, session)

    label = FEATURE_LABELS.get(feature_type, feature_type)
    print(f"[Feature] Triggering {feature_type} phone={phone} location={location_id} email={email}")

    result = trigger_action(feature_type, phone, location_id, email, user_id)

    next_offer_map = FEATURE_NEXT_OFFER.get(feature_type, {})
    next_offer = next_offer_map.get(lang, next_offer_map.get("hi", ""))

    if result.get("success"):
        if en:
            return f"✅ *{label}* is being processed... I'll send the result shortly! 😊"
        return f"✅ *{label}* process ho rahi hai... thodi der mein result aayega! 😊"
    else:
        error_msg = result.get("message", "")
        if en:
            return (
                f"*{label}* ran into a small issue. 😕\n"
                f"{f'({error_msg})' if error_msg else ''}\n\n"
                f"Please call: 📞 9283344726\n\n"
                f"{next_offer}"
            )
        return (
            f"*{label}* mein thodi problem aayi. 😕\n"
            f"{f'({error_msg})' if error_msg else ''}\n\n"
            f"Kripya call karein: 📞 9283344726\n\n"
            f"{next_offer}"
        )


def _get_location_resource_name(session: dict) -> str:
    """
    Get locationResourceName from connected businesses.
    Matches the confirmed business first, then falls back to first in list.
    API expects format: 'locations/913426026493879201'
    """
    businesses = session.get("connected_businesses", [])
    if not businesses:
        return ""

    # Try to match confirmed business by name
    confirmed_name = ""
    found_place = session.get("found_place", {})
    if found_place:
        confirmed_name = found_place.get("displayName", {}).get("text", "") or \
                        session.get("business_name", "")

    if confirmed_name:
        confirmed_lower = confirmed_name.lower().strip()
        for b in businesses:
            biz_title = b.get("title", "").lower().strip()
            if biz_title == confirmed_lower or confirmed_lower in biz_title or biz_title in confirmed_lower:
                loc = b.get("locationResourceName", "") or b.get("locationId", "") or b.get("id", "")
                if loc:
                    print(f"[Feature] Matched business '{b['title']}' → {loc}")
                    return loc

    # Fallback to first business
    b = businesses[0]
    loc = b.get("locationResourceName", "") or b.get("locationId", "") or b.get("id", "")
    print(f"[Feature] Fallback to first business '{b.get('title','')}' → {loc}")
    return loc