from app.core.llm import llm
from app.core.prompts import get_main_prompt
from app.services.redis_service import get_history, get_session
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage


def detect_and_respond(user_id: str, message: str) -> str:
    """Main Claude response — returns raw reply (may contain action tags)"""
    session = get_session(user_id)
    history = get_history(user_id)

    system_prompt = get_main_prompt(session)
    messages = [SystemMessage(content=system_prompt)]

    # Last 10 messages for context (skip current — it's in state)
    recent = history[-10:] if len(history) > 10 else history
    for msg in recent[:-1]:
        if msg["role"] == "user":
            messages.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "assistant":
            messages.append(AIMessage(content=msg["content"]))

    messages.append(HumanMessage(content=message))

    response = llm.invoke(messages)
    return response.content.strip()