from datetime import datetime, timezone


def extract_gmb_score(place: dict) -> dict:
    score = 0
    data = {}

    rating        = place.get("rating", 0) or 0
    reviews_count = place.get("userRatingCount", 0) or 0
    reviews_list  = place.get("reviews", [])
    photos_list   = place.get("photos", [])
    photos        = len(photos_list)
    has_website   = bool(place.get("websiteUri"))
    has_phone     = bool(place.get("nationalPhoneNumber") or place.get("internationalPhoneNumber"))
    has_hours     = bool(place.get("regularOpeningHours"))
    has_address   = bool(place.get("formattedAddress"))
    has_name      = bool(place.get("displayName", {}).get("text"))
    types         = place.get("types", [])
    primary_type  = (
        place.get("primaryType") or
        place.get("primaryTypeDisplayName", {}).get("text") or
        (types[0] if types else "")
    )

    # 1. Profile Completion (25 pts)
    profile_checks = {
        "Name": has_name, "Phone Number": has_phone, "Website": has_website,
        "Business Hours": has_hours, "Address": has_address,
        "Category": bool(primary_type), "Photos": photos > 0,
    }
    filled = sum(profile_checks.values())
    profile_pct = round((filled / len(profile_checks)) * 100)
    missing_fields = [k for k, v in profile_checks.items() if not v]
    data["profile_completion"] = profile_pct
    data["profile_status"] = "Good" if profile_pct >= 90 else ("Average" if profile_pct >= 70 else "Poor")
    data["missing_fields"] = missing_fields
    score += round(profile_pct * 0.25)

    # 2. Reviews & Rating (25 pts)
    data["rating"] = rating
    data["reviews"] = reviews_count
    review_rate = _calculate_review_rate(reviews_list, reviews_count)
    data["review_rate"] = review_rate

    if reviews_count >= 200: rev_vol_score = 12
    elif reviews_count >= 100: rev_vol_score = 10
    elif reviews_count >= 50: rev_vol_score = 7
    elif reviews_count >= 25: rev_vol_score = 4
    elif reviews_count >= 10: rev_vol_score = 2
    elif reviews_count > 0: rev_vol_score = 1
    else: rev_vol_score = 0

    if reviews_count > 0:
        if rating >= 4.5: rating_score = 13
        elif rating >= 4.0: rating_score = 10
        elif rating >= 3.5: rating_score = 6
        elif rating >= 3.0: rating_score = 2
        else: rating_score = 0
    else:
        rating_score = 0

    score += rev_vol_score + rating_score

    # 3. Review Reply Rate (20 pts)
    reply_rate, replied, total_fetched = _calculate_reply_rate(reviews_list)
    data["reply_rate"] = reply_rate
    data["replied_count"] = replied
    data["fetched_reviews"] = total_fetched

    if reply_rate is not None:
        if reply_rate >= 80: reply_score = 20
        elif reply_rate >= 60: reply_score = 14
        elif reply_rate >= 40: reply_score = 8
        elif reply_rate >= 20: reply_score = 4
        else: reply_score = 0
    else:
        reply_score = 0
    score += reply_score

    # 4. Photos (15 pts)
    data["photos"] = photos
    if photos >= 10: photo_score = 15
    elif photos >= 5: photo_score = 10
    elif photos >= 1: photo_score = 5
    else: photo_score = 0
    score += photo_score

    # 5. SEO / Categories (15 pts)
    GENERIC_TYPES = {"point_of_interest", "establishment", "food", "store", "locality", "political", "geocode"}
    specific_types = [t for t in types if t not in GENERIC_TYPES]
    seo_points = 0
    if primary_type: seo_points += 5
    if len(specific_types) >= 2: seo_points += 5
    if has_website: seo_points += 5
    seo_score = min(seo_points, 15)
    score += seo_score

    seo_pct = round((seo_points / 15) * 100)
    kw_display = (
        ", ".join(t.replace("_", " ").title() for t in specific_types[:3])
        if specific_types else "Keywords missing"
    )
    data["seo_score"] = seo_pct
    data["seo_status"] = "Good" if seo_pct >= 70 else ("Average" if seo_pct >= 40 else "Poor")
    data["seo_keywords"] = kw_display
    data["search_rank"] = None
    data["post_activity"] = None

    score = min(max(score, 5), 100)
    if score >= 75: grade, color = "Good", "🟢"
    elif score >= 50: grade, color = "Average", "🟡"
    elif score >= 30: grade, color = "Needs Work", "🟠"
    else: grade, color = "Poor", "🔴"

    return {
        "score": score, "grade": grade, "color": color, "data": data,
        "rating": rating, "reviews": reviews_count, "photos": photos,
        "issues": [], "strengths": [],
    }


def _calculate_review_rate(reviews_list: list, total_reviews: int) -> float:
    if not reviews_list or total_reviews == 0:
        return 0.0
    timestamps = []
    for r in reviews_list:
        pt = r.get("publishTime")
        if pt:
            try:
                dt = datetime.fromisoformat(pt.replace("Z", "+00:00"))
                timestamps.append(dt)
            except Exception:
                pass
    if len(timestamps) < 2:
        return round(total_reviews / 78, 1)
    timestamps.sort()
    span_days = (timestamps[-1] - timestamps[0]).days
    if span_days < 7:
        return round(total_reviews / 78, 1)
    sample_rate_per_week = (len(timestamps) / span_days) * 7
    if sample_rate_per_week > 0:
        est_total_weeks = total_reviews / sample_rate_per_week
        return round(total_reviews / est_total_weeks, 1)
    return round(total_reviews / 78, 1)


def _calculate_reply_rate(reviews_list: list):
    if not reviews_list:
        return None, 0, 0
    total = len(reviews_list)
    replied = sum(1 for r in reviews_list if r.get("ownerResponse"))
    rate = round((replied / total) * 100) if total > 0 else None
    return rate, replied, total