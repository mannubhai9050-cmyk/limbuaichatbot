from app.extractors.business_extractor import extract_gmb_score
from app.services.redis_service import save_session, get_session
from app.core.config import LIMBU_CONNECT_URL, LIMBU_API_BASE
import uuid
import threading
import time
import httpx


def handle_analyse(user_id: str, session: dict) -> str:
    place = session.get("found_place")

    if not place:
        return "Pehle aapka business confirm karna hoga. Business naam aur city batayein? 😊"

    if not session.get("confirmed"):
        return "Kya jo business maine dhundha woh aapka hai? Ek baar confirm kar dein. 😊"

    analysis = extract_gmb_score(place)
    session["analysis"] = analysis

    if not session.get("connect_session_id"):
        session["connect_session_id"] = uuid.uuid4().hex[:16]
    connect_session_id = session["connect_session_id"]
    session["connect_link_sent"] = True
    session["connect_verified"] = False
    session["poll_msg_saved"] = False
    session["payment_notified"] = False
    save_session(user_id, session)

    connect_url = f"{LIMBU_CONNECT_URL}?session_id={connect_session_id}"
    name = place.get("displayName", {}).get("text", "Your Business")
    score = analysis["score"]

    if score == 100:
        growth_msg = (
            "🌟 Profile setup is perfect! But growth ke liye automation chahiye.\n"
            "Daily posts + Magic QR se 3-4x zyada customers aa sakte hain.\n"
            "Ek extra booking se poora plan ka cost nikal jaata hai!"
        )
    elif score >= 80:
        growth_msg = "Profile strong hai — automation se growth aur tez ho sakti hai! 💪"
    elif score >= 55:
        growth_msg = "Profile average hai — improvements se business significantly grow kar sakta hai."
    else:
        growth_msg = "Profile mein gaps hain jo customers ko rok rahi hain."

    issues_text = "\n".join([f"  • {i}" for i in analysis["issues"]]) if analysis["issues"] else "  • No major issues!"
    strengths_text = "\n".join([f"  • {s}" for s in analysis["strengths"]]) if analysis["strengths"] else "  • Keep building"

    report = (
        f"**Google Business Profile — {name}**\n\n"
        f"📊 Score: **{score}/100** — {analysis['grade']} {analysis['color']}\n\n"
        f"{growth_msg}\n\n"
        f"**Needs Improvement:**\n{issues_text}\n\n"
        f"**Working Well:**\n{strengths_text}\n\n"
        f"**Limbu.ai se kya milega:**\n"
        f"  • Daily AI posts → 'near me' ranking improve\n"
        f"  • Magic QR → automatic reviews\n"
        f"  • AI review replies → customer trust\n"
        f"  • Social media automation → wider reach\n\n"
        f"💡 **Best Plan:** {analysis['plan']}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 **Apna business Limbu.ai se connect karein:**\n"
        f"{connect_url}\n\n"
        f"Connect karo — main automatically verify kar doongi aur plan activate kar doongi! 😊"
    )

    # Start connection polling (fast)
    _poll_connection(user_id, connect_session_id)
    # Start payment polling (runs for 30 min)
    _poll_payment(user_id, connect_session_id)

    return report


def _call_api(session_id: str) -> dict:
    """Hit the API once"""
    try:
        res = httpx.get(
            f"{LIMBU_API_BASE}/gmb/status",
            params={"session_id": session_id},
            timeout=10
        )
        return res.json()
    except Exception as e:
        print(f"[API] Error: {e}")
        return {}


def _send_payment_msg(user_id: str, data: dict, sess: dict):
    """Send payment confirmation message"""
    from app.services.redis_service import save_message as _save
    p = data.get("payment", {})
    if isinstance(p, list):
        p = p[0] if p else {}

    plan_title = p.get("planTitle", "Plan")
    amount = p.get("amount", "")
    pay_email = p.get("email") or data.get("email", "")
    paid_at = p.get("paidAt", "")[:10] if p.get("paidAt") else ""
    payment_id = p.get("paymentId", "")

    pay_msg = (
        f"🎉 **Payment successful! Bahut badhaai ho!**\n\n"
        f"✅ **{plan_title}** active ho gaya!\n\n"
        f"**Payment Details:**\n"
        f"  💳 Amount: {amount}\n"
        f"  📧 Email: {pay_email}\n"
        f"  📅 Date: {paid_at}\n"
        f"  🔑 Payment ID: {payment_id}\n\n"
        f"Hamari team aapke GMB profile par kaam shuru kar degi.\n"
        f"Invoice aapki email par bhej diya jayega. 🙏\n\n"
        f"Koi bhi sawaal ho: 📞 9283344726 | 📧 info@limbu.ai"
    )
    sess["payment_notified"] = True
    save_session(user_id, sess)
    _save(user_id, "assistant", pay_msg)
    print(f"[Poll] ✅ Payment notified! {user_id} — {plan_title}")


def _poll_connection(user_id: str, session_id: str):
    """Poll every 3 sec for connection — stops after connected (max 5 min)"""
    def run():
        for attempt in range(100):
            time.sleep(3)
            try:
                sess = get_session(user_id)
                if sess.get("connect_session_id") != session_id:
                    break
                if sess.get("poll_msg_saved"):
                    break

                data = _call_api(session_id)
                api_status = data.get("status", "")
                connected = data.get("businessConnected", False)
                print(f"[ConnPoll] {user_id} attempt {attempt+1}: status={api_status} connected={connected}")

                if (api_status == "success" or connected) and not sess.get("poll_msg_saved"):
                    from app.nodes.connect import handle_check_latest_connection
                    from app.services.redis_service import save_message as _save
                    email = data.get("email", "")
                    if email:
                        sess["connected_email"] = email
                    sess["connect_verified"] = True
                    sess["poll_msg_saved"] = True
                    save_session(user_id, sess)
                    reply = handle_check_latest_connection(user_id, sess)
                    _save(user_id, "assistant", reply)
                    print(f"[ConnPoll] ✅ Connected! {user_id} email:{email}")
                    # Send via WhatsApp if user came from WhatsApp
                    if user_id.startswith("wa_"):
                        try:
                            from app.services.whatsapp_service import send_whatsapp
                            phone = user_id.replace("wa_", "")
                            send_whatsapp(phone, reply)
                        except Exception as wa_e:
                            print(f"[WA] Send error: {wa_e}")
                    break

            except Exception as e:
                print(f"[ConnPoll] Error: {e}")
                time.sleep(5)

    threading.Thread(target=run, daemon=True).start()
    print(f"[ConnPoll] Started for {user_id}")


def _poll_payment(user_id: str, session_id: str):
    """Poll every 5 sec for payment — runs for 30 min"""
    def run():
        for attempt in range(360):  # 30 min (360 x 5sec)
            time.sleep(5)
            try:
                sess = get_session(user_id)
                if sess.get("connect_session_id") != session_id:
                    break
                if sess.get("payment_notified"):
                    break

                data = _call_api(session_id)
                pay_status = data.get("paymentStatus", "none")
                pay_obj = data.get("payment")

                print(f"[PayPoll] {user_id} attempt {attempt+1}: paymentStatus={pay_status} | payment={bool(pay_obj)}")

                # Payment detected
                if pay_status == "paid" or (pay_obj and isinstance(pay_obj, dict)):
                    sess = get_session(user_id)  # Reload fresh
                    if not sess.get("payment_notified"):
                        _send_payment_msg(user_id, data, sess)
                    # Send via WhatsApp if user came from WhatsApp
                    if user_id.startswith("wa_"):
                        try:
                            from app.services.whatsapp_service import send_whatsapp
                            phone = user_id.replace("wa_", "")
                            pay_sess = get_session(user_id)
                            # Get last assistant message
                            from app.services.redis_service import get_history
                            hist = get_history(user_id)
                            if hist:
                                last_msg = hist[-1].get("content", "")
                                send_whatsapp(phone, last_msg)
                        except Exception as wa_e:
                            print(f"[WA] Payment send error: {wa_e}")
                    break

            except Exception as e:
                print(f"[PayPoll] Error: {e}")
                time.sleep(10)

    threading.Thread(target=run, daemon=True).start()
    print(f"[PayPoll] Started for {user_id}")