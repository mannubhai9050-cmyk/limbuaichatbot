"""
Priya — hybrid expert brain. SIRF tab chalta hai jab user button na dabakar
apna text likhe.

Button click -> flow engine (deterministic). Free text -> yeh:

  1. INTENT: agar user flow ka koi kaam chahta hai (subscription plans dekhna,
     apna business connect/analyze karna, human/support, restart) to us SCREEN
     par bhej deta hai — [GOTO:X].
  2. EXPERT ANSWER: warna ek expert ki tarah jawab deta hai — poora gyaan
     (flows/knowledge.md + current plans) prompt mein hi hai, KOI RAG/Qdrant nahi.

Pehle RAG (Qdrant embeddings) use hota tha jo confuse karta tha aur galat/purani
baat bol deta tha. Ab saara gyaan seedha prompt mein — expert, consistent, fast.
"""
import logging
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.config import SUPPORT_EMAIL, SUPPORT_PHONE
from app.core.llm import llm

log = logging.getLogger(__name__)

# GOTO token -> flow screen
_GOTO_SCREEN = {
    "PLANS": "PLANS",
    "BUSINESS": "ASK_BUSINESS",
    "SUPPORT": "SUPPORT",
    "DEMO": "DEMO_ASK_NAME",
    "RESTART": "WELCOME",
}

_KNOWLEDGE_CACHE = None


def _knowledge_file() -> str:
    global _KNOWLEDGE_CACHE
    if _KNOWLEDGE_CACHE is None:
        try:
            p = Path(__file__).resolve().parents[2] / "flows" / "knowledge.md"
            _KNOWLEDGE_CACHE = p.read_text(encoding="utf-8") if p.exists() else ""
        except Exception as e:
            log.warning("knowledge.md load fail: %s", e)
            _KNOWLEDGE_CACHE = ""
    return _KNOWLEDGE_CACHE


def _current_plans() -> str:
    """Subscription plans ki current sahi prices (plans_service se)."""
    try:
        from app.services.plans_service import get_plan_by_name

        lines = []
        for key in ("basic plan", "professional plan", "premium plan"):
            p = get_plan_by_name(key)
            if p:
                lines.append(
                    f"- {p['title']}: ₹{p['basePrice']}/month + 18% GST "
                    f"(total ₹{p['totalAmount']}), {p['posts']} GMB posts, "
                    f"{p['citations']} citations"
                )
        if lines:
            return "SUBSCRIPTION PLANS (authoritative current prices):\n" + "\n".join(lines)
    except Exception as e:
        log.warning("Plans load for AI fail: %s", e)
    return ""


_SYSTEM = """You are Priya — a warm, sharp, expert female sales agent for Limbu.ai (AI-powered Google Business Profile growth for local businesses).

The user is chatting on WhatsApp. There is a BUTTON menu, but they typed a free message. First decide if their intent maps to a flow action; otherwise answer as an expert.

ROUTE (reply with ONLY the tag, nothing else) when the user clearly wants to:
• See the monthly SUBSCRIPTION plans (Basic/Professional/Premium) or buy them -> [GOTO:PLANS]
• Add / connect / analyze THEIR OWN business, get their health report, GMB -> [GOTO:BUSINESS]
• Talk to a human / agent / support / call back -> [GOTO:SUPPORT]
• Book a demo / schedule a call / want a demo -> [GOTO:DEMO]
• Restart / go to main menu / start fresh -> [GOTO:RESTART]

Otherwise, ANSWER as an expert using ONLY the knowledge below:
- Questions about other services (website, SEO, ads setup, GMB one-time, WhatsApp automation), franchise, features, comparison, "how does it work", objections, etc.
- Keep it SHORT: 2-4 lines, crisp, confident, like an expert who knows the product cold.
- Same language/script the user wrote (Hindi/Hinglish -> female verbs: karungi, bataungi, dikhaungi).
- Give concrete facts/prices from the knowledge. NEVER invent prices or features.
- If something isn't in the knowledge, say you'll check and give {phone}.
- End naturally; do NOT tell them to type — the menu buttons reappear after your reply.
- Be persuasive but not pushy. If relevant, gently nudge toward the FREE health report or the right plan.

Decide intent by MEANING, not keywords. Don't confuse a general question with a flow action.

═══════════ KNOWLEDGE ═══════════
{plans}

{knowledge}

Support: {phone} / {email}
═════════════════════════════════"""


def respond(user_id: str, question: str, session: dict) -> tuple:
    """
    Returns ('goto', screen_name)  ya  ('text', answer).
    """
    from app.services.redis_service import get_history

    system = _SYSTEM.format(
        plans=_current_plans(),
        knowledge=_knowledge_file(),
        phone=SUPPORT_PHONE,
        email=SUPPORT_EMAIL,
    )
    messages = [SystemMessage(content=system)]

    try:
        for m in get_history(user_id)[-4:]:
            role, content = m.get("role"), m.get("content", "")
            if not content:
                continue
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(SystemMessage(content=f"[You said: {content[:120]}]"))
    except Exception as e:
        log.warning("History load fail: %s", e)

    messages.append(HumanMessage(content=question))

    try:
        reply = llm.invoke(messages).content.strip()
    except Exception as e:
        log.exception("LLM fail: %s", e)
        return "text", _error_text(session)

    if reply.startswith("[GOTO:"):
        key = reply[6:].split("]")[0].strip().upper()
        screen = _GOTO_SCREEN.get(key)
        if screen:
            log.info("Intent '%s' -> screen %s", question[:40], screen)
            return "goto", screen
        return "goto", "WELCOME"

    return "text", reply


def _error_text(session: dict) -> str:
    from app.flow import loader
    lang = session.get("lang", "en")
    return loader.text("error_generic")[lang].replace("{{support_phone}}", SUPPORT_PHONE)


# Backward-compat
def answer(user_id: str, question: str, session: dict) -> str:
    kind, val = respond(user_id, question, session)
    return val if kind == "text" else ""


# ── Business lookup brain ─────────────────────────────────────────
_BIZ_SYSTEM = """You gate a business-lookup step. The user was asked to identify THEIR OWN business by sending either:
  • a Google Business Profile / Google Maps LINK, or
  • their BUSINESS NAME + CITY.

Use the conversation so far (it may show a business we already displayed). Output EXACTLY ONE tag (nothing else):

[LINK]                      -> they refer to a link but did NOT paste a real URL
                               (e.g. "google business profile link", "i'll send link", "link", "gbp link")
[SEARCH] <business + city>  -> the message is an ACTUAL business name (optionally with city),
                               OR they want the SAME business in a DIFFERENT city/branch than the one shown.
                               Put a clean "Business Name City" query after the tag (combine with the
                               business name from the conversation if they only gave a new city).
[RETRY]                     -> they say the shown result is WRONG / are frustrated / rejecting
                               (e.g. "nahi yrr kuch bhi de diya", "kya de rahe ho", "ye nahi hai", "galat business")
[MORE]                      -> too vague to identify a business (generic keyword, greeting, unclear)
[PLANS]                     -> they ask about pricing / plans / cost
[DEMO]                      -> they want to book a demo / schedule a call / "book demo for me"
[SUPPORT]                   -> they want a human / support / to talk

HARD RULES:
- A phrase that NAMES the option ("google business profile link", "business name", "profile link") is NOT a business name -> [LINK] or [MORE], never [SEARCH].
- Only use [SEARCH] when it is clearly a real business name. When unsure, use [MORE] or [RETRY]. NEVER guess a business.
- Frustration or "this is wrong" in ANY language -> [RETRY]."""


def business_intent(user_id: str, text: str, session: dict) -> tuple:
    """
    Business-lookup input ko AI se samjho. Returns (action, value):
      ('search', 'Name City') | ('link', '') | ('retry', '') |
      ('more', '') | ('goto', 'PLANS'|'SUPPORT')

    Isi se hallucination/random-search rukta hai — search tabhi jab AI kahe.
    History ke saath, taaki "doosri city" (refinement) bhi samjhe.
    """
    from app.services.redis_service import get_history

    messages = [SystemMessage(content=_BIZ_SYSTEM)]
    try:
        for m in get_history(user_id)[-4:]:
            content = m.get("content", "")
            if not content:
                continue
            if m.get("role") == "user":
                messages.append(HumanMessage(content=content))
            else:
                messages.append(SystemMessage(content=f"[Bot showed/said: {content[:150]}]"))
    except Exception:
        pass
    messages.append(HumanMessage(content=text))

    try:
        reply = llm.invoke(messages).content.strip()
    except Exception as e:
        log.warning("business_intent LLM fail: %s", e)
        return "more", ""   # fail-safe: naam+city/link maango, guess mat karo

    up = reply.upper()
    if up.startswith("[SEARCH]"):
        q = reply.split("]", 1)[1].strip()
        return ("search", q) if len(q) >= 3 else ("more", "")
    if up.startswith("[LINK]"):
        return "link", ""
    if up.startswith("[RETRY]"):
        return "retry", ""
    if up.startswith("[PLANS]"):
        return "goto", "PLANS"
    if up.startswith("[DEMO]"):
        return "goto", "DEMO_ASK_NAME"
    if up.startswith("[SUPPORT]"):
        return "goto", "SUPPORT"
    return "more", ""
