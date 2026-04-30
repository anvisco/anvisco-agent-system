from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urlparse


def now_iso_date() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def normalize_domain(url: str) -> str:
    if not url:
        return ""
    candidate = url.strip()
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    parsed = urlparse(candidate)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host.split(":")[0]


def clean_phone(phone: str) -> str:
    digits = re.sub(r"\D+", "", phone or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def display_phone(phone: str) -> str:
    digits = clean_phone(phone)
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return phone.strip()


def is_probably_better_text(existing: str, incoming: str) -> bool:
    if not incoming.strip():
        return False
    if not existing.strip():
        return True
    weak_markers = {"unknown", "n/a", "none", "not checked"}
    if existing.strip().lower() in weak_markers:
        return True
    return len(incoming.strip()) > len(existing.strip()) + 30


def append_note(existing: str, note: str) -> str:
    if not existing:
        return note
    if note in existing:
        return existing
    return f"{existing}\n{note}"
