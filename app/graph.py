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
        "CHECK_BUSINESS_EMAIL", "BOOK_DEMO", "CHECK_USER",
        "SHOW_PLAN", "CHECK_PAYMENT", "DASHBOARD_ACTION"
    ]
    for action in actions:
        if f"[ACTION:{action}]" in text:
            return action
    return "RESPOND"


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
    # NOTE: Polling is handled by analyse.py — no duplicate polling here
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


def node_show_plan(state: ChatState) -> ChatState:
    """Show plan details with payment link"""
    user_id = state["user_id"]
    raw = state.get("raw_reply", "")
    import re as _re
    match = _re.search(r'\[ACTION:SHOW_PLAN\](.*?)\[/ACTION\]', raw, re.DOTALL)
    if match:
        params = extract_action_params(match.group(1))
        plan_name = params.get("plan", "Professional Plan")
        cycle = params.get("cycle", "monthly")
        from app.services.plans_service import get_plan_by_name, format_plan_message
        plan = get_plan_by_name(plan_name, cycle)
        if plan:
            session = get_session(user_id)
            plan_msg = format_plan_message(plan, "", user_id)
            reply = (
                f"Yeh hai aapke liye best plan:\n\n"
                f"{plan_msg}\n\n"
                f"Payment link pe click karke directly subscribe kar sakte hain. "
                f"Koi sawaal ho toh batayein! 😊"
            )
        else:
            reply = f"Plan details fetch karne mein problem aayi. Kripya 📞 9283344726 par call karein."
    else:
        reply = "Kaunsa plan dekhna chahte hain? Basic, Professional, ya Premium? 😊"
    save_message(user_id, "assistant", reply)
    state["response"] = reply
    return state


def node_check_payment(state: ChatState) -> ChatState:
    """Check payment status"""
    user_id = state["user_id"]
    session = get_session(user_id)
    email = session.get("connected_email", "")

    if email:
        import httpx
        from app.core.config import LIMBU_API_BASE
        try:
            with httpx.Client(timeout=10) as client:
                res = client.get(
                    f"{LIMBU_API_BASE}/users",
                    params={"email": "info@limbu.ai", "search": email}
                )
                data = res.json()
                if data.get("success") and data.get("users"):
                    user_data = data["users"][0]
                    sub = user_data.get("subscription", {})
                    status = sub.get("status", "")
                    plan_name = sub.get("planName", "")
                    if status == "active":
                        reply = "🎉 **Payment confirmed!**\n\n" + f"✅ **{plan_name}** active ho gaya hai.\n\n" + "Hamari team aapke GMB profile par kaam shuru kar degi.\nInvoice aapki email par bhej diya jayega.\n\nShukriya aapka! 🙏"
                    else:
                        reply = "Abhi payment confirm nahi mili. 🤔\n\nThodi der mein update ho jayega.\nYa call karein: 📞 9283344726"
                else:
                    reply = "Payment status check karne mein problem aayi. Kripya 📞 9283344726 par call karein."
        except Exception as e:
            reply = "Technical problem aayi. Kripya 📞 9283344726 par call karein."
    else:
        reply = "Kripya apni registered email batayein taaki payment verify kar sakein."

    save_message(user_id, "assistant", reply)
    state["response"] = reply
    return state


def node_dashboard_action(state: ChatState) -> ChatState:
    """Trigger Limbu.ai dashboard action"""
    user_id = state["user_id"]
    session = get_session(user_id)
    raw = state.get("raw_reply", "")

    import re as _re
    match = _re.search(r'\[ACTION:DASHBOARD_ACTION\](.*?)\[/ACTION\]', raw, re.DOTALL)

    if not match:
        reply = "Kripya batayein — Health Score, Magic QR, Website, ya Insights mein se kya chahiye? 😊"
        save_message(user_id, "assistant", reply)
        state["response"] = reply
        return state

    params = extract_action_params(match.group(1))
    action = params.get("action", "")
    location_id = params.get("location_id", "")
    email = params.get("email", session.get("connected_email", ""))
    # Get location_id from session if not provided
    if not location_id and session.get("connected_businesses"):
        bizs = session["connected_businesses"]
        if bizs:
            location_id = bizs[0].get("locationResourceName", "")

    action_labels = {
        "health_score": "Full Health Score Report",
        "magic_qr": "Magic QR Code",
        "website": "Optimized Website",
        "insights": "Business Insights",
        "social_posts": "Social Media Posts"
    }
    action_label = action_labels.get(action, action)

    # Show processing message
    reply = f"⏳ **{action_label}** generate ho raha hai...\n\nThodi der mein ready ho jayega. Main aapko notify kar doongi! 😊"
    save_message(user_id, "assistant", reply)
    state["response"] = reply

    # Save action in session
    session["pending_action"] = {
        "action": action,
        "location_id": location_id,
        "email": email,
        "label": action_label
    }
    save_session(user_id, session)

    # Trigger action API in background
    import threading
    def _trigger():
        from app.services.actions_service import trigger_action
        from app.services.redis_service import save_message as _save
        phone = user_id.replace("wa_", "") if user_id.startswith("wa_") else user_id.replace("u_", "")
        result = trigger_action(action, phone, location_id, email)
        if result.get("success"):
            msg = (
                f"✅ **{action_label} ready hai!**\n\n"
                f"{result.get('message', '')}\n"
            )
            if result.get("url"):
                msg += f"\n🔗 {result['url']}"
            if result.get("qr_url"):
                msg += f"\n🔮 QR Code: {result['qr_url']}"
        else:
            msg = (
                f"⏳ **{action_label}** process ho raha hai.\n\n"
                f"Ready hone pe aapko notify kiya jayega. "
                f"Ya check karein: 📞 9283344726"
            )
        _save(user_id, "assistant", msg)
        print(f"[Action] {action} complete for {user_id}")

    threading.Thread(target=_trigger, daemon=True).start()
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
    graph.add_node("show_plan", node_show_plan)
    graph.add_node("check_payment", node_check_payment)
    graph.add_node("dashboard_action", node_dashboard_action)

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
        "SHOW_PLAN": "show_plan",
        "CHECK_PAYMENT": "check_payment",
        "DASHBOARD_ACTION": "dashboard_action",
    })

    for node in ["respond", "confirmed", "search_business", "next_result",
                 "analyse", "connect_business", "check_latest_connection",
                 "check_business_email", "book_demo", "check_user",
                 "show_plan", "check_payment", "dashboard_action"]:
        graph.add_edge(node, END)

    return graph.compile()


app_graph = build_graph()


def chat(user_id: str, message: str) -> str:
    save_message(user_id, "user", message)
    result = app_graph.invoke({"user_id": user_id, "message": message})
    return result.get("response", "Kshama karein, kuch problem aayi. Dobara try karein ya 📞 9283344726 par call karein.")