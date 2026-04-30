"""Run with:
python -m agents.debug_notion_schema
"""

from __future__ import annotations

import json
from typing import Any, Dict

from notion_client import Client

from src.config import settings


def get_client() -> Client:
    if not settings.notion_api_key:
        raise ValueError("NOTION_API_KEY is missing.")
    if not settings.notion_database_id:
        raise ValueError("NOTION_DATABASE_ID is missing.")
    return Client(auth=settings.notion_api_key)


def print_schema() -> None:
    client = get_client()
    database: Dict[str, Any] = client.databases.retrieve(
        database_id=settings.notion_database_id,
    )
    data_sources = database.get("data_sources", [])
    if not data_sources:
        raise ValueError("Could not find any data sources in the Notion database.")
    data_source_id = data_sources[0]["id"]
    data_source = client.data_sources.retrieve(data_source_id=data_source_id)

    title = database.get("title", [])
    database_title = "".join(item.get("plain_text", "") for item in title)
    if not database_title:
        database_title = "<untitled>"

    print(f"Database title: {database_title}")
    print(f"Database ID: {settings.notion_database_id}")
    print(f"Data Source ID: {data_source_id}")

    properties = data_source.get("properties", {})
    title_property = None

    for name, prop in properties.items():
        print(f"{name}: {prop['type']}")
        if prop["type"] == "title":
            title_property = name

    if title_property is None:
        print(json.dumps(data_source, indent=2, sort_keys=True))
        raise ValueError("Could not find a title property in the Notion database schema.")

    print(f"Detected title property: {title_property}")


def main() -> None:
    print_schema()


if __name__ == "__main__":
    main()
