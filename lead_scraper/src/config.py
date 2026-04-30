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
    daily_lead_limit: int
    request_timeout_seconds: int
    filter_franchises: bool
    min_lead_score: int
    dry_run: bool


def _daily_limit() -> int:
    configured = _as_int(os.getenv("LEAD_SCRAPER_DAILY_LIMIT") or os.getenv("DAILY_LEAD_LIMIT"), 10)
    return max(10, min(configured, 20))


settings = ScraperSettings(
    notion_api_key=os.getenv("NOTION_API_KEY", "").strip(),
    notion_database_id=os.getenv("NOTION_DATABASE_ID", "").strip(),
    google_places_api_key=os.getenv("GOOGLE_PLACES_API_KEY", "").strip(),
    pagespeed_api_key=os.getenv("PAGESPEED_API_KEY", "").strip(),
    openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
    niche=os.getenv("LEAD_SCRAPER_NICHE", "dental clinic").strip(),
    locations=[
        item.strip()
        for item in os.getenv("LEAD_SCRAPER_LOCATIONS", "Toronto, North York, Willowdale").split(",")
        if item.strip()
    ],
    daily_lead_limit=_daily_limit(),
    request_timeout_seconds=_as_int(os.getenv("SCRAPER_REQUEST_TIMEOUT_SECONDS"), 12),
    filter_franchises=_as_bool(os.getenv("FILTER_FRANCHISES"), default=True),
    min_lead_score=_as_int(os.getenv("MIN_LEAD_SCORE"), 3),
    dry_run=_as_bool(os.getenv("DRY_RUN"), default=True),
)
