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
from app.services.redis_service import save_message, get_session, save_session
from app.extractors.entity_extractor import extract_action_params, extract_email
from app.core.llm import llm
from app.core.prompts import get_main_prompt
from langchain_core.messages import SystemMessage, HumanMessage


# ── Keywords ──────────────────────────────────────────────────────
YES_WORDS = {
    "yes", "haan", "han", "ha", "haa", "confirmed", "confirm",
    "bilkul", "theek", "correct", "right", "sahi", "ji haan",
    "ji ha", "ji", "ok", "okay", "hnji", "haan ji", "sure", "yep", "yup",
    "kar do", "kardo", "bhejo", "de do", "zaroor", "please"
}

NO_WORDS = {
    "no", "nahi", "nhi", "nahin", "nope", "not", "galat",
    "wrong", "different", "doosra", "alag", "nhi hai", "mat karo", "band karo"
}

CONNECTED_WORDS = {
    "connect kiya", "ho gaya", "connect ho gaya", "done", "kar liya",
    "connected", "link khola", "kiya", "hogaya", "connect kar liya",
    "ho gayi", "verify karo", "check karo", "connect hua",
    "ho gaya kya", "kya connect", "ab hua", "connect ho gya",
    "kr liya", "ho gya", "hua connect", "check kar",
    "connected hai", "connect ho gaya hai", "hua kya", "link click"
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
    "kota", "ajmer", "sikar", "bhilwara", "barmer", "jhunjhunu",
    "vadodara", "gandhinagar"
]


def is_yes(text: str) -> bool:
    t = text.lower().strip()
    return any(w in t for w in YES_WORDS) and not is_no(t)


def is_no(text: str) -> bool:
    t = text.lower().strip()
    return any(w in t for w in NO_WORDS)


def is_connected_confirm(text: str) -> bool:
    t = text.lower().strip()
    return any(w in t for w in CONNECTED_WORDS)


def _try_extract_business(message: str, session: dict):
    """Auto-detect business name + city in same message"""
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
        r"(?i)(mere|mera|meri|my|ka|ki|ke|business|shop|dhundho|check|batao|find|,|&|hai|ka naam)",
        "", business
    )
    business = business.strip(" ,.-&")
    if len(business) < 3:
        return None
    return f"[ACTION:SEARCH_BUSINESS]name={business}|city={found_city}[/ACTION]"


# ── Connection Polling ─────────────────────────────────────────────
def start_connection_polling(user_id: str, phone: str):
    """Poll GMB status every 3s for max 5 min using phone number"""
    def poll():
        import httpx
        from app.core.config import LIMBU_API_BASE
        from app.nodes.connect import _build_connected_response

        for attempt in range(100):  # 100 x 3s = 5 min
            time.sleep(3)
            try:
                session = get_session(user_id)
                if session.get("connect_verified"):
                    print(f"[ConnPoll] Already verified, stopping for {user_id}")
                    break
                if session.get("connect_phone") != phone:
                    print(f"[ConnPoll] Phone changed, stopping old poll for {user_id}")
                    break

                res = httpx.get(
                    f"{LIMBU_API_BASE}/gmb/status",
                    params={"phone": phone},
                    timeout=10
                )
                data = res.json()
                print(f"[ConnPoll] {user_id} attempt {attempt+1}: {data.get('status')}")

                if data.get("status") == "success" or data.get("success"):
                    email = data.get("email", "")
                    locations = (
                        data.get("locationsData") or
                        data.get("businesses") or
                        data.get("data") or []
                    )
                    session["connect_verified"] = True
                    session["connected_email"] = email
                    session["connected_businesses"] = locations
                    save_session(user_id, session)

                    reply = _build_connected_response(session, locations, email)
                    save_message(user_id, "assistant", reply)
                    print(f"[ConnPoll] Connected! user={user_id} email={email}")
                    break

            except Exception as e:
                print(f"[ConnPoll] Error: {e}")
                time.sleep(5)

    t = threading.Thread(target=poll, daemon=True)
    t.start()
    print(f"[ConnPoll] Started for user={user_id} phone={phone}")


# ── Detect language from message ───────────────────────────────────
def _detect_lang(message: str) -> str:
    """Detect if message is English or Hindi/mixed"""
    msg = message.strip().lower()
    # Common English-only words
    english_signals = [
        "yes", "no", "hello", "hi", "hey", "please", "thanks", "thank you",
        "sure", "okay", "ok", "what", "how", "when", "where", "who", "why",
        "send", "right", "correct", "wrong", "done", "connected", "good",
        "great", "awesome", "nice", "help", "need", "want", "can", "i am",
        "i'm", "my", "me", "we", "our", "the", "a ", "an ", "is ", "are ",
        "do ", "did", "will", "shall", "would", "could", "should", "get",
        "got", "find", "show", "check", "start", "stop", "more", "less"
    ]
    words = msg.split()
    if not words:
        return "hi"
    eng_count = sum(1 for w in words if any(sig in w for sig in english_signals))
    # If majority English words → English
    if eng_count >= max(1, len(words) * 0.4):
        return "en"
    return "hi"


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

    # ── Detect and save language ──────────────────────────────────
    lang = _detect_lang(message)
    if lang != session.get("lang"):
        session["lang"] = lang
        save_session(user_id, session)

    # ── Mark greeted ──────────────────────────────────────────────
    if not session.get("greeted"):
        session["greeted"] = True
        save_session(user_id, session)

    # ── 1. Connected words check (only if link was sent, not yet verified)
    if session.get("connect_link_sent") and not session.get("connect_verified"):
        if is_connected_confirm(message):
            state["action"] = "CHECK_LATEST_CONNECTION"
            return state

    # ── 2. Business confirmation (yes/no after showing result)
    if session.get("found_place") and not session.get("confirmed"):
        if is_yes(message):
            session["confirmed"] = True
            save_session(user_id, session)
            state["action"] = "CONFIRMED"
            return state
        elif is_no(message):
            state["action"] = "NEXT_RESULT"
            return state

    # ── 3. Analyse trigger
    if session.get("confirmed") and not session.get("analysis"):
        analyse_triggers = [
            "analyse", "analysis", "check", "dekho", "batao", "report",
            "haan", "yes", "han", "ha", "ok", "sure", "kar do",
            "karein", "ji", "need", "chahiye", "do", "nikalo", "dikhao"
        ]
        if any(w in msg_lower for w in analyse_triggers):
            state["action"] = "ANALYSE"
            return state

    # ── 4. Connect — YES after analysis/report
    if session.get("analysis") and not session.get("connect_link_sent"):
        if is_yes(message):
            state["action"] = "CONNECT_BUSINESS"
            return state

    # ── 5. Feature triggers (only after connected)
    if session.get("connect_verified"):
        feature_keywords = {
            "health report": "health_score", "health score": "health_score", "health": "health_score",
            "magic qr": "magic_qr", "qr code": "magic_qr", "qr": "magic_qr",
            "insight": "insights", "performance": "insights",
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

    # ── 6. Email detection (after connect link sent)
    if session.get("connect_link_sent") and not session.get("connect_verified"):
        email = extract_email(message)
        if email:
            state["action"] = "CHECK_BUSINESS_EMAIL"
            state["raw_reply"] = f"[ACTION:CHECK_BUSINESS_EMAIL]email={email}[/ACTION]"
            return state

    # ── 7. Smart business+city detection
    smart = _try_extract_business(message, session)
    if smart:
        state["raw_reply"] = smart
        state["action"] = "SEARCH_BUSINESS"
        return state

    # ── 8. Claude handles everything (general Q&A, support, etc.)
    reply = detect_and_respond(user_id, message)

    # If Claude returned an action tag, route to that node (NO double-save)
    detected = _detect_action(reply)
    if detected != "RESPOND":
        state["action"] = detected
        if detected == "FEATURE":
            m = re.search(r'\[ACTION:FEATURE\]type=(\w+)\[/ACTION\]', reply)
            if m:
                state["feature_type"] = m.group(1)
        elif detected == "CONNECT_BUSINESS":
            pass  # node_connect_business will handle and save
        elif detected == "SEARCH_BUSINESS":
            state["raw_reply"] = reply
        else:
            state["raw_reply"] = reply
        return state

    # Pure text response — save via RESPOND node
    state["raw_reply"] = reply
    state["action"] = "RESPOND"
    return state


def _detect_action(text: str) -> str:
    actions = [
        "SEARCH_BUSINESS", "NEXT_RESULT", "ANALYSE",
        "CONNECT_BUSINESS", "CHECK_LATEST_CONNECTION",
        "CHECK_BUSINESS_EMAIL", "FEATURE", "BOOK_DEMO", "CHECK_USER"
    ]
    for action in actions:
        if f"[ACTION:{action}]" in text:
            return action
    return "RESPOND"


# ── Nodes ─────────────────────────────────────────────────────────
def node_respond(state: ChatState) -> ChatState:
    """Save and return plain Claude text response"""
    save_message(state["user_id"], "assistant", state["raw_reply"])
    state["response"] = state["raw_reply"]
    return state


def node_confirmed(state: ChatState) -> ChatState:
    user_id = state["user_id"]
    session = get_session(user_id)
    place = session.get("found_place", {})
    name = place.get("displayName", {}).get("text", "your business")
    lang = session.get("lang", "hi")

    if lang == "en":
        reply = f"Great! ✅ *{name}* confirmed.\n\nShall I analyse your Google Business Profile? 😊"
    else:
        reply = f"Bahut achha! ✅ *{name}* confirm ho gaya.\n\nKya main aapki Google Business Profile analyse karoon? 😊"

    save_message(user_id, "assistant", reply)
    state["response"] = reply
    return state


def node_search_business(state: ChatState) -> ChatState:
    user_id = state["user_id"]
    session = get_session(user_id)
    raw = state.get("raw_reply", "")
    match = re.search(r'\[ACTION:SEARCH_BUSINESS\](.*?)\[/ACTION\]', raw, re.DOTALL)
    if match:
        params = extract_action_params(match.group(1))
        reply = handle_search(user_id, session, params.get("name", ""), params.get("city", ""))
    else:
        lang = session.get("lang", "hi")
        reply = "Please share your business name and city. 😊" if lang == "en" else "Kripya apna business naam aur city batayein. 😊"
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
    """
    Generate connect link and save ONCE.
    node_respond is NOT called for this action — no double save.
    """
    user_id = state["user_id"]
    session = get_session(user_id)
    reply = handle_connect_link(user_id, session)

    # Start polling — phone saved in session by handle_connect_link
    session = get_session(user_id)
    phone = session.get("connect_phone", "")
    if phone:
        start_connection_polling(user_id, phone)
    else:
        print(f"[ConnectNode] No phone for {user_id} — polling not started")

    # Save ONCE here — RESPOND node not called for this action
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
    raw = state.get("raw_reply", "")
    match = re.search(r'\[ACTION:CHECK_BUSINESS_EMAIL\](.*?)\[/ACTION\]', raw, re.DOTALL)
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
        raw = state.get("raw_reply", "")
        m = re.search(r'\[ACTION:FEATURE\]type=(\w+)\[/ACTION\]', raw)
        if m:
            feature_type = m.group(1)

    lang = session.get("lang", "hi")
    if not feature_type:
        reply = "Which feature would you like? Health Report, Magic QR, Insights, Website, or Review Reply? 😊" \
            if lang == "en" else \
            "Kaunsa feature chahiye? Health Report, Magic QR, Insights, Website, ya Review Reply? 😊"
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
        reply = handle_booking(
            user_id,
            name=params.get("name", ""),
            phone=params.get("phone", ""),
            date=params.get("date", ""),
            time=params.get("time", "")
        )
    else:
        session = get_session(user_id)
        lang = session.get("lang", "hi")
        reply = "Please share your name, phone number, and preferred date/time. 😊" \
            if lang == "en" else \
            "Kripya naam, phone number, aur date/time batayein. 😊"
    save_message(user_id, "assistant", reply)
    state["response"] = reply
    return state


def node_check_user(state: ChatState) -> ChatState:
    user_id = state["user_id"]
    session = get_session(user_id)
    raw = state.get("raw_reply", "")
    match = re.search(r'\[ACTION:CHECK_USER\](.*?)\[/ACTION\]', raw, re.DOTALL)
    if match:
        params = extract_action_params(match.group(1))
        phone = params.get("phone", "")
        user_data = check_user_by_phone(phone)
        lang = session.get("lang", "hi")
        if user_data:
            session["user_info"] = user_data
            save_session(user_id, session)
            status = user_data.get("subscription", {}).get("status", "inactive")
            ctx = f"User found — plan: {status}. Continue naturally in {'English' if lang=='en' else 'Hindi'}."
        else:
            ctx = f"New user. Continue demo booking in {'English' if lang=='en' else 'Hindi'}."
        follow_up = llm.invoke([
            SystemMessage(content=get_main_prompt(session)),
            HumanMessage(content=f"[SYSTEM: {ctx}]")
        ])
        reply = follow_up.content.strip()
    else:
        reply = "Please share your phone number. 😊"
    save_message(user_id, "assistant", reply)
    state["response"] = reply
    return state


# ── Router ────────────────────────────────────────────────────────
def router(state: ChatState) -> str:
    return state.get("action", "RESPOND")


# ── Build Graph ───────────────────────────────────────────────────
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

    for node in [
        "respond", "confirmed", "search_business", "next_result",
        "analyse", "connect_business", "check_latest_connection",
        "check_business_email", "feature", "book_demo", "check_user"
    ]:
        graph.add_edge(node, END)

    return graph.compile()


app_graph = build_graph()


def chat(user_id: str, message: str) -> str:
    save_message(user_id, "user", message)
    result = app_graph.invoke({"user_id": user_id, "message": message})
    return result.get(
        "response",
        "Sorry, something went wrong. Please try again or call 📞 9283344726."
    )