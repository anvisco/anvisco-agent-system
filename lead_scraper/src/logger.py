from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from .utils import now_iso_date


@dataclass
class DailyLogger:
    log_dir: Path = Path("logs")
    counters: Dict[str, int] = field(
        default_factory=lambda: {
            "total_found": 0,
            "candidates_found": 0,
            "target_new_leads_requested": 0,
            "candidates_processed": 0,
            "total_skipped": 0,
            "duplicates_found": 0,
            "new_inserted": 0,
            "would_insert": 0,
            "would_update": 0,
            "existing_enriched": 0,
            "duplicates_skipped": 0,
            "already_contacted_skipped": 0,
            "no_website_skipped": 0,
            "low_score_skipped": 0,
            "leads_scraped": 0,
            "errors": 0,
        }
    )
    skipped: List[str] = field(default_factory=list)
    events: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.log_dir / f"lead_scraper_{now_iso_date()}.log"

    def count(self, key: str, amount: int = 1) -> None:
        self.counters[key] = self.counters.get(key, 0) + amount

    def event(self, message: str) -> None:
        self.events.append(message)
        print(message)

    def skip(self, business_name: str, website_or_domain: str, reason: str) -> None:
        self.count("total_skipped")
        line = f"SKIP | {business_name or '<unknown>'} | {website_or_domain or '<no website>'} | {reason}"
        self.skipped.append(line)
        print(line)

    def error(self, business_name: str, reason: str) -> None:
        self.count("errors")
        line = f"ERROR | {business_name or '<unknown>'} | {reason}"
        self.events.append(line)
        print(line)

    def write(self) -> None:
        lines = ["Lead Scraper Daily Log", f"Date: {now_iso_date()}", "", "Summary:"]
        for key, value in self.counters.items():
            lines.append(f"- {key}: {value}")
        lines.extend(["", "Events:", *self.events, "", "Skipped:", *self.skipped])
        self.path.write_text("\n".join(lines), encoding="utf-8")
        self.print_summary()
        print(f"Log written to {self.path}")

    def print_summary(self) -> None:
        print("")
        print("Lead Scraper Run Summary")
        print(f"- target new leads requested: {self.counters.get('target_new_leads_requested', 0)}")
        print(f"- total candidates pulled: {self.counters.get('total_found', 0)}")
        print(f"- candidates found: {self.counters.get('candidates_found', 0)}")
        print(f"- candidates processed: {self.counters.get('candidates_processed', 0)}")
        print(f"- leads found from Google Places: {self.counters.get('total_found', 0)}")
        print(f"- leads skipped: {self.counters.get('total_skipped', 0)}")
        print(f"- duplicates found: {self.counters.get('duplicates_found', 0)}")
        print(f"- duplicates skipped: {self.counters.get('duplicates_skipped', 0)}")
        print(f"- leads scraped: {self.counters.get('leads_scraped', 0)}")
        print(f"- leads that would be inserted in dry run: {self.counters.get('would_insert', 0)}")
        print(f"- leads that would be updated in dry run: {self.counters.get('would_update', 0)}")
        print(f"- new leads inserted: {self.counters.get('new_inserted', 0)}")
        print(f"- duplicates enriched: {self.counters.get('existing_enriched', 0)}")
        print(f"- duplicates skipped during discovery: {self.counters.get('duplicates_skipped', 0)}")
        print(f"- errors: {self.counters.get('errors', 0)}")
        if self.skipped:
            print("Skipped lead details:")
            for line in self.skipped[:20]:
                print(f"- {line}")
