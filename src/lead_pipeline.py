from __future__ import annotations

from typing import Iterable

PIPELINE_STATUSES = (
    "new",
    "researching",
    "audit_ready",
    "outreach_drafted",
    "outreach_sent",
    "replied",
    "booked_call",
    "checkout_sent",
    "paid_client",
    "not_fit",
    "archived",
)

STATUS_ALIASES = {
    "new lead": "audit_ready",
    "draft ready": "outreach_drafted",
    "email 1 drafted": "outreach_drafted",
    "email 1 sent": "outreach_sent",
    "email 2 sent": "outreach_sent",
    "replied": "replied",
    "call booked": "booked_call",
    "checkout sent": "checkout_sent",
    "not interested": "not_fit",
    "do not contact": "not_fit",
    "no response": "archived",
    "closed": "archived",
}

DRAFT_READY_STATUSES = ("audit_ready", "outreach_drafted")
ACTIVE_OUTREACH_STATUSES = ("outreach_sent",)
STOPPED_STATUSES = ("replied", "booked_call", "checkout_sent", "paid_client", "not_fit", "archived")
REPLY_MARKED_STATUSES = ("replied",)

LEAD_FIELD_CANDIDATES = {
    "business_name": ("Business Name", "Practice Name", "Clinic Name", "Name"),
    "contact_name": ("Contact Name", "Primary Contact", "Owner Name", "Dentist Name"),
    "email": ("Email", "Contact Email"),
    "phone": ("Phone", "Contact Phone"),
    "website_url": ("Website URL", "Website"),
    "industry": ("Industry", "Niche"),
    "location": ("Location", "City"),
    "lead_source": ("Lead Source", "Source"),
    "lead_status": ("Lead Status", "Outreach Status"),
    "audit_status": ("Audit Status",),
    "outreach_status": ("Outreach Status",),
    "intent_level": ("Intent Level",),
    "recommended_offer": ("Recommended Offer",),
    "notes": ("Notes", "Scrape Notes"),
    "created_at": ("Created At", "Created Time"),
    "updated_at": ("Updated At", "Last Edited Time", "Last Scraped Date"),
}


def normalize_status(value: str | None) -> str:
    if not value:
        return ""
    cleaned = " ".join(value.strip().lower().replace("-", " ").split())
    return STATUS_ALIASES.get(cleaned, cleaned.replace(" ", "_"))


def status_matches(value: str | None, *expected: str) -> bool:
    normalized_value = normalize_status(value)
    if not normalized_value:
        return False
    normalized_expected = {normalize_status(item) for item in expected}
    return normalized_value in normalized_expected


def status_in_any(value: str | None, statuses: Iterable[str]) -> bool:
    return status_matches(value, *tuple(statuses))


def intent_level_from_score(score: int) -> str:
    if score >= 5:
        return "high"
    if score >= 3:
        return "medium"
    return "low"
