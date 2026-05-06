from __future__ import annotations

import os
import re
import sys
from html import escape
from email.utils import getaddresses, parseaddr
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from notion_client import Client

from agents import generate_drafts_from_notion as draft_flow
from src.config import settings
from src.email_writer import (
    SIGNATURE_HTML,
    _lead_business_name as email_lead_business_name,
    _lead_city,
    _lead_languages,
    _lead_rating,
    _lead_review_count,
    _lead_services,
    _short_business_name,
)
from src.gmail_client import get_draft, get_preferred_send_as_email, list_drafts, update_draft
from src.safety import validate_prospect_copy


def _max_redrafts_per_run() -> int:
    raw_value = os.getenv("MAX_REDRAFTS_PER_RUN", "5")
    if raw_value is None or not raw_value.strip():
        return 5
    try:
        return max(1, int(raw_value))
    except ValueError:
        return 5


MAX_REDRAFTS_PER_RUN = _max_redrafts_per_run()
REDRAFT_DRY_RUN = os.getenv("REDRAFT_DRY_RUN", "true").strip().lower() in {"1", "true", "yes", "on"}

OUTREACH_MARKERS = (
    "free website audit",
    "visibility, trust, and booking flow",
    "booking flow",
    "anvis",
    "brian nguyen",
    "anvisco.com",
)
BUSINESS_NAME_PATTERNS = (
    re.compile(r"\b(?:hi|hello)\s+(.+?)\s+team\b", re.IGNORECASE),
    re.compile(r"\bseeing\s+(.+?)'s\b", re.IGNORECASE),
    re.compile(r"\bis\s+(.+?)'s\b", re.IGNORECASE),
    re.compile(r"\bare\s+(.+?)'s\b", re.IGNORECASE),
    re.compile(r"\bfor\s+(.+?)\s+or a\b", re.IGNORECASE),
)
BLOCKED_LEAD_STATUSES = {"not_fit", "archived", "paid_client"}
BLOCKED_DUPLICATE_STATUSES = {"duplicate", "possible_duplicate", "already_contacted", "do_not_contact"}
BLOCKED_GMAIL_MATCH_STATUSES = {"sent_exists", "replied"}
SERVICE_PHRASE_MAP = {
    "cleaning": "family, cosmetic, and denture care",
    "cosmetic": "family, cosmetic, and denture care",
    "denture": "family, cosmetic, and denture care",
    "invisalign": "Invisalign care",
    "implant": "implant dentistry",
    "emergency": "emergency dental care",
    "orthodont": "orthodontic care",
    "root canal": "root canal treatment",
    "whitening": "teeth whitening",
}


def get_client() -> Client:
    if not settings.notion_api_key:
        raise ValueError("NOTION_API_KEY is missing.")
    return Client(auth=settings.notion_api_key)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _normalize_email(email: str) -> str:
    return parseaddr(email)[1].strip().lower()


def _split_emails(header_value: str) -> List[str]:
    return [email.strip().lower() for _, email in getaddresses([header_value]) if email.strip()]


def _header(message: Dict[str, Any], name: str) -> str:
    for header in message.get("payload", {}).get("headers", []):
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


def _decode_body_data(data: str) -> str:
    import base64

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
    mime_type = payload.get("mimeType", "")
    body = payload.get("body", {})
    if mime_type in {"text/html", "text/plain"}:
        data = body.get("data", "")
        if data:
            return _decode_body_data(data)
    for part in payload.get("parts", []) or []:
        text = _extract_message_text(part)
        if text:
            return text
    data = body.get("data", "")
    if data:
        return _decode_body_data(data)
    return ""


def _draft_message(draft: Dict[str, Any]) -> Dict[str, Any]:
    return draft.get("message", {}) or {}


def _draft_thread_id(draft: Dict[str, Any]) -> str:
    return str(_draft_message(draft).get("threadId", "") or "").strip()


def _draft_id(draft: Dict[str, Any]) -> str:
    return str(draft.get("id", "") or "").strip()


def _draft_subject(draft: Dict[str, Any]) -> str:
    subject = _header(_draft_message(draft), "Subject").strip()
    if subject:
        return subject
    return str(draft.get("subject", "") or "").strip()


def _draft_to_header(draft: Dict[str, Any]) -> str:
    to_header = _header(_draft_message(draft), "To").strip()
    if to_header:
        return to_header
    to_value = draft.get("to", [])
    if isinstance(to_value, list):
        return ", ".join(str(value).strip() for value in to_value if str(value).strip())
    return str(to_value or "").strip()


def _draft_cc_header(draft: Dict[str, Any]) -> str:
    cc_header = _header(_draft_message(draft), "Cc").strip()
    if cc_header:
        return cc_header
    cc_value = draft.get("cc", [])
    if isinstance(cc_value, list):
        return ", ".join(str(value).strip() for value in cc_value if str(value).strip())
    return str(cc_value or "").strip()


def _draft_bcc_header(draft: Dict[str, Any]) -> str:
    bcc_header = _header(_draft_message(draft), "Bcc").strip()
    if bcc_header:
        return bcc_header
    bcc_value = draft.get("bcc", [])
    if isinstance(bcc_value, list):
        return ", ".join(str(value).strip() for value in bcc_value if str(value).strip())
    return str(bcc_value or "").strip()


def _draft_from_header(draft: Dict[str, Any]) -> str:
    from_header = _header(_draft_message(draft), "From").strip()
    if from_header:
        return from_header
    return str(draft.get("from_", "") or "").strip()


def _draft_in_reply_to(draft: Dict[str, Any]) -> str:
    return _header(_draft_message(draft), "In-Reply-To").strip()


def _draft_references(draft: Dict[str, Any]) -> str:
    return _header(_draft_message(draft), "References").strip()


def _draft_body_text(draft: Dict[str, Any]) -> str:
    message = _draft_message(draft)
    text = _extract_message_text(message.get("payload", {}))
    if text:
        return text
    snippet = str(message.get("snippet", "") or "")
    return snippet


def _draft_search_text(draft: Dict[str, Any]) -> str:
    parts = [
        _draft_subject(draft),
        _draft_body_text(draft),
        _draft_to_header(draft),
        _draft_cc_header(draft),
    ]
    return "\n".join(part for part in parts if part)


def _draft_has_outreach_markers(draft: Dict[str, Any]) -> bool:
    text = _draft_search_text(draft).lower()
    return any(marker in text for marker in OUTREACH_MARKERS)


def _draft_business_name(draft: Dict[str, Any]) -> str:
    text = _draft_search_text(draft)
    for pattern in BUSINESS_NAME_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1).strip()
    return ""


def _lead_property_text(lead: Dict[str, Any], candidates: Sequence[str]) -> str:
    return draft_flow._lead_text_value(lead, list(candidates))  # type: ignore[attr-defined]


def _lead_business_name(lead: Dict[str, Any]) -> str:
    return draft_flow._get_lead_name(lead)  # type: ignore[attr-defined]


def _lead_email(lead: Dict[str, Any]) -> str:
    return _normalize_email(_lead_property_text(lead, draft_flow.EMAIL_FIELD_CANDIDATES))  # type: ignore[attr-defined]


def _lead_safe_for_redraft(lead: Dict[str, Any]) -> List[str]:
    reasons: List[str] = []

    if draft_flow._lead_checkbox_true(lead, ["Do Not Contact"]):  # type: ignore[attr-defined]
        reasons.append("Do Not Contact is true")

    if not draft_flow._lead_is_canada(lead):  # type: ignore[attr-defined]
        reasons.append("Country is not Canada")

    status_property = draft_flow._first_existing_property_name(  # type: ignore[attr-defined]
        lead.get("properties", {}),
        draft_flow.STATUS_FIELD_CANDIDATES,  # type: ignore[attr-defined]
    )
    status_value = _normalize_text(draft_flow._get_text_value(draft_flow._get_property(lead, status_property or "")))  # type: ignore[attr-defined]
    if status_value in BLOCKED_LEAD_STATUSES:
        reasons.append(f"Lead Status is {status_value}")

    duplicate_status = draft_flow._lead_duplicate_status(lead)  # type: ignore[attr-defined]
    if duplicate_status in BLOCKED_DUPLICATE_STATUSES:
        reasons.append(f"Duplicate Status is {duplicate_status}")

    gmail_match_status = draft_flow._lead_gmail_match_status(lead)  # type: ignore[attr-defined]
    if gmail_match_status in BLOCKED_GMAIL_MATCH_STATUSES:
        reasons.append(f"Gmail Match Status is {gmail_match_status}")

    return reasons


def _build_notion_indexes(leads: List[Dict[str, Any]]) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
    indexes = {
        "email": {},
        "draft_id": {},
        "thread_id": {},
        "business_name": {},
    }

    for lead in leads:
        lead_id = str(lead.get("id", "") or "").strip()
        if not lead_id:
            continue
        properties = lead.get("properties", {})
        email = _normalize_email(_lead_property_text(lead, draft_flow.EMAIL_FIELD_CANDIDATES))  # type: ignore[attr-defined]
        draft_id = _lead_property_text(lead, draft_flow.GMAIL_DRAFT_ID_CANDIDATES)  # type: ignore[attr-defined]
        thread_id = _lead_property_text(lead, draft_flow.GMAIL_THREAD_ID_CANDIDATES)  # type: ignore[attr-defined]
        business_name = _lead_business_name(lead)
        short_business_name = _short_business_name(business_name) if business_name else ""

        if email:
            indexes["email"].setdefault(email, []).append(lead)
        if draft_id:
            indexes["draft_id"].setdefault(draft_id.strip(), []).append(lead)
        if thread_id:
            indexes["thread_id"].setdefault(thread_id.strip(), []).append(lead)
        for name_value in (business_name, short_business_name):
            normalized = _normalize_text(name_value)
            if normalized:
                indexes["business_name"].setdefault(normalized, []).append(lead)

        # Keep direct access to properties for later filtering.
        lead["properties"] = properties

    return indexes


def _recipient_in_notion(recipient_emails: Iterable[str], indexes: Dict[str, Dict[str, List[Dict[str, Any]]]]) -> bool:
    notion_emails = set(indexes["email"].keys())
    return any(email in notion_emails for email in recipient_emails)


def _draft_candidate_reason(
    draft: Dict[str, Any],
    indexes: Dict[str, Dict[str, List[Dict[str, Any]]]],
) -> Tuple[bool, str]:
    to_emails = _split_emails(_draft_to_header(draft))
    draft_id = _draft_id(draft)
    thread_id = _draft_thread_id(draft)

    if _recipient_in_notion(to_emails, indexes):
        return True, "recipient email found in Notion"
    if draft_id and draft_id in indexes["draft_id"]:
        return True, "Gmail Draft ID found in Notion"
    if thread_id and thread_id in indexes["thread_id"]:
        return True, "Gmail Thread ID found in Notion"
    if _draft_has_outreach_markers(draft):
        return True, "Anvis outreach markers found"
    return False, "no Notion match or Anvis marker"


def _candidate_leads_from_indexes(
    draft: Dict[str, Any],
    indexes: Dict[str, Dict[str, List[Dict[str, Any]]]],
) -> Dict[str, List[Dict[str, Any]]]:
    draft_id = _draft_id(draft)
    thread_id = _draft_thread_id(draft)
    subject = _draft_subject(draft)
    body = _draft_body_text(draft)
    to_emails = _split_emails(_draft_to_header(draft))
    matches: Dict[str, List[Dict[str, Any]]] = {
        "email": [],
        "draft_id": [],
        "thread_id": [],
        "business_name": [],
    }

    seen: set[str] = set()

    def collect(key: str, items: Iterable[Dict[str, Any]]) -> None:
        for lead in items:
            lead_id = str(lead.get("id", "") or "").strip()
            if not lead_id or lead_id in seen:
                continue
            seen.add(lead_id)
            matches[key].append(lead)

    for email in to_emails:
        collect("email", indexes["email"].get(email, []))
    if draft_id:
        collect("draft_id", indexes["draft_id"].get(draft_id, []))
    if thread_id:
        collect("thread_id", indexes["thread_id"].get(thread_id, []))
    business_name = _draft_business_name(draft)
    if business_name:
        normalized = _normalize_text(business_name)
        collect("business_name", indexes["business_name"].get(normalized, []))
        short_normalized = _normalize_text(_short_business_name(business_name)) if business_name else ""
        if short_normalized:
            collect("business_name", indexes["business_name"].get(short_normalized, []))
    if not any(matches.values()) and any(marker in f"{subject}\n{body}".lower() for marker in OUTREACH_MARKERS):
        for email in to_emails:
            collect("email", indexes["email"].get(email, []))
    return matches


def _choose_lead_for_draft(
    draft: Dict[str, Any],
    indexes: Dict[str, Dict[str, List[Dict[str, Any]]]],
) -> Tuple[Optional[Dict[str, Any]], str]:
    matches = _candidate_leads_from_indexes(draft, indexes)
    priority = ("email", "draft_id", "thread_id", "business_name")

    for key in priority:
        candidates = matches.get(key, [])
        if not candidates:
            continue
        safe_candidates = [lead for lead in candidates if not _lead_safe_for_redraft(lead)]
        if len(safe_candidates) == 1:
            return safe_candidates[0], f"matched by {key}"
        if len(safe_candidates) > 1:
            return None, f"ambiguous {key} match"

    return None, "no safe Notion match"


def _existing_notion_id_updates(lead: Dict[str, Any], draft_id: str, thread_id: str) -> Dict[str, Any]:
    updates: Dict[str, Any] = {}
    properties = lead.get("properties", {})
    if draft_id:
        draft_flow._add_update_if_empty(  # type: ignore[attr-defined]
            updates,
            properties,
            lead,
            draft_flow.GMAIL_DRAFT_ID_CANDIDATES,  # type: ignore[attr-defined]
            draft_id,
        )
    if thread_id:
        draft_flow._add_update_if_empty(  # type: ignore[attr-defined]
            updates,
            properties,
            lead,
            draft_flow.GMAIL_THREAD_ID_CANDIDATES,  # type: ignore[attr-defined]
            thread_id,
        )
    return updates


def _update_notion_ids(lead: Dict[str, Any], draft_id: str, thread_id: str) -> None:
    updates = _existing_notion_id_updates(lead, draft_id, thread_id)
    if not updates:
        return
    if REDRAFT_DRY_RUN:
        print(f"DRY RUN: would update Notion IDs for {_lead_business_name(lead)} -> {list(updates.keys())}")
        return
    get_client().pages.update(page_id=lead["id"], properties=updates)


def _service_summary_for_redraft(lead: Dict[str, Any]) -> str:
    raw_services = _lead_services(lead)
    cleaned: List[str] = []
    seen: set[str] = set()

    for service in raw_services:
        lowered = service.lower()
        mapped = ""
        for key, phrase in SERVICE_PHRASE_MAP.items():
            if key in lowered:
                mapped = phrase
                break
        if not mapped:
            mapped = service
        key = mapped.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(mapped)

    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} and {cleaned[1]}"
    return ", ".join(cleaned[:-1]) + f", and {cleaned[-1]}"


def _indefinite_article(phrase: str) -> str:
    normalized = phrase.strip().lower()
    if not normalized:
        return "a"
    if normalized.startswith(("honest", "hour", "heir", "honor", "invisalign", "emergency", "implant", "orthodontic")):
        return "an"
    return "an" if normalized[0] in {"a", "e", "i", "o", "u"} else "a"


def _display_city(lead: Dict[str, Any]) -> str:
    city = _lead_city(lead).strip()
    if "," in city:
        city = city.split(",", 1)[0].strip()
    return city


def _build_redraft_subject(lead: Dict[str, Any]) -> str:
    business_name = _short_business_name(email_lead_business_name(lead))
    city = _display_city(lead)
    if city:
        if business_name.rstrip("’'\"").lower().endswith("s"):
            return f"Are patients in {city} seeing why {business_name} is worth choosing?"
        return f"Are patients in {city} seeing {business_name}'s strongest reasons to book?"
    if business_name.rstrip("’'\"").lower().endswith("s"):
        return f"Is {business_name} easy enough to choose online?"
    return f"Is {business_name}'s booking path clear enough?"


def _build_redraft_body(lead: Dict[str, Any]) -> str:
    business_name = escape(email_lead_business_name(lead))
    city = escape(_display_city(lead))
    service_summary = escape(_service_summary_for_redraft(lead))
    review_count = _lead_review_count(lead)
    rating = _lead_rating(lead)
    languages = _lead_languages(lead)

    strengths: List[str] = []
    if rating:
        strengths.append(f"a strong {escape(rating)}-star review profile")
    if review_count:
        strengths.append(f"{escape(review_count)} patient reviews")
    if languages:
        strengths.append(f"multilingual support in {escape(', '.join(languages))}")
    if service_summary:
        strengths.append(f"a wide service mix across {service_summary}")

    if strengths:
        if len(strengths) == 1:
            strength_text = strengths[0]
        elif len(strengths) == 2:
            strength_text = f"{strengths[0]} and {strengths[1]}"
        else:
            strength_text = ", ".join(strengths[:-1]) + f", and {strengths[-1]}"
        strength_sentence = f"The clinic has real strengths: {strength_text}. That is a lot to work with."
    else:
        strength_sentence = "There is still a solid base to work with."

    if city:
        gap_sentence = (
            f"The gap I noticed is that these strengths could be easier to scan and act on. "
            f"For patients comparing dentists in {city}, unclear service paths or booking steps can cost attention before someone ever books."
        )
        service_focus = "Invisalign dentist" if "invisalign" in service_summary.lower() else "family dentist"
        article = _indefinite_article(service_focus)
        search_sentence = (
            f"It also matters for how people search now. When someone asks Google, Maps, or AI tools for {article} {service_focus} or a {city} dental clinic, "
            "the clinic with the clearest service structure and trust signals has the advantage."
        )
    else:
        gap_sentence = "The gap I noticed is that these strengths could be easier to scan and act on."
        search_sentence = ""

    body_parts = [
        f"Hi {business_name} team,",
        f"I took a quick look at your website. {strength_sentence}",
        gap_sentence,
    ]
    if search_sentence:
        body_parts.append(search_sentence)
    body_parts.extend(
        [
            "I can send over a free website audit pointing out 3 to 5 things I would immediately improve around visibility, trust, and booking flow.",
            SIGNATURE_HTML,
        ]
    )

    return "\n".join(f"<p>{part}</p>" for part in body_parts)


def _regenerate_draft(lead: Dict[str, Any]) -> Dict[str, str]:
    subject = _build_redraft_subject(lead)
    body = _build_redraft_body(lead)
    validate_prospect_copy(subject, body)
    return {"subject": subject, "body": body}


def _summarize_draft(draft: Dict[str, Any]) -> str:
    subject = _draft_subject(draft) or "<no subject>"
    to_header = _draft_to_header(draft) or "<no recipient>"
    return f"{subject} | To: {to_header}"


def _expand_draft(draft: Dict[str, Any]) -> Dict[str, Any]:
    draft_id = _draft_id(draft)
    if not draft_id:
        return draft
    try:
        expanded = get_draft(draft_id)
    except Exception:
        return draft
    if "id" not in expanded:
        expanded["id"] = draft_id
    if "message" not in expanded and draft.get("message"):
        expanded["message"] = draft.get("message")
    return expanded


def main() -> None:
    leads = draft_flow.query_all_leads_for_debug()
    indexes = _build_notion_indexes(leads)
    verified_from_email = get_preferred_send_as_email(settings.gmail_send_as_email)
    if settings.gmail_send_as_email and not verified_from_email:
        print(
            f"Warning: Gmail send-as alias {settings.gmail_send_as_email} is not verified. "
            "Drafts will keep using the authenticated account in draft mode, and auto-send must remain blocked."
        )

    gmail_drafts = [_expand_draft(draft) for draft in list_drafts()]
    total_found = len(gmail_drafts)
    selected: List[Dict[str, Any]] = []
    diagnostics: List[str] = []
    for draft in gmail_drafts:
        candidate, reason = _draft_candidate_reason(draft, indexes)
        recipients = _split_emails(_draft_to_header(draft))
        recipient_in_notion = _recipient_in_notion(recipients, indexes)
        if len(diagnostics) < 10:
            diagnostics.append(
                f"- recipients: {', '.join(recipients) or '<none>'}; in Notion: {'yes' if recipient_in_notion else 'no'}; "
                f"candidate: {'yes' if candidate else 'no'}; reason: {reason}"
            )
        if candidate:
            selected.append(draft)

    selected = selected[:MAX_REDRAFTS_PER_RUN]

    summary = {
        "drafts_found": total_found,
        "candidate_drafts": len(selected),
        "matched": 0,
        "skipped_no_match": 0,
        "skipped_unsafe_status": 0,
        "updated": 0,
        "failed_validation": 0,
        "failed_gmail_update": 0,
        "notion_id_updates": 0,
    }

    print("Redraft run summary:")
    print(f"- dry run: {'yes' if REDRAFT_DRY_RUN else 'no'}")
    print(f"- max redrafts per run: {MAX_REDRAFTS_PER_RUN}")
    print(f"- Gmail drafts found: {total_found}")
    print(f"- candidate drafts selected: {len(selected)}")
    print("First 10 draft recipient diagnostics:")
    for line in diagnostics:
        print(line)

    for draft in selected:
        draft_id = _draft_id(draft)
        thread_id = _draft_thread_id(draft)
        subject = _draft_subject(draft)
        to_header = _draft_to_header(draft)
        cc_header = _draft_cc_header(draft)
        bcc_header = _draft_bcc_header(draft)
        in_reply_to = _draft_in_reply_to(draft)
        references = _draft_references(draft)

        lead, match_status = _choose_lead_for_draft(draft, indexes)
        if not lead:
            summary["skipped_no_match"] += 1
            print(f"SKIP | no match | {draft_id} | {subject or '<no subject>'} | {match_status}")
            continue

        safe_reasons = _lead_safe_for_redraft(lead)
        if safe_reasons:
            summary["skipped_unsafe_status"] += 1
            print(
                f"SKIP | unsafe status | {_lead_business_name(lead)} | "
                f"{'; '.join(safe_reasons)} | draft {draft_id or '<no id>'}"
            )
            continue

        try:
            regenerated = _regenerate_draft(lead)
        except Exception as exc:
            summary["failed_validation"] += 1
            print(f"FAIL | validation | {_lead_business_name(lead)} | draft {draft_id or '<no id>'} | {exc}")
            continue

        summary["matched"] += 1
        lead_name = _lead_business_name(lead)
        print(
            f"MATCHED | {lead_name} | draft {draft_id or '<no id>'} | "
            f"thread {thread_id or '<none>'} | to {to_header or '<none>'}"
        )
        print(f"- old subject: {subject or '<no subject>'}")
        print(f"- new subject: {regenerated['subject']}")

        if REDRAFT_DRY_RUN:
            print("- DRY RUN: would update Gmail draft body and preserve recipients/cc/bcc/thread headers")
            print(f"- DRY RUN: would reapply Gmail label '{settings.gmail_label}' after draft update")
            id_updates = _existing_notion_id_updates(lead, draft_id, thread_id)
            if id_updates:
                print(f"- DRY RUN: would update Notion IDs: {', '.join(id_updates.keys())}")
                summary["notion_id_updates"] += 1
            continue

        try:
            updated = update_draft(
                draft_id=draft_id,
                to_email=to_header,
                subject=regenerated["subject"],
                body=regenerated["body"],
                from_email=verified_from_email,
                cc=cc_header,
                bcc=bcc_header,
                in_reply_to=in_reply_to,
                references=references,
                thread_id=thread_id,
                label_name=settings.gmail_label,
            )
            summary["updated"] += 1
            print(f"UPDATED | draft {draft_id or '<no id>'} | Gmail draft updated")
            updated_message = updated.get("message", {}) or {}
            updated_thread_id = str(updated_message.get("threadId", "") or thread_id or "").strip()
            if draft_id or updated_thread_id:
                _update_notion_ids(lead, draft_id, updated_thread_id)
        except Exception as exc:
            summary["failed_gmail_update"] += 1
            print(f"FAIL | gmail update | {_lead_business_name(lead)} | draft {draft_id or '<no id>'} | {exc}")

    print("Redraft summary:")
    for key, value in summary.items():
        print(f"- {key}: {value}")


if __name__ == "__main__":
    main()
