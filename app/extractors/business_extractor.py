def extract_gmb_score(place: dict) -> dict:
    """Calculate GMB profile completeness score from Google Places data"""
    issues = []
    strengths = []
    score = 0

    rating = place.get("rating", 0)
    reviews = place.get("userRatingCount", 0)
    photos = len(place.get("photos", []))

    # Rating (20 pts)
    if rating >= 4.0:
        strengths.append(f"Acha rating ({rating}/5)")
        score += 20
    elif rating > 0:
        issues.append(f"Rating improve karni hai ({rating}/5) — positive reviews collect karo")
        score += 5
    else:
        issues.append("Koi rating nahi — Magic QR se reviews lao")

    # Reviews (20 pts)
    if reviews >= 50:
        strengths.append(f"Bahut reviews hain ({reviews})")
        score += 20
    elif reviews > 0:
        issues.append(f"Kam reviews ({reviews}) — minimum 50 target karo")
        score += 10
    else:
        issues.append("Koi review nahi — Magic QR se shuru karo")

    # Photos (20 pts)
    if photos >= 10:
        strengths.append(f"Achi photos hain ({photos})")
        score += 20
    elif photos > 0:
        issues.append(f"Kam photos ({photos}) — 10+ quality images add karo")
        score += 10
    else:
        issues.append("Koi photo nahi — business photos add karo")

    # Website (15 pts)
    if place.get("websiteUri"):
        strengths.append("Website linked hai")
        score += 15
    else:
        issues.append("Website nahi linked — credibility aur SEO weak hai")

    # Phone (10 pts)
    if place.get("nationalPhoneNumber"):
        strengths.append("Phone number available hai")
        score += 10
    else:
        issues.append("Phone number missing — customers contact nahi kar sakte")

    # Hours (15 pts)
    if place.get("regularOpeningHours"):
        strengths.append("Business hours set hain")
        score += 15
    else:
        issues.append("Business hours set nahi — customers ko pata nahi kab open ho")

    score = min(score, 100)

    if score >= 80:
        grade, color = "Excellent", "🟢"
        plan = "Premium Plan (₹7,500/month) — Advanced automation"
    elif score >= 55:
        grade, color = "Good", "🟡"
        plan = "Professional Plan (₹5,500/month) — Review management, insights, 30 GMB posts"
    else:
        grade, color = "Needs Improvement", "🔴"
        plan = "Basic Plan (₹2,500/month) — GMB posts, Magic QR, citations"

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