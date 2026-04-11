from langgraph.graph import StateGraph, END
from app.chatbot import chatbot_response
from app.memory import clear_booking_state
import httpx
import json
import re
from datetime import date

LIMBU_API = "https://limbu.ai/api"
LIMBU_EMAIL = "info@limbu.ai"


def check_user(phone: str) -> dict | None:
    try:
        with httpx.Client(timeout=10) as client:
            res = client.get(f"{LIMBU_API}/users", params={"email": LIMBU_EMAIL, "search": phone})
            data = res.json()
            if data.get("success") and data.get("users"):
                return data["users"][0]
    except Exception as e:
        print(f"User check error: {e}")
    return None


def book_demo(name: str, phone: str, selected_date: str, seminar_time: str) -> dict:
    try:
        with httpx.Client(timeout=15) as client:
            payload = {"name": name, "phone": phone, "seminarTime": seminar_time, "selectedDate": selected_date}
            print(f"📅 Booking: {payload}")
            res = client.post(f"{LIMBU_API}/bookDemo", json=payload, headers={"Content-Type": "application/json"})
            print(f"📅 Response: {res.status_code} - {res.text}")
            return {"success": res.status_code in [200, 201]}
    except Exception as e:
        print(f"Booking error: {e}")
        return {"success": False}


def parse_user_context(user_data: dict) -> str:
    sub = user_data.get("subscription", {})
    status = sub.get("status", "unknown")
    created = user_data.get("createdAt", "")[:10] if user_data.get("createdAt") else ""
    ctx = f"""USER_DATA:
- Status: {status}
- Joined: {created}
- {'Plan active hai' if status == 'active' else 'Plan inactive — encourage karo plan lene ke liye'}"""
    return ctx


def detect_intent(state: dict) -> dict:
    msg = state.get("message", "").lower()
    if any(w in msg for w in ["bye", "thanks", "thank you", "shukriya"]):
        intent = "farewell"
    else:
        intent = "general"
    return {**state, "intent": intent}


def handle_general(state: dict) -> dict:
    user_id = state["user_id"]
    message = state["message"]
    reply = chatbot_response(user_id, message)

    # BOOK_DEMO trigger
    if "##BOOK_DEMO##" in reply:
        match = re.search(r'##BOOK_DEMO##(\{.*?\})', reply, re.DOTALL)
        if match:
            try:
                booking_data = json.loads(match.group(1))
                return {**state, "intent": "book_demo", "booking_data": booking_data}
            except:
                return {**state, "response": "Ek second, date aur time thoda clearly batao? 😊", "intent": "general"}

    # CHECK_PHONE trigger
    if "##CHECK_PHONE##" in reply:
        match = re.search(r'##CHECK_PHONE##(\{.*?\})', reply, re.DOTALL)
        if match:
            try:
                check_data = json.loads(match.group(1))
                phone = check_data.get("phone", "")
                user_data = check_user(phone)
                if user_data:
                    ctx = parse_user_context(user_data)
                    follow_up = chatbot_response(user_id, f"[SYSTEM: Phone {phone} ka user mila. {ctx}]", extra_context=ctx)
                else:
                    follow_up = chatbot_response(user_id, f"[SYSTEM: Phone {phone} naya user hai. Booking continue karo.]")
                return {**state, "response": follow_up, "intent": "general"}
            except Exception as e:
                print(f"Check phone error: {e}")

    return {**state, "response": reply, "intent": "general"}


def handle_book_demo(state: dict) -> dict:
    booking = state.get("booking_data", {})
    result = book_demo(
        name=booking.get("name", ""),
        phone=booking.get("phone", ""),
        selected_date=booking.get("selectedDate", ""),
        seminar_time=booking.get("seminarTime", "")
    )
    clear_booking_state(state["user_id"])

    if result.get("success"):
        reply = (
            f"Ho gaya! ✅ {booking.get('name')} ji, demo book ho gaya!\n\n"
            f"📅 {booking.get('selectedDate')} ko {booking.get('seminarTime')} baje\n"
            f"📞 {booking.get('phone')} par call aayega\n\n"
            f"Koi sawaal ho toh batao! 😊"
        )
    else:
        reply = "Thodi problem aayi. 😕 Seedha call karo: 📞 9283344726"

    return {**state, "response": reply, "intent": "book_demo"}


def handle_farewell(state: dict) -> dict:
    return {**state, "response": "Shukriya! 🙏 Zaroorat ho toh hum hain. Take care! 😊", "intent": "farewell"}


def route(state: dict) -> str:
    return state.get("intent", "general")


def route_after_general(state: dict) -> str:
    return state.get("intent", "general")


graph = StateGraph(dict)
graph.add_node("detect", detect_intent)
graph.add_node("general", handle_general)
graph.add_node("book_demo", handle_book_demo)
graph.add_node("farewell", handle_farewell)

graph.set_entry_point("detect")
graph.add_conditional_edges("detect", route, {"general": "general", "farewell": "farewell"})
graph.add_conditional_edges("general", route_after_general, {"general": END, "book_demo": "book_demo"})
graph.add_edge("book_demo", END)
graph.add_edge("farewell", END)

app_graph = graph.compile()