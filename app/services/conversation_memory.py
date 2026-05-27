"""
Conversation Memory — Summary, context compression, objection memory.
Prevents long conversations from losing context.
"""
from app.services.redis_service import get_session, save_session, get_history


def get_conversation_summary(user_id: str) -> str:
    """
    Get compressed conversation summary for long chats.
    After 15 messages, summarize older context.
    """
    session = get_session(user_id)
    history = get_history(user_id)

    if len(history) < 15:
        return ""

    # Return cached summary if exists
    cached = session.get("conversation_summary", "")
    if cached and len(history) < session.get("summary_at_count", 0) + 10:
        return cached

    # Build summary from key facts
    summary_parts = []

    if session.get("business_name"):
        summary_parts.append(f"Business: {session['business_name']}")
    if session.get("city"):
        summary_parts.append(f"City: {session['city']}")
    if session.get("confirmed"):
        summary_parts.append("Business confirmed ✓")
    if session.get("analysis"):
        score = session["analysis"].get("score", 0)
        summary_parts.append(f"Profile score: {score}/100")
    if session.get("connect_verified"):
        summary_parts.append("GMB connected ✓")
    if session.get("features_offered"):
        summary_parts.append(f"Features given: {session['features_offered']}")
    if session.get("funnel_stage"):
        summary_parts.append(f"Stage: {session['funnel_stage']}")
    if session.get("objections"):
        summary_parts.append(f"Objections: {session['objections']}")
    if session.get("lead_score"):
        summary_parts.append(f"Lead score: {session['lead_score']}/100")

    summary = " | ".join(summary_parts)

    # Cache it
    session["conversation_summary"] = summary
    session["summary_at_count"] = len(history)
    save_session(user_id, session)

    return summary


def get_smart_history(user_id: str, max_messages: int = 12) -> list:
    """
    Get recent history with intelligent compression.
    Keeps last N messages + injects summary of older context.
    """
    history = get_history(user_id)

    if len(history) <= max_messages:
        return history

    # Get summary of older messages
    summary = get_conversation_summary(user_id)

    # Return last N messages
    recent = history[-max_messages:]

    # Prepend summary as system context if available
    if summary:
        recent = [{"role": "system", "content": f"[CONVERSATION SUMMARY: {summary}]"}] + recent

    return recent


def save_objection(user_id: str, objection: str):
    """Remember user's objection for smart handling later."""
    session = get_session(user_id)
    objections = session.get("objections", [])
    if objection not in objections:
        objections.append(objection)
        session["objections"] = objections[-5:]  # Keep last 5
        save_session(user_id, session)


def get_objection_response(objection_type: str, lang: str = "hi") -> str:
    """Get smart response for known objections."""
    responses = {
        "price_concern": {
            "hi": "Samajh sakti hoon! 😊 Rs 2,500/month = Rs 83/day. Ek customer roz aaye to ROI cover. Plus yearly plan pe 20% discount milta hai!",
            "en": "I understand! Rs 2,500/month = Rs 83/day. Just one extra customer daily covers it. Plus 20% off on yearly plan!"
        },
        "time_concern": {
            "hi": "Bilkul no tension! 😊 Limbu AI poora automatically kaam karta hai — posts, reviews, sab AI handle karta hai. Aapko kuch nahi karna.",
            "en": "No worries at all! 😊 Limbu AI handles everything automatically — posts, reviews, all AI-managed. You don't need to do anything."
        },
        "delay": {
            "hi": "Zaroor sochiye! 😊 Lekin competitors abhi bhi kaam kar rahe hain. Har din delay = Google par unse peeche rehna. FREE health report se shuru karte hain — koi commitment nahi.",
            "en": "Of course, take your time! 😊 Just know competitors are working daily. Each day delayed = falling behind on Google. Start with FREE health report — zero commitment."
        },
        "competitor": {
            "hi": "Koi baat nahi! 😊 Kya woh daily AI-generated posts daal rahe hain? Limbu AI 30-45 posts/month automatically publish karta hai + Magic QR + reviews. Compare karo free mein?",
            "en": "That's fine! 😊 Are they posting daily AI-generated content? Limbu AI publishes 30-45 posts/month automatically + Magic QR + reviews. Want a free comparison?"
        },
    }
    r = responses.get(objection_type, {})
    return r.get(lang, r.get("hi", ""))


# ── Dynamic Urgency Engine ─────────────────────────────────────────
def get_urgency_message(session: dict) -> str:
    """Generate urgency message based on context."""
    lang = session.get("lang", "hi")
    biz_city = session.get("city", "aapki city")
    msg_count = session.get("message_count", 0)
    
    import random
    urgency_msgs_hi = [
        f"Aapke competitors {biz_city} mein daily 30-45 AI posts daal rahe hain. Aap?",
        "Google algorithm fresh content ko reward karta hai. Har din delay = ranking drop.",
        "Is mahine 3 new businesses aapke area mein Limbu AI join kar chuke hain.",
        "GMB profile jo daily active hai, wo 5x zyada customers attract karta hai.",
    ]
    urgency_msgs_en = [
        f"Your competitors in {biz_city} are posting 30-45 AI posts daily. Are you?",
        "Google rewards fresh content. Every day delayed = ranking drop.",
        "3 new businesses in your area joined Limbu AI this month.",
        "Active GMB profiles attract 5x more customers.",
    ]
    
    msgs = urgency_msgs_en if lang == "en" else urgency_msgs_hi
    # Rotate based on message count
    return msgs[msg_count % len(msgs)]


# ── Smart Discount Engine ──────────────────────────────────────────
def should_offer_discount(session: dict) -> bool:
    """Offer discount after 2+ price objections or long hesitation."""
    objections = session.get("objections", [])
    msg_count = session.get("message_count", 0)
    
    price_objections = objections.count("price_concern")
    delay_objections = objections.count("delay")
    
    return (price_objections >= 1 or delay_objections >= 2 or msg_count >= 15)


def get_discount_offer(session: dict) -> str:
    """Smart discount offer based on context."""
    lang = session.get("lang", "hi")
    objections = session.get("objections", [])
    
    if "price_concern" in objections:
        if lang == "en":
            return ("Special offer for you: Yearly plan gives *20% discount* + we'll set up your first month FREE! 🎁\n"
                    "That's ₹6,000 saved on Basic plan. Want to lock this in today?")
        return ("Aapke liye special: Yearly plan pe *20% discount* + pehla mahina FREE setup! 🎁\n"
                "Basic plan pe ₹6,000 ki bachatt. Aaj hi lock karein?")
    else:
        if lang == "en":
            return "Quarterly plan gives 10% off — that's ₹750 saved every 3 months! Want details?"
        return "Quarterly plan pe 10% off — har 3 mahine ₹750 bachenge! Details chahiye?"


# ── Competitor Intelligence ────────────────────────────────────────
COMPETITOR_DATA = {
    "dhanda ai": {
        "weakness": "Basic tool — no AI automation, no keyword research, no social media management",
        "limbu_advantage": "Limbu AI = full automation + AI posts + social media + review management + Magic QR",
        "pitch_hi": "Dhanda AI basic tool hai. Limbu AI mein AI automation, keyword research, social media management sab hai.",
        "pitch_en": "Dhanda AI is a basic tool. Limbu AI has full AI automation, keyword research, social media — complete ecosystem.",
    },
    "grexa": {
        "weakness": "CRM + WhatsApp focused — limited GMB optimization",
        "limbu_advantage": "Limbu AI = GMB specialist + local SEO + AI content + social + review + Magic QR",
        "pitch_hi": "Grexa mainly CRM hai. Limbu AI Google Business pe specialist hai — local SEO, AI posts, Magic QR sab included.",
        "pitch_en": "Grexa is mainly CRM. Limbu AI specializes in Google Business — local SEO, AI posts, Magic QR all included.",
    },
}

def get_competitor_response(competitor_name: str, lang: str = "hi") -> str:
    """Get smart competitor comparison response."""
    c_lower = competitor_name.lower()
    for key, data in COMPETITOR_DATA.items():
        if key in c_lower:
            return data[f"pitch_{lang}"] if f"pitch_{lang}" in data else data["pitch_hi"]
    return ""


# ── Abandonment Recovery ───────────────────────────────────────────
def get_abandonment_recovery(session: dict) -> str:
    """Smart message when user drops off mid-conversation."""
    lang = session.get("lang", "hi")
    stage = session.get("funnel_stage", "new")
    biz = session.get("business_name", "")
    
    recovery = {
        "engaged": {
            "hi": f"Kya *{biz}* ko Google par grow karna chahte ho? FREE analysis abhi bhi available hai! 😊",
            "en": f"Want to grow *{biz}* on Google? FREE analysis still available! 😊",
        },
        "interested": {
            "hi": f"*{biz}* ki Google profile analyse karni thi — abhi bhi FREE hai! 📊",
            "en": f"*{biz}* profile analysis was pending — still FREE! 📊",
        },
        "analysed": {
            "hi": f"*{biz}* connect karna baaki tha — ek click mein ho jaata hai! 🔗",
            "en": f"*{biz}* connection was pending — takes just one click! 🔗",
        },
        "connected": {
            "hi": "Aapki FREE features abhi bhi available hain! Health Report, Magic QR, Website — sab FREE. 🎁",
            "en": "Your FREE features are still waiting! Health Report, Magic QR, Website — all FREE. 🎁",
        },
    }
    
    r = recovery.get(stage, {})
    return r.get(lang, r.get("hi", ""))


# ── Natural Interruption Handler ───────────────────────────────────
OOT_PATTERNS = [
    "kya time hai", "what time", "weather", "mausam",
    "joke", "mazak", "funny",
    "aap kaun", "who are you", "aap kahan se",
    "help me with", "suggest", "recommend",
]

def is_off_topic(message: str) -> bool:
    """Detect if user went completely off-topic."""
    msg_lower = message.lower()
    return any(p in msg_lower for p in OOT_PATTERNS)