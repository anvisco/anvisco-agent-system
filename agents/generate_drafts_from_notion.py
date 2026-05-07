from __future__ import annotations

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import argparse
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from notion_client import Client
from notion_client.errors import APIResponseError

from src.config import settings
from src.email_writer import generate_email_sequence
from src.gmail_client import create_draft, get_preferred_send_as_email, is_verified_send_as_alias, send_email_message
from src.notion_client import get_data_source_schema, get_database_and_data_source


def _env_flag(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _max_drafts_per_run() -> int:
    raw_value = os.getenv("MAX_DRAFTS_PER_RUN")
    if raw_value is None or not raw_value.strip():
        return 25
    try:
        value = int(raw_value)
    except ValueError:
        return 25
    return max(1, value)


MAX_DRAFTS_PER_RUN = _max_drafts_per_run()


def _min_drafts_target(max_drafts: int) -> int:
    raw_value = os.getenv("MIN_DRAFTS_TARGET")
    default_target = min(15, max_drafts)
    if raw_value is None or not raw_value.strip():
        return default_target
    try:
        value = int(raw_value)
    except ValueError:
        return default_target
    return max(1, min(value, max_drafts))


MIN_DRAFTS_TARGET = _min_drafts_target(MAX_DRAFTS_PER_RUN)
ALLOW_LEGACY_STATUS_FALLBACK = _env_flag("ALLOW_LEGACY_STATUS_FALLBACK", False)
OPS_STATUS_CANDIDATES = ["Ops Status"]
OPS_READY_TO_DRAFT = "ready_to_draft"
OPS_SENT = "sent"
STATUS_FIELD_CANDIDATES = ["Lead Status", "Outreach Status"]
OUTREACH_STATUS_FIELD_CANDIDATES = ["Outreach Status"]
NAME_FIELD_CANDIDATES = ["Business Name", "Practice Name", "Clinic Name", "Name"]
EMAIL_FIELD_CANDIDATES = ["Email", "Contact Email"]
DO_NOT_CONTACT_CANDIDATES = ["Do Not Contact", "DNC"]
EMAIL_1_SUBJECT_CANDIDATES = ["Email 1 Subject", "Email Subject", "Subject"]
EMAIL_1_DRAFT_CANDIDATES = ["Email 1 Draft", "Email Draft", "Outreach Email Draft"]
EMAIL_2_SUBJECT_CANDIDATES = ["Email 2 Subject"]
EMAIL_2_DRAFT_CANDIDATES = ["Email 2 Draft"]
EMAIL_3_SUBJECT_CANDIDATES = ["Email 3 Subject"]
EMAIL_3_DRAFT_CANDIDATES = ["Email 3 Draft"]
DRAFT_CREATED_DATE_CANDIDATES = ["Draft Created Date"]
EMAIL_1_DATE_CANDIDATES = ["Email 1 Date"]
TIER_CANDIDATES = ["Tier"]
TOP_ISSUE_CANDIDATES = ["Top 3 Issues", "Top Issue"]
OUTREACH_ANGLE_CANDIDATES = ["Email Angle", "Outreach Angle"]
WEBSITE_CANDIDATES = ["Website"]
RECOMMENDED_OFFER_CANDIDATES = ["Recommended Offer"]
LEAD_QUALITY_SCORE_CANDIDATES = ["Lead Quality Score"]
ANGLE_BUCKET_CANDIDATES = ["Angle Bucket"]
LOOM_RECOMMENDED_CANDIDATES = ["Loom Recommended"]
LOOM_SCRIPT_CANDIDATES = ["Loom Script"]
SEQUENCE_STEP_CANDIDATES = ["Sequence Step"]
LAST_OUTREACH_DATE_CANDIDATES = ["Last Outreach Date", "Last Email Sent At"]
NEXT_FOLLOW_UP_DATE_CANDIDATES = ["Next Follow-up Date", "Next Follow Up Date"]
REPLY_STATUS_CANDIDATES = ["Reply Status"]
GMAIL_DRAFT_ID_CANDIDATES = ["Gmail Draft ID"]
GMAIL_THREAD_ID_CANDIDATES = ["Gmail Thread ID"]
SCRAPE_NOTES_CANDIDATES = ["Scrape Notes"]
COUNTRY_CANDIDATES = ["Country"]
PROVINCE_CANDIDATES = ["Province"]
SUBJECT_ANGLE_CANDIDATES = ["Subject Angle", "Email Angle"]
CLINIC_STRENGTHS_CANDIDATES = ["Clinic Strengths"]
STRONGEST_ADVANTAGE_CANDIDATES = ["Strongest Advantage"]
PATIENT_TYPE_LOCATION_ANGLE_CANDIDATES = ["Patient Type / Location Angle"]
TOP_3_ISSUES_CANDIDATES = ["Top 3 Issues"]
BUSINESS_IMPACT_CANDIDATES = ["Business Impact"]
RECOMMENDED_FIX_CANDIDATES = ["Recommended Fix"]
EMAIL_ANGLE_CANDIDATES = ["Email Angle"]
LOOM_LINK_CANDIDATES = ["Loom Link"]
DUPLICATE_STATUS_CANDIDATES = ["Duplicate Status"]
GMAIL_MATCH_STATUS_CANDIDATES = ["Gmail Match Status"]
GMAIL_SENT_STATUS_CANDIDATES = ["Gmail Sent Status"]
ADMIN_APPROVED_CANDIDATES = ["Admin Approved"]
CASL_BASIS_CANDIDATES = ["CASL Basis"]
SEND_MODE_CANDIDATES = ["Send Mode"]
AUTO_SEND_ELIGIBLE_CANDIDATES = ["Auto-Send Eligible"]
LAST_EMAIL_DRAFTED_AT_CANDIDATES = ["Last Email Drafted At"]
LAST_EMAIL_SENT_AT_CANDIDATES = ["Last Outreach Date", "Last Email Sent At"]
FOLLOW_UP_DUE_NOW_CANDIDATES = ["Follow-Up Due Now"]
CITY_CANDIDATES = ["City"]
NICHE_CANDIDATES = ["Niche"]
SERVICES_CANDIDATES = ["Services"]
LANGUAGES_CANDIDATES = ["Languages"]
REVIEW_COUNT_CANDIDATES = ["Review Count"]
RATING_CANDIDATES = ["Rating"]
BOOKING_URL_CANDIDATES = ["Booking URL", "Contact Page URL"]
WEBSITE_STATUS_CANDIDATES = ["Website Status"]
NOTES_CANDIDATES = ["Notes", "Scrape Notes"]

DRAFT_READY_STATUS_VALUES = {"New Lead", "Draft Ready", "audit_ready", "draft_ready", "outreach_drafted"}
SENT_STATUS_VALUES = {"Email 1 Sent", "Email 2 Sent", "outreach_sent"}

CANADA_COUNTRY = "canada"
TERMINAL_LEAD_STATUSES = {"not_fit"}
BLOCKED_DUPLICATE_STATUSES = {"possible_duplicate", "duplicate", "already_contacted", "do_not_contact"}
FALLBACK_ANGLE_BUCKET = "visibility_trust_booking"

STAGE_NEW_LEADS = "new_leads"
STAGE_BACKFILL = "backfill"
STAGE_FALLBACK = "fallback"
STAGE_OPS_READY = "ops_ready_to_draft"
STAGE_CONFIGS = (
    (STAGE_NEW_LEADS, True, True),
    (STAGE_BACKFILL, True, True),
    (STAGE_FALLBACK, False, False),
)

CANONICAL_LEAD_STATUS_VALUES = ("audit_ready", "outreach_drafted")
LEGACY_OUTREACH_STATUS_VALUES = ("New Lead", "Draft Ready", "draft_ready")
EMAIL_INPUT_FIELD_GROUPS: Tuple[Tuple[str, List[str]], ...] = (
    ("Business Name", NAME_FIELD_CANDIDATES),
    ("Email", EMAIL_FIELD_CANDIDATES),
    ("Website", WEBSITE_CANDIDATES),
    ("City", CITY_CANDIDATES),
    ("Country", COUNTRY_CANDIDATES),
    ("Province", PROVINCE_CANDIDATES),
    ("Niche", NICHE_CANDIDATES),
    ("Services", SERVICES_CANDIDATES),
    ("Languages", LANGUAGES_CANDIDATES),
    ("Review Count", REVIEW_COUNT_CANDIDATES),
    ("Rating", RATING_CANDIDATES),
    ("Booking URL", BOOKING_URL_CANDIDATES),
    ("Subject Angle", SUBJECT_ANGLE_CANDIDATES),
    ("Clinic Strengths", CLINIC_STRENGTHS_CANDIDATES),
    ("Strongest Advantage", STRONGEST_ADVANTAGE_CANDIDATES),
    ("Patient Type / Location Angle", PATIENT_TYPE_LOCATION_ANGLE_CANDIDATES),
    ("Top Issue", TOP_ISSUE_CANDIDATES),
    ("Business Impact", BUSINESS_IMPACT_CANDIDATES),
    ("Recommended Fix", RECOMMENDED_FIX_CANDIDATES),
    ("Email Angle", EMAIL_ANGLE_CANDIDATES),
    ("Outreach Angle", OUTREACH_ANGLE_CANDIDATES),
    ("Recommended Offer", RECOMMENDED_OFFER_CANDIDATES),
    ("Angle Bucket", ANGLE_BUCKET_CANDIDATES),
    ("Loom Link", LOOM_LINK_CANDIDATES),
    ("Website Status", WEBSITE_STATUS_CANDIDATES),
    ("Notes", NOTES_CANDIDATES),
)
MANUAL_AUDIT_PLACEHOLDER_PATTERNS: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    ("NEEDS MANUAL AUDIT", re.compile(r"\bNEEDS\s+MANUAL\s+AUDIT\b", re.IGNORECASE)),
    ("NEEDS AUDIT", re.compile(r"\bNEEDS\s+AUDIT\b", re.IGNORECASE)),
    ("MANUAL AUDIT", re.compile(r"\bMANUAL\s+AUDIT\b", re.IGNORECASE)),
    ("AUDIT WEBSITE MANUALLY", re.compile(r"\bAUDIT\s+WEBSITE\s+MANUALLY\b", re.IGNORECASE)),
    ("WRITE SPECIFIC ISSUE HERE", re.compile(r"\bWRITE\s+SPECIFIC\s+ISSUE\s+HERE\b", re.IGNORECASE)),
    ("TODO", re.compile(r"\bTODO\b", re.IGNORECASE)),
    ("TBD", re.compile(r"\bTBD\b", re.IGNORECASE)),
    ("PLACEHOLDER", re.compile(r"\bPLACEHOLDER\b", re.IGNORECASE)),
    ("N/A", re.compile(r"(^|[\s,;:/|()-])N\s*/?\s*A($|[\s,.;:/|()-])", re.IGNORECASE)),
)


def get_client() -> Client:
    if not settings.notion_api_key:
        raise ValueError("NOTION_API_KEY is missing.")
    return Client(auth=settings.notion_api_key)


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
    return ""


def _has_value(property_value: Dict[str, Any]) -> bool:
    if not property_value:
        return False
    if "email" in property_value:
        return bool(property_value["email"])
    if "rich_text" in property_value:
        return bool(property_value["rich_text"])
    if "title" in property_value:
        return bool(property_value["title"])
    if "url" in property_value:
        return bool(property_value["url"])
    if "select" in property_value:
        return bool(property_value["select"])
    if "status" in property_value:
        return bool(property_value["status"])
    if "checkbox" in property_value:
        return True
    return False


def _get_property(lead: Dict[str, Any], name: str) -> Dict[str, Any]:
    return lead.get("properties", {}).get(name, {})


def _get_lead_name(lead: Dict[str, Any]) -> str:
    lead_name_property = _first_existing_property_name(lead.get("properties", {}), NAME_FIELD_CANDIDATES)
    lead_name = _get_text_value(_get_property(lead, lead_name_property or "")) if lead_name_property else ""
    return lead_name or lead.get("id", "<unknown>")


def _get_checkbox_value(property_value: Dict[str, Any]) -> bool:
    return bool(property_value.get("checkbox")) if property_value else False


def _has_date_value(property_value: Dict[str, Any]) -> bool:
    return bool(property_value.get("date", {}).get("start")) if property_value else False


def _get_date_value(property_value: Dict[str, Any]) -> Optional[date]:
    if not property_value:
        return None
    start = property_value.get("date", {}).get("start")
    if not start:
        return None
    try:
        return date.fromisoformat(start[:10])
    except ValueError:
        return None


def _get_formula_value(property_value: Dict[str, Any]) -> Any:
    if not property_value:
        return None
    formula = property_value.get("formula")
    if not isinstance(formula, dict):
        return None
    if formula.get("type") == "boolean":
        return formula.get("boolean")
    if formula.get("type") == "number":
        return formula.get("number")
    if formula.get("type") == "string":
        return formula.get("string")
    if formula.get("type") == "date":
        return formula.get("date")
    return None


def _is_true_like(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1"}
    return False


def _normalized_text_value(lead: Dict[str, Any], candidates: List[str]) -> str:
    return _lead_text_value(lead, candidates).strip().lower()


def _lead_is_canada(lead: Dict[str, Any]) -> bool:
    country = _normalized_text_value(lead, COUNTRY_CANDIDATES)
    return country == CANADA_COUNTRY


def _lead_has_terminal_status(lead: Dict[str, Any]) -> bool:
    lead_status = _normalized_text_value(lead, STATUS_FIELD_CANDIDATES)
    return lead_status in TERMINAL_LEAD_STATUSES


def _lead_duplicate_status(lead: Dict[str, Any]) -> str:
    return _normalized_text_value(lead, DUPLICATE_STATUS_CANDIDATES)


def _lead_gmail_match_status(lead: Dict[str, Any]) -> str:
    return _normalized_text_value(lead, GMAIL_MATCH_STATUS_CANDIDATES)


def _draft_block_reasons(
    lead: Dict[str, Any],
    *,
    require_unique_duplicate: bool,
    require_gmail_match_no_match: bool,
) -> List[str]:
    reasons: List[str] = []

    if _lead_has_terminal_status(lead):
        reasons.append("Lead Status is not_fit")

    country = _lead_text_value(lead, COUNTRY_CANDIDATES)
    if country and country.lower() != "canada":
        reasons.append(f"Country is {country}")
    elif not country:
        reasons.append("Country is missing")

    duplicate_status = _lead_duplicate_status(lead)
    if require_unique_duplicate:
        if duplicate_status != "unique":
            reasons.append(f"Duplicate Status is {duplicate_status or '<empty>'}")
    elif duplicate_status in BLOCKED_DUPLICATE_STATUSES:
        reasons.append(f"Duplicate Status is {duplicate_status}")

    if require_gmail_match_no_match:
        gmail_match_status = _lead_gmail_match_status(lead)
        if gmail_match_status != "no_match":
            reasons.append(f"Gmail Match Status is {gmail_match_status or '<empty>'}")

    return reasons


def _first_existing_property_name(properties: Dict[str, Any], candidates: List[str]) -> Optional[str]:
    for candidate in candidates:
        if candidate in properties:
            return candidate
    return None


def _build_not_empty_filter(property_name: str, property_type: str) -> Optional[Dict[str, Any]]:
    if property_type in {"rich_text", "title", "email", "url", "phone_number"}:
        return {"property": property_name, property_type: {"is_not_empty": True}}
    if property_type in {"select", "status"}:
        return {"property": property_name, property_type: {"is_not_empty": True}}
    return None


def _build_empty_filter(property_name: str, property_type: str) -> Optional[Dict[str, Any]]:
    if property_type in {"rich_text", "title", "email", "url", "phone_number"}:
        return {"property": property_name, property_type: {"is_empty": True}}
    if property_type in {"select", "status"}:
        return {"property": property_name, property_type: {"is_empty": True}}
    return None


def _build_status_filter(property_name: str, property_type: str, statuses: Tuple[str, ...]) -> Optional[Dict[str, Any]]:
    clauses: List[Dict[str, Any]] = []
    for status in statuses:
        clause = _build_equality_filter(property_name, property_type, status)
        if clause:
            clauses.append(clause)
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"or": clauses}


def _available_status_values_for_field(property_name: str) -> Tuple[str, ...]:
    if property_name == "Lead Status":
        return CANONICAL_LEAD_STATUS_VALUES
    if property_name == "Outreach Status":
        return LEGACY_OUTREACH_STATUS_VALUES
    return ()


def _candidate_status_field(properties: Dict[str, Any]) -> Tuple[Optional[str], Tuple[str, ...]]:
    lead_status_property = _first_existing_property_name(properties, ["Lead Status"])
    if lead_status_property:
        return lead_status_property, _available_status_values_for_field(lead_status_property)

    outreach_status_property = _first_existing_property_name(properties, ["Outreach Status"])
    if outreach_status_property:
        return outreach_status_property, _available_status_values_for_field(outreach_status_property)

    return None, ()


def _ops_status_field(properties: Dict[str, Any]) -> Optional[str]:
    return _first_existing_property_name(properties, OPS_STATUS_CANDIDATES)


def _build_common_email1_candidate_filters(
    properties: Dict[str, Any],
    *,
    require_top_issue: bool,
    require_angle_bucket: bool,
) -> List[Dict[str, Any]]:
    filter_parts: List[Dict[str, Any]] = []

    lead_status_property = _first_existing_property_name(properties, ["Lead Status"])
    if lead_status_property:
        _print_detected_fields(properties, [lead_status_property], "lead status field")
        lead_status_filter = _build_not_equals_filter(
            lead_status_property,
            properties[lead_status_property].get("type"),
            "not_fit",
        )
        if lead_status_filter:
            filter_parts.append(lead_status_filter)

    country_property = _first_existing_property_name(properties, COUNTRY_CANDIDATES)
    if country_property:
        _print_detected_fields(properties, [country_property], "country field")
        country_filter = _build_equality_filter(
            country_property,
            properties[country_property].get("type"),
            "Canada",
        )
        if country_filter:
            filter_parts.append(country_filter)

    duplicate_status_property = _first_existing_property_name(properties, DUPLICATE_STATUS_CANDIDATES)
    if duplicate_status_property:
        _print_detected_fields(properties, [duplicate_status_property], "duplicate status field")
        for blocked_status in ("possible_duplicate", "duplicate", "already_contacted", "do_not_contact"):
            duplicate_filter = _build_not_equals_filter(
                duplicate_status_property,
                properties[duplicate_status_property].get("type"),
                blocked_status,
            )
            if duplicate_filter:
                filter_parts.append(duplicate_filter)

    gmail_draft_id_property = _first_existing_property_name(properties, GMAIL_DRAFT_ID_CANDIDATES)
    if gmail_draft_id_property:
        _print_detected_fields(properties, [gmail_draft_id_property], "Gmail Draft ID field")
        draft_filter = _build_empty_filter(
            gmail_draft_id_property,
            properties[gmail_draft_id_property].get("type"),
        )
        if draft_filter:
            filter_parts.append(draft_filter)

    gmail_sent_status_property = _first_existing_property_name(properties, GMAIL_SENT_STATUS_CANDIDATES)
    if gmail_sent_status_property:
        _print_detected_fields(properties, [gmail_sent_status_property], "Gmail Sent Status field")
        sent_filter = _build_not_equals_filter(
            gmail_sent_status_property,
            properties[gmail_sent_status_property].get("type"),
            "sent",
        )
        if sent_filter:
            filter_parts.append(sent_filter)

    gmail_match_status_property = _first_existing_property_name(properties, GMAIL_MATCH_STATUS_CANDIDATES)
    if gmail_match_status_property:
        _print_detected_fields(properties, [gmail_match_status_property], "Gmail Match Status field")
        for blocked_status in ("sent_exists", "replied"):
            match_filter = _build_not_equals_filter(
                gmail_match_status_property,
                properties[gmail_match_status_property].get("type"),
                blocked_status,
            )
            if match_filter:
                filter_parts.append(match_filter)

    email_property = _first_existing_property_name(properties, EMAIL_FIELD_CANDIDATES)
    if email_property:
        _print_detected_fields(properties, [email_property], "email field")
        email_filter = _build_not_empty_filter(email_property, properties[email_property].get("type"))
        if email_filter:
            filter_parts.append(email_filter)

    website_property = _first_existing_property_name(properties, WEBSITE_CANDIDATES)
    if website_property:
        _print_detected_fields(properties, [website_property], "website field")
        website_filter = _build_not_empty_filter(website_property, properties[website_property].get("type"))
        if website_filter:
            filter_parts.append(website_filter)

    if require_top_issue:
        top_issue_property = _first_existing_property_name(properties, TOP_ISSUE_CANDIDATES)
        if top_issue_property:
            _print_detected_fields(properties, [top_issue_property], "Top Issue field")
            top_issue_filter = _build_not_empty_filter(
                top_issue_property,
                properties[top_issue_property].get("type"),
            )
            if top_issue_filter:
                filter_parts.append(top_issue_filter)

    if require_angle_bucket:
        angle_bucket_property = _first_existing_property_name(properties, ANGLE_BUCKET_CANDIDATES)
        if angle_bucket_property:
            _print_detected_fields(properties, [angle_bucket_property], "Angle Bucket field")
            angle_bucket_filter = _build_not_empty_filter(
                angle_bucket_property,
                properties[angle_bucket_property].get("type"),
            )
            if angle_bucket_filter:
                filter_parts.append(angle_bucket_filter)

    dnc_property = _first_existing_property_name(properties, DO_NOT_CONTACT_CANDIDATES)
    if dnc_property:
        _print_detected_fields(properties, [dnc_property], "do-not-contact field")
        dnc_filter = _build_checkbox_filter(dnc_property, properties[dnc_property].get("type"), False)
        if dnc_filter:
            filter_parts.append(dnc_filter)

    return filter_parts


def _build_query_filter(
    properties: Dict[str, Any],
    status_property: Optional[str],
    statuses: Tuple[str, ...],
    require_top_issue: bool,
    require_angle_bucket: bool,
) -> Optional[Dict[str, Any]]:
    filter_parts: List[Dict[str, Any]] = []

    if not status_property:
        _print_available_properties(properties)
        raise ValueError("Lead Status / Outreach Status property is missing from the Notion data source.")
    _print_detected_fields(properties, [status_property], "status field")
    status_filter = _build_status_filter(
        status_property,
        properties[status_property].get("type"),
        statuses,
    )
    if status_filter:
        filter_parts.append(status_filter)

    filter_parts.extend(
        _build_common_email1_candidate_filters(
            properties,
            require_top_issue=require_top_issue,
            require_angle_bucket=require_angle_bucket,
        )
    )

    if not filter_parts:
        return None
    if len(filter_parts) == 1:
        return filter_parts[0]
    return {"and": filter_parts}


def _build_broad_query_filter(
    properties: Dict[str, Any],
    status_property: Optional[str],
    require_top_issue: bool,
    require_angle_bucket: bool,
) -> Optional[Dict[str, Any]]:
    filter_parts: List[Dict[str, Any]] = []

    if not status_property:
        _print_available_properties(properties)
        raise ValueError("Lead Status / Outreach Status property is missing from the Notion data source.")

    _print_detected_fields(properties, [status_property], "status field")
    status_filter = _build_not_empty_filter(status_property, properties[status_property].get("type"))
    if status_filter:
        filter_parts.append(status_filter)

    filter_parts.extend(
        _build_common_email1_candidate_filters(
            properties,
            require_top_issue=require_top_issue,
            require_angle_bucket=require_angle_bucket,
        )
    )

    if not filter_parts:
        return None
    if len(filter_parts) == 1:
        return filter_parts[0]
    return {"and": filter_parts}


def _build_ops_ready_query_filter(properties: Dict[str, Any], ops_status_property: str) -> Optional[Dict[str, Any]]:
    filter_parts: List[Dict[str, Any]] = []
    _print_detected_fields(properties, [ops_status_property], "Ops Status field")
    ops_filter = _build_equality_filter(
        ops_status_property,
        properties[ops_status_property].get("type"),
        OPS_READY_TO_DRAFT,
    )
    if ops_filter:
        filter_parts.append(ops_filter)

    filter_parts.extend(
        _build_common_email1_candidate_filters(
            properties,
            require_top_issue=False,
            require_angle_bucket=False,
        )
    )

    if not filter_parts:
        return None
    if len(filter_parts) == 1:
        return filter_parts[0]
    return {"and": filter_parts}


def _query_draft_candidates(
    limit: int,
    require_top_issue: bool,
    require_angle_bucket: bool,
) -> List[Dict[str, Any]]:
    client = get_client()
    _, data_source_id = get_database_and_data_source()
    schema = get_data_source_schema()
    properties = schema.get("properties", {})
    status_property, statuses = _candidate_status_field(properties)
    if not status_property:
        return []

    filter_payload = _build_query_filter(
        properties,
        status_property,
        statuses,
        require_top_issue=require_top_issue,
        require_angle_bucket=require_angle_bucket,
    )
    if not filter_payload:
        return []

    try:
        response = client.data_sources.query(
            data_source_id=data_source_id,
            filter=filter_payload,
            page_size=limit,
        )
        return list(response.get("results", []))
    except APIResponseError as error:
        error_message = str(error).lower()
        if "select option" not in error_message and "status" not in error_message:
            raise

        print(
            "Warning: Notion rejected the status filter for the candidate query; "
            "retrying with a broader filter and local status filtering."
        )
        broad_filter = _build_broad_query_filter(
            properties,
            status_property,
            require_top_issue=require_top_issue,
            require_angle_bucket=require_angle_bucket,
        )
        if not broad_filter:
            return []

        results: List[Dict[str, Any]] = []
        next_cursor: Optional[str] = None
        while len(results) < limit:
            query_kwargs: Dict[str, Any] = {
                "data_source_id": data_source_id,
                "filter": broad_filter,
                "page_size": min(100, max(limit, 25)),
            }
            if next_cursor:
                query_kwargs["start_cursor"] = next_cursor
            response = client.data_sources.query(**query_kwargs)
            page_results = list(response.get("results", []))
            if not page_results:
                break
            for page in page_results:
                if _draft_candidate_status_matches(page, status_property, statuses):
                    results.append(page)
                    if len(results) >= limit:
                        break
            if not response.get("has_more"):
                break
            next_cursor = response.get("next_cursor")
            if not next_cursor:
                break
        return results


def _query_ops_ready_to_draft_candidates(limit: int) -> List[Dict[str, Any]]:
    client = get_client()
    _, data_source_id = get_database_and_data_source()
    schema = get_data_source_schema()
    properties = schema.get("properties", {})
    ops_status_property = _ops_status_field(properties)
    if not ops_status_property:
        return []

    filter_payload = _build_ops_ready_query_filter(properties, ops_status_property)
    if not filter_payload:
        return []

    response = client.data_sources.query(
        data_source_id=data_source_id,
        filter=filter_payload,
        page_size=limit,
    )
    return list(response.get("results", []))


def _draft_candidate_status_matches(lead: Dict[str, Any], status_property: str, statuses: Tuple[str, ...]) -> bool:
    if not statuses:
        return False
    status_value = _get_text_value(_get_property(lead, status_property))
    if not status_value:
        return False
    return status_value in statuses


def _print_available_properties(properties: Dict[str, Any]) -> None:
    print("Available Notion properties:")
    for name, prop in properties.items():
        print(f"- {name}: {prop.get('type')}")


def _print_detected_fields(properties: Dict[str, Any], field_names: List[str], label: str) -> None:
    for field_name in field_names:
        prop = properties.get(field_name)
        if prop:
            print(f"Detected {label}: {field_name} ({prop.get('type')})")


def _build_equality_filter(property_name: str, property_type: str, value: str) -> Optional[Dict[str, Any]]:
    if property_type == "status":
        return {"property": property_name, "status": {"equals": value}}
    if property_type == "select":
        return {"property": property_name, "select": {"equals": value}}
    if property_type == "rich_text":
        return {"property": property_name, "rich_text": {"equals": value}}

    print(f"Warning: skipping unsupported filter type '{property_type}' for {property_name}")
    return None


def _build_not_equals_filter(property_name: str, property_type: str, value: str) -> Optional[Dict[str, Any]]:
    if property_type == "status":
        return {"property": property_name, "status": {"does_not_equal": value}}
    if property_type == "select":
        return {"property": property_name, "select": {"does_not_equal": value}}
    if property_type == "rich_text":
        return {"property": property_name, "rich_text": {"does_not_equal": value}}

    print(f"Warning: skipping unsupported not-equals filter type '{property_type}' for {property_name}")
    return None


def _build_checkbox_filter(property_name: str, property_type: str, value: bool) -> Optional[Dict[str, Any]]:
    if property_type == "checkbox":
        return {"property": property_name, "checkbox": {"equals": value}}

    print(f"Warning: skipping unsupported filter type '{property_type}' for {property_name}")
    return None


def _build_empty_filter(property_name: str, property_type: str) -> Optional[Dict[str, Any]]:
    if property_type == "rich_text":
        return {"property": property_name, "rich_text": {"is_empty": True}}
    if property_type == "title":
        return {"property": property_name, "title": {"is_empty": True}}

    print(f"Warning: skipping unsupported empty filter type '{property_type}' for {property_name}")
    return None


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


def _add_update(
    updates: Dict[str, Any],
    schema_properties: Dict[str, Any],
    candidates: List[str],
    value: Any,
) -> None:
    property_name = _first_existing_property_name(schema_properties, candidates)
    if not property_name:
        return
    update_value = _property_update(schema_properties[property_name].get("type"), value)
    if update_value:
        updates[property_name] = update_value


def _add_update_if_empty(
    updates: Dict[str, Any],
    schema_properties: Dict[str, Any],
    lead: Dict[str, Any],
    candidates: List[str],
    value: Any,
) -> None:
    property_name = _first_existing_property_name(schema_properties, candidates)
    if not property_name:
        return
    if _get_text_value(_get_property(lead, property_name)):
        return
    update_value = _property_update(schema_properties[property_name].get("type"), value)
    if update_value:
        updates[property_name] = update_value


def _append_scrape_note_update(schema: Dict[str, Any], lead: Dict[str, Any], note: str) -> Dict[str, Any]:
    schema_properties = schema.get("properties", {})
    scrape_notes_property = _first_existing_property_name(schema_properties, SCRAPE_NOTES_CANDIDATES)
    if not scrape_notes_property:
        return {}
    existing = _get_text_value(_get_property(lead, scrape_notes_property))
    combined = f"{existing}\n{note}".strip() if existing else note
    update_value = _property_update(schema_properties[scrape_notes_property].get("type"), combined)
    return {scrape_notes_property: update_value} if update_value else {}


def _lead_quality_score(lead: Dict[str, Any]) -> int:
    score_property = _first_existing_property_name(lead.get("properties", {}), LEAD_QUALITY_SCORE_CANDIDATES)
    raw_score = _get_text_value(_get_property(lead, score_property or ""))
    try:
        return int(float(raw_score))
    except ValueError:
        return 0


def _missing_email_1_fields(lead: Dict[str, Any]) -> List[str]:
    missing: List[str] = []
    properties = lead.get("properties", {})
    checks = [
        ("Business Name", _get_text_value(_get_property(lead, _first_existing_property_name(properties, NAME_FIELD_CANDIDATES) or ""))),
        ("Website", _get_text_value(_get_property(lead, _first_existing_property_name(properties, WEBSITE_CANDIDATES) or ""))),
        ("Email", _get_text_value(_get_property(lead, _first_existing_property_name(properties, EMAIL_FIELD_CANDIDATES) or ""))),
    ]
    for label, value in checks:
        if not value:
            missing.append(label)
    return missing


def _has_duplicate_draft_for_step(lead: Dict[str, Any], target_step: str) -> bool:
    properties = lead.get("properties", {})
    sequence_step_property = _first_existing_property_name(properties, SEQUENCE_STEP_CANDIDATES)
    draft_id_property = _first_existing_property_name(properties, GMAIL_DRAFT_ID_CANDIDATES)
    sequence_step = _get_text_value(_get_property(lead, sequence_step_property or ""))
    draft_id = _get_text_value(_get_property(lead, draft_id_property or ""))
    return bool(draft_id and sequence_step == target_step)


def _draft_ids_from_gmail_response(draft: Dict[str, Any]) -> Tuple[str, str]:
    draft_id = draft.get("id", "")
    thread_id = draft.get("message", {}).get("threadId", "")
    return draft_id, thread_id


def _lead_presence_flag(lead: Dict[str, Any], candidates: List[str]) -> bool:
    properties = lead.get("properties", {})
    property_name = _first_existing_property_name(properties, candidates)
    if not property_name:
        return False
    return bool(_get_text_value(_get_property(lead, property_name)))


def _lead_text_value(lead: Dict[str, Any], candidates: List[str]) -> str:
    properties = lead.get("properties", {})
    property_name = _first_existing_property_name(properties, candidates)
    if not property_name:
        return ""
    return _get_text_value(_get_property(lead, property_name))


def _manual_audit_placeholder_value(value: str) -> Optional[str]:
    normalized = " ".join(value.strip().split())
    if not normalized:
        return None
    for _placeholder_name, pattern in MANUAL_AUDIT_PLACEHOLDER_PATTERNS:
        if pattern.search(normalized):
            return normalized
    return None


def _email_input_placeholder_hits(lead: Dict[str, Any]) -> List[Tuple[str, str]]:
    properties = lead.get("properties", {})
    hits: List[Tuple[str, str]] = []
    seen_fields: set[str] = set()
    for _group_label, candidates in EMAIL_INPUT_FIELD_GROUPS:
        for field_name in candidates:
            if field_name in seen_fields or field_name not in properties:
                continue
            seen_fields.add(field_name)
            placeholder_value = _manual_audit_placeholder_value(_get_text_value(_get_property(lead, field_name)))
            if placeholder_value:
                hits.append((field_name, placeholder_value))
    return hits


def _log_manual_audit_placeholder_skip(lead: Dict[str, Any], hits: List[Tuple[str, str]]) -> None:
    lead_name = _get_lead_name(lead)
    for field_name, placeholder_value in hits:
        print(
            f"Skipped manual-audit placeholder: {lead_name}; "
            f"field: {field_name}; placeholder value: {placeholder_value}"
        )


def _lead_text_count(lead: Dict[str, Any], candidates: List[str]) -> int:
    text = _lead_text_value(lead, candidates)
    if not text:
        return 0
    parts = [part.strip() for part in text.replace("\n", ",").split(",") if part.strip()]
    return len(parts)


def _lead_checkbox_true(lead: Dict[str, Any], candidates: List[str]) -> bool:
    properties = lead.get("properties", {})
    property_name = _first_existing_property_name(properties, candidates)
    if not property_name:
        return False
    return _get_checkbox_value(_get_property(lead, property_name))


def _existing_gmail_artifact(lead: Dict[str, Any]) -> bool:
    properties = lead.get("properties", {})
    draft_property = _first_existing_property_name(properties, GMAIL_DRAFT_ID_CANDIDATES)
    thread_property = _first_existing_property_name(properties, GMAIL_THREAD_ID_CANDIDATES)
    sent_status_property = _first_existing_property_name(properties, GMAIL_SENT_STATUS_CANDIDATES)
    return any(
        _get_text_value(_get_property(lead, prop_name or ""))
        for prop_name in (draft_property, thread_property, sent_status_property)
    )


def _auto_send_is_eligible(lead: Dict[str, Any], sequence: Dict[str, Any], alias_verified: bool) -> tuple[bool, List[str]]:
    reasons: List[str] = []
    if _ops_status_field(lead.get("properties", {})):
        reasons.append("auto-send from draft generation is disabled when Ops Status exists")
    if settings.send_mode != "auto_send_gated":
        reasons.append("send mode is not auto_send_gated")
    if not settings.auto_send_first_emails:
        reasons.append("AUTO_SEND_FIRST_EMAILS is false")
    if settings.require_admin_approval_for_send and not _lead_checkbox_true(lead, ADMIN_APPROVED_CANDIDATES):
        reasons.append("Admin Approved is not true")
    reasons.extend(_draft_block_reasons(lead, require_unique_duplicate=True, require_gmail_match_no_match=True))
    if _lead_checkbox_true(lead, ["Do Not Contact"]):
        reasons.append("Do Not Contact is true")
    casl_basis = _lead_text_value(lead, CASL_BASIS_CANDIDATES)
    if not casl_basis:
        reasons.append("CASL Basis is missing")
    email = _lead_text_value(lead, EMAIL_FIELD_CANDIDATES)
    if not email:
        reasons.append("Email is missing")
    if _existing_gmail_artifact(lead):
        reasons.append("existing Gmail draft/thread/sent record already exists")
    subject_angle = _lead_text_value(lead, SUBJECT_ANGLE_CANDIDATES) or sequence.get("subject_angle", "")
    if not subject_angle:
        reasons.append("Subject Angle is missing")
    clinic_strengths = _lead_text_value(lead, CLINIC_STRENGTHS_CANDIDATES) or sequence.get("clinic_strengths", "")
    if len([part for part in clinic_strengths.replace("\n", ",").split(",") if part.strip()]) < 4:
        reasons.append("Clinic Strengths does not have enough real content")
    if not alias_verified:
        reasons.append("sender alias is not verified")
    if not sequence.get("emails", {}).get("email_1", {}).get("subject"):
        reasons.append("Email 1 subject is missing")
    if not sequence.get("emails", {}).get("email_1", {}).get("body"):
        reasons.append("Email 1 body is missing")
    return not reasons, reasons


def _log_skip_details(lead: Dict[str, Any], reason: str) -> None:
    properties = lead.get("properties", {})
    ops_status_property = _ops_status_field(properties)
    outreach_status_property = _first_existing_property_name(properties, STATUS_FIELD_CANDIDATES)
    gmail_draft_id_property = _first_existing_property_name(properties, GMAIL_DRAFT_ID_CANDIDATES)
    ops_status = _get_text_value(_get_property(lead, ops_status_property or ""))
    outreach_status = _get_text_value(_get_property(lead, outreach_status_property or ""))
    gmail_draft_id_present = bool(_get_text_value(_get_property(lead, gmail_draft_id_property or "")))
    business_name_present = _lead_presence_flag(lead, NAME_FIELD_CANDIDATES)
    email_present = _lead_presence_flag(lead, EMAIL_FIELD_CANDIDATES)
    website_present = _lead_presence_flag(lead, WEBSITE_CANDIDATES)

    print(f"Skipped lead: {_get_lead_name(lead)}")
    print(f"- Business Name present: {'yes' if business_name_present else 'no'}")
    print(f"- Email present: {'yes' if email_present else 'no'}")
    print(f"- Website present: {'yes' if website_present else 'no'}")
    if ops_status_property:
        print(f"- Ops Status: {ops_status or '<empty>'}")
    print(f"- Outreach Status: {outreach_status or '<empty>'}")
    print(f"- Gmail Draft ID present: {'yes' if gmail_draft_id_present else 'no'}")
    print(f"- Exact skip reason: {reason}")


def _sequence_angle_bucket(sequence: Dict[str, Any]) -> str:
    angle_bucket = sequence.get("angle_bucket")
    if isinstance(angle_bucket, str) and angle_bucket.strip():
        return angle_bucket.strip()
    return FALLBACK_ANGLE_BUCKET


def query_new_leads(limit: int = MAX_DRAFTS_PER_RUN) -> List[Dict[str, Any]]:
    return _query_draft_candidates(limit, require_top_issue=True, require_angle_bucket=True)


def query_backfill_leads(limit: int = MAX_DRAFTS_PER_RUN) -> List[Dict[str, Any]]:
    return _query_draft_candidates(limit, require_top_issue=True, require_angle_bucket=True)


def query_fallback_leads(limit: int = MAX_DRAFTS_PER_RUN) -> List[Dict[str, Any]]:
    return _query_draft_candidates(limit, require_top_issue=False, require_angle_bucket=False)


def _collect_draft_candidates() -> List[Tuple[str, Dict[str, Any]]]:
    selected: List[Tuple[str, Dict[str, Any]]] = []
    seen_ids: set[str] = set()
    stage_query_counts: Dict[str, int] = {}
    stage_selected_counts: Dict[str, int] = {stage_name: 0 for stage_name, *_ in STAGE_CONFIGS}
    schema = get_data_source_schema()
    properties = schema.get("properties", {})
    ops_status_property = _ops_status_field(properties)

    def _append_stage(stage_name: str, leads: List[Dict[str, Any]]) -> int:
        added = 0
        for lead in leads:
            lead_id = lead.get("id", "")
            if not lead_id or lead_id in seen_ids:
                continue
            seen_ids.add(lead_id)
            selected.append((stage_name, lead))
            added += 1
        return added

    if ops_status_property:
        leads = _query_ops_ready_to_draft_candidates(limit=MAX_DRAFTS_PER_RUN)
        stage_query_counts[STAGE_OPS_READY] = len(leads)
        stage_selected_counts[STAGE_OPS_READY] = _append_stage(STAGE_OPS_READY, leads)
        print("Draft candidate source: Ops Status")
        print("Draft candidate staging summary:")
        print(f"- ops_ready_to_draft queried: {stage_query_counts.get(STAGE_OPS_READY, 0)}")
        print(f"- ops_ready_to_draft selected: {stage_selected_counts.get(STAGE_OPS_READY, 0)}")
        print(f"- unique candidates selected: {len(selected)}")
        return selected

    if not ALLOW_LEGACY_STATUS_FALLBACK:
        print("Draft candidate source: Ops Status")
        print("Draft candidate staging summary:")
        print("- Ops Status field missing: fail closed")
        print("- legacy fallback enabled: false")
        print("- legacy approval path used: false")
        print("- unique candidates selected: 0")
        return selected

    print("Draft candidate source: legacy Lead Status / Outreach Status fallback")
    for stage_name, _require_top_issue, _require_angle_bucket in STAGE_CONFIGS:
        if stage_name == STAGE_BACKFILL and len(selected) >= MAX_DRAFTS_PER_RUN:
            stage_query_counts[stage_name] = 0
            continue
        if stage_name == STAGE_FALLBACK and len(selected) >= MIN_DRAFTS_TARGET:
            stage_query_counts[stage_name] = 0
            continue

        if stage_name == STAGE_NEW_LEADS:
            leads = query_new_leads(limit=MAX_DRAFTS_PER_RUN)
        elif stage_name == STAGE_BACKFILL:
            leads = query_backfill_leads(limit=MAX_DRAFTS_PER_RUN)
        else:
            leads = query_fallback_leads(limit=MAX_DRAFTS_PER_RUN)

        stage_query_counts[stage_name] = len(leads)
        stage_selected_counts[stage_name] = _append_stage(stage_name, leads)

    print("Draft candidate staging summary:")
    print(f"- new leads queried: {stage_query_counts.get(STAGE_NEW_LEADS, 0)}")
    print(f"- new leads selected: {stage_selected_counts.get(STAGE_NEW_LEADS, 0)}")
    print(f"- backfill queried: {stage_query_counts.get(STAGE_BACKFILL, 0)}")
    print(f"- backfill selected: {stage_selected_counts.get(STAGE_BACKFILL, 0)}")
    print(f"- fallback queried: {stage_query_counts.get(STAGE_FALLBACK, 0)}")
    print(f"- fallback selected: {stage_selected_counts.get(STAGE_FALLBACK, 0)}")
    print(f"- unique candidates selected: {len(selected)}")
    return selected


def query_all_leads_for_debug() -> List[Dict[str, Any]]:
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


def print_no_eligible_lead_debug(schema: Dict[str, Any]) -> None:
    schema_properties = schema.get("properties", {})
    ops_status_property = _ops_status_field(schema_properties)
    outreach_status_property = _first_existing_property_name(schema_properties, STATUS_FIELD_CANDIDATES)
    email_property = _first_existing_property_name(schema_properties, EMAIL_FIELD_CANDIDATES)
    dnc_property = _first_existing_property_name(schema_properties, DO_NOT_CONTACT_CANDIDATES)

    leads = query_all_leads_for_debug()
    counts = {
        "eligible": 0,
        "status": 0,
        "email": 0,
        "website": 0,
        "top_issue": 0,
        "angle_bucket": 0,
        "do_not_contact": 0,
    }
    skipped: List[Tuple[str, str, str, str]] = []

    for lead in leads:
        lead_name = _get_lead_name(lead)
        ops_status_value = _get_text_value(_get_property(lead, ops_status_property or ""))
        outreach_status_value = _get_text_value(_get_property(lead, outreach_status_property or ""))
        workflow_status_value = ops_status_value if ops_status_property else outreach_status_value
        workflow_status_label = ops_status_property or outreach_status_property or "Outreach Status"
        email_value = _get_property(lead, email_property or "").get("email") or _get_text_value(
            _get_property(lead, email_property or "")
        )
        website_value = _get_text_value(
            _get_property(lead, _first_existing_property_name(lead.get("properties", {}), WEBSITE_CANDIDATES) or "")
        )
        top_issue_value = _get_text_value(
            _get_property(lead, _first_existing_property_name(lead.get("properties", {}), TOP_ISSUE_CANDIDATES) or "")
        )
        angle_bucket_value = _get_text_value(
            _get_property(lead, _first_existing_property_name(lead.get("properties", {}), ANGLE_BUCKET_CANDIDATES) or "")
        )
        do_not_contact = _get_checkbox_value(_get_property(lead, dnc_property or ""))

        reason = ""
        if ops_status_property and ops_status_value != OPS_READY_TO_DRAFT:
            counts["status"] += 1
            reason = f"{workflow_status_label} was not {OPS_READY_TO_DRAFT}"
        elif not ops_status_property and outreach_status_value not in DRAFT_READY_STATUS_VALUES:
            counts["status"] += 1
            reason = f"{workflow_status_label} was not draft-ready"
        elif not email_value:
            counts["email"] += 1
            reason = f"{email_property or 'Email'} was missing"
        elif not website_value:
            counts["website"] += 1
            reason = "Website was missing"
        elif not top_issue_value:
            counts["top_issue"] += 1
            reason = "Top 3 Issues was missing"
        elif not angle_bucket_value:
            counts["angle_bucket"] += 1
            reason = "Angle Bucket was missing"
        elif do_not_contact:
            counts["do_not_contact"] += 1
            reason = f"{dnc_property or 'Do Not Contact'} was true"
        else:
            counts["eligible"] += 1

        if reason and len(skipped) < 10:
            skipped.append((lead_name, workflow_status_value or "<empty>", email_value or "<empty>", reason))

    print(f"Total leads checked: {len(leads)}")
    print(f"Number eligible: {counts['eligible']}")
    print(f"Number skipped because {ops_status_property or 'Outreach Status'} is not draft-ready: {counts['status']}")
    print(f"Number skipped because Email is missing: {counts['email']}")
    print(f"Number skipped because Website is missing: {counts['website']}")
    print(f"Number skipped because Top 3 Issues is missing: {counts['top_issue']}")
    print(f"Number skipped because Angle Bucket is missing: {counts['angle_bucket']}")
    print(f"Number skipped because Do Not Contact / status is Do Not Contact: {counts['do_not_contact']}")
    print("Skipped leads:")
    for lead_name, workflow_status, email, reason in skipped:
        print(
            f"- Practice Name: {lead_name}; {ops_status_property or 'Outreach Status'}: {workflow_status}; "
            f"Email: {email}; Reason: {reason}"
        )


def print_validation_warnings(schema: Dict[str, Any]) -> None:
    schema_properties = schema.get("properties", {})
    outreach_status_property = _first_existing_property_name(schema_properties, STATUS_FIELD_CANDIDATES)
    email_draft_property = _first_existing_property_name(schema_properties, EMAIL_1_DRAFT_CANDIDATES)
    email_1_date_property = _first_existing_property_name(schema_properties, EMAIL_1_DATE_CANDIDATES)

    if not outreach_status_property:
        return

    leads = query_all_leads_for_debug()
    for lead in leads:
        lead_name = _get_lead_name(lead)
        outreach_status = _get_text_value(_get_property(lead, outreach_status_property))

        if outreach_status in {"Draft Ready", "draft_ready", "outreach_drafted"} and email_draft_property:
            email_draft = _get_text_value(_get_property(lead, email_draft_property))
            if not email_draft:
                print(f"Warning: {lead_name} is draft-ready but Email Draft is empty.")

        if outreach_status in {"Email 1 Sent", "outreach_sent"} and email_1_date_property:
            if not _has_date_value(_get_property(lead, email_1_date_property)):
                print(f"Warning: {lead_name} is Email 1 Sent but Email 1 Date is missing.")


def update_notion_lead(page_id: str, updates: Dict[str, Any]) -> None:
    client = get_client()
    client.pages.update(page_id=page_id, properties=updates)


def infer_tier_from_top_issue(top_issue: str) -> str:
    normalized = top_issue.lower()
    hot_keywords = (
        "broken",
        "no website",
        "expired",
        "severe",
        "not working",
        "old covid",
        "outdated",
        "missing booking",
        "weak booking",
        "no clear patient journey",
    )
    warm_keywords = (
        "multilingual",
        "translation",
        "confusing",
        "content-heavy",
        "slow",
        "mobile",
        "high-value",
        "service organization",
    )

    if any(keyword in normalized for keyword in hot_keywords):
        return "HOT"
    if any(keyword in normalized for keyword in warm_keywords):
        return "WARM"
    return "COOL"


def build_email_1_sequence_updates(
    schema: Dict[str, Any],
    lead: Dict[str, Any],
    sequence: Dict[str, Any],
    draft_id: str = "",
    thread_id: str = "",
    sent_message_id: str = "",
    sent_status: str = "",
    auto_send_eligible: bool = False,
) -> Dict[str, Any]:
    properties = schema.get("properties", {})
    updates: Dict[str, Any] = {}

    emails = sequence["emails"]
    _add_update_if_empty(updates, properties, lead, EMAIL_1_SUBJECT_CANDIDATES, emails["email_1"]["subject"])
    _add_update_if_empty(updates, properties, lead, EMAIL_1_DRAFT_CANDIDATES, emails["email_1"]["body"])
    _add_update(updates, properties, EMAIL_2_SUBJECT_CANDIDATES, emails["email_2"]["subject"])
    _add_update(updates, properties, EMAIL_2_DRAFT_CANDIDATES, emails["email_2"]["body"])
    _add_update(updates, properties, EMAIL_3_SUBJECT_CANDIDATES, emails["email_3"]["subject"])
    _add_update(updates, properties, EMAIL_3_DRAFT_CANDIDATES, emails["email_3"]["body"])
    _add_update(updates, properties, DRAFT_CREATED_DATE_CANDIDATES, datetime.now(timezone.utc).date().isoformat())
    _add_update_if_empty(updates, properties, lead, TOP_ISSUE_CANDIDATES, sequence["top_issue"])
    _add_update(updates, properties, ANGLE_BUCKET_CANDIDATES, _sequence_angle_bucket(sequence))
    _add_update_if_empty(updates, properties, lead, OUTREACH_ANGLE_CANDIDATES, sequence["outreach_angle"])
    _add_update_if_empty(updates, properties, lead, RECOMMENDED_OFFER_CANDIDATES, sequence["recommended_offer"])
    _add_update(updates, properties, LOOM_RECOMMENDED_CANDIDATES, sequence["loom_recommended"])
    if sequence["loom_script"]:
        _add_update(updates, properties, LOOM_SCRIPT_CANDIDATES, sequence["loom_script"])
    _add_update_if_empty(updates, properties, lead, SUBJECT_ANGLE_CANDIDATES, sequence["subject_angle"])
    _add_update_if_empty(updates, properties, lead, CLINIC_STRENGTHS_CANDIDATES, sequence["clinic_strengths"])
    _add_update_if_empty(updates, properties, lead, STRONGEST_ADVANTAGE_CANDIDATES, sequence["strongest_advantage"])
    _add_update_if_empty(updates, properties, lead, PATIENT_TYPE_LOCATION_ANGLE_CANDIDATES, sequence["patient_type_location_angle"])
    _add_update_if_empty(updates, properties, lead, TOP_3_ISSUES_CANDIDATES, sequence["top_3_issues"])
    _add_update_if_empty(updates, properties, lead, BUSINESS_IMPACT_CANDIDATES, sequence["business_impact"])
    _add_update_if_empty(updates, properties, lead, RECOMMENDED_FIX_CANDIDATES, sequence["recommended_fix"])
    _add_update_if_empty(updates, properties, lead, EMAIL_ANGLE_CANDIDATES, sequence["email_angle"])
    _add_update_if_empty(updates, properties, lead, LOOM_LINK_CANDIDATES, sequence["loom_link"])
    _add_update(updates, properties, SEND_MODE_CANDIDATES, settings.send_mode)
    _add_update(updates, properties, AUTO_SEND_ELIGIBLE_CANDIDATES, auto_send_eligible)

    tier_property = _first_existing_property_name(properties, TIER_CANDIDATES)
    top_issue_property = _first_existing_property_name(properties, TOP_ISSUE_CANDIDATES)
    if tier_property and top_issue_property and not _get_text_value(_get_property(lead, tier_property)):
        tier_type = properties[tier_property].get("type")
        inferred_tier = infer_tier_from_top_issue(sequence["top_issue"])
        if tier_type == "select":
            updates[tier_property] = {"select": {"name": inferred_tier}}
        elif tier_type == "rich_text":
            updates[tier_property] = {"rich_text": [{"type": "text", "text": {"content": inferred_tier}}]}

    if draft_id:
        _add_update(updates, properties, GMAIL_DRAFT_ID_CANDIDATES, draft_id)
        if thread_id:
            _add_update(updates, properties, GMAIL_THREAD_ID_CANDIDATES, thread_id)
        _add_update(updates, properties, SEQUENCE_STEP_CANDIDATES, "Email 1 Drafted")
        if _first_existing_property_name(properties, ["Lead Status"]):
            _add_update(updates, properties, ["Lead Status"], "outreach_drafted")
        else:
            _add_update(updates, properties, OUTREACH_STATUS_FIELD_CANDIDATES, "draft_ready")
        _add_update(updates, properties, LAST_EMAIL_DRAFTED_AT_CANDIDATES, datetime.now(timezone.utc).date().isoformat())

    if sent_message_id:
        _add_update(updates, properties, GMAIL_THREAD_ID_CANDIDATES, thread_id or sent_message_id)
        _add_update(updates, properties, GMAIL_SENT_STATUS_CANDIDATES, sent_status or "Sent")
        _add_update(updates, properties, SEQUENCE_STEP_CANDIDATES, "Email 1 Sent")
        if _first_existing_property_name(properties, ["Lead Status"]):
            _add_update(updates, properties, ["Lead Status"], "outreach_sent")
        else:
            _add_update(updates, properties, OUTREACH_STATUS_FIELD_CANDIDATES, "Email 1 Sent")
        _add_update(updates, properties, LAST_OUTREACH_DATE_CANDIDATES, datetime.now(timezone.utc).date().isoformat())

    return updates


def build_followup_updates(
    schema: Dict[str, Any],
    step_name: str,
    draft_id: str,
    thread_id: str = "",
) -> Dict[str, Any]:
    properties = schema.get("properties", {})
    updates: Dict[str, Any] = {}
    _add_update(updates, properties, GMAIL_DRAFT_ID_CANDIDATES, draft_id)
    if thread_id:
        _add_update(updates, properties, GMAIL_THREAD_ID_CANDIDATES, thread_id)
    _add_update(updates, properties, SEQUENCE_STEP_CANDIDATES, step_name)
    return updates


def build_manual_sent_updates(schema: Dict[str, Any], step_name: str, next_followup_days: int) -> Dict[str, Any]:
    properties = schema.get("properties", {})
    today = datetime.now(timezone.utc).date()
    updates: Dict[str, Any] = {}
    _add_update(updates, properties, LAST_OUTREACH_DATE_CANDIDATES, today.isoformat())
    _add_update(updates, properties, NEXT_FOLLOW_UP_DATE_CANDIDATES, (today + timedelta(days=next_followup_days)).isoformat())
    _add_update(updates, properties, SEQUENCE_STEP_CANDIDATES, step_name)
    return updates


def process_lead(lead: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[str]]:
    properties = lead.get("properties", {})
    email_property = _first_existing_property_name(properties, EMAIL_FIELD_CANDIDATES)
    email = ""
    if email_property:
        email_value = _get_property(lead, email_property)
        email = email_value.get("email") or _get_text_value(email_value)
    if not email:
        return {}, None

    sequence = generate_email_sequence(lead)
    return sequence, email


def query_due_followups() -> List[Dict[str, Any]]:
    leads = query_all_leads_for_debug()
    due: List[Dict[str, Any]] = []
    today = datetime.now(timezone.utc).date()
    for lead in leads:
        properties = lead.get("properties", {})
        ops_status_property = _ops_status_field(properties)
        outreach_status_property = _first_existing_property_name(properties, STATUS_FIELD_CANDIDATES)
        reply_status_property = _first_existing_property_name(properties, REPLY_STATUS_CANDIDATES)
        next_followup_property = _first_existing_property_name(properties, NEXT_FOLLOW_UP_DATE_CANDIDATES)
        follow_up_due_now_property = _first_existing_property_name(properties, FOLLOW_UP_DUE_NOW_CANDIDATES)
        outreach_status = _get_text_value(_get_property(lead, outreach_status_property or ""))
        ops_status = _get_text_value(_get_property(lead, ops_status_property or "")).strip().lower()
        reply_status = _get_text_value(_get_property(lead, reply_status_property or ""))
        next_followup = _get_date_value(_get_property(lead, next_followup_property or ""))
        follow_up_due_now = False
        if follow_up_due_now_property:
            follow_up_due_now = _is_true_like(_get_formula_value(_get_property(lead, follow_up_due_now_property)))

        if _lead_has_terminal_status(lead):
            continue
        if ops_status_property and ops_status != OPS_SENT:
            continue
        if not ops_status_property and not ALLOW_LEGACY_STATUS_FALLBACK:
            continue
        if not _lead_is_canada(lead):
            continue
        if _lead_duplicate_status(lead) in BLOCKED_DUPLICATE_STATUSES:
            continue
        if reply_status == "Replied" or outreach_status in {"Replied", "Closed"}:
            continue
        if follow_up_due_now_property:
            if follow_up_due_now:
                due.append(lead)
            continue
        if outreach_status in {"Email 1 Sent", "Email 2 Sent"} and next_followup and today >= next_followup:
            due.append(lead)
    return due[:MAX_DRAFTS_PER_RUN]


def _sequence_email_from_lead(lead: Dict[str, Any], step: str) -> Tuple[str, str]:
    properties = lead.get("properties", {})
    if step == "email_2":
        subject_property = _first_existing_property_name(properties, EMAIL_2_SUBJECT_CANDIDATES)
        draft_property = _first_existing_property_name(properties, EMAIL_2_DRAFT_CANDIDATES)
    else:
        subject_property = _first_existing_property_name(properties, EMAIL_3_SUBJECT_CANDIDATES)
        draft_property = _first_existing_property_name(properties, EMAIL_3_DRAFT_CANDIDATES)
    return (
        _get_text_value(_get_property(lead, subject_property or "")),
        _get_text_value(_get_property(lead, draft_property or "")),
    )


def _handle_missing_required_fields(schema: Dict[str, Any], lead: Dict[str, Any], missing: List[str]) -> None:
    note = f"Email 1 draft skipped because required fields are missing: {', '.join(missing)}"
    if settings.dry_run:
        print(note)
        return
    updates = _append_scrape_note_update(schema, lead, note)
    if updates:
        update_notion_lead(lead["id"], updates)


def _process_new_lead(schema: Dict[str, Any], lead: Dict[str, Any]) -> str:
    lead_name = _get_lead_name(lead)
    properties = lead.get("properties", {})
    ops_status_property = _ops_status_field(properties)
    outreach_status_property = _first_existing_property_name(properties, STATUS_FIELD_CANDIDATES)
    email_property = _first_existing_property_name(properties, EMAIL_FIELD_CANDIDATES)
    website_property = _first_existing_property_name(properties, WEBSITE_CANDIDATES)
    name_property = _first_existing_property_name(properties, NAME_FIELD_CANDIDATES)
    gmail_draft_id_property = _first_existing_property_name(properties, GMAIL_DRAFT_ID_CANDIDATES)

    ops_status = _get_text_value(_get_property(lead, ops_status_property or ""))
    outreach_status = _get_text_value(_get_property(lead, outreach_status_property or ""))
    email = _get_text_value(_get_property(lead, email_property or ""))
    website = _get_text_value(_get_property(lead, website_property or ""))
    business_name = _get_text_value(_get_property(lead, name_property or ""))
    gmail_draft_id = _get_text_value(_get_property(lead, gmail_draft_id_property or ""))

    blocked_reasons = _draft_block_reasons(lead, require_unique_duplicate=False, require_gmail_match_no_match=False)
    if blocked_reasons:
        _log_skip_details(lead, "; ".join(blocked_reasons))
        return "skipped_wrong_status"
    if ops_status_property and ops_status != OPS_READY_TO_DRAFT:
        _log_skip_details(lead, f"Ops Status is {ops_status or '<empty>'}")
        return "skipped_wrong_status"
    if not ops_status_property and not ALLOW_LEGACY_STATUS_FALLBACK:
        _log_skip_details(lead, "Ops Status is missing and legacy status fallback is disabled")
        return "skipped_wrong_status"
    if not ops_status_property and outreach_status not in DRAFT_READY_STATUS_VALUES:
        _log_skip_details(lead, f"Outreach Status is {outreach_status or '<empty>'}")
        return "skipped_wrong_status"
    if not business_name:
        _log_skip_details(lead, "Business Name is missing")
        return "skipped_missing_business_name"
    if not website:
        _log_skip_details(lead, "Website is missing")
        return "skipped_missing_website"
    if not email:
        _log_skip_details(lead, "Email is missing")
        return "skipped_missing_email"
    if gmail_draft_id:
        _log_skip_details(lead, "Gmail Draft ID already exists")
        return "skipped_already_drafted"
    placeholder_hits = _email_input_placeholder_hits(lead)
    if placeholder_hits:
        _log_manual_audit_placeholder_skip(lead, placeholder_hits)
        return "skipped_manual_audit_placeholder"

    sequence, _ = process_lead(lead)
    verified_from_email = get_preferred_send_as_email(settings.gmail_send_as_email)
    alias_verified = bool(verified_from_email)
    if settings.gmail_send_as_email and not alias_verified:
        print(
            f"Warning: Gmail send-as alias {settings.gmail_send_as_email} is not verified. "
            "Draft mode will continue, but auto-send must remain blocked."
        )

    email_1 = sequence["emails"]["email_1"]

    if settings.dry_run:
        print(f"Lead: {lead_name}")
        print(f"Angle Bucket: {_sequence_angle_bucket(sequence)}")
        print(f"To: {email}")
        print(f"Email 1 Subject: {email_1['subject']}")
        print("Email 1 Body:")
        print(email_1["body"])
        print("Email 2 Draft:")
        print(sequence["emails"]["email_2"]["body"])
        print("Email 3 Draft:")
        print(sequence["emails"]["email_3"]["body"])
        print("-" * 40)
        return "dry_run_email_1"

    auto_send_eligible, auto_send_reasons = _auto_send_is_eligible(lead, sequence, alias_verified)
    if auto_send_eligible:
        print(f"Auto-send approved for {lead_name}")
    else:
        print(f"Auto-send blocked for {lead_name}: {', '.join(auto_send_reasons)}")

    if settings.send_mode == "auto_send_gated" and settings.auto_send_first_emails and auto_send_eligible:
        sent = send_email_message(
            email,
            email_1["subject"],
            email_1["body"],
            from_email=verified_from_email,
            label_name=settings.gmail_label,
        )
        sent_id = sent.get("id", "")
        thread_id = sent.get("threadId", "")
        updates = build_email_1_sequence_updates(
            schema,
            lead,
            sequence,
            thread_id=thread_id,
            sent_message_id=sent_id,
            sent_status="Sent",
            auto_send_eligible=True,
        )
        if updates:
            update_notion_lead(lead["id"], updates)
        print(f"Sent Email 1 for {lead_name} via verified alias {settings.gmail_send_as_email}")
        return "email_1_sent"

    updates = build_email_1_sequence_updates(schema, lead, sequence, auto_send_eligible=auto_send_eligible)
    if updates:
        update_notion_lead(lead["id"], updates)
        print(f"Generated sequence for {lead_name}; angle assigned: {_sequence_angle_bucket(sequence)}")

    if not settings.create_gmail_drafts:
        print(f"Saved sequence only for {lead_name}; Gmail draft creation disabled")
        return "sequence_saved"

    if _has_duplicate_draft_for_step(lead, "Email 1 Drafted"):
        print(f"Skipped {lead_name}: draft already exists")
        return "duplicate_draft"

    draft = create_draft(
        email,
        email_1["subject"],
        email_1["body"],
        from_email=verified_from_email,
        label_name=settings.gmail_label,
    )
    draft_id, thread_id = _draft_ids_from_gmail_response(draft)
    if not draft_id:
        print(f"Skipped {lead_name}: Gmail did not return a draft id")
        return "skipped"

    updates = build_email_1_sequence_updates(
        schema,
        lead,
        sequence,
        draft_id=draft_id,
        thread_id=thread_id,
        auto_send_eligible=auto_send_eligible,
    )
    if updates:
        update_notion_lead(lead["id"], updates)
    print(f"Created Email 1 Gmail draft for {lead_name}")
    return "email_1_created"


def _process_due_followup(schema: Dict[str, Any], lead: Dict[str, Any]) -> str:
    lead_name = _get_lead_name(lead)
    properties = lead.get("properties", {})
    ops_status_property = _ops_status_field(properties)
    outreach_status_property = _first_existing_property_name(properties, STATUS_FIELD_CANDIDATES)
    sequence_step_property = _first_existing_property_name(properties, SEQUENCE_STEP_CANDIDATES)
    outreach_status = _get_text_value(_get_property(lead, outreach_status_property or ""))
    ops_status = _get_text_value(_get_property(lead, ops_status_property or "")).strip().lower()
    sequence_step = _get_text_value(_get_property(lead, sequence_step_property or ""))
    email_property = _first_existing_property_name(properties, EMAIL_FIELD_CANDIDATES)
    email = _get_text_value(_get_property(lead, email_property or ""))
    verified_from_email = get_preferred_send_as_email(settings.gmail_send_as_email)
    alias_verified = bool(verified_from_email)
    lead_status = _normalize_text(outreach_status)
    blocked_reasons = _draft_block_reasons(lead, require_unique_duplicate=False, require_gmail_match_no_match=False)
    if blocked_reasons:
        print(f"Skipped {lead_name}: {', '.join(blocked_reasons)}")
        return "skipped"
    if ops_status_property and ops_status != OPS_SENT:
        print(f"Skipped {lead_name}: Ops Status is {ops_status or '<empty>'}")
        return "skipped"
    if not ops_status_property and not ALLOW_LEGACY_STATUS_FALLBACK:
        print(f"Skipped {lead_name}: Ops Status is missing and legacy status fallback is disabled")
        return "skipped"

    if sequence_step == "Email 1 Sent" or outreach_status == "Email 1 Sent" or (lead_status == "outreach_sent" and not sequence_step):
        target_step = "Email 2 Drafted"
        email_step = "email_2"
    elif sequence_step == "Email 2 Sent" or outreach_status == "Email 2 Sent":
        target_step = "Email 3 Drafted"
        email_step = "email_3"
    else:
        return "skipped"

    if _has_duplicate_draft_for_step(lead, target_step):
        print(f"Skipped {lead_name}: draft already exists")
        return "duplicate_draft"

    subject, body = _sequence_email_from_lead(lead, email_step)
    if not email or not subject or not body:
        print(f"Skipped {lead_name}: missing email address or {target_step} copy")
        return "skipped"

    if settings.dry_run:
        print(f"Due follow-up: {lead_name}")
        print(f"To: {email}")
        print(f"Subject: {subject}")
        print("Body:")
        print(body)
        print("-" * 40)
        return f"dry_run_{email_step}"

    if not settings.create_gmail_drafts:
        print(f"Skipped {lead_name}: Gmail draft creation disabled")
        return "skipped"

    draft = create_draft(
        email,
        subject,
        body,
        from_email=verified_from_email,
        label_name=settings.gmail_label,
    )
    draft_id, thread_id = _draft_ids_from_gmail_response(draft)
    if not draft_id:
        print(f"Skipped {lead_name}: Gmail did not return a draft id")
        return "skipped"

    updates = build_followup_updates(schema, target_step, draft_id, thread_id)
    if updates:
        update_notion_lead(lead["id"], updates)
    print(f"Created {target_step} Gmail draft for {lead_name}")
    return "email_2_created" if email_step == "email_2" else "email_3_created"


def _sync_manual_sent_steps(schema: Dict[str, Any]) -> None:
    leads = query_all_leads_for_debug()
    today = datetime.now(timezone.utc).date()
    for lead in leads:
        properties = lead.get("properties", {})
        outreach_status_property = _first_existing_property_name(properties, STATUS_FIELD_CANDIDATES)
        sequence_step_property = _first_existing_property_name(properties, SEQUENCE_STEP_CANDIDATES)
        last_outreach_property = _first_existing_property_name(properties, LAST_OUTREACH_DATE_CANDIDATES)
        next_followup_property = _first_existing_property_name(properties, NEXT_FOLLOW_UP_DATE_CANDIDATES)
        outreach_status = _get_text_value(_get_property(lead, outreach_status_property or ""))
        sequence_step = _get_text_value(_get_property(lead, sequence_step_property or ""))
        last_outreach = _get_date_value(_get_property(lead, last_outreach_property or ""))
        next_followup = _get_date_value(_get_property(lead, next_followup_property or ""))

        if (
            sequence_step == "Email 1 Sent"
            or outreach_status == "Email 1 Sent"
            or (outreach_status == "outreach_sent" and not sequence_step)
        ) and (sequence_step != "Email 1 Sent" or not last_outreach or not next_followup):
            if settings.dry_run:
                print(f"DRY RUN: would set follow-up schedule for {_get_lead_name(lead)} after Email 1 Sent")
                continue
            updates = build_manual_sent_updates(schema, "Email 1 Sent", 3)
            if updates:
                update_notion_lead(lead["id"], updates)
        elif (
            sequence_step == "Email 2 Sent"
            or outreach_status == "Email 2 Sent"
        ) and (sequence_step != "Email 2 Sent" or not last_outreach or not next_followup):
            if settings.dry_run:
                print(f"DRY RUN: would set follow-up schedule for {_get_lead_name(lead)} after Email 2 Sent")
                continue
            updates = build_manual_sent_updates(schema, "Email 2 Sent", 5)
            if updates:
                update_notion_lead(lead["id"], updates)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Gmail draft outreach from Notion leads.")
    parser.add_argument(
        "--mode",
        choices=("all", "email1", "followups"),
        default="email1",
        help="Run the full draft agent, only Email 1 creation, or only due follow-up drafts.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    schema = get_data_source_schema()
    properties = schema.get("properties", {})
    ops_status_property = _ops_status_field(properties)
    outreach_status_property = _first_existing_property_name(properties, STATUS_FIELD_CANDIDATES)
    if not ops_status_property and not outreach_status_property and ALLOW_LEGACY_STATUS_FALLBACK:
        _print_available_properties(properties)
        raise ValueError("Ops Status or Lead Status / Outreach Status property is missing from the Notion data source.")
    if not ops_status_property and not ALLOW_LEGACY_STATUS_FALLBACK:
        print("Warning: Ops Status property is missing; legacy status fallback is disabled, so email1 drafting will fail closed.")
    print(f"workflow source: {'Ops Status' if ops_status_property else 'Ops Status missing'}")
    print(f"legacy fallback enabled: {'true' if ALLOW_LEGACY_STATUS_FALLBACK else 'false'}")
    print(
        "active approval source: "
        f"{'Ops Status only' if ops_status_property else ('legacy fallback' if ALLOW_LEGACY_STATUS_FALLBACK else 'none - fail closed')}"
    )
    print(
        "legacy approval path used: "
        f"{'true' if not ops_status_property and ALLOW_LEGACY_STATUS_FALLBACK else 'false'}"
    )
    print_validation_warnings(schema)
    summary = {
        "records_checked": 0,
        "eligible_records": 0,
        "drafts_attempted": 0,
        "gmail_drafts_created": 0,
        "gmail_emails_sent": 0,
        "ops_ready_used": 0,
        "new_leads_used": 0,
        "backfill_used": 0,
        "fallback_used": 0,
        "skipped_missing_email": 0,
        "skipped_missing_website": 0,
        "skipped_already_drafted": 0,
        "skipped_wrong_status": 0,
        "skipped_missing_business_name": 0,
        "skipped_manual_audit_placeholder": 0,
        "errors": 0,
        "shortfall_reason": "",
    }

    if args.mode in {"all", "email1"}:
        leads = _collect_draft_candidates()

        if not leads:
            print("No eligible leads found.")
            print_no_eligible_lead_debug(schema)
        else:
            for stage_name, lead in leads:
                if summary["drafts_attempted"] >= MAX_DRAFTS_PER_RUN:
                    print(f"Draft cap reached: {MAX_DRAFTS_PER_RUN}")
                    break
                summary["records_checked"] += 1
                try:
                    result = _process_new_lead(schema, lead)
                    if result == "email_1_created":
                        summary["eligible_records"] += 1
                        summary["drafts_attempted"] += 1
                        summary["gmail_drafts_created"] += 1
                        if stage_name == STAGE_OPS_READY:
                            summary["ops_ready_used"] += 1
                        elif stage_name == STAGE_NEW_LEADS:
                            summary["new_leads_used"] += 1
                        elif stage_name == STAGE_BACKFILL:
                            summary["backfill_used"] += 1
                        elif stage_name == STAGE_FALLBACK:
                            summary["fallback_used"] += 1
                    elif result == "sequence_saved":
                        summary["eligible_records"] += 1
                        summary["drafts_attempted"] += 1
                        if stage_name == STAGE_OPS_READY:
                            summary["ops_ready_used"] += 1
                        elif stage_name == STAGE_NEW_LEADS:
                            summary["new_leads_used"] += 1
                        elif stage_name == STAGE_BACKFILL:
                            summary["backfill_used"] += 1
                        elif stage_name == STAGE_FALLBACK:
                            summary["fallback_used"] += 1
                    elif result == "dry_run_email_1":
                        summary["eligible_records"] += 1
                        summary["drafts_attempted"] += 1
                        if stage_name == STAGE_OPS_READY:
                            summary["ops_ready_used"] += 1
                        elif stage_name == STAGE_NEW_LEADS:
                            summary["new_leads_used"] += 1
                        elif stage_name == STAGE_BACKFILL:
                            summary["backfill_used"] += 1
                        elif stage_name == STAGE_FALLBACK:
                            summary["fallback_used"] += 1
                    elif result == "email_1_sent":
                        summary["eligible_records"] += 1
                        summary["drafts_attempted"] += 1
                        summary["gmail_emails_sent"] += 1
                        if stage_name == STAGE_OPS_READY:
                            summary["ops_ready_used"] += 1
                        elif stage_name == STAGE_NEW_LEADS:
                            summary["new_leads_used"] += 1
                        elif stage_name == STAGE_BACKFILL:
                            summary["backfill_used"] += 1
                        elif stage_name == STAGE_FALLBACK:
                            summary["fallback_used"] += 1
                    elif result == "skipped_missing_email":
                        summary["skipped_missing_email"] += 1
                    elif result == "skipped_missing_website":
                        summary["skipped_missing_website"] += 1
                    elif result == "skipped_missing_business_name":
                        summary["skipped_missing_business_name"] += 1
                    elif result == "skipped_already_drafted":
                        summary["skipped_already_drafted"] += 1
                    elif result == "skipped_wrong_status":
                        summary["skipped_wrong_status"] += 1
                    elif result == "skipped_manual_audit_placeholder":
                        summary["skipped_manual_audit_placeholder"] += 1
                except Exception as exc:
                    summary["errors"] += 1
                    print(f"Error processing {_get_lead_name(lead)}: {exc}")

            total_outreach_artifacts = summary["gmail_drafts_created"] + summary["gmail_emails_sent"]
            target_progress = summary["drafts_attempted"] if settings.dry_run else total_outreach_artifacts
            if target_progress < MIN_DRAFTS_TARGET:
                if summary["drafts_attempted"] >= MAX_DRAFTS_PER_RUN:
                    summary["shortfall_reason"] = (
                        f"hard cap reached before soft target: created, sent, or previewed {target_progress} of "
                        f"{MIN_DRAFTS_TARGET}; cap is {MAX_DRAFTS_PER_RUN}"
                    )
                elif not summary["drafts_attempted"]:
                    if ops_status_property:
                        summary["shortfall_reason"] = "no eligible candidates matched Ops Status ready_to_draft"
                    elif ALLOW_LEGACY_STATUS_FALLBACK:
                        summary["shortfall_reason"] = "no eligible candidates matched the legacy staged filters"
                    else:
                        summary["shortfall_reason"] = "Ops Status field missing and legacy status fallback is disabled"
                elif not settings.create_gmail_drafts:
                    summary["shortfall_reason"] = "Gmail draft creation is disabled"
                else:
                    summary["shortfall_reason"] = (
                        f"eligible candidates were exhausted after stage rotation and dedupe: created, sent, "
                        f"or previewed {target_progress} of {MIN_DRAFTS_TARGET}"
                    )

    if args.mode in {"all", "followups"}:
        _sync_manual_sent_steps(schema)

        due_followups = query_due_followups()
        if not due_followups:
            print("No due follow-up drafts found.")
        else:
            for lead in due_followups[:MAX_DRAFTS_PER_RUN]:
                try:
                    result = _process_due_followup(schema, lead)
                    if result == "email_2_created":
                        summary["gmail_drafts_created"] += 1
                    elif result == "email_3_created":
                        summary["gmail_drafts_created"] += 1
                except Exception as exc:
                    summary["errors"] += 1
                    print(f"Error creating follow-up for {_get_lead_name(lead)}: {exc}")

    print("Draft Agent Summary:")
    print(f"- cap reached: {'yes' if summary['drafts_attempted'] >= MAX_DRAFTS_PER_RUN else 'no'}")
    print(f"- MIN_DRAFTS_TARGET: {MIN_DRAFTS_TARGET}")
    print(f"- MAX_DRAFTS_PER_RUN: {MAX_DRAFTS_PER_RUN}")
    print(f"- ops_ready_used: {summary['ops_ready_used']}")
    print(f"- new_leads_used: {summary['new_leads_used']}")
    print(f"- backfill_used: {summary['backfill_used']}")
    print(f"- fallback_used: {summary['fallback_used']}")
    print(f"- total drafts created: {summary['gmail_drafts_created']}")
    print(f"- total emails sent: {summary['gmail_emails_sent']}")
    if summary["shortfall_reason"]:
        print(f"- shortfall reason: {summary['shortfall_reason']}")
    print(f"- records_checked: {summary['records_checked']}")
    print(f"- eligible_records: {summary['eligible_records']}")
    print(f"- drafts_attempted: {summary['drafts_attempted']}")
    print(f"- skipped_missing_email: {summary['skipped_missing_email']}")
    print(f"- skipped_missing_website: {summary['skipped_missing_website']}")
    print(f"- skipped_already_drafted: {summary['skipped_already_drafted']}")
    print(f"- skipped_wrong_status: {summary['skipped_wrong_status']}")
    print(f"- skipped_missing_business_name: {summary['skipped_missing_business_name']}")
    print(f"- skipped_manual_audit_placeholder: {summary['skipped_manual_audit_placeholder']}")
    print(f"- errors: {summary['errors']}")


if __name__ == "__main__":
    main()
