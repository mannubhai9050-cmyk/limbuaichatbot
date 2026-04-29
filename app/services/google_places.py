import httpx
from app.core.config import GOOGLE_API_KEY

FIELD_MASK = (
    "places.displayName,places.formattedAddress,"
    "places.googleMapsUri,places.rating,"
    "places.userRatingCount,places.photos,"
    "places.regularOpeningHours,places.websiteUri,"
    "places.nationalPhoneNumber,places.businessStatus"
)


def search_places(name: str, city: str, page_size: int = 5) -> list:
    """Search business on Google Places API v1"""
    try:
        with httpx.Client(timeout=10) as client:
            res = client.post(
                "https://places.googleapis.com/v1/places:searchText",
                headers={
                    "Content-Type": "application/json",
                    "X-Goog-Api-Key": GOOGLE_API_KEY,
                    "X-Goog-FieldMask": FIELD_MASK
                },
                json={"textQuery": f"{name} {city}", "pageSize": page_size}
            )
            data = res.json()
            return data.get("places", [])
    except Exception as e:
        print(f"[GooglePlaces] Error: {e}")
        return []