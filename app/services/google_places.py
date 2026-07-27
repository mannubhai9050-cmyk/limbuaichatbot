import httpx
from app.core.config import GOOGLE_API_KEY

# Full field mask for accurate scoring
FIELD_MASK_SEARCH = (
    "places.id,places.displayName,places.formattedAddress,"
    "places.googleMapsUri,places.rating,places.userRatingCount,"
    "places.photos,places.regularOpeningHours,places.websiteUri,"
    "places.nationalPhoneNumber,places.internationalPhoneNumber,"
    "places.businessStatus,places.primaryType,places.primaryTypeDisplayName,"
    "places.types,places.location,places.addressComponents"
)

# Full field mask for place details (includes reviews for reply rate)
FIELD_MASK_DETAILS = (
    "id,displayName,formattedAddress,googleMapsUri,rating,userRatingCount,"
    "photos,regularOpeningHours,websiteUri,nationalPhoneNumber,"
    "internationalPhoneNumber,businessStatus,primaryType,primaryTypeDisplayName,"
    "types,reviews,location,addressComponents,editorialSummary,"
    "openingDate,pureServiceAreaBusiness"
)


def search_places(name: str, city: str, page_size: int = 5,
                  lat: float = None, lng: float = None) -> list:
    """
    Search business on Google Places API v1.

    lat/lng diye ho (jaise Maps link se) to search UN coordinates par bias hoti
    hai — warna 'Mr. Dumpling' jaisa naam duniya bhar mein pehla galat result
    (USA) de deta hai. Bias se sahi location (jaise Kanpur) wala aata hai.
    """
    query = f"{name} {city}".strip() if city else name
    body = {"textQuery": query, "pageSize": page_size}
    if lat is not None and lng is not None:
        body["locationBias"] = {
            "circle": {"center": {"latitude": lat, "longitude": lng},
                       "radius": 3000.0}
        }
    try:
        with httpx.Client(timeout=15) as client:
            res = client.post(
                "https://places.googleapis.com/v1/places:searchText",
                headers={
                    "Content-Type": "application/json",
                    "X-Goog-Api-Key": GOOGLE_API_KEY,
                    "X-Goog-FieldMask": FIELD_MASK_SEARCH
                },
                json=body
            )
            data = res.json()
            places = data.get("places", [])
            bias = f" @({lat},{lng})" if lat is not None else ""
            print(f"[Places] Search '{query}'{bias} → {len(places)} results")
            return places
    except Exception as e:
        print(f"[GooglePlaces] Search error: {e}")
        return []


def get_place_details(place_id: str) -> dict:
    """
    Get full place details by place_id — includes reviews for reply rate scoring.
    place_id format: 'places/ChIJ...' or just 'ChIJ...'
    """
    if not place_id:
        return {}
    # Ensure proper format
    if not place_id.startswith("places/"):
        place_id = f"places/{place_id}"
    try:
        with httpx.Client(timeout=15) as client:
            res = client.get(
                f"https://places.googleapis.com/v1/{place_id}",
                headers={
                    "Content-Type": "application/json",
                    "X-Goog-Api-Key": GOOGLE_API_KEY,
                    "X-Goog-FieldMask": FIELD_MASK_DETAILS
                }
            )
            if res.status_code == 200:
                data = res.json()
                print(f"[Places] Got details for {place_id}: rating={data.get('rating')} reviews={data.get('userRatingCount')}")
                return data
            else:
                print(f"[Places] Details error {res.status_code}: {res.text[:100]}")
                return {}
    except Exception as e:
        print(f"[GooglePlaces] Details error: {e}")
        return {}