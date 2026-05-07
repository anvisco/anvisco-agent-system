from __future__ import annotations

import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from email.utils import getaddresses, parseaddr
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from notion_client import Client
from googleapiclient.errors import HttpError

from agents import generate_drafts_from_notion as draft_flow
from src.config import settings
from src.gmail_client import (
    apply_label_to_message,
    extract_draft_details,
    get_draft,
    get_preferred_send_as_email,
    send_draft,
)
from src.notion_client import get_data_source_schema, get_database_and_data_source
from src.safety import validate_prospect_copy


SEND_DRY_RUN = os.getenv("SEND_DRY_RUN", "true").strip().lower() in {"1", "true", "yes", "on"}
SEND_APPROVED_DRAFTS = os.getenv("SEND_APPROVED_DRAFTS", "false").strip().lower() in {"1", "true", "yes", "on"}
ALLOW_RULE_BASED_APPROVAL = os.getenv("ALLOW_RULE_BASED_APPROVAL", "false").strip().lower() in {"1", "true", "yes", "on"}
ALLOW_LEGACY_STATUS_FALLBACK = os.getenv("ALLOW_LEGACY_STATUS_FALLBACK", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
SEND_OPS_DIAGNOSTIC_SCAN = os.getenv("SEND_OPS_DIAGNOSTIC_SCAN", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


_UNLIMITED_MAX_SENDS_VALUES = {"", "none", "unlimited", "0"}


def _max_sends_per_run() -> Optional[int]:
    raw_value = os.getenv("MAX_SENDS_PER_RUN", "").strip()
    if raw_value.lower() in _UNLIMITED_MAX_SENDS_VALUES:
        return None
    try:
        n = int(raw_value)
        return None if n <= 0 else n
    except ValueError:
        print(f"Invalid MAX_SENDS_PER_RUN value: {raw_value}")
        sys.exit(1)


MAX_SENDS_PER_RUN: Optional[int] = _max_sends_per_run()
_VERIFIED_SEND_AS_EMAIL: Optional[str] = None


def _verified_send_as_email() -> str:
    global _VERIFIED_SEND_AS_EMAIL
    if _VERIFIED_SEND_AS_EMAIL is None:
        _VERIFIED_SEND_AS_EMAIL = get_preferred_send_as_email(settings.gmail_send_as_email)
    return _VERIFIED_SEND_AS_EMAIL


NAME_FIELD_CANDIDATES = draft_flow.NAME_FIELD_CANDIDATES
EMAIL_FIELD_CANDIDATES = draft_flow.EMAIL_FIELD_CANDIDATES
DO_NOT_CONTACT_CANDIDATES = draft_flow.DO_NOT_CONTACT_CANDIDATES
OPS_STATUS_CANDIDATES = getattr(draft_flow, "OPS_STATUS_CANDIDATES", ["Ops Status"])
STATUS_FIELD_CANDIDATES = draft_flow.STATUS_FIELD_CANDIDATES
DUPLICATE_STATUS_CANDIDATES = draft_flow.DUPLICATE_STATUS_CANDIDATES
GMAIL_DRAFT_ID_CANDIDATES = draft_flow.GMAIL_DRAFT_ID_CANDIDATES
GMAIL_THREAD_ID_CANDIDATES = draft_flow.GMAIL_THREAD_ID_CANDIDATES
GMAIL_MATCH_STATUS_CANDIDATES = draft_flow.GMAIL_MATCH_STATUS_CANDIDATES
GMAIL_SENT_STATUS_CANDIDATES = draft_flow.GMAIL_SENT_STATUS_CANDIDATES
ADMIN_APPROVED_CANDIDATES = draft_flow.ADMIN_APPROVED_CANDIDATES
CASL_BASIS_CANDIDATES = draft_flow.CASL_BASIS_CANDIDATES
SEND_MODE_CANDIDATES = draft_flow.SEND_MODE_CANDIDATES
SEQUENCE_STEP_CANDIDATES = draft_flow.SEQUENCE_STEP_CANDIDATES
LAST_EMAIL_SENT_AT_CANDIDATES = draft_flow.LAST_EMAIL_SENT_AT_CANDIDATES
LAST_OUTREACH_DATE_CANDIDATES = draft_flow.LAST_OUTREACH_DATE_CANDIDATES
NEXT_FOLLOW_UP_DATE_CANDIDATES = draft_flow.NEXT_FOLLOW_UP_DATE_CANDIDATES
SCHEDULED_SEND_DATE_CANDIDATES = getattr(draft_flow, "SCHEDULED_SEND_DATE_CANDIDATES", ["Scheduled Send Date"])

BLOCKED_LEAD_STATUSES = {"not_fit", "archived", "paid_client"}
BLOCKED_DUPLICATE_STATUSES = {"duplicate", "possible_duplicate", "already_contacted", "do_not_contact"}
BLOCKED_GMAIL_MATCH_STATUSES = {"sent_exists", "replied"}
BLOCKED_GMAIL_SENT_STATUSES = {"sent"}
OPS_READY_TO_SEND = "ready_to_send"
REQUIRED_SEND_MODE = "auto_send_gated"

# Follow-up scheduling: business days to wait after each email before drafting the next.
FOLLOWUP_DELAY_AFTER_EMAIL_1_BUSINESS_DAYS = 3
FOLLOWUP_DELAY_AFTER_EMAIL_2_BUSINESS_DAYS = 5
REQUIRED_OUTREACH_STATUS = "Email 1 Sent"
REQUIRED_LEAD_STATUS = "outreach_sent"
REQUIRED_GMAIL_MATCH_STATUS = "sent_exists"
REQUIRED_GMAIL_SENT_STATUS = "sent"
RULE_APPROVAL_ALLOWED_SEND_MODES = {"auto_draft", "auto_send_gated"}
RULE_APPROVAL_ALLOWED_CASL_BASIS = {
    "conspicuously_published_business_email",
    "existing_business_relationship",
    "referral_or_intro",
}
RULE_APPROVAL_ALLOWED_DUPLICATE_STATUS = {"", "unique"}
RULE_APPROVAL_ALLOWED_GMAIL_MATCH_STATUS = {"", "no_match", "draft_exists"}


def get_client() -> Client:
    if not settings.notion_api_key:
        raise ValueError("NOTION_API_KEY is missing.")
    return Client(auth=settings.notion_api_key)


def _normalize_text(text: str) -> str:
    return " ".join(str(text or "").split()).strip().lower()


def _normalize_choice(text: str) -> str:
    normalized = _normalize_text(text)
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
    return normalized.strip("_")


def _first_existing_property_name(properties: Dict[str, Any], candidates: Sequence[str]) -> Optional[str]:
    for candidate in candidates:
        if candidate in properties:
            return candidate
    return None


def _lead_property_text(lead: Dict[str, Any], candidates: Sequence[str]) -> str:
    return draft_flow._lead_text_value(lead, list(candidates))  # type: ignore[attr-defined]


def _lead_checkbox_true(lead: Dict[str, Any], candidates: Sequence[str]) -> bool:
    return draft_flow._lead_checkbox_true(lead, list(candidates))  # type: ignore[attr-defined]


def _lead_name(lead: Dict[str, Any]) -> str:
    return draft_flow._get_lead_name(lead)  # type: ignore[attr-defined]


def _lead_email(lead: Dict[str, Any]) -> str:
    return _lead_property_text(lead, EMAIL_FIELD_CANDIDATES)


def _lead_send_mode(lead: Dict[str, Any]) -> str:
    return _lead_property_text(lead, SEND_MODE_CANDIDATES)


def _lead_ops_status(lead: Dict[str, Any]) -> str:
    return _normalize_choice(_lead_property_text(lead, OPS_STATUS_CANDIDATES))


def _lead_status(lead: Dict[str, Any]) -> str:
    return _normalize_text(_lead_property_text(lead, STATUS_FIELD_CANDIDATES))


def _lead_duplicate_status(lead: Dict[str, Any]) -> str:
    return _normalize_text(_lead_property_text(lead, DUPLICATE_STATUS_CANDIDATES))


def _lead_gmail_match_status(lead: Dict[str, Any]) -> str:
    return _normalize_text(_lead_property_text(lead, GMAIL_MATCH_STATUS_CANDIDATES))


def _lead_gmail_sent_status(lead: Dict[str, Any]) -> str:
    return _normalize_text(_lead_property_text(lead, GMAIL_SENT_STATUS_CANDIDATES))


def _lead_gmail_draft_id(lead: Dict[str, Any]) -> str:
    return _lead_property_text(lead, GMAIL_DRAFT_ID_CANDIDATES)


def _lead_thread_id(lead: Dict[str, Any]) -> str:
    return _lead_property_text(lead, GMAIL_THREAD_ID_CANDIDATES)


def _lead_casl_basis(lead: Dict[str, Any]) -> str:
    return _lead_property_text(lead, CASL_BASIS_CANDIDATES)


def _lead_admin_approved(lead: Dict[str, Any]) -> bool:
    return _lead_checkbox_true(lead, ADMIN_APPROVED_CANDIDATES) or _normalize_text(
        _lead_property_text(lead, ADMIN_APPROVED_CANDIDATES)
    ) in {"true", "yes", "approved", "1"}


def _lead_website(lead: Dict[str, Any]) -> str:
    return _lead_property_text(lead, draft_flow.WEBSITE_CANDIDATES)  # type: ignore[attr-defined]


def _lead_scheduled_send_date(lead: Dict[str, Any]) -> str:
    return _lead_property_text(lead, SCHEDULED_SEND_DATE_CANDIDATES)


def _lead_sequence_step(lead: Dict[str, Any]) -> str:
    return _lead_property_text(lead, SEQUENCE_STEP_CANDIDATES)


def _lead_country(lead: Dict[str, Any]) -> str:
    return _normalize_text(draft_flow._lead_text_value(lead, draft_flow.COUNTRY_CANDIDATES))  # type: ignore[attr-defined]


def _lead_do_not_contact(lead: Dict[str, Any]) -> bool:
    return _lead_checkbox_true(lead, DO_NOT_CONTACT_CANDIDATES) or _normalize_text(
        _lead_property_text(lead, DO_NOT_CONTACT_CANDIDATES)
    ) in {"true", "yes", "1"}


def _lead_approval_path(lead: Dict[str, Any]) -> str:
    if _lead_admin_approved(lead):
        return "admin"
    if ALLOW_RULE_BASED_APPROVAL:
        return "rule"
    return ""


def _rule_based_approval_block_reasons(lead: Dict[str, Any]) -> List[str]:
    reasons: List[str] = []

    send_mode = _normalize_choice(_lead_send_mode(lead))
    if send_mode not in RULE_APPROVAL_ALLOWED_SEND_MODES:
        reasons.append(f"Send Mode is {send_mode or '<empty>'}")

    if _lead_country(lead) != "canada":
        country = draft_flow._lead_text_value(lead, draft_flow.COUNTRY_CANDIDATES)  # type: ignore[attr-defined]
        reasons.append(f"Country is {country or '<empty>'}")

    if not _lead_email(lead):
        reasons.append("Email is missing")

    if not _lead_website(lead):
        reasons.append("Website is missing")

    if not _lead_gmail_draft_id(lead):
        reasons.append("Gmail Draft ID is missing")

    casl_basis = _normalize_choice(_lead_casl_basis(lead))
    if casl_basis not in RULE_APPROVAL_ALLOWED_CASL_BASIS:
        reasons.append(f"CASL Basis is {casl_basis or '<empty>'}")

    if _lead_do_not_contact(lead):
        reasons.append("Do Not Contact is true")

    duplicate_status = _normalize_choice(_lead_duplicate_status(lead))
    if duplicate_status not in RULE_APPROVAL_ALLOWED_DUPLICATE_STATUS:
        reasons.append(f"Duplicate Status is {duplicate_status}")

    gmail_match_status = _normalize_choice(_lead_gmail_match_status(lead))
    if gmail_match_status not in RULE_APPROVAL_ALLOWED_GMAIL_MATCH_STATUS:
        reasons.append(f"Gmail Match Status is {gmail_match_status}")

    gmail_sent_status = _lead_gmail_sent_status(lead)
    if gmail_sent_status in BLOCKED_GMAIL_SENT_STATUSES:
        reasons.append(f"Gmail Sent Status is {gmail_sent_status}")

    lead_status = _lead_status(lead)
    if lead_status in BLOCKED_LEAD_STATUSES:
        reasons.append(f"Lead Status is {lead_status}")

    if not _verified_send_as_email():
        reasons.append(f"sender alias {settings.gmail_send_as_email} is not verified")

    return reasons


def _ops_send_safety_block_reasons(lead: Dict[str, Any]) -> List[str]:
    reasons: List[str] = []

    if _lead_country(lead) != "canada":
        country = draft_flow._lead_text_value(lead, draft_flow.COUNTRY_CANDIDATES)  # type: ignore[attr-defined]
        reasons.append(f"Country is {country or '<empty>'}")

    if not _lead_email(lead):
        reasons.append("Email is missing")

    if not _lead_website(lead):
        reasons.append("Website is missing")

    if not _lead_gmail_draft_id(lead):
        reasons.append("Gmail Draft ID is missing")

    casl_basis = _normalize_choice(_lead_casl_basis(lead))
    if casl_basis not in RULE_APPROVAL_ALLOWED_CASL_BASIS:
        reasons.append(f"CASL Basis is {casl_basis or '<empty>'}")

    if _lead_do_not_contact(lead):
        reasons.append("Do Not Contact is true")

    duplicate_status = _normalize_choice(_lead_duplicate_status(lead))
    if duplicate_status in BLOCKED_DUPLICATE_STATUSES:
        reasons.append(f"Duplicate Status is {duplicate_status}")

    gmail_sent_status = _lead_gmail_sent_status(lead)
    if gmail_sent_status in BLOCKED_GMAIL_SENT_STATUSES:
        reasons.append(f"Gmail Sent Status is {gmail_sent_status}")

    gmail_match_status = _normalize_choice(_lead_gmail_match_status(lead))
    if gmail_match_status in BLOCKED_GMAIL_MATCH_STATUSES:
        reasons.append(f"Gmail Match Status is {gmail_match_status}")

    lead_status = _lead_status(lead)
    if lead_status in BLOCKED_LEAD_STATUSES:
        reasons.append(f"Lead Status is {lead_status}")

    if not _verified_send_as_email():
        reasons.append(f"sender alias {settings.gmail_send_as_email} is not verified")

    return reasons


def _lead_send_block_reasons(lead: Dict[str, Any]) -> List[str]:
    reasons: List[str] = []
    if _lead_approval_path(lead) == "admin":
        send_mode = _lead_send_mode(lead)
        if send_mode != REQUIRED_SEND_MODE:
            reasons.append(f"Send Mode is {send_mode or '<empty>'}")

        if _lead_country(lead) != "canada":
            country = draft_flow._lead_text_value(lead, draft_flow.COUNTRY_CANDIDATES)  # type: ignore[attr-defined]
            reasons.append(f"Country is {country or '<empty>'}")

        if _lead_do_not_contact(lead):
            reasons.append("Do Not Contact is true")

        casl_basis = _lead_casl_basis(lead)
        if not casl_basis:
            reasons.append("CASL Basis is missing")

        if not _lead_email(lead):
            reasons.append("Email is missing")

        if not _lead_gmail_draft_id(lead):
            reasons.append("Gmail Draft ID is missing")

        lead_status = _lead_status(lead)
        if lead_status in BLOCKED_LEAD_STATUSES:
            reasons.append(f"Lead Status is {lead_status}")

        duplicate_status = _lead_duplicate_status(lead)
        if duplicate_status in BLOCKED_DUPLICATE_STATUSES:
            reasons.append(f"Duplicate Status is {duplicate_status}")

        gmail_sent_status = _lead_gmail_sent_status(lead)
        if gmail_sent_status in BLOCKED_GMAIL_SENT_STATUSES:
            reasons.append(f"Gmail Sent Status is {gmail_sent_status}")

        gmail_match_status = _lead_gmail_match_status(lead)
        if gmail_match_status in BLOCKED_GMAIL_MATCH_STATUSES:
            reasons.append(f"Gmail Match Status is {gmail_match_status}")

        if not _verified_send_as_email():
            reasons.append(f"sender alias {settings.gmail_send_as_email} is not verified")
        return reasons

    if ALLOW_RULE_BASED_APPROVAL:
        reasons.extend(_rule_based_approval_block_reasons(lead))
        return reasons

    reasons.append("Admin Approved is not true")
    send_mode = _lead_send_mode(lead)
    if send_mode != REQUIRED_SEND_MODE:
        reasons.append(f"Send Mode is {send_mode or '<empty>'}")

    if _lead_country(lead) != "canada":
        country = draft_flow._lead_text_value(lead, draft_flow.COUNTRY_CANDIDATES)  # type: ignore[attr-defined]
        reasons.append(f"Country is {country or '<empty>'}")

    if _lead_do_not_contact(lead):
        reasons.append("Do Not Contact is true")

    casl_basis = _lead_casl_basis(lead)
    if not casl_basis:
        reasons.append("CASL Basis is missing")

    email = _lead_email(lead)
    if not email:
        reasons.append("Email is missing")

    draft_id = _lead_gmail_draft_id(lead)
    if not draft_id:
        reasons.append("Gmail Draft ID is missing")

    lead_status = _lead_status(lead)
    if lead_status in BLOCKED_LEAD_STATUSES:
        reasons.append(f"Lead Status is {lead_status}")

    duplicate_status = _lead_duplicate_status(lead)
    if duplicate_status in BLOCKED_DUPLICATE_STATUSES:
        reasons.append(f"Duplicate Status is {duplicate_status}")

    gmail_sent_status = _lead_gmail_sent_status(lead)
    if gmail_sent_status in BLOCKED_GMAIL_SENT_STATUSES:
        reasons.append(f"Gmail Sent Status is {gmail_sent_status}")

    gmail_match_status = _lead_gmail_match_status(lead)
    if gmail_match_status in BLOCKED_GMAIL_MATCH_STATUSES:
        reasons.append(f"Gmail Match Status is {gmail_match_status}")

    return reasons


def _draft_recipient_emails(draft_details: Dict[str, Any]) -> List[str]:
    return [email.strip().lower() for _, email in getaddresses([draft_details.get("to", "")]) if email.strip()]


def _draft_from_email(draft_details: Dict[str, Any]) -> str:
    return parseaddr(draft_details.get("from", ""))[1].strip().lower()


def _draft_html_body(draft_details: Dict[str, Any]) -> str:
    return str(draft_details.get("html_body", "") or "").strip()


def _draft_plain_body(draft_details: Dict[str, Any]) -> str:
    return str(draft_details.get("plain_body", "") or "").strip()


def _draft_message_id(draft_details: Dict[str, Any]) -> str:
    return str(draft_details.get("message_id", "") or "").strip()


def _draft_label_ids(draft_details: Dict[str, Any]) -> List[str]:
    labels = draft_details.get("label_ids", []) or []
    return [str(label).strip().upper() for label in labels if str(label).strip()]


def _is_stale_gmail_draft_error(exc: Exception) -> bool:
    if not isinstance(exc, HttpError):
        return False
    status = getattr(exc.resp, "status", None)
    message = str(exc).lower()
    return status == 404 or "notfound" in message or "not found" in message


def _active_draft_block_reason(stored_draft_id: str, draft_details: Dict[str, Any]) -> Optional[str]:
    resolved_draft_id = draft_details.get("draft_id", "").strip()
    message_id = _draft_message_id(draft_details)
    label_ids = _draft_label_ids(draft_details)

    if not resolved_draft_id:
        return "not_active_draft"
    if stored_draft_id.strip() and resolved_draft_id != stored_draft_id.strip():
        return "not_active_draft"
    if not message_id:
        return "not_active_draft"
    if not label_ids or "DRAFT" not in label_ids:
        return "not_active_draft"
    return None


def _draft_send_block_reasons(lead: Dict[str, Any], draft_details: Dict[str, Any]) -> List[str]:
    reasons: List[str] = []
    verified_send_as_email = _verified_send_as_email()
    lead_email = _lead_email(lead).lower()
    recipient_emails = _draft_recipient_emails(draft_details)
    if not recipient_emails:
        reasons.append("draft recipient is missing")
    elif lead_email not in recipient_emails:
        reasons.append(f"draft recipient does not match Notion Email ({lead_email or '<empty>'})")

    subject = draft_details.get("subject", "").strip()
    html_body = _draft_html_body(draft_details)
    plain_body = _draft_plain_body(draft_details)
    body = draft_details.get("body", "").strip()
    if not subject:
        reasons.append("draft subject is missing")
    if not html_body and not plain_body and not body:
        reasons.append("draft body is missing")

    from_email = _draft_from_email(draft_details)
    if not verified_send_as_email:
        reasons.append(f"sender alias {settings.gmail_send_as_email} is not verified")
    elif from_email and from_email != verified_send_as_email:
        reasons.append(f"draft From address is {from_email}, expected {verified_send_as_email}")

    try:
        validate_prospect_copy(subject, body)
    except Exception as exc:
        reasons.append(str(exc))

    return reasons


def _skip_stale_draft(summary: Dict[str, int], skip_reasons: Dict[str, int], lead_name: str, draft_id: str, exc: Exception) -> None:
    summary["skipped"] += 1
    summary["stale_gmail_draft_id"] += 1
    skip_reasons["stale_gmail_draft_id"] = skip_reasons.get("stale_gmail_draft_id", 0) + 1
    print(f"SKIP | {lead_name} | Gmail Draft ID: {draft_id} | Reasons: stale_gmail_draft_id ({exc})")


def _skip_not_active_draft(summary: Dict[str, int], skip_reasons: Dict[str, int], lead_name: str, draft_id: str, reason: str) -> None:
    summary["skipped"] += 1
    summary["not_active_draft"] += 1
    skip_reasons["not_active_draft"] = skip_reasons.get("not_active_draft", 0) + 1
    print(f"SKIP | {lead_name} | Gmail Draft ID: {draft_id} | Reasons: not_active_draft ({reason})")


def _skip_ops_status_not_ready_to_send(
    summary: Dict[str, int],
    skip_reasons: Dict[str, int],
    lead_name: str,
    ops_status: str,
) -> None:
    reason = "skipped_ops_status_not_ready_to_send"
    summary["skipped"] += 1
    summary[reason] += 1
    skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
    print(
        f"SKIP | {lead_name} | Ops Status: {ops_status or '<empty>'} | "
        f"Reasons: {reason}"
    )


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


def _set_update(
    updates: Dict[str, Any],
    schema_properties: Dict[str, Any],
    candidates: Sequence[str],
    value: Any,
    *,
    only_if_empty: bool = False,
    lead: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    property_name = _first_existing_property_name(schema_properties, list(candidates))
    if not property_name:
        return None
    if only_if_empty and lead is not None:
        current_value = draft_flow._get_text_value(draft_flow._get_property(lead, property_name))  # type: ignore[attr-defined]
        if current_value:
            return property_name
    update_value = _property_update(schema_properties[property_name].get("type"), value)
    if update_value:
        updates[property_name] = update_value
    return property_name


def _business_days_from(start_date: datetime, days: int) -> str:
    current = start_date.date()
    remaining = days
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current.isoformat()


_DRAFT_TO_SENT_STEP: Dict[str, str] = {
    "Email 1 Drafted": "Email 1 Sent",
    "Email 2 Drafted": "Email 2 Sent",
    "Email 3 Drafted": "Email 3 Sent",
}


def build_notion_send_updates(
    schema_properties: Dict[str, Any],
    lead: Dict[str, Any],
    thread_id: str,
) -> Dict[str, Any]:
    updates: Dict[str, Any] = {}
    now = datetime.now(timezone.utc)
    sent_date = now.isoformat()

    current_step = _lead_sequence_step(lead)
    sent_step = _DRAFT_TO_SENT_STEP.get(current_step, "Email 1 Sent")
    is_final_email = sent_step == "Email 3 Sent"

    # Follow-up delay is step-specific: +3 days after Email 1, +5 days after Email 2.
    if sent_step == "Email 2 Sent":
        follow_up_date = _business_days_from(now, FOLLOWUP_DELAY_AFTER_EMAIL_2_BUSINESS_DAYS)
    else:
        follow_up_date = _business_days_from(now, FOLLOWUP_DELAY_AFTER_EMAIL_1_BUSINESS_DAYS)

    _set_update(updates, schema_properties, GMAIL_SENT_STATUS_CANDIDATES, REQUIRED_GMAIL_SENT_STATUS)
    if _set_update(updates, schema_properties, ["Lead Status"], REQUIRED_LEAD_STATUS) is None:
        _set_update(updates, schema_properties, ["Outreach Status"], REQUIRED_OUTREACH_STATUS)
    _set_update(updates, schema_properties, LAST_OUTREACH_DATE_CANDIDATES, sent_date)
    if thread_id:
        _set_update(updates, schema_properties, GMAIL_THREAD_ID_CANDIDATES, thread_id)
    _set_update(updates, schema_properties, GMAIL_MATCH_STATUS_CANDIDATES, REQUIRED_GMAIL_MATCH_STATUS)

    if is_final_email:
        # Mark the sequence as complete rather than leaving it at "Email 3 Sent"
        _set_update(updates, schema_properties, SEQUENCE_STEP_CANDIDATES, "Sequence Complete")
    else:
        _set_update(updates, schema_properties, SEQUENCE_STEP_CANDIDATES, sent_step)
        # Always write the fresh follow-up date based on the actual send time
        _set_update(updates, schema_properties, NEXT_FOLLOW_UP_DATE_CANDIDATES, follow_up_date)

    return updates


def _query_records(
    data_source_id: str,
    *,
    filter_payload: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    client = get_client()
    records: List[Dict[str, Any]] = []
    next_cursor: Optional[str] = None

    while True:
        page_size = 100
        if limit is not None:
            remaining = limit - len(records)
            if remaining <= 0:
                break
            page_size = min(page_size, remaining)

        kwargs: Dict[str, Any] = {"data_source_id": data_source_id, "page_size": page_size}
        if filter_payload:
            kwargs["filter"] = filter_payload
        if next_cursor:
            kwargs["start_cursor"] = next_cursor

        response = client.data_sources.query(**kwargs)
        records.extend(response.get("results", []))
        if not response.get("has_more"):
            break
        next_cursor = response.get("next_cursor")
        if not next_cursor:
            break

    return records


def _load_records(data_source_id: str, *, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    return _query_records(data_source_id, limit=limit)


def _build_ops_ready_to_send_filter(
    schema_properties: Dict[str, Any],
    ops_status_property: str,
) -> Optional[Dict[str, Any]]:
    return draft_flow._build_equality_filter(  # type: ignore[attr-defined]
        ops_status_property,
        schema_properties[ops_status_property].get("type"),
        OPS_READY_TO_SEND,
    )


def _query_ops_ready_to_send_records(
    data_source_id: str,
    schema_properties: Dict[str, Any],
    ops_status_property: str,
) -> List[Dict[str, Any]]:
    filter_payload = _build_ops_ready_to_send_filter(schema_properties, ops_status_property)
    if not filter_payload:
        return []
    return _query_records(data_source_id, filter_payload=filter_payload)


def _print_global_gate_status() -> None:
    verified_send_as_email = _verified_send_as_email()
    if SEND_DRY_RUN:
        print("Global send gate: dry run mode")
    else:
        print("Global send gate: live mode")
    print(f"- SEND_APPROVED_DRAFTS: {'yes' if SEND_APPROVED_DRAFTS else 'no'}")
    print(f"- ALLOW_RULE_BASED_APPROVAL: {'yes' if ALLOW_RULE_BASED_APPROVAL else 'no'}")
    print(f"- ALLOW_LEGACY_STATUS_FALLBACK: {'yes' if ALLOW_LEGACY_STATUS_FALLBACK else 'no'}")
    print(f"- SEND_OPS_DIAGNOSTIC_SCAN: {'yes' if SEND_OPS_DIAGNOSTIC_SCAN else 'no'}")
    if MAX_SENDS_PER_RUN is None:
        print("- MAX_SENDS_PER_RUN: unlimited")
        print("max sends per run: unlimited")
    else:
        print(f"- MAX_SENDS_PER_RUN: {MAX_SENDS_PER_RUN}")
        print(f"max sends per run: {MAX_SENDS_PER_RUN}")
    print(f"- Gmail send-as alias: {settings.gmail_send_as_email}")
    print(f"- Verified alias: {'yes' if verified_send_as_email else 'no'}")
    if ALLOW_RULE_BASED_APPROVAL:
        print("Rule-based approval path is available only when legacy fallback is active.")
    if not SEND_APPROVED_DRAFTS:
        print("GLOBAL BLOCK | SEND_APPROVED_DRAFTS=false")
    if not verified_send_as_email:
        print(f"GLOBAL BLOCK | sender alias {settings.gmail_send_as_email} is not verified")
    if not SEND_DRY_RUN and not SEND_APPROVED_DRAFTS:
        print("Live sending is disabled until SEND_APPROVED_DRAFTS=true.")


def main() -> None:
    _, data_source_id = get_database_and_data_source()
    schema = get_data_source_schema()
    schema_properties = schema.get("properties", {})
    ops_status_property = _first_existing_property_name(schema_properties, OPS_STATUS_CANDIDATES)

    _print_global_gate_status()
    legacy_approval_path_used = False
    skipped_ops_status_not_ready_to_send = 0
    if ops_status_property:
        records = _query_ops_ready_to_send_records(data_source_id, schema_properties, ops_status_property)
        print("send candidate source: Ops Status")
        print("workflow source: Ops Status")
        print(f"legacy fallback enabled: {'true' if ALLOW_LEGACY_STATUS_FALLBACK else 'false'}")
        print("active approval source: Ops Status only")
        print("legacy approval path used: false")
        print(f"ops_ready_to_send queried: {len(records)}")
        print(f"ops_ready_to_send selected: {len(records)}")
        if SEND_OPS_DIAGNOSTIC_SCAN:
            all_records = _load_records(data_source_id)
            skipped_ops_status_not_ready_to_send = 0
            for lead in all_records:
                ops_status = _lead_ops_status(lead)
                if ops_status == OPS_READY_TO_SEND:
                    continue
                skipped_ops_status_not_ready_to_send += 1
                print(
                    f"SKIP | {_lead_name(lead)} | Ops Status: {ops_status or '<empty>'} | "
                    "Reasons: skipped_ops_status_not_ready_to_send"
                )
    else:
        print("send candidate source: legacy approval fallback" if ALLOW_LEGACY_STATUS_FALLBACK else "send candidate source: Ops Status")
        print("workflow source: Ops Status missing")
        print(f"legacy fallback enabled: {'true' if ALLOW_LEGACY_STATUS_FALLBACK else 'false'}")
        if ALLOW_LEGACY_STATUS_FALLBACK:
            records = _load_records(data_source_id)
            legacy_approval_path_used = True
            print("active approval source: legacy fallback")
            print("legacy approval path used: true")
        else:
            records = []
            print("active approval source: none - fail closed")
            print("legacy approval path used: false")
            print("Ops Status field missing; legacy status fallback is disabled.")
    print(f"Loaded Notion records: {len(records)}")

    eligible: List[Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]] = []
    summary = {
        "records_checked": 0,
        "ops_ready_to_send_queried": len(records) if ops_status_property else 0,
        "ops_ready_to_send_selected": len(records) if ops_status_property else 0,
        "eligible_records": 0,
        "approved_by_ops": 0,
        "approved_by_admin": 0,
        "approved_by_rules": 0,
        "active_drafts_selected": 0,
        "selected": 0,
        "would_send": 0,
        "sent": 0,
        "notion_updated": 0,
        "notion_update_failed": 0,
        "sent_labels_applied": 0,
        "sent_label_apply_failed": 0,
        "skipped": 0,
        "skipped_ops_status_not_ready_to_send": skipped_ops_status_not_ready_to_send,
        "skipped_missing_scheduled_send_date": 0,
        "skipped_future_scheduled_send_date": 0,
        "stale_gmail_draft_id": 0,
        "not_active_draft": 0,
        "errors": 0,
    }
    skip_reasons: Dict[str, int] = {}
    if skipped_ops_status_not_ready_to_send:
        summary["skipped"] += skipped_ops_status_not_ready_to_send
        skip_reasons["skipped_ops_status_not_ready_to_send"] = skipped_ops_status_not_ready_to_send

    for lead in records:
        summary["records_checked"] += 1
        lead_name = _lead_name(lead)

        if ops_status_property:
            reasons = _ops_send_safety_block_reasons(lead)
            approval_path = "ops"
        elif legacy_approval_path_used:
            reasons = _lead_send_block_reasons(lead)
            approval_path = _lead_approval_path(lead)
        else:
            reasons = ["Ops Status field is missing and legacy status fallback is disabled"]
            approval_path = ""
        draft_id = _lead_gmail_draft_id(lead)
        if reasons:
            summary["skipped"] += 1
            for reason in reasons:
                skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
            print(
                f"SKIP | {lead_name} | Gmail Draft ID: {draft_id or '<missing>'} | "
                f"Reasons: {', '.join(reasons)}"
            )
            continue

        # Scheduled Send Date gate — required when Ops Status controls the send queue.
        if ops_status_property:
            ssd_raw = _lead_scheduled_send_date(lead)
            if not ssd_raw:
                summary["skipped"] += 1
                summary["skipped_missing_scheduled_send_date"] += 1
                skip_reasons["skipped_missing_scheduled_send_date"] = skip_reasons.get("skipped_missing_scheduled_send_date", 0) + 1
                print(f"SKIP | {lead_name} | Gmail Draft ID: {draft_id or '<missing>'} | Reasons: skipped_missing_scheduled_send_date")
                continue
            try:
                ssd = date.fromisoformat(ssd_raw[:10])
                today = datetime.now(timezone.utc).date()
                if ssd > today:
                    summary["skipped"] += 1
                    summary["skipped_future_scheduled_send_date"] += 1
                    skip_reasons["skipped_future_scheduled_send_date"] = skip_reasons.get("skipped_future_scheduled_send_date", 0) + 1
                    print(f"SKIP | {lead_name} | Gmail Draft ID: {draft_id or '<missing>'} | Scheduled Send Date: {ssd} | Reasons: skipped_future_scheduled_send_date")
                    continue
            except (ValueError, TypeError):
                summary["skipped"] += 1
                summary["skipped_missing_scheduled_send_date"] += 1
                skip_reasons["skipped_missing_scheduled_send_date"] = skip_reasons.get("skipped_missing_scheduled_send_date", 0) + 1
                print(f"SKIP | {lead_name} | Gmail Draft ID: {draft_id or '<missing>'} | Reasons: skipped_missing_scheduled_send_date (invalid: {ssd_raw!r})")
                continue

        if approval_path == "ops":
            summary["approved_by_ops"] += 1
        elif approval_path == "admin":
            summary["approved_by_admin"] += 1
        elif approval_path == "rule":
            summary["approved_by_rules"] += 1
            if ALLOW_RULE_BASED_APPROVAL:
                print(f"APPROVED | rule-based approval | {lead_name} | Gmail Draft ID: {draft_id}")

        try:
            draft = get_draft(draft_id)
            draft_details = extract_draft_details(draft)
            active_block_reason = _active_draft_block_reason(draft_id, draft_details)
            if active_block_reason:
                _skip_not_active_draft(summary, skip_reasons, lead_name, draft_id, active_block_reason)
                continue
            draft_block_reasons = _draft_send_block_reasons(lead, draft_details)
            if draft_block_reasons:
                summary["skipped"] += 1
                for reason in draft_block_reasons:
                    skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                print(
                    f"SKIP | {lead_name} | Gmail Draft ID: {draft_id} | "
                    f"Reasons: {', '.join(draft_block_reasons)}"
                )
                continue
        except Exception as exc:
            if _is_stale_gmail_draft_error(exc):
                _skip_stale_draft(summary, skip_reasons, lead_name, draft_id, exc)
                continue
            summary["errors"] += 1
            print(f"ERROR | {lead_name} | Gmail Draft ID: {draft_id or '<missing>'} | {exc}")
            continue

        eligible.append((lead, draft, draft_details))

    summary["eligible_records"] = len(eligible)
    summary["active_drafts_selected"] = len(eligible)
    selected = eligible if MAX_SENDS_PER_RUN is None else eligible[:MAX_SENDS_PER_RUN]
    summary["selected"] = len(selected)
    if SEND_DRY_RUN or not SEND_APPROVED_DRAFTS:
        summary["would_send"] = len(selected)

    print(f"Eligible records: {len(eligible)}")
    print(f"Selected records: {len(selected)}")

    for lead, draft, draft_details in selected:
        lead_name = _lead_name(lead)
        draft_id = draft_details["draft_id"] or _lead_gmail_draft_id(lead)
        action = "WOULD SEND" if SEND_DRY_RUN or not SEND_APPROVED_DRAFTS else "SENDING"
        print(
            f"{action} | {lead_name} | draft {draft_id} | to {draft_details.get('to', '<none>')} | "
            f"subject {draft_details.get('subject', '<no subject>')}"
        )
        html_body = _draft_html_body(draft_details)
        plain_body = _draft_plain_body(draft_details)
        if html_body:
            print(f"- html body chars: {len(html_body)}")
        if plain_body:
            print(f"- plain body chars: {len(plain_body)}")
        if SEND_DRY_RUN or not SEND_APPROVED_DRAFTS:
            print("- sent message would be labeled after send: Anvis/Leads")

    verified_send_as_email = _verified_send_as_email()
    if SEND_DRY_RUN or not SEND_APPROVED_DRAFTS or not verified_send_as_email:
        print("No live sends were performed.")
        print("Send skipped reasons:")
        for reason, count in sorted(skip_reasons.items(), key=lambda item: (-item[1], item[0])):
            print(f"- {reason}: {count}")
        print("Send summary:")
        for key, value in summary.items():
            print(f"- {key}: {value}")
        return

    for lead, draft, draft_details in selected:
        lead_name = _lead_name(lead)
        draft_id = draft_details["draft_id"]
        message_id = draft_details.get("message_id", "")
        label_ids = ", ".join(draft_details.get("label_ids", [])) or "<none>"
        try:
            active_block_reason = _active_draft_block_reason(draft_id, draft_details)
            if active_block_reason:
                _skip_not_active_draft(summary, skip_reasons, lead_name, draft_id, active_block_reason)
                continue

            print(f"SENDING | {lead_name} | draft {draft_id} | message {message_id or '<none>'} | labels {label_ids}")
            sent = send_draft(draft_id)
            sent_message_id = str(sent.get("id", "") or sent.get("messageId", "") or sent.get("message_id", "") or "").strip()
            sent_thread_id = str(sent.get("threadId", "") or sent.get("thread_id", "") or "").strip()
            print(
                f"SENT | {lead_name} | draft {draft_id} | message {sent_message_id or '<none>'} | "
                f"thread {sent_thread_id or '<none>'}"
            )

            if sent_message_id:
                try:
                    if SEND_DRY_RUN or not SEND_APPROVED_DRAFTS:
                        print(
                            f"LABEL WOULD APPLY | {lead_name} | message {sent_message_id} | label Anvis/Leads"
                        )
                    else:
                        apply_label_to_message(sent_message_id, "Anvis/Leads")
                        summary["sent_labels_applied"] += 1
                except Exception as exc:
                    summary["sent_label_apply_failed"] += 1
                    print(f"Warning: could not apply Gmail label 'Anvis/Leads' to sent message {sent_message_id}: {exc}")
            else:
                summary["sent_label_apply_failed"] += 1
                print(
                    f"Warning: could not apply Gmail label 'Anvis/Leads' because Gmail returned no sent message id "
                    f"for draft {draft_id}."
                )

            updates = build_notion_send_updates(schema_properties, lead, sent_thread_id)
            if updates:
                get_client().pages.update(page_id=lead["id"], properties=updates)
                summary["notion_updated"] += 1
            summary["sent"] += 1
        except Exception as exc:
            if _is_stale_gmail_draft_error(exc):
                _skip_stale_draft(summary, skip_reasons, lead_name, draft_id, exc)
                continue
            summary["errors"] += 1
            print(f"FAIL | send | {lead_name} | draft {draft_id} | {exc}")

    print("Send summary:")
    for key, value in summary.items():
        print(f"- {key}: {value}")


if __name__ == "__main__":
    main()
