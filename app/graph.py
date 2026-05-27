import re
import threading
import time
from typing import TypedDict
from langgraph.graph import StateGraph, END

from app.nodes.intent import detect_and_respond
from app.nodes.search import handle_search, handle_next_result
from app.nodes.analyse import handle_analyse
from app.nodes.booking import handle_booking
from app.nodes.connect import handle_connect_link, handle_check_latest_connection, handle_check_email
from app.nodes.social_connect import handle_social_connect_link, handle_check_social_connection
from app.nodes.franchise import handle_franchise_register
from app.services.user_intelligence import (update_user_intelligence, get_sales_context,
    detect_hesitation, get_hesitation_response, get_smart_cta,
    update_buying_intent, get_business_category)
from app.services.conversation_memory import (get_smart_history, get_objection_response,
    get_urgency_message, should_offer_discount, get_discount_offer,
    get_competitor_response, get_abandonment_recovery, is_off_topic)
from app.nodes.features import handle_feature, FEATURE_SEQUENCE
from app.services.limbu_api import check_user_by_phone
from app.services.redis_service import save_message, get_session, save_session, get_history
from app.extractors.entity_extractor import extract_action_params, extract_email
from app.core.llm import llm
from app.core.prompts import get_main_prompt
from langchain_core.messages import SystemMessage, HumanMessage

# ── Per-user lock ─────────────────────────────────────────────────
_user_locks: dict = {}
_locks_mutex = threading.Lock()

def _get_user_lock(user_id: str) -> threading.Lock:
    with _locks_mutex:
        if user_id not in _user_locks:
            _user_locks[user_id] = threading.Lock()
        return _user_locks[user_id]


# ── LLM helper — language-aware, strips action tags ───────────────
def _llm_interpret_intent(user_id: str, message: str, context: str = "") -> str:
    """
    Fast LLM call to interpret ambiguous user message.
    Returns: "yes" | "no" | "other"
    Context: "business_confirm" | "analyse_confirm"
    """
    try:
        session = get_session(user_id)
        place = session.get("found_place", {}) or {}
        biz_name = place.get("displayName", {}).get("text", "this business")

        if context == "business_confirm":
            system = (
                "You are interpreting if a user is confirming or denying their business. "
                f"The business shown is: {biz_name}. "
                "Reply with ONLY one word: 'yes' if they are confirming, 'no' if denying, 'other' if unclear."
            )
        else:
            system = (
                "Interpret user intent. "
                "Reply ONLY: 'yes' to proceed, 'no' to decline, 'other' if unclear."
            )

        response = llm.invoke([
            SystemMessage(content=system),
            HumanMessage(content=message)
        ])
        result = response.content.strip().lower().split()[0]
        print(f"[IntentLLM] '{message}' → {result}")
        if result in ("yes", "no", "other"):
            return result
        return "other"
    except Exception as e:
        print(f"[IntentLLM] Error: {e}")
        return "other"


def _llm_reply(user_id: str, instruction: str) -> str:
    """Generate a conversational reply using Claude/OpenAI with RAG context."""
    session = get_session(user_id)
    history = get_history(user_id)
    last_user_msg = ""
    for msg in reversed(history):
        if msg.get("role") == "user":
            last_user_msg = msg.get("content", "")
            break

    # RAG: get relevant knowledge base context
    rag_context = ""
    try:
        from app.services.knowledge_base import get_rag_context
        rag_context = get_rag_context(last_user_msg or instruction, top_k=2)
    except Exception:
        pass

    messages = [
        SystemMessage(content=get_main_prompt(session, rag_context=rag_context)),
        HumanMessage(content=last_user_msg or "hello"),
        HumanMessage(content=(
            f"[SYSTEM INSTRUCTION: {instruction}. "
            f"Reply MUST be in the exact same language/script the user wrote in. "
            f"You are Priya — always use female Hindi verb forms: karungi, bataungi, bhejungi, doongi. "
            f"IMPORTANT: Write ONLY the conversational reply text. "
            f"Do NOT include any [ACTION:...][/ACTION] tags in your reply.]"
        ))
    ]
    response = llm.invoke(messages)
    reply = response.content.strip()
    # Strip any action tags Claude accidentally included
    reply = re.sub(r'\[ACTION:[A-Z_]+\].*?\[/ACTION\]', '', reply, flags=re.DOTALL).strip()
    return reply


# ── Template name → context mapping ─────────────────────────────
TEMPLATE_CONTEXTS = {
    "franchise_msg": {
        "type": "franchise",
        "interested_reply": "Bahut achha! Limbu.ai franchise mein interested hain aap!\n\nHamare team member aapko jald call karega.\nYa abhi call karein: 9289344726",
        "not_interested_reply": "Koi baat nahi! Agar kabhi consider karna ho to 9289344726 pe contact kar sakte hain.",
    },
    "demo_session_confirmation": {
        "type": "demo",
        "interested_reply": "Demo confirm ho gaya! Hamar team aapke scheduled time par aayega. Koi sawal: 9289344726",
        "not_interested_reply": "Koi baat nahi! Reschedule ke liye 9289344726 pe call karein.",
    },
    "copy_of_service_availability_response_new": {
        "type": "service",
        "interested_reply": "Service confirm ho gayi! Hamar technician jald aayega. Tracking: 9289344726",
        "not_interested_reply": "Theek hai! Baad mein service chahiye to 9289344726 pe call karein.",
    },
    "service_availability_response_new": {
        "type": "service",
        "interested_reply": "Service confirmed! Our technician will arrive shortly. Contact: 9289344726",
        "not_interested_reply": "No problem! Call us at 9289344726 whenever you need service.",
    },
    "vendor_service_availability": {
        "type": "service",
        "interested_reply": "Service confirmed! Our team will reach you soon. 9289344726",
        "not_interested_reply": "Understood! Contact us at 9289344726 whenever needed.",
    },
    "welcome_msg": {
        "type": "welcome",
        "interested_reply": "Namaste! Limbu.ai mein aapka swagat hai!\n\nMain Priya hoon. Apna business naam aur city batayein! 😊",
        "not_interested_reply": "Theek hai! Agar kabhi help chahiye to wapas aa sakte hain. 😊",
    },
    "call_back": {
        "type": "callback",
        "interested_reply": "Callback registered! Hamar team jald call karega. 9289344726",
        "not_interested_reply": "Theek hai! Zaroorat ho to 9289344726 pe call karein.",
    },
    "callback_later_after_call": {
        "type": "callback",
        "interested_reply": "Callback scheduled! We will call you back shortly. 9289344726",
        "not_interested_reply": "Alright! Feel free to call us at 9289344726 anytime.",
    },
    "call_not_picked_followup": {
        "type": "callback",
        "interested_reply": "Got it! Our team will call you back soon. 9289344726",
        "not_interested_reply": "No problem! Reach us at 9289344726 when convenient.",
    },
}


# ── Template button → intent mapping ────────────────────────────
# When user clicks a WhatsApp template button, map to standard intent
TEMPLATE_BUTTON_INTENTS = {
    # Chat / engage — only multi-word phrases to avoid false matches
    "chat now": "CHAT",
    "start chat": "CHAT",
    # Positive / interested — only unambiguous button texts
    "interested": "INTERESTED",
    "i am intrested": "INTERESTED",
    "i am interested": "INTERESTED",
    "intrested": "INTERESTED",
    "confirm now": "INTERESTED",
    "accept": "INTERESTED",
    # Callback
    "call me back": "CALLBACK",
    "request call back": "CALLBACK",
    "call me later": "CALLBACK",
    # Support
    "need support": "SUPPORT",
    "contact support": "SUPPORT",
    # Negative — only clear template button texts
    "not interested": "NOT_INTERESTED",
    "not intrested": "NOT_INTERESTED",
    "connect later": "NOT_INTERESTED",
    "call later": "NOT_INTERESTED",
    "remind me later": "NOT_INTERESTED",
    "reject": "NOT_INTERESTED",
}
# NOTE: "yes", "no", "confirm", "chat", "support", "help" are NOT in this dict
# because they are common conversation words and would cause false matches


def get_template_button_intent(btn_text: str) -> str:
    """
    Returns intent ONLY for known template button texts.
    Strict matching — must be an exact known button phrase.
    Common words like yes/no/ok are excluded to prevent false matches.
    """
    t = btn_text.lower().strip()
    # Must be at least 2 words OR an exact known phrase
    # Single common words are NEVER template buttons
    single_word_blocklist = {
        "yes", "no", "ok", "okay", "hi", "hello", "haan", "han",
        "confirm", "chat", "help", "support", "done", "sure"
    }
    if t in single_word_blocklist:
        return ""
    return TEMPLATE_BUTTON_INTENTS.get(t, "")


# ── Keywords ──────────────────────────────────────────────────────
YES_WORDS = {
    "yes", "yeah", "yeahh", "yess", "yesss",
    "haan", "han", "ha", "haa", "hnji", "haan ji",
    "confirmed", "confirm", "bilkul", "theek", "correct",
    "right", "sahi", "ji haan", "ji ha", "ji",
    "ok", "okay", "okk", "okkk", "sure", "yep", "yup",
    "kar do", "kardo", "bhejo", "de do", "zaroor", "please",
    "yahi hai", "yahi he", "ye hai", "ye he", "yeh hai",
    "ha ji", "haan bhai", "haan yaar", "bilkul sahi",
    "absolutely", "definitely", "of course", "done"
}
NO_WORDS = {
    "no", "nahi", "nhi", "nahin", "nope", "not", "galat",
    "wrong", "different", "doosra", "alag", "mat karo"
}
CONNECTED_WORDS = {
    "connect kiya", "ho gaya", "connect ho gaya", "done", "kar liya",
    "connected", "link khola", "kiya", "hogaya", "connect kar liya",
    "ho gayi", "verify karo", "check karo", "connect hua",
    "ho gaya kya", "ab hua", "connect ho gya", "ho gya",
    "connected hai", "connect ho gaya hai", "hua kya", "link click"
}
ALREADY_CONNECTED_WORDS = {
    "already connected", "pehle se connected", "already connect",
    "connected kar rakha", "connect kar rakha", "plan bhi", "plan le rakha",
    "pehle connect", "connected hai", "already ho gaya", "bhai connected",
    "mera connected", "kar liya connect", "already link", "connected hun",
    "connect to he", "connect to hai", "connect he", "connected he",
    "kar rakha he", "kar rakha hai", "connected to", "already kar",
    "check karo connected", "connected check", "mene connect",
    "connenct kar rakha", "connect kar liya", "already connected he"
}
WRONG_BUSINESS_WORDS = {
    "galat hai", "galat he", "yeh mera nahi", "ye mera nahi",
    "wrong", "nahi hai yeh", "different", "doosra", "alag",
    "sahi nahi", "correct nahi", "yeh nahi", "ye nahi hai",
    "hamara nahi", "mera nahi", "iska nahi"
}

INDIAN_CITIES = [
    "delhi", "mumbai", "bangalore", "bengaluru", "hyderabad", "chennai",
    "kolkata", "pune", "ahmedabad", "jaipur", "surat", "lucknow",
    "kanpur", "nagpur", "indore", "bhopal", "patna", "ludhiana",
    "agra", "nashik", "faridabad", "gurgaon", "gurugram", "noida",
    "meerut", "rajkot", "varanasi", "amritsar", "ranchi", "howrah",
    "coimbatore", "jabalpur", "guwahati", "chandigarh", "mysore", "mysuru",
    "jodhpur", "raipur", "kochi", "dehradun", "nuh", "mewat", "rewari",
    "rohtak", "sonipat", "panipat", "ambala", "karnal", "hisar",
    "panchkula", "manesar", "bhiwadi", "allahabad", "prayagraj",
    "bhubaneswar", "srinagar", "jammu", "alwar", "bikaner", "udaipur",
    "kota", "ajmer", "sikar", "bhilwara", "vadodara", "gandhinagar"
]

_ENGLISH_WORDS = {
    "yes", "no", "hello", "hi", "hey", "please", "thanks", "sure",
    "okay", "ok", "what", "how", "when", "where", "who", "why",
    "send", "right", "correct", "wrong", "done", "connected", "good",
    "great", "my", "me", "we", "the", "and", "for", "with", "this",
    "that", "not", "but", "are", "was", "will", "do", "did", "does",
    "is", "it", "in", "on", "at", "to", "of", "i", "you", "want",
    "need", "can", "get", "have", "has", "help", "show", "check"
}
_HINDI_WORDS = {
    "haan", "han", "nahi", "nhi", "karo", "kare", "karta", "karti",
    "mere", "mera", "meri", "mujhe", "aapka", "aap", "yeh", "woh",
    "hai", "hain", "tha", "thi", "kya", "kyun", "kaise", "kab",
    "batao", "bataye", "chahiye", "chahte", "karein", "dijiye",
    "theek", "bilkul", "zaroor", "bhai", "ji", "bata", "isko"
}


def is_yes(text: str) -> bool:
    t = text.lower().strip()
    if len(t.split()) > 6:
        return False
    for w in YES_WORDS:
        if re.search(r'(?<![a-z])' + re.escape(w) + r'(?![a-z])', t):
            return True
    return False


def is_no(text: str) -> bool:
    t = text.lower().strip()
    for w in NO_WORDS:
        if re.search(r'(?<![a-z])' + re.escape(w) + r'(?![a-z])', t):
            return True
    return False


def is_connected_confirm(text: str) -> bool:
    t = text.lower().strip()
    return any(w in t for w in CONNECTED_WORDS)


def _detect_lang(message: str, current_lang: str = "hi") -> str:
    for char in message:
        code = ord(char)
        if 0x0B80 <= code <= 0x0BFF: return "ta"
        if 0x0C00 <= code <= 0x0C7F: return "te"
        if 0x0C80 <= code <= 0x0CFF: return "kn"
        if 0x0D00 <= code <= 0x0D7F: return "ml"
        if 0x0A00 <= code <= 0x0A7F: return "pa"
        if 0x0A80 <= code <= 0x0AFF: return "gu"
        if 0x0900 <= code <= 0x097F: return "hi"
    msg = message.strip().lower()
    words = [w.strip(".,!?") for w in msg.split() if w.strip(".,!?")]
    if not words or len(words) <= 2:
        return current_lang
    en_count = sum(1 for w in words if w in _ENGLISH_WORDS)
    hi_count = sum(1 for w in words if w in _HINDI_WORDS)
    total = len(words)
    if en_count >= max(2, total * 0.4): return "en"
    if hi_count >= max(2, total * 0.3): return "hi"
    return current_lang


def _extract_maps_url(message: str) -> str:
    import re as _re
    patterns = [
        r'https?://maps\.app\.goo\.gl/\S+',
        r'https?://maps\.google\.com/\S+',
        r'https?://www\.google\.com/maps/\S+',
        r'https?://goo\.gl/maps/\S+',
        r'https?://share\.google/\S+',
        r'https?://www\.google\.com/search\?\S+',
        r'https?://g\.co/\S+',
    ]
    for p in patterns:
        m = _re.search(p, message)
        if m:
            return m.group(0).rstrip('.,!?)')
    return ''


def _try_extract_business(message: str, session: dict):
    """
    Extract business name + full city/address from one message.
    City = everything from city keyword onwards (keeps Sector 48, JMD Megapolis etc.)
    Business = everything before city keyword.
    """
    if session.get("found_place") or session.get("search_places"):
        return None

    msg_lower = message.lower().strip()

    # Find earliest city keyword position
    city_pos = -1
    for city in INDIAN_CITIES:
        idx = msg_lower.find(city)
        if idx >= 0 and (city_pos < 0 or idx < city_pos):
            city_pos = idx

    if city_pos < 0:
        return None

    # Business = before city, City = from city onwards (full address)
    business = message[:city_pos].strip(" ,.-&\n\t")
    city_full = message[city_pos:].strip()
    business = re.sub(r"\s+", " ", business).strip()

    if len(business) < 3:
        return None

    # Block generic-only business names
    generic_starts = [
        "manufacturer", "manufacturers", "supplier", "suppliers", "dealer",
        "shop", "store", "company", "business", "service", "services",
        "center", "centre", "restaurant", "clinic", "hospital", "hotel",
        "school", "college", "office", "factory", "i am", "every kind",
    ]
    bl = business.lower()
    for g in generic_starts:
        if bl == g or bl.startswith(g + " "):
            return None

    meaningful_words = [w for w in business.split() if len(w) > 2 and w.lower() not in
                        {"every", "kind", "type", "items", "stuff", "this", "that", "the", "and"}]
    if len(meaningful_words) == 0:
        return None

    if business.lower() in [c.lower() for c in INDIAN_CITIES]:
        return None

    return "[ACTION:SEARCH_BUSINESS]name=" + business + "|city=" + city_full + "[/ACTION]"


def _try_switch_business(msg_lower: str, businesses: list, session: dict, user_id: str) -> str:
    if not businesses:
        return ""
    matched = []
    for b in businesses:
        title = b.get("title", "").lower().strip()
        if not title or len(title) < 4:
            continue
        title_words = [w for w in title.split() if len(w) > 3]
        if title in msg_lower or any(w in msg_lower for w in title_words):
            matched.append(b)
    if not matched:
        return ""

    def _city_match(locality: str, msg: str) -> bool:
        if not locality: return False
        if locality in msg: return True
        for word in msg.split():
            if len(word) < 4: continue
            for i in range(len(word) - 3):
                if word[i:i+4] in locality:
                    return True
        return False

    for b in matched:
        locality = b.get("locality", "").lower()
        address = b.get("address", "").lower()
        if _city_match(locality, msg_lower) or _city_match(address, msg_lower):
            matched = [b]
            break

    if len(matched) > 1:
        session["pending_business_matches"] = matched
        save_session(user_id, session)
        print(f"[Graph] Multiple matches: {[b['title'] for b in matched]}")
        return "needs_city_confirm"

    b = matched[0]
    biz_title = b.get("title", "")
    current = session.get("active_business_name", "")
    if current == biz_title and session.get("active_location_id"):
        return "switched"
    session["active_business_name"] = biz_title
    session["active_location_id"] = (
        b.get("locationResourceName") or b.get("locationId") or b.get("id") or ""
    )
    session["features_offered"] = []
    session.pop("pending_business_matches", None)
    save_session(user_id, session)
    print(f"[Graph] Switched to: {biz_title} → {session['active_location_id']}")
    return "switched"


# ── Message dedup ─────────────────────────────────────────────────
_processed_ids: set = set()
_MAX_PROCESSED = 500

def _is_duplicate(msg_id: str) -> bool:
    global _processed_ids
    if not msg_id:
        return False
    if msg_id in _processed_ids:
        return True
    _processed_ids.add(msg_id)
    if len(_processed_ids) > _MAX_PROCESSED:
        _processed_ids = set(list(_processed_ids)[-250:])
    return False


# ── Connection Polling ────────────────────────────────────────────
def start_connection_polling(user_id: str, phone: str):
    def poll():
        import httpx
        from app.core.config import LIMBU_API_BASE
        from app.nodes.connect import _build_connected_response
        for attempt in range(100):
            time.sleep(3)
            try:
                session = get_session(user_id)
                if session.get("connect_verified"):
                    print(f"[ConnPoll] Already verified, stopping")
                    break
                res = httpx.get(
                    f"{LIMBU_API_BASE}/gmb/status",
                    params={"phone": phone}, timeout=10
                )
                data = res.json()
                print(f"[ConnPoll] {user_id} attempt {attempt+1}: {data.get('status')}")
                if data.get("status") == "success" or data.get("success"):
                    email = data.get("email", "")
                    locations = (data.get("locationsData") or
                                 data.get("businesses") or
                                 data.get("data") or [])
                    session["connect_verified"] = True
                    session["connect_link_sent"] = True
                    session["connected_email"] = email
                    session["connected_businesses"] = locations
                    save_session(user_id, session)
                    reply = _build_connected_response(session, locations, email)
                    save_message(user_id, "assistant", reply)
                    from app.services.whatsapp_service import send_whatsapp
                    send_whatsapp(phone, reply)
                    # Schedule feature follow-ups
                    from app.services.followup_service import on_connected
                    on_connected(user_id, phone)
                    print(f"[ConnPoll] Connected! user={user_id} email={email}")
                    break
            except Exception as e:
                print(f"[ConnPoll] Error: {e}")
                time.sleep(5)
    t = threading.Thread(target=poll, daemon=True)
    t.start()
    print(f"[ConnPoll] Started for user={user_id} phone={phone}")


# ── State ─────────────────────────────────────────────────────────
class ChatState(TypedDict, total=False):
    user_id: str
    message: str
    raw_reply: str
    action: str
    response: str
    feature_type: str


# ── Entry Node ────────────────────────────────────────────────────
def entry_node(state: ChatState) -> ChatState:
    user_id = state["user_id"]
    message = state["message"]
    session = get_session(user_id)
    msg_lower = message.lower().strip()

    # Cancel any pending follow-up — user is active
    from app.services.followup_service import on_user_message
    on_user_message(user_id)

    # Update user intelligence — lead score, personality, funnel stage
    update_user_intelligence(user_id, message)
    update_buying_intent(user_id, message)
    session = get_session(user_id)  # Refresh after update

    # ── Hesitation Detection ──────────────────────────────────────
    if detect_hesitation(message) and session.get("found_place"):
        reply = get_hesitation_response(session)
        if reply:
            # Add urgency if high hesitation
            if session.get("message_count", 0) > 5:
                urgency = get_urgency_message(session)
                reply += "\n\n💡 " + urgency
            state["raw_reply"] = reply
            state["action"] = "RESPOND"
            return state

    # ── Smart Discount Trigger ────────────────────────────────────
    if should_offer_discount(session) and not session.get("discount_offered"):
        # Only offer once and when asking about plans
        if any(w in msg_lower for w in ["plan", "price", "kitna", "mahnga", "expensive"]):
            session["discount_offered"] = True
            save_session(user_id, session)
            discount_msg = get_discount_offer(session)
            state["raw_reply"] = discount_msg
            state["action"] = "RESPOND"
            return state

    # ── Competitor Mention ────────────────────────────────────────
    for comp in ["dhanda ai", "grexa", "justdial", "sulekha", "indiamart"]:
        if comp in msg_lower:
            lang = session.get("lang", "hi")
            comp_reply = get_competitor_response(comp, lang)
            if comp_reply:
                state["raw_reply"] = comp_reply
                state["action"] = "RESPOND"
                return state

    # ── PRIORITY: Explicit language switch ────────────────────────
    LANG_SWITCH = {
        "english": "en", "in english": "en", "talk in english": "en",
        "speak english": "en", "english me": "en", "english mein": "en",
        "reply in english": "en", "english please": "en",
        "hindi": "hi", "in hindi": "hi", "hindi me baat karo": "hi",
        "hindi mein": "hi", "hinglish": "hi",
    }
    for phrase, switch_lang in LANG_SWITCH.items():
        if phrase in msg_lower:
            session["lang"] = switch_lang
            save_session(user_id, session)
            if switch_lang == "en":
                reply = "Sure! I'll speak in English from now on. 😊"
            else:
                reply = "Bilkul! Ab Hindi mein baat karta hoon. 😊"
            state["raw_reply"] = reply
            state["action"] = "RESPOND"
            return state

    # ── Template button click handling (HIGHEST PRIORITY) ────────
    btn_intent = get_template_button_intent(message)
    if btn_intent:
        print(f"[Graph] Template button: '{message}' → intent={btn_intent}")
        session["greeted"] = True
        save_session(user_id, session)

        # Get template-specific context if available
        last_template = session.get("last_template", "")
        template_ctx = TEMPLATE_CONTEXTS.get(last_template, {})
        template_type = template_ctx.get("type", "")
        print(f"[Graph] Template context: {last_template} → type={template_type}")

        if btn_intent == "CHAT":
            # User clicked "Chat Now" — greet and ask how to help
            reply = _llm_reply(
                user_id,
                "User ne 'Chat Now' button click kiya hai Limbu.ai template mein. "
                "Warmly greet karo — 'Main yahi hoon!' type se. "
                "Poocho kya help chahiye: feature, plan, ya koi sawaal?"
            )
            state["raw_reply"] = reply
            state["action"] = "RESPOND"
            return state

        elif btn_intent == "INTERESTED":
            # Use template-specific reply if available
            if template_ctx.get("interested_reply"):
                reply = template_ctx["interested_reply"]
                # For welcome/GMB templates, continue with normal flow
                if template_type == "welcome":
                    state["raw_reply"] = reply
                    state["action"] = "RESPOND"
                    return state
                elif template_type in ("franchise", "demo", "service", "callback"):
                    state["raw_reply"] = reply
                    state["action"] = "RESPOND"
                    return state

            # Default: if connected show features, else ask business
            if session.get("connect_verified"):
                offered = session.get("features_offered", [])
                for feat in FEATURE_SEQUENCE:
                    if feat not in offered:
                        state["action"] = "FEATURE"
                        state["feature_type"] = feat
                        return state
            elif session.get("confirmed"):
                state["action"] = "CONNECT_BUSINESS"
                return state
            else:
                reply = _llm_reply(
                    user_id,
                    "User ne 'Interested' button click kiya hai Limbu.ai template mein. "
                    "Warmly welcome karo aur poocho unka business naam aur city kya hai. "
                    "Introduce yourself as Priya from Limbu.ai."
                )
                state["raw_reply"] = reply
                state["action"] = "RESPOND"
                return state

        elif btn_intent == "NOT_INTERESTED":
            if template_ctx.get("not_interested_reply"):
                reply = template_ctx["not_interested_reply"]
            else:
                reply = _llm_reply(
                    user_id,
                    "User ne 'Not Interested' ya 'Remind Me Later' click kiya. "
                    "Politely acknowledge karo, koi pressure nahi. "
                    "Batao ki agar kabhi zaroorat ho to wapas aa sakte hain: 9289344726"
                )
            state["raw_reply"] = reply
            state["action"] = "RESPOND"
            return state

        elif btn_intent == "CALLBACK":
            reply = _llm_reply(
                user_id,
                "User ne callback request kiya hai. "
                "Confirm karo ki hamar team jald call karega. "
                "Contact: 9289344726"
            )
            state["raw_reply"] = reply
            state["action"] = "RESPOND"
            return state

        elif btn_intent == "SUPPORT":
            reply = _llm_reply(
                user_id,
                "User ko support chahiye. "
                "Poocho kya problem hai aur batao: "
                "📞 9289344726 | info@limbu.ai"
            )
            state["raw_reply"] = reply
            state["action"] = "RESPOND"
            return state

    # ── Language detection
    current_lang = session.get("lang", "hi")
    lang = _detect_lang(message, current_lang)
    if lang != current_lang:
        session["lang"] = lang
        save_session(user_id, session)

    if not session.get("greeted"):
        session["greeted"] = True
        save_session(user_id, session)

    # ── Fast path: greeting ───────────────────────────────────────
    history = get_history(user_id)
    GREET_EN = {"hi", "hello", "hey", "hlo", "helo", "hii", "hy", "start"}
    GREET_HI = {"namaste", "namaskar", "hnji"}
    if len(history) <= 2 and msg_lower in GREET_EN | GREET_HI:
        from app.nodes.intent import FIRST_MSG_EN, FIRST_MSG_HI
        if msg_lower in GREET_EN:
            first_reply = FIRST_MSG_EN
            session["lang"] = "en"
        else:
            first_reply = FIRST_MSG_HI
            session["lang"] = "hi"
        save_session(user_id, session)
        state["raw_reply"] = first_reply
        state["action"] = "RESPOND"
        return state

    # ── PRIORITY: Already connected ───────────────────────────────
    if not session.get("connect_verified"):
        if any(w in msg_lower for w in ALREADY_CONNECTED_WORDS):
            state["action"] = "CHECK_LATEST_CONNECTION"
            return state

    # ── PRIORITY: Social media connect check ──────────────────────
    social_connected_words = {
        "facebook connected", "fb connected", "instagram connected",
        "insta connected", "social connected", "facebook ho gaya",
        "instagram ho gaya", "fb ho gaya"
    }
    for w in social_connected_words:
        if w in msg_lower:
            platform = "facebook" if "facebook" in w or "fb" in w else "instagram"
            state["action"] = "CHECK_SOCIAL_CONNECTION"
            state["feature_type"] = platform
            return state

    # ── PRIORITY: Wrong business ──────────────────────────────────
    if session.get("found_place") and not session.get("confirmed"):
        if any(w in msg_lower for w in WRONG_BUSINESS_WORDS):
            session.pop("found_place", None)
            session.pop("search_places", None)
            session.pop("result_index", None)
            session.pop("confirmed", None)
            session.pop("business_name", None)
            session.pop("city", None)
            save_session(user_id, session)
            reply = _llm_reply(
                user_id,
                "User ne bola ki shown business galat hai. "
                "Politely apologize karo aur correct business name aur city maango."
            )
            state["raw_reply"] = reply
            state["action"] = "RESPOND"
            return state

    # Correction after confirm
    if session.get("confirmed") and not session.get("analysis"):
        correction_signals = ["hamara shop", "mera shop", "hamare yahan", "our shop", "my shop",
                              "actually", "nahi woh", "alag hai"]
        if any(w in msg_lower for w in correction_signals):
            session.pop("found_place", None)
            session.pop("search_places", None)
            session.pop("confirmed", None)
            session.pop("analysis", None)
            session.pop("business_name", None)
            session.pop("city", None)
            save_session(user_id, session)
            reply = detect_and_respond(user_id, message)
            clean = re.sub(r'\[ACTION:[A-Z_]+\].*?\[/ACTION\]', '', reply, flags=re.DOTALL).strip()
            state["raw_reply"] = clean
            state["action"] = _detect_action(reply) if "[ACTION:" in reply else "RESPOND"
            return state

    # ── Social media connect — works anytime, no GMB needed ─────
    SOCIAL_KEYWORDS = {
        "facebook": "facebook", "fb page": "facebook", "fb connect": "facebook",
        "facebook page": "facebook", "facebook connect": "facebook",
        "instagram": "instagram", "insta": "instagram", "ig connect": "instagram",
        "instagram page": "instagram", "instagram connect": "instagram",
        "youtube": "youtube", "yt connect": "youtube", "youtube channel": "youtube",
        "youtube connect": "youtube",
        "linkedin": "linkedin", "linked in": "linkedin", "linkedin page": "linkedin",
        "linkedin connect": "linkedin",
        "social media": None,
        "social connect": None,
        "social media connect": None,
    }
    for keyword, platform in SOCIAL_KEYWORDS.items():
        if keyword in msg_lower:
            if platform:
                if not session.get(f"{platform}_verified"):
                    state["action"] = "SOCIAL_CONNECT"
                    state["feature_type"] = platform
                    return state
            else:
                # Both platforms - start with facebook
                if not session.get("facebook_verified"):
                    state["action"] = "SOCIAL_CONNECT"
                    state["feature_type"] = "facebook"
                    return state
                elif not session.get("instagram_verified"):
                    state["action"] = "SOCIAL_CONNECT"
                    state["feature_type"] = "instagram"
                    return state

    # Check if pending social connect
    for platform in ["facebook", "instagram"]:
        if session.get(f"{platform}_link_sent") and not session.get(f"{platform}_verified"):
            if is_connected_confirm(message):
                state["action"] = "CHECK_SOCIAL_CONNECTION"
                state["feature_type"] = platform
                return state

    # ── 1. Connect link sent → check connected ────────────────────
    if session.get("connect_link_sent") and not session.get("connect_verified"):
        if is_connected_confirm(message):
            state["action"] = "CHECK_LATEST_CONNECTION"
            return state

    # ── 2. Business confirmation ──────────────────────────────────
    if session.get("found_place") and not session.get("confirmed"):
        if is_yes(message):
            session["confirmed"] = True
            save_session(user_id, session)
            state["action"] = "CONFIRMED"
            return state
        elif is_no(message):
            state["action"] = "NEXT_RESULT"
            return state
        else:
            # Not a clear yes/no — ask LLM to interpret intent
            # LLM decides: is user confirming, denying, or asking something else?
            intent = _llm_interpret_intent(user_id, message, context="business_confirm")
            if intent == "yes":
                session["confirmed"] = True
                save_session(user_id, session)
                state["action"] = "CONFIRMED"
                return state
            elif intent == "no":
                state["action"] = "NEXT_RESULT"
                return state
            # else: user asked something else — fall through to LLM response

    # ── 3a. Already confirmed + no analysis → ANALYSE trigger ────
    if session.get("confirmed") and not session.get("analysis"):
        ANALYSE_WORDS = [
            "analyse", "analysis", "check", "report", "karo", "kar", "batao",
            "dikhao", "nikalo", "haan", "han", "ok", "sure", "yes", "continue",
            "next", "aage", "chalte", "kitni baar", "already", "bata diya",
            "dekho", "nikaal", "shuru"
        ]
        if is_yes(message) or any(w in msg_lower for w in ANALYSE_WORDS):
            state["action"] = "ANALYSE"
            return state
        else:
            # Unclear — LLM interpret
            intent = _llm_interpret_intent(user_id, message, context="analyse_confirm")
            if intent == "yes":
                state["action"] = "ANALYSE"
                return state
            # "no" or "other" — fall through to LLM for natural response

    # ── 3. Analyse (handled above in 3a) ─────────────────────────

    # ── 4. Connect after analysis ─────────────────────────────────
    if session.get("analysis") and not session.get("connect_link_sent"):
        connect_words = [
            "connect", "jodo", "link", "yes", "haan", "han", "ok", "karo",
            "sure", "bilkul", "chalte", "aage", "next", "haan karo"
        ]
        if is_yes(message) or any(w in msg_lower for w in connect_words):
            state["action"] = "CONNECT_BUSINESS"
            return state

    # ── 5. Features after connected ───────────────────────────────
    if session.get("connect_verified"):
        businesses = session.get("connected_businesses", [])

        # Direct address-based location switch — use connected list, no Google search
        if businesses and len(businesses) > 1:
            for b in businesses:
                addr = (b.get("address", "") or b.get("locality", "")).lower()
                addr_words = [w for w in addr.replace(",","").split() if len(w) > 3]
                if addr_words and any(w in msg_lower for w in addr_words):
                    biz_title = b.get("title", "")
                    loc_id = b.get("locationResourceName") or b.get("locationId") or ""
                    if session.get("active_location_id") != loc_id:
                        session["active_business_name"] = biz_title
                        session["active_location_id"] = loc_id
                        session["features_offered"] = []
                        save_session(user_id, session)
                        addr_short = (b.get("locality") or b.get("address",""))[:40]
                        lang = session.get("lang", "hi")
                        lang = session.get("lang", "hi")
                        en_r = "Switched to *" + biz_title + "* (" + addr_short + ").\nWhich feature do you need?"
                        hi_r = "*" + biz_title + "* (" + addr_short + ") select kar liya.\nKaunsa feature chahiye?"
                        reply = en_r if lang == "en" else hi_r
                        state["raw_reply"] = reply
                        state["action"] = "RESPOND"
                        return state

        switch_result = _try_switch_business(msg_lower, businesses, session, user_id)

        if switch_result == "needs_city_confirm":
            session = get_session(user_id)
            pending = session.get("pending_business_matches", [])
            cities = [b.get("locality") or b.get("address", "")[:20] for b in pending]
            cities_str = " / ".join(f"*{c}*" for c in cities if c)
            reply = _llm_reply(
                user_id,
                f"Is business ki multiple locations hain: {cities_str}. "
                "User se politely poocho kaunsi location/city chahiye."
            )
            state["raw_reply"] = reply
            state["action"] = "RESPOND"
            return state

        elif switch_result == "switched":
            session = get_session(user_id)
            session.pop("pending_business_matches", None)
            save_session(user_id, session)
            biz_name = session.get("active_business_name", "")
            reply = _llm_reply(
                user_id,
                f"Business *{biz_name}* select ho gaya. "
                "Confirm karo aur poocho kaunsa feature chahiye: "
                "Health Report, Magic QR, Insights, Website, ya Review Reply."
            )
            state["raw_reply"] = reply
            state["action"] = "RESPOND"
            return state

        pending = session.get("pending_business_matches", [])
        if pending:
            for b in pending:
                locality = b.get("locality", "").lower()
                address = b.get("address", "").lower()
                addr_words = [w for w in address.split() if len(w) > 3]
                if (locality and locality in msg_lower) or any(w in msg_lower for w in addr_words):
                    session["active_business_name"] = b.get("title", "")
                    session["active_location_id"] = (
                        b.get("locationResourceName") or b.get("locationId") or ""
                    )
                    session["features_offered"] = []
                    session.pop("pending_business_matches", None)
                    save_session(user_id, session)
                    biz_name = b.get("title", "")
                    reply = _llm_reply(
                        user_id,
                        f"Business *{biz_name}* ({b.get('locality', '')}) select ho gaya. "
                        "Confirm karo aur poocho kaunsa feature chahiye."
                    )
                    state["raw_reply"] = reply
                    state["action"] = "RESPOND"
                    return state

        feature_keywords = {
            "health report": "health_score", "health score": "health_score", "health": "health_score",
            "magic qr": "magic_qr", "qr code": "magic_qr", "qr": "magic_qr",
            "insight": "insights", "inshit": "insights", "performance": "insights",
            "website": "website", "site": "website",
            "review reply": "review_reply", "review": "review_reply"
        }


        if is_yes(message):
            offered = session.get("features_offered", [])
            for feat in FEATURE_SEQUENCE:
                if feat not in offered:
                    state["action"] = "FEATURE"
                    state["feature_type"] = feat
                    return state
        for keyword, feat in feature_keywords.items():
            if keyword in msg_lower:
                state["action"] = "FEATURE"
                state["feature_type"] = feat
                return state

    # ── 6. Email detection ────────────────────────────────────────
    if session.get("connect_link_sent") and not session.get("connect_verified"):
        email = extract_email(message)
        if email:
            state["raw_reply"] = f"[ACTION:CHECK_BUSINESS_EMAIL]email={email}[/ACTION]"
            state["action"] = "CHECK_BUSINESS_EMAIL"
            return state

    # ── 7a. Google Maps URL → extract place and analyse ──────────
    maps_url = _extract_maps_url(message)
    if maps_url:
        state["raw_reply"] = maps_url
        state["action"] = "SEARCH_BY_URL"
        return state

    # ── 7b. Business + city ───────────────────────────────────────
    smart = _try_extract_business(message, session)
    if smart:
        state["raw_reply"] = smart
        state["action"] = "SEARCH_BUSINESS"
        return state

    # ── 7c. Franchise keywords ────────────────────────────────────
    FRANCHISE_WORDS = [
        "franchise", "franchisee", "franshise", "franshize",
        "partner", "partnership", "business opportunity",
        "join limbu", "distributor", "reseller", "agency",
        "invest", "investment", "5 lakh", "5lakh", "earning",
        "income opportunity", "monthly income", "passive income",
    ]
    if any(w in msg_lower for w in FRANCHISE_WORDS):
        # Let Claude handle with full franchise context
        pass  # Falls through to LLM below

    # ── 8. Claude LLM ─────────────────────────────────────────────
    reply = detect_and_respond(user_id, message)
    detected = _detect_action(reply)
    if detected != "RESPOND":
        session = get_session(user_id)
        if not _validate_action(detected, state, session):
            # Validation failed — ask LLM for natural response
            if not state.get("raw_reply"):
                fallback_reply = _llm_reply(
                    user_id,
                    "User ne kuch kaha hai. Naturally respond karo aur poocho kya chahiye."
                )
                state["raw_reply"] = fallback_reply or _fallback(user_id)
            state["action"] = "RESPOND"
        else:
            state["action"] = detected
        if detected == "FEATURE":
            m = re.search(r'\[ACTION:FEATURE\]type=(\w+)\[/ACTION\]', reply)
            if m:
                state["feature_type"] = m.group(1)
        if detected in ("SEARCH_BUSINESS", "CHECK_BUSINESS_EMAIL", "BOOK_DEMO", "CHECK_USER"):
            state["raw_reply"] = reply
        return state

    # Clean accidental action tags from plain text
    clean_reply = re.sub(r'\[ACTION:[A-Z_]+\].*?\[/ACTION\]', '', reply, flags=re.DOTALL).strip()
    # Ensure raw_reply is always set
    state["raw_reply"] = clean_reply or _fallback(user_id)
    state["action"] = "RESPOND"
    return state


def _safe_action(action: str, state: dict, session: dict) -> str:
    """Validate action before routing — fallback to RESPOND if invalid."""
    if _validate_action(action, state, session):
        return action
    return "RESPOND"


def _validate_action(action: str, state: dict, session: dict) -> bool:
    """
    Validate that detected action makes sense in current context.
    Prevents hallucinated actions from executing.
    """
    # SEARCH_BUSINESS — basic check only
    if action == "SEARCH_BUSINESS":
        raw = state.get("raw_reply", "")
        if not raw:
            print(f"[Validation] SEARCH_BUSINESS rejected — empty raw_reply")
            return False

    # FEATURE needs connect_verified
    if action == "FEATURE":
        if not session.get("connect_verified"):
            print(f"[Validation] FEATURE rejected — not connected")
            return False

    # ANALYSE needs confirmed
    if action == "ANALYSE":
        if not session.get("confirmed") and not session.get("found_place"):
            print(f"[Validation] ANALYSE rejected — no confirmed business")
            return False

    # CONNECT_BUSINESS needs found_place or confirmed
    if action == "CONNECT_BUSINESS":
        if not session.get("confirmed") and not session.get("analysis"):
            print(f"[Validation] CONNECT_BUSINESS rejected — not ready")
            return False

    # REGISTER_FRANCHISE needs name and phone
    if action == "REGISTER_FRANCHISE":
        raw = state.get("raw_reply", "")
        if "name=" not in raw or "phone=" not in raw:
            print(f"[Validation] REGISTER_FRANCHISE rejected — missing params")
            return False

    return True


def _detect_action(text: str) -> str:
    actions = [
        "SEARCH_BUSINESS", "NEXT_RESULT", "ANALYSE", "CONNECT_BUSINESS",
        "CHECK_LATEST_CONNECTION", "CHECK_BUSINESS_EMAIL", "FEATURE",
        "BOOK_DEMO", "CHECK_USER", "REGISTER_FRANCHISE"
    ]
    for action in actions:
        if f"[ACTION:{action}]" in text:
            return action
    return "RESPOND"


# ── Nodes ─────────────────────────────────────────────────────────
def node_respond(state: ChatState) -> ChatState:
    raw = state.get("raw_reply", "")
    if not raw:
        raw = _fallback(state["user_id"])
    save_message(state["user_id"], "assistant", raw)
    state["response"] = raw
    return state


def node_confirmed(state: ChatState) -> ChatState:
    user_id = state["user_id"]
    session = get_session(user_id)
    place = session.get("found_place", {})
    name = place.get("displayName", {}).get("text", "your business")
    lang = session.get("lang", "hi")
    if lang == "en":
        reply = "Great! ✅ *" + name + "* confirmed.\n\nShall I analyse your Google Business Profile? 😊"
    else:
        reply = "Bahut achha! ✅ *" + name + "* confirm ho gaya.\n\nKya main aapki Google Business Profile analyse karoon? 😊"
    save_message(user_id, "assistant", reply)
    state["response"] = reply
    return state

def node_search_business(state: ChatState) -> ChatState:
    user_id = state["user_id"]
    session = get_session(user_id)
    match = re.search(r'\[ACTION:SEARCH_BUSINESS\](.*?)\[/ACTION\]', state.get("raw_reply", ""), re.DOTALL)
    if match:
        params = extract_action_params(match.group(1))
        reply = handle_search(user_id, session, params.get("name", ""), params.get("city", ""))
    else:
        lang = session.get("lang", "hi")
        reply = "Please share your business name and city. 😊" if lang == "en" else \
                "Kripya apna business naam aur city batayein. 😊"
    save_message(user_id, "assistant", reply)
    state["response"] = reply
    return state


def node_next_result(state: ChatState) -> ChatState:
    user_id = state["user_id"]
    session = get_session(user_id)
    reply = handle_next_result(user_id, session)
    save_message(user_id, "assistant", reply)
    state["response"] = reply
    return state


def node_analyse(state: ChatState) -> ChatState:
    user_id = state["user_id"]
    session = get_session(user_id)
    reply = handle_analyse(user_id, session)
    save_message(user_id, "assistant", reply)
    state["response"] = reply
    return state


def node_connect_business(state: ChatState) -> ChatState:
    user_id = state["user_id"]
    session = get_session(user_id)
    reply = handle_connect_link(user_id, session)
    session = get_session(user_id)
    phone = session.get("connect_phone", "")
    if phone:
        start_connection_polling(user_id, phone)
        # Schedule follow-up if user doesn't connect in 7 min
        from app.services.followup_service import on_connect_link_sent
        on_connect_link_sent(user_id, phone)
    save_message(user_id, "assistant", reply)
    state["response"] = reply
    return state


def node_check_latest_connection(state: ChatState) -> ChatState:
    user_id = state["user_id"]
    session = get_session(user_id)
    reply = handle_check_latest_connection(user_id, session)
    save_message(user_id, "assistant", reply)
    state["response"] = reply
    return state


def node_check_business_email(state: ChatState) -> ChatState:
    user_id = state["user_id"]
    session = get_session(user_id)
    match = re.search(r'\[ACTION:CHECK_BUSINESS_EMAIL\](.*?)\[/ACTION\]', state.get("raw_reply", ""), re.DOTALL)
    if match:
        params = extract_action_params(match.group(1))
        reply = handle_check_email(user_id, session, params.get("email", ""))
    else:
        reply = "Kripya apni registered Gmail email batayein. 😊"
    save_message(user_id, "assistant", reply)
    state["response"] = reply
    return state


def node_feature(state: ChatState) -> ChatState:
    user_id = state["user_id"]
    session = get_session(user_id)
    feature_type = state.get("feature_type", "")
    if not feature_type:
        m = re.search(r'\[ACTION:FEATURE\]type=(\w+)\[/ACTION\]', state.get("raw_reply", ""))
        if m:
            feature_type = m.group(1)
    if not feature_type:
        reply = _llm_reply(
            user_id,
            "User ne feature maanga par specify nahi kiya. "
            "Poocho: Health Report, Magic QR, Insights, Website, ya Review Reply?"
        )
    else:
        reply = handle_feature(user_id, session, feature_type)
    save_message(user_id, "assistant", reply)
    state["response"] = reply
    return state


def node_book_demo(state: ChatState) -> ChatState:
    user_id = state["user_id"]
    raw = state.get("raw_reply", "")
    match = re.search(r'\[ACTION:BOOK_DEMO\](.*?)\[/ACTION\]', raw, re.DOTALL)
    if match:
        params = extract_action_params(match.group(1))
        print(f"[Demo] Booking: {params}")
        phone = params.get("phone", "")
        if not phone and user_id.startswith("wa_"):
            phone = user_id.replace("wa_", "")
            if phone.startswith("91"):
                phone = phone[2:]
        reply = handle_booking(
            user_id,
            name=params.get("name", ""),
            phone=phone,
            date=params.get("date", ""),
            time=params.get("time", "")
        )
    else:
        session = get_session(user_id)
        lang = session.get("lang", "hi")
        reply = "Please share your name, phone number, and preferred date/time. 😊" if lang == "en" else \
                "Kripya naam, phone number, aur date/time batayein. 😊"
    save_message(user_id, "assistant", reply)
    state["response"] = reply
    return state


def node_check_user(state: ChatState) -> ChatState:
    user_id = state["user_id"]
    session = get_session(user_id)
    match = re.search(r'\[ACTION:CHECK_USER\](.*?)\[/ACTION\]', state.get("raw_reply", ""), re.DOTALL)
    if match:
        params = extract_action_params(match.group(1))
        phone = params.get("phone", "")
        user_data = check_user_by_phone(phone)
        lang = session.get("lang", "hi")
        if user_data:
            session["user_info"] = user_data
            save_session(user_id, session)
            ctx = f"User found. Continue in {'English' if lang=='en' else 'Hindi'}."
        else:
            ctx = f"New user. Continue in {'English' if lang=='en' else 'Hindi'}."
        follow_up = llm.invoke([
            SystemMessage(content=get_main_prompt(session)),
            HumanMessage(content=f"[SYSTEM: {ctx}]")
        ])
        reply = follow_up.content.strip()
    else:
        reply = "Kripya phone number batayein. 😊"
    save_message(user_id, "assistant", reply)
    state["response"] = reply
    return state


def node_search_by_url(state: ChatState) -> ChatState:
    user_id = state['user_id']
    session = get_session(user_id)
    url = state.get('raw_reply', '')
    lang = session.get('lang', 'hi')
    try:
        import httpx as _httpx
        import re as _re
        import urllib.parse as _up
        resolved_url = url
        if any(x in url for x in ['goo.gl', 'share.google', 'g.co']):
            try:
                with _httpx.Client(timeout=10, follow_redirects=True) as c:
                    r = c.get(url)
                    resolved_url = str(r.url)
                    print(f'[SearchByURL] Resolved: {resolved_url[:80]}')
            except Exception as e:
                print(f'[SearchByURL] Resolve error: {e}')
        search_query = ''
        q_match = _re.search(r'[?&]q=([^&]+)', resolved_url)
        if q_match:
            search_query = _up.unquote_plus(q_match.group(1))
            print(f'[SearchByURL] Query: {search_query}')
        from app.services.google_places import search_places
        places = []
        if search_query:
            places = search_places(search_query, '', page_size=1)
        if not places:
            cid_m = _re.search(r'cid=(\d+)', resolved_url)
            if cid_m:
                places = search_places('cid:' + cid_m.group(1), '', page_size=1)
        if not places:
            pm = _re.search(r'/place/([^/@?]+)', resolved_url)
            if pm:
                places = search_places(_up.unquote_plus(pm.group(1)), '', page_size=1)
        if places:
            place = places[0]
            name = place.get('displayName', {}).get('text', 'Business')
            address = place.get('formattedAddress', '')
            rating = place.get('rating', 0)
            reviews = place.get('userRatingCount', 0)
            maps_uri = place.get('googleMapsUri', url)
            session['found_place'] = place
            session['search_places'] = places
            session['result_index'] = 0
            session['business_name'] = name
            session.pop('confirmed', None)
            save_session(user_id, session)
            stars = str(rating) + '/5' if rating else 'N/A'
            if lang == 'en':
                reply = 'Found it!\n\n'
                reply += '\U0001f3ea *' + name + '*\n'
                reply += '\U0001f4cd ' + address + '\n'
                reply += '\u2b50 ' + stars + ' (' + str(reviews) + ' reviews)\n'
                reply += '\U0001f517 ' + maps_uri + '\n\n'
                reply += 'Is this your business?'
            else:
                reply = 'Yeh mila!\n\n'
                reply += '\U0001f3ea *' + name + '*\n'
                reply += '\U0001f4cd ' + address + '\n'
                reply += '\u2b50 ' + stars + ' (' + str(reviews) + ' reviews)\n'
                reply += '\U0001f517 ' + maps_uri + '\n\n'
                reply += 'Kya yeh aapka business hai?'
        else:
            if lang == 'en':
                reply = 'Business not found from this link. Please share name and city directly.'
            else:
                reply = 'Is link se business nahi mila. Naam aur city directly batayein.'
    except Exception as e:
        print(f'[SearchByURL] Error: {e}')
        reply = 'Link process nahi ho saka. Business naam aur city batayein.' if lang != 'en' else 'Could not process link. Please share business name and city.'
    save_message(user_id, 'assistant', reply)
    state['response'] = reply
    return state


def node_franchise_register(state: ChatState) -> ChatState:
    user_id = state["user_id"]
    session = get_session(user_id)
    raw = state.get("raw_reply", "")
    import re as _re
    match = _re.search(r'\[ACTION:REGISTER_FRANCHISE\](.*?)\[/ACTION\]', raw, _re.DOTALL)
    if match:
        params = extract_action_params(match.group(1))
        name = params.get("name", "")
        phone = params.get("phone", "") or session.get("connect_phone", "")
        city = params.get("city", "")
        email = params.get("email", "")
        reply = handle_franchise_register(user_id, session, name, phone, city, email)
    else:
        lang = session.get("lang", "hi")
        if lang == "en":
            reply = "Please share your name, phone number, and city to register for the franchise."
        else:
            reply = "Franchise ke liye apna naam, phone number, aur city batayein."
    save_message(user_id, "assistant", reply)
    state["response"] = reply
    return state


def node_social_connect(state: ChatState) -> ChatState:
    user_id = state["user_id"]
    session = get_session(user_id)
    platform = state.get("feature_type", "facebook")
    reply = handle_social_connect_link(user_id, session, platform)
    save_message(user_id, "assistant", reply)
    state["response"] = reply
    return state


def node_check_social_connection(state: ChatState) -> ChatState:
    user_id = state["user_id"]
    session = get_session(user_id)
    platform = state.get("feature_type", "facebook")
    reply = handle_check_social_connection(user_id, session, platform)
    save_message(user_id, "assistant", reply)
    state["response"] = reply
    return state


def router(state: ChatState) -> str:
    return state.get("action", "RESPOND")


def build_graph():
    graph = StateGraph(ChatState)
    graph.add_node("entry", entry_node)
    graph.add_node("respond", node_respond)
    graph.add_node("confirmed", node_confirmed)
    graph.add_node("search_business", node_search_business)
    graph.add_node("next_result", node_next_result)
    graph.add_node("analyse", node_analyse)
    graph.add_node("connect_business", node_connect_business)
    graph.add_node("check_latest_connection", node_check_latest_connection)
    graph.add_node("check_business_email", node_check_business_email)
    graph.add_node("feature", node_feature)
    graph.add_node("book_demo", node_book_demo)
    graph.add_node("check_user", node_check_user)
    graph.add_node("search_by_url", node_search_by_url)
    graph.add_node("franchise_register", node_franchise_register)
    graph.add_node("social_connect", node_social_connect)
    graph.add_node("check_social_connection", node_check_social_connection)
    graph.set_entry_point("entry")
    graph.add_conditional_edges("entry", router, {
        "RESPOND": "respond",
        "CONFIRMED": "confirmed",
        "SEARCH_BUSINESS": "search_business",
        "NEXT_RESULT": "next_result",
        "ANALYSE": "analyse",
        "CONNECT_BUSINESS": "connect_business",
        "CHECK_LATEST_CONNECTION": "check_latest_connection",
        "CHECK_BUSINESS_EMAIL": "check_business_email",
        "FEATURE": "feature",
        "BOOK_DEMO": "book_demo",
        "CHECK_USER": "check_user",
        "SEARCH_BY_URL": "search_by_url",
        "REGISTER_FRANCHISE": "franchise_register",
        "SOCIAL_CONNECT": "social_connect",
        "CHECK_SOCIAL_CONNECTION": "check_social_connection",
    })
    for node in ["respond", "confirmed", "search_business", "next_result", "analyse",
                 "connect_business", "check_latest_connection", "check_business_email",
                 "feature", "book_demo", "check_user",
                 "social_connect", "check_social_connection",
                 "search_by_url", "franchise_register"]:
        graph.add_edge(node, END)
    return graph.compile()


app_graph = build_graph()


def _fallback(user_id: str) -> str:
    try:
        lang = get_session(user_id).get("lang", "hi")
        if lang == "en":
            return "Sorry, technical issue. Please try again or call 📞 +91 9289344726."
        return "Maafi chahti hoon, kuch problem aayi. Dobara try karein ya call karein: 📞 +91 9289344726"
    except Exception:
        return "Sorry. Call: +91 9289344726"


def chat(user_id: str, message: str) -> str:
    """Process with per-user lock + fail-safe + hallucination guard."""
    lock = _get_user_lock(user_id)
    with lock:
        try:
            save_message(user_id, "user", message)
            result = app_graph.invoke({"user_id": user_id, "message": message})
            response = result.get("response", "")

            # Fail-safe: empty response
            if not response or len(response.strip()) < 3:
                return _fallback(user_id)

            # Hallucination guard: strip leaked action tags
            response = re.sub(r"\[ACTION:[A-Z_]+\].*?\[/ACTION\]", "", response, flags=re.DOTALL).strip()

            return response or _fallback(user_id)

        except Exception as e:
            print(f"[Chat] Error {user_id}: {e}")
            import traceback; traceback.print_exc()
            return _fallback(user_id)