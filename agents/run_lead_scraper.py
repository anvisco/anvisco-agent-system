from __future__ import annotations

import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from lead_scraper.src.config import settings
from lead_scraper.src.index import run_daily_scrape


if __name__ == "__main__":
    print("Running Anvisco lead scraper agent")
    print("Secrets are reported as present yes/no only; secret values are never printed.")
    print(f"DRY_RUN value: {settings.dry_run}")
    print(f"MAX_NEW_LEADS_PER_RUN: {settings.max_new_leads_per_run}")
    print(f"MAX_PLACES_RESULTS_PER_LOCATION: {settings.max_places_results_per_location}")
    print(f"MAX_TOTAL_CANDIDATES: {settings.max_total_candidates}")
    run_daily_scrape()
