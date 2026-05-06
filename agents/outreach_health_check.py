from __future__ import annotations

import os
import sys
from collections import Counter
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from googleapiclient.errors import HttpError
from notion_client import Client

from agents import generate_drafts_from_notion as draft_flow
from agents import send_approved_gmail_drafts as send_flow
from lead_scraper.src.lead_finder import (
    ACTIVE_CITY_STATUSES,
    CANADA_CITY_QUEUE_TITLE,
    CITY_NAME_CANDIDATES,
    CITY_STATUS_CANDIDATES,
    PROVINCE_CANDIDATES,
    resolve_active_city_context,
)
from src.config import settings
from src.gmail_client import extract_draft_details, get_draft, is_stale_gmail_thread_error
from src.notion_client import get_data_source_schema, get_database_and_data_source


CHECK_GMAIL_DRAFT_HEALTH = os.getenv("CHECK_GMAIL_DRAFT_HEALTH", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
ALLOW_RULE_BASED_APPROVAL = os.getenv("ALLOW_RULE_BASED_APPROVAL", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

CANONICAL_LEAD_STATUS_CANDIDATES = ("Lead Status", "Outreach Status")
CANONICAL_GMAIL_SENT_STATUS_CANDIDATES = ("Gmail Sent Status",)
CANONICAL_GMAIL_MATCH_STATUS_CANDIDATES = ("Gmail Match Status",)
CANONICAL_CASL_BASIS_CANDIDATES = ("CASL Basis",)
CANONICAL_DUPLICATE_STATUS_CANDIDATES = ("Duplicate Status",)
CANONICAL_SEND_MODE_CANDIDATES = ("Send Mode",)
CANONICAL_EMAIL_CANDIDATES = ("Email", "Contact Email")
CANONICAL_WEBSITE_CANDIDATES = ("Website",)
CANONICAL_GMAIL_DRAFT_ID_CANDIDATES = ("Gmail Draft ID",)
CANONICAL_COUNTRY_CANDIDATES = ("Country",)
CANONICAL_DNC_CANDIDATES = ("Do Not Contact", "DNC")
CANONICAL_NEXT_FOLLOW_UP_CANDIDATES = ("Next Follow-up Date", "Next Follow Up Date")
CANONICAL_FOLLOW_UP_DUE_NOW_CANDIDATES = ("Follow-Up Due Now",)
OPS_STATUS_CANDIDATES = ("Ops Status",)
BLOCKER_REASON_CANDIDATES = ("Blocker Reason",)

CANADA_COUNTRY = "canada"
READY_TO_SEND_MODE = "auto_send_gated"
CANONICAL_DRAFT_READY_STATUSES = {"audit_ready", "draft_ready", "outreach_drafted", "new lead", "draft ready"}
CANONICAL_REPLIED_STATUSES = {"replied"}
CANONICAL_BLOCKED_LEAD_STATUSES = {"not_fit", "archived", "paid_client"}
CANONICAL_BLOCKED_DUPLICATE_STATUSES = {"duplicate", "possible_duplicate", "already_contacted", "do_not_contact"}
CASL_READY_VALUES = {
    "conspicuously_published_business_email",
    "existing_business_relationship",
    "referral_or_intro",
}
MANUAL_CASL_VALUES = {"manual_research_needed"}


def get_client() -> Client:
    if not settings.notion_api_key:
        raise ValueError("NOTION_API_KEY is missing.")
    return Client(auth=settings.notion_api_key)


def _normalize(text: str) -> str:
    return " ".join(str(text or "").split()).strip().lower()


def _first_existing(properties: Dict[str, Any], candidates: Tuple[str, ...]) -> Optional[str]:
    for candidate in candidates:
        if candidate in properties:
            return candidate
    return None


def _text(prop: Dict[str, Any]) -> str:
    if not prop:
        return ""
    if prop.get("title"):
        return "".join(item.get("plain_text", "") for item in prop["title"]).strip()
    if prop.get("rich_text"):
        return "".join(item.get("plain_text", "") for item in prop["rich_text"]).strip()
    if prop.get("email"):
        return str(prop["email"]).strip()
    if prop.get("url"):
        return str(prop["url"]).strip()
    if prop.get("select"):
        return str(prop["select"].get("name", "")).strip()
    if prop.get("status"):
        return str(prop["status"].get("name", "")).strip()
    if prop.get("date"):
        return str(prop["date"].get("start", "")).strip()
    if prop.get("checkbox") is not None:
        return "true" if prop["checkbox"] else "false"
    if prop.get("formula"):
        formula = prop.get("formula", {})
        if isinstance(formula, dict):
            if formula.get("type") == "string":
                return str(formula.get("string", "")).strip()
            if formula.get("type") == "number" and formula.get("number") is not None:
                return str(formula.get("number")).strip()
            if formula.get("type") == "boolean":
                return "true" if formula.get("boolean") else "false"
            if formula.get("type") == "date" and formula.get("date"):
                return str(formula.get("date", {}).get("start", "")).strip()
    return ""


def _date_value(prop: Dict[str, Any]) -> Optional[date]:
    raw = _text(prop)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw[:10]).date()
    except ValueError:
        return None


def _lead_text(lead: Dict[str, Any], candidates: Tuple[str, ...]) -> str:
    properties = lead.get("properties", {})
    property_name = _first_existing(properties, candidates)
    if not property_name:
        return ""
    return _text(properties.get(property_name, {}))


def _lead_checkbox(lead: Dict[str, Any], candidates: Tuple[str, ...]) -> bool:
    properties = lead.get("properties", {})
    property_name = _first_existing(properties, candidates)
    if not property_name:
        return False
    return bool(properties.get(property_name, {}).get("checkbox"))


def _lead_status(lead: Dict[str, Any]) -> str:
    return _normalize(_lead_text(lead, CANONICAL_LEAD_STATUS_CANDIDATES))


def _lead_gmail_sent_status(lead: Dict[str, Any]) -> str:
    return _normalize(_lead_text(lead, CANONICAL_GMAIL_SENT_STATUS_CANDIDATES))


def _lead_gmail_match_status(lead: Dict[str, Any]) -> str:
    return _normalize(_lead_text(lead, CANONICAL_GMAIL_MATCH_STATUS_CANDIDATES))


def _lead_casl_basis(lead: Dict[str, Any]) -> str:
    return _normalize(_lead_text(lead, CANONICAL_CASL_BASIS_CANDIDATES))


def _lead_duplicate_status(lead: Dict[str, Any]) -> str:
    return _normalize(_lead_text(lead, CANONICAL_DUPLICATE_STATUS_CANDIDATES))


def _lead_send_mode(lead: Dict[str, Any]) -> str:
    return _normalize(_lead_text(lead, CANONICAL_SEND_MODE_CANDIDATES))


def _lead_email(lead: Dict[str, Any]) -> str:
    return _lead_text(lead, CANONICAL_EMAIL_CANDIDATES)


def _lead_website(lead: Dict[str, Any]) -> str:
    return _lead_text(lead, CANONICAL_WEBSITE_CANDIDATES)


def _lead_country(lead: Dict[str, Any]) -> str:
    return _normalize(_lead_text(lead, CANONICAL_COUNTRY_CANDIDATES))


def _lead_draft_id(lead: Dict[str, Any]) -> str:
    return _lead_text(lead, CANONICAL_GMAIL_DRAFT_ID_CANDIDATES)


def _lead_next_follow_up(lead: Dict[str, Any]) -> Optional[date]:
    properties = lead.get("properties", {})
    property_name = _first_existing(properties, CANONICAL_NEXT_FOLLOW_UP_CANDIDATES)
    if not property_name:
        return None
    return _date_value(properties.get(property_name, {}))


def _lead_follow_up_due_now(lead: Dict[str, Any]) -> bool:
    properties = lead.get("properties", {})
    property_name = _first_existing(properties, CANONICAL_FOLLOW_UP_DUE_NOW_CANDIDATES)
    if not property_name:
        return False
    formula = properties.get(property_name, {}).get("formula", {})
    if not isinstance(formula, dict):
        return False
    if formula.get("type") == "boolean":
        return bool(formula.get("boolean"))
    return False


def _lead_ops_status(lead: Dict[str, Any]) -> str:
    return _normalize(_lead_text(lead, OPS_STATUS_CANDIDATES))


def _lead_blocker_reasons(lead: Dict[str, Any]) -> List[str]:
    properties = lead.get("properties", {})
    property_name = _first_existing(properties, BLOCKER_REASON_CANDIDATES)
    if not property_name:
        return []

    prop = properties.get(property_name, {})
    values: List[str] = []
    if prop.get("multi_select"):
        values.extend(
            str(item.get("name", "")).strip()
            for item in prop["multi_select"]
            if str(item.get("name", "")).strip()
        )
    elif prop.get("rich_text"):
        raw = _text(prop)
        if raw:
            values.extend(part.strip() for part in raw.replace(";", ",").split(",") if part.strip())
    else:
        raw = _text(prop)
        if raw:
            values.extend(part.strip() for part in raw.replace(";", ",").split(",") if part.strip())
    return [_normalize(value) for value in values if _normalize(value)]


def _outreach_status_value(lead: Dict[str, Any]) -> str:
    return _normalize(_lead_text(lead, CANONICAL_LEAD_STATUS_CANDIDATES))


def _draft_ready_reason(lead: Dict[str, Any]) -> Optional[str]:
    lead_status = _lead_status(lead)
    if not lead_status:
        return "Lead Status is missing"
    if lead_status not in CANONICAL_DRAFT_READY_STATUSES:
        return "Lead Status is not draft-ready"

    country = _lead_country(lead)
    if country and country != CANADA_COUNTRY:
        return f"Country is {country}"
    if not country:
        return "Country is missing"

    duplicate_status = _lead_duplicate_status(lead)
    if duplicate_status in CANONICAL_BLOCKED_DUPLICATE_STATUSES:
        return f"Duplicate Status is {duplicate_status}"

    if _lead_checkbox(lead, CANONICAL_DNC_CANDIDATES):
        return "Do Not Contact is true"

    if not _lead_email(lead):
        return "Email is missing"
    if not _lead_website(lead):
        return "Website is missing"

    top_issue = _lead_text(lead, tuple(draft_flow.TOP_ISSUE_CANDIDATES))
    if not top_issue:
        return "Top Issue is missing"

    angle_bucket = _lead_text(lead, tuple(draft_flow.ANGLE_BUCKET_CANDIDATES))
    if not angle_bucket:
        return "Angle Bucket is missing"

    if _lead_draft_id(lead):
        return "Gmail Draft ID already exists"

    return None


def _casl_ready(lead: Dict[str, Any]) -> bool:
    return _lead_casl_basis(lead) in CASL_READY_VALUES


def _manual_casl_review(lead: Dict[str, Any]) -> bool:
    basis = _lead_casl_basis(lead)
    return not basis or basis in MANUAL_CASL_VALUES or basis not in CASL_READY_VALUES


def _send_block_reasons_notion_only(lead: Dict[str, Any]) -> List[str]:
    reasons: List[str] = []
    if send_flow._lead_admin_approved(lead):  # type: ignore[attr-defined]
        if _lead_send_mode(lead) != READY_TO_SEND_MODE:
            reasons.append(f"Send Mode is {_lead_send_mode(lead) or '<empty>'}")
        if _lead_country(lead) != CANADA_COUNTRY:
            reasons.append(f"Country is {_lead_text(lead, CANONICAL_COUNTRY_CANDIDATES) or '<empty>'}")
        if _lead_checkbox(lead, CANONICAL_DNC_CANDIDATES):
            reasons.append("Do Not Contact is true")
        if not _lead_casl_basis(lead):
            reasons.append("CASL Basis is missing")
        if not _lead_email(lead):
            reasons.append("Email is missing")
        if not _lead_draft_id(lead):
            reasons.append("Gmail Draft ID is missing")
        if _lead_status(lead) in CANONICAL_BLOCKED_LEAD_STATUSES:
            reasons.append(f"Lead Status is {_lead_status(lead)}")
        if _lead_duplicate_status(lead) in CANONICAL_BLOCKED_DUPLICATE_STATUSES:
            reasons.append(f"Duplicate Status is {_lead_duplicate_status(lead)}")
        if _lead_gmail_sent_status(lead) == "sent":
            reasons.append("Gmail Sent Status is sent")
        if _lead_gmail_match_status(lead) in {"replied", "sent_exists"}:
            reasons.append(f"Gmail Match Status is {_lead_gmail_match_status(lead)}")
        return reasons

    if ALLOW_RULE_BASED_APPROVAL:
        if _lead_send_mode(lead) not in {"auto_draft", "auto_send_gated"}:
            reasons.append(f"Send Mode is {_lead_send_mode(lead) or '<empty>'}")
        if _lead_country(lead) != CANADA_COUNTRY:
            reasons.append(f"Country is {_lead_text(lead, CANONICAL_COUNTRY_CANDIDATES) or '<empty>'}")
        if not _lead_email(lead):
            reasons.append("Email is missing")
        if not _lead_website(lead):
            reasons.append("Website is missing")
        if not _lead_draft_id(lead):
            reasons.append("Gmail Draft ID is missing")
        if _lead_casl_basis(lead) not in CASL_READY_VALUES:
            reasons.append(f"CASL Basis is {_lead_casl_basis(lead) or '<empty>'}")
        if _lead_checkbox(lead, CANONICAL_DNC_CANDIDATES):
            reasons.append("Do Not Contact is true")
        if _lead_duplicate_status(lead) not in {"", "unique"}:
            reasons.append(f"Duplicate Status is {_lead_duplicate_status(lead)}")
        if _lead_gmail_match_status(lead) not in {"", "no_match", "draft_exists"}:
            reasons.append(f"Gmail Match Status is {_lead_gmail_match_status(lead)}")
        if _lead_gmail_sent_status(lead) == "sent":
            reasons.append("Gmail Sent Status is sent")
        if _lead_status(lead) in CANONICAL_BLOCKED_LEAD_STATUSES:
            reasons.append(f"Lead Status is {_lead_status(lead)}")
        return reasons

    reasons.append("Admin Approved is not true")
    if _lead_send_mode(lead) != READY_TO_SEND_MODE:
        reasons.append(f"Send Mode is {_lead_send_mode(lead) or '<empty>'}")
    if _lead_country(lead) != CANADA_COUNTRY:
        reasons.append(f"Country is {_lead_text(lead, CANONICAL_COUNTRY_CANDIDATES) or '<empty>'}")
    if _lead_checkbox(lead, CANONICAL_DNC_CANDIDATES):
        reasons.append("Do Not Contact is true")
    if not _lead_casl_basis(lead):
        reasons.append("CASL Basis is missing")
    if not _lead_email(lead):
        reasons.append("Email is missing")
    if not _lead_draft_id(lead):
        reasons.append("Gmail Draft ID is missing")
    if _lead_status(lead) in CANONICAL_BLOCKED_LEAD_STATUSES:
        reasons.append(f"Lead Status is {_lead_status(lead)}")
    if _lead_duplicate_status(lead) in CANONICAL_BLOCKED_DUPLICATE_STATUSES:
        reasons.append(f"Duplicate Status is {_lead_duplicate_status(lead)}")
    if _lead_gmail_sent_status(lead) == "sent":
        reasons.append("Gmail Sent Status is sent")
    if _lead_gmail_match_status(lead) in {"replied", "sent_exists"}:
        reasons.append(f"Gmail Match Status is {_lead_gmail_match_status(lead)}")
    return reasons


def _replied(lead: Dict[str, Any]) -> bool:
    status = _lead_status(lead)
    reply_status = _normalize(_lead_text(lead, tuple(draft_flow.REPLY_STATUS_CANDIDATES)))
    gmail_match_status = _lead_gmail_match_status(lead)
    return (
        status in CANONICAL_REPLIED_STATUSES
        or reply_status in CANONICAL_REPLIED_STATUSES
        or gmail_match_status in CANONICAL_REPLIED_STATUSES
    )


def _non_canada_or_not_fit(lead: Dict[str, Any]) -> bool:
    country = _lead_country(lead)
    status = _lead_status(lead)
    return country != CANADA_COUNTRY or status in CANONICAL_BLOCKED_LEAD_STATUSES


def _draft_indicator_reasons(lead: Dict[str, Any]) -> List[str]:
    reasons: List[str] = []
    draft_id = _lead_draft_id(lead)
    if not draft_id:
        return reasons

    status = _lead_status(lead)
    if status in CANONICAL_BLOCKED_LEAD_STATUSES or status in CANONICAL_REPLIED_STATUSES:
        reasons.append(f"Lead Status is {status}")

    sent_status = _lead_gmail_sent_status(lead)
    if sent_status == "sent":
        reasons.append("Gmail Sent Status is sent")

    match_status = _lead_gmail_match_status(lead)
    if match_status in {"replied", "sent_exists"}:
        reasons.append(f"Gmail Match Status is {match_status}")

    if _lead_checkbox(lead, CANONICAL_DNC_CANDIDATES):
        reasons.append("Do Not Contact is true")

    if _lead_duplicate_status(lead) in CANONICAL_BLOCKED_DUPLICATE_STATUSES:
        reasons.append(f"Duplicate Status is {_lead_duplicate_status(lead)}")

    if not _lead_email(lead):
        reasons.append("Email is missing")

    if not _lead_website(lead):
        reasons.append("Website is missing")

    return reasons


def _load_leads() -> List[Dict[str, Any]]:
    client = draft_flow.get_client()  # type: ignore[attr-defined]
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


def _load_city_queue_rows() -> Tuple[List[Dict[str, Any]], bool, Optional[str]]:
    try:
        client = get_client()
        search = getattr(client, "search", None)
        if search is None:
            return [], False, "Canada City Queue not accessible. Share the database with the integration or set ACTIVE_CITY env manually."

        response = search(query=CANADA_CITY_QUEUE_TITLE, filter={"property": "object", "value": "data_source"})
        database_id = ""
        for result in response.get("results", []):
            title_parts = result.get("title", [])
            title_text = "".join(part.get("plain_text", "") for part in title_parts).strip()
            if title_text.lower() == CANADA_CITY_QUEUE_TITLE.lower():
                database_id = result.get("id", "")
                break
        if not database_id:
            return [], False, "Canada City Queue not accessible. Share the database with the integration or set ACTIVE_CITY env manually."

        database = client.databases.retrieve(database_id=database_id)
        data_sources = database.get("data_sources", [])
        if not data_sources:
            return [], False, "Canada City Queue not accessible. Share the database with the integration or set ACTIVE_CITY env manually."

        rows: List[Dict[str, Any]] = []
        next_cursor: Optional[str] = None
        while True:
            kwargs: Dict[str, Any] = {"data_source_id": data_sources[0]["id"], "page_size": 100}
            if next_cursor:
                kwargs["start_cursor"] = next_cursor
            response = client.data_sources.query(**kwargs)
            rows.extend(response.get("results", []))
            if not response.get("has_more"):
                break
            next_cursor = response.get("next_cursor")
            if not next_cursor:
                break
        return rows, True, None
    except Exception:
        return [], False, "Canada City Queue not accessible. Share the database with the integration or set ACTIVE_CITY env manually."


def _city_text(row: Dict[str, Any], candidates: Tuple[str, ...]) -> str:
    properties = row.get("properties", {})
    property_name = _first_existing(properties, candidates)
    if not property_name:
        return ""
    return _text(properties.get(property_name, {}))


def _city_queue_summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    status_counts: Counter[str] = Counter()
    for row in rows:
        status = _normalize(_city_text(row, tuple(CITY_STATUS_CANDIDATES))) or "<empty>"
        status_counts[status] += 1
    active_rows = sum(count for status, count in status_counts.items() if status in ACTIVE_CITY_STATUSES)
    return {
        "total_rows": len(rows),
        "active_rows": active_rows,
        "status_counts": status_counts,
    }


def _followups_due_count(leads: List[Dict[str, Any]]) -> int:
    due = 0
    today = datetime.now(timezone.utc).date()
    for lead in leads:
        lead_status = _lead_status(lead)
        reply_status = _normalize(_lead_text(lead, tuple(draft_flow.REPLY_STATUS_CANDIDATES)))
        if lead_status in CANONICAL_REPLIED_STATUSES:
            continue
        if lead_status in {"closed", "call_booked", "not_interested"}:
            continue
        if _non_canada_or_not_fit(lead):
            continue
        if _lead_duplicate_status(lead) in CANONICAL_BLOCKED_DUPLICATE_STATUSES:
            continue
        if _lead_checkbox(lead, CANONICAL_DNC_CANDIDATES):
            continue

        follow_up_due_now = _lead_follow_up_due_now(lead)
        next_followup = _lead_next_follow_up(lead)
        outreach_status = _outreach_status_value(lead)

        if reply_status == "replied" or outreach_status in {"replied", "closed"}:
            continue
        if follow_up_due_now:
            due += 1
            continue
        if outreach_status in {"email 1 sent", "email 2 sent"} and next_followup and today >= next_followup:
            due += 1
    return due


def _draft_state_counts(leads: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {
        "draft_exists_drafted": 0,
        "stale_non_active_unsent": 0,
        "stale_non_active_already_sent": 0,
        "casl_missing": 0,
    }
    for lead in leads:
        if not _lead_casl_basis(lead):
            counts["casl_missing"] += 1

        draft_id = _lead_draft_id(lead)
        if not draft_id:
            continue

        sent_status = _lead_gmail_sent_status(lead)
        match_status = _lead_gmail_match_status(lead)
        draft_reasons = _draft_indicator_reasons(lead)

        if sent_status == "sent" or match_status in {"replied", "sent_exists"}:
            counts["stale_non_active_already_sent"] += 1
        elif draft_reasons:
            counts["stale_non_active_unsent"] += 1
        else:
            counts["draft_exists_drafted"] += 1
    return counts


def _count_by_field(leads: List[Dict[str, Any]], field_getter) -> Counter[str]:
    counts: Counter[str] = Counter()
    for lead in leads:
        value = _normalize(field_getter(lead)) or "<empty>"
        counts[value] += 1
    return counts


def _count_blocker_reasons(leads: List[Dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for lead in leads:
        reasons = _lead_blocker_reasons(lead)
        if not reasons:
            counts["<empty>"] += 1
            continue
        for reason in reasons:
            counts[reason] += 1
    return counts


def _recommended_next_step(
    *,
    active_city: str,
    use_ops_status: bool,
    ops_queue_counts: Dict[str, int],
    send_ready: int,
    stale_non_active_unsent: int,
    draft_ready: int,
    casl_backfill_needed: int,
    followup_due: int,
    draft_exists_drafted: int,
    current_pool_exhausted: bool,
) -> str:
    if not active_city:
        return "Fix Canada City Queue."
    if use_ops_status:
        if ops_queue_counts.get("ready_to_send", 0) > 0:
            return "Run send dry run."
        if ops_queue_counts.get("needs_reconciliation", 0) > 0:
            return "Run reconciliation."
        if ops_queue_counts.get("ready_to_draft", 0) > 0:
            return "Generate drafts."
        if ops_queue_counts.get("needs_casl_review", 0) > 0:
            return "Work CASL review / run CASL backfill where eligible."
        if ops_queue_counts.get("needs_email_research", 0) > 0:
            return "Work manual email research queue."
        if ops_queue_counts.get("follow_up_due", 0) > 0:
            return "Run follow-up workflow."
        active_work = sum(
            ops_queue_counts.get(key, 0)
            for key in (
                "ready_to_send",
                "needs_reconciliation",
                "ready_to_draft",
                "needs_casl_review",
                "needs_email_research",
                "follow_up_due",
            )
        )
        if active_work == 0 and (ops_queue_counts.get("sent", 0) + ops_queue_counts.get("replied", 0) > 0):
            return "Current pool exhausted. Scrape next active city."
        if ops_queue_counts.get("not_fit", 0) > 0:
            return "Current pool exhausted. Scrape next active city."
        return "Review the ops queue manually."
    if send_ready > 0:
        return "Run send dry run."
    if stale_non_active_unsent > 0:
        return "Run reconciliation."
    if draft_ready > 0:
        return "Generate drafts."
    if casl_backfill_needed > 0:
        return "Run CASL backfill."
    if followup_due > 0:
        return "Generate follow-up drafts."
    if current_pool_exhausted:
        return "Switch/scrape next active city."
    if draft_exists_drafted > 0:
        return "Review drafted records before switching cities."
    return "Review the queue manually."


def _print_counter(title: str, counts: Counter[str]) -> None:
    print(title)
    for key, value in counts.most_common():
        print(f"- {key}: {value}")


def _active_city_line() -> Tuple[str, str]:
    city, province = resolve_active_city_context()
    return city, province


def main() -> None:
    leads = _load_leads()
    schema = get_data_source_schema()
    schema_properties = schema.get("properties", {})
    active_city, active_province = _active_city_line()
    queue_rows, queue_accessible, queue_warning = _load_city_queue_rows()
    queue_summary = _city_queue_summary(queue_rows)
    city_source_label = "ENV fallback city" if queue_warning else "Canada City Queue active city"
    ops_status_field = _first_existing(schema_properties, OPS_STATUS_CANDIDATES)
    blocker_reason_field = _first_existing(schema_properties, BLOCKER_REASON_CANDIDATES)
    ops_status_exists = bool(ops_status_field)

    lead_status_counts = _count_by_field(leads, _lead_status)
    gmail_sent_counts = _count_by_field(leads, _lead_gmail_sent_status)
    gmail_match_counts = _count_by_field(leads, _lead_gmail_match_status)
    casl_basis_counts = _count_by_field(leads, _lead_casl_basis)
    duplicate_status_counts = _count_by_field(leads, _lead_duplicate_status)
    ops_status_counts = _count_by_field(leads, _lead_ops_status)
    blocker_reason_counts = _count_blocker_reasons(leads)

    draft_ready_count = 0
    casl_ready_count = 0
    manual_casl_review_count = 0
    send_ready_count = 0
    missing_email_count = 0
    missing_website_count = 0
    non_canada_or_not_fit_count = 0
    replied_count = 0
    follow_up_due_count = _followups_due_count(leads)
    send_blocker_counts: Counter[str] = Counter()
    draft_state_counts = _draft_state_counts(leads)

    for lead in leads:
        if _draft_ready_reason(lead) is None:
            draft_ready_count += 1

        if _casl_ready(lead):
            casl_ready_count += 1
        if _manual_casl_review(lead):
            manual_casl_review_count += 1

        send_reasons = _send_block_reasons_notion_only(lead)
        if not send_reasons:
            send_ready_count += 1
        else:
            for reason in send_reasons:
                send_blocker_counts[reason] += 1

        if not _lead_email(lead):
            missing_email_count += 1
        if not _lead_website(lead):
            missing_website_count += 1
        if _non_canada_or_not_fit(lead):
            non_canada_or_not_fit_count += 1
        if _replied(lead):
            replied_count += 1

    stale_non_active_unsent_count = draft_state_counts["stale_non_active_unsent"]
    stale_non_active_already_sent_count = draft_state_counts["stale_non_active_already_sent"]
    draft_exists_drafted_count = draft_state_counts["draft_exists_drafted"]
    current_pool_exhausted = (
        send_ready_count == 0
        and draft_ready_count == 0
        and stale_non_active_unsent_count == 0
        and follow_up_due_count == 0
        and manual_casl_review_count == 0
        and draft_exists_drafted_count == 0
    )
    ops_queue_counts = {
        "ready_to_send": ops_status_counts.get("ready_to_send", 0),
        "needs_reconciliation": ops_status_counts.get("needs_reconciliation", 0),
        "ready_to_draft": ops_status_counts.get("ready_to_draft", 0),
        "needs_casl_review": ops_status_counts.get("needs_casl_review", 0),
        "needs_email_research": ops_status_counts.get("needs_email_research", 0),
        "follow_up_due": ops_status_counts.get("follow_up_due", 0),
        "sent": ops_status_counts.get("sent", 0),
        "replied": ops_status_counts.get("replied", 0),
        "not_fit": ops_status_counts.get("not_fit", 0),
    }

    recommended = _recommended_next_step(
        active_city=active_city,
        use_ops_status=ops_status_exists,
        ops_queue_counts=ops_queue_counts,
        send_ready=send_ready_count,
        stale_non_active_unsent=stale_non_active_unsent_count,
        draft_ready=draft_ready_count,
        casl_backfill_needed=manual_casl_review_count,
        followup_due=follow_up_due_count,
        draft_exists_drafted=draft_exists_drafted_count,
        current_pool_exhausted=current_pool_exhausted,
    )

    print("Outreach Health Check")
    print(f"Total Outreach Tracker records: {len(leads)}")
    print("")
    print("1. Total Outreach Tracker records")
    print(f"- {len(leads)}")
    print("2. Records by Lead Status")
    _print_counter("Lead Status counts:", lead_status_counts)
    print("3. Records by Gmail Sent Status")
    _print_counter("Gmail Sent Status counts:", gmail_sent_counts)
    print("4. Records by Gmail Match Status")
    _print_counter("Gmail Match Status counts:", gmail_match_counts)
    print("5. Records by CASL Basis")
    _print_counter("CASL Basis counts:", casl_basis_counts)
    print("6. Records by Duplicate Status")
    _print_counter("Duplicate Status counts:", duplicate_status_counts)
    print("Ops Queue Summary")
    for key in (
        "ready_to_send",
        "needs_reconciliation",
        "ready_to_draft",
        "needs_casl_review",
        "needs_email_research",
        "follow_up_due",
        "sent",
        "replied",
        "not_fit",
    ):
        print(f"- {key}: {ops_queue_counts.get(key, 0)}")
    print("6b. Records by Ops Status")
    _print_counter("Ops Status counts:", ops_status_counts)
    print("6c. Records by Blocker Reason")
    _print_counter("Blocker Reason counts:", blocker_reason_counts)
    print("7. Draft ready count")
    print(f"- {draft_ready_count}")
    print("8. CASL ready count")
    print(f"- {casl_ready_count}")
    print("9. Send ready count")
    print(f"- {send_ready_count}")
    print("10. Manual CASL review count")
    print(f"- {manual_casl_review_count}")
    print("11. Missing email count")
    print(f"- {missing_email_count}")
    print("12. Missing website count")
    print(f"- {missing_website_count}")
    print("13. Non-Canada / not-fit count")
    print(f"- {non_canada_or_not_fit_count}")
    print("14. Replied count")
    print(f"- {replied_count}")
    print("15. Follow-up due count")
    print(f"- {follow_up_due_count}")
    print("16. Stale/non-active draft indicators")
    print(f"- draft_exists/drafted records: {draft_exists_drafted_count}")
    print(f"- stale/non-active unsent: {stale_non_active_unsent_count}")
    print(f"- stale/non-active already sent: {stale_non_active_already_sent_count}")

    if CHECK_GMAIL_DRAFT_HEALTH:
        gmail_active = 0
        gmail_stale = 0
        gmail_non_active = 0
        gmail_errors = 0
        for lead in leads:
            draft_id = _lead_draft_id(lead)
            if not draft_id:
                continue
            try:
                draft = get_draft(draft_id)
                active_block_reason = send_flow._active_draft_block_reason(  # type: ignore[attr-defined]
                    draft_id,
                    extract_draft_details(draft),
                )
                if active_block_reason:
                    gmail_non_active += 1
                else:
                    gmail_active += 1
            except Exception as exc:
                if is_stale_gmail_thread_error(exc) or (
                    isinstance(exc, HttpError)
                    and getattr(exc.resp, "status", None) == 404
                ):
                    gmail_stale += 1
                else:
                    gmail_errors += 1

        print("- Gmail draft health check: enabled")
        print(f"- active drafts: {gmail_active}")
        print(f"- stale Gmail draft IDs: {gmail_stale}")
        print(f"- non-active Gmail drafts: {gmail_non_active}")
        print(f"- Gmail draft errors: {gmail_errors}")
    else:
        print("- Gmail draft health check: disabled (set CHECK_GMAIL_DRAFT_HEALTH=true)")

    print("17. Active city from Canada City Queue")
    print(f"- {city_source_label}: {active_city}, {active_province}" if active_province else f"- {city_source_label}: {active_city}")

    print("18. City queue summary")
    print(f"- total queue rows: {queue_summary['total_rows']}")
    print(f"- active queue rows: {queue_summary['active_rows']}")
    if queue_rows:
        status_counts: Counter[str] = queue_summary["status_counts"]
        for status, count in status_counts.most_common(10):
            print(f"- {status}: {count}")
    else:
        print("- queue unavailable or not found")

    print("Data source warnings")
    if ALLOW_RULE_BASED_APPROVAL:
        print("- ALLOW_RULE_BASED_APPROVAL=true; admin approval is not counted as a blocker by itself.")
    else:
        print("- ALLOW_RULE_BASED_APPROVAL=false; admin approval remains part of the computed send gate.")
    if ops_status_exists:
        print(f"- Ops Status field detected: {ops_status_field}")
        if blocker_reason_field:
            print(f"- Blocker Reason field detected: {blocker_reason_field}")
    if queue_warning:
        print(f"- {queue_warning}")
    if not CHECK_GMAIL_DRAFT_HEALTH:
        print("- Gmail draft health check disabled by default; set CHECK_GMAIL_DRAFT_HEALTH=true to enable Gmail checks.")

    print("19. Top 10 blockers preventing sends")
    for reason, count in send_blocker_counts.most_common(10):
        print(f"- {reason}: {count}")
    if not send_blocker_counts:
        print("- none")

    print("20. Recommended next action")
    print(f"- {recommended}")
    print("Recommended Next Step:")
    print(f"- {recommended}")


if __name__ == "__main__":
    main()
