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
            "📞 +91 9289344726"
        ),
        "en": (
            "🎉 Great! You've tried all FREE features!\n\n"
            "Get a plan to automate these features regularly.\n"
            "📞 +91 9289344726"
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
        return f"Please call: 📞 +91 9289344726" if en else f"Kripya call karein: 📞 +91 9289344726"

    # ── Get locationResourceName — prefer active (switched) business ─
    location_id = session.get("active_location_id") or _get_location_resource_name(session)

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
        if en:
            msg = f"Something went wrong with *{label}*. Let me try again in a moment.\n\nNeed help? 📞 +91 9289344726"
        else:
            msg = f"*{label}* mein kuch technical issue aa gaya. Main dobara try karti hoon.\n\nHelp ke liye: 📞 +91 9289344726"
        if next_offer:
            msg += "\n\n" + next_offer
        return msg


# City aliases — handle different spellings
_CITY_ALIASES = {
    "gurgaon": ["gurugram", "gurgaon"],
    "gurugram": ["gurugram", "gurgaon"],
    "bangalore": ["bengaluru", "bangalore"],
    "bengaluru": ["bengaluru", "bangalore"],
    "bombay": ["mumbai", "bombay"],
    "mumbai": ["mumbai", "bombay"],
    "calcutta": ["kolkata", "calcutta"],
    "kolkata": ["kolkata", "calcutta"],
    "prayagraj": ["allahabad", "prayagraj"],
    "allahabad": ["allahabad", "prayagraj"],
    "mysuru": ["mysore", "mysuru"],
    "mysore": ["mysore", "mysuru"],
}


def _city_match_advanced(confirmed_city: str, biz_locality: str, biz_address: str) -> bool:
    """Match city with alias support (gurgaon=gurugram, bangalore=bengaluru etc.)"""
    c = confirmed_city.lower().strip()
    loc = biz_locality.lower()
    addr = biz_address.lower()
    if not c:
        return False
    if c in loc or loc in c or c in addr:
        return True
    for alias in _CITY_ALIASES.get(c, []):
        if alias in loc or alias in addr:
            return True
    return False


def _get_location_resource_name(session: dict) -> str:
    """
    Get locationResourceName — matches by name + city/address for accuracy.
    When multiple same-name businesses exist, city match is critical.
    API expects format: 'locations/913426026493879201'
    """
    businesses = session.get("connected_businesses", [])
    if not businesses:
        return ""

    # 1. active_location_id takes highest priority (user explicitly switched)
    active_id = session.get("active_location_id", "")
    if active_id:
        # Verify it exists in businesses list
        for b in businesses:
            loc = b.get("locationResourceName", "") or b.get("locationId", "") or b.get("id", "")
            if loc == active_id:
                print(f"[Feature] Using active business '{b['title']}' → {loc}")
                return loc

    # 2. Match by name + city from confirmed search
    found_place = session.get("found_place", {})
    confirmed_name = found_place.get("displayName", {}).get("text", "") or session.get("business_name", "")
    confirmed_city = session.get("city", "").lower()
    confirmed_address = found_place.get("formattedAddress", "").lower()

    if confirmed_name:
        confirmed_lower = confirmed_name.lower().strip()

        # First pass: name + city match
        if confirmed_city:
            for b in businesses:
                biz_title = b.get("title", "").lower().strip()
                biz_locality = b.get("locality", "").lower()
                biz_address = b.get("address", "").lower()
                name_match = (biz_title == confirmed_lower or
                              confirmed_lower in biz_title or
                              biz_title in confirmed_lower)
                city_match = _city_match_advanced(confirmed_city, biz_locality, biz_address)
                if name_match and city_match:
                    loc = b.get("locationResourceName", "") or b.get("locationId", "") or b.get("id", "")
                    if loc:
                        print(f"[Feature] Matched by name+city '{b['title']}' ({b.get('locality','')}) → {loc}")
                        return loc

        # Second pass: name only (if city didn't match)
        for b in businesses:
            biz_title = b.get("title", "").lower().strip()
            if biz_title == confirmed_lower or confirmed_lower in biz_title or biz_title in confirmed_lower:
                loc = b.get("locationResourceName", "") or b.get("locationId", "") or b.get("id", "")
                if loc:
                    print(f"[Feature] Matched by name only '{b['title']}' → {loc}")
                    return loc

    # 3. Fallback to first verified business
    for b in businesses:
        if b.get("verified"):
            loc = b.get("locationResourceName", "") or b.get("locationId", "") or b.get("id", "")
            if loc:
                print(f"[Feature] Fallback to first verified '{b.get('title','')}' → {loc}")
                return loc

    # 4. Absolute fallback
    b = businesses[0]
    loc = b.get("locationResourceName", "") or b.get("locationId", "") or b.get("id", "")
    print(f"[Feature] Absolute fallback '{b.get('title','')}' → {loc}")
    return loc