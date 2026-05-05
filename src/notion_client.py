from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from notion_client import Client

from src.config import settings


TEST_LEAD = {
    "Practice Name": "TEST Dental Clinic",
    "Website": "https://example.com",
    "Email": "test@example.com",
    "Lead Status": "audit_ready",
    "Outreach Status": "draft_ready",
    "Source": "Codex Notion Test",
}


def get_client() -> Client:
    if not settings.notion_api_key:
        raise ValueError("NOTION_API_KEY is missing.")
    return Client(auth=settings.notion_api_key)


def get_database_and_data_source() -> Tuple[Dict[str, Any], str]:
    client = get_client()
    database = client.databases.retrieve(database_id=settings.notion_database_id)
    data_sources = database.get("data_sources", [])
    if not data_sources:
        raise ValueError("Could not find any data sources in the Notion database.")
    data_source_id = data_sources[0]["id"]
    return database, data_source_id


def get_data_source_schema() -> Dict[str, Any]:
    client = get_client()
    database, data_source_id = get_database_and_data_source()
    data_source = client.data_sources.retrieve(data_source_id=data_source_id)
    data_source = dict(data_source)
    if "title" not in data_source and database.get("title"):
        data_source["title"] = database.get("title", [])
    return data_source


def get_title_property_name(schema: Optional[Dict[str, Any]] = None) -> str:
    schema = schema or get_data_source_schema()
    properties = schema.get("properties", schema)

    title_property = None
    for name, prop in properties.items():
        if prop["type"] == "title":
            title_property = name

    if title_property is None:
        print(schema)
        raise ValueError("Could not find a title property in the Notion database schema.")

    return title_property


def query_database_by_practice_name(practice_name: str) -> List[Dict[str, Any]]:
    client = get_client()
    schema = get_data_source_schema()
    title_property_name = get_title_property_name(schema)
    _, data_source_id = get_database_and_data_source()
    response = client.data_sources.query(
        data_source_id=data_source_id,
        filter={
            "property": title_property_name,
            "title": {"equals": practice_name},
        },
    )
    return list(response.get("results", []))


def _title_rich_text(text: str) -> List[Dict[str, Any]]:
    return [{"type": "text", "text": {"content": text}}]


def _property_value(property_name: str, property_type: str, value: str) -> Optional[Dict[str, Any]]:
    if property_type == "title":
        return {"title": _title_rich_text(value)}
    if property_type == "rich_text":
        return {"rich_text": _title_rich_text(value)}
    if property_type == "url":
        return {"url": value}
    if property_type == "email":
        return {"email": value}
    if property_type == "select":
        return {"select": {"name": value}}
    return None


def build_properties(lead: Dict[str, str]) -> Tuple[Dict[str, Any], List[str]]:
    schema = get_data_source_schema()
    title_property_name = get_title_property_name(schema)
    schema_properties = schema.get("properties", schema)
    properties: Dict[str, Any] = {}
    skipped: List[str] = []
    for key, value in lead.items():
        property_name = title_property_name if key == "Practice Name" else key
        property_info = schema_properties.get(property_name)
        if not property_info:
            skipped.append(key)
            continue
        notion_value = _property_value(property_name, property_info["type"], value)
        if notion_value is None:
            skipped.append(key)
            continue
        properties[property_name] = notion_value
    return properties, skipped


def create_test_lead() -> Optional[Dict[str, Any]]:
    client = get_client()
    schema = get_data_source_schema()
    title_property_name = get_title_property_name(schema)
    print(f"Detected title property: {title_property_name}")
    existing = query_database_by_practice_name(TEST_LEAD["Practice Name"])
    properties, skipped = build_properties(TEST_LEAD)

    if settings.dry_run:
        action = "update" if existing else "create"
        print(f"DRY RUN: would {action} lead: {TEST_LEAD['Practice Name']}")
        if skipped:
            print(f"DRY RUN: skipped unsupported or missing properties: {', '.join(skipped)}")
        return None

    if existing:
        page_id = existing[0]["id"]
        print(f"Updating existing lead: {TEST_LEAD['Practice Name']}")
        return client.pages.update(page_id=page_id, properties=properties)

    print(f"Creating new lead: {TEST_LEAD['Practice Name']}")
    return client.pages.create(
        parent={"data_source_id": get_database_and_data_source()[1]},
        properties=properties,
    )


def update_test_lead() -> Optional[Dict[str, Any]]:
    schema = get_data_source_schema()
    title_property_name = get_title_property_name(schema)
    print(f"Detected title property: {title_property_name}")
    existing = query_database_by_practice_name(TEST_LEAD["Practice Name"])
    if not existing:
        print(f"No existing lead found for: {TEST_LEAD['Practice Name']}")
        return None

    client = get_client()
    page_id = existing[0]["id"]
    schema = get_data_source_schema()
    source_properties = schema.get("properties", schema)
    source_type = source_properties.get("Source", {}).get("type")
    source_value = _property_value("Source", source_type, "Codex Notion Test")
    if source_value is None:
        raise ValueError("Source property must be select, rich_text, or title.")
    properties = {"Source": source_value}

    if settings.dry_run:
        print(f"DRY RUN: would update lead: {TEST_LEAD['Practice Name']}")
        return None

    print(f"Updating lead: {TEST_LEAD['Practice Name']}")
    return client.pages.update(page_id=page_id, properties=properties)
