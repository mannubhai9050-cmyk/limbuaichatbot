from app.core.llm import llm
from app.core.prompts import get_main_prompt
from app.services.redis_service import get_history, get_session
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

FIRST_MSG_HI = (
    "Namaste! 🙏\n\n"
    "Main Priya hoon, Limbu.ai se. Main aapki Google Business Profile "
    "strong banane mein help karti hoon.\n\n"
    "Apna *business naam* aur *city* batayein, main abhi check karti hoon! 😊"
)

FIRST_MSG_EN = (
    "Hello! 🙏\n\n"
    "I'm Priya from Limbu.ai. I help businesses grow on Google.\n\n"
    "Please share your *business name* and *city* — I'll check it right away! 😊"
)


def detect_and_respond(user_id: str, message: str) -> str:
    session = get_session(user_id)
    history = get_history(user_id)
    lang = session.get("lang", "hi")

    # RAG: fetch relevant knowledge for this message
    rag_context = ""
    try:
        from app.services.knowledge_base import get_rag_context
        rag_context = get_rag_context(message, top_k=3)
    except Exception:
        pass

    system_prompt = get_main_prompt(session, rag_context=rag_context)
    messages = [SystemMessage(content=system_prompt)]

    # Smart history — compressed for long conversations
    try:
        from app.services.conversation_memory import get_smart_history
        smart_hist = get_smart_history(user_id, max_messages=12)
        recent = smart_hist
    except Exception:
        recent = history[-12:] if len(history) > 12 else history
    for msg in recent[:-1]:
        if msg["role"] == "user":
            messages.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "assistant":
            messages.append(AIMessage(content=msg["content"]))

    messages.append(HumanMessage(content=message))

    response = llm.invoke(messages)
    reply = response.content.strip()
    # Return as-is — graph.py handles action tag detection and cleaning
    return reply