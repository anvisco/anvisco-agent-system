from __future__ import annotations

import re
from typing import Iterable, List


ALLOWED_PROSPECT_REFERENCES = ("anvisco.com", "brian@anvisco.com")
STALE_BRAND_RE = re.compile(r"\banvisco\b", re.IGNORECASE)
MANUAL_PAYMENT_RE = re.compile(
    r"\b(manual payment|manual pay|payment link|payment links|stripe payment links?)\b",
    re.IGNORECASE,
)
BACKEND_RE = re.compile(
    r"\b("
    r"supabase|stripe|resend|cloudflare|gmail|notion|webhook|backend|database|auth|"
    r"portal internals|magic link|api key|api secret|secret key"
    r")\b",
    re.IGNORECASE,
)
GUARANTEE_RE = re.compile(
    r"\b("
    r"guarantee|guaranteed|promise|promises|guaranteeing|"
    r"more leads|more calls|more bookings|more patients|more revenue|"
    r"increase leads|increase bookings|increase revenue|grow by|increase by|boost by|"
    r"rank better|higher rankings?|seo rankings?|patients? growth|revenue growth"
    r")\b",
    re.IGNORECASE,
)
SECRET_RE = re.compile(
    r"\b("
    r"sk-[A-Za-z0-9]{10,}|pk_live_[A-Za-z0-9]{10,}|pk_test_[A-Za-z0-9]{10,}|"
    r"client_secret|refresh_token|webhook_secret|private_key|api_key|token=[A-Za-z0-9_-]{8,}"
    r")\b",
    re.IGNORECASE,
)


def _strip_allowed_references(text: str) -> str:
    sanitized = text
    for allowed in ALLOWED_PROSPECT_REFERENCES:
        sanitized = re.sub(re.escape(allowed), "", sanitized, flags=re.IGNORECASE)
    return sanitized


def _find_matches(pattern: re.Pattern[str], text: str) -> List[str]:
    matches = pattern.findall(text)
    return [match if isinstance(match, str) else "".join(match) for match in matches]


def prospect_copy_violations(*parts: str) -> List[str]:
    text = "\n".join(part for part in parts if part)
    if not text.strip():
        return []

    sanitized = _strip_allowed_references(text)
    violations: List[str] = []

    if STALE_BRAND_RE.search(sanitized):
        violations.append("stale Anvisco brand wording")
    if MANUAL_PAYMENT_RE.search(sanitized):
        violations.append("manual payment-link wording")
    if BACKEND_RE.search(sanitized):
        violations.append("backend-tool mention")
    if GUARANTEE_RE.search(sanitized):
        violations.append("guarantee claim")
    if SECRET_RE.search(sanitized):
        violations.append("secret-like token")

    return violations


def validate_prospect_copy(*parts: str) -> None:
    violations = prospect_copy_violations(*parts)
    if violations:
        joined = ", ".join(sorted(set(violations)))
        raise ValueError(f"Prospect copy safety validation failed: {joined}")
