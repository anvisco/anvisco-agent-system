from __future__ import annotations

from typing import Any, Dict

from .auditor import audit_lead
from .config import settings
from .lead_finder import find_local_leads
from .logger import DailyLogger
from .models import AuditedLead, FoundLead
from .notion_writer import (
    CONTACTED_OR_CLOSED,
    EARLY_STAGE,
    find_duplicate,
    find_duplicate_by_keys,
    ensure_source_option,
    load_existing_leads,
    should_skip_recent_good_record,
    update_existing_lead,
    write_new_lead,
)
from .utils import normalize_domain
from .website_scraper import scrape_website


def _existing_status(page: Dict[str, Any]) -> str:
    status = page.get("properties", {}).get("Outreach Status", {})
    if status.get("select"):
        return status["select"].get("name", "")
    if status.get("status"):
        return status["status"].get("name", "")
    if status.get("rich_text"):
        return "".join(item.get("plain_text", "") for item in status["rich_text"])
    return ""


def _is_valid_for_write(audited: AuditedLead) -> tuple[bool, str]:
    if not audited.business_name:
        return False, "missing business name"
    if not audited.website or not audited.domain:
        return False, "missing website/domain"
    if not audited.top_issue or not audited.outreach_angle:
        return False, "missing audit summary"
    if not audited.angle_bucket:
        return False, "missing angle bucket"
    if not audited.google_place_id:
        return False, "missing Google Place ID"
    if audited.lead_quality_score < settings.min_lead_score:
        return False, f"low score ({audited.lead_quality_score})"
    return True, ""


def _skip_duplicate_if_needed(found: FoundLead, existing_pages: list[Dict[str, Any]], logger: DailyLogger) -> bool:
    domain = normalize_domain(found.website)
    duplicate = find_duplicate_by_keys(
        google_place_id=found.google_place_id,
        domain=domain,
        phone=found.phone,
        business_name=found.business_name,
        address=found.address,
        existing_pages=existing_pages,
    )
    if not duplicate:
        return False

    logger.count("duplicates_found")
    status = _existing_status(duplicate)
    if status in CONTACTED_OR_CLOSED:
        logger.count("already_contacted_skipped")
        logger.skip(found.business_name, domain, "Duplicate already contacted or closed")
        return True

    if status in EARLY_STAGE and should_skip_recent_good_record(duplicate):
        logger.count("duplicates_skipped")
        logger.skip(found.business_name, domain, "Duplicate recently scraped with acceptable data quality")
        return True

    return False


def run_daily_scrape() -> None:
    logger = DailyLogger()
    logger.event("Starting lead scraper daily run")
    logger.event(f"DRY_RUN: {settings.dry_run}")
    logger.event(f"MAX_NEW_LEADS_PER_RUN: {settings.max_new_leads_per_run}")
    logger.event(f"MAX_PLACES_RESULTS_PER_LOCATION: {settings.max_places_results_per_location}")
    logger.event(f"MAX_TOTAL_CANDIDATES: {settings.max_total_candidates}")
    logger.count("target_new_leads_requested", settings.max_new_leads_per_run)
    logger.event(f"Google Places API key present: {'yes' if settings.google_places_api_key else 'no'}")
    logger.event(f"Notion API key present: {'yes' if settings.notion_api_key else 'no'}")
    logger.event(f"Notion database ID present: {'yes' if settings.notion_database_id else 'no'}")
    logger.event(f"Search niche/query base: {settings.niche}")
    for location in settings.locations:
        logger.event(f"Search location: {location}")
        logger.event(f"Search query used: {settings.niche} in {location}")
    logger.event("Lead finder implementation: Places API (New) searchText")

    try:
        existing_pages, data_source, data_source_id = load_existing_leads()
        schema_properties = data_source.get("properties", {})
        if not settings.dry_run:
            ensure_source_option(schema_properties, data_source_id)
    except Exception as exc:
        logger.error("Notion", f"Could not load existing leads: {exc}")
        logger.write()
        return

    try:
        found_leads = find_local_leads()
        logger.count("total_found", len(found_leads))
        logger.event(f"Leads found from Google Places: {len(found_leads)}")
        if not found_leads:
            for location in settings.locations:
                logger.event(f"Google Places returned 0 leads for query/location: {settings.niche} in {location}")
    except Exception as exc:
        logger.error("Lead Finder", str(exc))
        logger.write()
        return

    accepted_count = 0
    seen_domains: set[str] = set()

    for found in found_leads[: settings.max_total_candidates]:
        if accepted_count >= settings.max_new_leads_per_run:
            logger.event(f"Target new lead count reached: {settings.max_new_leads_per_run}")
            break

        logger.count("candidates_processed")
        domain = normalize_domain(found.website)
        if not found.website:
            logger.count("no_website_skipped")
            logger.skip(found.business_name, "", "No website")
            continue
        if domain in seen_domains:
            logger.count("duplicates_skipped")
            logger.skip(found.business_name, domain, "Duplicate found in current run")
            continue
        seen_domains.add(domain)

        try:
            if _skip_duplicate_if_needed(found, existing_pages, logger):
                continue

            scraped = scrape_website(found)
            logger.count("leads_scraped")
            logger.event(f"Scraped lead: {found.business_name} ({domain})")
            audited = audit_lead(found, scraped)
            duplicate = find_duplicate(audited, existing_pages)
            if duplicate:
                logger.count("duplicates_found")
            valid, reason = _is_valid_for_write(audited)
            if not valid:
                if reason.startswith("low score"):
                    logger.count("low_score_skipped")
                logger.skip(audited.business_name, audited.domain, reason)
                continue

            if settings.dry_run:
                action = "update" if duplicate else "insert"
                logger.count("would_update" if duplicate else "would_insert")
                logger.event(f"DRY RUN: would {action} {audited.business_name} ({audited.domain})")
                accepted_count += 1
                continue

            if duplicate:
                status = _existing_status(duplicate)
                if status in CONTACTED_OR_CLOSED:
                    logger.count("already_contacted_skipped")
                    logger.skip(audited.business_name, audited.domain, "Duplicate already contacted or closed")
                    continue
                if update_existing_lead(duplicate, audited, schema_properties):
                    logger.count("existing_enriched")
                    logger.event(f"Updated existing lead: {audited.business_name}")
                else:
                    logger.count("duplicates_skipped")
                    logger.skip(audited.business_name, audited.domain, "Duplicate had no weaker/missing fields to enrich")
            else:
                page_id = write_new_lead(audited, schema_properties, data_source_id)
                logger.count("new_inserted")
                logger.event(f"Inserted new lead: {audited.business_name} ({page_id})")

            accepted_count += 1
        except Exception as exc:
            logger.error(found.business_name, str(exc))
            continue

    if accepted_count < settings.max_new_leads_per_run:
        if len(found_leads) >= settings.max_total_candidates:
            reason = "candidate safety cap reached before target"
        else:
            reason = "candidate pool exhausted after skips, duplicates, low scores, or errors"
        logger.event(
            "Target not reached: "
            f"accepted {accepted_count}/{settings.max_new_leads_per_run}; "
            f"processed {logger.counters.get('candidates_processed', 0)}/"
            f"{min(len(found_leads), settings.max_total_candidates)} candidates; "
            f"reason: {reason}"
        )

    logger.event("Lead scraper daily run complete")
    logger.write()


if __name__ == "__main__":
    run_daily_scrape()
