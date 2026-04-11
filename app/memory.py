import os
import json
import redis
from datetime import datetime

r = redis.from_url(os.getenv("REDIS_URL"))
MAX_HISTORY = 20  # Zyada history rakhenge


def save_chat(user_id: str, role: str, content: str):
    """Save message to Redis"""
    key = f"chat:{user_id}"
    history = get_chat(user_id)
    history.append({
        "role": role,
        "content": content,
        "time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    })
    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]
    r.set(key, json.dumps(history), ex=604800)  # 7 din

    # User ko global list mein track karo
    r.sadd("all_users", user_id)
    # Last activity update karo
    r.set(f"last_active:{user_id}", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), ex=604800)


def get_chat(user_id: str) -> list:
    """Get chat history from Redis"""
    try:
        data = r.get(f"chat:{user_id}")
        return json.loads(data) if data else []
    except Exception:
        return []


def get_all_users() -> list:
    """Saare users ki list"""
    try:
        users = r.smembers("all_users")
        result = []
        for uid in users:
            uid = uid.decode() if isinstance(uid, bytes) else uid
            history = get_chat(uid)
            last_active = r.get(f"last_active:{uid}")
            last_active = last_active.decode() if last_active else "Unknown"
            result.append({
                "user_id": uid,
                "message_count": len(history),
                "last_active": last_active,
                "last_message": history[-1]["content"][:50] + "..." if history else ""
            })
        # Last active se sort karo
        result.sort(key=lambda x: x["last_active"], reverse=True)
        return result
    except Exception as e:
        print(f"Get all users error: {e}")
        return []


def clear_chat(user_id: str):
    r.delete(f"chat:{user_id}")


# Booking state
def get_booking_state(user_id: str) -> dict:
    try:
        data = r.get(f"booking:{user_id}")
        return json.loads(data) if data else {}
    except Exception:
        return {}


def save_booking_state(user_id: str, state: dict):
    r.set(f"booking:{user_id}", json.dumps(state), ex=3600)


def clear_booking_state(user_id: str):
    r.delete(f"booking:{user_id}")