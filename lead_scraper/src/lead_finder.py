from __future__ import annotations

from typing import Any, Dict, List

import requests

from .config import settings
from .models import FoundLead
from .utils import clean_phone, normalize_domain


FRANCHISE_KEYWORDS = (
    "dentalcorp",
    "altima",
    "dawson dental",
    "123dentist",
    "toothworks",
    "monarch dentistry",
)
PLACES_SEARCH_TEXT_ENDPOINT = "https://places.googleapis.com/v1/places:searchText"
PLACES_FIELD_MASK = ",".join(
    (
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.location",
        "places.rating",
        "places.userRatingCount",
        "places.nationalPhoneNumber",
        "places.internationalPhoneNumber",
        "places.websiteUri",
        "places.googleMapsUri",
        "places.businessStatus",
    )
)


def _is_obvious_franchise(name: str, website: str) -> bool:
    combined = f"{name} {website}".lower()
    return any(keyword in combined for keyword in FRANCHISE_KEYWORDS)


def _safe_error_message(payload: Dict[str, Any]) -> str:
    error = payload.get("error", {})
    code = error.get("status") or error.get("code") or "UNKNOWN"
    message = error.get("message") or payload.get("error_message") or "No error message returned"
    return f"{code}: {message}"


def _search_places_new(text_query: str) -> List[Dict[str, Any]]:
    print("Google Places endpoint used: Places API (New) searchText")
    print(f"Google Places query: {text_query}")
    response = requests.post(
        PLACES_SEARCH_TEXT_ENDPOINT,
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": settings.google_places_api_key,
            "X-Goog-FieldMask": PLACES_FIELD_MASK,
        },
        json={
            "textQuery": text_query,
            "maxResultCount": 10,
            "languageCode": "en",
            "regionCode": "CA",
        },
        timeout=settings.request_timeout_seconds,
    )
    print(f"Google Places HTTP status for '{text_query}': {response.status_code}")

    try:
        payload = response.json()
    except ValueError:
        print(f"Google Places returned non-JSON response for query: {text_query}")
        response.raise_for_status()
        return []

    if response.status_code != 200:
        error_message = _safe_error_message(payload)
        print(f"Google Places error for '{text_query}': {error_message}")
        if "PERMISSION_DENIED" in error_message:
            print("Places API (New) may not be enabled or API key restriction is wrong.")
        if "INVALID_ARGUMENT" in error_message:
            print(f"Google Places INVALID_ARGUMENT response body: {payload}")
        return []

    places = payload.get("places", [])
    print(f"Google Places places returned for '{text_query}': {len(places)}")
    if not places:
        print(f"No Google Places leads returned for exact textQuery: {text_query}")
    return places


def _display_name(place: Dict[str, Any]) -> str:
    display_name = place.get("displayName", {})
    if isinstance(display_name, dict):
        return display_name.get("text", "")
    return ""


def _dedupe_key(place: Dict[str, Any], location: str) -> tuple[str, str]:
    place_id = place.get("id", "")
    if place_id:
        return "place_id", place_id

    website = normalize_domain(place.get("websiteUri", ""))
    if website:
        return "domain", website

    phone = clean_phone(place.get("nationalPhoneNumber", "") or place.get("internationalPhoneNumber", ""))
    if phone:
        return "phone", phone

    name = _display_name(place).strip().lower()
    address = place.get("formattedAddress", "").strip().lower()
    return "name_address", f"{name}|{address or location.lower()}"


def _to_found_lead(place: Dict[str, Any], location: str) -> FoundLead:
    phone = place.get("nationalPhoneNumber", "") or place.get("internationalPhoneNumber", "")
    return FoundLead(
        google_place_id=place.get("id", ""),
        business_name=_display_name(place),
        website=place.get("websiteUri", ""),
        phone=phone,
        address=place.get("formattedAddress", ""),
        city=location,
        rating=place.get("rating"),
        review_count=place.get("userRatingCount"),
        google_maps_url=place.get("googleMapsUri", ""),
        source="Google Places New",
    )


def find_local_leads() -> List[FoundLead]:
    if not settings.google_places_api_key:
        raise ValueError("GOOGLE_PLACES_API_KEY is missing.")

    found: List[FoundLead] = []
    seen_keys: set[tuple[str, str]] = set()

    for location in settings.locations:
        query = f"{settings.niche} in {location}"
        places = _search_places_new(query)

        for place in places:
            if len(found) >= settings.daily_lead_limit * 2:
                print(f"Total unique leads found: {len(found)}")
                return found
            dedupe_key = _dedupe_key(place, location)
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)

            if place.get("businessStatus") and place["businessStatus"] != "OPERATIONAL":
                continue

            website = place.get("websiteUri", "")
            name = _display_name(place)
            if settings.filter_franchises and _is_obvious_franchise(name, website):
                continue

            found.append(_to_found_lead(place, location))

    print(f"Total unique leads found: {len(found)}")
    return found
