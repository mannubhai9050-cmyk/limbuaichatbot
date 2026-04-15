def extract_gmb_score(place: dict) -> dict:
    """
    Analyse Google Business Profile completeness.
    Returns score, issues, strengths.
    """
    issues = []
    strengths = []
    score = 0

    rating = place.get("rating", 0)
    reviews = place.get("userRatingCount", 0)
    photos = len(place.get("photos", []))

    # Rating (20 pts)
    if rating >= 4.0:
        strengths.append(f"Good rating ({rating}/5)")
        score += 20
    elif rating > 0:
        issues.append(f"Rating needs improvement ({rating}/5) — encourage positive reviews")
        score += 5
    else:
        issues.append("No rating yet — start collecting reviews immediately")

    # Reviews (20 pts)
    if reviews >= 50:
        strengths.append(f"Strong review count ({reviews} reviews)")
        score += 20
    elif reviews > 0:
        issues.append(f"Low review count ({reviews}) — target minimum 50 reviews")
        score += 10
    else:
        issues.append("No reviews — use Magic QR to collect reviews")

    # Photos (20 pts)
    if photos >= 10:
        strengths.append(f"Good photo gallery ({photos} photos)")
        score += 20
    elif photos > 0:
        issues.append(f"Insufficient photos ({photos}) — add 10+ quality images")
        score += 10
    else:
        issues.append("No photos — add business photos to improve click-through rate")

    # Website (15 pts)
    if place.get("websiteUri"):
        strengths.append("Website linked to profile")
        score += 15
    else:
        issues.append("No website linked — reduces credibility and SEO ranking")

    # Phone (10 pts)
    if place.get("nationalPhoneNumber"):
        strengths.append("Phone number available")
        score += 10
    else:
        issues.append("Phone number missing — customers cannot contact directly")

    # Hours (15 pts)
    if place.get("regularOpeningHours"):
        strengths.append("Business hours are set")
        score += 15
    else:
        issues.append("Business hours not set — customers don't know when you're open")

    # Grade
    score = min(score, 100)
    if score >= 80:
        grade, color, plan = "Excellent", "🟢", "Premium Plan (₹7,500/month) — Advanced automation to stay ahead"
    elif score >= 55:
        grade, color, plan = "Good", "🟡", "Professional Plan (₹5,500/month) — Review management, insights, 30 GMB posts"
    else:
        grade, color, plan = "Needs Improvement", "🔴", "Basic Plan (₹2,500/month) — GMB posts, Magic QR, citations"

    return {
        "score": score,
        "grade": grade,
        "color": color,
        "plan": plan,
        "issues": issues,
        "strengths": strengths,
        "rating": rating,
        "reviews": reviews,
        "photos": photos
    }