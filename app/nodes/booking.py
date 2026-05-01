from app.services.limbu_api import book_demo
from app.extractors.date_extractor import is_future_datetime
from app.services.redis_service import clear_session, get_session
from app.core.llm import llm
from app.core.prompts import get_main_prompt
from langchain_core.messages import SystemMessage, HumanMessage


def handle_booking(user_id: str, name: str, phone: str, date: str, time: str) -> str:
    if not is_future_datetime(date, time):
        session = get_session(user_id)
        reply = llm.invoke([
            SystemMessage(content=get_main_prompt(session)),
            HumanMessage(content=(
                "[SYSTEM: Selected date/time is in the past. "
                "Politely inform and ask for a future slot. Reply in user's language.]"
            ))
        ])
        return reply.content.strip()

    success = book_demo(name, phone, date, time)
    session = get_session(user_id)

    if success:
        clear_session(user_id)
        reply = llm.invoke([
            SystemMessage(content=get_main_prompt(session)),
            HumanMessage(content=(
                f"[SYSTEM: Demo booked! Write warm confirmation. "
                f"Keep these details EXACTLY as-is (don't translate):\n\n"
                f"✅ Demo Confirmed!\n\n"
                f"• Name: {name}\n• Date: {date}\n• Time: {time}\n• Phone: {phone}\n\n"
                f"Add warm closing in user's language.]"
            ))
        ])
        return reply.content.strip()
    else:
        reply = llm.invoke([
            SystemMessage(content=get_main_prompt(session)),
            HumanMessage(content=(
                "[SYSTEM: Booking failed due to technical error. "
                "Apologize and ask to call +91 9289344726. Reply in user's language.]"
            ))
        ])
        return reply.content.strip()