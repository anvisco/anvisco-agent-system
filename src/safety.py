from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


ALLOWED_COPY_EXCEPTIONS = (
    "anvisco.com",
    "brian@anvisco.com",
)

STALE_BRAND_PATTERN = re.compile(r"\bAnvisco\b", re.IGNORECASE)
MANUAL_PAYMENT_PATTERN = re.compile(
    r"\b(manual payment(?:s)?(?: link(?:s)?)?|payment link(?:s)?|stripe payment links?)\b",
    re.IGNORECASE,
)
BACKEND_TOOL_PATTERN = re.compile(
    r"\b("
    r"supabase|stripe|resend|cloudflare|gmail|notion|webhook|back-end|backend|"
    r"api secret|api key|client secret|refresh token|database|portal internals|magic link|"
    r"secret(?:s)?|credential(?:s)?|token(?:s)?"
    r")\b",
    re.IGNORECASE,
)
GUARANTEE_PATTERN = re.compile(
    r"\b(guarantee(?:d|s|ing)?|promise(?:d|s|ing)?|promised)\b",
    re.IGNORECASE,
)
GUARANTEE_TARGET_PATTERN = re.compile(
    r"\b(leads?|bookings?|revenue|seo rankings?|rankings?|patient growth)\b",
    re.IGNORECASE,
)
SECRET_LEAK_PATTERN = re.compile(
    r"("
    r"\bsk-[A-Za-z0-9_-]{10,}\b|"
    r"\bpk_(?:live|test)_[A-Za-z0-9_-]{10,}\b|"
    r"\bclient[_ -]?secret\b|"
    r"\brefresh[_ -]?token\b|"
    r"\bwebhook[_ -]?secret\b|"
    r"\bapi[_ -]?key\b|"
    r"\bprivate[_ -]?key\b"
    r")",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SafetyViolation:
    rule: str
    detail: str


def _mask_allowed_exceptions(text: str) -> str:
    masked = text
    for token in ALLOWED_COPY_EXCEPTIONS:
        masked = re.sub(re.escape(token), " " * len(token), masked, flags=re.IGNORECASE)
    return masked


def validate_prospect_copy(texts: Iterable[str], *, context: str = "prospect copy") -> None:
    text = "\n".join(part for part in texts if part)
    if not text:
        return

    masked = _mask_allowed_exceptions(text)
    violations: list[SafetyViolation] = []

    if STALE_BRAND_PATTERN.search(masked):
        violations.append(SafetyViolation("brand", "stale Anvisco brand wording is not allowed in prospect-facing copy."))
    if MANUAL_PAYMENT_PATTERN.search(masked):
        violations.append(SafetyViolation("payment", "manual payment-link wording is not allowed in prospect-facing copy."))
    if BACKEND_TOOL_PATTERN.search(masked):
        violations.append(SafetyViolation("backend", "backend tool names are not allowed in prospect-facing copy."))
    if GUARANTEE_PATTERN.search(masked) and GUARANTEE_TARGET_PATTERN.search(masked):
        violations.append(SafetyViolation("guarantee", "guaranteed outcomes are not allowed in prospect-facing copy."))
    if SECRET_LEAK_PATTERN.search(masked):
        violations.append(SafetyViolation("secrets", "secret-like tokens or credential patterns are not allowed in prospect-facing copy."))

    if violations:
        details = "; ".join(f"{item.rule}: {item.detail}" for item in violations)
        raise ValueError(f"Safety validation failed for {context}: {details}")
