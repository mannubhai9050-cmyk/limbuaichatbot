from app.services.google_places import search_places
from app.services.redis_service import save_session, get_session


def handle_search(user_id: str, session: dict, name: str, city: str) -> str:
    lang = session.get("lang", "hi")
    en = (lang == "en")

    # Validate both name and city are present and meaningful
    name = name.strip()
    city = city.strip()

    if not name or len(name) < 3:
        return "Please share your *business name* (e.g. Shyamji Traders). 😊" if en else                "Apna *business naam* batayein (jaise: Shyamji Traders). 😊"

    if not city or len(city) < 2:
        return f"*{name}* — kaun se city mein hai? 😊" if not en else                f"*{name}* — which city is it in? 😊"

    # Reject generic-only search terms
    generic = {"manufacturer", "trader", "shop", "store", "company", "business",
               "service", "center", "restaurant", "clinic", "i am", "i am on"}
    if name.lower() in generic:
        return f"Aapke business ka exact naam kya hai? (jaise: Shyamji Traders, ABC Store) 😊" if not en else                f"What is the exact name of your business? (e.g. Shyamji Traders, ABC Store) 😊"

    places = search_places(name, city, page_size=5)
    session["search_places"] = places
    session["result_index"] = 0
    session["business_name"] = name
    session["city"] = city
    session["confirmed"] = False
    session["found_place"] = None
    save_session(user_id, session)
    return _format_result(places, 0, name, city, user_id, session)


def handle_next_result(user_id: str, session: dict) -> str:
    places = session.get("search_places", [])
    idx = session.get("result_index", 0) + 1
    session["result_index"] = idx
    session["confirmed"] = False
    session["found_place"] = None
    save_session(user_id, session)
    return _format_result(
        places, idx,
        session.get("business_name", ""),
        session.get("city", ""),
        None, session
    )


def _format_result(places: list, index: int, name: str, city: str, user_id, session: dict) -> str:
    lang = session.get("lang", "hi")
    en = (lang == "en")

    if not places or index >= len(places):
        if en:
            return (
                f"I couldn't find *{name}* in {city} on Google. 😕\n\n"
                f"Your business might not be listed yet. Limbu.ai can create your GMB profile — ₹3,000 one-time.\n\n"
                f"Want to know more? 📞 9283344726"
            )
        return (
            f"*{name}* {city} mein Google par nahi mila. 😕\n\n"
            f"Aapka business listed nahi hai abhi tak. Limbu.ai GMB profile bana sakta hai — ₹3,000 one-time.\n\n"
            f"Jaanna chahte hain? 📞 9283344726"
        )

    place = places[index]
    if user_id:
        from app.services.redis_service import save_session as _ss
        session["found_place"] = place
        session["confirmed"] = False
        _ss(user_id, session)

    if en:
        prefix = "Here's what I found:" if index == 0 else "Let me show you another result:"
        confirm_q = "Is this your business?"
    else:
        prefix = "Yeh mila:" if index == 0 else "Ek aur result dekhte hain:"
        confirm_q = "Kya yeh aapka business hai?"

    return (
        f"{prefix}\n\n"
        f"🏪 *{place.get('displayName', {}).get('text', name)}*\n"
        f"📍 {place.get('formattedAddress', '')}\n"
        f"⭐ {place.get('rating', 'N/A')}/5 ({place.get('userRatingCount', 0)} reviews)\n"
        f"🔗 {place.get('googleMapsUri', '')}\n\n"
        f"{confirm_q}"
    )