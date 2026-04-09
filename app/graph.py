from langgraph.graph import StateGraph, END
from app.chatbot import chatbot_response
import httpx
import json
import re


LIMBU_API = "http://limbu.ai/api"


async def check_user_exists(phone: str) -> bool:
    """Check karo ki user already registered hai ya nahi"""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(
                f"{LIMBU_API}/users",
                params={"search": phone}
            )
            data = res.json()
            # Agar user mila toh True
            return bool(data) and len(data) > 0
    except Exception as e:
        print(f"User check error: {e}")
        return False


async def book_demo_api(name: str, phone: str, date: str, time: str) -> dict:
    """Limbu.ai API se demo book karo"""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.post(
                f"{LIMBU_API}/bookDemo",
                json={
                    "name": name,
                    "phone": phone,
                    "seminarTime": time,
                    "selectedDate": date
                }
            )
            
            return {"success": res.status_code in [200, 201], "data": res.json()}
    except Exception as e:
        print(f"Booking API error: {e}")
        return {"success": False, "error": str(e)}


def detect_intent(state: dict) -> dict:
    msg = state.get("message", "").lower()

    if any(w in msg for w in ["complaint", "problem", "issue", "not working", "kaam nahi", "shikayat"]):
        intent = "complaint"
    elif any(w in msg for w in ["bye", "thanks", "thank you", "shukriya"]):
        intent = "farewell"
    else:
        intent = "general"  # Sab general mein — chatbot khud handle karega

    return {
        "intent": intent,
        "user_id": state.get("user_id"),
        "message": state.get("message")
    }


def handle_general(state: dict) -> dict:
    reply = chatbot_response(state["user_id"], state["message"])

    # Check karo BOOK_DEMO trigger hai kya
    if reply.startswith("BOOK_DEMO:"):
        try:
            json_str = reply.replace("BOOK_DEMO:", "").strip()
            booking_data = json.loads(json_str)
            return {
                "response": None,
                "intent": "book_demo",
                "booking_data": booking_data,
                "user_id": state["user_id"]
            }
        except Exception as e:
            print(f"Booking parse error: {e}")
            return {"response": "Ek second, booking mein thodi problem aayi. Naam, number, date aur time dobara batao?", "intent": "general"}

    # CHECK_USER trigger
    if reply.startswith("CHECK_USER:"):
        try:
            json_str = reply.replace("CHECK_USER:", "").strip()
            check_data = json.loads(json_str)
            return {
                "response": None,
                "intent": "check_user",
                "check_phone": check_data.get("phone"),
                "user_id": state["user_id"],
                "message": state["message"]
            }
        except Exception:
            pass

    return {"response": reply, "intent": "general"}


def handle_book_demo(state: dict) -> dict:
    """Limbu.ai API se booking karo"""
    import asyncio
    booking = state.get("booking_data", {})

    result = asyncio.run(book_demo_api(
        name=booking.get("name", ""),
        phone=booking.get("phone", ""),
        date=booking.get("selectedDate", ""),
        time=booking.get("seminarTime", "")
    ))

    if result.get("success"):
        reply = (
            f"✅ Done! {booking.get('name')} ji, aapka demo book ho gaya!\n\n"
            f"📅 Date: {booking.get('selectedDate')}\n"
            f"⏰ Time: {booking.get('seminarTime')}\n"
            f"📞 Hamar team {booking.get('phone')} par call karega.\n\n"
            f"Koi aur sawaal ho toh batao! 😊"
        )
    else:
        reply = (
            "Thodi si problem aayi booking mein. 😕\n"
            "Seedha call karein: 📞 9283344726\n"
            "Ya email: info@limbu.ai"
        )

    return {"response": reply, "intent": "book_demo"}


def handle_check_user(state: dict) -> dict:
    """User exist check karo phir conversation continue karo"""
    import asyncio
    phone = state.get("check_phone", "")
    exists = asyncio.run(check_user_exists(phone))

    # User exist status chatbot ko batao aur continue karo
    status_msg = f"[User {phone} {'already registered hai' if exists else 'new user hai'}]"
    reply = chatbot_response(state["user_id"], f"{state.get('message', '')} {status_msg}")

    return {"response": reply, "intent": "general"}


def handle_complaint(state: dict) -> dict:
    return {
        "response": "Oops, sorry! 😔 Problem ke liye:\n📧 info@limbu.ai\n📞 9283344726\n\nTeam jald madad karegi!",
        "intent": "complaint"
    }


def handle_farewell(state: dict) -> dict:
    return {
        "response": "Shukriya! 🙏 Koi bhi sawaal ho toh hum hain. Take care! 😊",
        "intent": "farewell"
    }


def route(state: dict) -> str:
    return state["intent"]


# Graph build
graph = StateGraph(dict)
graph.add_node("intent", detect_intent)
graph.add_node("general", handle_general)
graph.add_node("book_demo", handle_book_demo)
graph.add_node("check_user", handle_check_user)
graph.add_node("complaint", handle_complaint)
graph.add_node("farewell", handle_farewell)

graph.set_entry_point("intent")
graph.add_conditional_edges("intent", route, {
    "general": "general",
    "complaint": "complaint",
    "farewell": "farewell",
})

# General se booking ya check_user ja sakta hai
graph.add_conditional_edges("general", lambda s: s.get("intent", "general"), {
    "general": END,
    "book_demo": "book_demo",
    "check_user": "check_user",
})

graph.add_edge("book_demo", END)
graph.add_edge("check_user", END)
graph.add_edge("complaint", END)
graph.add_edge("farewell", END)

app_graph = graph.compile()