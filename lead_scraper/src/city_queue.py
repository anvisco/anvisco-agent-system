from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, List, Optional

from src.config import settings
from src.notion_client import get_client, get_database_and_data_source_by_id


CANADA_CITY_QUEUE_TITLE = "Canada City Queue"
CITY_STATUS_CANDIDATES = ("City Status",)
CITY_NAME_CANDIDATES = ("City", "Name")
PROVINCE_CANDIDATES = ("Province",)
COUNTRY_CANDIDATES = ("Country",)
ACTIVE_CITY_STATUSES = {"active"}


@dataclass(frozen=True)
class CityQueueContext:
    source: str
    city: str
    province: str
    country: str
    accessible: bool
    warning: str
    rows: List[Dict[str, Any]]
    active_rows: List[Dict[str, Any]]


def _first_existing_property(properties: Dict[str, Any], candidates: tuple[str, ...]) -> str:
    for candidate in candidates:
        if candidate in properties:
            return candidate
    return ""


def _property_text(property_value: Dict[str, Any]) -> str:
    if not property_value:
        return ""
    if property_value.get("title"):
        return "".join(item.get("plain_text", "") for item in property_value["title"]).strip()
    if property_value.get("rich_text"):
        return "".join(item.get("plain_text", "") for item in property_value["rich_text"]).strip()
    if property_value.get("select"):
        return str(property_value["select"].get("name", "")).strip()
    if property_value.get("status"):
        return str(property_value["status"].get("name", "")).strip()
    if property_value.get("date"):
        return str(property_value["date"].get("start", "")).strip()
    if property_value.get("number") is not None:
        return str(property_value["number"]).strip()
    return ""


def _row_text(row: Dict[str, Any], candidates: tuple[str, ...]) -> str:
    properties = row.get("properties", {})
    property_name = _first_existing_property(properties, candidates)
    if not property_name:
        return ""
    return _property_text(properties.get(property_name, {}))


def _row_details(row: Dict[str, Any]) -> Dict[str, str]:
    return {
        "city": _row_text(row, CITY_NAME_CANDIDATES),
        "province": _row_text(row, PROVINCE_CANDIDATES),
        "country": _row_text(row, COUNTRY_CANDIDATES),
        "status": _row_text(row, CITY_STATUS_CANDIDATES),
    }


def _data_source_rows(client, data_source_id: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    next_cursor: Optional[str] = None
    while True:
        kwargs: Dict[str, Any] = {"data_source_id": data_source_id, "page_size": 100}
        if next_cursor:
            kwargs["start_cursor"] = next_cursor
        response = client.data_sources.query(**kwargs)
        rows.extend(response.get("results", []))
        if not response.get("has_more"):
            break
        next_cursor = response.get("next_cursor")
        if not next_cursor:
            break
    return rows


def _queue_database_id() -> str:
    return settings.canada_city_queue_database_id or settings.city_queue_database_id


def _fallback_city() -> str:
    return os.getenv("ACTIVE_CITY", "").strip()


def _fallback_province() -> str:
    return os.getenv("ACTIVE_PROVINCE", "").strip()


def _fallback_country() -> str:
    return settings.country_scope.strip() or "Canada"


def _environment_fallback_enabled() -> bool:
    return bool(settings.allow_env_city_fallback)


def _environment_fallback_context(warning: str) -> CityQueueContext:
    city = _fallback_city()
    province = _fallback_province()
    if not city or not province:
        raise ValueError(
            warning
            + " Set ACTIVE_CITY and ACTIVE_PROVINCE, or share the City Queue database with the integration."
        )
    return CityQueueContext(
        source="ENV fallback",
        city=city,
        province=province,
        country=_fallback_country(),
        accessible=False,
        warning=warning,
        rows=[],
        active_rows=[],
    )


@lru_cache(maxsize=1)
def resolve_canada_city_queue_context() -> CityQueueContext:
    client = get_client()
    warning = "Canada City Queue not accessible. Share the database with the integration or set ALLOW_ENV_CITY_FALLBACK=true."

    try:
        queue_database_id = _queue_database_id()
        if queue_database_id:
            # The env var may hold a data_source ID (new API) or a classic database ID.
            # Try direct data_source query first; fall back to the database → data_sources path.
            data_source_id = ""
            try:
                client.data_sources.retrieve(data_source_id=queue_database_id)
                data_source_id = queue_database_id
            except Exception:
                pass
            if not data_source_id:
                _, data_source_id = get_database_and_data_source_by_id(queue_database_id)
        else:
            search = getattr(client, "search", None)
            if search is None:
                if _environment_fallback_enabled():
                    return _environment_fallback_context(warning)
                raise ValueError(warning)

            # "database" filter is not valid in this API version; use "data_source".
            data_source_id = ""
            try:
                response = search(query=CANADA_CITY_QUEUE_TITLE, filter={"property": "object", "value": "data_source"})
                for result in response.get("results", []):
                    title_parts = result.get("title", [])
                    title_text = "".join(part.get("plain_text", "") for part in title_parts).strip()
                    if title_text.lower() == CANADA_CITY_QUEUE_TITLE.lower():
                        data_source_id = result.get("id", "")
                        break
            except Exception:
                pass
            if not data_source_id:
                if _environment_fallback_enabled():
                    return _environment_fallback_context(warning)
                raise ValueError(warning)

        rows = _data_source_rows(client, data_source_id)
        active_rows = [
            row
            for row in rows
            if _row_details(row).get("status", "").strip().lower() in ACTIVE_CITY_STATUSES
        ]

        if len(active_rows) == 1:
            details = _row_details(active_rows[0])
            return CityQueueContext(
                source="Notion City Queue",
                city=details.get("city") or "",
                province=details.get("province") or "",
                country=details.get("country") or _fallback_country(),
                accessible=True,
                warning="",
                rows=rows,
                active_rows=active_rows,
            )

        if len(active_rows) > 1:
            warning = (
                "Canada City Queue has multiple active rows. "
                "Resolve the queue so exactly one City Status = active row remains."
            )
        else:
            warning = "Canada City Queue has no active rows. Resolve the queue before scraping."

        if _environment_fallback_enabled():
            return _environment_fallback_context(warning)
        raise ValueError(warning + " Set ALLOW_ENV_CITY_FALLBACK=true to use the ENV fallback.")
    except ValueError:
        raise
    except Exception as exc:
        if _environment_fallback_enabled():
            return _environment_fallback_context(
                f"Canada City Queue lookup failed: {exc}. Set ALLOW_ENV_CITY_FALLBACK=true to use the ENV fallback."
            )
        raise ValueError(
            "Canada City Queue not accessible. Share the database with the integration or set "
            "ALLOW_ENV_CITY_FALLBACK=true."
        ) from exc
