from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: str | None, default: int) -> int:
    if value is None or not value.strip():
        return default
    return int(value)


@dataclass(frozen=True)
class ScraperSettings:
    notion_api_key: str
    notion_database_id: str
    google_places_api_key: str
    pagespeed_api_key: str
    openai_api_key: str
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


settings = ScraperSettings(
    notion_api_key=os.getenv("NOTION_API_KEY", "").strip(),
    notion_database_id=os.getenv("NOTION_DATABASE_ID", "").strip(),
    google_places_api_key=os.getenv("GOOGLE_PLACES_API_KEY", "").strip(),
    pagespeed_api_key=os.getenv("PAGESPEED_API_KEY", "").strip(),
    openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
    niche=os.getenv("LEAD_SCRAPER_NICHE", "dental clinic").strip(),
    locations=_parse_csv_env(
        "LEAD_SCRAPER_LOCATIONS",
        "Toronto, North York, Willowdale, Scarborough, Etobicoke, Markham, Vaughan, Richmond Hill, Thornhill, Mississauga, Brampton, East York, York, Leaside, Midtown Toronto, Downtown Toronto",
    ),
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
)
