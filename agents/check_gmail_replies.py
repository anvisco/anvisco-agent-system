from __future__ import annotations

import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from datetime import date, timedelta
from email.utils import parseaddr
from typing import Any, Dict, Optional

from notion_client import Client

from src.config import settings
from src.gmail_client import get_profile_email, get_thread, search_messages
from src.notion_client import get_database_and_data_source, get_data_source_schema


ACTIVE_SENT_STATUSES = {"Email 1 Sent", "Email 2 Sent"}
STOP_STATUSES = {"Replied", "Closed", "Call Booked", "Not Interested", "Do Not Contact"}
NAME_CANDIDATES = ("Business Name", "Practice Name", "Clinic Name", "Name")
EMAIL_CANDIDATES = ("Email", "Contact Email")
OUTREACH_STATUS_CANDIDATES = ("Outreach Status",)
REPLY_STATUS_CANDIDATES = ("Reply Status",)
GMAIL_THREAD_ID_CANDIDATES = ("Gmail Thread ID",)
LAST_OUTREACH_DATE_CANDIDATES = ("Last Email Sent At", "Last Outreach Date", "Email 1 Date")
SEQUENCE_STEP_CANDIDATES = ("Sequence Step",)
SCRAPE_NOTES_CANDIDATES = ("Scrape Notes",)


def get_client() -> Client:
    if not settings.notion_api_key:
        raise ValueError("NOTION_API_KEY is missing.")
    return Client(auth=settings.notion_api_key)


def _first_existing(properties: Dict[str, Any], candidates: tuple[str, ...]) -> Optional[str]:
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
    return ""


def _date_value(prop: Dict[str, Any]) -> Optional[date]:
    raw = _text(prop)
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _property_update(prop_type: str, value: str) -> Optional[Dict[str, Any]]:
    if prop_type == "select":
        return {"select": {"name": value}}
    if prop_type == "status":
        return {"status": {"name": value}}
    if prop_type == "rich_text":
        return {"rich_text": [{"type": "text", "text": {"content": value}}]}
    return None


def _add_update(updates: Dict[str, Any], schema_properties: Dict[str, Any], candidates: tuple[str, ...], value: str) -> None:
    property_name = _first_existing(schema_properties, candidates)
    if not property_name:
        return
    update = _property_update(schema_properties[property_name].get("type"), value)
    if update:
        updates[property_name] = update


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


def _lead_name(page: Dict[str, Any]) -> str:
    properties = page.get("properties", {})
    field = _first_existing(properties, NAME_CANDIDATES)
    return _text(properties.get(field or "", {})) or page.get("id", "<unknown>")


def _email_from_header(header_value: str) -> str:
    return parseaddr(header_value)[1].lower()


def _header(message: Dict[str, Any], name: str) -> str:
    headers = message.get("payload", {}).get("headers", [])
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


def _thread_has_reply_from_lead(thread_id: str, lead_email: str, my_email: str) -> bool:
    if not thread_id:
        return False
    thread = get_thread(thread_id)
    for message in thread.get("messages", []):
        from_email = _email_from_header(_header(message, "From"))
        if from_email and from_email == lead_email.lower() and from_email != my_email.lower():
            return True
    return False


def _search_has_reply_from_lead(lead_email: str, last_outreach: Optional[date]) -> bool:
    if last_outreach:
        query = f"from:{lead_email} after:{last_outreach.strftime('%Y/%m/%d')} -in:spam -in:trash"
    else:
        query = f"from:{lead_email} newer_than:30d -in:spam -in:trash"
    return bool(search_messages(query, max_results=5))


def _build_reply_updates(schema_properties: Dict[str, Any]) -> Dict[str, Any]:
    updates: Dict[str, Any] = {}
    _add_update(updates, schema_properties, REPLY_STATUS_CANDIDATES, "Replied")
    _add_update(updates, schema_properties, OUTREACH_STATUS_CANDIDATES, "Replied")
    _add_update(updates, schema_properties, SEQUENCE_STEP_CANDIDATES, "Replied")
    return updates


def main() -> None:
    _, data_source_id = get_database_and_data_source()
    schema = get_data_source_schema()
    schema_properties = schema.get("properties", {})
    pages = _load_pages(data_source_id)
    my_email = get_profile_email()

    summary = {
        "records_checked": 0,
        "replies_found": 0,
        "records_updated": 0,
        "skipped": 0,
        "errors": 0,
    }

    for page in pages:
        try:
            properties = page.get("properties", {})
            status_field = _first_existing(properties, OUTREACH_STATUS_CANDIDATES)
            reply_field = _first_existing(properties, REPLY_STATUS_CANDIDATES)
            email_field = _first_existing(properties, EMAIL_CANDIDATES)
            thread_field = _first_existing(properties, GMAIL_THREAD_ID_CANDIDATES)
            last_outreach_field = _first_existing(properties, LAST_OUTREACH_DATE_CANDIDATES)

            outreach_status = _text(properties.get(status_field or "", {}))
            reply_status = _text(properties.get(reply_field or "", {}))
            if outreach_status in STOP_STATUSES or reply_status == "Replied":
                summary["skipped"] += 1
                continue
            if outreach_status not in ACTIVE_SENT_STATUSES:
                summary["skipped"] += 1
                continue

            summary["records_checked"] += 1
            lead_email = _text(properties.get(email_field or "", {})).lower()
            if not lead_email:
                print(f"Skipped {_lead_name(page)}: missing email")
                summary["skipped"] += 1
                continue

            thread_id = _text(properties.get(thread_field or "", {}))
            last_outreach = _date_value(properties.get(last_outreach_field or "", {}))
            replied = _thread_has_reply_from_lead(thread_id, lead_email, my_email) or _search_has_reply_from_lead(
                lead_email,
                last_outreach,
            )
            if not replied:
                continue

            summary["replies_found"] += 1
            if settings.dry_run:
                print(f"DRY RUN: would mark replied: {_lead_name(page)} ({lead_email})")
                continue

            updates = _build_reply_updates(schema_properties)
            if updates:
                get_client().pages.update(page_id=page["id"], properties=updates)
                summary["records_updated"] += 1
                print(f"Marked replied: {_lead_name(page)} ({lead_email})")
        except Exception as exc:
            summary["errors"] += 1
            print(f"ERROR | {_lead_name(page)} | {exc}")

    print("Gmail Reply Check Summary:")
    for key, value in summary.items():
        print(f"- {key}: {value}")


if __name__ == "__main__":
    main()
