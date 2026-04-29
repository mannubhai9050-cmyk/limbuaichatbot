from app.extractors.business_extractor import extract_gmb_score
from app.services.redis_service import save_session, get_session


def handle_analyse(user_id: str, session: dict) -> str:
    place = session.get("found_place")
    lang = session.get("lang", "hi")
    en = (lang == "en")

    if not place:
        return "Please confirm your business first. 😊" if en else "Pehle business confirm karna hoga. 😊"
    if not session.get("confirmed"):
        return "Please confirm if the business I found is yours. 😊" if en else "Pehle business confirm karein. 😊"

    analysis = extract_gmb_score(place)
    session["analysis"] = analysis
    save_session(user_id, session)

    name = place.get("displayName", {}).get("text", "Your Business")
    score = analysis["score"]
    grade = analysis["grade"]
    color = analysis["color"]

    issues_text = "\n".join([f"  • {i}" for i in analysis["issues"]]) if analysis["issues"] else ("  • No major issues!" if en else "  • Koi major issue nahi!")
    strengths_text = "\n".join([f"  • {s}" for s in analysis["strengths"]]) if analysis["strengths"] else ("  • Keep building!" if en else "  • Profile build karte rahein")

    if score >= 80:
        growth_msg = "Profile is strong, but consistent growth needs automation! 💪" if en else "Profile strong hai, lekin growth ke liye automation zaroori hai! 💪"
    elif score >= 55:
        growth_msg = "Profile is average — improvements can significantly grow your business." if en else "Profile average hai — improvements se business grow kar sakta hai."
    else:
        growth_msg = "Profile has significant gaps that are stopping customers from finding you." if en else "Profile mein kaafi gaps hain jo customers ko rok rahi hain."

    if en:
        report = (
            f"*Google Business Profile — {name}*\n\n"
            f"📊 Score: *{score}/100* — {grade} {color}\n\n"
            f"{growth_msg}\n\n"
            f"*Needs improvement:*\n{issues_text}\n\n"
            f"*What's working:*\n{strengths_text}\n\n"
            f"*FREE with Limbu.ai:*\n"
            f"  • Health Report → complete GMB analysis\n"
            f"  • Magic QR → automatic reviews\n"
            f"  • AI Review Reply → build customer trust\n"
            f"  • Google Insights → performance data\n"
            f"  • Free Website → online presence (no charge)\n\n"
            f"💡 *Best Plan:* {analysis['plan']}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Shall I send you the link to connect with Limbu.ai and try these FREE features? 😊"
        )
    else:
        report = (
            f"*Google Business Profile — {name}*\n\n"
            f"📊 Score: *{score}/100* — {grade} {color}\n\n"
            f"{growth_msg}\n\n"
            f"*Improve karna hai:*\n{issues_text}\n\n"
            f"*Acha chal raha hai:*\n{strengths_text}\n\n"
            f"*Limbu.ai se FREE mein milega:*\n"
            f"  • Health Report → complete GMB analysis\n"
            f"  • Magic QR → automatic reviews\n"
            f"  • AI Review Reply → customer trust\n"
            f"  • Google Insights → performance data\n"
            f"  • Free Website → online presence (koi charge nahi)\n\n"
            f"💡 *Best Plan:* {analysis['plan']}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Kya main aapko Limbu.ai se connect karne ka link bhejoon taaki FREE features try kar sakein? 😊"
        )

    return report