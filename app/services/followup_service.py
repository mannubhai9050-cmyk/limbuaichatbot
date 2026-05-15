"""
Follow-up message service — sends automatic reminders based on conversation state.
Runs as background threads, respects user language.
"""
import threading
import time
from app.services.redis_service import get_session, save_session, save_message
from app.services.whatsapp_service import send_whatsapp

# Track active follow-up timers per user — prevent duplicates
_active_timers: dict = {}
_timers_lock = threading.Lock()


def _cancel_followup(user_id: str):
    """Cancel any pending follow-up for this user"""
    with _timers_lock:
        t = _active_timers.pop(user_id, None)
        if t:
            t.cancel()


def _schedule_followup(user_id: str, phone: str, delay_seconds: int, followup_type: str):
    """Schedule a follow-up message after delay"""
    _cancel_followup(user_id)
    t = threading.Timer(
        delay_seconds,
        _send_followup,
        args=(user_id, phone, followup_type)
    )
    t.daemon = True
    t.start()
    with _timers_lock:
        _active_timers[user_id] = t
    print(f"[Followup] Scheduled {followup_type} for {user_id} in {delay_seconds}s")


def _get_phone(user_id: str, session: dict) -> str:
    phone = session.get("connect_phone", "")
    if not phone and user_id.startswith("wa_"):
        phone = user_id.replace("wa_", "")
        if not phone.startswith("91") and len(phone) == 10:
            phone = "91" + phone
    return phone


def _build_message(followup_type: str, session: dict) -> str:
    lang = session.get("lang", "hi")
    en = (lang == "en")
    biz_name = (
        session.get("active_business_name") or
        session.get("business_name") or
        "aapka business"
    )

    if followup_type == "CONNECT_PENDING":
        phone = session.get("connect_phone", "")
        connect_url = f"https://limbu.ai/connect-google-business?phone={phone}" if phone else "https://limbu.ai/connect-google-business"
        if en:
            return (
                f"Hi! 😊 I noticed you haven't connected your Google Business Profile yet.\n\n"
                f"Having trouble? Here's the link again:\n"
                f"🔗 {connect_url}\n\n"
                f"Just login with Gmail and click Allow. Takes less than 1 minute!\n"
                f"Need help? Call 📞 +91 9289344726"
            )
        return (
            f"Namaste! 😊 Lagta hai aapne abhi tak Google Business Profile connect nahi kiya.\n\n"
            f"Koi problem aa rahi hai? Yeh raha link dobara:\n"
            f"🔗 {connect_url}\n\n"
            f"Bas Gmail se login karein aur Allow click karein. 1 minute se kam lagta hai!\n"
            f"Help chahiye? Call karein 📞 +91 9289344726"
        )

    elif followup_type == "FEATURE_PENDING":
        offered = session.get("features_offered", [])
        all_features = ["health_score", "magic_qr", "insights", "website", "review_reply"]
        remaining = [f for f in all_features if f not in offered]
        feature_names = {
            "health_score": "Full Health Report",
            "magic_qr": "Magic QR Code",
            "insights": "Google Insights",
            "website": "Free Website",
            "review_reply": "AI Review Reply"
        }
        next_feat = feature_names.get(remaining[0], "FREE feature") if remaining else "FREE features"
        if en:
            return (
                f"Hi! 😊 Don't miss your FREE tools for *{biz_name}*!\n\n"
                f"✅ Next up: *{next_feat}*\n\n"
                f"Just reply *Yes* and I'll get it ready for you! 🚀"
            )
        return (
            f"Namaste! 😊 *{biz_name}* ke liye FREE tools baaki hain!\n\n"
            f"✅ Agla: *{next_feat}*\n\n"
            f"Bas *Haan* likho — main abhi ready kar doongi! 🚀"
        )

    elif followup_type == "SOCIAL_MEDIA":
        connected = []
        for p in ["facebook", "instagram", "youtube", "linkedin"]:
            if session.get(f"{p}_verified"):
                connected.append(p.title())
        not_connected = [p.title() for p in ["Facebook", "Instagram", "YouTube", "LinkedIn"] if p.lower() not in [c.lower() for c in connected]]
        next_platform = not_connected[0] if not_connected else None
        if not next_platform:
            return ""
        if en:
            return (
                f"Hi! 😊 *{biz_name}* is doing well on Google!\n\n"
                f"Now let's grow your *{next_platform}* presence too. 📱\n\n"
                f"Connect your {next_platform} page to get:\n"
                f"• Automatic post scheduling\n"
                f"• Customer engagement tools\n"
                f"• Performance insights\n\n"
                f"Reply *{next_platform}* to get the connect link! 🚀"
            )
        return (
            f"Namaste! 😊 *{biz_name}* Google par acha chal raha hai!\n\n"
            f"Ab *{next_platform}* par bhi grow karein. 📱\n\n"
            f"*{next_platform}* connect karne se milega:\n"
            f"• Automatic post scheduling\n"
            f"• Customer engagement\n"
            f"• Performance insights\n\n"
            f"*{next_platform}* likhein — connect link doongi! 🚀"
        )

    elif followup_type == "PLAN_UPSELL":
        if en:
            return (
                f"Hi! 😊 You've tried all FREE features for *{biz_name}*!\n\n"
                f"📊 Your competitors are actively working on their profiles.\n"
                f"Don't fall behind — get a plan to automate everything:\n\n"
                f"• 🥉 Basic ₹2,500/month — GMB posts, Magic QR, citations\n"
                f"• 🥈 Professional ₹5,500/month — + Review management, insights\n"
                f"• 🥇 Premium ₹7,500/month — Full automation\n\n"
                f"Reply *Plan* to know more or call 📞 +91 9289344726"
            )
        return (
            f"Namaste! 😊 *{biz_name}* ke liye saari FREE features try ho gayi!\n\n"
            f"📊 Aapke competitors apni profiles par kaam kar rahe hain.\n"
            f"Peeche mat rahein — plan lo sab automate karne ke liye:\n\n"
            f"• 🥉 Basic ₹2,500/month — GMB posts, Magic QR, citations\n"
            f"• 🥈 Professional ₹5,500/month — + Review management, insights\n"
            f"• 🥇 Premium ₹7,500/month — Full automation\n\n"
            f"*Plan* likhein ya call karein 📞 +91 9289344726"
        )

    return ""


def _send_followup(user_id: str, phone: str, followup_type: str):
    """Actually send the follow-up — max 2 total per user"""
    try:
        session = get_session(user_id)
        if not session:
            return

        # Max 2 follow-ups per user
        followup_count = session.get("followup_count", 0)
        if followup_count >= 2:
            print(f"[Followup] Max 2 reached for {user_id}, stopping")
            return

        # Check if follow-up is still relevant
        if followup_type == "CONNECT_PENDING":
            if session.get("connect_verified"):
                print(f"[Followup] {user_id} already connected, skip")
                return

        elif followup_type == "FEATURE_PENDING":
            if not session.get("connect_verified"):
                return
            all_features = ["health_score", "magic_qr", "insights", "website", "review_reply"]
            offered = session.get("features_offered", [])
            if all(f in offered for f in all_features):
                followup_type = "SOCIAL_MEDIA"

        elif followup_type == "SOCIAL_MEDIA":
            all_social = ["facebook", "instagram", "youtube", "linkedin"]
            if all(session.get(f"{p}_verified") for p in all_social):
                followup_type = "PLAN_UPSELL"

        msg = _build_message(followup_type, session)
        if not msg:
            print(f"[Followup] No message for {followup_type}, skip")
            return

        # Increment count and save
        session["followup_count"] = followup_count + 1
        save_session(user_id, session)

        save_message(user_id, "assistant", msg)
        send_whatsapp(phone, msg)
        print(f"[Followup] Sent {followup_type} to {user_id} (count={followup_count + 1}/2)")

    except Exception as e:
        print(f"[Followup] Error: {e}")
        import traceback; traceback.print_exc()


# ── Public API ────────────────────────────────────────────────────

def on_connect_link_sent(user_id: str, phone: str):
    """Call when connect link is sent — follow-up in 10 min"""
    _schedule_followup(user_id, phone, 600, "CONNECT_PENDING")


def on_connected(user_id: str, phone: str):
    """Call when user connects — cancel connect follow-up, first feature follow-up in 1 hour"""
    _cancel_followup(user_id)
    # Reset followup count on new connection
    from app.services.redis_service import get_session, save_session
    session = get_session(user_id)
    if session:
        session["followup_count"] = 0
        save_session(user_id, session)
    _schedule_followup(user_id, phone, 3600, "FEATURE_PENDING")   # 1 hour


def on_feature_delivered(user_id: str, phone: str, feature: str):
    """After feature delivery — schedule follow-up only if followups remaining < 2"""
    session = get_session(user_id)
    if not session:
        return

    followup_count = session.get("followup_count", 0)
    if followup_count >= 2:
        print(f"[Followup] Max 2 reached for {user_id}, no more")
        return

    all_features = ["health_score", "magic_qr", "insights", "website", "review_reply"]
    offered = session.get("features_offered", [])
    remaining = [f for f in all_features if f not in offered]

    if remaining:
        _schedule_followup(user_id, phone, 600, "FEATURE_PENDING")   # 10 min
    else:
        _schedule_followup(user_id, phone, 3600, "SOCIAL_MEDIA")      # 1 hour


def on_user_message(user_id: str):
    """Call when user sends any message — cancel pending follow-up (they're active)"""
    _cancel_followup(user_id)