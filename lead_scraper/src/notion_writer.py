from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from notion_client import Client

from .config import settings
from .models import AuditedLead
from src.lead_pipeline import DRAFT_READY_STATUSES, STOPPED_STATUSES
from .utils import append_note, clean_phone, is_probably_better_text, normalize_domain, now_iso_date


CONTACTED_OR_CLOSED = {
    *STOPPED_STATUSES,
    "Email 1 Sent",
    "Email 2 Sent",
    "Replied",
    "Call Booked",
    "No Response",
    "Not Interested",
    "Do Not Contact",
    "Closed",
}
EARLY_STAGE = {
    *DRAFT_READY_STATUSES,
    "New Lead",
    "Draft Ready",
    "new",
    "researching",
}
SOURCE_GOOGLE_PLACES_NEW = "Google Places New"


FIELD_MAP = {
    "Google Place ID": "google_place_id",
    "Business Name": "business_name",
    "Contact Name": "contact_name",
    "Niche": "niche",
    "Industry": "industry",
    "City": "city",
    "Location": "location",
    "Website": "website",
    "Website URL": "website_url",
    "Domain": "domain",
    "Email": "email",
    "Phone": "phone",
    "Address": "address",
    "Google Maps URL": "google_maps_url",
    "Rating": "rating",
    "Review Count": "review_count",
    "Top Issue": "top_issue",
    "Top 3 Issues": "top_3_issues",
    "Business Impact": "business_impact",
    "Recommended Fix": "recommended_fix",
    "Outreach Angle": "outreach_angle",
    "Email Angle": "email_angle",
    "Angle Bucket": "angle_bucket",
    "Recommended Offer": "recommended_offer",
    "Loom Script": "loom_script",
    "Lead Quality Score": "lead_quality_score",
    "Website Status": "website_status",
    "Source": "source",
    "Lead Source": "lead_source",
    "Lead Status": "lead_status",
    "Audit Status": "audit_status",
    "Last Scraped Date": None,
    "Scrape Notes": "scrape_notes",
    "Notes": "notes",
    "Created At": "created_at",
    "Updated At": "updated_at",
    "Outreach Status": "lead_status",
    "Contact Page URL": "contact_page_url",
    "Booking URL": "booking_url",
    "Languages": "languages",
    "Services": "services",
    "Intent Level": "intent_level",
}


def get_client() -> Client:
    if not settings.notion_api_key:
        raise ValueError("NOTION_API_KEY is missing.")
    return Client(auth=settings.notion_api_key)


def get_data_source() -> tuple[Dict[str, Any], str]:
    client = get_client()
    database = client.databases.retrieve(database_id=settings.notion_database_id)
    data_sources = database.get("data_sources", [])
    if not data_sources:
        raise ValueError("Could not find any data sources in the Notion database.")
    data_source_id = data_sources[0]["id"]
    return client.data_sources.retrieve(data_source_id=data_source_id), data_source_id


def _plain_text(value: Dict[str, Any]) -> str:
    if not value:
        return ""
    if value.get("title"):
        return "".join(item.get("plain_text", "") for item in value["title"])
    if value.get("rich_text"):
        return "".join(item.get("plain_text", "") for item in value["rich_text"])
    if value.get("url"):
        return value["url"]
    if value.get("email"):
        return value["email"]
    if value.get("phone_number"):
        return value["phone_number"]
    if value.get("select"):
        return value["select"].get("name", "")
    if value.get("status"):
        return value["status"].get("name", "")
    if value.get("number") is not None:
        return str(value["number"])
    if value.get("date"):
        return value["date"].get("start", "")
    return ""


def _property_value(prop_type: str, value: Any) -> Optional[Dict[str, Any]]:
    if value is None or value == "":
        return None
    if isinstance(value, (list, tuple)):
        value = "\n".join(f"- {item}" for item in value if str(item).strip())
        if not value:
            return None
    if prop_type == "title":
        return {"title": [{"type": "text", "text": {"content": str(value)}}]}
    if prop_type == "rich_text":
        return {"rich_text": [{"type": "text", "text": {"content": str(value)}}]}
    if prop_type == "url":
        return {"url": str(value)}
    if prop_type == "email":
        return {"email": str(value)}
    if prop_type == "phone_number":
        return {"phone_number": str(value)}
    if prop_type == "number":
        return {"number": value}
    if prop_type == "select":
        return {"select": {"name": str(value)}}
    if prop_type == "status":
        return {"status": {"name": str(value)}}
    if prop_type == "date":
        return {"date": {"start": str(value)}}
    return None


def _title_property(properties: Dict[str, Any]) -> str:
    for name, prop in properties.items():
        if prop.get("type") == "title":
            return name
    raise ValueError("Could not find a Notion title property.")


def load_existing_leads() -> tuple[list[Dict[str, Any]], Dict[str, Any], str]:
    data_source, data_source_id = get_data_source()
    client = get_client()
    leads: list[Dict[str, Any]] = []
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
    return leads, data_source, data_source_id


def ensure_source_option(schema_properties: Dict[str, Any], data_source_id: str) -> None:
    source_property = schema_properties.get("Source", {})
    if source_property.get("type") != "select":
        return
    existing_options = source_property.get("select", {}).get("options", [])
    if any(option.get("name") == SOURCE_GOOGLE_PLACES_NEW for option in existing_options):
        return

    updated_options = [
        {"name": option.get("name", ""), "color": option.get("color", "default")}
        for option in existing_options
        if option.get("name")
    ]
    updated_options.append({"name": SOURCE_GOOGLE_PLACES_NEW, "color": "default"})
    get_client().data_sources.update(
        data_source_id=data_source_id,
        properties={
            "Source": {
                "select": {
                    "options": updated_options,
                }
            }
        },
    )


def _lead_key_values(page: Dict[str, Any]) -> Dict[str, str]:
    props = page.get("properties", {})
    return {
        "google_place_id": _plain_text(props.get("Google Place ID", {})),
        "domain": normalize_domain(_plain_text(props.get("Domain", {})) or _plain_text(props.get("Website", {}))),
        "phone": clean_phone(_plain_text(props.get("Phone", {}))),
        "name_address": f"{_plain_text(props.get('Business Name', {})).lower()}|{_plain_text(props.get('Address', {})).lower()}",
        "status": _plain_text(props.get("Outreach Status", {})),
        "last_scraped": _plain_text(props.get("Last Scraped Date", {})),
        "score": _plain_text(props.get("Lead Quality Score", {})),
    }


def find_duplicate(audited: AuditedLead, existing_pages: list[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return find_duplicate_by_keys(
        google_place_id=audited.google_place_id,
        domain=audited.domain,
        phone=audited.phone,
        business_name=audited.business_name,
        address=audited.address,
        existing_pages=existing_pages,
    )


def find_duplicate_by_keys(
    google_place_id: str,
    domain: str,
    phone: str,
    business_name: str,
    address: str,
    existing_pages: list[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    target_google_place_id = google_place_id.strip()
    target_domain = normalize_domain(domain)
    target_phone = clean_phone(phone)
    target_name_address = f"{business_name.lower()}|{address.lower()}"
    for key in ("google_place_id", "domain", "phone", "name_address"):
        for page in existing_pages:
            values = _lead_key_values(page)
            if key == "google_place_id" and target_google_place_id and values[key] == target_google_place_id:
                return page
            if key == "domain" and target_domain and values[key] == target_domain:
                return page
            if key == "phone" and target_phone and values[key] == target_phone:
                return page
            if key == "name_address" and target_name_address.strip("|") and values[key] == target_name_address:
                return page
    return None


def should_skip_recent_good_record(page: Dict[str, Any]) -> bool:
    values = _lead_key_values(page)
    last_scraped = values.get("last_scraped")
    if not last_scraped:
        return False
    try:
        scraped_date = date.fromisoformat(last_scraped[:10])
    except ValueError:
        return False
    has_good_data = bool(
        _plain_text(page["properties"].get("Email", {}))
        and _plain_text(page["properties"].get("Top Issue", {}))
        and _plain_text(page["properties"].get("Outreach Angle", {}))
    )
    return has_good_data and scraped_date >= date.today() - timedelta(days=30)


def _build_create_properties(audited: AuditedLead, schema_properties: Dict[str, Any]) -> Dict[str, Any]:
    props: Dict[str, Any] = {}
    title_property = _title_property(schema_properties)
    now_iso = datetime.now(timezone.utc).isoformat()
    for notion_field, attr in FIELD_MAP.items():
        if notion_field not in schema_properties and notion_field != "Business Name":
            continue
        value = getattr(audited, attr) if attr else None
        if notion_field == "Business Name":
            value = audited.business_name
        elif notion_field == "Created At":
            value = audited.created_at or now_iso
        elif notion_field == "Updated At":
            value = audited.updated_at or now_iso
        elif notion_field == "Last Scraped Date":
            value = now_iso_date()
        property_name = title_property if notion_field == "Business Name" and title_property != notion_field else notion_field
        prop_info = schema_properties.get(property_name)
        if not prop_info:
            continue
        notion_value = _property_value(prop_info["type"], value)
        if notion_value:
            props[property_name] = notion_value
    if title_property not in props:
        props[title_property] = _property_value(schema_properties[title_property]["type"], audited.business_name) or {}
    return props


def _build_update_properties(page: Dict[str, Any], audited: AuditedLead, schema_properties: Dict[str, Any]) -> Dict[str, Any]:
    existing_props = page.get("properties", {})
    updates: Dict[str, Any] = {}
    title_property = _title_property(schema_properties)
    now_iso = datetime.now(timezone.utc).isoformat()
    for notion_field, attr in FIELD_MAP.items():
        if notion_field not in schema_properties and notion_field != "Business Name":
            continue
        if notion_field == "Outreach Status":
            continue
        incoming = getattr(audited, attr) if attr else None
        property_name = title_property if notion_field == "Business Name" and title_property != notion_field else notion_field
        if notion_field == "Last Scraped Date":
            incoming = now_iso_date()
        if notion_field == "Updated At":
            incoming = audited.updated_at or now_iso
        if notion_field == "Scrape Notes":
            current = _plain_text(existing_props.get(property_name, {}))
            incoming = append_note(current, audited.scrape_notes)
        current = _plain_text(existing_props.get(property_name, {}))
        if notion_field in {"Top Issue", "Outreach Angle"} and not is_probably_better_text(current, str(incoming or "")):
            continue
        elif notion_field not in {"Top Issue", "Outreach Angle", "Last Scraped Date", "Scrape Notes", "Updated At"} and current:
            continue
        notion_value = _property_value(schema_properties[property_name]["type"], incoming)
        if notion_value:
            updates[property_name] = notion_value
    return updates


def write_new_lead(audited: AuditedLead, schema_properties: Dict[str, Any], data_source_id: str) -> str:
    client = get_client()
    props = _build_create_properties(audited, schema_properties)
    page = client.pages.create(parent={"data_source_id": data_source_id}, properties=props)
    return page["id"]


def update_existing_lead(page: Dict[str, Any], audited: AuditedLead, schema_properties: Dict[str, Any]) -> bool:
    updates = _build_update_properties(page, audited, schema_properties)
    if not updates:
        return False
    get_client().pages.update(page_id=page["id"], properties=updates)
    return True
