from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: str | None, default: int) -> int:
    if value is None or not value.strip():
        return default
    return int(value)


def _as_float(value: str | None, default: float) -> float:
    if value is None or not value.strip():
        return default
    return float(value)


@dataclass(frozen=True)
class ScraperSettings:
    notion_api_key: str
    notion_database_id: str
    google_places_api_key: str
    pagespeed_api_key: str
    openai_api_key: str
    country_scope: str
    active_province: str
    active_city: str
    one_city_per_run: bool
    niche: str
    locations: list[str]
    query_variations: list[str]
    max_new_leads_per_run: int
    max_places_results_per_location: int
    max_total_candidates: int
    request_timeout_seconds: int
    filter_franchises: bool
    min_lead_score: int
    dry_run: bool
    city_duplicate_rate_limit: float
    city_min_usable_email_rate: float
    city_weak_batch_limit: int
    city_target_usable_leads: int
    max_daily_places_requests: int
    max_weekly_places_requests: int
    max_monthly_places_requests: int
    max_weekly_raw_place_results: int
    max_weekly_place_details_calls: int
    max_weekly_unique_leads: int
    max_weekly_gmail_drafts: int


def _bounded_int(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(value, maximum))


def _max_new_leads_per_run() -> int:
    configured = _as_int(
        os.getenv("MAX_NEW_LEADS_PER_RUN")
        or os.getenv("MAX_LEADS_PER_RUN")
        or os.getenv("LEAD_SCRAPER_DAILY_LIMIT")
        or os.getenv("DAILY_LEAD_LIMIT"),
        15,
    )
    return _bounded_int(configured, 1, 50)


def _parse_csv_env(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _build_locations() -> list[str]:
    active_city = os.getenv("ACTIVE_CITY", "Toronto").strip()
    active_province = os.getenv("ACTIVE_PROVINCE", "Ontario").strip()
    one_city_per_run = _as_bool(os.getenv("ONE_CITY_PER_RUN"), default=True)
    if one_city_per_run:
        if active_province:
            return [f"{active_city}, {active_province}"]
        return [active_city]
    return _parse_csv_env(
        "LEAD_SCRAPER_LOCATIONS",
        "Toronto, North York, Scarborough, Etobicoke, East York, York, Mississauga, Brampton, Vaughan, Markham, Richmond Hill, Thornhill, Oakville, Burlington, Hamilton, Milton, Pickering, Ajax, Whitby, Oshawa, Aurora, Newmarket, Barrie, Guelph, Kitchener, Waterloo, Cambridge, London, Windsor, Ottawa, Kanata, Nepean, Orleans, Kingston",
    )


settings = ScraperSettings(
    notion_api_key=os.getenv("NOTION_API_KEY", "").strip(),
    notion_database_id=os.getenv("NOTION_DATABASE_ID", "").strip(),
    google_places_api_key=os.getenv("GOOGLE_PLACES_API_KEY", "").strip(),
    pagespeed_api_key=os.getenv("PAGESPEED_API_KEY", "").strip(),
    openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
    country_scope=os.getenv("COUNTRY_SCOPE", "Canada").strip(),
    active_province=os.getenv("ACTIVE_PROVINCE", "Ontario").strip(),
    active_city=os.getenv("ACTIVE_CITY", "Toronto").strip(),
    one_city_per_run=_as_bool(os.getenv("ONE_CITY_PER_RUN"), default=True),
    niche=os.getenv("LEAD_SCRAPER_NICHE", "dental clinic").strip(),
    locations=_build_locations(),
    query_variations=_parse_csv_env(
        "LEAD_SCRAPER_QUERIES",
        "dental clinic, dentist, cosmetic dentist, family dentist, dental office",
    ),
    max_new_leads_per_run=_max_new_leads_per_run(),
    max_places_results_per_location=_bounded_int(_as_int(os.getenv("MAX_PLACES_RESULTS_PER_LOCATION"), 20), 1, 20),
    max_total_candidates=_bounded_int(_as_int(os.getenv("MAX_TOTAL_CANDIDATES"), 60), 1, 200),
    request_timeout_seconds=_as_int(os.getenv("SCRAPER_REQUEST_TIMEOUT_SECONDS"), 12),
    filter_franchises=_as_bool(os.getenv("FILTER_FRANCHISES"), default=True),
    min_lead_score=_as_int(os.getenv("MIN_LEAD_SCORE"), 3),
    dry_run=_as_bool(os.getenv("DRY_RUN"), default=True),
    city_duplicate_rate_limit=_as_float(os.getenv("CITY_DUPLICATE_RATE_LIMIT"), 0.70),
    city_min_usable_email_rate=_as_float(os.getenv("CITY_MIN_USABLE_EMAIL_RATE"), 0.15),
    city_weak_batch_limit=_as_int(os.getenv("CITY_WEAK_BATCH_LIMIT"), 3),
    city_target_usable_leads=_as_int(os.getenv("CITY_TARGET_USABLE_LEADS"), 300),
    max_daily_places_requests=_as_int(os.getenv("MAX_DAILY_PLACES_REQUESTS"), 1000),
    max_weekly_places_requests=_as_int(os.getenv("MAX_WEEKLY_PLACES_REQUESTS"), 3000),
    max_monthly_places_requests=_as_int(os.getenv("MAX_MONTHLY_PLACES_REQUESTS"), 10000),
    max_weekly_raw_place_results=_as_int(os.getenv("MAX_WEEKLY_RAW_PLACE_RESULTS"), 1000),
    max_weekly_place_details_calls=_as_int(os.getenv("MAX_WEEKLY_PLACE_DETAILS_CALLS"), 750),
    max_weekly_unique_leads=_as_int(os.getenv("MAX_WEEKLY_UNIQUE_LEADS"), 300),
    max_weekly_gmail_drafts=_as_int(os.getenv("MAX_WEEKLY_GMAIL_DRAFTS"), 75),
)
