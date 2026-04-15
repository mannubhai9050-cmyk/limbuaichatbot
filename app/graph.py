import re
from langgraph.graph import StateGraph, END
from typing import TypedDict, Optional, Any
from typing import TypedDict, Optional
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


# ── Confirmation Keywords ─────────────────────────────────────────
YES_WORDS = {"yes", "haan", "han", "ha", "haa", "confirmed", "confirm",
             "bilkul", "theek", "correct", "right", "sahi", "ji haan",
             "ji ha", "ji", "ok", "okay", "hnji", "haan ji"}
NO_WORDS = {"no", "nahi", "nhi", "nahin", "nope", "not", "galat",
            "wrong", "different", "doosra", "alag", "nhi hai"}
CONNECTED_WORDS = {"connect kiya", "ho gaya", "connect ho gaya", "done",
                   "kar liya", "connected", "link khola", "kiya", "hogaya",
                   "connect kar liya", "ho gayi", "verify karo", "check karo"}


def is_yes(text: str) -> bool:
    t = text.lower().strip()
    return any(w in t for w in YES_WORDS) and not is_no(t)


def is_no(text: str) -> bool:
    t = text.lower().strip()
    return any(w in t for w in NO_WORDS)


def is_connected(text: str) -> bool:
    t = text.lower().strip()
    return any(w in t for w in CONNECTED_WORDS)


# ── State ─────────────────────────────────────────────────────────
class ChatState(TypedDict, total=False):
    user_id: str
    message: str
    raw_reply: str
    action: str
    response: str
    booking_data: Any
    search_data: Any
    biz_state: Any



# Smart Business Extractor
INDIAN_CITIES = [
    "delhi", "mumbai", "bangalore", "bengaluru", "hyderabad", "chennai",
    "kolkata", "pune", "ahmedabad", "jaipur", "surat", "lucknow",
    "kanpur", "nagpur", "indore", "bhopal", "patna", "ludhiana",
    "agra", "nashik", "faridabad", "gurgaon", "gurugram", "noida",
    "meerut", "rajkot", "varanasi", "amritsar", "ranchi", "howrah",
    "coimbatore", "jabalpur", "visakhapatnam", "guwahati", "chandigarh",
    "mysore", "mysuru", "jodhpur", "raipur", "kochi", "dehradun",
    "nuh", "mewat", "rewari", "rohtak", "sonipat", "panipat",
    "ambala", "karnal", "hisar", "panchkula", "manesar", "bhiwadi",
    "allahabad", "prayagraj", "bhubaneswar", "srinagar", "jammu"
]

def _try_extract_business(message: str, session: dict):
    """If message has business name + city together, return action tag"""
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

# ── Entry Node ────────────────────────────────────────────────────
def entry_node(state: ChatState) -> ChatState:
    user_id = state["user_id"]
    message = state["message"]
    session = get_session(user_id)

    # ── Check if user connected business ─────────────────────────
    if is_connected(message) and not session.get("confirmed"):
        state["raw_reply"] = "[ACTION:CHECK_LATEST_CONNECTION][/ACTION]"
        state["action"] = "CHECK_LATEST_CONNECTION"
        return state

    # ── Handle confirmation (after business shown) ────────────────
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

    # ── Handle analyse trigger after confirmation ─────────────────
    if session.get("confirmed") and not session.get("analysis"):
        analyse_words = ["analyse", "analysis", "check karo", "dekho", "batao",
                         "report", "haan", "yes", "han", "ha", "ok", "sure",
                         "kar do", "karein", "ji"]
        if any(w in message.lower() for w in analyse_words):
            state["raw_reply"] = "[ACTION:ANALYSE][/ACTION]"
            state["action"] = "ANALYSE"
            return state

    # ── Check if user shared email for verification ───────────────
    if session.get("connect_link_sent") and not session.get("connected_email"):
        email = extract_email(message)
        if email:
            state["raw_reply"] = f"[ACTION:CHECK_BUSINESS_EMAIL]email={email}[/ACTION]"
            state["action"] = "CHECK_BUSINESS_EMAIL"
            return state

    # ── Normal Claude response ────────────────────────────────────
    # Smart: detect business+city in one message
    _smart = _try_extract_business(message, session)
    if _smart:
        state["raw_reply"] = _smart
        state["action"] = "SEARCH_BUSINESS"
        return state

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


# ── Router ────────────────────────────────────────────────────────
def router(state: ChatState) -> str:
    return state.get("action", "RESPOND")


# ── Nodes ─────────────────────────────────────────────────────────

def node_respond(state: ChatState) -> ChatState:
    user_id = state["user_id"]
    reply = state["raw_reply"]
    save_message(user_id, "assistant", reply)
    state["response"] = reply
    return state


def node_confirmed(state: ChatState) -> ChatState:
    user_id = state["user_id"]
    session = get_session(user_id)
    place = session.get("found_place", {})
    name = place.get("displayName", {}).get("text", "aapka business")
    reply = (
        f"Bahut achha! ✅ **{name}** confirm ho gaya.\n\n"
        f"Kya aap chahte hain ki main aapki Google Business Profile ko analyse karoon "
        f"aur bataaon ki kahan improvement ki scope hai? 😊"
    )
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
        reply = "Ji, aapka business naam aur city batayein? 😊"
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
    session["connect_link_sent"] = True
    save_session(user_id, session)
    reply = handle_connect_link(user_id, session)
    save_message(user_id, "assistant", reply)
    state["response"] = reply
    return state


def node_check_latest_connection(state: ChatState) -> ChatState:
    """Auto-check latest connection — no email needed from user"""
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
        reply = "Ji, aapki registered email address share karein. 😊"
    save_message(user_id, "assistant", reply)
    state["response"] = reply
    return state


def node_book_demo(state: ChatState) -> ChatState:
    user_id = state["user_id"]
    raw = state.get("raw_reply", "")
    # Strip any visible BOOK_DEMO text from raw reply before showing
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
        # Try to parse from raw text if Claude wrote params without proper tags
        import re as _re2
        name_m = _re2.search(r"name[=:]\s*([A-Za-z\s]+)", raw, _re2.IGNORECASE)
        phone_m = _re2.search(r"phone[=:]\s*(\d{10})", raw)
        date_m = _re2.search(r"date[=:]\s*(\d{4}-\d{2}-\d{2})", raw)
        time_m = _re2.search(r"time[=:]\s*([\d:]+\s*[AaPp][Mm])", raw)
        if name_m and phone_m and date_m and time_m:
            reply = handle_booking(
                user_id,
                name=name_m.group(1).strip(),
                phone=phone_m.group(1).strip(),
                date=date_m.group(1).strip(),
                time=time_m.group(1).strip()
            )
        else:
            reply = "Ji, demo book karne ke liye naam, phone number, aur convenient date/time batayein. 😊"
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
            ctx = f"User found — plan: {status}. Respectfully continue."
        else:
            ctx = "New user. Respectfully continue with demo booking."
        follow_up = llm.invoke([
            SystemMessage(content=get_main_prompt(session)),
            HumanMessage(content=f"[SYSTEM: {ctx}]")
        ])
        reply = follow_up.content.strip()
    else:
        reply = "Ji, aapka phone number share karein? 😊"
    save_message(user_id, "assistant", reply)
    state["response"] = reply
    return state


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