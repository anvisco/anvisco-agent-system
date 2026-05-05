from __future__ import annotations

import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from collections import defaultdict
from typing import Any, Dict, Iterable, Optional

from notion_client import Client

from src.config import settings
from src.notion_client import get_database_and_data_source, get_data_source_schema


REQUIRED_FOR_DRAFT = (
    "Business Name",
    "Website",
    "Email",
    "Top 3 Issues",
    "Email Angle",
    "Angle Bucket",
)
DUPLICATE_KEYS = ("Domain", "Email", "Phone")
LEAD_STATUS_CANDIDATES = ("Lead Status", "Outreach Status")
AUDIT_STATUS_CANDIDATES = ("Audit Status",)


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


def _first_existing(properties: Dict[str, Any], candidates: tuple[str, ...]) -> Optional[str]:
    for candidate in candidates:
        if candidate in properties:
            return candidate
    return None


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

    new_lead_count = 0
    valid_new_lead_count = 0
    skipped_count = 0
    for page in pages:
        properties = page.get("properties", {})
        lead_status_field = _first_existing(properties, LEAD_STATUS_CANDIDATES)
        audit_status_field = _first_existing(properties, AUDIT_STATUS_CANDIDATES)
        lead_status = _text(properties.get(lead_status_field or "", {})).lower()
        audit_status = _text(properties.get(audit_status_field or "", {})).lower()
        if lead_status not in {"audit_ready", "draft_ready", "new lead", "draft ready"} and audit_status != "complete":
            continue
        new_lead_count += 1
        name = _field_value(page, "Business Name", title_property) or page["id"]
        missing = [field for field in REQUIRED_FOR_DRAFT if not _field_value(page, field, title_property)]
        if _score(page) < 3:
            missing.append("Lead Quality Score >= 3")
        if missing:
            skipped_count += 1
            print(f"SKIP | {name} | missing/invalid: {', '.join(missing)}")
            continue
        valid_new_lead_count += 1

    print(f"New Lead records: {new_lead_count}")
    print(f"Valid New Lead records: {valid_new_lead_count}")
    print(f"Records skipped by validation: {skipped_count}")

    duplicate_count = 0
    for field in DUPLICATE_KEYS:
        duplicates = _duplicate_values(pages, field)
        duplicate_count += len(duplicates)
        for value, ids in list(duplicates.items())[:10]:
            print(f"DUPLICATE | {field}={value} | records={len(ids)}")
    print(f"Duplicate key groups found: {duplicate_count}")


if __name__ == "__main__":
    main()
