from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from notion_client import Client

from agents import generate_drafts_from_notion as draft_flow
from src.config import settings
from src.notion_client import get_data_source_schema, get_database_and_data_source


def _env_flag(name: str, default: bool = True) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


SEQUENCE_BACKFILL_DRY_RUN = _env_flag("SEQUENCE_BACKFILL_DRY_RUN", True)

# Field candidates
SEQUENCE_STEP_CANDIDATES: List[str] = list(getattr(draft_flow, "SEQUENCE_STEP_CANDIDATES", ["Sequence Step"]))
LAST_OUTREACH_DATE_CANDIDATES: List[str] = list(getattr(draft_flow, "LAST_OUTREACH_DATE_CANDIDATES", ["Last Outreach Date", "Last Email Sent At"]))
NEXT_FOLLOW_UP_DATE_CANDIDATES: List[str] = list(getattr(draft_flow, "NEXT_FOLLOW_UP_DATE_CANDIDATES", ["Next Follow-up Date", "Next Follow Up Date"]))
EMAIL_1_DATE_CANDIDATES: List[str] = list(getattr(draft_flow, "EMAIL_1_DATE_CANDIDATES", ["Email 1 Date"]))
GMAIL_SENT_STATUS_CANDIDATES: List[str] = list(draft_flow.GMAIL_SENT_STATUS_CANDIDATES)
GMAIL_MATCH_STATUS_CANDIDATES: List[str] = list(draft_flow.GMAIL_MATCH_STATUS_CANDIDATES)
REPLY_STATUS_CANDIDATES: List[str] = list(draft_flow.REPLY_STATUS_CANDIDATES)
DO_NOT_CONTACT_CANDIDATES: List[str] = list(draft_flow.DO_NOT_CONTACT_CANDIDATES)
OPS_STATUS_CANDIDATES: List[str] = list(getattr(draft_flow, "OPS_STATUS_CANDIDATES", ["Ops Status"]))
EMAIL_2_DRAFT_CANDIDATES: List[str] = list(getattr(draft_flow, "EMAIL_2_DRAFT_CANDIDATES", ["Email 2 Draft"]))
EMAIL_3_DRAFT_CANDIDATES: List[str] = list(getattr(draft_flow, "EMAIL_3_DRAFT_CANDIDATES", ["Email 3 Draft"]))

# Sequence step value sets
SKIP_SEQUENCE_STEPS = {"Email 2 Sent", "Email 3 Sent", "Sequence Complete", "Replied", "Not Fit"}
ALREADY_EMAIL_1_SENT = {"Email 1 Sent"}
EVIDENCE_EMAIL_2_STEPS = {"Email 2 Drafted", "Email 2 Sent"}
EVIDENCE_EMAIL_3_STEPS = {"Email 3 Drafted", "Email 3 Sent"}

# Follow-up days after each sequence step
FOLLOW_UP_DAYS_AFTER_EMAIL_1 = 3
FOLLOW_UP_DAYS_AFTER_EMAIL_2 = 5


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


def _prop(lead: Dict[str, Any], name: str) -> Dict[str, Any]:
    val = lead.get("properties", {}).get(name)
    return val if isinstance(val, dict) else {}


def _text(prop_value: Dict[str, Any]) -> str:
    if not prop_value:
        return ""
    if prop_value.get("rich_text"):
        return "".join(p.get("plain_text", "") for p in prop_value["rich_text"]).strip()
    if prop_value.get("title"):
        return "".join(p.get("plain_text", "") for p in prop_value["title"]).strip()
    if prop_value.get("email"):
        return str(prop_value["email"]).strip()
    if prop_value.get("select"):
        return str(prop_value["select"].get("name", "")).strip()
    if prop_value.get("status"):
        return str(prop_value["status"].get("name", "")).strip()
    if prop_value.get("checkbox") is not None:
        return "true" if prop_value["checkbox"] else "false"
    if prop_value.get("date"):
        return str(prop_value["date"].get("start", "")).strip()
    return ""


def _date_val(prop_value: Dict[str, Any]) -> Optional[date]:
    if not prop_value:
        return None
    date_obj = prop_value.get("date") or {}
    start = date_obj.get("start") if isinstance(date_obj, dict) else None
    if not start:
        return None
    try:
        return datetime.fromisoformat(str(start)[:10]).date()
    except ValueError:
        return None


def _lead_text(lead: Dict[str, Any], candidates: Sequence[str]) -> str:
    field = _first_existing(lead.get("properties", {}), candidates)
    return _text(_prop(lead, field)) if field else ""


def _lead_date(lead: Dict[str, Any], candidates: Sequence[str]) -> Optional[date]:
    field = _first_existing(lead.get("properties", {}), candidates)
    return _date_val(_prop(lead, field)) if field else None


def _lead_name(lead: Dict[str, Any]) -> str:
    return draft_flow._get_lead_name(lead)  # type: ignore[attr-defined]


def _lead_replied(lead: Dict[str, Any]) -> bool:
    ops = _normalize(_lead_text(lead, OPS_STATUS_CANDIDATES))
    if ops == "replied":
        return True
    reply = _normalize(_lead_text(lead, REPLY_STATUS_CANDIDATES))
    if reply in {"replied", "yes", "true", "1"}:
        return True
    gmail_match = _normalize(_lead_text(lead, GMAIL_MATCH_STATUS_CANDIDATES))
    if gmail_match == "replied":
        return True
    return False


def _lead_do_not_contact(lead: Dict[str, Any]) -> bool:
    field = _first_existing(lead.get("properties", {}), DO_NOT_CONTACT_CANDIDATES)
    if not field:
        return False
    pval = _prop(lead, field)
    if "checkbox" in pval:
        return bool(pval["checkbox"])
    return _normalize(_text(pval)) in {"true", "yes", "1"}


def _lead_is_sent(lead: Dict[str, Any]) -> bool:
    gmail_sent = _normalize(_lead_text(lead, GMAIL_SENT_STATUS_CANDIDATES))
    if gmail_sent == "sent":
        return True
    gmail_match = _normalize(_lead_text(lead, GMAIL_MATCH_STATUS_CANDIDATES))
    if gmail_match == "sent_exists":
        return True
    ops = _normalize(_lead_text(lead, OPS_STATUS_CANDIDATES))
    if ops == "sent":
        return True
    return False


def _lead_sequence_step(lead: Dict[str, Any]) -> str:
    return _lead_text(lead, SEQUENCE_STEP_CANDIDATES)


def _lead_last_outreach_date(lead: Dict[str, Any]) -> Optional[date]:
    d = _lead_date(lead, LAST_OUTREACH_DATE_CANDIDATES)
    if d:
        return d
    return _lead_date(lead, EMAIL_1_DATE_CANDIDATES)


def _lead_next_follow_up_date(lead: Dict[str, Any]) -> Optional[date]:
    return _lead_date(lead, NEXT_FOLLOW_UP_DATE_CANDIDATES)


def _lead_email_2_draft(lead: Dict[str, Any]) -> str:
    return _lead_text(lead, EMAIL_2_DRAFT_CANDIDATES)


def _lead_email_3_draft(lead: Dict[str, Any]) -> str:
    return _lead_text(lead, EMAIL_3_DRAFT_CANDIDATES)


def _add_business_days(start: date, days: int) -> date:
    current = start
    remaining = days
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


def _property_update(prop_type: str, value: Any) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    if prop_type == "select":
        return {"select": {"name": str(value)}}
    if prop_type == "status":
        return {"status": {"name": str(value)}}
    if prop_type == "rich_text":
        return {"rich_text": [{"type": "text", "text": {"content": str(value)}}]}
    if prop_type == "title":
        return {"title": [{"type": "text", "text": {"content": str(value)}}]}
    if prop_type == "date":
        return {"date": {"start": str(value)}}
    return None


def _set_field(
    updates: Dict[str, Any],
    schema_properties: Dict[str, Any],
    candidates: Sequence[str],
    value: Any,
) -> bool:
    field_name = _first_existing(schema_properties, candidates)
    if not field_name:
        return False
    prop_type = schema_properties[field_name].get("type", "")
    update_value = _property_update(prop_type, value)
    if update_value:
        updates[field_name] = update_value
        return True
    return False


@dataclass
class BackfillCandidate:
    lead: Dict[str, Any]
    target_step: str
    next_follow_up: Optional[date]
    uncertain_followup: bool = False
    missing_outreach_date: bool = False
    reasons: list = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.reasons is None:
            self.reasons = []


def _classify_sent_lead(lead: Dict[str, Any]) -> BackfillCandidate:
    sequence_step = _lead_sequence_step(lead)

    # Use Sequence Step as the authoritative signal.
    # Email 2/3 Draft field content is NOT evidence of sending — it contains templates
    # generated at draft-creation time for all 3 emails simultaneously.
    # Only explicit "Sent" Sequence Step values confirm a send happened.
    has_email_3_evidence = sequence_step in EVIDENCE_EMAIL_3_STEPS
    has_email_2_evidence = sequence_step in EVIDENCE_EMAIL_2_STEPS

    last_sent = _lead_last_outreach_date(lead)
    next_fu = _lead_next_follow_up_date(lead)
    uncertain = False
    missing_date = False

    if has_email_3_evidence:
        # Sequence Step explicitly shows Email 3 activity — treat as Email 3 Sent (uncertain
        # because we see "Drafted" not "Sent", but it's further than Email 1)
        target = "Email 3 Sent"
        uncertain = sequence_step not in {"Email 3 Sent"}
        next_fu = None  # no further follow-up after Email 3
    elif has_email_2_evidence:
        target = "Email 2 Sent"
        uncertain = sequence_step not in {"Email 2 Sent"}
        if not next_fu:
            if last_sent:
                next_fu = _add_business_days(last_sent, FOLLOW_UP_DAYS_AFTER_EMAIL_2)
            else:
                missing_date = True
    else:
        # Default: Email 1 Sent — covers empty Sequence Step, "Email 1 Drafted", legacy steps
        target = "Email 1 Sent"
        if not next_fu:
            if last_sent:
                next_fu = _add_business_days(last_sent, FOLLOW_UP_DAYS_AFTER_EMAIL_1)
            else:
                missing_date = True

    return BackfillCandidate(
        lead=lead,
        target_step=target,
        next_follow_up=next_fu,
        uncertain_followup=uncertain,
        missing_outreach_date=missing_date,
    )


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


def main() -> None:
    print("Sequence Step Backfill")
    print(f"- SEQUENCE_BACKFILL_DRY_RUN: {'yes' if SEQUENCE_BACKFILL_DRY_RUN else 'NO - LIVE WRITES ENABLED'}")
    print()

    schema = get_data_source_schema()
    schema_properties = schema.get("properties", {})
    leads = _query_all_leads()
    print(f"Loaded Notion records: {len(leads)}")
    print()

    summary: Dict[str, int] = {
        "records_checked": 0,
        "candidates_email1_sent": 0,
        "candidates_email2_sent": 0,
        "candidates_email3_sent": 0,
        "skipped_replied": 0,
        "skipped_dnc": 0,
        "skipped_existing_sequence_step": 0,
        "skipped_not_sent": 0,
        "skipped_already_email1_sent": 0,
        "missing_last_outreach_date": 0,
        "uncertain_followup_history": 0,
        "would_update": 0,
        "updated": 0,
        "errors": 0,
    }

    candidates: List[BackfillCandidate] = []
    example_log_limit = 8
    email1_examples: List[str] = []
    email2_examples: List[str] = []
    email3_examples: List[str] = []
    uncertain_examples: List[str] = []
    missing_date_examples: List[str] = []
    skipped_examples: List[str] = []

    for lead in leads:
        summary["records_checked"] += 1
        name = _lead_name(lead)

        if _lead_replied(lead):
            summary["skipped_replied"] += 1
            if len(skipped_examples) < example_log_limit:
                skipped_examples.append(f"SKIP replied | {name}")
            continue

        if _lead_do_not_contact(lead):
            summary["skipped_dnc"] += 1
            if len(skipped_examples) < example_log_limit:
                skipped_examples.append(f"SKIP dnc | {name}")
            continue

        current_step = _lead_sequence_step(lead)
        if current_step in SKIP_SEQUENCE_STEPS:
            summary["skipped_existing_sequence_step"] += 1
            if len(skipped_examples) < example_log_limit:
                skipped_examples.append(f"SKIP existing_step={current_step} | {name}")
            continue

        if current_step in ALREADY_EMAIL_1_SENT:
            summary["skipped_already_email1_sent"] += 1
            continue

        if not _lead_is_sent(lead):
            summary["skipped_not_sent"] += 1
            continue

        candidate = _classify_sent_lead(lead)

        if candidate.uncertain_followup:
            summary["uncertain_followup_history"] += 1
            if len(uncertain_examples) < example_log_limit:
                uncertain_examples.append(
                    f"UNCERTAIN | {name} | step={current_step or '<empty>'} | target={candidate.target_step}"
                )

        if candidate.missing_outreach_date:
            summary["missing_last_outreach_date"] += 1
            if len(missing_date_examples) < example_log_limit:
                missing_date_examples.append(f"MISSING_DATE | {name} | target={candidate.target_step}")

        if candidate.target_step == "Email 1 Sent":
            summary["candidates_email1_sent"] += 1
            if len(email1_examples) < example_log_limit:
                fu = candidate.next_follow_up.isoformat() if candidate.next_follow_up else "<none>"
                email1_examples.append(f"EMAIL1 | {name} | follow_up={fu}")
        elif candidate.target_step == "Email 2 Sent":
            summary["candidates_email2_sent"] += 1
            if len(email2_examples) < example_log_limit:
                email2_examples.append(f"EMAIL2 | {name}")
        elif candidate.target_step == "Email 3 Sent":
            summary["candidates_email3_sent"] += 1
            if len(email3_examples) < example_log_limit:
                email3_examples.append(f"EMAIL3 | {name}")

        summary["would_update"] += 1
        candidates.append(candidate)

    # Print proposal summary
    print("Backfill proposal:")
    for key in (
        "records_checked",
        "candidates_email1_sent",
        "candidates_email2_sent",
        "candidates_email3_sent",
        "skipped_replied",
        "skipped_dnc",
        "skipped_existing_sequence_step",
        "skipped_already_email1_sent",
        "skipped_not_sent",
        "missing_last_outreach_date",
        "uncertain_followup_history",
        "would_update",
    ):
        print(f"  {key}: {summary.get(key, 0)}")

    if email1_examples:
        print(f"\nEmail 1 Sent examples ({len(email1_examples)} shown):")
        for line in email1_examples:
            print(f"  {line}")
    if email2_examples:
        print(f"\nEmail 2 Sent examples ({len(email2_examples)} shown):")
        for line in email2_examples:
            print(f"  {line}")
    if email3_examples:
        print(f"\nEmail 3 Sent examples ({len(email3_examples)} shown):")
        for line in email3_examples:
            print(f"  {line}")
    if uncertain_examples:
        print(f"\nUncertain follow-up history ({len(uncertain_examples)} shown):")
        for line in uncertain_examples:
            print(f"  {line}")
    if missing_date_examples:
        print(f"\nMissing Last Outreach Date ({len(missing_date_examples)} shown):")
        for line in missing_date_examples:
            print(f"  {line}")
    if skipped_examples:
        print(f"\nSkipped examples:")
        for line in skipped_examples:
            print(f"  {line}")

    if SEQUENCE_BACKFILL_DRY_RUN:
        print(f"\nDry run: {summary['would_update']} records would be updated. No writes made.")
        return

    # Live write path
    print(f"\nLive write: updating {len(candidates)} records...")
    client = get_client()

    for candidate in candidates:
        lead = candidate.lead
        name = _lead_name(lead)
        updates: Dict[str, Any] = {}

        _set_field(updates, schema_properties, SEQUENCE_STEP_CANDIDATES, candidate.target_step)
        if candidate.next_follow_up is not None:
            _set_field(
                updates,
                schema_properties,
                NEXT_FOLLOW_UP_DATE_CANDIDATES,
                candidate.next_follow_up.isoformat(),
            )

        if not updates:
            print(f"  SKIP | {name} | no writable fields found in schema")
            continue

        try:
            client.pages.update(page_id=lead["id"], properties=updates)
            summary["updated"] += 1
            fu_str = candidate.next_follow_up.isoformat() if candidate.next_follow_up else "<not set>"
            print(f"  UPDATED | {name} | Sequence Step -> {candidate.target_step} | Next Follow-up -> {fu_str}")
        except Exception as exc:
            summary["errors"] += 1
            print(f"  ERROR | {name} | {exc}")

    print("\nBackfill complete:")
    for key in ("would_update", "updated", "errors"):
        print(f"  {key}: {summary.get(key, 0)}")


if __name__ == "__main__":
    main()
