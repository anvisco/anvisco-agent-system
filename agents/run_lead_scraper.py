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
    print(f"MAX_LEADS_PER_RUN: {settings.daily_lead_limit}")
    run_daily_scrape()
