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
                f"[SYSTEM: Selected time is in the past. Respectfully inform user "
                f"and suggest a future date/time. Reply in user's language.]"
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
                f"[SYSTEM: Demo booked successfully. Write a warm confirmation message "
                f"in user's language. IMPORTANT: Keep these details EXACTLY in English as shown:\n\n"
                f"✅ Demo Confirmed!\n\n"
                f"• Name: {name}\n"
                f"• Date: {date}\n"
                f"• Time: {time}\n"
                f"• Phone: {phone}\n\n"
                f"Add a warm closing line in user's language saying our team will call them. "
                f"Do NOT translate the above details — keep them exactly as is.]"
            ))
        ])
        return reply.content.strip()
    else:
        reply = llm.invoke([
            SystemMessage(content=get_main_prompt(session)),
            HumanMessage(content=(
                f"[SYSTEM: Booking failed due to technical error. "
                f"Apologize respectfully and ask to call 9283344726. "
                f"Reply in user's language.]"
            ))
        ])
        return reply.content.strip()