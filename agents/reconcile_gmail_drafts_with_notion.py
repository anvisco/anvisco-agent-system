from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional, Tuple

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.config import settings
from src.gmail_client import create_draft, extract_draft_details, get_draft, get_preferred_send_as_email
from src.notion_client import get_data_source_schema

from agents import generate_drafts_from_notion as draft_flow
from agents import send_approved_gmail_drafts as send_flow


RECONCILE_DRY_RUN = os.getenv("RECONCILE_DRY_RUN", "true").strip().lower() in {"1", "true", "yes", "on"}


def _max_reconcile_drafts() -> int:
    raw_value = os.getenv("MAX_RECONCILE_DRAFTS", "20")
    if not raw_value.strip():
        return 20
    try:
        return max(1, int(raw_value))
    except ValueError:
        return 20


MAX_RECONCILE_DRAFTS = _max_reconcile_drafts()
ANVIS_LEADS_LABEL = "Anvis/Leads"


def _verified_send_as_email() -> str:
    return get_preferred_send_as_email(settings.gmail_send_as_email)


def _draft_ids_from_response(draft: Dict[str, Any]) -> Tuple[str, str]:
    draft_id = str(draft.get("id", "") or "").strip()
    thread_id = str(draft.get("message", {}).get("threadId", "") or "").strip()
    return draft_id, thread_id


def _log_rebuild_preview(lead_name: str, draft_id: str, reason: str, subject: str, email: str) -> None:
    action = "WOULD REBUILD" if RECONCILE_DRY_RUN else "REBUILDING"
    print(
        f"{action} | {lead_name} | Gmail Draft ID: {draft_id or '<missing>'} | "
        f"Reason: {reason} | to {email or '<none>'} | subject {subject or '<no subject>'}"
    )
    print(f"- label after create: {ANVIS_LEADS_LABEL}")


def main() -> None:
    schema = get_data_source_schema()
    schema_properties = schema.get("properties", {})
    ops_status_property = send_flow._first_existing_property_name(  # type: ignore[attr-defined]
        schema_properties,
        send_flow.OPS_STATUS_CANDIDATES,  # type: ignore[attr-defined]
    )
    all_leads = draft_flow.query_all_leads_for_debug()
    legacy_approval_path_used = False
    if ops_status_property:
        leads = [
            lead
            for lead in all_leads
            if send_flow._lead_ops_status(lead) == send_flow.OPS_READY_TO_SEND  # type: ignore[attr-defined]
        ]
    elif send_flow.ALLOW_LEGACY_STATUS_FALLBACK:  # type: ignore[attr-defined]
        leads = all_leads
        legacy_approval_path_used = True
    else:
        leads = []
    verified_from_email = _verified_send_as_email()

    if settings.gmail_send_as_email and not verified_from_email:
        print(
            f"Warning: Gmail send-as alias {settings.gmail_send_as_email} is not verified. "
            "Fresh draft creation will fall back to the authenticated account if needed."
        )

    print("Reconcile gate:")
    print(f"- dry run: {'yes' if RECONCILE_DRY_RUN else 'no'}")
    print(f"- max drafts per run: {MAX_RECONCILE_DRAFTS}")
    print(f"- label: {ANVIS_LEADS_LABEL}")
    print(f"- Gmail send-as alias: {settings.gmail_send_as_email}")
    print(f"- Verified alias: {'yes' if verified_from_email else 'no'}")
    print(f"- workflow source: {'Ops Status' if ops_status_property else 'Ops Status missing'}")
    print(
        "- legacy fallback enabled: "
        f"{'yes' if send_flow.ALLOW_LEGACY_STATUS_FALLBACK else 'no'}"  # type: ignore[attr-defined]
    )
    print(
        "- active approval source: "
        f"{'Ops Status only' if ops_status_property else ('legacy fallback' if legacy_approval_path_used else 'none - fail closed')}"
    )
    print(f"- legacy approval path used: {'yes' if legacy_approval_path_used else 'no'}")
    if ops_status_property:
        print(f"- ops_ready_to_send selected: {len(leads)}")
    elif not legacy_approval_path_used:
        print("- Ops Status field missing; legacy status fallback is disabled.")
    print(f"Loaded Notion records before source-of-truth filtering: {len(all_leads)}")
    print(f"Loaded Notion records: {len(leads)}")

    summary = {
        "records_checked": 0,
        "approved_by_ops": 0,
        "approved_by_admin": 0,
        "approved_by_rules": 0,
        "eligible_records": 0,
        "selected": 0,
        "would_create": 0,
        "drafts_created": 0,
        "notion_updated": 0,
        "active_drafts_kept": 0,
        "stale_gmail_draft_id": 0,
        "not_active_draft": 0,
        "skipped_missing_gmail_draft_id": 0,
        "skipped_ineligible": 0,
        "errors": 0,
    }
    skip_reasons: Dict[str, int] = {}
    selected: List[Tuple[Dict[str, Any], str]] = []

    for lead in leads:
        summary["records_checked"] += 1
        lead_name = send_flow._lead_name(lead)  # type: ignore[attr-defined]

        if ops_status_property:
            block_reasons = send_flow._ops_send_safety_block_reasons(lead)  # type: ignore[attr-defined]
            approval_path = "ops"
        elif legacy_approval_path_used:
            block_reasons = send_flow._lead_send_block_reasons(lead)  # type: ignore[attr-defined]
            approval_path = send_flow._lead_approval_path(lead)  # type: ignore[attr-defined]
        else:
            block_reasons = ["Ops Status field is missing and legacy status fallback is disabled"]
            approval_path = ""
        if block_reasons:
            summary["skipped_ineligible"] += 1
            for reason in block_reasons:
                skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
            continue

        if approval_path == "ops":
            summary["approved_by_ops"] += 1
        elif approval_path == "admin":
            summary["approved_by_admin"] += 1
        elif approval_path == "rule":
            summary["approved_by_rules"] += 1

        draft_id = send_flow._lead_gmail_draft_id(lead)  # type: ignore[attr-defined]
        if not draft_id:
            summary["skipped_missing_gmail_draft_id"] += 1
            skip_reasons["missing_gmail_draft_id"] = skip_reasons.get("missing_gmail_draft_id", 0) + 1
            print(f"SKIP | {lead_name} | Gmail Draft ID: <missing> | Reason: missing_gmail_draft_id")
            continue

        try:
            draft = get_draft(draft_id)
            draft_details = extract_draft_details(draft)
            active_block_reason = send_flow._active_draft_block_reason(draft_id, draft_details)  # type: ignore[attr-defined]
            if active_block_reason:
                summary[active_block_reason] += 1
                skip_reasons[active_block_reason] = skip_reasons.get(active_block_reason, 0) + 1
                selected.append((lead, active_block_reason))
                continue

            summary["active_drafts_kept"] += 1
        except Exception as exc:
            if send_flow._is_stale_gmail_draft_error(exc):  # type: ignore[attr-defined]
                summary["stale_gmail_draft_id"] += 1
                skip_reasons["stale_gmail_draft_id"] = skip_reasons.get("stale_gmail_draft_id", 0) + 1
                selected.append((lead, "stale_gmail_draft_id"))
                continue
            summary["errors"] += 1
            print(f"ERROR | {lead_name} | Gmail Draft ID: {draft_id} | {exc}")
            continue

    summary["eligible_records"] = len(selected)
    selected = selected[:MAX_RECONCILE_DRAFTS]
    summary["selected"] = len(selected)
    summary["would_create"] = len(selected) if RECONCILE_DRY_RUN else 0

    print(f"Eligible records: {summary['eligible_records']}")
    print(f"Selected records: {summary['selected']}")

    for lead, reason in selected:
        lead_name = send_flow._lead_name(lead)  # type: ignore[attr-defined]
        draft_id = send_flow._lead_gmail_draft_id(lead)  # type: ignore[attr-defined]
        sequence, email = draft_flow.process_lead(lead)
        if not sequence or not email:
            summary["errors"] += 1
            print(f"ERROR | {lead_name} | Gmail Draft ID: {draft_id} | unable to generate draft copy")
            continue

        email_1 = sequence["emails"]["email_1"]
        _log_rebuild_preview(lead_name, draft_id, reason, email_1["subject"], email)

        if RECONCILE_DRY_RUN:
            continue

        try:
            draft = create_draft(
                email,
                email_1["subject"],
                email_1["body"],
                from_email=verified_from_email,
                label_name=ANVIS_LEADS_LABEL,
            )
            new_draft_id, new_thread_id = _draft_ids_from_response(draft)
            if not new_draft_id:
                summary["errors"] += 1
                print(f"ERROR | {lead_name} | Gmail Draft ID: {draft_id} | Gmail did not return a new draft id")
                continue

            updates = draft_flow.build_email_1_sequence_updates(
                schema,
                lead,
                sequence,
                draft_id=new_draft_id,
                thread_id=new_thread_id,
            )
            if updates:
                draft_flow.update_notion_lead(lead["id"], updates)
                summary["notion_updated"] += 1

            summary["drafts_created"] += 1
            print(
                f"CREATED | {lead_name} | old draft {draft_id} | new draft {new_draft_id} | "
                f"thread {new_thread_id or '<none>'} | label {ANVIS_LEADS_LABEL}"
            )
        except Exception as exc:
            summary["errors"] += 1
            print(f"ERROR | {lead_name} | Gmail Draft ID: {draft_id} | {exc}")

    print("Reconcile summary:")
    for key, value in summary.items():
        print(f"- {key}: {value}")
    print("Skip reasons:")
    for reason, count in sorted(skip_reasons.items(), key=lambda item: (-item[1], item[0])):
        print(f"- {reason}: {count}")


if __name__ == "__main__":
    main()
