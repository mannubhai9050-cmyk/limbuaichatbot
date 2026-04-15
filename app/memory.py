"""
Backward compatibility wrapper.
All memory operations now handled by app.services.redis_service
"""
from app.services.redis_service import (
    save_message as save_chat,
    get_history as get_chat,
    save_session,
    get_session,
    clear_session,
    clear_history as clear_chat,
    get_all_users
)

# Aliases for backward compatibility
def get_booking_state(user_id: str) -> dict:
    return get_session(user_id).get("booking", {})

def save_booking_state(user_id: str, state: dict):
    session = get_session(user_id)
    session["booking"] = state
    save_session(user_id, session)

def clear_booking_state(user_id: str):
    session = get_session(user_id)
    session.pop("booking", None)
    save_session(user_id, session)