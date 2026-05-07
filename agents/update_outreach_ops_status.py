from __future__ import annotations

import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from googleapiclient.errors import HttpError
from notion_client import Client

from agents import generate_drafts_from_notion as draft_flow
from agents import send_approved_gmail_drafts as send_flow
from src.config import settings
from src.gmail_client import extract_draft_details, get_draft
from src.notion_client import get_database_and_data_source, get_data_source_schema


OPS_STATUS_DRY_RUN = os.getenv("OPS_STATUS_DRY_RUN", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
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

OPS_STATUS_VALUES = {
    "ready_to_draft",
    "draft_created",
    "needs_email_research",
    "needs_website_research",
    "needs_casl_review",
    "needs_duplicate_review",
    "needs_reconciliation",
    "ready_to_send",
    "sent",
    "replied",
    "follow_up_due",
    "not_fit",
    "do_not_contact",
    "blocked",
}

OPS_STATUS_CANDIDATES = ("Ops Status",)
BLOCKER_REASON_CANDIDATES = ("Blocker Reason",)

NAME_CANDIDATES = ("Business Name", "Practice Name", "Clinic Name", "Name")
LEAD_STATUS_CANDIDATES = ("Lead Status", "Outreach Status")
REPLY_STATUS_CANDIDATES = tuple(draft_flow.REPLY_STATUS_CANDIDATES)  # type: ignore[attr-defined]
GMAIL_SENT_STATUS_CANDIDATES = tuple(draft_flow.GMAIL_SENT_STATUS_CANDIDATES)  # type: ignore[attr-defined]
GMAIL_MATCH_STATUS_CANDIDATES = tuple(draft_flow.GMAIL_MATCH_STATUS_CANDIDATES)  # type: ignore[attr-defined]
CASL_BASIS_CANDIDATES = tuple(draft_flow.CASL_BASIS_CANDIDATES)  # type: ignore[attr-defined]
DUPLICATE_STATUS_CANDIDATES = tuple(draft_flow.DUPLICATE_STATUS_CANDIDATES)  # type: ignore[attr-defined]
SEND_MODE_CANDIDATES = tuple(draft_flow.SEND_MODE_CANDIDATES)  # type: ignore[attr-defined]
EMAIL_CANDIDATES = tuple(draft_flow.EMAIL_FIELD_CANDIDATES)  # type: ignore[attr-defined]
PHONE_CANDIDATES = ("Phone", "Phone Number", "Business Phone", "Contact Phone", "Mobile Phone", "Cell Phone")
WEBSITE_CANDIDATES = tuple(draft_flow.WEBSITE_CANDIDATES)  # type: ignore[attr-defined]
GMAIL_DRAFT_ID_CANDIDATES = tuple(draft_flow.GMAIL_DRAFT_ID_CANDIDATES)  # type: ignore[attr-defined]
COUNTRY_CANDIDATES = tuple(draft_flow.COUNTRY_CANDIDATES)  # type: ignore[attr-defined]
DO_NOT_CONTACT_CANDIDATES = tuple(draft_flow.DO_NOT_CONTACT_CANDIDATES)  # type: ignore[attr-defined]
TOP_ISSUE_CANDIDATES = tuple(draft_flow.TOP_ISSUE_CANDIDATES)  # type: ignore[attr-defined]
OUTREACH_ANGLE_CANDIDATES = tuple(draft_flow.OUTREACH_ANGLE_CANDIDATES)  # type: ignore[attr-defined]
NEXT_FOLLOW_UP_CANDIDATES = tuple(draft_flow.NEXT_FOLLOW_UP_DATE_CANDIDATES)  # type: ignore[attr-defined]
FOLLOW_UP_DUE_NOW_CANDIDATES = tuple(draft_flow.FOLLOW_UP_DUE_NOW_CANDIDATES)  # type: ignore[attr-defined]
ADMIN_APPROVED_CANDIDATES = tuple(getattr(send_flow, "ADMIN_APPROVED_CANDIDATES", ("Admin Approved",)))
SCHEDULED_SEND_DATE_CANDIDATES = tuple(getattr(draft_flow, "SCHEDULED_SEND_DATE_CANDIDATES", ("Scheduled Send Date",)))
OUTREACH_BATCH_CANDIDATES = tuple(getattr(draft_flow, "OUTREACH_BATCH_CANDIDATES", ("Outreach Batch",)))
SEQUENCE_STEP_CANDIDATES = tuple(getattr(draft_flow, "SEQUENCE_STEP_CANDIDATES", ("Sequence Step",)))

CANADA_COUNTRY = "canada"
APPROVED_SEND_MODES = {"auto_draft", "auto_send_gated"}
READY_TO_DRAFT_STATUS_VALUES = {"audit_ready", "draft_ready", "outreach_drafted", "new lead", "draft ready"}
SENT_STATUS_VALUES = {"sent"}
REPLIED_STATUS_VALUES = {"replied"}
CASL_READY_VALUES = {"conspicuously_published_business_email"}
MANUAL_CASL_VALUES = {"manual_research_needed"}
SAFE_DUPLICATE_VALUES = {"", "unique"}
DUPLICATE_REVIEW_REASON = "duplicate_possible"
DUPLICATE_REVIEW_STATUS = "needs_duplicate_review"
DUPLICATE_STATUS_REVIEW_VALUES = {"possible_duplicate"}
DUPLICATE_STATUS_DO_NOT_CONTACT_VALUES = {"do_not_contact"}
DUPLICATE_STATUS_ACTIVE_BLOCKED_VALUES = {"duplicate", "already_contacted"}
IGNORED_DUPLICATE_GROUP_STATUSES = {"sent", "replied", "paid_client", "archived", "do_not_contact", "not_fit"}


@dataclass
class Classification:
    status: str
    blockers: List[str]
    reason: str


def get_client() -> Client:
    if not settings.notion_api_key:
        raise ValueError("NOTION_API_KEY is missing.")
    return Client(auth=settings.notion_api_key)


def _normalize(text: Any) -> str:
    return " ".join(str(text or "").split()).strip().lower()


def _first_existing(properties: Dict[str, Any], candidates: Sequence[str]) -> Optional[str]:
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
    if prop.get("phone_number"):
        return str(prop["phone_number"]).strip()
    if prop.get("select"):
        return str(prop["select"].get("name", "")).strip()
    if prop.get("status"):
        return str(prop["status"].get("name", "")).strip()
    if prop.get("date"):
        return str(prop["date"].get("start", "")).strip()
    if prop.get("checkbox") is not None:
        return "true" if prop["checkbox"] else "false"
    if prop.get("multi_select"):
        return ", ".join(str(item.get("name", "")).strip() for item in prop["multi_select"] if str(item.get("name", "")).strip())
    if prop.get("formula"):
        formula = prop["formula"]
        if formula.get("type") == "string":
            return str(formula.get("string", "")).strip()
        if formula.get("type") == "boolean":
            return "true" if formula.get("boolean") else "false"
        if formula.get("type") == "number" and formula.get("number") is not None:
            return str(formula.get("number")).strip()
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


def _lead_text(lead: Dict[str, Any], candidates: Sequence[str]) -> str:
    properties = lead.get("properties", {})
    property_name = _first_existing(properties, candidates)
    if not property_name:
        return ""
    return _text(properties.get(property_name, {}))


def _lead_checkbox(lead: Dict[str, Any], candidates: Sequence[str]) -> bool:
    properties = lead.get("properties", {})
    property_name = _first_existing(properties, candidates)
    if not property_name:
        return False
    prop = properties.get(property_name, {})
    if "checkbox" in prop:
        return bool(prop.get("checkbox"))
    return _normalize(_text(prop)) in {"true", "yes", "1", "approved"}


def _lead_date(lead: Dict[str, Any], candidates: Sequence[str]) -> Optional[date]:
    properties = lead.get("properties", {})
    property_name = _first_existing(properties, candidates)
    if not property_name:
        return None
    return _date_value(properties.get(property_name, {}))


def _lead_name(lead: Dict[str, Any]) -> str:
    properties = lead.get("properties", {})
    property_name = _first_existing(properties, NAME_CANDIDATES)
    if property_name:
        name = _text(properties.get(property_name, {}))
        if name:
            return name
    return lead.get("id", "<unknown>")


def _lead_status(lead: Dict[str, Any]) -> str:
    return _normalize(_lead_text(lead, LEAD_STATUS_CANDIDATES))


def _lead_reply_status(lead: Dict[str, Any]) -> str:
    return _normalize(_lead_text(lead, REPLY_STATUS_CANDIDATES))


def _lead_gmail_sent_status(lead: Dict[str, Any]) -> str:
    return _normalize(_lead_text(lead, GMAIL_SENT_STATUS_CANDIDATES))


def _lead_gmail_match_status(lead: Dict[str, Any]) -> str:
    return _normalize(_lead_text(lead, GMAIL_MATCH_STATUS_CANDIDATES))


def _lead_casl_basis(lead: Dict[str, Any]) -> str:
    return _normalize(_lead_text(lead, CASL_BASIS_CANDIDATES))


def _lead_duplicate_status(lead: Dict[str, Any]) -> str:
    return _normalize(_lead_text(lead, DUPLICATE_STATUS_CANDIDATES))


def _lead_send_mode(lead: Dict[str, Any]) -> str:
    return _normalize(_lead_text(lead, SEND_MODE_CANDIDATES))


def _lead_email(lead: Dict[str, Any]) -> str:
    return _lead_text(lead, EMAIL_CANDIDATES)


def _lead_phone(lead: Dict[str, Any]) -> str:
    return _lead_text(lead, PHONE_CANDIDATES)


def _lead_website(lead: Dict[str, Any]) -> str:
    return _lead_text(lead, WEBSITE_CANDIDATES)


def _lead_draft_id(lead: Dict[str, Any]) -> str:
    return _lead_text(lead, GMAIL_DRAFT_ID_CANDIDATES)


def _lead_country(lead: Dict[str, Any]) -> str:
    return _normalize(_lead_text(lead, COUNTRY_CANDIDATES))


def _lead_do_not_contact(lead: Dict[str, Any]) -> bool:
    return _lead_checkbox(lead, DO_NOT_CONTACT_CANDIDATES)


def _lead_admin_approved(lead: Dict[str, Any]) -> bool:
    return send_flow._lead_admin_approved(lead)  # type: ignore[attr-defined]


def _lead_top_issue(lead: Dict[str, Any]) -> str:
    return _lead_text(lead, TOP_ISSUE_CANDIDATES)


def _lead_outreach_angle(lead: Dict[str, Any]) -> str:
    return _lead_text(lead, OUTREACH_ANGLE_CANDIDATES)


def _lead_follow_up_due_now(lead: Dict[str, Any]) -> bool:
    properties = lead.get("properties", {})
    property_name = _first_existing(properties, FOLLOW_UP_DUE_NOW_CANDIDATES)
    if not property_name:
        return False
    prop = properties.get(property_name, {})
    formula = prop.get("formula", {})
    if isinstance(formula, dict) and formula.get("type") == "boolean":
        return bool(formula.get("boolean"))
    return _normalize(_text(prop)) in {"true", "yes", "1"}


def _lead_next_follow_up(lead: Dict[str, Any]) -> Optional[date]:
    return _lead_date(lead, NEXT_FOLLOW_UP_CANDIDATES)


def _lead_scheduled_send_date(lead: Dict[str, Any]) -> Optional[date]:
    return _lead_date(lead, SCHEDULED_SEND_DATE_CANDIDATES)


def _lead_sequence_step(lead: Dict[str, Any]) -> str:
    return _lead_text(lead, SEQUENCE_STEP_CANDIDATES)


def _lead_has_replied(lead: Dict[str, Any]) -> bool:
    return (
        _lead_status(lead) in REPLIED_STATUS_VALUES
        or _lead_reply_status(lead) in REPLIED_STATUS_VALUES
        or _lead_gmail_match_status(lead) in REPLIED_STATUS_VALUES
    )


def _lead_has_sent(lead: Dict[str, Any]) -> bool:
    return _lead_gmail_sent_status(lead) in SENT_STATUS_VALUES or _lead_gmail_match_status(lead) == "sent_exists"


def _lead_is_missing_required_content(lead: Dict[str, Any]) -> List[str]:
    blockers: List[str] = []
    if not _lead_email(lead):
        blockers.append("missing_email")
    if not _lead_website(lead):
        blockers.append("missing_website")
    return blockers


def _lead_is_send_ready(lead: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Return (send_ready, blockers) using the Ops-Status-based readiness rule.

    Admin Approved and Send Mode are no longer required gates; Scheduled Send Date is.
    """
    blockers: List[str] = []
    if _lead_status(lead) == "not_fit":
        blockers.append("lead_status_not_fit")
    if _lead_country(lead) != CANADA_COUNTRY:
        blockers.append("non_canada")
    if _lead_do_not_contact(lead):
        blockers.append("do_not_contact")
    if _lead_duplicate_status(lead) not in SAFE_DUPLICATE_VALUES:
        blockers.append(f"duplicate_status_{_lead_duplicate_status(lead) or 'unknown'}")
    if _lead_casl_basis(lead) not in CASL_READY_VALUES:
        blockers.append(f"casl_basis_{_lead_casl_basis(lead) or 'missing'}")
    if not _lead_draft_id(lead):
        blockers.append("missing_gmail_draft_id")
    if not _lead_scheduled_send_date(lead):
        blockers.append("missing_scheduled_send_date")
    return len(blockers) == 0, blockers


def _lead_is_active_draft_but_not_send_ready(lead: Dict[str, Any], *, allow_rule_based_approval: bool) -> List[str]:
    blockers: List[str] = []
    if _lead_send_mode(lead) not in APPROVED_SEND_MODES:
        blockers.append(f"send_mode_{_lead_send_mode(lead) or 'missing'}")
    if not allow_rule_based_approval and not _lead_admin_approved(lead):
        blockers.append("admin_approval_required")
    if _lead_duplicate_status(lead) not in SAFE_DUPLICATE_VALUES:
        blockers.append(f"duplicate_status_{_lead_duplicate_status(lead) or 'unknown'}")
    if _lead_casl_basis(lead) not in CASL_READY_VALUES:
        blockers.append(f"casl_basis_{_lead_casl_basis(lead) or 'missing'}")
    return blockers


def _lead_ready_to_draft(lead: Dict[str, Any]) -> bool:
    lead_status = _lead_status(lead)
    return bool(
        lead_status in READY_TO_DRAFT_STATUS_VALUES
        or _lead_top_issue(lead)
        or _lead_outreach_angle(lead)
    )


def _lead_follow_up_due_status(lead: Dict[str, Any]) -> bool:
    if _lead_has_replied(lead):
        return False
    sequence_step = _lead_sequence_step(lead)
    if sequence_step in {"Email 3 Sent", "Sequence Complete"}:
        return False
    follow_up_eligible = (
        sequence_step in {"Email 1 Sent", "Email 2 Sent"}
        or _lead_status(lead) in {"outreach_sent", "email_1_sent", "email_2_sent"}
    )
    if not follow_up_eligible:
        return False
    due_now = _lead_follow_up_due_now(lead)
    next_follow_up = _lead_next_follow_up(lead)
    today = datetime.now(timezone.utc).date()
    return due_now or (next_follow_up is not None and today >= next_follow_up)


def _blocker_reason_for_draft_health(lead: Dict[str, Any]) -> Optional[str]:
    draft_id = _lead_draft_id(lead)
    if not draft_id:
        return None

    if not CHECK_GMAIL_DRAFT_HEALTH:
        return None

    try:
        draft = get_draft(draft_id)
        block_reason = send_flow._active_draft_block_reason(  # type: ignore[attr-defined]
            draft_id,
            extract_draft_details(draft),
        )
        return block_reason
    except Exception as exc:
        if send_flow._is_stale_gmail_draft_error(exc):  # type: ignore[attr-defined]
            return "stale_gmail_draft_id"
        if isinstance(exc, HttpError) and getattr(exc.resp, "status", None) == 404:
            return "stale_gmail_draft_id"
        return "gmail_draft_health_error"


def _normalize_email_key(value: str) -> str:
    return _normalize(value)


def _normalize_phone_key(value: str) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits


def _duplicate_group_key(lead: Dict[str, Any], field: str) -> Tuple[str, str]:
    if field == "email":
        raw_value = _lead_email(lead)
        return raw_value, _normalize_email_key(raw_value)
    if field == "phone":
        raw_value = _lead_phone(lead)
        return raw_value, _normalize_phone_key(raw_value)
    return "", ""


def _duplicate_group_candidate(lead: Dict[str, Any]) -> bool:
    if _lead_has_sent(lead) or _lead_has_replied(lead):
        return False
    lead_status = _lead_status(lead)
    if lead_status in IGNORED_DUPLICATE_GROUP_STATUSES or lead_status in {"duplicate", "already_contacted"}:
        return False
    if _lead_do_not_contact(lead):
        return False
    return True


@dataclass
class DuplicateGroup:
    field: str
    normalized_value: str
    raw_value: str
    records: List[Dict[str, Any]]


def _find_duplicate_groups(records: List[Dict[str, Any]]) -> Tuple[List[DuplicateGroup], set[str]]:
    grouped: Dict[str, Dict[str, List[Dict[str, Any]]]] = {
        "email": defaultdict(list),
        "phone": defaultdict(list),
    }

    for record in records:
        if not _duplicate_group_candidate(record):
            continue
        for field in ("email", "phone"):
            raw_value, normalized_value = _duplicate_group_key(record, field)
            if not raw_value or not normalized_value:
                continue
            grouped[field][normalized_value].append(record)

    groups: List[DuplicateGroup] = []
    member_ids: set[str] = set()
    for field, buckets in grouped.items():
        for normalized_value, bucket in buckets.items():
            if len(bucket) < 2:
                continue
            raw_value = _duplicate_group_key(bucket[0], field)[0]
            groups.append(
                DuplicateGroup(
                    field=field,
                    normalized_value=normalized_value,
                    raw_value=raw_value,
                    records=bucket,
                )
            )
            member_ids.update(record["id"] for record in bucket)

    groups.sort(key=lambda group: (group.field, group.normalized_value))
    return groups, member_ids


def classify_lead(
    lead: Dict[str, Any],
    *,
    duplicate_group_membership: set[str],
) -> Classification:
    if _lead_has_replied(lead):
        return Classification("replied", [], "replied")
    if _lead_follow_up_due_status(lead):
        return Classification("follow_up_due", [], "follow_up_due")
    if _lead_has_sent(lead):
        return Classification("sent", [], "sent")

    if _lead_do_not_contact(lead):
        return Classification("do_not_contact", ["do_not_contact"], "do_not_contact")

    lead_status = _lead_status(lead)
    if lead_status == "not_fit":
        return Classification("not_fit", ["lead_status_not_fit"], "lead_status_not_fit")
    if lead_status in {"archived", "paid_client"}:
        return Classification("blocked", [f"lead_status_{lead_status}"], f"lead_status_{lead_status}")

    if _lead_country(lead) != CANADA_COUNTRY:
        return Classification("not_fit", ["non_canada"], "non_canada")

    duplicate_status = _lead_duplicate_status(lead)
    if duplicate_status in DUPLICATE_STATUS_REVIEW_VALUES:
        return Classification(DUPLICATE_REVIEW_STATUS, [DUPLICATE_REVIEW_REASON], DUPLICATE_REVIEW_REASON)
    if duplicate_status in DUPLICATE_STATUS_DO_NOT_CONTACT_VALUES:
        return Classification("do_not_contact", ["do_not_contact"], "do_not_contact")
    if duplicate_status in DUPLICATE_STATUS_ACTIVE_BLOCKED_VALUES:
        return Classification("blocked", [f"duplicate_status_{duplicate_status}"], f"duplicate_status_{duplicate_status}")
    if lead.get("id") in duplicate_group_membership:
        return Classification(DUPLICATE_REVIEW_STATUS, [DUPLICATE_REVIEW_REASON], DUPLICATE_REVIEW_REASON)

    missing_research = _lead_is_missing_required_content(lead)
    if "missing_email" in missing_research:
        return Classification("needs_email_research", missing_research, "missing_email")
    if "missing_website" in missing_research:
        return Classification("needs_website_research", missing_research, "missing_website")

    casl_basis = _lead_casl_basis(lead)
    if not casl_basis:
        return Classification("needs_casl_review", ["casl_missing"], "casl_missing")
    if casl_basis in MANUAL_CASL_VALUES:
        return Classification("needs_casl_review", ["casl_manual_review"], "casl_manual_review")

    draft_health_reason = _blocker_reason_for_draft_health(lead)
    if draft_health_reason:
        return Classification("needs_reconciliation", [draft_health_reason], draft_health_reason)

    draft_id = _lead_draft_id(lead)
    if draft_id:
        send_ready, send_blockers = _lead_is_send_ready(lead)
        if send_ready:
            return Classification("ready_to_send", [], "ready_to_send")
        return Classification("draft_created", send_blockers, "draft_created")

    if _lead_ready_to_draft(lead):
        return Classification("ready_to_draft", [], "ready_to_draft")

    blockers: List[str] = []
    if not _lead_top_issue(lead):
        blockers.append("missing_top_issue")
    if not _lead_outreach_angle(lead):
        blockers.append("missing_outreach_angle")
    if _lead_status(lead) not in READY_TO_DRAFT_STATUS_VALUES:
        blockers.append(f"lead_status_{lead_status or 'missing'}")
    if not blockers:
        blockers.append("not_draft_ready")
    return Classification("blocked", blockers, blockers[0])


def _query_all_records() -> List[Dict[str, Any]]:
    client = get_client()
    _, data_source_id = get_database_and_data_source()
    records: List[Dict[str, Any]] = []
    next_cursor: Optional[str] = None
    while True:
        kwargs: Dict[str, Any] = {"data_source_id": data_source_id, "page_size": 100}
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


def _field_info(schema_properties: Dict[str, Any], candidates: Sequence[str]) -> Tuple[Optional[str], Optional[str]]:
    field_name = _first_existing(schema_properties, candidates)
    if not field_name:
        return None, None
    field_type = schema_properties.get(field_name, {}).get("type")
    return field_name, str(field_type) if field_type else None


def _property_text_value(prop: Dict[str, Any]) -> str:
    return _text(prop)


def _property_update(property_type: Optional[str], value: Any) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    if property_type == "rich_text":
        return {"rich_text": [{"type": "text", "text": {"content": str(value)}}]}
    if property_type == "multi_select":
        values = [str(item).strip() for item in value if str(item).strip()] if isinstance(value, list) else [str(value).strip()]
        return {"multi_select": [{"name": item} for item in values]}
    if property_type == "select":
        return {"select": {"name": str(value)}}
    if property_type == "status":
        return {"status": {"name": str(value)}}
    if property_type == "checkbox":
        return {"checkbox": bool(value)}
    if property_type == "date":
        return {"date": {"start": str(value)}}
    return None


def _clear_property_update(property_type: Optional[str]) -> Optional[Dict[str, Any]]:
    if property_type == "rich_text":
        return {"rich_text": []}
    if property_type == "multi_select":
        return {"multi_select": []}
    if property_type == "select":
        return {"select": None}
    if property_type == "status":
        return {"status": None}
    return None


def _build_ops_updates(
    schema_properties: Dict[str, Any],
    status: str,
    blockers: List[str],
) -> Dict[str, Any]:
    updates: Dict[str, Any] = {}
    status_field, status_type = _field_info(schema_properties, OPS_STATUS_CANDIDATES)
    blocker_field, blocker_type = _field_info(schema_properties, BLOCKER_REASON_CANDIDATES)

    if status_field and status in OPS_STATUS_VALUES:
        update = _property_update(status_type, status)
        if update:
            updates[status_field] = update

    if blocker_field:
        if blockers:
            update = _property_update(blocker_type, blockers)
            if update:
                updates[blocker_field] = update
        else:
            clear_update = _clear_property_update(blocker_type)
            if clear_update is not None:
                updates[blocker_field] = clear_update

    return updates


def _current_ops_values(lead: Dict[str, Any], schema_properties: Dict[str, Any]) -> Tuple[str, str]:
    status_field, _ = _field_info(schema_properties, OPS_STATUS_CANDIDATES)
    blocker_field, blocker_type = _field_info(schema_properties, BLOCKER_REASON_CANDIDATES)
    status_value = _text(lead.get("properties", {}).get(status_field or "", {})) if status_field else ""
    blocker_value = ""
    if blocker_field:
        blocker_prop = lead.get("properties", {}).get(blocker_field, {})
        blocker_value = _text(blocker_prop)
        if blocker_type == "multi_select":
            blocker_value = ", ".join(
                sorted({str(item.get("name", "")).strip() for item in blocker_prop.get("multi_select", []) if str(item.get("name", "")).strip()})
            )
    return _normalize(status_value), _normalize(blocker_value)


def _print_counter(title: str, counts: Counter[str]) -> None:
    print(title)
    for key, value in counts.most_common():
        print(f"- {key}: {value}")


def _print_examples(examples_by_status: Dict[str, List[str]]) -> None:
    print("Examples by Ops Status")
    for status in sorted(examples_by_status.keys()):
        examples = examples_by_status[status][:3]
        print(f"- {status}: {', '.join(examples)}")


def _print_duplicate_groups(groups: List[DuplicateGroup]) -> None:
    print("Duplicate groups")
    if not groups:
        print("- none")
        return

    for group in groups:
        examples = []
        for record in group.records[:3]:
            examples.append(_lead_name(record))
        print(
            f"- {group.field.title()}={group.raw_value or group.normalized_value} | "
            f"records={len(group.records)} | examples={', '.join(examples)}"
        )


def main() -> None:
    records = _query_all_records()
    schema = get_data_source_schema()
    schema_properties = schema.get("properties", {})
    ops_status_field, ops_status_type = _field_info(schema_properties, OPS_STATUS_CANDIDATES)
    blocker_field, blocker_type = _field_info(schema_properties, BLOCKER_REASON_CANDIDATES)
    duplicate_groups, duplicate_group_membership = _find_duplicate_groups(records)

    print("Outreach Ops Status Classifier")
    print(f"- OPS_STATUS_DRY_RUN: {'yes' if OPS_STATUS_DRY_RUN else 'no'}")
    print(f"- CHECK_GMAIL_DRAFT_HEALTH: {'yes' if CHECK_GMAIL_DRAFT_HEALTH else 'no'}")
    print(f"- ALLOW_RULE_BASED_APPROVAL: {'yes' if ALLOW_RULE_BASED_APPROVAL else 'no'}")
    print(f"- records loaded: {len(records)}")
    print(f"- Ops Status field: {ops_status_field or '<missing>'} ({ops_status_type or 'unsupported'})")
    print(f"- Blocker Reason field: {blocker_field or '<missing>'} ({blocker_type or 'unsupported'})")
    if not ops_status_field:
        print("- Warning: Ops Status field is missing; classifier will only preview unless the field exists.")
    if not blocker_field:
        print("- Warning: Blocker Reason field is missing; classifier will only preview blocker codes.")
    print(f"- duplicate groups found: {len(duplicate_groups)}")
    _print_duplicate_groups(duplicate_groups)

    status_counts: Counter[str] = Counter()
    blocker_counts: Counter[str] = Counter()
    examples_by_status: Dict[str, List[str]] = defaultdict(list)
    live_updates: List[Tuple[str, Dict[str, Any], Classification]] = []
    would_update = 0
    blocked_for_schema = 0

    for record in records:
        classification = classify_lead(
            record,
            duplicate_group_membership=duplicate_group_membership,
        )
        status_counts[classification.status] += 1
        if classification.blockers:
            for blocker in classification.blockers:
                blocker_counts[blocker] += 1
        lead_name = _lead_name(record)
        if len(examples_by_status[classification.status]) < 3:
            examples_by_status[classification.status].append(lead_name)

        current_status, current_blockers = _current_ops_values(record, schema_properties)
        proposed_status = _normalize(classification.status)
        proposed_blockers = _normalize(", ".join(classification.blockers))
        if ops_status_field and blocker_field:
            if current_status != proposed_status or current_blockers != proposed_blockers:
                would_update += 1
                live_updates.append((record["id"], record, classification))
        elif ops_status_field or blocker_field:
            if current_status != proposed_status or (classification.blockers and current_blockers != proposed_blockers):
                would_update += 1
                live_updates.append((record["id"], record, classification))
        else:
            blocked_for_schema += 1

    print("")
    print("Proposed Ops Status counts")
    _print_counter("Ops Status counts:", status_counts)
    print("")
    print(f"- would_update: {would_update}")
    if blocked_for_schema:
        print(f"- schema-blocked records: {blocked_for_schema}")
    print("")
    _print_counter("Top blocker reasons:", blocker_counts)
    print("")
    _print_examples(examples_by_status)

    if OPS_STATUS_DRY_RUN:
        print("")
        print("Dry run mode: no Notion writes were made.")
        return

    if not ops_status_field and not blocker_field:
        print("")
        print("Live mode requested, but Ops Status and Blocker Reason fields are both missing. No updates applied.")
        return

    client = get_client()
    updated = 0
    skipped_missing_schema = 0
    for record_id, record, classification in live_updates:
        updates = _build_ops_updates(schema_properties, classification.status, classification.blockers)
        if not updates:
            skipped_missing_schema += 1
            continue
        try:
            client.pages.update(page_id=record_id, properties=updates)
            updated += 1
            print(f"UPDATED | {_lead_name(record)} | Ops Status={classification.status} | Blockers={', '.join(classification.blockers) or '<none>'}")
        except Exception as exc:
            print(f"ERROR | {_lead_name(record)} | {exc}")

    print("")
    print("Ops Status update summary")
    print(f"- records_checked: {len(records)}")
    print(f"- records_updated: {updated}")
    print(f"- would_update: {would_update}")
    print(f"- skipped_missing_schema: {skipped_missing_schema}")


if __name__ == "__main__":
    main()
