import ast
import json
import logging
import uuid
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from app.flow import engine, loader
from app.services.redis_service import (
    clear_history, get_all_users, get_history, get_session, save_session,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
log = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Flow import ke waqt hi validate ho chuka hai — yahan sirf report.
    log.info("Flow loaded: %d screens, start=%s",
             len(loader.FLOW["screens"]), loader.start_screen())
    # RAG/Qdrant hata diya — Priya ka gyaan seedha prompt mein (flows/knowledge.md).

    from app.services.followup_service import start_sweeper
    start_sweeper()
    yield


app = FastAPI(title="Limbu.ai WhatsApp Chatbot", version="6.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Webhook parsing ───────────────────────────────────────────────
def _parse_field(val):
    """Provider kabhi dict bhejta hai, kabhi stringified dict."""
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        for parser in (json.loads, ast.literal_eval):
            try:
                out = parser(val)
                if isinstance(out, dict):
                    return out
            except Exception:
                pass
    return {}


def _normalize_phone(raw: str) -> str:
    from app.services.whatsapp_service import normalize_phone
    return normalize_phone(raw) if raw else ""


def _extract(body: dict) -> tuple:
    """
    Webhook se (user_id, phone, text, button_payload) nikalo.

    Button click par provider bhejta hai:
        message.type = "button"
        message.button_text    = "Confirm Order"   <- label (badal sakta hai)
        message.button_payload = "confirm_order"   <- ID (fix rehta hai)

    PURANA CODE button_text ko preference deta tha aur payload ko sirf fallback
    rakhta tha — isi wajah se graph.py mein "intrested"/"i am intrested" jaisi
    spelling lists banani padi thi. Ab payload hi asli signal hai.
    """
    contact = _parse_field(body.get("contact") or {})
    phone = _normalize_phone(
        contact.get("phone") or contact.get("wa_id") or body.get("phone") or ""
    )

    msg = _parse_field(body.get("message") or {})

    # 1. Template quick-reply: id seedha aata hai (button_payload / button_reply.id)
    payload = str(msg.get("button_payload") or "").strip()
    if not payload:
        interactive = _parse_field(msg.get("interactive") or {})
        for key in ("button_reply", "list_reply"):
            reply = _parse_field(interactive.get(key) or {})
            if reply.get("id"):
                payload = str(reply["id"]).strip()
                break

    text = ""
    if not payload:
        text = str(
            msg.get("content") or msg.get("text") or msg.get("body")
            or body.get("content") or body.get("text") or ""
        ).strip()

    # 2. Interactive button tap: platform id NAHI bhejta, sirf title 'content'
    #    mein aur type='interactive'. Title ko current screen ke buttons se
    #    match karke id nikaalo — warna bot ise free text samajh kar AI chala
    #    deta hai (do message, loop).
    msg_type = str(msg.get("type") or "").strip().lower()
    is_button_tap = msg_type in ("interactive", "button") and bool(text)

    user_id = f"wa_{phone}" if phone else (body.get("user_id") or str(uuid.uuid4()))
    return user_id, phone, text, payload, is_button_tap


# ── Dedup ─────────────────────────────────────────────────────────
def _is_duplicate(wamid: str) -> bool:
    """
    Redis-backed dedup.

    NOTE: purana code ek in-memory set use karta tha, jo 1 se zyada worker par
    kaam hi nahi karta — har worker apna set rakhta aur duplicate nikal jaata.
    SET NX ek atomic operation hai, saare workers ke liye ek sach.
    """
    if not wamid:
        return False
    try:
        from app.services.redis_service import r
        return not r.set(f"wamid:{wamid}", "1", nx=True, ex=3600)
    except Exception as e:
        log.warning("Dedup check fail (message process kar rahe hain): %s", e)
        return False


async def _process(body: dict) -> dict:
    log.info("Webhook in: %s", str(body)[:160])

    wamid = _parse_field(body.get("message") or {}).get("wamid", "")
    if _is_duplicate(wamid):
        log.info("Duplicate wamid, skip")
        return {"status": "duplicate"}

    user_id, phone, text, payload, is_button_tap = _extract(body)
    if not phone:
        return {"error": "phone required"}
    if not text and not payload:
        return {"status": "ignored", "detail": "no text or button"}

    session = get_session(user_id)
    if not session.get("connect_phone"):
        session["connect_phone"] = phone
        save_session(user_id, session)

    # Interactive tap: title -> id (current screen ke buttons se). Platform id
    # nahi bhejta, isliye yahan resolve karna zaroori hai.
    if not payload and is_button_tap:
        current = session.get("flow_screen", "")
        bid = loader.button_by_title(current, text) if current else ""
        if bid:
            payload, text = bid, ""
            log.info("Interactive tap '%s' -> button %s (screen %s)",
                     body.get("message", {}).get("content", ""), bid, current)

    log.info("user=%s button=%r text=%r", user_id, payload, text[:60])

    # engine blocking hai (Redis, HTTP, LLM). Threadpool mein bhejna zaroori —
    # warna ek slow API poore server ke saare users ko rok deti hai.
    await run_in_threadpool(engine.handle, user_id, phone, text, payload)
    return {"status": "ok", "user_id": user_id}


@app.post("/webhook/chat")
@app.post("/webhook/whatsapp")
async def webhook(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    result = await _process(body)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/webhook/action-complete")
async def webhook_action_complete(request: Request):
    """Limbu dashboard se action complete hone par result deliver karo."""
    body = await request.json()
    phone = _normalize_phone(body.get("phone", ""))
    action = body.get("action", "")
    if not phone or not action:
        raise HTTPException(status_code=400, detail="phone and action required")

    if body.get("status") != "success":
        return {"status": "ignored"}

    user_id = f"wa_{phone}"
    if not get_session(user_id):
        log.warning("action-complete: user nahi mila phone=%s", phone[-4:])
        return {"status": "user_not_found"}

    from app.services.actions_service import deliver_from_webhook
    await run_in_threadpool(
        deliver_from_webhook, user_id, phone, action,
        body.get("result", {}), body.get("actionId", ""),
    )
    return {"status": "ok"}


@app.post("/webhook/connected")
async def webhook_connected(request: Request):
    """Limbu se: user ne Google OAuth complete kar liya."""
    body = await request.json()
    phone = _normalize_phone(body.get("phone", ""))
    if not phone:
        raise HTTPException(status_code=400, detail="phone required")

    user_id = f"wa_{phone}"
    session = get_session(user_id)
    if not session:
        return {"status": "user_not_found"}

    if body.get("status") == "failed":
        await run_in_threadpool(engine.handle, user_id, phone, "", "CONNECT_GO")
    else:
        # Seedha verify + auto health report (polling jaisa hi). Button
        # simulation par depend nahi — current screen kuch bhi ho, kaam karega.
        from app.flow.actions import verify_and_start
        await run_in_threadpool(verify_and_start, user_id, phone)
    return {"status": "ok"}


# ── Admin ─────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "version": "6.0.0", "screens": len(loader.FLOW["screens"])}


@app.get("/")
def root():
    return {"message": "Limbu.ai Chatbot API v6"}


@app.get("/api/admin/users")
def admin_users():
    users = get_all_users()
    return {"total": len(users), "users": users}


@app.get("/api/admin/chat/{user_id}")
def admin_chat(user_id: str):
    history = get_history(user_id)
    return {"user_id": user_id, "messages": history, "total": len(history)}


@app.delete("/api/admin/chat/{user_id}")
def admin_clear(user_id: str):
    clear_history(user_id)
    return {"message": f"Cleared for {user_id}"}
