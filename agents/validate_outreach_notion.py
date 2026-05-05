from __future__ import annotations

import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from collections import defaultdict
from typing import Any, Dict, Iterable, Optional

from notion_client import Client

from src.config import settings
from src.lead_pipeline import DRAFT_READY_STATUSES, status_matches
from src.notion_client import get_database_and_data_source, get_data_source_schema


REQUIRED_FOR_DRAFT = (
    "Business Name",
    "Website",
    "Email",
    "Top Issue",
    "Outreach Angle",
    "Angle Bucket",
)
DUPLICATE_KEYS = ("Domain", "Email", "Phone")
TEST_CLIENT_FIELDS = ("Test Client", "Is Test Client", "Client Type")
GMAIL_DRAFT_FIELDS = ("Gmail Draft ID",)


def get_client() -> Client:
    if not settings.notion_api_key:
        raise ValueError("NOTION_API_KEY is missing.")
    return Client(auth=settings.notion_api_key)


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
    if prop.get("number") is not None:
        return str(prop["number"]).strip()
    if prop.get("checkbox") is not None:
        return "true" if prop["checkbox"] else "false"
    return ""


def _title_property(schema_properties: Dict[str, Any]) -> str:
    for name, prop in schema_properties.items():
        if prop.get("type") == "title":
            return name
    raise ValueError("No title property found in Notion data source.")


def _field_value(page: Dict[str, Any], field: str, title_property: str) -> str:
    properties = page.get("properties", {})
    if field == "Business Name":
        return _text(properties.get("Business Name", {})) or _text(properties.get(title_property, {}))
    return _text(properties.get(field, {}))


def _score(page: Dict[str, Any]) -> int:
    raw = _text(page.get("properties", {}).get("Lead Quality Score", {}))
    try:
        return int(float(raw))
    except ValueError:
        return 0


def _load_pages(data_source_id: str) -> list[Dict[str, Any]]:
    client = get_client()
    pages: list[Dict[str, Any]] = []
    next_cursor: Optional[str] = None
    while True:
        kwargs: Dict[str, Any] = {"data_source_id": data_source_id, "page_size": 100}
        if next_cursor:
            kwargs["start_cursor"] = next_cursor
        response = client.data_sources.query(**kwargs)
        pages.extend(response.get("results", []))
        if not response.get("has_more"):
            break
        next_cursor = response.get("next_cursor")
        if not next_cursor:
            break
    return pages


def _duplicate_values(pages: Iterable[Dict[str, Any]], field: str) -> Dict[str, list[str]]:
    values: Dict[str, list[str]] = defaultdict(list)
    for page in pages:
        value = _text(page.get("properties", {}).get(field, {})).lower()
        if value:
            values[value].append(page["id"])
    return {value: ids for value, ids in values.items() if len(ids) > 1}


def _is_truthy(value: str) -> bool:
    return value.strip().lower() in {"true", "yes", "y", "1", "test", "test client"}


def _queue_bucket(status: str, reply_status: str, has_checkout_started: bool, is_paid_client: bool, is_test_client: bool) -> str:
    normalized = " ".join(status.strip().lower().replace("-", " ").split())
    if is_test_client:
        return "test_clients"
    if is_paid_client or normalized == "paid client":
        return "paid_clients"
    if has_checkout_started or normalized in {"checkout sent", "checkout_started"}:
        return "checkout_started"
    if reply_status.strip().lower() == "replied" or normalized == "replied":
        return "replies_needing_action"
    if normalized in {"audit ready", "outreach drafted"}:
        return "audit_ready_leads"
    if normalized in {"new", "new lead", "researching"}:
        return "new_leads"
    return "other"


def main() -> None:
    _, data_source_id = get_database_and_data_source()
    schema = get_data_source_schema()
    schema_properties = schema.get("properties", {})
    title_property = _title_property(schema_properties)
    pages = _load_pages(data_source_id)

    print("Notion Validation Summary")
    print(f"Total records checked: {len(pages)}")

    missing_schema_fields = [field for field in REQUIRED_FOR_DRAFT if field not in schema_properties and field != "Business Name"]
    if "Business Name" not in schema_properties and title_property not in schema_properties:
        missing_schema_fields.append("Business Name")
    if missing_schema_fields:
        print(f"Missing schema fields: {', '.join(missing_schema_fields)}")

    draft_ready_count = 0
    valid_draft_ready_count = 0
    skipped_count = 0
    queue_counts: Dict[str, int] = defaultdict(int)
    for page in pages:
        properties = page.get("properties", {})
        status = _text(properties.get("Lead Status", {}) or properties.get("Outreach Status", {}))
        reply_status = _text(properties.get("Reply Status", {}))
        checkout_started = _text(properties.get("Checkout Status", {}))
        paid_client = _text(properties.get("Client Status", {}))
        gmail_draft_id = any(_text(properties.get(field, {})) for field in GMAIL_DRAFT_FIELDS)
        sequence_step = _text(properties.get("Sequence Step", {}))
        test_client = any(_is_truthy(_text(properties.get(field, {}))) for field in TEST_CLIENT_FIELDS)
        bucket = _queue_bucket(status, reply_status, bool(checkout_started), bool(paid_client), test_client)
        queue_counts[bucket] += 1
        if gmail_draft_id or sequence_step in {"Email 1 Drafted", "Email 2 Drafted", "Email 3 Drafted"}:
            queue_counts["drafted_emails"] += 1
        if status_matches(status, *DRAFT_READY_STATUSES):
            queue_counts["audit_ready_leads"] += 1
        if not status_matches(status, *DRAFT_READY_STATUSES):
            continue
        draft_ready_count += 1
        name = _field_value(page, "Business Name", title_property) or page["id"]
        missing = [field for field in REQUIRED_FOR_DRAFT if not _field_value(page, field, title_property)]
        if _score(page) < 3:
            missing.append("Lead Quality Score >= 3")
        if missing:
            skipped_count += 1
            print(f"SKIP | {name} | missing/invalid: {', '.join(missing)}")
            continue
        valid_draft_ready_count += 1

    print(f"Draft-ready records: {draft_ready_count}")
    print(f"Valid draft-ready records: {valid_draft_ready_count}")
    print(f"Records skipped by validation: {skipped_count}")
    print(f"Admin queue | new leads: {queue_counts['new_leads']}")
    print(f"Admin queue | audit-ready leads: {queue_counts['audit_ready_leads']}")
    print(f"Admin queue | drafted emails: {queue_counts['drafted_emails']}")
    print(f"Admin queue | replies needing action: {queue_counts['replies_needing_action']}")
    print(f"Admin queue | checkout-started leads: {queue_counts['checkout_started']}")
    print(f"Admin queue | paid clients: {queue_counts['paid_clients']}")
    print(f"Admin queue | test clients: {queue_counts['test_clients']}")

    duplicate_count = 0
    for field in DUPLICATE_KEYS:
        duplicates = _duplicate_values(pages, field)
        duplicate_count += len(duplicates)
        for value, ids in list(duplicates.items())[:10]:
            print(f"DUPLICATE | {field}={value} | records={len(ids)}")
    print(f"Duplicate key groups found: {duplicate_count}")


if __name__ == "__main__":
    main()
