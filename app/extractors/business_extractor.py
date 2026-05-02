def extract_gmb_score(place: dict) -> dict:
    """
    Calculate preview GMB score from Google Places API data.
    Returns data in Grexa-compatible format for WhatsApp report.

    Note: Google Places has LIMITED data.
    Full accurate score comes from Limbu's health_score action after connecting.
    """
    score = 0
    data = {}

    rating = place.get("rating", 0) or 0
    reviews = place.get("userRatingCount", 0) or 0
    photos = len(place.get("photos", []))
    has_website = bool(place.get("websiteUri"))
    has_phone = bool(place.get("nationalPhoneNumber"))
    has_hours = bool(place.get("regularOpeningHours"))
    has_address = bool(place.get("formattedAddress"))
    business_status = place.get("businessStatus", "OPERATIONAL")

    # ── Profile Completion (from Places data) ─────────────────────
    total_fields = 6  # name, phone, website, hours, address, category
    filled = sum([
        True,          # name always present
        has_phone,
        has_website,
        has_hours,
        has_address,
        bool(place.get("types")),
    ])
    profile_pct = round((filled / total_fields) * 100)
    missing_fields = []
    if not has_phone:
        missing_fields.append("Phone Number")
    if not has_website:
        missing_fields.append("Website")
    if not has_hours:
        missing_fields.append("Business Hours")

    data["profile_completion"] = profile_pct
    data["profile_status"] = "Good" if profile_pct >= 90 else ("Average" if profile_pct >= 70 else "Poor")
    data["missing_fields"] = missing_fields

    # Profile score (20 pts)
    score += round(profile_pct * 0.20)

    # ── Review Score ──────────────────────────────────────────────
    data["rating"] = rating
    data["reviews"] = reviews

    # Review rate (approximate from total reviews — Places doesn't give dates)
    # Assume business listed ~1 year avg, estimate weekly rate
    estimated_weeks = 52  # 1 year
    review_rate = round(reviews / estimated_weeks, 1) if reviews else 0
    data["review_rate"] = review_rate

    # Review volume score (15 pts)
    if reviews >= 100:
        rev_vol_score = 15
    elif reviews >= 50:
        rev_vol_score = 10
    elif reviews >= 25:
        rev_vol_score = 6
    elif reviews >= 10:
        rev_vol_score = 3
    else:
        rev_vol_score = 1 if reviews > 0 else 0

    # Rating score (10 pts)
    if reviews > 0:
        if rating >= 4.5:
            rating_score = 10
        elif rating >= 4.0:
            rating_score = 7
        elif rating >= 3.5:
            rating_score = 4
        else:
            rating_score = 1
    else:
        rating_score = 0

    # Reply rate — unknown from Places, assume 0 as unknown
    data["reply_rate"] = None  # Will be None = not shown
    reply_score = 0  # unknown, flag as issue

    score += rev_vol_score + rating_score + reply_score

    # ── SEO Score (from description + categories) ─────────────────
    desc = place.get("editorialSummary", {}).get("text", "") or ""
    types = place.get("types", [])
    primary_type = place.get("primaryType", "") or (types[0] if types else "")

    # Basic SEO signals
    seo_points = 0
    if desc and len(desc) > 100:
        seo_points += 40
    elif desc:
        seo_points += 20
    if primary_type:
        seo_points += 30
    if len(types) > 2:
        seo_points += 30

    data["seo_score"] = min(seo_points, 100)
    data["seo_status"] = "Good" if seo_points >= 70 else ("Average" if seo_points >= 40 else "Poor")

    # SEO contribution to total (20 pts)
    score += round(seo_points * 0.20)

    # ── Photos (15 pts) ───────────────────────────────────────────
    data["photos"] = photos
    if photos >= 10:
        photo_score = 15
    elif photos >= 5:
        photo_score = 10
    elif photos >= 1:
        photo_score = 5
    else:
        photo_score = 0
    score += photo_score

    # ── Posts — unknown from Places (note only) ───────────────────
    data["post_activity"] = None  # unknown

    # ── Search Rank — unknown from Places ─────────────────────────
    data["search_rank"] = None  # unknown from Places API

    # ── Cap score ─────────────────────────────────────────────────
    score = min(max(score, 5), 85)  # Max 85 from Places — full 100 needs real data

    if score >= 70:
        grade, color = "Good", "🟡"
    elif score >= 50:
        grade, color = "Average", "🟠"
    elif score >= 30:
        grade, color = "Needs Work", "🔴"
    else:
        grade, color = "Poor", "🔴"

    return {
        "score": score,
        "grade": grade,
        "color": color,
        "data": data,
        # Legacy fields for compatibility
        "rating": rating,
        "reviews": reviews,
        "photos": photos,
        "issues": [],   # Not used in new format
        "strengths": [] # Not used in new format
    }