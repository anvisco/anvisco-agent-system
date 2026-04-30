from __future__ import annotations

import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from lead_scraper.src.index import run_daily_scrape


if __name__ == "__main__":
    run_daily_scrape()
