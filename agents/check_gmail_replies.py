from __future__ import annotations

import os
import re
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from datetime import date, datetime, timedelta
from email.utils import parseaddr
from typing import Any, Dict, List, Optional, Tuple

from notion_client import Client

from src.config import settings
from src.gmail_client import (
    get_profile_email,
    get_thread_full,
    is_stale_gmail_thread_error,
    search_messages,
    _extract_message_text,  # type: ignore[attr-defined]
)
from src.notion_client import get_database_and_data_source, get_data_source_schema


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


REPLY_CHECK_DRY_RUN = _env_flag("REPLY_CHECK_DRY_RUN", True)

# ---------------------------------------------------------------------------
# Lead / sequence state constants
# ---------------------------------------------------------------------------
ACTIVE_SENT_STATUSES = {"email 1 sent", "email 2 sent", "outreach_sent"}
STOP_STATUSES = {"replied", "closed", "call booked", "not interested", "do not contact"}
BLOCKED_LEAD_STATUSES = {"not_fit", "archived", "paid_client"}
TERMINAL_LEAD_STATUSES = STOP_STATUSES | BLOCKED_LEAD_STATUSES

# ---------------------------------------------------------------------------
# Field candidates
# ---------------------------------------------------------------------------
NAME_CANDIDATES = ("Business Name", "Practice Name", "Clinic Name", "Name")
EMAIL_CANDIDATES = ("Email", "Contact Email")
LEAD_STATUS_CANDIDATES = ("Lead Status", "Outreach Status")
REPLY_STATUS_CANDIDATES = ("Reply Status",)
REPLY_CATEGORY_CANDIDATES = ("Reply Category",)
GMAIL_SENT_STATUS_CANDIDATES = ("Gmail Sent Status",)
GMAIL_MATCH_STATUS_CANDIDATES = ("Gmail Match Status",)
GMAIL_THREAD_ID_CANDIDATES = ("Gmail Thread ID",)
DO_NOT_CONTACT_CANDIDATES = ("Do Not Contact", "DNC")
LAST_OUTREACH_DATE_CANDIDATES = ("Last Outreach Date", "Last Email Sent At", "Email 1 Date")
NEXT_FOLLOW_UP_DATE_CANDIDATES = ("Next Follow-up Date", "Next Follow Up Date")
SEQUENCE_STEP_CANDIDATES = ("Sequence Step",)
REPLY_NOTES_CANDIDATES = ("Reply Notes",)
OPS_STATUS_CANDIDATES = ("Ops Status",)
BLOCKER_REASON_CANDIDATES = ("Blocker Reason",)

# ---------------------------------------------------------------------------
# Reply category values
# ---------------------------------------------------------------------------
REPLY_HUMAN = "human_reply"
REPLY_OOO = "out_of_office"
REPLY_BOUNCE = "bounce_or_undeliverable"
REPLY_AUTO = "auto_reply"
REPLY_UNSUB = "unsubscribe"
REPLY_UNKNOWN = "unknown"

REPLY_NOTES_HUMAN = "Human reply detected by Gmail reply checker."
REPLY_NOTES_BOUNCE = "Bounce / undeliverable notification detected by Gmail reply checker."
REPLY_NOTES_OOO = "Out-of-office auto-reply detected by Gmail reply checker."
REPLY_NOTES_AUTO = "Automated response detected by Gmail reply checker."
REPLY_NOTES_UNSUB = "Unsubscribe / do-not-contact request detected by Gmail reply checker."
REPLY_NOTES_UNKNOWN = "Possible reply detected — manual review required."

OOO_FOLLOWUP_DELAY_DAYS = 5  # business days to delay if no return date found

# ---------------------------------------------------------------------------
# Classification patterns
# ---------------------------------------------------------------------------
BOUNCE_SUBJECT_PATTERNS: Tuple[str, ...] = (
    "delivery status notification",
    "undelivered mail returned to sender",
    "delivery has failed",
    "address not found",
    "the email account that you tried to reach does not exist",
    "domain not found",
    "domain unavailable",
    "mailbox unavailable",
    "message not delivered",
    "mail delivery subsystem",
    "delivery failure",
    "delivery notification: failure",
)
BOUNCE_FROM_PATTERNS: Tuple[str, ...] = (
    "mailer-daemon",
    "mail delivery subsystem",
    "postmaster@",
)
BOUNCE_BODY_PATTERNS: Tuple[str, ...] = (
    "550 ",
    "5.1.1",
    "5.4.1",
    "permanent failure",
    "recipient address rejected",
    "address not found",
    "does not exist",
    "domain not found",
    "domain unavailable",
    "mailbox unavailable",
    "message not delivered",
)

OOO_SUBJECT_PATTERNS: Tuple[str, ...] = (
    "out of office",
    "ooo:",
    " ooo ",
    "automatic reply:",
    "auto-reply:",
    "away from the office",
    "i am away",
    "vacation",
)
OOO_BODY_PATTERNS: Tuple[str, ...] = (
    "out of office",
    "i am away",
    "away from the office",
    "away from office",
    "on vacation",
    "returning on",
    "will return",
    "i will be back",
    "back in the office",
    "returning on",
)

AUTO_SUBJECT_PATTERNS: Tuple[str, ...] = (
    "auto-reply:",
    "autoreply:",
    "automatic response:",
    "automated response:",
    "automatic email",
)
AUTO_FROM_PATTERNS: Tuple[str, ...] = (
    "no-reply@",
    "noreply@",
    "donotreply@",
    "do-not-reply@",
)
AUTO_BODY_PATTERNS: Tuple[str, ...] = (
    "auto-reply",
    "autoreply",
    "automatic response",
    "automated response",
    "this is an automated message",
    "this message was sent automatically",
    "please do not reply to this",
)

UNSUB_SUBJECT_PATTERNS: Tuple[str, ...] = (
    "unsubscribe",
    "remove me",
    "stop emailing",
)
UNSUB_BODY_PATTERNS: Tuple[str, ...] = (
    "unsubscribe",
    "remove me",
    "stop emailing",
    "do not contact",
    "please remove",
    "take me off",
    "opt out",
    "opt-out",
)

# Return-date patterns for OOO parsing
_RETURN_DATE_PATS = [
    re.compile(r"returning\s+(?:on\s+)?([A-Za-z]+\s+\d{1,2}(?:,?\s+\d{4})?)", re.IGNORECASE),
    re.compile(r"back\s+(?:in\s+the\s+office\s+)?(?:on\s+)?([A-Za-z]+\s+\d{1,2}(?:,?\s+\d{4})?)", re.IGNORECASE),
    re.compile(r"return\s+(?:on\s+)?([A-Za-z]+\s+\d{1,2}(?:,?\s+\d{4})?)", re.IGNORECASE),
    re.compile(r"available\s+(?:again\s+)?(?:on\s+)?([A-Za-z]+\s+\d{1,2}(?:,?\s+\d{4})?)", re.IGNORECASE),
]
_DATE_FMTS = ("%B %d, %Y", "%B %d %Y", "%B %d")


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def get_client() -> Client:
    if not settings.notion_api_key:
        raise ValueError("NOTION_API_KEY is missing.")
    return Client(auth=settings.notion_api_key)


def _first_existing(properties: Dict[str, Any], candidates: Tuple[str, ...]) -> Optional[str]:
    for c in candidates:
        if c in properties:
            return c
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
    if prop.get("date") and isinstance(prop["date"], dict):
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


def _property_update(prop_type: str, value: Any) -> Optional[Dict[str, Any]]:
    if prop_type == "select":
        return {"select": {"name": str(value)}}
    if prop_type == "status":
        return {"status": {"name": str(value)}}
    if prop_type == "rich_text":
        return {"rich_text": [{"type": "text", "text": {"content": str(value)}}]}
    if prop_type == "checkbox":
        return {"checkbox": bool(value)}
    if prop_type == "date":
        return {"date": {"start": str(value)}}
    if prop_type == "multi_select":
        names = [str(value)] if isinstance(value, str) else [str(v) for v in value]
        return {"multi_select": [{"name": n} for n in names if n]}
    return None


def _add_update(
    updates: Dict[str, Any],
    schema_properties: Dict[str, Any],
    candidates: Tuple[str, ...],
    value: Any,
) -> None:
    field = _first_existing(schema_properties, candidates)
    if not field:
        return
    upd = _property_update(schema_properties[field].get("type", ""), value)
    if upd:
        updates[field] = upd


def _checkbox_update(
    updates: Dict[str, Any],
    schema_properties: Dict[str, Any],
    candidates: Tuple[str, ...],
    value: bool = True,
) -> None:
    field = _first_existing(schema_properties, candidates)
    if not field:
        return
    updates[field] = {"checkbox": value}


def _checkbox_true(properties: Dict[str, Any], candidates: Tuple[str, ...]) -> bool:
    field = _first_existing(properties, candidates)
    if not field:
        return False
    return bool(properties.get(field, {}).get("checkbox"))


def _load_pages(data_source_id: str) -> List[Dict[str, Any]]:
    client = get_client()
    pages: List[Dict[str, Any]] = []
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
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


# ---------------------------------------------------------------------------
# Reply classification helpers
# ---------------------------------------------------------------------------

def _extract_body(message: Dict[str, Any]) -> str:
    """Extract plain/HTML text from a full-format Gmail message."""
    payload = message.get("payload", {})
    if not payload:
        return ""
    return _extract_message_text(payload) or ""


def _classify_reply(
    subject: str,
    from_addr: str,
    body: str,
    lead_email: str,
) -> str:
    s = subject.lower()
    f = from_addr.lower()
    b = body.lower()[:3000]  # scan first 3k chars

    # --- Bounce (highest priority) ---
    if any(p in s for p in BOUNCE_SUBJECT_PATTERNS):
        return REPLY_BOUNCE
    if any(p in f for p in BOUNCE_FROM_PATTERNS):
        return REPLY_BOUNCE
    if b and any(p in b for p in BOUNCE_BODY_PATTERNS):
        return REPLY_BOUNCE

    # --- Unsubscribe ---
    if any(p in s for p in UNSUB_SUBJECT_PATTERNS):
        return REPLY_UNSUB
    if b and any(p in b for p in UNSUB_BODY_PATTERNS):
        return REPLY_UNSUB

    # --- Out of office ---
    if any(p in s for p in OOO_SUBJECT_PATTERNS):
        return REPLY_OOO
    if b and any(p in b for p in OOO_BODY_PATTERNS):
        return REPLY_OOO

    # --- Auto reply ---
    if any(p in s for p in AUTO_SUBJECT_PATTERNS):
        return REPLY_AUTO
    if any(p in f for p in AUTO_FROM_PATTERNS):
        return REPLY_AUTO
    if b and any(p in b for p in AUTO_BODY_PATTERNS):
        return REPLY_AUTO

    # --- Human (from lead email specifically) ---
    if f and f == lead_email.lower():
        return REPLY_HUMAN

    return REPLY_UNKNOWN


def _parse_return_date(body: str) -> Optional[date]:
    """Try to extract an OOO return date from body text."""
    today = date.today()
    for pat in _RETURN_DATE_PATS:
        m = pat.search(body)
        if not m:
            continue
        date_str = m.group(1).strip().rstrip(",")
        for fmt in _DATE_FMTS:
            try:
                parsed = datetime.strptime(date_str.title(), fmt).date()
                if fmt == "%B %d":
                    parsed = parsed.replace(year=today.year)
                    if parsed < today:
                        parsed = parsed.replace(year=today.year + 1)
                return parsed
            except ValueError:
                continue
    return None


def _add_business_days(start: date, n: int) -> date:
    current = start
    remaining = n
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


# ---------------------------------------------------------------------------
# Gmail thread / search helpers
# ---------------------------------------------------------------------------

def _find_inbound_message(
    thread_id: str,
    lead_email: str,
    my_email: str,
    send_as_alias: str = "",
) -> Optional[Dict[str, Any]]:
    """Fetch a thread (full format) and return the first reply-like message.

    Accepted messages: from the lead email, OR from a known bounce sender
    (mailer-daemon / postmaster). Outbound messages (our own addresses) are
    always skipped, including the send-as alias.
    """
    if not thread_id:
        return None
    my_addresses = {my_email.lower()}
    if send_as_alias:
        my_addresses.add(send_as_alias.strip().lower())
    lead_lower = lead_email.lower()
    thread = get_thread_full(thread_id)
    for message in thread.get("messages", []):
        from_hdr = _email_from_header(_header(message, "From"))
        if not from_hdr:
            continue
        if from_hdr in my_addresses:
            continue  # skip our own outbound messages
        # Accept reply from the lead themselves
        if from_hdr == lead_lower:
            return message
        # Accept bounce / delivery-failure notifications from mail systems
        if any(p in from_hdr for p in BOUNCE_FROM_PATTERNS):
            return message
    return None


def _search_reply_message(
    lead_email: str,
    last_outreach: Optional[date],
) -> Optional[Dict[str, Any]]:
    """Search Gmail for any message FROM lead_email after outreach date."""
    if last_outreach:
        query = f"from:{lead_email} after:{last_outreach.strftime('%Y/%m/%d')} -in:spam -in:trash"
    else:
        query = f"from:{lead_email} newer_than:30d -in:spam -in:trash"
    messages = search_messages(query, max_results=5)
    return messages[0] if messages else None


def _search_bounce_message(lead_email: str) -> Optional[Dict[str, Any]]:
    """Search for bounce notifications related to lead_email."""
    query = f"from:mailer-daemon {lead_email} -in:spam -in:trash newer_than:90d"
    messages = search_messages(query, max_results=3)
    return messages[0] if messages else None


# ---------------------------------------------------------------------------
# Notion update builders
# ---------------------------------------------------------------------------

def _build_category_updates(
    schema_properties: Dict[str, Any],
    category: str,
    *,
    ooo_return_date: Optional[date] = None,
    lead: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    updates: Dict[str, Any] = {}
    today = date.today()
    write_legacy_fields = settings.write_legacy_notion_fields

    if category == REPLY_HUMAN:
        if write_legacy_fields and _first_existing(schema_properties, ("Lead Status",)):
            _add_update(updates, schema_properties, ("Lead Status",), "replied")
        elif write_legacy_fields:
            _add_update(updates, schema_properties, REPLY_STATUS_CANDIDATES, "Replied")
            _add_update(updates, schema_properties, ("Outreach Status",), "Replied")
        _add_update(updates, schema_properties, SEQUENCE_STEP_CANDIDATES, "Replied")
        _add_update(updates, schema_properties, GMAIL_MATCH_STATUS_CANDIDATES, "replied")
        _add_update(updates, schema_properties, REPLY_CATEGORY_CANDIDATES, REPLY_HUMAN)
        _add_update(updates, schema_properties, REPLY_NOTES_CANDIDATES, REPLY_NOTES_HUMAN)

    elif category == REPLY_UNSUB:
        _checkbox_update(updates, schema_properties, DO_NOT_CONTACT_CANDIDATES, True)
        _add_update(updates, schema_properties, GMAIL_MATCH_STATUS_CANDIDATES, "replied")
        if write_legacy_fields:
            _add_update(updates, schema_properties, REPLY_STATUS_CANDIDATES, "unsubscribe")
        _add_update(updates, schema_properties, REPLY_CATEGORY_CANDIDATES, REPLY_UNSUB)
        _add_update(updates, schema_properties, REPLY_NOTES_CANDIDATES, REPLY_NOTES_UNSUB)

    elif category == REPLY_BOUNCE:
        _add_update(updates, schema_properties, GMAIL_MATCH_STATUS_CANDIDATES, "bounced")
        _add_update(updates, schema_properties, REPLY_CATEGORY_CANDIDATES, REPLY_BOUNCE)
        _add_update(updates, schema_properties, REPLY_NOTES_CANDIDATES, REPLY_NOTES_BOUNCE)
        # Block from future sends/follow-ups: set Ops Status + Blocker Reason.
        # Sequence Step = "Bounced" is intentionally NOT written — that option is not
        # guaranteed to exist in Notion. Ops Status = needs_email_research is the blocker.
        _add_update(updates, schema_properties, OPS_STATUS_CANDIDATES, "needs_email_research")
        _add_update(updates, schema_properties, BLOCKER_REASON_CANDIDATES, "bounced_email")

    elif category == REPLY_OOO:
        _add_update(updates, schema_properties, REPLY_CATEGORY_CANDIDATES, REPLY_OOO)
        _add_update(updates, schema_properties, REPLY_NOTES_CANDIDATES, REPLY_NOTES_OOO)
        followup_field = _first_existing(schema_properties, NEXT_FOLLOW_UP_DATE_CANDIDATES)
        if followup_field:
            if ooo_return_date:
                new_fu = _add_business_days(ooo_return_date, 1)
            else:
                new_fu = _add_business_days(today, OOO_FOLLOWUP_DELAY_DAYS)
            existing_fu: Optional[date] = None
            if lead:
                existing_fu = _date_value((lead.get("properties") or {}).get(followup_field) or {})
            if existing_fu is None or new_fu > existing_fu:
                upd = _property_update(schema_properties[followup_field].get("type", ""), new_fu.isoformat())
                if upd:
                    updates[followup_field] = upd

    elif category == REPLY_AUTO:
        _add_update(updates, schema_properties, REPLY_CATEGORY_CANDIDATES, REPLY_AUTO)
        _add_update(updates, schema_properties, REPLY_NOTES_CANDIDATES, REPLY_NOTES_AUTO)

    else:  # REPLY_UNKNOWN
        _add_update(updates, schema_properties, REPLY_CATEGORY_CANDIDATES, REPLY_UNKNOWN)
        _add_update(updates, schema_properties, REPLY_NOTES_CANDIDATES, REPLY_NOTES_UNKNOWN)

    return updates


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    dry_run = REPLY_CHECK_DRY_RUN or getattr(settings, "dry_run", False)

    print("Gmail Reply Checker")
    print(f"- REPLY_CHECK_DRY_RUN: {'yes' if REPLY_CHECK_DRY_RUN else 'no'}")
    print(f"- effective dry_run: {'yes' if dry_run else 'NO - LIVE WRITES ENABLED'}")
    print()

    _, data_source_id = get_database_and_data_source()
    schema = get_data_source_schema()
    schema_properties = schema.get("properties", {})
    pages = _load_pages(data_source_id)
    my_email = get_profile_email()

    summary: Dict[str, int] = {
        "records_checked": 0,
        "human_reply": 0,
        "out_of_office": 0,
        "bounce_or_undeliverable": 0,
        "auto_reply": 0,
        "unsubscribe": 0,
        "unknown": 0,
        "skipped_self_sent": 0,
        "skipped_already_classified": 0,
        "skipped_terminal": 0,
        "skipped_not_sent": 0,
        "skipped_missing_email": 0,
        "stale_gmail_thread_id": 0,
        "would_update": 0,
        "records_updated": 0,
        "errors": 0,
    }

    for page in pages:
        try:
            properties = page.get("properties", {})
            status_field = _first_existing(properties, LEAD_STATUS_CANDIDATES)
            gmail_sent_field = _first_existing(properties, GMAIL_SENT_STATUS_CANDIDATES)
            gmail_match_field = _first_existing(properties, GMAIL_MATCH_STATUS_CANDIDATES)
            reply_category_field = _first_existing(properties, REPLY_CATEGORY_CANDIDATES)
            email_field = _first_existing(properties, EMAIL_CANDIDATES)
            thread_field = _first_existing(properties, GMAIL_THREAD_ID_CANDIDATES)
            last_outreach_field = _first_existing(properties, LAST_OUTREACH_DATE_CANDIDATES)

            lead_status = _text(properties.get(status_field or "", {})).strip().lower()
            gmail_sent_status = _text(properties.get(gmail_sent_field or "", {})).strip().lower()
            gmail_match_status = _text(properties.get(gmail_match_field or "", {})).strip().lower()

            # Skip already-terminal records
            if (
                lead_status in TERMINAL_LEAD_STATUSES
                or lead_status == "replied"
                or gmail_match_status == "replied"
                or _checkbox_true(properties, DO_NOT_CONTACT_CANDIDATES)
            ):
                summary["skipped_terminal"] += 1
                continue

            # Skip if already classified (e.g., already bounce or OOO noted)
            if reply_category_field:
                existing_category = _text(properties.get(reply_category_field, {})).strip()
                if existing_category:
                    summary["skipped_already_classified"] += 1
                    continue

            # Must be a sent lead
            ops_status_field = _first_existing(properties, ("Ops Status",))
            ops_status = _text(properties.get(ops_status_field or "", {})).strip().lower() if ops_status_field else ""
            if gmail_sent_status != "sent" and lead_status not in ACTIVE_SENT_STATUSES and ops_status != "sent":
                summary["skipped_not_sent"] += 1
                continue

            summary["records_checked"] += 1
            lead_email = _text(properties.get(email_field or "", {})).lower()
            if not lead_email:
                summary["skipped_missing_email"] += 1
                continue

            thread_id = _text(properties.get(thread_field or "", {}))
            last_outreach = _date_value(properties.get(last_outreach_field or "", {}))

            # --- Find an inbound message ---
            inbound_message: Optional[Dict[str, Any]] = None
            search_based = False

            if thread_id:
                try:
                    inbound_message = _find_inbound_message(
                        thread_id, lead_email, my_email,
                        send_as_alias=settings.gmail_send_as_email,
                    )
                except Exception as exc:
                    if is_stale_gmail_thread_error(exc):
                        summary["stale_gmail_thread_id"] += 1
                        continue
                    raise

            if inbound_message is None:
                # Fallback: search by lead email
                search_result = _search_reply_message(lead_email, last_outreach)
                if search_result:
                    search_based = True
                    # Build a minimal message dict from search result for classification
                    # (search results are message stubs; use subject from snippet if available)
                    inbound_message = search_result
                else:
                    # Also check for bounces when no thread_id
                    if not thread_id:
                        bounce_result = _search_bounce_message(lead_email)
                        if bounce_result:
                            search_based = True
                            inbound_message = bounce_result

            if inbound_message is None:
                continue

            # --- Classify the reply ---
            subject = _header(inbound_message, "Subject") if not search_based else ""
            from_addr = _email_from_header(_header(inbound_message, "From")) if not search_based else ""
            body = _extract_body(inbound_message) if not search_based else ""

            # Self-sent guard (applies to search-based path; thread path already filters)
            my_addrs = {my_email.lower(), settings.gmail_send_as_email.strip().lower()}
            if from_addr and from_addr in my_addrs:
                summary["skipped_self_sent"] += 1
                continue

            category = _classify_reply(subject, from_addr, body, lead_email)

            # Extract OOO return date if applicable
            ooo_return: Optional[date] = None
            if category == REPLY_OOO and body:
                ooo_return = _parse_return_date(body)

            name = _lead_name(page)
            ooo_note = f" (return: {ooo_return})" if ooo_return else ""
            print(f"  {category.upper()} | {name} | {lead_email} | subject: {subject[:80] or '<no subject>'}{ooo_note}")

            # Increment category counter
            summary[category] = summary.get(category, 0) + 1

            if dry_run:
                summary["would_update"] += 1
                continue

            updates = _build_category_updates(
                schema_properties,
                category,
                ooo_return_date=ooo_return,
                lead=page,
            )
            if updates:
                get_client().pages.update(page_id=page["id"], properties=updates)
                summary["records_updated"] += 1

        except Exception as exc:
            summary["errors"] += 1
            print(f"ERROR | {_lead_name(page)} | {exc}")

    print()
    print("Gmail Reply Check Summary:")
    for key in (
        "records_checked",
        "human_reply",
        "out_of_office",
        "bounce_or_undeliverable",
        "auto_reply",
        "unsubscribe",
        "unknown",
        "skipped_self_sent",
        "skipped_already_classified",
        "skipped_terminal",
        "skipped_not_sent",
        "skipped_missing_email",
        "stale_gmail_thread_id",
        "would_update",
        "records_updated",
        "errors",
    ):
        print(f"- {key}: {summary.get(key, 0)}")
    if dry_run:
        print("Dry run mode: no Notion writes were made.")


if __name__ == "__main__":
    main()
