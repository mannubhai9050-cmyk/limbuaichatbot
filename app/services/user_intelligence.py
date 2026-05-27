"""
User Intelligence — Lead scoring, buying intent, personality profiling,
sales funnel tracking, objection memory, ROI projection.
Stored in Redis session — no extra DB needed.
"""
from app.services.redis_service import get_session, save_session


# ── Lead Score Signals ─────────────────────────────────────────────
POSITIVE_SIGNALS = {
    "plan": 15, "price": 15, "kitna": 15, "cost": 15, "pricing": 15,
    "franchise": 20, "invest": 20, "partner": 15, "earning": 15,
    "buy": 20, "purchase": 20, "kharidna": 15, "lena": 10,
    "connect": 10, "start": 10, "shuru": 10,
    "demo": 15, "meeting": 10, "call": 10,
    "basic": 8, "professional": 8, "premium": 8,
    "interested": 20, "intrested": 20,
}

NEGATIVE_SIGNALS = {
    "expensive": -5, "mehenga": -5, "costly": -5,
    "later": -3, "baad mein": -3, "sochna": -3,
    "not interested": -20, "nahi chahiye": -15,
    "busy": -5, "time nahi": -5,
}

# ── Personality Types ─────────────────────────────────────────────
# Detected from conversation patterns
PERSONALITY_SIGNALS = {
    "analytical": ["data", "proof", "results", "stats", "number", "report", "kitne", "kaisa"],
    "driver": ["fast", "jaldi", "abhi", "turant", "now", "quick", "seedha"],
    "amiable": ["help", "support", "samjhao", "guide", "explain", "batao"],
    "expressive": ["amazing", "great", "bahut achha", "superb", "wow", "🔥", "💯"],
}

# ── Funnel Stages ─────────────────────────────────────────────────
FUNNEL_STAGES = [
    "new",           # Just started
    "engaged",       # Business shared
    "interested",    # Business confirmed
    "analysed",      # Profile analysed
    "connected",     # GMB connected
    "features_used", # Used free features
    "plan_inquiry",  # Asked about plans
    "converted",     # Bought a plan
]


def update_user_intelligence(user_id: str, message: str):
    """Update lead score, personality, funnel stage from user message."""
    session = get_session(user_id)
    msg_lower = message.lower()

    # ── Lead Score ────────────────────────────────────────────────
    score = session.get("lead_score", 0)
    for word, points in POSITIVE_SIGNALS.items():
        if word in msg_lower:
            score = min(100, score + points)
    for word, points in NEGATIVE_SIGNALS.items():
        if word in msg_lower:
            score = max(0, score + points)
    session["lead_score"] = score

    # ── Personality Detection ─────────────────────────────────────
    personality_scores = session.get("personality_scores", {
        "analytical": 0, "driver": 0, "amiable": 0, "expressive": 0
    })
    for ptype, signals in PERSONALITY_SIGNALS.items():
        for signal in signals:
            if signal in msg_lower:
                personality_scores[ptype] = personality_scores.get(ptype, 0) + 1
    session["personality_scores"] = personality_scores
    # Dominant personality
    if any(v > 0 for v in personality_scores.values()):
        dominant = max(personality_scores, key=personality_scores.get)
        session["personality_type"] = dominant

    # ── Funnel Stage ──────────────────────────────────────────────
    current_stage = session.get("funnel_stage", "new")
    if session.get("connect_verified") and session.get("features_offered"):
        stage = "features_used"
    elif session.get("connect_verified"):
        stage = "connected"
    elif session.get("analysis"):
        if any(w in msg_lower for w in ["plan", "price", "kitna", "basic", "professional", "premium"]):
            stage = "plan_inquiry"
        else:
            stage = "analysed"
    elif session.get("confirmed"):
        stage = "interested"
    elif session.get("found_place"):
        stage = "engaged"
    else:
        stage = current_stage
    session["funnel_stage"] = stage

    # ── Objection Memory ──────────────────────────────────────────
    objections = session.get("objections", [])
    OBJECTION_TRIGGERS = {
        "mehenga": "price_concern",
        "expensive": "price_concern",
        "costly": "price_concern",
        "time nahi": "time_concern",
        "busy": "time_concern",
        "sochna": "hesitation",
        "baad mein": "delay",
        "later": "delay",
        "already": "competitor",
        "koi aur": "competitor",
    }
    for trigger, objection_type in OBJECTION_TRIGGERS.items():
        if trigger in msg_lower and objection_type not in objections:
            objections.append(objection_type)
    session["objections"] = objections

    # ── Message Count ─────────────────────────────────────────────
    session["message_count"] = session.get("message_count", 0) + 1

    save_session(user_id, session)
    return session


def get_sales_context(session: dict) -> dict:
    """Get actionable sales context for Claude."""
    lead_score = session.get("lead_score", 0)
    personality = session.get("personality_type", "amiable")
    stage = session.get("funnel_stage", "new")
    objections = session.get("objections", [])
    msg_count = session.get("message_count", 0)

    # Hot lead detection
    is_hot = lead_score >= 50
    is_cold = lead_score < 15 and msg_count > 5

    # ROI projection based on business type
    biz_name = session.get("business_name", "").lower()
    monthly_roi = _estimate_roi(biz_name, stage)

    # Closing approach based on personality
    closing_style = {
        "analytical": "data-driven — share numbers, stats, case studies",
        "driver": "direct + urgent — quick decision, clear next step",
        "amiable": "consultative — build trust, explain benefits slowly",
        "expressive": "enthusiastic — highlight transformation, success stories",
    }.get(personality, "consultative")

    # Urgency level
    urgency = "high" if is_hot else ("medium" if msg_count > 3 else "low")

    return {
        "lead_score": lead_score,
        "is_hot_lead": is_hot,
        "personality_type": personality,
        "closing_style": closing_style,
        "funnel_stage": stage,
        "objections": objections,
        "urgency_level": urgency,
        "monthly_roi_estimate": monthly_roi,
        "message_count": msg_count,
    }


def _estimate_roi(business_name: str, stage: str) -> str:
    """Estimate monthly ROI based on business type."""
    HIGH_VALUE = ["restaurant", "hotel", "clinic", "hospital", "gym", "salon", "real estate"]
    MED_VALUE = ["shop", "store", "retail", "agency", "school", "coaching"]

    for biz in HIGH_VALUE:
        if biz in business_name:
            return "₹15,000-50,000/month (high-value business)"
    for biz in MED_VALUE:
        if biz in business_name:
            return "₹5,000-15,000/month"
    return "₹3,000-10,000/month"


# ── Buying Intent Signals ──────────────────────────────────────────
BUYING_INTENT_SIGNALS = {
    # Strong buying signals
    "plan lena": 30, "plan chahiye": 25, "subscribe": 25,
    "kharidna": 25, "buy": 25, "purchase": 25,
    "kitne mein milega": 20, "payment": 20, "upi": 20, "paytm": 15,
    "invoice": 20, "bill": 15, "gst": 15,
    "start karna": 15, "shuru karna": 15, "join": 15,
    "basic plan": 20, "professional plan": 20, "premium plan": 20,
    # Weak buying signals
    "sochta": 5, "consider": 5, "dekhte": 5,
}

# ── Hesitation Signals ─────────────────────────────────────────────
HESITATION_SIGNALS = [
    "shayad", "pata nahi", "sochna", "soch raha", "sochta hoon",
    "baad mein", "later", "kal", "next week", "next month",
    "abhi nahi", "not sure", "maybe", "might", "could be",
    "zaroorat nahi", "needed nahi",
]

# ── Business Category Intelligence ────────────────────────────────
BUSINESS_CATEGORIES = {
    "restaurant": {
        "pain_points": ["reviews bahut important hain", "Google par dikhna zaroori hai lunch/dinner time mein"],
        "pitch": "Restaurants ke liye Google reviews = business. Magic QR se daily 5-10 new reviews aa sakti hain.",
        "best_plan": "professional",
        "roi": "₹20,000-80,000/month (restaurant average customer value high hota hai)",
    },
    "clinic": {
        "pain_points": ["patients Google par doctor dhundhte hain", "reviews trust build karte hain"],
        "pitch": "90% patients online clinic search karte hain. Limbu AI se aap top mein aayenge.",
        "best_plan": "professional",
        "roi": "₹15,000-50,000/month",
    },
    "gym": {
        "pain_points": ["new members chahiye", "seasonal fluctuation"],
        "pitch": "Log 'gym near me' search karte hain. Daily AI posts se aap consistently dikhenge.",
        "best_plan": "basic",
        "roi": "₹5,000-20,000/month",
    },
    "salon": {
        "pain_points": ["walk-in customers chahiye", "loyal customers banana"],
        "pitch": "Salon ke liye before/after photos + reviews = bookings. Sab automate ho sakta hai.",
        "best_plan": "basic",
        "roi": "₹5,000-15,000/month",
    },
    "real estate": {
        "pain_points": ["leads chahiye", "trust banana"],
        "pitch": "Real estate mein Google visibility = high-value leads. Professional plan best rahega.",
        "best_plan": "premium",
        "roi": "₹50,000-2,00,000/month (high ticket)",
    },
    "school": {
        "pain_points": ["admissions chahiye", "parents Google par dekhte hain"],
        "pitch": "Parents admission season mein Google par search karte hain. Top mein rahna zaroori hai.",
        "best_plan": "professional",
        "roi": "₹10,000-30,000/month",
    },
    "shop": {
        "pain_points": ["foot traffic chahiye", "online visibility"],
        "pitch": "'Shop near me' searches se daily customers aa sakte hain.",
        "best_plan": "basic",
        "roi": "₹3,000-10,000/month",
    },
}

def get_business_category(business_name: str) -> dict:
    """Detect business category and return intelligence."""
    b = business_name.lower()
    for category, data in BUSINESS_CATEGORIES.items():
        if category in b:
            return {"category": category, **data}
    # Generic fallback
    return {
        "category": "general",
        "pitch": "Har local business ko Google visibility chahiye. Limbu AI se daily AI posts + reviews automated.",
        "best_plan": "basic",
        "roi": "₹3,000-10,000/month",
    }


def update_buying_intent(user_id: str, message: str):
    """Track buying intent separately from lead score."""
    session = get_session(user_id)
    intent_score = session.get("buying_intent", 0)
    msg_lower = message.lower()
    
    for signal, points in BUYING_INTENT_SIGNALS.items():
        if signal in msg_lower:
            intent_score = min(100, intent_score + points)
    
    session["buying_intent"] = intent_score
    save_session(user_id, session)
    return intent_score


def detect_hesitation(message: str) -> bool:
    """Detect if user is hesitating."""
    msg_lower = message.lower()
    return any(h in msg_lower for h in HESITATION_SIGNALS)


def get_hesitation_response(session: dict) -> str:
    """Get smart response for hesitating user."""
    lang = session.get("lang", "hi")
    objections = session.get("objections", [])
    
    # After 2+ objections → offer discount
    if len(objections) >= 2:
        if lang == "en":
            return ("I understand you need time to decide. 😊\n\n"
                    "Quick thought — our yearly plan saves 20% (₹6,000 off on Basic!).\n"
                    "Want me to share the exact ROI calculation for your business?")
        return ("Samajh sakti hoon! 😊\n\n"
                "Ek baat bataaun — yearly plan pe 20% discount milta hai (Basic pe ₹6,000 bachenge!).\n"
                "Aapke business ke liye exact ROI calculate karoon?")
    
    if lang == "en":
        return ("No pressure at all! 😊\n\n"
                "While you think, want to see a FREE analysis of your Google profile?\n"
                "It shows exactly where you stand vs competitors — zero commitment.")
    return ("Koi tension nahi! 😊\n\n"
            "Sochte sochte, FREE profile analysis dekhna chahenge?\n"
            "Competitors se compare kar sakte hain — koi commitment nahi.")


def get_smart_cta(session: dict) -> str:
    """Get the right CTA based on current state."""
    stage = session.get("funnel_stage", "new")
    lang = session.get("lang", "hi")
    lead_score = session.get("lead_score", 0)
    
    ctas = {
        "new": ("Share apna business naam aur city! 😊", "Share your business name and city! 😊"),
        "engaged": ("Kya yeh aapka business hai?", "Is this your business?"),
        "interested": ("Kya main analyse karoon? (FREE hai)", "Shall I analyse? (FREE)"),
        "analysed": ("Is link se connect karein — 1 minute mein ho jaata hai!", "Connect in 1 minute!"),
        "connected": ("FREE Health Report lein — aapki Google ranking dikhaunga!", "Get FREE Health Report!"),
        "features_used": ("Kaunsa plan aapke liye best rahega? Main bataaun?", "Want me to recommend the best plan?"),
        "plan_inquiry": ("Abhi shuru karein — aaj hi active ho jaata hai!", "Start today — goes live immediately!"),
    }
    
    en_cta = ctas.get(stage, ("Koi sawaal? Main hoon! 😊", "Any questions? I'm here! 😊"))
    return en_cta[1] if lang == "en" else en_cta[0]