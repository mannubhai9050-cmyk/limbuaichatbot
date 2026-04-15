from app.extractors.business_extractor import extract_gmb_score
from app.services.redis_service import save_session
from app.core.config import LIMBU_CONNECT_URL


def handle_analyse(user_id: str, session: dict) -> str:
    place = session.get("found_place")

    if not place:
        return "Pehle aapka business confirm karna hoga. Business naam aur city batayein? 😊"

    if not session.get("confirmed"):
        return "Kya jo business maine dhundha woh aapka hai? Ek baar confirm kar dein. 😊"

    analysis = extract_gmb_score(place)
    session["analysis"] = analysis
    save_session(user_id, session)

    name = place.get("displayName", {}).get("text", "Your Business")
    score = analysis["score"]
    grade = analysis["grade"]
    color = analysis["color"]

    issues_text = "\n".join([f"  • {i}" for i in analysis["issues"]]) if analysis["issues"] else "  • No major issues found!"
    strengths_text = "\n".join([f"  • {s}" for s in analysis["strengths"]]) if analysis["strengths"] else "  • Keep building your profile"

    # Growth message based on score
    if score == 100:
        growth_msg = (
            "🌟 Profile setup is perfect! But remember — setup aur growth alag hain.\n"
            "Daily posts, automated reviews, aur social media se aapki reach 3-4x badh sakti hai.\n"
            "Ek extra customer booking se poora plan ka cost nikal aata hai!"
        )
    elif score >= 80:
        growth_msg = "Profile strong hai, but consistent growth ke liye automation zaroori hai! 💪"
    elif score >= 55:
        growth_msg = "Profile average hai — improvements se business significantly grow kar sakta hai."
    else:
        growth_msg = "Profile mein kaafi gaps hain jo aapke customers ko rok rahi hain."

    report = f"""**Google Business Profile — {name}**

📊 Score: **{score}/100** — {grade} {color}

{growth_msg}

**Needs Improvement:**
{issues_text}

**Working Well:**
{strengths_text}

**How Limbu.ai helps:**
  • Daily AI posts → better 'near me' ranking
  • Magic QR → automatic review collection
  • AI review replies → builds customer trust
  • Social media automation → wider reach

💡 **Best Plan:** {analysis['plan']}

━━━━━━━━━━━━━━━━━━━━━━━━
🔗 **Apna business Limbu.ai se connect karein:**
{LIMBU_CONNECT_URL}

Connect karein taaki hum directly aapki profile manage karein aur growth track karein. Jab connect ho jaye, mujhe batayein! 😊"""

    return report