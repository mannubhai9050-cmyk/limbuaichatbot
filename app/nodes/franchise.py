"""
Franchise registration node — collects user details and registers via API.
"""
import httpx
from app.services.redis_service import get_session, save_session

FRANCHISE_API = "https://limbu.ai/api/franchise"


def handle_franchise_register(user_id: str, session: dict, name: str, phone: str, city: str, email: str = "") -> str:
    lang = session.get("lang", "hi")
    en = (lang == "en")

    # Validate required fields
    if not name or not phone or not city:
        if en:
            return "Please share your *name*, *phone number*, and *city* to register for the franchise."
        return "Franchise ke liye apna *naam*, *phone number*, aur *city* batayein."

    # Clean phone
    phone_clean = phone.replace("+91", "").replace("+", "").replace(" ", "").replace("-", "")
    if phone_clean.startswith("91") and len(phone_clean) == 12:
        phone_clean = phone_clean[2:]

    try:
        payload = {
            "name": name,
            "email": email or "",
            "phone": phone_clean,
            "city": city,
            "investment": ""
        }
        print(f"[Franchise] Registering: {payload}")

        with httpx.Client(timeout=15) as client:
            res = client.post(
                FRANCHISE_API,
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            print(f"[Franchise] API {res.status_code}: {res.text[:200]}")
            data = res.json() if res.status_code in [200, 201] else {}
            success = data.get("success") or res.status_code in [200, 201]

    except Exception as e:
        print(f"[Franchise] Error: {e}")
        success = False

    # Save to session
    session["franchise_registered"] = True
    session["franchise_name"] = name
    session["franchise_city"] = city
    save_session(user_id, session)

    if success:
        if en:
            return (
                "🎉 *Franchise registration successful!*\n\n"
                "✅ Name: " + name + "\n"
                "✅ City: " + city + "\n\n"
                "Our team will call you within *24 hours* to discuss the next steps.\n\n"
                "Questions? Call 📞 +91 9289344726 | info@limbu.ai"
            )
        return (
            "🎉 *Franchise registration ho gaya!*\n\n"
            "✅ Naam: " + name + "\n"
            "✅ City: " + city + "\n\n"
            "Hamare team member aapko *24 hours* mein call karenge.\n\n"
            "Sawaal hain? Call karein 📞 +91 9289344726 | info@limbu.ai"
        )
    else:
        if en:
            return (
                "Registration submitted! Our team will reach out soon.\n\n"
                "Direct contact: 📞 +91 9289344726 | info@limbu.ai"
            )
        return (
            "Registration ho gaya! Hamar team jald contact karega.\n\n"
            "Direct contact: 📞 +91 9289344726 | info@limbu.ai"
        )