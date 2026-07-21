"""
AI fallback — SIRF tab chalta hai jab user button na dabakar apna text likhe.

Button click par yeh file bilkul nahi chhui jaati: na LLM call, na embedding,
na RAG. Pehle har message par LLM chalta tha — ab shayad har 10 mein se 1 par.

Yahan AI ka kaam sirf jawab dena hai. Kya karna hai, kahan jaana hai — woh
flow decide karta hai. Isliye action tags, intent guessing, spelling lists —
kuch nahi chahiye.
"""
import logging

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.config import SUPPORT_EMAIL, SUPPORT_PHONE
from app.core.llm import llm
from app.flow import loader

log = logging.getLogger(__name__)

_MAX_HISTORY = 6

_SYSTEM = """You are Priya, a warm and helpful sales agent for Limbu.ai.

Reply in the SAME language/script the user wrote in.
If Hindi/Hinglish, use FEMALE verb forms: karungi, bataungi, bhejungi.

Keep it SHORT — 2-3 lines. Answer only what was asked.

The user is in a button-based menu. After your reply they will see the menu
buttons again, so do NOT ask them to type anything, and do NOT invent
buttons, links or menu options.

{knowledge}

Facts you may state:
- Support: {phone} / {email}

If you don't know something, say so and give the support number.
Never invent prices, plans, or features."""


def _knowledge(question: str) -> str:
    """RAG. Fail ho to AI bina knowledge ke jawab dega — par log mein dikhega."""
    try:
        from app.services.knowledge_base import get_rag_context

        ctx = get_rag_context(question, top_k=2)
        if not ctx:
            return ""
        return (
            "Use ONLY this knowledge base for prices, plans and features.\n"
            "Never guess prices — if it's not written here, say you'll check.\n"
            "─────\n" + ctx + "\n─────"
        )
    except Exception as e:
        # Purana code yahan `except: pass` karta tha — RAG chup-chaap band ho
        # jaata tha aur bot bina knowledge ke price bolne lagta tha.
        log.exception("RAG fail — bina knowledge ke jawab de rahe hain: %s", e)
        return ""


def answer(user_id: str, question: str, session: dict) -> str:
    from app.services.redis_service import get_history

    system = _SYSTEM.format(
        knowledge=_knowledge(question), phone=SUPPORT_PHONE, email=SUPPORT_EMAIL
    )

    messages = [SystemMessage(content=system)]

    try:
        history = get_history(user_id)[-_MAX_HISTORY:]
        for m in history:
            role, content = m.get("role"), m.get("content", "")
            if not content:
                continue
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(SystemMessage(content=f"[You said: {content}]"))
    except Exception as e:
        log.warning("History load fail, bina history ke chal rahe hain: %s", e)

    messages.append(HumanMessage(content=question))

    try:
        return llm.invoke(messages).content.strip()
    except Exception as e:
        log.exception("LLM fail: %s", e)
        lang = session.get("lang", "en")
        return loader.text("error_generic")[lang].replace("{{support_phone}}", SUPPORT_PHONE)
