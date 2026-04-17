import re
import threading
import time
from typing import TypedDict, Optional, Any
from langgraph.graph import StateGraph, END
from app.nodes.intent import detect_and_respond
from app.nodes.search import handle_search, handle_next_result
from app.nodes.analyse import handle_analyse
from app.nodes.booking import handle_booking
from app.nodes.connect import handle_connect_link, handle_check_latest_connection, handle_check_email
from app.services.limbu_api import check_user_by_phone
from app.services.redis_service import save_message, get_session, save_session
from app.extractors.entity_extractor import extract_action_params, extract_email
from app.core.llm import llm
from app.core.prompts import get_main_prompt
from langchain_core.messages import SystemMessage, HumanMessage


# ── Keywords ──────────────────────────────────────────────────────
YES_WORDS = {"yes", "haan", "han", "ha", "haa", "confirmed", "confirm",
             "bilkul", "theek", "correct", "right", "sahi", "ji haan",
             "ji ha", "ji", "ok", "okay", "hnji", "haan ji", "sure", "yep", "yup"}

NO_WORDS = {"no", "nahi", "nhi", "nahin", "nope", "not", "galat",
            "wrong", "different", "doosra", "alag", "nhi hai"}

CONNECTED_WORDS = {
    "connect kiya", "ho gaya", "connect ho gaya", "done", "kar liya",
    "connected", "link khola", "kiya", "hogaya", "connect kar liya",
    "ho gayi", "verify karo", "check karo", "connect hua", "hua kya",
    "ho gaya kya", "kya connect", "business connect", "ab hua",
    "connect ho gya", "kr liya", "ho gya", "hua connect", "check kar",
    "connected hai", "connect ho gaya hai"
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
    "kota", "ajmer", "sikar", "bhilwara", "barmer", "jhunjhunu"
]


def is_yes(text: str) -> bool:
    t = text.lower().strip()
    return any(w in t for w in YES_WORDS) and not is_no(t)


def is_no(text: str) -> bool:
    t = text.lower().strip()
    return any(w in t for w in NO_WORDS)


def is_connected(text: str) -> bool:
    t = text.lower().strip()
    return any(w in t for w in CONNECTED_WORDS)


def _try_extract_business(message: str, session: dict):
    """Detect business name + city in same message"""
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
    import re as _re
    business = message
    business = _re.sub(r"(?i)" + found_city, "", business)
    business = _re.sub(r"(?i)(mere|mera|meri|my|ka|ki|ke|business|shop|dhundho|check|batao|find|,|&)", "", business)
    business = business.strip(" ,.-&")
    if len(business) < 3:
        return None
    return f"[ACTION:SEARCH_BUSINESS]name={business}|city={found_city}[/ACTION]"


# ── Background Polling ────────────────────────────────────────────
def start_connection_polling(user_id: str, session_id: str):
    """Poll API every 3 seconds for 5 minutes"""
    def poll():
        import httpx
        from app.core.config import LIMBU_API_BASE
        max_attempts = 100  # 5 min (100 x 3sec)
        for attempt in range(max_attempts):
            time.sleep(3)
            try:
                session = get_session(user_id)
                # Stop if already verified
                if session.get("connect_verified"):
                    print(f"[Poll] Already verified, stopping for {user_id}")
                    break
                # Stop if session_id changed (new connect link sent)
                if session.get("connect_session_id") != session_id:
                    print(f"[Poll] Session changed, stopping old poll for {user_id}")
                    break

                res = httpx.get(
                    f"{LIMBU_API_BASE}/gmb/status",
                    params={"session_id": session_id},
                    timeout=10
                )
                data = res.json()
                print(f"[Poll] {user_id} attempt {attempt+1}: {data.get('status')}")

                if data.get("status") == "success" or data.get("success"):
                    email = data.get("email", "")
                    if email:
                        session["connected_email"] = email
                    session["connect_verified"] = True
                    save_session(user_id, session)
                    # Use updated session for smart response
                    reply = handle_check_latest_connection(user_id, session)
                    save_message(user_id, "assistant", reply)
                    print(f"[Poll] ✅ Connected! User: {user_id}, Email: {email}")
                    break
            except Exception as e:
                print(f"[Poll] Error: {e}")
                time.sleep(5)  # Wait longer on error

    thread = threading.Thread(target=poll, daemon=True)
    thread.start()
    print(f"[Poll] Started for user {user_id}, session {session_id}")


# ── State ─────────────────────────────────────────────────────────
class ChatState(TypedDict, total=False):
    user_id: str
    message: str
    raw_reply: str
    action: str
    response: str
    booking_data: Any
    search_data: Any


# ── Entry Node ────────────────────────────────────────────────────
def entry_node(state: ChatState) -> ChatState:
    user_id = state["user_id"]
    message = state["message"]
    session = get_session(user_id)

    # Mark greeted
    if not session.get("greeted"):
        session["greeted"] = True
        save_session(user_id, session)

    # Check connected words
    if is_connected(message) and not session.get("connect_verified"):
        state["raw_reply"] = "[ACTION:CHECK_LATEST_CONNECTION][/ACTION]"
        state["action"] = "CHECK_LATEST_CONNECTION"
        return state

    # Handle confirmation after business shown
    if session.get("found_place") and not session.get("confirmed"):
        if is_yes(message):
            session["confirmed"] = True
            save_session(user_id, session)
            state["raw_reply"] = "__CONFIRMED__"
            state["action"] = "CONFIRMED"
            return state
        elif is_no(message):
            state["raw_reply"] = "__NEXT__"
            state["action"] = "NEXT_RESULT"
            return state

    # Handle analyse after confirmation
    if session.get("confirmed") and not session.get("analysis"):
        analyse_words = ["analyse", "analysis", "check", "dekho", "batao",
                         "report", "haan", "yes", "han", "ha", "ok", "sure",
                         "kar do", "karein", "ji", "need", "chahiye", "do"]
        if any(w in message.lower() for w in analyse_words):
            state["raw_reply"] = "[ACTION:ANALYSE][/ACTION]"
            state["action"] = "ANALYSE"
            return state

    # Email detection after connect link sent
    if session.get("connect_link_sent") and not session.get("connect_verified"):
        email = extract_email(message)
        if email:
            state["raw_reply"] = f"[ACTION:CHECK_BUSINESS_EMAIL]email={email}[/ACTION]"
            state["action"] = "CHECK_BUSINESS_EMAIL"
            return state

    # Smart business+city detection
    smart = _try_extract_business(message, session)
    if smart:
        state["raw_reply"] = smart
        state["action"] = "SEARCH_BUSINESS"
        return state

    # Claude response
    reply = detect_and_respond(user_id, message)
    state["raw_reply"] = reply
    state["action"] = _detect_action(reply)
    return state


def _detect_action(text: str) -> str:
    actions = [
        "SEARCH_BUSINESS", "NEXT_RESULT", "ANALYSE",
        "CONNECT_BUSINESS", "CHECK_LATEST_CONNECTION",
        "CHECK_BUSINESS_EMAIL", "BOOK_DEMO", "CHECK_USER"
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
    name = place.get("displayName", {}).get("text", "aapka business")
    
    # Match language based on last user message
    msg = state.get("message", "").lower()
    if any(w in msg for w in ["yes", "correct", "right"]):
        reply = f"Great! ✅ **{name}** confirmed.\n\nShall I analyse your Google Business Profile and show improvement areas? 😊"
    else:
        reply = f"Bahut achha! ✅ **{name}** confirm ho gaya.\n\nKya main aapki Google Business Profile analyse karoon aur improvement ki scope bataaon? 😊"
    
    save_message(user_id, "assistant", reply)
    state["response"] = reply
    return state


def node_search_business(state: ChatState) -> ChatState:
    user_id = state["user_id"]
    session = get_session(user_id)
    match = re.search(r'\[ACTION:SEARCH_BUSINESS\](.*?)\[/ACTION\]', state["raw_reply"], re.DOTALL)
    if match:
        params = extract_action_params(match.group(1))
        reply = handle_search(user_id, session, params.get("name", ""), params.get("city", ""))
    else:
        reply = "Kripya apna business naam aur city batayein. 😊"
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
    # Start background polling
    session = get_session(user_id)
    session_id = session.get("connect_session_id", "")
    if session_id:
        start_connection_polling(user_id, session_id)
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
    match = re.search(r'\[ACTION:CHECK_BUSINESS_EMAIL\](.*?)\[/ACTION\]', state["raw_reply"], re.DOTALL)
    if match:
        params = extract_action_params(match.group(1))
        reply = handle_check_email(user_id, session, params.get("email", ""))
    else:
        reply = "Kripya apni registered email batayein. 😊"
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
        reply = "Kripya naam, phone number, aur convenient date/time batayein. 😊"
    save_message(user_id, "assistant", reply)
    state["response"] = reply
    return state


def node_check_user(state: ChatState) -> ChatState:
    user_id = state["user_id"]
    session = get_session(user_id)
    match = re.search(r'\[ACTION:CHECK_USER\](.*?)\[/ACTION\]', state["raw_reply"], re.DOTALL)
    if match:
        params = extract_action_params(match.group(1))
        phone = params.get("phone", "")
        user_data = check_user_by_phone(phone)
        if user_data:
            session["user_info"] = user_data
            save_session(user_id, session)
            status = user_data.get("subscription", {}).get("status", "inactive")
            ctx = f"User found — plan: {status}. Continue naturally in user's language."
        else:
            ctx = "New user. Continue demo booking in user's language."
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
        "BOOK_DEMO": "book_demo",
        "CHECK_USER": "check_user",
    })

    for node in ["respond", "confirmed", "search_business", "next_result",
                 "analyse", "connect_business", "check_latest_connection",
                 "check_business_email", "book_demo", "check_user"]:
        graph.add_edge(node, END)

    return graph.compile()


app_graph = build_graph()


def chat(user_id: str, message: str) -> str:
    save_message(user_id, "user", message)
    result = app_graph.invoke({"user_id": user_id, "message": message})
    return result.get("response", "Kshama karein, kuch problem aayi. Dobara try karein ya 📞 9283344726 par call karein.")