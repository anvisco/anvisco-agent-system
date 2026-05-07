from __future__ import annotations

import base64
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from html import unescape
from email.utils import getaddresses
from typing import Any, Dict, List, Optional, Tuple

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from notion_client import Client

from src.config import settings
from src.gmail_client import get_gmail_service, get_profile_email
from src.notion_client import get_data_source_schema, get_database_and_data_source


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


DRY_RUN: bool = _env_flag("SENT_RECONCILE_DRY_RUN", True)
GMAIL_SENT_LOOKBACK_DAYS: int = 60
FOLLOWUP_BUSINESS_DAYS_EMAIL_1: int = 3
FOLLOWUP_BUSINESS_DAYS_EMAIL_2: int = 5


# ---------------------------------------------------------------------------
# Property candidate lists
# ---------------------------------------------------------------------------

NAME_CANDIDATES: List[str] = ["Business Name", "Practice Name", "Clinic Name", "Name"]
EMAIL_CANDIDATES: List[str] = ["Email", "Contact Email"]
LEAD_STATUS_CANDIDATES: List[str] = ["Lead Status", "Outreach Status", "Reply Status"]
OPS_STATUS_CANDIDATES: List[str] = ["Ops Status"]
SEQUENCE_STEP_CANDIDATES: List[str] = ["Sequence Step"]
GMAIL_DRAFT_ID_CANDIDATES: List[str] = ["Gmail Draft ID"]
GMAIL_THREAD_ID_CANDIDATES: List[str] = ["Gmail Thread ID"]
GMAIL_MATCH_STATUS_CANDIDATES: List[str] = ["Gmail Match Status"]
GMAIL_SENT_STATUS_CANDIDATES: List[str] = ["Gmail Sent Status"]
GMAIL_MESSAGE_ID_CANDIDATES: List[str] = ["Gmail Message ID"]
LAST_OUTREACH_DATE_CANDIDATES: List[str] = ["Last Outreach Date", "Last Email Sent At"]
NEXT_FOLLOW_UP_DATE_CANDIDATES: List[str] = ["Next Follow-up Date", "Next Follow Up Date"]
SCHEDULED_SEND_DATE_CANDIDATES: List[str] = ["Scheduled Send Date"]
DO_NOT_CONTACT_CANDIDATES: List[str] = ["Do Not Contact", "DNC"]
EMAIL_1_SUBJECT_CANDIDATES: List[str] = ["Email 1 Subject", "Email Subject", "Subject"]
BLOCKER_REASON_CANDIDATES: List[str] = ["Blocker Reason"]

HISTORICAL_OUTREACH_SIGNALS: Tuple[str, ...] = (
    "web design services",
    "web design services to improve conversion",
    "web design",
    "follow-up:",
    "website",
    "booking",
    "conversion",
    "i build websites that run, grow, and optimize your business",
    "anvisco.com",
    "anvis",
    "get a free website audit",
    "book a discovery call",
    "websites built to run, grow, and get discovered",
)

DELIVERY_FAILURE_SIGNALS: Tuple[str, ...] = (
    "delivery status notification",
    "delivery failure",
    "message delivery failure",
    "undeliverable",
    "returned to sender",
    "mailer-daemon",
    "postmaster",
)

HISTORICAL_VERBOSE_REJECTION_LIMIT = 8
HISTORICAL_ACCEPTED_EXAMPLE_LIMIT = 10


# ---------------------------------------------------------------------------
# Status / blocker constants
# ---------------------------------------------------------------------------

CANDIDATE_OPS_STATUSES = {"ready_to_draft", "draft_created", "ready_to_send"}
GMAIL_DRAFT_SENT_STATUSES = {"", "not_sent", "drafted"}
REPLIED_VALUES = {"replied", "reply_received", "human_reply"}
BOUNCED_VALUES = {"bounced", "bounce", "bounce_or_undeliverable", "bounced_email"}

# Blocker Reason values that are safe to clear once a Gmail sent match is confirmed.
# NOT cleared: duplicate_possible, bounced_email, do_not_contact, casl_missing, casl_manual_review
CLEARABLE_BLOCKERS = {
    "missing_scheduled_send_date",
    "draft_missing",
    "stale_draft",
    "not_active_draft",
    "stale_gmail_draft_id",
}

PROTECTED_BLOCKERS = {
    "duplicate_possible",
    "bounced_email",
    "do_not_contact",
    "casl_missing",
    "casl_manual_review",
}


# ---------------------------------------------------------------------------
# Notion helpers
# ---------------------------------------------------------------------------

def _notion_client() -> Client:
    if not settings.notion_api_key:
        raise ValueError("NOTION_API_KEY is missing.")
    return Client(auth=settings.notion_api_key)


def _first(properties: Dict[str, Any], candidates: List[str]) -> Optional[str]:
    for c in candidates:
        if c in properties:
            return c
    return None


def _norm_choice(text: str) -> str:
    return re.sub(r"\s+", "_", str(text or "").strip().lower())


def _text(prop: Dict[str, Any]) -> str:
    if not prop:
        return ""
    if prop.get("title"):
        return "".join(i.get("plain_text", "") for i in prop["title"]).strip()
    if prop.get("rich_text"):
        return "".join(i.get("plain_text", "") for i in prop["rich_text"]).strip()
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


def _prop_text(page: Dict[str, Any], candidates: List[str]) -> str:
    props = page.get("properties", {})
    field = _first(props, candidates)
    return _text(props.get(field or "", {}))


def _checkbox_true(page: Dict[str, Any], candidates: List[str]) -> bool:
    props = page.get("properties", {})
    field = _first(props, candidates)
    if not field:
        return False
    return bool(props.get(field, {}).get("checkbox"))


def _lead_name(page: Dict[str, Any]) -> str:
    return _prop_text(page, NAME_CANDIDATES) or page.get("id", "<unknown>")


def _load_all_pages() -> List[Dict[str, Any]]:
    client = _notion_client()
    _, data_source_id = get_database_and_data_source()
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


# ---------------------------------------------------------------------------
# Notion update helpers
# ---------------------------------------------------------------------------

def _property_update(prop_type: str, value: Any) -> Optional[Dict[str, Any]]:
    if not value:
        return None
    if prop_type == "rich_text":
        return {"rich_text": [{"type": "text", "text": {"content": str(value)}}]}
    if prop_type == "title":
        return {"title": [{"type": "text", "text": {"content": str(value)}}]}
    if prop_type == "select":
        return {"select": {"name": str(value)}}
    if prop_type == "status":
        return {"status": {"name": str(value)}}
    if prop_type == "date":
        return {"date": {"start": str(value)}}
    if prop_type == "url":
        return {"url": str(value)}
    if prop_type == "email":
        return {"email": str(value)}
    return None


def _set_field(
    updates: Dict[str, Any],
    schema_props: Dict[str, Any],
    candidates: List[str],
    value: str,
) -> None:
    field = _first(schema_props, candidates)
    if not field:
        return
    upd = _property_update(schema_props[field].get("type", ""), value)
    if upd:
        updates[field] = upd


def _clear_date_field(
    updates: Dict[str, Any],
    schema_props: Dict[str, Any],
    candidates: List[str],
) -> None:
    field = _first(schema_props, candidates)
    if not field:
        return
    if schema_props[field].get("type") == "date":
        updates[field] = {"date": None}


def _clear_select_or_text_field(
    updates: Dict[str, Any],
    schema_props: Dict[str, Any],
    candidates: List[str],
) -> None:
    field = _first(schema_props, candidates)
    if not field:
        return
    prop_type = schema_props[field].get("type", "")
    if prop_type == "select":
        updates[field] = {"select": None}
    elif prop_type == "status":
        updates[field] = {"status": None}
    elif prop_type == "rich_text":
        updates[field] = {"rich_text": []}


def _clear_rich_text_field(
    updates: Dict[str, Any],
    schema_props: Dict[str, Any],
    candidates: List[str],
) -> None:
    field = _first(schema_props, candidates)
    if not field:
        return
    prop_type = schema_props[field].get("type")
    if prop_type == "rich_text":
        updates[field] = {"rich_text": []}
    elif prop_type in {"url", "email"}:
        updates[field] = {prop_type: None}


# ---------------------------------------------------------------------------
# Business day arithmetic
# ---------------------------------------------------------------------------

def _add_business_days(start: date, n: int) -> date:
    current = start
    remaining = n
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:  # Mon–Fri only
            remaining -= 1
    return current


# ---------------------------------------------------------------------------
# Candidate filter
# ---------------------------------------------------------------------------

def _has_candidate_signal(
    ops: str,
    sequence: str,
    gmail_sent: str,
    draft_id: str,
    thread_id: str,
) -> bool:
    if ops in CANDIDATE_OPS_STATUSES:
        return True
    if sequence == "email_1_drafted":
        return True
    if draft_id and gmail_sent in GMAIL_DRAFT_SENT_STATUSES:
        return True
    if thread_id and gmail_sent != "sent":
        return True
    return False


def _classify_page(page: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Returns (is_candidate, skip_reason).

    skip_reason is '' when is_candidate is True.
    skip_reason is 'not_candidate' for records that are simply not in scope
    (e.g., already sent, not_fit) — these are not tallied in a named counter.
    All other skip_reason values map directly to summary counter keys.
    """
    if _checkbox_true(page, DO_NOT_CONTACT_CANDIDATES):
        return False, "skipped_dnc"

    ops = _norm_choice(_prop_text(page, OPS_STATUS_CANDIDATES))
    lead_status = _norm_choice(_prop_text(page, LEAD_STATUS_CANDIDATES))
    gmail_sent = _norm_choice(_prop_text(page, GMAIL_SENT_STATUS_CANDIDATES))
    gmail_match = _norm_choice(_prop_text(page, GMAIL_MATCH_STATUS_CANDIDATES))
    sequence = _norm_choice(_prop_text(page, SEQUENCE_STEP_CANDIDATES))
    blocker = _norm_choice(_prop_text(page, BLOCKER_REASON_CANDIDATES))
    draft_id = _prop_text(page, GMAIL_DRAFT_ID_CANDIDATES).strip()
    thread_id = _prop_text(page, GMAIL_THREAD_ID_CANDIDATES).strip()

    # Hard skips (in priority order)
    if ops in REPLIED_VALUES or lead_status in REPLIED_VALUES or gmail_match == "replied" or sequence == "replied":
        return False, "skipped_replied"

    if gmail_match == "bounced" or gmail_sent in BOUNCED_VALUES or blocker == "bounced_email" or lead_status in BOUNCED_VALUES:
        return False, "skipped_bounced"

    if gmail_sent == "sent":
        return False, "skipped_already_sent"

    if ops == "needs_email_research":
        return False, "skipped_email_research"

    candidate_signal = _has_candidate_signal(ops, sequence, gmail_sent, draft_id, thread_id)

    if ops == "needs_duplicate_review" and not candidate_signal:
        return False, "skipped_duplicate_review"

    if candidate_signal:
        return True, ""

    return False, "not_candidate"


# ---------------------------------------------------------------------------
# Gmail search helpers (read-only — no mutations)
# ---------------------------------------------------------------------------

def _search_sent_messages(
    service: Any,
    query: str,
    max_results: int = 50,
) -> List[Dict[str, Any]]:
    response = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=max_results)
        .execute()
    )
    return list(response.get("messages", []))


def _get_message_full(service: Any, message_id: str) -> Dict[str, Any]:
    return (
        service.users()
        .messages()
        .get(
            userId="me",
            id=message_id,
            format="full",
        )
        .execute()
    )


def _message_headers(message: Dict[str, Any]) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    for header in (message.get("payload") or {}).get("headers", []):
        name = str(header.get("name", "")).lower()
        if name:
            headers[name] = str(header.get("value", "") or "")
    return headers


def _header_email_match(header_value: str, lead_email: str) -> bool:
    expected = lead_email.strip().lower()
    if not expected:
        return False
    parsed = [email.lower() for _, email in getaddresses([header_value]) if email]
    if parsed:
        return expected in parsed
    return expected in header_value.lower()


def _header_emails(header_value: str) -> List[str]:
    parsed = [email.lower() for _, email in getaddresses([header_value]) if email]
    if parsed:
        return parsed
    fallback = re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", header_value or "")
    return [email.lower() for email in fallback]


def _decode_message_data(data: str) -> str:
    if not data:
        return ""
    padded = data + "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _extract_message_text(payload: Dict[str, Any]) -> str:
    if not payload:
        return ""
    mime_type = str(payload.get("mimeType", "") or "").lower()
    body = payload.get("body", {}) or {}
    data = body.get("data", "")
    if mime_type in {"text/html", "text/plain"} and data:
        return unescape(_decode_message_data(data))
    for part in payload.get("parts", []) or []:
        text = _extract_message_text(part)
        if text:
            return text
    if data:
        return unescape(_decode_message_data(data))
    return ""


def _message_body_text(message: Dict[str, Any]) -> str:
    return _extract_message_text(message.get("payload", {}) or {})


def _normalized_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _message_from_email(message: Dict[str, Any]) -> str:
    headers = _message_headers(message)
    from_hdr = headers.get("from", "")
    emails = _header_emails(from_hdr)
    return emails[0] if emails else ""


def _allowed_sender_emails() -> List[str]:
    candidates = {
        settings.gmail_send_as_email.strip().lower(),
    }
    try:
        profile_email = get_profile_email()
        if profile_email:
            candidates.add(str(profile_email).strip().lower())
    except Exception as exc:
        print(f"    Warning: could not read authenticated Gmail profile email: {exc}")
    return sorted(email for email in candidates if email)


def _has_allowed_sender(message: Dict[str, Any], allowed_senders: List[str]) -> bool:
    if not allowed_senders:
        return False
    from_email = _message_from_email(message)
    if from_email:
        return from_email in allowed_senders
    headers = _message_headers(message)
    from_hdr = headers.get("from", "").lower()
    return any(sender in from_hdr for sender in allowed_senders)


def _is_delivery_failure_message(message: Dict[str, Any]) -> bool:
    headers = _message_headers(message)
    subject = _normalized_text(headers.get("subject", ""))
    body = _normalized_text(_message_body_text(message))
    if any(signal in subject for signal in DELIVERY_FAILURE_SIGNALS):
        return True
    if any(signal in body for signal in DELIVERY_FAILURE_SIGNALS):
        return True
    return False


def _historical_signal_hits(message: Dict[str, Any]) -> List[str]:
    headers = _message_headers(message)
    subject = _normalized_text(headers.get("subject", ""))
    body = _normalized_text(_message_body_text(message))
    snippet = _normalized_text(message.get("snippet", ""))
    haystack = f"{subject}\n{body}\n{snippet}"
    return [signal for signal in HISTORICAL_OUTREACH_SIGNALS if signal in haystack]


def _subject_signal_hits(subject: str) -> List[str]:
    normalized = _normalized_text(subject)
    return [signal for signal in HISTORICAL_OUTREACH_SIGNALS if signal in normalized]


def _message_label_strings(message: Dict[str, Any]) -> List[str]:
    return [str(label).strip() for label in (message.get("labelIds") or []) if str(label).strip()]


def _historical_message_debug_info(
    message: Dict[str, Any],
    lead_email: str,
    allowed_senders: List[str],
) -> Dict[str, Any]:
    headers = _message_headers(message)
    labels = _message_label_strings(message)
    subject = headers.get("subject", "")
    from_hdr = headers.get("from", "")
    to_hdr = headers.get("to", "")
    sender_match = _has_allowed_sender(message, allowed_senders)
    subject_hits = _subject_signal_hits(subject)
    signal_hits = subject_hits or _historical_signal_hits(message)

    debug = {
        "subject": subject,
        "from": from_hdr,
        "to": to_hdr,
        "labels": labels,
        "sender_match": sender_match,
        "subject_hits": subject_hits,
        "signal_hits": signal_hits,
        "accepted": False,
        "reason": "",
    }

    if "SENT" not in {label.upper() for label in labels}:
        debug["reason"] = "rejected_missing_sent_label"
        return debug

    if not _header_email_match(to_hdr, lead_email):
        debug["reason"] = "rejected_to_mismatch"
        return debug

    if _is_delivery_failure_message(message):
        debug["reason"] = "rejected_bounce_signature"
        return debug

    if not signal_hits:
        debug["reason"] = "rejected_missing_outreach_signal"
        return debug

    debug["accepted"] = True
    debug["reason"] = "accepted_historical_outreach"
    return debug


def _strip_subject_prefixes(subject: str) -> str:
    s = subject.strip()
    while True:
        stripped = re.sub(r"^(?:re|fw|fwd)\s*:\s*", "", s, flags=re.IGNORECASE).strip()
        if stripped == s:
            return stripped
        s = stripped


def _strong_normalized_subject(subject: str) -> str:
    s = _strip_subject_prefixes(subject)
    replacements = {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u00a0": " ",
    }
    for old, new in replacements.items():
        s = s.replace(old, new)
    s = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def _subject_match_quality(gmail_subject: str, expected_subject: str) -> str:
    if gmail_subject.strip() == expected_subject.strip():
        return "exact"
    if _strong_normalized_subject(gmail_subject) == _strong_normalized_subject(expected_subject):
        return "normalized"
    return ""


def _load_sent_candidates(
    service: Any,
    lead_email: str,
    allowed_senders: List[str],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    if not lead_email:
        return [], []

    query = f"to:{lead_email} in:sent newer_than:{GMAIL_SENT_LOOKBACK_DAYS}d"
    stubs = _search_sent_messages(service, query, max_results=50)
    if not stubs:
        return [], []

    cutoff_dt = datetime.now(tz=timezone.utc) - timedelta(days=GMAIL_SENT_LOOKBACK_DAYS)
    messages: List[Dict[str, Any]] = []
    diagnostics: List[Dict[str, Any]] = []

    for stub in stubs:
        msg_id = stub.get("id", "")
        if not msg_id:
            diagnostics.append({
                "subject": "",
                "from": "",
                "to": "",
                "labels": [],
                "sender_match": False,
                "subject_hits": [],
                "signal_hits": [],
                "accepted": False,
                "reason": "rejected_unknown",
            })
            continue

        try:
            msg = _get_message_full(service, msg_id)
        except Exception as exc:
            print(f"    Warning: could not fetch Gmail message {msg_id}: {exc}")
            diagnostics.append({
                "subject": "",
                "from": "",
                "to": "",
                "labels": [],
                "sender_match": False,
                "subject_hits": [],
                "signal_hits": [],
                "accepted": False,
                "reason": "rejected_unknown",
            })
            continue

        # Must carry the SENT label
        labels = _message_label_strings(msg)
        if "SENT" not in {label.upper() for label in labels}:
            diagnostics.append({
                "subject": _message_headers(msg).get("subject", ""),
                "from": _message_headers(msg).get("from", ""),
                "to": _message_headers(msg).get("to", ""),
                "labels": labels,
                "sender_match": _has_allowed_sender(msg, allowed_senders),
                "subject_hits": _subject_signal_hits(_message_headers(msg).get("subject", "")),
                "signal_hits": _historical_signal_hits(msg),
                "accepted": False,
                "reason": "rejected_missing_sent_label",
            })
            continue

        # Date guard
        internal_ms = int(msg.get("internalDate") or 0)
        if not internal_ms:
            diagnostics.append({
                "subject": _message_headers(msg).get("subject", ""),
                "from": _message_headers(msg).get("from", ""),
                "to": _message_headers(msg).get("to", ""),
                "labels": labels,
                "sender_match": _has_allowed_sender(msg, allowed_senders),
                "subject_hits": _subject_signal_hits(_message_headers(msg).get("subject", "")),
                "signal_hits": _historical_signal_hits(msg),
                "accepted": False,
                "reason": "rejected_missing_timestamp",
            })
            continue
        sent_dt = datetime.fromtimestamp(internal_ms / 1000, tz=timezone.utc)
        if sent_dt < cutoff_dt:
            diagnostics.append({
                "subject": _message_headers(msg).get("subject", ""),
                "from": _message_headers(msg).get("from", ""),
                "to": _message_headers(msg).get("to", ""),
                "labels": labels,
                "sender_match": _has_allowed_sender(msg, allowed_senders),
                "subject_hits": _subject_signal_hits(_message_headers(msg).get("subject", "")),
                "signal_hits": _historical_signal_hits(msg),
                "accepted": False,
                "reason": "rejected_outside_lookback",
            })
            continue

        debug = _historical_message_debug_info(msg, lead_email, allowed_senders)
        diagnostics.append(debug)
        if not debug["accepted"]:
            continue

        headers = _message_headers(msg)
        gmail_subject = headers.get("subject", "")
        thread_id = stub.get("threadId", "") or msg.get("threadId", "")
        messages.append({
            "message_id": msg_id,
            "thread_id": thread_id,
            "sent_date": sent_dt.date(),
            "sent_dt": sent_dt,
            "subject": gmail_subject,
            "body": _message_body_text(msg),
            "from_email": _message_from_email(msg),
            "sender_match": debug["sender_match"],
            "signal_hits": debug["signal_hits"],
        })

    messages.sort(
        key=lambda item: item.get("sent_dt", datetime.min.replace(tzinfo=timezone.utc)),
        reverse=True,
    )
    return messages, diagnostics


def _find_subject_match(
    sent_messages: List[Dict[str, Any]],
    email_1_subject: str,
) -> Optional[Dict[str, Any]]:
    if not email_1_subject:
        return None

    matches: List[Dict[str, Any]] = []
    for message in sent_messages:
        match_quality = _subject_match_quality(message.get("subject", ""), email_1_subject)
        if not match_quality:
            continue
        matched = dict(message)
        matched["match_quality"] = match_quality
        matches.append(matched)

    if not matches:
        return None

    matches.sort(
        key=lambda item: (
            1 if item.get("match_quality") == "exact" else 0,
            item.get("sent_dt", datetime.min.replace(tzinfo=timezone.utc)),
        ),
        reverse=True,
    )
    best = dict(matches[0])
    best.pop("sent_dt", None)
    return best


def _sequence_step_from_sent_count(sent_count: int) -> str:
    if sent_count >= 3:
        return "Sequence Complete"
    if sent_count == 2:
        return "Email 2 Sent"
    return "Email 1 Sent"


def _followup_days_for_sequence_step(sequence_step: str) -> Optional[int]:
    if sequence_step == "Email 1 Sent":
        return FOLLOWUP_BUSINESS_DAYS_EMAIL_1
    if sequence_step == "Email 2 Sent":
        return FOLLOWUP_BUSINESS_DAYS_EMAIL_2
    return None


def _next_followup_for_sequence(sent_date: date, sequence_step: str) -> Optional[date]:
    followup_days = _followup_days_for_sequence_step(sequence_step)
    if followup_days is None:
        return None
    return _add_business_days(sent_date, followup_days)


# ---------------------------------------------------------------------------
# Notion update builder
# ---------------------------------------------------------------------------

def _build_notion_update(
    page: Dict[str, Any],
    schema_props: Dict[str, Any],
    sent_date: date,
    sequence_step: str,
    next_followup_date: Optional[date],
    thread_id: str,
    message_id: str,
) -> Dict[str, Any]:
    """
    Build the Notion property update dict for a confirmed-sent lead.

    Sets:
      Ops Status         → sent
      Sequence Step      → inferred sent step
      Gmail Sent Status  → sent
      Gmail Match Status → sent_exists
      Gmail Thread ID    → from Gmail (if available)
      Gmail Message ID   → from Gmail (if field exists in schema)
      Last Outreach Date → Gmail sent date
      Next Follow-up Date→ step-specific follow-up date, or cleared for completion
      Scheduled Send Date→ cleared (date → null)
      Gmail Draft ID     → cleared (no longer relevant post-send)
      Blocker Reason     → cleared only if it is a send/draft-side blocker;
                           preserved if it is duplicate/bounce/DNC/CASL related.
    """
    updates: Dict[str, Any] = {}

    _set_field(updates, schema_props, OPS_STATUS_CANDIDATES, "sent")
    _set_field(updates, schema_props, SEQUENCE_STEP_CANDIDATES, sequence_step)
    _set_field(updates, schema_props, GMAIL_SENT_STATUS_CANDIDATES, "sent")
    _set_field(updates, schema_props, GMAIL_MATCH_STATUS_CANDIDATES, "sent_exists")
    _set_field(updates, schema_props, LAST_OUTREACH_DATE_CANDIDATES, sent_date.isoformat())
    if next_followup_date:
        _set_field(updates, schema_props, NEXT_FOLLOW_UP_DATE_CANDIDATES, next_followup_date.isoformat())
    else:
        _clear_date_field(updates, schema_props, NEXT_FOLLOW_UP_DATE_CANDIDATES)

    if thread_id:
        _set_field(updates, schema_props, GMAIL_THREAD_ID_CANDIDATES, thread_id)

    if message_id:
        # Only writes if "Gmail Message ID" property exists in schema.
        _set_field(updates, schema_props, GMAIL_MESSAGE_ID_CANDIDATES, message_id)

    # Clear Scheduled Send Date (date field → null)
    _clear_date_field(updates, schema_props, SCHEDULED_SEND_DATE_CANDIDATES)

    # Clear Gmail Draft ID — draft was consumed by the send
    _clear_rich_text_field(updates, schema_props, GMAIL_DRAFT_ID_CANDIDATES)

    # Clear Blocker Reason only if it is a send/draft-side blocker.
    # Preserve: duplicate_possible, bounced_email, do_not_contact, casl_missing, casl_manual_review
    blocker_field = _first(schema_props, BLOCKER_REASON_CANDIDATES)
    if blocker_field:
        current_blocker = _norm_choice(_prop_text(page, BLOCKER_REASON_CANDIDATES))
        if current_blocker in CLEARABLE_BLOCKERS:
            _clear_select_or_text_field(updates, schema_props, BLOCKER_REASON_CANDIDATES)

    return updates


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("Gmail Sent-State Reconciliation")
    print(f"  SENT_RECONCILE_DRY_RUN : {'yes — no Notion writes' if DRY_RUN else 'NO — LIVE WRITES ENABLED'}")
    print(f"  Gmail lookback         : {GMAIL_SENT_LOOKBACK_DAYS} days")
    print(
        f"  Follow-up offsets      : Email 1 +{FOLLOWUP_BUSINESS_DAYS_EMAIL_1} business days,"
        f" Email 2 +{FOLLOWUP_BUSINESS_DAYS_EMAIL_2} business days,"
        f" Email 3/Complete clears Next Follow-up Date"
    )
    print()

    schema = get_data_source_schema()
    schema_props = schema.get("properties", {})

    print("Loading Notion records...")
    pages = _load_all_pages()
    print(f"Loaded {len(pages)} Notion records.")
    print()

    service = get_gmail_service()
    allowed_senders = _allowed_sender_emails()

    summary: Dict[str, int] = {
        "records_checked": 0,
        "candidates": 0,
        "historical_raw_sent_found": 0,
        "rejected_wrong_sender": 0,
        "rejected_missing_sent_label": 0,
        "rejected_to_mismatch": 0,
        "rejected_bounce_signature": 0,
        "rejected_missing_outreach_signal": 0,
        "rejected_missing_timestamp": 0,
        "rejected_outside_lookback": 0,
        "rejected_unknown": 0,
        "accepted_historical_outreach": 0,
        "gmail_sent_matches": 0,
        "subject_match_sent_matches": 0,
        "historical_sent_matches": 0,
        "historical_email1_sent": 0,
        "historical_email2_sent": 0,
        "historical_email3_sent": 0,
        "no_subject_historical_match": 0,
        "no_subject_no_match": 0,
        "would_update": 0,
        "updated": 0,
        "no_match": 0,
        "skipped_replied": 0,
        "skipped_bounced": 0,
        "skipped_email_research": 0,
        "skipped_duplicate_review": 0,
        "skipped_already_sent": 0,
        "errors": 0,
    }
    example_log_limit = 10
    subject_match_examples: List[str] = []
    historical_match_examples: List[str] = []
    accepted_historical_examples: List[str] = []
    historical_rejection_examples: List[str] = []
    no_match_examples: List[str] = []
    skipped_examples: List[str] = []

    for page in pages:
        summary["records_checked"] += 1
        name = _lead_name(page)
        is_candidate, skip_reason = _classify_page(page)

        if not is_candidate:
            if skip_reason in summary:
                summary[skip_reason] += 1
            if skip_reason != "not_candidate" and len(skipped_examples) < example_log_limit:
                ops_status = _prop_text(page, OPS_STATUS_CANDIDATES) or "<empty>"
                gmail_sent = _prop_text(page, GMAIL_SENT_STATUS_CANDIDATES) or "<empty>"
                gmail_match = _prop_text(page, GMAIL_MATCH_STATUS_CANDIDATES) or "<empty>"
                skipped_examples.append(
                    f"SKIP {skip_reason.replace('skipped_', '')} | {name} | "
                    f"ops={ops_status} | gmail_sent={gmail_sent} | gmail_match={gmail_match}"
                )
            # not_candidate = record simply not in scope (sent, not_fit, etc.) — no counter
            continue

        summary["candidates"] += 1

        lead_email = _prop_text(page, EMAIL_CANDIDATES).strip().lower()
        email_1_subject = _prop_text(page, EMAIL_1_SUBJECT_CANDIDATES).strip()
        ops_status = _prop_text(page, OPS_STATUS_CANDIDATES)
        sequence_step = _prop_text(page, SEQUENCE_STEP_CANDIDATES)
        draft_id = _prop_text(page, GMAIL_DRAFT_ID_CANDIDATES)
        thread_id = _prop_text(page, GMAIL_THREAD_ID_CANDIDATES)

        if not lead_email:
            print(f"  SKIP | {name} | no email address in Notion")
            if len(skipped_examples) < example_log_limit:
                skipped_examples.append(f"SKIP missing_email | {name}")
            summary["errors"] += 1
            continue

        print(
            f"  CHECKING | {name} | {lead_email}"
            f" | ops: {ops_status} | step: {sequence_step}"
            f" | draft_id: {draft_id or '<none>'} | thread_id: {thread_id or '<none>'}"
        )

        try:
            sent_messages, diagnostics = _load_sent_candidates(service, lead_email, allowed_senders)
        except Exception as exc:
            print(f"    → ERROR | Gmail search failed: {exc}")
            summary["errors"] += 1
            continue

        for debug in diagnostics:
            summary["historical_raw_sent_found"] += 1
            if not debug.get("sender_match"):
                summary["rejected_wrong_sender"] += 1
            reason = str(debug.get("reason", "") or "")
            if not reason:
                reason = "rejected_unknown"
            if reason in summary and reason.startswith("rejected_"):
                summary[reason] += 1
            if reason == "accepted_historical_outreach":
                summary["accepted_historical_outreach"] += 1
            if not debug.get("accepted") and len(historical_rejection_examples) < example_log_limit:
                labels = ", ".join(debug.get("labels", [])) or "<none>"
                historical_rejection_examples.append(
                    f"{reason or 'rejected_unknown'} | subject={str(debug.get('subject', ''))[:70]} | "
                    f"from={str(debug.get('from', ''))[:70]} | to={str(debug.get('to', ''))[:70]} | "
                    f"labels={labels}"
                )

        subject_match = _find_subject_match(sent_messages, email_1_subject)

        match: Optional[Dict[str, Any]] = None
        match_kind = ""
        sequence_step = ""
        next_followup_date: Optional[date] = None
        sent_count = 0

        if subject_match:
            match = subject_match
            match_kind = "subject"
            sequence_step = "Email 1 Sent"
            next_followup_date = _next_followup_for_sequence(match["sent_date"], sequence_step)
            summary["subject_match_sent_matches"] += 1
            summary["gmail_sent_matches"] += 1
            if len(subject_match_examples) < example_log_limit:
                subject_match_examples.append(
                    f"SUBJECT MATCH | {name} | {lead_email} | sent={match['sent_date']} | "
                    f"match={match.get('match_quality', '<unknown>')} | subject={match['subject'][:70]}"
                )
        else:
            historical_matches = sent_messages
            if historical_matches:
                sent_count = len(historical_matches)
                match = historical_matches[0]
                match_kind = "historical"
                sequence_step = _sequence_step_from_sent_count(sent_count)
                next_followup_date = _next_followup_for_sequence(match["sent_date"], sequence_step)
                summary["historical_sent_matches"] += 1
                summary["gmail_sent_matches"] += 1
                if sent_count == 1:
                    summary["historical_email1_sent"] += 1
                elif sent_count == 2:
                    summary["historical_email2_sent"] += 1
                else:
                    summary["historical_email3_sent"] += 1
                if not email_1_subject:
                    summary["no_subject_historical_match"] += 1
                if len(historical_match_examples) < example_log_limit:
                    hit_summary = ", ".join(match.get("signal_hits", [])) or "<none>"
                    historical_match_examples.append(
                        f"HISTORICAL MATCH | {name} | {lead_email} | count={sent_count} | "
                        f"inferred={sequence_step} | sent={match['sent_date']} | "
                        f"signals={hit_summary} | subject={match['subject'][:70]}"
                    )
                if len(accepted_historical_examples) < HISTORICAL_ACCEPTED_EXAMPLE_LIMIT:
                    accepted_historical_examples.append(
                        f"ACCEPTED | {name} | to={lead_email} | subject={match['subject'][:70]} | "
                        f"sent={match['sent_date']} | signal={', '.join(match.get('signal_hits', [])) or '<none>'} | "
                        f"sequence_count={sent_count}"
                    )
            else:
                if not email_1_subject:
                    summary["no_subject_no_match"] += 1
                    print("    → NO SUBJECT | falling back to historical search found no valid outreach message")
                else:
                    print(
                        f"    → NO MATCH | subject: {email_1_subject[:70]}"
                        f" | no sent message found in last {GMAIL_SENT_LOOKBACK_DAYS} days"
                    )
                if len(no_match_examples) < example_log_limit:
                    if email_1_subject:
                        no_match_examples.append(
                            f"NO MATCH | {name} | {lead_email} | subject={email_1_subject[:70]}"
                        )
                    else:
                        no_match_examples.append(f"NO SUBJECT NO MATCH | {name} | {lead_email}")
                summary["no_match"] += 1
                continue

        if match_kind == "historical" and not email_1_subject:
            print("    → HISTORICAL MATCH | no Email 1 Subject present; matched on sent-message signals")
        elif match_kind == "historical":
            print("    → HISTORICAL MATCH | Email 1 Subject did not match; matched on sent-message signals")
        else:
            print(f"    → SUBJECT MATCH | Email 1 Subject matched via {match.get('match_quality', '<unknown>')}")

        sent_date = match["sent_date"]
        matched_thread = match["thread_id"]
        matched_msg = match["message_id"]
        followup_date = next_followup_date
        current_blocker = _prop_text(page, BLOCKER_REASON_CANDIDATES)
        blocker_note = ""
        if current_blocker:
            current_blocker_norm = _norm_choice(current_blocker)
            if current_blocker_norm in CLEARABLE_BLOCKERS:
                blocker_note = f" | clears blocker: {current_blocker}"
            elif current_blocker_norm in PROTECTED_BLOCKERS:
                blocker_note = f" | preserves blocker: {current_blocker}"
            else:
                blocker_note = f" | preserves blocker: {current_blocker}"

        match_summary = (
            f"    → MATCH | Gmail sent: {sent_date}"
            f" | subject: {match['subject'][:60]}"
            f" | step: {sequence_step}"
            f" | kind: {match_kind}"
            f" | thread: {matched_thread or '<none>'}"
            f" | followup → {followup_date.isoformat() if followup_date else '<cleared>'}"
            f"{blocker_note}"
        )

        if DRY_RUN:
            summary["would_update"] += 1
            print(match_summary)
            print(
                f"      WOULD UPDATE"
                f" → ops: sent | step: {sequence_step}"
                f" | gmail_sent: sent | gmail_match: sent_exists"
                f" | last_outreach: {sent_date} | next_followup: {followup_date.isoformat() if followup_date else '<cleared>'}"
                f" | scheduled_send: clear | draft_id: clear"
            )
            continue

        try:
            updates = _build_notion_update(
                page,
                schema_props,
                sent_date,
                sequence_step,
                followup_date,
                matched_thread,
                matched_msg,
            )
            if not updates:
                print("    → SKIP | no updatable fields found in schema")
                continue
            _notion_client().pages.update(page_id=page["id"], properties=updates)
            summary["updated"] += 1
            print(match_summary)
            print(
                f"      UPDATED"
                f" → ops: sent | step: {sequence_step}"
                f" | gmail_sent: sent | gmail_match: sent_exists"
                f" | last_outreach: {sent_date} | next_followup: {followup_date.isoformat() if followup_date else '<cleared>'}"
                f" | scheduled_send: clear | draft_id: clear"
            )
        except Exception as exc:
            summary["errors"] += 1
            print(f"    → ERROR | Notion update failed: {exc}")

    print()
    print("Reconciliation Summary:")
    for key in (
        "records_checked",
        "candidates",
        "historical_raw_sent_found",
        "rejected_wrong_sender",
        "rejected_missing_sent_label",
        "rejected_to_mismatch",
        "rejected_bounce_signature",
        "rejected_missing_outreach_signal",
        "rejected_missing_timestamp",
        "rejected_outside_lookback",
        "rejected_unknown",
        "accepted_historical_outreach",
        "gmail_sent_matches",
        "subject_match_sent_matches",
        "historical_sent_matches",
        "historical_email1_sent",
        "historical_email2_sent",
        "historical_email3_sent",
        "no_subject_historical_match",
        "no_subject_no_match",
        "would_update",
        "updated",
        "no_match",
        "skipped_replied",
        "skipped_bounced",
        "skipped_email_research",
        "skipped_duplicate_review",
        "skipped_already_sent",
        "errors",
    ):
        print(f"  {key}: {summary.get(key, 0)}")

    if subject_match_examples:
        print()
        print(f"Subject-match examples ({len(subject_match_examples)} shown):")
        for line in subject_match_examples:
            print(f"  {line}")

    if historical_match_examples:
        print()
        print(f"Historical-match examples ({len(historical_match_examples)} shown):")
        for line in historical_match_examples:
            print(f"  {line}")

    if accepted_historical_examples:
        print()
        print(f"Accepted historical examples ({len(accepted_historical_examples)} shown):")
        for line in accepted_historical_examples:
            print(f"  {line}")

    if historical_rejection_examples:
        print()
        print(f"Historical rejection examples ({len(historical_rejection_examples)} shown):")
        for line in historical_rejection_examples:
            print(f"  {line}")

    if no_match_examples:
        print()
        print(f"No-match examples ({len(no_match_examples)} shown):")
        for line in no_match_examples:
            print(f"  {line}")

    if skipped_examples:
        print()
        print(f"Skipped examples ({len(skipped_examples)} shown):")
        for line in skipped_examples:
            print(f"  {line}")

    if DRY_RUN:
        print()
        print("Dry run complete. No Notion writes were made.")
        print("Run with SENT_RECONCILE_DRY_RUN=false to apply changes.")


if __name__ == "__main__":
    main()
