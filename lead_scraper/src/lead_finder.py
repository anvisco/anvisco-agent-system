from __future__ import annotations

from typing import Any, Dict, Iterable, List

import requests

from .config import settings
from .models import FoundLead


FRANCHISE_KEYWORDS = (
    "dentalcorp",
    "altima",
    "dawson dental",
    "123dentist",
    "toothworks",
    "monarch dentistry",
)


def _is_obvious_franchise(name: str, website: str) -> bool:
    combined = f"{name} {website}".lower()
    return any(keyword in combined for keyword in FRANCHISE_KEYWORDS)


def _extract_city(address: str) -> str:
    parts = [part.strip() for part in address.split(",") if part.strip()]
    if len(parts) >= 2:
        return parts[-3] if len(parts) >= 3 else parts[-2]
    return ""


def _details_for_place(place_id: str) -> Dict[str, Any]:
    response = requests.get(
        "https://maps.googleapis.com/maps/api/place/details/json",
        params={
            "place_id": place_id,
            "fields": "name,formatted_address,formatted_phone_number,website,rating,user_ratings_total,url,business_status",
            "key": settings.google_places_api_key,
        },
        timeout=settings.request_timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    return payload.get("result", {})


def find_local_leads() -> List[FoundLead]:
    if not settings.google_places_api_key:
        raise ValueError("GOOGLE_PLACES_API_KEY is missing.")

    found: List[FoundLead] = []
    seen_place_ids: set[str] = set()

    for location in settings.locations:
        response = requests.get(
            "https://maps.googleapis.com/maps/api/place/textsearch/json",
            params={
                "query": f"{settings.niche} in {location}",
                "key": settings.google_places_api_key,
            },
            timeout=settings.request_timeout_seconds,
        )
        response.raise_for_status()
        results = response.json().get("results", [])

        for result in results:
            if len(found) >= settings.daily_lead_limit * 2:
                return found
            place_id = result.get("place_id")
            if not place_id or place_id in seen_place_ids:
                continue
            seen_place_ids.add(place_id)

            details = _details_for_place(place_id)
            if details.get("business_status") and details["business_status"] != "OPERATIONAL":
                continue

            website = details.get("website", "")
            name = details.get("name", result.get("name", ""))
            if settings.filter_franchises and _is_obvious_franchise(name, website):
                continue

            found.append(
                FoundLead(
                    business_name=name,
                    website=website,
                    phone=details.get("formatted_phone_number", ""),
                    address=details.get("formatted_address", result.get("formatted_address", "")),
                    city=_extract_city(details.get("formatted_address", result.get("formatted_address", ""))),
                    rating=details.get("rating"),
                    review_count=details.get("user_ratings_total"),
                    google_maps_url=details.get("url", ""),
                )
            )

    return found
