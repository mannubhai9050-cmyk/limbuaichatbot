import redis
import json
from datetime import datetime

from redis.backoff import ExponentialBackoff
from redis.exceptions import ConnectionError as RedisConnectionError, TimeoutError as RedisTimeoutError
from redis.retry import Retry

from app.core.config import REDIS_URL, MAX_CHAT_HISTORY, SESSION_TTL, CHAT_TTL

# Cloud Redis idle connections band kar deta hai. Bina resilience config ke,
# agla command "Connection closed by server" se crash ho jaata tha — jaise
# SEARCH_BUSINESS jo business MIL jaane ke baad save_session par gir gaya aur
# user ko galat "not found" dikha diya.
#
#   • health_check_interval — har 30s ping, taaki dead connection pehle pakdi jaaye
#   • socket_keepalive      — TCP keepalive
#   • retry + retry_on_error — ConnectionError/TimeoutError par khud reconnect+retry
r = redis.from_url(
    REDIS_URL,
    decode_responses=True,
    socket_timeout=5,
    socket_connect_timeout=5,
    socket_keepalive=True,
    health_check_interval=30,
    retry=Retry(ExponentialBackoff(cap=2, base=0.1), retries=3),
    retry_on_error=[RedisConnectionError, RedisTimeoutError],
)


# ── Chat History ──────────────────────────────────────────────────

def save_message(user_id: str, role: str, content: str):
    """Save message with deduplication — prevents double messages"""
    key = f"chat:{user_id}"
    history = get_history(user_id)

    # Deduplication: skip if last assistant message is identical
    if role == "assistant" and history:
        last = history[-1]
        if last["role"] == "assistant" and last["content"].strip() == content.strip():
            print(f"[Redis] Duplicate message skipped for {user_id}")
            return

    history.append({
        "role": role,
        "content": content,
        "time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    })

    if len(history) > MAX_CHAT_HISTORY:
        history = history[-MAX_CHAT_HISTORY:]

    r.set(key, json.dumps(history), ex=CHAT_TTL)
    r.set(f"last_active:{user_id}", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), ex=CHAT_TTL)


def get_history(user_id: str) -> list:
    try:
        data = r.get(f"chat:{user_id}")
        return json.loads(data) if data else []
    except Exception:
        return []


def clear_history(user_id: str):
    r.delete(f"chat:{user_id}")
    r.delete(f"session:{user_id}")
    r.delete(f"last_active:{user_id}")


# ── Session State ─────────────────────────────────────────────────

def save_session(user_id: str, session: dict):
    r.set(f"session:{user_id}", json.dumps(session), ex=SESSION_TTL)


def get_session(user_id: str) -> dict:
    try:
        data = r.get(f"session:{user_id}")
        return json.loads(data) if data else {}
    except Exception:
        return {}


def clear_session(user_id: str):
    r.delete(f"session:{user_id}")


# ── Admin ─────────────────────────────────────────────────────────

def get_all_users() -> list:
    try:
        chat_keys = r.keys("chat:*")
        result = []
        for key in chat_keys:
            uid = key.replace("chat:", "")
            history = get_history(uid)
            last_active = r.get(f"last_active:{uid}") or "Unknown"
            if history:
                result.append({
                    "user_id": uid,
                    "message_count": len(history),
                    "last_active": last_active,
                    "last_message": history[-1]["content"][:60] + "..." if history else ""
                })
        result.sort(key=lambda x: x["last_active"], reverse=True)
        return result
    except Exception as e:
        print(f"[Redis] Get all users error: {e}")
        return []