import httpx
import threading
import time
from app.core.config import LIMBU_META_STATUS_API, SOCIAL_PLATFORMS
from app.services.redis_service import get_session, save_session, save_message
from app.services.whatsapp_service import send_whatsapp


def _get_phone(user_id: str, session: dict = None) -> str:
    if session and session.get("connect_phone"):
        return session["connect_phone"]
    if user_id.startswith("wa_"):
        phone = user_id.replace("wa_", "").replace("+", "").replace(" ", "")
        if not phone.startswith("91") and len(phone) == 10:
            phone = "91" + phone
        return phone
    return ""


def handle_social_connect_link(user_id: str, session: dict, platform: str) -> str:
    """Generate and send social media connect link — no business name needed"""
    phone = _get_phone(user_id, session)
    lang = session.get("lang", "hi")
    en = (lang == "en")

    platform_info = SOCIAL_PLATFORMS.get(platform)
    if not platform_info:
        return "Invalid platform. Supported: facebook, instagram" if en else                "Invalid platform. Facebook aur Instagram supported hain."

    # Build connect URL with phone
    connect_url = f"{platform_info['connect_url']}&phone={phone}" if phone else platform_info['connect_url']

    # Save state
    session[f"{platform}_link_sent"] = True
    session[f"{platform}_verified"] = False
    if phone:
        session["connect_phone"] = phone
    save_session(user_id, session)

    emoji = platform_info["emoji"]
    name = platform_info["name"]

    if en:
        reply = emoji + " *Connect your " + name + " Page*\n\n"
        reply += "Click this link:\n"
        reply += "🔗 " + connect_url + "\n\n"
        reply += "Login with your " + name + " account and allow access.\n"
        reply += "I'll notify you automatically once connected! 😊"
    else:
        reply = emoji + " *" + name + " Page connect karein*\n\n"
        reply += "Is link se connect karein:\n"
        reply += "🔗 " + connect_url + "\n\n"
        reply += "Apne " + name + " account se login karein aur access allow karein.\n"
        reply += "Connect hone ke baad main automatically notify karungi! 😊"

    # Start polling
    if phone:
        _start_social_polling(user_id, phone, platform)

    return reply


def _start_social_polling(user_id: str, phone: str, platform: str):
    t = threading.Thread(
        target=_poll_social_connection,
        args=(user_id, phone, platform),
        daemon=True
    )
    t.start()
    print(f"[SocialPoll] Started for user={user_id} platform={platform}")


def _poll_social_connection(user_id: str, phone: str, platform: str):
    """Poll for social media connection — same as GMB polling"""
    for attempt in range(100):
        time.sleep(5)
        try:
            session = get_session(user_id)

            # Already verified
            if session.get(f"{platform}_verified"):
                break

            # Phone changed
            if session.get("connect_phone") != phone:
                break

            with httpx.Client(timeout=10) as client:
                res = client.get(
                    LIMBU_META_STATUS_API,
                    params={"phone": phone, "type": platform}
                )
                data = res.json()
                print(f"[SocialPoll] {user_id} {platform} attempt {attempt+1}: {data.get('status')}")

                if data.get("success") and data.get("connected"):
                    pages = data.get("pagesData", [])
                    email = data.get("userId", "")

                    session[f"{platform}_verified"] = True
                    session[f"{platform}_pages"] = pages
                    session[f"{platform}_user_id"] = email
                    save_session(user_id, session)

                    reply = _build_connected_response(session, platform, pages)
                    save_message(user_id, "assistant", reply)
                    send_whatsapp(phone, reply)
                    print(f"[SocialPoll] Connected! user={user_id} platform={platform}")
                    break

        except Exception as e:
            print(f"[SocialPoll] Error: {e}")
            time.sleep(5)


def _build_connected_response(session: dict, platform: str, pages: list) -> str:
    """Build connected response — similar to GMB connected response"""
    lang = session.get("lang", "hi")
    en = (lang == "en")
    platform_info = SOCIAL_PLATFORMS.get(platform, {})
    emoji = platform_info.get("emoji", "📱")
    name = platform_info.get("name", platform.title())

    if not pages:
        if en:
            return f"🎉 *{name} connected successfully!*\n\nNo pages found. Please check your account."
        return f"🎉 *{name} connect ho gaya!*\n\nKoi page nahi mila. Account check karein."

    page_lines = []
    for i, p in enumerate(pages, 1):
        page_name = p.get("pageName", "Page")
        page_id = p.get("pageId", "")
        page_lines.append(f"  {i}. *{page_name}*" + (f" (ID: {page_id})" if page_id else ""))

    pages_text = "\n".join(page_lines)

    if en:
        return (
            f"🎉 *{name} Connected Successfully!*\n\n"
            f"{emoji} *Connected Pages:*\n{pages_text}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Your {name} pages are now connected. 😊"
        )
    return (
        f"🎉 *{name} Connect Ho Gaya!*\n\n"
        f"{emoji} *Connected Pages:*\n{pages_text}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Aapke {name} pages ab connected hain. 😊"
    )


def handle_check_social_connection(user_id: str, session: dict, platform: str) -> str:
    """Check current social media connection status"""
    phone = _get_phone(user_id, session)
    if not phone:
        return handle_social_connect_link(user_id, session, platform)

    try:
        with httpx.Client(timeout=15) as client:
            res = client.get(
                LIMBU_META_STATUS_API,
                params={"phone": phone, "type": platform}
            )
            data = res.json()
            print(f"[SocialCheck] {platform}: {data.get('status')}")

            if data.get("success") and data.get("connected"):
                pages = data.get("pagesData", [])
                session[f"{platform}_verified"] = True
                session[f"{platform}_pages"] = pages
                save_session(user_id, session)
                return _build_connected_response(session, platform, pages)
            else:
                return handle_social_connect_link(user_id, session, platform)

    except Exception as e:
        print(f"[SocialCheck] Error: {e}")
        lang = session.get("lang", "hi")
        return "Technical issue. Please call +91 9289344726." if lang == "en" else \
               "Technical problem aayi. +91 9289344726 pe call karein."