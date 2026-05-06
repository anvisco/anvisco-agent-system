from __future__ import annotations

import os
import re
import ssl
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from notion_client import Client

from agents import generate_drafts_from_notion as draft_flow
from src.config import settings
from src.notion_client import get_data_source_schema, get_database_and_data_source


CASL_BACKFILL_DRY_RUN = os.getenv("CASL_BACKFILL_DRY_RUN", "true").strip().lower() in {"1", "true", "yes", "on"}
FORCE_CASL_BACKFILL = os.getenv("FORCE_CASL_BACKFILL", "false").strip().lower() in {"1", "true", "yes", "on"}


def _max_casl_backfill() -> int:
    raw_value = os.getenv("MAX_CASL_BACKFILL", "25")
    if not raw_value.strip():
        return 25
    try:
        return max(1, int(raw_value))
    except ValueError:
        return 25


MAX_CASL_BACKFILL = _max_casl_backfill()
CASL_BASIS_SAFE_VALUE = "conspicuously_published_business_email"
CASL_BASIS_MANUAL_VALUE = "manual_research_needed"
CASL_NOTE_SAFE = (
    "CASL Basis set by automated check: email found on public website/contact page, "
    "no no-solicitation language detected."
)
CASL_NOTE_MANUAL = "CASL basis needs manual review."

CASL_BASIS_CANDIDATES = draft_flow.CASL_BASIS_CANDIDATES
EMAIL_FIELD_CANDIDATES = draft_flow.EMAIL_FIELD_CANDIDATES
WEBSITE_FIELD_CANDIDATES = draft_flow.WEBSITE_CANDIDATES  # type: ignore[attr-defined]
CONTACT_PAGE_CANDIDATES = ("Contact Page URL", "Booking URL")
COUNTRY_CANDIDATES = draft_flow.COUNTRY_CANDIDATES  # type: ignore[attr-defined]
STATUS_FIELD_CANDIDATES = draft_flow.STATUS_FIELD_CANDIDATES
DUPLICATE_STATUS_CANDIDATES = draft_flow.DUPLICATE_STATUS_CANDIDATES
DO_NOT_CONTACT_CANDIDATES = draft_flow.DO_NOT_CONTACT_CANDIDATES
GMAIL_DRAFT_ID_CANDIDATES = draft_flow.GMAIL_DRAFT_ID_CANDIDATES
GMAIL_THREAD_ID_CANDIDATES = draft_flow.GMAIL_THREAD_ID_CANDIDATES
GMAIL_SENT_STATUS_CANDIDATES = draft_flow.GMAIL_SENT_STATUS_CANDIDATES
GMAIL_MATCH_STATUS_CANDIDATES = draft_flow.GMAIL_MATCH_STATUS_CANDIDATES
REDRAFT_MARKER_FIELDS = ("Last Redrafted At", "Redraft Status", "Email Redraft Status", "Notes", "Scrape Notes")
NOTE_FIELD_CANDIDATES = ("Notes", "Scrape Notes")
ALLOWED_DRAFT_READY_STATUSES = {"draft_ready", "outreach_drafted", "drafted", "email_1_drafted"}
BLOCKED_LEAD_STATUSES = {"not_fit", "archived", "paid_client"}
BLOCKED_DUPLICATE_STATUSES = {"duplicate", "possible_duplicate", "already_contacted", "do_not_contact"}
ALLOWED_GMAIL_MATCH_STATUSES = {"", "no_match", "draft_exists"}
NO_SOLICITATION_PHRASES = (
    "no solicitation",
    "no unsolicited",
    "do not solicit",
    "no marketing emails",
    "not for marketing",
)
BUSINESS_KEYWORDS = (
    "dental",
    "dentistry",
    "clinic",
    "orthodont",
    "implant",
    "cosmetic",
    "smile",
    "teeth",
    "tooth",
    "office",
    "patient",
    "family dentistry",
)
BUSINESS_LOCAL_HINTS = (
    "info",
    "hello",
    "contact",
    "office",
    "admin",
    "appointments",
    "appointment",
    "booking",
    "bookings",
    "reception",
    "frontdesk",
    "team",
    "support",
    "patients",
    "patient",
    "care",
    "clinic",
    "dental",
    "dentistry",
    "smile",
    "smiles",
    "mail",
    "hello",
)
FREE_EMAIL_DOMAINS = {
    "gmail.com",
    "yahoo.com",
    "hotmail.com",
    "outlook.com",
    "live.com",
    "aol.com",
    "icloud.com",
    "proton.me",
    "protonmail.com",
    "gmx.com",
    "mail.com",
}


def get_client() -> Client:
    if not settings.notion_api_key:
        raise ValueError("NOTION_API_KEY is missing.")
    return Client(auth=settings.notion_api_key)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _normalize_email(email: str) -> str:
    return str(email or "").strip().lower()


def _normalize_choice(text: str) -> str:
    normalized = _normalize_text(text)
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
    return normalized.strip("_")


def _first_existing_property_name(properties: Dict[str, Any], candidates: Sequence[str]) -> Optional[str]:
    for candidate in candidates:
        if candidate in properties:
            return candidate
    return None


def _get_property(lead: Dict[str, Any], name: str) -> Dict[str, Any]:
    return lead.get("properties", {}).get(name, {})


def _get_text_value(property_value: Dict[str, Any]) -> str:
    if "rich_text" in property_value and property_value["rich_text"]:
        return "".join(part.get("plain_text", "") for part in property_value["rich_text"]).strip()
    if "title" in property_value and property_value["title"]:
        return "".join(part.get("plain_text", "") for part in property_value["title"]).strip()
    if "email" in property_value and property_value["email"]:
        return str(property_value["email"]).strip()
    if "url" in property_value and property_value["url"]:
        return str(property_value["url"]).strip()
    if "select" in property_value and property_value["select"]:
        return str(property_value["select"].get("name", "")).strip()
    if "status" in property_value and property_value["status"]:
        return str(property_value["status"].get("name", "")).strip()
    if "checkbox" in property_value:
        return "true" if property_value["checkbox"] else "false"
    if "date" in property_value and property_value["date"]:
        return str(property_value["date"].get("start", "")).strip()
    return ""


def _property_update(property_type: str, value: Any) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    if property_type == "rich_text":
        return {"rich_text": [{"type": "text", "text": {"content": str(value)}}]}
    if property_type == "title":
        return {"title": [{"type": "text", "text": {"content": str(value)}}]}
    if property_type == "select":
        return {"select": {"name": str(value)}}
    if property_type == "status":
        return {"status": {"name": str(value)}}
    if property_type == "checkbox":
        return {"checkbox": bool(value)}
    if property_type == "date":
        return {"date": {"start": str(value)}}
    if property_type == "number":
        return {"number": value}
    if property_type == "url":
        return {"url": str(value)}
    if property_type == "email":
        return {"email": str(value)}
    return None


def _lead_name(lead: Dict[str, Any]) -> str:
    return draft_flow._get_lead_name(lead)  # type: ignore[attr-defined]


def _lead_email(lead: Dict[str, Any]) -> str:
    return draft_flow._lead_text_value(lead, list(EMAIL_FIELD_CANDIDATES))  # type: ignore[attr-defined]


def _lead_website(lead: Dict[str, Any]) -> str:
    return draft_flow._lead_text_value(lead, list(WEBSITE_FIELD_CANDIDATES))  # type: ignore[attr-defined]


def _lead_contact_page(lead: Dict[str, Any]) -> str:
    return draft_flow._lead_text_value(lead, list(CONTACT_PAGE_CANDIDATES))  # type: ignore[attr-defined]


def _lead_country(lead: Dict[str, Any]) -> str:
    return _normalize_text(draft_flow._lead_text_value(lead, list(COUNTRY_CANDIDATES)))  # type: ignore[attr-defined]


def _lead_do_not_contact(lead: Dict[str, Any]) -> bool:
    return draft_flow._lead_checkbox_true(lead, list(DO_NOT_CONTACT_CANDIDATES)) or _normalize_text(  # type: ignore[attr-defined]
        draft_flow._lead_text_value(lead, list(DO_NOT_CONTACT_CANDIDATES))  # type: ignore[attr-defined]
    ) in {"true", "yes", "1"}


def _lead_status(lead: Dict[str, Any]) -> str:
    return _normalize_choice(draft_flow._lead_text_value(lead, list(STATUS_FIELD_CANDIDATES)))  # type: ignore[attr-defined]


def _lead_duplicate_status(lead: Dict[str, Any]) -> str:
    return _normalize_choice(draft_flow._lead_text_value(lead, list(DUPLICATE_STATUS_CANDIDATES)))  # type: ignore[attr-defined]


def _lead_gmail_draft_id(lead: Dict[str, Any]) -> str:
    return draft_flow._lead_text_value(lead, list(GMAIL_DRAFT_ID_CANDIDATES))  # type: ignore[attr-defined]


def _lead_gmail_thread_id(lead: Dict[str, Any]) -> str:
    return draft_flow._lead_text_value(lead, list(GMAIL_THREAD_ID_CANDIDATES))  # type: ignore[attr-defined]


def _lead_gmail_sent_status(lead: Dict[str, Any]) -> str:
    return _normalize_choice(draft_flow._lead_text_value(lead, list(GMAIL_SENT_STATUS_CANDIDATES)))  # type: ignore[attr-defined]


def _lead_gmail_match_status(lead: Dict[str, Any]) -> str:
    return _normalize_choice(draft_flow._lead_text_value(lead, list(GMAIL_MATCH_STATUS_CANDIDATES)))  # type: ignore[attr-defined]


def _lead_casl_basis(lead: Dict[str, Any]) -> str:
    return draft_flow._lead_text_value(lead, list(CASL_BASIS_CANDIDATES))  # type: ignore[attr-defined]


def _lead_has_redraft_marker(lead: Dict[str, Any]) -> bool:
    properties = lead.get("properties", {})
    for field_name in REDRAFT_MARKER_FIELDS:
        if field_name not in properties:
            continue
        text = _normalize_text(_get_text_value(_get_property(lead, field_name)))
        if field_name == "Last Redrafted At" and text:
            return True
        if field_name in {"Redraft Status", "Email Redraft Status"} and text in {"redrafted", "redraft_complete", "completed", "done"}:
            return True
        if field_name in {"Notes", "Scrape Notes"} and "redrafted at:" in text:
            return True
    return False


def _lead_has_draft_support(lead: Dict[str, Any]) -> bool:
    if _lead_gmail_draft_id(lead):
        return True
    if _lead_has_redraft_marker(lead):
        return True
    status = _lead_status(lead)
    return status in ALLOWED_DRAFT_READY_STATUSES


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: List[str] = []

    def handle_data(self, data: str) -> None:
        if data:
            self._chunks.append(data)

    def get_text(self) -> str:
        return _normalize_text(unescape(" ".join(self._chunks)))


def _html_to_text(html: str) -> str:
    cleaned = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html)
    cleaned = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", cleaned)
    cleaned = re.sub(r"(?is)<!--.*?-->", " ", cleaned)
    extractor = _HTMLTextExtractor()
    try:
        extractor.feed(cleaned)
    except Exception:
        fallback = re.sub(r"(?is)<[^>]+>", " ", cleaned)
        return _normalize_text(unescape(fallback))
    return extractor.get_text()


def _normalize_url(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    if not raw.startswith(("http://", "https://")):
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))


def _base_domain(url: str) -> str:
    parsed = urlparse(_normalize_url(url))
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _fetch_url_text(url: str, timeout: int = 15) -> Tuple[str, str]:
    normalized_url = _normalize_url(url)
    if not normalized_url:
        raise ValueError("empty url")
    request = Request(
        normalized_url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; AnvisCASLBackfill/1.0)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    context = ssl.create_default_context()
    with urlopen(request, timeout=timeout, context=context) as response:
        raw = response.read()
        charset = "utf-8"
        content_type = response.headers.get_content_charset()
        if content_type:
            charset = content_type
        text = raw.decode(charset, errors="replace")
        return normalized_url, text


def _email_exact_in_text(email: str, text: str) -> bool:
    if not email or not text:
        return False
    return email.lower() in text.lower()


def _no_solicitation_hits(text: str) -> List[str]:
    normalized = text.lower()
    hits = [phrase for phrase in NO_SOLICITATION_PHRASES if phrase in normalized]
    return hits


def _email_context_snippet(text: str, email: str, window: int = 240) -> str:
    if not text or not email:
        return ""
    lower_text = text.lower()
    index = lower_text.find(email.lower())
    if index < 0:
        return ""
    start = max(0, index - window)
    end = min(len(text), index + len(email) + window)
    return _normalize_text(text[start:end])


def _lead_tokens(lead: Dict[str, Any]) -> List[str]:
    name = _lead_name(lead)
    tokens = re.findall(r"[a-z0-9]+", name.lower())
    stopwords = {"dr", "drs", "clinic", "dental", "dentistry", "care", "centre", "center", "family", "and", "the", "of", "at"}
    return [token for token in tokens if token not in stopwords and len(token) > 1]


def _email_business_related(email: str, lead: Dict[str, Any], page_text: str, page_url: str) -> Tuple[bool, str]:
    local_part, _, domain = email.partition("@")
    local = local_part.lower()
    domain = domain.lower()
    base_domain = _base_domain(page_url)
    generic_hint = any(local.startswith(prefix) for prefix in BUSINESS_LOCAL_HINTS)
    lead_tokens = _lead_tokens(lead)
    token_hint = any(token and token in local for token in lead_tokens)
    domain_hint = bool(base_domain and domain and (base_domain.endswith(domain) or domain.endswith(base_domain)))
    clinic_hint = any(keyword in page_text.lower() for keyword in BUSINESS_KEYWORDS)
    personal_style = bool(re.match(r"^[a-z]+[._-][a-z]+$", local))
    free_domain = domain in FREE_EMAIL_DOMAINS

    if generic_hint or token_hint:
        return True, "business mailbox pattern"
    if clinic_hint and domain_hint:
        return True, "clinic context and matching domain"
    if clinic_hint and not free_domain and not personal_style:
        return True, "clinic context on non-personal domain"
    if clinic_hint and domain_hint:
        return True, "clinic context and domain match"
    if free_domain and personal_style:
        return False, "personal-style address on free email domain"
    if not clinic_hint:
        return False, "page text does not clearly indicate a clinic/business page"
    return False, "email is not clearly business-related"


def _lead_supports_public_casl(lead: Dict[str, Any]) -> Tuple[bool, str]:
    email = _lead_email(lead)
    website = _lead_website(lead)
    contact_page = _lead_contact_page(lead)
    urls = [_normalize_url(value) for value in (contact_page, website) if value]
    if not email:
        return False, "Email is missing"
    if not website:
        return False, "Website is missing"
    if not _lead_has_draft_support(lead):
        return False, "No Gmail Draft ID, redraft marker, or draft-ready status"
    if _lead_country(lead) != "canada":
        return False, f"Country is {draft_flow._lead_text_value(lead, list(COUNTRY_CANDIDATES)) or '<empty>'}"  # type: ignore[attr-defined]
    if _lead_do_not_contact(lead):
        return False, "Do Not Contact is true"
    lead_status = _lead_status(lead)
    if lead_status in BLOCKED_LEAD_STATUSES:
        return False, f"Lead Status is {lead_status}"
    duplicate_status = _lead_duplicate_status(lead)
    if duplicate_status in BLOCKED_DUPLICATE_STATUSES:
        return False, f"Duplicate Status is {duplicate_status}"
    if not urls:
        return False, "Website URL and Contact Page URL are missing"
    return True, "passed hard filters"


def _casl_basis_property_info(schema_properties: Dict[str, Any]) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    field_name = _first_existing_property_name(schema_properties, CASL_BASIS_CANDIDATES)
    if not field_name:
        return None, None
    return field_name, schema_properties.get(field_name, {})


def _choice_supported(property_schema: Dict[str, Any], desired_value: str) -> bool:
    if not property_schema:
        return False
    prop_type = property_schema.get("type")
    if prop_type in {"rich_text", "title"}:
        return True
    if prop_type in {"select", "status"}:
        options = []
        if isinstance(property_schema.get(prop_type), dict):
            options = property_schema[prop_type].get("options", []) or []
        elif isinstance(property_schema.get("options"), list):
            options = property_schema.get("options", [])
        if not options:
            return True
        normalized_desired = _normalize_choice(desired_value)
        for option in options:
            if _normalize_choice(option.get("name", "")) == normalized_desired:
                return True
        return False
    return False


def _casl_basis_update(schema_properties: Dict[str, Any], lead: Dict[str, Any], desired_value: str) -> Tuple[Dict[str, Any], str]:
    field_name, field_schema = _casl_basis_property_info(schema_properties)
    if not field_name or not field_schema:
        return {}, ""
    if not FORCE_CASL_BACKFILL and _get_text_value(_get_property(lead, field_name)):
        return {}, field_name
    if not _choice_supported(field_schema, desired_value):
        return {}, field_name
    update_value = _property_update(field_schema.get("type"), desired_value)
    return ({field_name: update_value} if update_value else {}), field_name


def _append_note_update(schema_properties: Dict[str, Any], lead: Dict[str, Any], note: str) -> Dict[str, Any]:
    if not note:
        return {}
    for field_name in NOTE_FIELD_CANDIDATES:
        if field_name not in schema_properties:
            continue
        existing = _get_text_value(_get_property(lead, field_name))
        if note.lower() in existing.lower():
            return {}
        combined = f"{existing}\n{note}".strip() if existing else note
        update_value = _property_update(schema_properties[field_name].get("type"), combined)
        if update_value:
            return {field_name: update_value}
    return {}


@dataclass
class CandidateDecision:
    lead: Dict[str, Any]
    classification: str
    reasons: List[str]
    evidence: str = ""
    basis_field: str = ""
    note_field: str = ""
    website_url: str = ""


def _manual_research_supported(schema_properties: Dict[str, Any]) -> bool:
    field_name, field_schema = _casl_basis_property_info(schema_properties)
    if not field_name or not field_schema:
        return False
    return _choice_supported(field_schema, CASL_BASIS_MANUAL_VALUE)


def _query_all_leads() -> List[Dict[str, Any]]:
    client = get_client()
    _, data_source_id = get_database_and_data_source()
    leads: List[Dict[str, Any]] = []
    next_cursor: Optional[str] = None
    while True:
        kwargs: Dict[str, Any] = {"data_source_id": data_source_id, "page_size": 100}
        if next_cursor:
            kwargs["start_cursor"] = next_cursor
        response = client.data_sources.query(**kwargs)
        leads.extend(response.get("results", []))
        if not response.get("has_more"):
            break
        next_cursor = response.get("next_cursor")
        if not next_cursor:
            break
    return leads


def _fetch_evidence_pages(lead: Dict[str, Any]) -> List[Tuple[str, str]]:
    pages: List[Tuple[str, str]] = []
    for raw_url in (_lead_contact_page(lead), _lead_website(lead)):
        normalized_url = _normalize_url(raw_url)
        if not normalized_url:
            continue
        if any(existing_url == normalized_url for existing_url, _ in pages):
            continue
        try:
            fetched_url, html = _fetch_url_text(normalized_url)
            pages.append((fetched_url, _html_to_text(html)))
        except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
            pages.append((normalized_url, f"ERROR: {exc}"))
    return pages


def _score_candidate(lead: Dict[str, Any], schema_properties: Dict[str, Any]) -> CandidateDecision:
    reasons: List[str] = []
    email = _normalize_email(_lead_email(lead))
    website = _lead_website(lead)
    if not email:
        reasons.append("Email is missing")
    if not website:
        reasons.append("Website is missing")
    if not _lead_has_draft_support(lead):
        reasons.append("No Gmail Draft ID, redraft marker, or draft-ready status")
    if _lead_country(lead) != "canada":
        reasons.append(f"Country is {draft_flow._lead_text_value(lead, list(COUNTRY_CANDIDATES)) or '<empty>'}")  # type: ignore[attr-defined]
    if _lead_do_not_contact(lead):
        reasons.append("Do Not Contact is true")
    lead_status = _lead_status(lead)
    if lead_status in BLOCKED_LEAD_STATUSES:
        reasons.append(f"Lead Status is {lead_status}")
    duplicate_status = _lead_duplicate_status(lead)
    if duplicate_status in BLOCKED_DUPLICATE_STATUSES:
        reasons.append(f"Duplicate Status is {duplicate_status}")

    basis_value = _lead_casl_basis(lead)
    if basis_value and not FORCE_CASL_BACKFILL:
        reasons.append("CASL Basis is already set")

    if reasons:
        return CandidateDecision(lead=lead, classification="skip", reasons=reasons)

    pages = _fetch_evidence_pages(lead)
    if not pages:
        reasons.append("Website fetch failed")
        return CandidateDecision(lead=lead, classification="manual", reasons=reasons)

    exact_email_found = False
    solicitation_hits: List[str] = []
    business_related = False
    evidence_notes: List[str] = []
    for page_url, page_text in pages:
        if not page_text or page_text.startswith("ERROR:"):
            evidence_notes.append(f"{page_url}: fetch failed")
            continue
        if _email_exact_in_text(email, page_text):
            exact_email_found = True
            snippet = _email_context_snippet(page_text, email)
            if snippet:
                evidence_notes.append(f"{page_url}: email snippet {snippet[:180]}")
            hits = _no_solicitation_hits(page_text)
            if hits:
                solicitation_hits.extend(hits)
            related, related_reason = _email_business_related(email, lead, page_text, page_url)
            business_related = business_related or related
            if related_reason:
                evidence_notes.append(f"{page_url}: {related_reason}")
        else:
            evidence_notes.append(f"{page_url}: email not found")

    if not exact_email_found:
        reasons.append("Email was not found on the public website/contact page")
    if solicitation_hits:
        unique_hits = sorted(set(solicitation_hits))
        reasons.append(f"No-solicitation language detected ({', '.join(unique_hits)})")
    if not business_related:
        reasons.append("Email is not clearly business-related")

    if exact_email_found and not solicitation_hits and business_related:
        return CandidateDecision(
            lead=lead,
            classification="safe",
            reasons=[],
            evidence="; ".join(evidence_notes[:4]),
            website_url=website,
        )

    if reasons:
        return CandidateDecision(
            lead=lead,
            classification="manual",
            reasons=reasons,
            evidence="; ".join(evidence_notes[:4]),
            website_url=website,
        )

    return CandidateDecision(
        lead=lead,
        classification="manual",
        reasons=["CASL basis needs manual review"],
        evidence="; ".join(evidence_notes[:4]),
        website_url=website,
    )


def _print_header() -> None:
    print("CASL backfill gate:")
    print(f"- CASL_BACKFILL_DRY_RUN: {'yes' if CASL_BACKFILL_DRY_RUN else 'no'}")
    print(f"- FORCE_CASL_BACKFILL: {'yes' if FORCE_CASL_BACKFILL else 'no'}")
    print(f"- MAX_CASL_BACKFILL: {MAX_CASL_BACKFILL}")
    print(f"- Gmail send-as alias: {settings.gmail_send_as_email}")


def _record_summary_reason(summary: Dict[str, int], reason: str) -> None:
    summary[reason] = summary.get(reason, 0) + 1


def main() -> None:
    schema = get_data_source_schema()
    schema_properties = schema.get("properties", {})
    leads = _query_all_leads()

    _print_header()
    print(f"Loaded Notion records: {len(leads)}")

    summary: Dict[str, int] = {
        "records_checked": 0,
        "candidates": 0,
        "would_set_conspicuously_published_business_email": 0,
        "would_set_manual_research_needed": 0,
        "manual_note_only": 0,
        "updated": 0,
        "notes_written": 0,
        "skipped_existing_basis": 0,
        "skipped_not_canada": 0,
        "skipped_dnc": 0,
        "skipped_duplicate": 0,
        "skipped_missing_email": 0,
        "skipped_missing_website": 0,
        "skipped_missing_support": 0,
        "skipped_fetch_error": 0,
        "errors": 0,
    }
    skip_log_limit = 12
    skip_logs: List[str] = []
    decisions: List[CandidateDecision] = []

    for lead in leads:
        summary["records_checked"] += 1
        decision = _score_candidate(lead, schema_properties)
        if decision.classification == "skip":
            reason_text = ", ".join(decision.reasons) if decision.reasons else "skipped"
            if "CASL Basis is already set" in reason_text:
                summary["skipped_existing_basis"] += 1
            elif "Country is" in reason_text and "Canada" not in reason_text:
                summary["skipped_not_canada"] += 1
            elif "Do Not Contact" in reason_text:
                summary["skipped_dnc"] += 1
            elif "Duplicate Status" in reason_text:
                summary["skipped_duplicate"] += 1
            elif "Email is missing" in reason_text:
                summary["skipped_missing_email"] += 1
            elif "Website is missing" in reason_text:
                summary["skipped_missing_website"] += 1
            elif "No Gmail Draft ID, redraft marker, or draft-ready status" in reason_text:
                summary["skipped_missing_support"] += 1
            elif "fetch failed" in reason_text.lower():
                summary["skipped_fetch_error"] += 1
            if len(skip_logs) < skip_log_limit:
                skip_logs.append(f"SKIP | {_lead_name(lead)} | {reason_text}")
            continue

        summary["candidates"] += 1
        decisions.append(decision)

    selected = decisions[:MAX_CASL_BACKFILL]
    print(f"Candidates with empty CASL Basis: {len(decisions)}")
    print(f"Selected for processing: {len(selected)}")

    for decision in selected:
        lead = decision.lead
        lead_name = _lead_name(lead)
        email = _normalize_email(_lead_email(lead))
        draft_id = _lead_gmail_draft_id(lead)
        if decision.classification == "safe":
            summary["would_set_conspicuously_published_business_email"] += 1
            print(
                f"WOULD SET | conspicuously_published_business_email | {lead_name} | "
                f"Email: {email} | Draft ID: {draft_id or '<missing>'} | {decision.evidence or '<no evidence>'}"
            )
        else:
            summary["would_set_manual_research_needed"] += 1
            if _manual_research_supported(schema_properties):
                print(
                    f"WOULD SET | manual_research_needed | {lead_name} | "
                    f"Email: {email} | Draft ID: {draft_id or '<missing>'} | {decision.evidence or '<no evidence>'}"
                )
            else:
                summary["manual_note_only"] += 1
                print(
                    f"WOULD NOTE | manual review only | {lead_name} | "
                    f"Email: {email} | Draft ID: {draft_id or '<missing>'} | {decision.evidence or '<no evidence>'}"
                )

    if CASL_BACKFILL_DRY_RUN:
        print("Dry run only. No Notion records were updated.")
    else:
        client = get_client()
        for decision in selected:
            lead = decision.lead
            lead_name = _lead_name(lead)
            email = _normalize_email(_lead_email(lead))
            basis_value = CASL_BASIS_SAFE_VALUE if decision.classification == "safe" else CASL_BASIS_MANUAL_VALUE
            basis_update, basis_field = _casl_basis_update(schema_properties, lead, basis_value)
            note_text = CASL_NOTE_SAFE if decision.classification == "safe" else CASL_NOTE_MANUAL
            note_update = _append_note_update(schema_properties, lead, note_text)

            try:
                if basis_update:
                    client.pages.update(page_id=lead["id"], properties=basis_update)
                    summary["updated"] += 1
                    print(f"UPDATED | {lead_name} | {basis_field} -> {basis_value}")
                elif basis_field:
                    print(f"SKIP | {lead_name} | CASL Basis field exists but could not safely set {basis_value}")
                else:
                    print(f"SKIP | {lead_name} | CASL Basis field missing")

                if note_update:
                    client.pages.update(page_id=lead["id"], properties=note_update)
                    summary["notes_written"] += 1
                    print(f"NOTE | {lead_name} | {note_text}")
            except Exception as exc:
                summary["errors"] += 1
                print(f"ERROR | {lead_name} | Email: {email} | {exc}")

    print("CASL backfill summary:")
    for key in (
        "records_checked",
        "candidates",
        "would_set_conspicuously_published_business_email",
        "would_set_manual_research_needed",
        "manual_note_only",
        "updated",
        "notes_written",
        "skipped_existing_basis",
        "skipped_not_canada",
        "skipped_dnc",
        "skipped_duplicate",
        "skipped_missing_email",
        "skipped_missing_website",
        "skipped_missing_support",
        "skipped_fetch_error",
        "errors",
    ):
        print(f"- {key}: {summary.get(key, 0)}")
    if skip_logs:
        print("Skipped records:")
        for line in skip_logs:
            print(f"- {line}")


if __name__ == "__main__":
    main()
