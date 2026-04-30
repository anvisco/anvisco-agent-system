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
            "new_inserted": 0,
            "existing_enriched": 0,
            "duplicates_skipped": 0,
            "already_contacted_skipped": 0,
            "no_website_skipped": 0,
            "low_score_skipped": 0,
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
        print(f"Log written to {self.path}")
