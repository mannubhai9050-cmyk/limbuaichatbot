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
        return "Kya jo business maine dhundha woh aapka hai? Confirm kar dein. 😊"

    analysis = extract_gmb_score(place)
    session["analysis"] = analysis

    # Determine connect URL
    is_whatsapp = user_id.startswith("wa_")
    if is_whatsapp:
        phone = user_id.replace("wa_", "")
        connect_url = f"{LIMBU_CONNECT_URL}?phone={phone}"
        poll_key = phone  # poll by phone
    else:
        if not session.get("connect_session_id"):
            session["connect_session_id"] = uuid.uuid4().hex[:16]
        connect_url = f"{LIMBU_CONNECT_URL}?session_id={session['connect_session_id']}"
        poll_key = session["connect_session_id"]

    session["connect_link_sent"] = True
    session["connect_verified"] = False
    session["poll_msg_saved"] = False
    session["payment_notified"] = False
    session["features_offered"] = []
    save_session(user_id, session)

    name = place.get("displayName", {}).get("text", "Your Business")
    score = analysis["score"]

    if score >= 90:
        growth_msg = "Profile almost perfect hai! Par growth ke liye daily automation chahiye. Ek extra customer se poora plan recover ho jaata hai! 💪"
    elif score >= 70:
        growth_msg = "Profile acchi hai — automation se growth aur tez ho sakti hai!"
    elif score >= 50:
        growth_msg = "Profile average hai — improvements se business significantly grow kar sakta hai."
    else:
        growth_msg = "Profile mein gaps hain jo customers ko rok rahi hain."

    issues = "\n".join([f"  • {i}" for i in analysis["issues"]]) if analysis["issues"] else "  • No major issues!"
    strengths = "\n".join([f"  • {s}" for s in analysis["strengths"]]) if analysis["strengths"] else "  • Keep building!"

    report = (
        f"**{name} — GMB Score: {score}/100** {analysis['color']}\n\n"
        f"{growth_msg}\n\n"
        f"**Sudhar chahiye:**\n{issues}\n\n"
        f"**Accha hai:**\n{strengths}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 **Business connect karein:**\n{connect_url}\n\n"
        f"Connect karein — main automatically verify kar doongi! 😊"
    )

    # Start polling
    _poll_connection(user_id, poll_key, is_whatsapp)
    _poll_payment(user_id, poll_key, is_whatsapp)

    return report


def _call_api(poll_key: str, is_whatsapp: bool) -> dict:
    try:
        param = "phone" if is_whatsapp else "session_id"
        res = httpx.get(
            f"{LIMBU_API_BASE}/gmb/status",
            params={param: poll_key},
            timeout=10
        )
        return res.json()
    except Exception as e:
        print(f"[API] Error: {e}")
        return {}


def _get_features_message(session: dict, business_name: str) -> str:
    """First feature offer after connect"""
    return (
        f"🎉 **{business_name} connect ho gaya!**\n\n"
        f"Ab main aapke liye kuch FREE kaam karti hoon.\n\n"
        f"Pehle — kya main aapki GMB ki poori **Health Report** nikaal dun? 📊\n"
        f"Score, gaps, improvements — sab yahan milega!"
    )


def _poll_connection(user_id: str, poll_key: str, is_whatsapp: bool):
    """Poll every 3 sec for connection — max 5 min"""
    def run():
        for attempt in range(100):
            time.sleep(3)
            try:
                sess = get_session(user_id)
                if sess.get("poll_msg_saved"):
                    break

                data = _call_api(poll_key, is_whatsapp)
                connected = data.get("businessConnected", False) or data.get("status") == "success"
                print(f"[ConnPoll] {user_id} attempt {attempt+1}: connected={connected}")

                if connected and not sess.get("poll_msg_saved"):
                    from app.nodes.connect import handle_check_latest_connection
                    from app.services.redis_service import save_message as _save
                    email = data.get("email", "")
                    locations = data.get("locationsData", [])
                    if email:
                        sess["connected_email"] = email
                    sess["connected_businesses"] = locations
                    sess["connect_verified"] = True
                    sess["poll_msg_saved"] = True
                    save_session(user_id, sess)

                    # Build connect success + first feature offer
                    found = sess.get("found_place", {})
                    biz_name = found.get("displayName", {}).get("text", "aapka business")

                    # Find confirmed business in locations
                    confirmed_biz = None
                    for loc in locations:
                        loc_name = loc.get("title", "").lower()
                        if biz_name.lower() in loc_name or loc_name in biz_name.lower():
                            confirmed_biz = loc
                            break
                    if not confirmed_biz and locations:
                        confirmed_biz = locations[0]

                    if confirmed_biz:
                        name = confirmed_biz.get("title", biz_name)
                        address = confirmed_biz.get("address", "")
                        phone = confirmed_biz.get("primaryPhone", "")
                        verified = "✅ Verified" if confirmed_biz.get("verified") else "⚠️ Not Verified"
                        website = confirmed_biz.get("websiteUri", "")

                        msg = f"🎉 **{name} connect ho gaya!**\n\n"
                        msg += f"📧 {email}\n"
                        msg += f"🏪 {name} — {verified}\n"
                        if address:
                            msg += f"📍 {address}\n"
                        if phone:
                            msg += f"📞 {phone}\n"
                        if website:
                            msg += f"🌐 {website}\n"
                        if len(locations) > 1:
                            msg += f"\n_(Is account se {len(locations)} profiles linked hain)_\n"
                        msg += f"\nAb main aapke liye kuch FREE kaam karti hoon! 🎁\n\nPehle — kya main aapki GMB ki poori **Health Report** nikaal dun? 📊"
                    else:
                        msg = f"🎉 **Business connect ho gaya!**\n\n📧 {email}\n\nAb main aapke liye kuch FREE kaam karti hoon! 🎁\n\nPehle — kya main aapki GMB ki poori **Health Report** nikaal dun? 📊"

                    _save(user_id, "assistant", msg)
                    print(f"[ConnPoll] ✅ Connected! {user_id}")

                    # Send via WhatsApp if needed
                    if is_whatsapp:
                        try:
                            from app.services.whatsapp_service import send_whatsapp
                            send_whatsapp(poll_key, msg)
                        except Exception as e:
                            print(f"[WA] Send error: {e}")
                    break

            except Exception as e:
                print(f"[ConnPoll] Error: {e}")
                time.sleep(5)

    threading.Thread(target=run, daemon=True).start()
    print(f"[ConnPoll] Started for {user_id}")


def _poll_payment(user_id: str, poll_key: str, is_whatsapp: bool):
    """Poll every 5 sec for payment — max 30 min"""
    def run():
        for attempt in range(360):
            time.sleep(5)
            try:
                sess = get_session(user_id)
                if sess.get("payment_notified"):
                    break

                data = _call_api(poll_key, is_whatsapp)
                pay_status = data.get("paymentStatus", "none")
                pay_obj = data.get("payment")

                if attempt % 12 == 0:
                    print(f"[PayPoll] {user_id} attempt {attempt+1}: {pay_status}")

                if pay_status == "paid" or (pay_obj and isinstance(pay_obj, dict)):
                    sess = get_session(user_id)
                    if sess.get("payment_notified"):
                        break
                    p = pay_obj if isinstance(pay_obj, dict) else {}
                    plan_title = p.get("planTitle", "Plan")
                    amount = p.get("amount", "")
                    pay_email = p.get("email") or data.get("email", "")
                    paid_at = p.get("paidAt", "")[:10] if p.get("paidAt") else ""
                    payment_id = p.get("paymentId", "")

                    pay_msg = (
                        f"🎉 **Payment successful! Bahut badhaai ho!**\n\n"
                        f"✅ **{plan_title}** active ho gaya!\n\n"
                        f"💳 Amount: {amount}\n"
                        f"📧 Email: {pay_email}\n"
                        f"📅 Date: {paid_at}\n"
                        f"🔑 ID: {payment_id}\n\n"
                        f"Hamari team kaam shuru kar degi. 🙏\n"
                        f"Koi sawaal ho: 📞 9283344726"
                    )
                    sess["payment_notified"] = True
                    save_session(user_id, sess)
                    from app.services.redis_service import save_message as _save
                    _save(user_id, "assistant", pay_msg)
                    print(f"[PayPoll] ✅ Payment! {user_id}")

                    if is_whatsapp:
                        try:
                            from app.services.whatsapp_service import send_whatsapp
                            send_whatsapp(poll_key, pay_msg)
                        except Exception as e:
                            print(f"[WA] Pay send error: {e}")

                    try:
                        from app.services.analytics_service import save_payment
                        save_payment(user_id, {"plan": plan_title, "amount": amount, "email": pay_email})
                    except: pass
                    break

            except Exception as e:
                print(f"[PayPoll] Error: {e}")
                time.sleep(10)

    threading.Thread(target=run, daemon=True).start()
    print(f"[PayPoll] Started for {user_id}")