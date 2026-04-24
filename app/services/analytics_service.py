import json
import redis
from datetime import datetime
from app.core.config import REDIS_URL

r = redis.from_url(REDIS_URL)


def track_event(user_id: str, event: str, data: dict = {}):
    """Track user activity event"""
    try:
        event_data = {
            "user_id": user_id,
            "event": event,
            "data": data,
            "time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        }
        # Save to user events list
        key = f"events:{user_id}"
        events = []
        existing = r.get(key)
        if existing:
            events = json.loads(existing)
        events.append(event_data)
        r.set(key, json.dumps(events), ex=2592000)  # 30 days

        # Global counters
        r.incr(f"counter:{event}")
        r.incr(f"counter:total_events")

        # Daily stats
        today = datetime.utcnow().strftime("%Y-%m-%d")
        r.incr(f"daily:{today}:{event}")

        print(f"[Analytics] {user_id} → {event}")
    except Exception as e:
        print(f"[Analytics] Error: {e}")


def get_stats() -> dict:
    """Get overall stats"""
    try:
        events = [
            "business_searched", "business_confirmed", "analysis_done",
            "business_connected", "feature_health_score", "feature_insights",
            "feature_magic_qr", "feature_review_reply", "feature_keyword_planner",
            "plan_viewed", "payment_done", "demo_booked", "whatsapp_message"
        ]
        stats = {}
        for event in events:
            val = r.get(f"counter:{event}")
            stats[event] = int(val) if val else 0

        # Today stats
        today = datetime.utcnow().strftime("%Y-%m-%d")
        stats["today"] = {}
        for event in events:
            val = r.get(f"daily:{today}:{event}")
            stats["today"][event] = int(val) if val else 0

        return stats
    except Exception as e:
        print(f"[Analytics] Stats error: {e}")
        return {}


def get_user_events(user_id: str) -> list:
    """Get all events for a user"""
    try:
        data = r.get(f"events:{user_id}")
        return json.loads(data) if data else []
    except:
        return []


def get_payments() -> list:
    """Get all payment records"""
    try:
        data = r.get("all_payments")
        return json.loads(data) if data else []
    except:
        return []


def save_payment(user_id: str, payment_data: dict):
    """Save payment record"""
    try:
        payments = get_payments()
        payments.insert(0, {
            "user_id": user_id,
            "time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            **payment_data
        })
        payments = payments[:500]  # Keep last 500
        r.set("all_payments", json.dumps(payments))
        track_event(user_id, "payment_done", payment_data)
    except Exception as e:
        print(f"[Analytics] Payment save error: {e}")


def get_connected_businesses() -> list:
    """Get all connected business records"""
    try:
        data = r.get("all_connections")
        return json.loads(data) if data else []
    except:
        return []


def save_connection(user_id: str, connection_data: dict):
    """Save business connection record"""
    try:
        connections = get_connected_businesses()
        connections.insert(0, {
            "user_id": user_id,
            "time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            **connection_data
        })
        connections = connections[:1000]
        r.set("all_connections", json.dumps(connections))
        track_event(user_id, "business_connected", connection_data)
    except Exception as e:
        print(f"[Analytics] Connection save error: {e}")