from app.services.google_places import search_places
from app.services.redis_service import save_session
from app.core.prompts import BUSINESS_FOUND_TEMPLATE


def handle_search(user_id: str, session: dict, name: str, city: str) -> str:
    """Search business and save result to session"""
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
    """Show next search result"""
    places = session.get("search_places", [])
    idx = session.get("result_index", 0) + 1
    session["result_index"] = idx
    session["confirmed"] = False
    session["found_place"] = None
    save_session(user_id, session)
    return _format_result(places, idx,
                          session.get("business_name", ""),
                          session.get("city", ""),
                          user_id, session)


def _format_result(places: list, index: int, name: str, city: str, user_id: str, session: dict) -> str:
    if not places or index >= len(places):
        return (
            f"I couldn't find **{name}** in {city} on Google. 😕\n\n"
            f"Your business might not be listed yet. Limbu.ai can help create your GMB profile — ₹3,000 one-time.\n\n"
            f"Want to know more? 📞 9283344726"
        )

    place = places[index]

    # ✅ IMPORTANT: Save found_place to session
    session["found_place"] = place
    session["confirmed"] = False
    save_session(user_id, session)

    prefix = "Here's what I found:" if index == 0 else "Let me try another one:"

    return BUSINESS_FOUND_TEMPLATE.format(
        prefix=prefix,
        name=place.get("displayName", {}).get("text", name),
        address=place.get("formattedAddress", ""),
        rating=place.get("rating", "N/A"),
        reviews=place.get("userRatingCount", 0),
        maps_url=place.get("googleMapsUri", "")
    )