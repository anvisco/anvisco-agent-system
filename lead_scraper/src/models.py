from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FoundLead:
    google_place_id: str
    business_name: str
    website: str
    phone: str = ""
    address: str = ""
    city: str = ""
    rating: Optional[float] = None
    review_count: Optional[int] = None
    google_maps_url: str = ""
    source: str = "Google Places"


@dataclass
class ScrapedWebsite:
    website_url: str
    domain: str
    email: str = ""
    phone: str = ""
    contact_page_url: str = ""
    booking_url: str = ""
    business_name: str = ""
    dentist_or_owner_name: str = ""
    services: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    social_links: list[str] = field(default_factory=list)
    website_status: str = "unknown"
    https_active: bool = False
    mobile_friendly: str = "unknown"
    pagespeed_score: Optional[int] = None
    found_emails: list[str] = field(default_factory=list)
    technical_notes: list[str] = field(default_factory=list)
    issue_signals: list[str] = field(default_factory=list)


@dataclass
class AuditedLead:
    google_place_id: str
    business_name: str
    niche: str
    city: str
    website: str
    domain: str
    email: str
    phone: str
    address: str
    google_maps_url: str
    rating: Optional[float]
    review_count: Optional[int]
    top_issue: str
    outreach_angle: str
    angle_bucket: str
    recommended_offer: str
    lead_quality_score: int
    website_status: str
    source: str
    scrape_notes: str
    contact_name: str = ""
    website_url: str = ""
    industry: str = ""
    location: str = ""
    lead_source: str = ""
    lead_status: str = ""
    audit_status: str = ""
    outreach_status: str = ""
    intent_level: str = ""
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    contact_page_url: str = ""
    booking_url: str = ""
    languages: str = ""
    services: str = ""
    top_3_issues: list[str] = field(default_factory=list)
    business_impact: str = ""
    recommended_fix: str = ""
    email_angle: str = ""
    loom_script: str = ""
