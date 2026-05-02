from app.extractors.business_extractor import extract_gmb_score
from app.services.redis_service import save_session


def handle_analyse(user_id: str, session: dict) -> str:
    place = session.get("found_place")
    lang = session.get("lang", "hi")
    en = (lang == "en")

    if not place:
        return "Please confirm your business first. 😊" if en else \
               "Pehle business confirm karna hoga. 😊"
    if not session.get("confirmed"):
        return "Please confirm if the shown business is yours. 😊" if en else \
               "Pehle business confirm karein. 😊"

    analysis = extract_gmb_score(place)
    session["analysis"] = analysis
    save_session(user_id, session)

    name = place.get("displayName", {}).get("text", "Your Business")
    data = analysis["data"]

    # ── Build Grexa-style WhatsApp report ─────────────────────────
    biz_name = name
    rating = data.get("rating", 0)
    reviews = data.get("reviews", 0)
    address = place.get("formattedAddress", "")

    # Greeting line
    if en:
        msg = f"Here's a quick look at your business, *{biz_name}*, on Google! 🚀\n\n"
    else:
        msg = f"*{biz_name}* ka Google par quick overview! 🚀\n\n"

    # Search Rank
    search_rank = data.get("search_rank")
    if search_rank:
        rank_status = "🟢 Good" if search_rank <= 5 else ("🟡 Average" if search_rank <= 10 else "🔴 Poor")
        if en:
            msg += (
                f"🔍 *Google Search Rank: {search_rank}* — {rank_status}\n"
                f"Your business appears at position *{search_rank}*. "
                + ("Great visibility!" if search_rank <= 5 else
                   "Not in top 10 — customers may not find you." if search_rank > 10 else
                   "Average position — can be improved.") + "\n\n"
            )
        else:
            msg += (
                f"🔍 *Google Search Rank: {search_rank}* — {rank_status}\n"
                f"Aapka business position *{search_rank}* par hai. "
                + ("Bahut achha!" if search_rank <= 5 else
                   "Top 10 mein nahi — customers nahi dhundh paate." if search_rank > 10 else
                   "Average position — improve ho sakta hai.") + "\n\n"
            )

    # Profile Completion
    profile_pct = data.get("profile_completion")
    profile_status = data.get("profile_status", "")
    missing_fields = data.get("missing_fields", [])
    if profile_pct is not None:
        p_icon = "✅" if profile_pct >= 90 else ("🟡" if profile_pct >= 70 else "🔴")
        p_label = "Good" if profile_pct >= 90 else ("Average" if profile_pct >= 70 else "Poor")
        missing_str = ", ".join(missing_fields) if missing_fields else ""
        if en:
            msg += (
                f"{p_icon} *Profile Completion: {profile_pct}%* — {p_label}\n"
                + (f"Missing: {missing_str}\n\n" if missing_str else "\n")
            )
        else:
            msg += (
                f"{p_icon} *Profile Completion: {profile_pct}%* — {p_label}\n"
                + (f"Missing fields: {missing_str}\n\n" if missing_str else "\n")
            )

    # SEO Score
    seo_score = data.get("seo_score")
    seo_keywords = data.get("seo_keywords", "")
    if seo_score is not None:
        s_icon = "✅" if seo_score >= 70 else ("🟡" if seo_score >= 40 else "🔴")
        s_label = "Good" if seo_score >= 70 else ("Average" if seo_score >= 40 else "Poor")
        if en:
            msg += (
                f"{s_icon} *SEO Score: {seo_score}%* — {s_label}\n"
                f"{'Keywords are well optimized!' if seo_score >= 70 else 'Add more relevant keywords to your profile.'}\n\n"
            )
        else:
            msg += (
                f"{s_icon} *SEO Score: {seo_score}%* — {s_label}\n"
                f"{'Keywords sahi hain!' if seo_score >= 70 else 'Profile mein aur relevant keywords add karein.'}\n\n"
            )

    # Review Rate
    review_rate = data.get("review_rate")  # e.g. "1 review every 3 weeks" or 0.3 per week
    if review_rate is not None:
        r_icon = "✅" if float(review_rate) >= 2 else ("🟡" if float(review_rate) >= 1 else "🔴")
        r_label = "Good" if float(review_rate) >= 2 else ("Average" if float(review_rate) >= 1 else "Poor")
        if en:
            msg += (
                f"{r_icon} *Review Rate: {review_rate}/week* — {r_label}\n"
                f"Rating: *{rating}/5* from *{reviews} reviews*\n"
                f"{'Great review frequency!' if float(review_rate) >= 2 else 'Ideal is 2+ reviews per week. Use Magic QR to collect more!'}\n\n"
            )
        else:
            msg += (
                f"{r_icon} *Review Rate: {review_rate}/week* — {r_label}\n"
                f"Rating: *{rating}/5* — {reviews} reviews\n"
                f"{'Review frequency achha hai!' if float(review_rate) >= 2 else 'Ideal: 2+ reviews per week. Magic QR se zyada reviews collect karo!'}\n\n"
            )
    else:
        # Fallback from Places data
        r_icon = "✅" if reviews >= 50 else ("🟡" if reviews >= 20 else "🔴")
        r_label = "Good" if reviews >= 50 else ("Average" if reviews >= 20 else "Poor")
        if en:
            msg += (
                f"{r_icon} *Reviews: {reviews}* — {r_label} | Rating: *{rating}/5*\n"
                f"{'Great review count!' if reviews >= 50 else 'Need more reviews. Magic QR helps collect them automatically!'}\n\n"
            )
        else:
            msg += (
                f"{r_icon} *Reviews: {reviews}* — {r_label} | Rating: *{rating}/5*\n"
                f"{'Reviews bahut achhe hain!' if reviews >= 50 else 'Aur reviews chahiye. Magic QR se automatically collect karo!'}\n\n"
            )

    # Review Reply Score
    reply_pct = data.get("reply_rate")
    if reply_pct is not None:
        rr_icon = "✅" if float(reply_pct) >= 80 else ("🟡" if float(reply_pct) >= 50 else "🔴")
        rr_label = "Good" if float(reply_pct) >= 80 else ("Average" if float(reply_pct) >= 50 else "Poor")
        if en:
            msg += f"{rr_icon} *Review Reply Score: {reply_pct}%* — {rr_label}\n"
            msg += ("You reply to all your reviews — Google loves this! 🙌\n\n" if float(reply_pct) >= 80 else
                    "Reply to all reviews to build customer trust.\n\n")
        else:
            msg += f"{rr_icon} *Review Reply Score: {reply_pct}%* — {rr_label}\n"
            msg += ("Aap sabhi reviews ka reply karte ho — Google ko yeh pasand hai! 🙌\n\n" if float(reply_pct) >= 80 else
                    "Sabhi reviews ka reply karo — customer trust badhta hai.\n\n")

    # Overall Score
    score = analysis["score"]
    grade = analysis["grade"]
    color = analysis["color"]
    msg += f"━━━━━━━━━━━━━━━━━━━━\n"
    if en:
        msg += f"📊 *Overall Score: {score}/100* — {grade} {color}\n\n"
        msg += "Would you like to connect with Limbu.ai to get the *Full Detailed Report* and improve your ranking? 😊"
    else:
        msg += f"📊 *Overall Score: {score}/100* — {grade} {color}\n\n"
        msg += "Kya main Limbu.ai se connect karne ka link bhejoon taaki *Full Detailed Report* mile aur ranking improve ho? 😊"

    return msg