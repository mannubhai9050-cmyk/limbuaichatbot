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
def _llm_reply(user_id: str, instruction: str) -> str:
    """Generate a conversational reply using Claude. Strips any accidental action tags."""
    session = get_session(user_id)
    history = get_history(user_id)
    last_user_msg = ""
    for msg in reversed(history):
        if msg.get("role") == "user":
            last_user_msg = msg.get("content", "")
            break
    messages = [
        SystemMessage(content=get_main_prompt(session)),
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


# ── Keywords ──────────────────────────────────────────────────────
YES_WORDS = {
    "yes", "haan", "han", "ha", "haa", "confirmed", "confirm",
    "bilkul", "theek", "correct", "right", "sahi", "ji haan",
    "ji ha", "ji", "ok", "okay", "hnji", "sure", "yep", "yup",
    "kar do", "kardo", "bhejo", "de do", "zaroor", "please"
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


def _try_extract_business(message: str, session: dict):
    if session.get("found_place") or session.get("search_places"):
        return None
    msg_lower = message.lower().strip()
    found_city = None
    for city in INDIAN_CITIES:
        if city in msg_lower:
            found_city = city.capitalize()
            break
    if not found_city:
        return None
    business = re.sub(r"(?i)" + found_city, "", message)
    business = re.sub(
        r"(?i)(mere|mera|meri|my|ka|ki|ke|business|shop|dhundho|check|batao|find|,|&|hai|ka naam|mein|me|se|ka|ki)",
        " ", business
    )
    business = re.sub(r"\s+", " ", business).strip(" ,.-& ")
    generic_starts = [
        "manufacturer", "manufacturers", "supplier", "suppliers", "dealer",
        "traders", "trader", "shop", "store", "company", "business",
        "service", "services", "center", "centre", "restaurant", "clinic",
        "hospital", "hotel", "school", "college", "office", "factory",
        "i am", "i am on", "i am in", "every kind", "all kind", "all type"
    ]
    if len(business) < 3:
        return None
    bl = business.lower()
    for g in generic_starts:
        if bl == g or bl.startswith(g + " ") or bl.startswith(g + "s "):
            return None
    meaningful_words = [w for w in business.split() if len(w) > 3 and w.lower() not in
                        {"every", "kind", "type", "bags", "items", "things", "stuff",
                         "product", "products", "work", "works", "this", "that"}]
    if len(meaningful_words) == 0:
        return None
    if business.lower() in [c.lower() for c in INDIAN_CITIES]:
        return None
    return f"[ACTION:SEARCH_BUSINESS]name={business}|city={found_city}[/ACTION]"


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
                    break
                if session.get("connect_phone") != phone:
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

    # Language detection
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

    # ── 3. Analyse ────────────────────────────────────────────────
    if session.get("confirmed") and not session.get("analysis"):
        if is_yes(message):
            state["action"] = "ANALYSE"
            return state
        analyse_words = ["analyse", "analysis", "check", "report", "karein",
                         "karo", "nikalo", "dikhao", "bata", "batao", "dekho"]
        if any(w in msg_lower for w in analyse_words):
            state["action"] = "ANALYSE"
            return state

    # ── 4. Connect after analysis ─────────────────────────────────
    if session.get("analysis") and not session.get("connect_link_sent"):
        if is_yes(message):
            state["action"] = "CONNECT_BUSINESS"
            return state

    # ── 5. Features after connected ───────────────────────────────
    if session.get("connect_verified"):
        businesses = session.get("connected_businesses", [])
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

    # ── 7. Business + city ────────────────────────────────────────
    smart = _try_extract_business(message, session)
    if smart:
        state["raw_reply"] = smart
        state["action"] = "SEARCH_BUSINESS"
        return state

    # ── 8. Claude LLM ─────────────────────────────────────────────
    reply = detect_and_respond(user_id, message)
    detected = _detect_action(reply)
    if detected != "RESPOND":
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
    state["raw_reply"] = clean_reply
    state["action"] = "RESPOND"
    return state


def _detect_action(text: str) -> str:
    actions = [
        "SEARCH_BUSINESS", "NEXT_RESULT", "ANALYSE", "CONNECT_BUSINESS",
        "CHECK_LATEST_CONNECTION", "CHECK_BUSINESS_EMAIL", "FEATURE",
        "BOOK_DEMO", "CHECK_USER"
    ]
    for action in actions:
        if f"[ACTION:{action}]" in text:
            return action
    return "RESPOND"


# ── Nodes ─────────────────────────────────────────────────────────
def node_respond(state: ChatState) -> ChatState:
    save_message(state["user_id"], "assistant", state["raw_reply"])
    state["response"] = state["raw_reply"]
    return state


def node_confirmed(state: ChatState) -> ChatState:
    user_id = state["user_id"]
    session = get_session(user_id)
    place = session.get("found_place", {})
    name = place.get("displayName", {}).get("text", "your business")
    reply = _llm_reply(
        user_id,
        f"Business *{name}* confirm ho gaya hai. "
        "Warmly acknowledge karo. Phir poocho: "
        "Kya main Google Business Profile analyse karoon? "
        "Do NOT say business is connected. Do NOT mention any connection status."
    )
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
    })
    for node in ["respond", "confirmed", "search_business", "next_result", "analyse",
                 "connect_business", "check_latest_connection", "check_business_email",
                 "feature", "book_demo", "check_user"]:
        graph.add_edge(node, END)
    return graph.compile()


app_graph = build_graph()


def chat(user_id: str, message: str) -> str:
    lock = _get_user_lock(user_id)
    with lock:
        save_message(user_id, "user", message)
        result = app_graph.invoke({"user_id": user_id, "message": message})
        return result.get(
            "response",
            "Sorry, something went wrong. Please try again or call 📞 9283344726."
        )