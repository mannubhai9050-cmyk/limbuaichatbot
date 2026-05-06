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

    msg_lower = message.lower().strip()

    # ── Fast path: first greeting — word se decide, session se nahi ──
    GREET_EN = {"hi", "hello", "hey", "hlo", "helo", "hii", "hiii", "hy", "helloo", "start"}
    GREET_HI = {"namaste", "namasthe", "namaskar"}

    if len(history) <= 2 and msg_lower in GREET_EN | GREET_HI:
        if msg_lower in GREET_EN:
            return FIRST_MSG_EN
        return FIRST_MSG_HI

    # ── LLM for everything else ───────────────────────────────────
    system_prompt = get_main_prompt(session)
    messages = [SystemMessage(content=system_prompt)]

    recent = history[-10:] if len(history) > 10 else history
    for msg in recent[:-1]:
        if msg["role"] == "user":
            messages.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "assistant":
            messages.append(AIMessage(content=msg["content"]))

    messages.append(HumanMessage(content=message))
    response = llm.invoke(messages)
    return response.content.strip()