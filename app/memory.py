import os
import json
import redis

r = redis.from_url(os.getenv("REDIS_URL"))
MAX_HISTORY = 10


def save_chat(user_id: str, role: str, content: str):
    key = f"chat:{user_id}"
    history = get_chat(user_id)
    history.append({"role": role, "content": content})
    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]
    r.set(key, json.dumps(history), ex=86400)


def get_chat(user_id: str) -> list:
    try:
        data = r.get(f"chat:{user_id}")
        return json.loads(data) if data else []
    except Exception:
        return []


def clear_chat(user_id: str):
    r.delete(f"chat:{user_id}")
    r.delete(f"booking:{user_id}")


# ── Booking State ─────────────────────────────────────────────────
def get_booking_state(user_id: str) -> dict:
    """Booking ke liye collected data"""
    try:
        data = r.get(f"booking:{user_id}")
        return json.loads(data) if data else {}
    except Exception:
        return {}


def save_booking_state(user_id: str, state: dict):
    r.set(f"booking:{user_id}", json.dumps(state), ex=3600)  # 1 hour


def clear_booking_state(user_id: str):
    r.delete(f"booking:{user_id}")