from __future__ import annotations

import sys
import os

# Ensure the project root is importable when this script is run directly.
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from typing import Any, Dict, Optional

from src.config import settings
from src.gmail_client import build_draft_payload, create_draft, get_preferred_send_as_email, is_verified_send_as_alias
from src.notion_client import get_data_source_schema, query_database_by_practice_name
from src.safety import validate_prospect_copy


SUBJECT = "Is TEST Dental Clinic making it easy enough to choose you?"
BODY = """<p>Hello TEST Dental Clinic team,</p>

<p>I build websites that run, grow, and get discovered.</p>

    <p>You can check out some of my work here: <a href="https://anvisco.com">https://anvisco.com</a></p>

<p>This is a Gmail draft creation test.</p>

<p>If you're looking to improve how your website performs, I'd be happy to share how I'd approach it.</p>

<p>Warmly,<br>
Brian Nguyen<br>
Anvis | Websites built to run, grow, and get discovered<br>
<a href="https://forms.gle/tNPhqQRGYSWQvbZ99">Get a free website audit</a> | <a href="https://calendly.com/nducanhnguyenn/15-minute-discovery-call">Book a discovery call</a></p>
"""


def get_test_lead() -> Optional[Dict[str, Any]]:
    leads = query_database_by_practice_name("TEST Dental Clinic")
    return leads[0] if leads else None


def get_lead_email(lead: Dict[str, Any]) -> Optional[str]:
    properties = lead.get("properties", {})
    email_field = properties.get("Email")
    if not email_field:
        return None
    email = email_field.get("email")
    if email:
        return email
    rich_text = email_field.get("rich_text", [])
    if rich_text:
        return rich_text[0].get("plain_text")
    return None


def update_notion_after_draft(draft_id: str) -> None:
    from notion_client import Client

    client = Client(auth=settings.notion_api_key)
    lead = get_test_lead()
    if not lead:
        raise ValueError("Could not find the test lead in Notion.")
    page_id = lead["id"]
    schema = get_data_source_schema()
    properties = schema.get("properties", {})

    updates: Dict[str, Any] = {}
    if "Gmail Draft ID" in properties:
        updates["Gmail Draft ID"] = {"rich_text": [{"type": "text", "text": {"content": draft_id}}]}
    if "Lead Status" in properties:
        updates["Lead Status"] = {"select": {"name": "outreach_drafted"}}
    elif "Outreach Status" in properties:
        updates["Outreach Status"] = {"select": {"name": "draft_ready"}}

    if updates:
        client.pages.update(page_id=page_id, properties=updates)


def main() -> None:
    lead = get_test_lead()
    if not lead:
        print("No TEST Dental Clinic lead found.")
        return

    email = get_lead_email(lead)
    if not email:
        print("TEST Dental Clinic lead has no email.")
        return

    validate_prospect_copy(SUBJECT, BODY)
    verified_alias = get_preferred_send_as_email(settings.gmail_send_as_email)
    if verified_alias and is_verified_send_as_alias(verified_alias):
        print(f"Verified Gmail send-as alias available: {verified_alias}")
    elif settings.gmail_send_as_email:
        print(
            f"Warning: Gmail send-as alias not verified for {settings.gmail_send_as_email}. "
            "Draft creation will continue, but auto-send should remain blocked."
        )

    payload = build_draft_payload(email, SUBJECT, BODY, from_email=verified_alias)

    if settings.dry_run or not settings.create_gmail_drafts:
        print("DRY RUN: Gmail draft payload")
        print(payload)
        return

    draft = create_draft(email, SUBJECT, BODY, from_email=verified_alias, label_name=settings.gmail_label)
    draft_id = draft.get("id")
    print(f"Created Gmail draft: {draft_id}")

    if draft_id:
        update_notion_after_draft(draft_id)


if __name__ == "__main__":
    main()
