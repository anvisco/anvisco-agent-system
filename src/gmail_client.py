from __future__ import annotations

import base64
import re
from email.message import EmailMessage
from email.utils import formataddr
from html import unescape
from pathlib import Path
from typing import Any, Dict, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError
from googleapiclient.discovery import build

from src.config import settings


SCOPES = [
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.settings.basic",
    "https://www.googleapis.com/auth/gmail.modify",
]

# Backward-compatible alias for older imports.
GMAIL_SCOPES = SCOPES


def _save_token(creds: Credentials) -> None:
    if not settings.gmail_token_path:
        raise ValueError("GMAIL_TOKEN_PATH is missing.")
    token_path = Path(settings.gmail_token_path)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")


def get_gmail_credentials() -> Credentials:
    creds: Optional[Credentials] = None

    if settings.gmail_client_id and settings.gmail_client_secret and settings.gmail_refresh_token:
        creds = Credentials(
            token=None,
            refresh_token=settings.gmail_refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.gmail_client_id,
            client_secret=settings.gmail_client_secret,
            scopes=SCOPES,
        )

    if settings.gmail_token_path:
        try:
            creds = Credentials.from_authorized_user_file(settings.gmail_token_path, SCOPES)
        except FileNotFoundError:
            pass

    if creds and creds.refresh_token and (creds.expired or not creds.valid):
        try:
            creds.refresh(Request())
        except RefreshError as exc:
            if settings.gmail_token_path and Path(settings.gmail_token_path).exists():
                raise RuntimeError(
                    "Gmail token refresh failed because the OAuth scopes are stale or invalid. "
                    "Delete gmail_token.json and re-authenticate Gmail so the new scopes are granted."
                ) from exc
            raise
    elif not creds or not creds.valid:
        if not settings.gmail_credentials_path:
            raise ValueError("GMAIL_CREDENTIALS_PATH is missing.")
        credentials_path = Path(settings.gmail_credentials_path)
        if not credentials_path.is_file():
            raise FileNotFoundError(
                "Gmail credentials file not found at credentials/gmail_credentials.json. "
                "Download OAuth Desktop credentials from Google Cloud, rename the file to gmail_credentials.json, "
                "and place it in the credentials/ folder."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
        print("Opening browser for Gmail authorization...")
        print("If the browser does not open, use the authorization URL printed below and paste it manually.")
        print("Waiting for authorization callback...")
        creds = flow.run_local_server(
            host="localhost",
            port=0,
            open_browser=True,
        )
        _save_token(creds)
        print("Gmail authorization completed.")

    if not creds:
        raise ValueError("Could not initialize Gmail credentials.")

    return creds


def get_gmail_service():
    creds = get_gmail_credentials()
    return build("gmail", "v1", credentials=creds)


def get_profile_email() -> str:
    profile = get_gmail_service().users().getProfile(userId="me").execute()
    return profile.get("emailAddress", "")


def get_send_as_aliases() -> list[Dict[str, Any]]:
    service = get_gmail_service()
    aliases: list[Dict[str, Any]] = []
    page_token: Optional[str] = None

    while True:
        request = service.users().settings().sendAs().list(userId="me")
        if page_token:
            request = request.pageToken(page_token)
        try:
            response = request.execute()
        except Exception as exc:
            print(f"Warning: Gmail send-as alias lookup failed: {exc}")
            return []

        aliases.extend(response.get("sendAs", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return aliases


def is_verified_send_as_alias(email: str) -> bool:
    preferred_email = email.strip().lower()
    if not preferred_email:
        return False
    for alias in get_send_as_aliases():
        alias_email = str(alias.get("sendAsEmail", "")).strip().lower()
        status = str(alias.get("verificationStatus", "")).strip().lower()
        if alias_email == preferred_email and status == "accepted":
            return True
    return False


def resolve_verified_send_as_email(preferred_email: str) -> str:
    preferred_email = preferred_email.strip().lower()
    if preferred_email and is_verified_send_as_alias(preferred_email):
        return preferred_email
    return ""


def get_preferred_send_as_email(preferred_email: str = "") -> str:
    email = preferred_email.strip().lower() if preferred_email else settings.gmail_send_as_email.strip().lower()
    return resolve_verified_send_as_email(email)


def search_messages(query: str, max_results: int = 10) -> list[Dict[str, Any]]:
    service = get_gmail_service()
    response = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
    return list(response.get("messages", []))


def list_drafts(max_results: int = 100) -> list[Dict[str, Any]]:
    service = get_gmail_service()
    drafts: list[Dict[str, Any]] = []
    page_token: Optional[str] = None

    while True:
        request = service.users().drafts().list(userId="me", maxResults=max_results)
        if page_token:
            request = request.pageToken(page_token)
        response = request.execute()
        drafts.extend(response.get("drafts", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return drafts


def get_thread(thread_id: str) -> Dict[str, Any]:
    return get_gmail_service().users().threads().get(userId="me", id=thread_id, format="metadata").execute()


def get_draft(draft_id: str) -> Dict[str, Any]:
    return get_gmail_service().users().drafts().get(userId="me", id=draft_id, format="full").execute()


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
    if mime_type in {"text/html", "text/plain"}:
        data = body.get("data", "")
        if data:
            return _decode_message_data(data)
    for part in payload.get("parts", []) or []:
        text = _extract_message_text(part)
        if text:
            return text
    data = body.get("data", "")
    if data:
        return _decode_message_data(data)
    return ""


def _extract_html_and_plain_body(payload: Dict[str, Any]) -> tuple[str, str]:
    html_body = ""
    plain_body = ""
    if not payload:
        return html_body, plain_body

    mime_type = str(payload.get("mimeType", "") or "").lower()
    body = payload.get("body", {}) or {}
    data = body.get("data", "")
    if mime_type == "text/html" and data:
        html_body = _decode_message_data(data)
    elif mime_type == "text/plain" and data:
        plain_body = _decode_message_data(data)

    for part in payload.get("parts", []) or []:
        part_html, part_plain = _extract_html_and_plain_body(part)
        if part_html and not html_body:
            html_body = part_html
        if part_plain and not plain_body:
            plain_body = part_plain
        if html_body and plain_body:
            break

    if not html_body and mime_type == "text/html" and data:
        html_body = _decode_message_data(data)
    if not plain_body and mime_type == "text/plain" and data:
        plain_body = _decode_message_data(data)
    return html_body, plain_body


def _message_label_ids(message: Dict[str, Any]) -> list[str]:
    label_ids = message.get("labelIds", []) or []
    return [str(label).strip() for label in label_ids if str(label).strip()]


def extract_draft_details(draft: Dict[str, Any]) -> Dict[str, Any]:
    message = draft.get("message", {}) or {}
    payload = message.get("payload", {}) or {}
    html_body, plain_body = _extract_html_and_plain_body(payload)
    extracted_body = html_body or plain_body or _extract_message_text(payload)
    label_ids = _message_label_ids(message)
    return {
        "draft_id": str(draft.get("id", "") or "").strip(),
        "message_id": str(message.get("id", "") or "").strip(),
        "thread_id": str(message.get("threadId", "") or "").strip(),
        "label_ids": label_ids,
        "to": _header_from_payload(payload, "To"),
        "from": _header_from_payload(payload, "From"),
        "cc": _header_from_payload(payload, "Cc"),
        "bcc": _header_from_payload(payload, "Bcc"),
        "subject": _header_from_payload(payload, "Subject"),
        "html_body": html_body,
        "plain_body": plain_body,
        "body": extracted_body,
    }


def _header_from_payload(payload: Dict[str, Any], name: str) -> str:
    for header in payload.get("headers", []):
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


def ensure_gmail_label(label_name: str) -> str:
    service = get_gmail_service()
    response = service.users().labels().list(userId="me").execute()
    for label in response.get("labels", []):
        if label.get("name") == label_name:
            return label.get("id", "")

    created = service.users().labels().create(
        userId="me",
        body={
            "name": label_name,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show",
        },
    ).execute()
    return created.get("id", "")


def _apply_label_to_draft_message(message_id: str, label_name: str) -> None:
    if not message_id or not label_name:
        return
    label_id = ensure_gmail_label(label_name)
    if not label_id:
        print(f"Warning: Gmail label '{label_name}' could not be created or found.")
        return

    service = get_gmail_service()
    try:
        service.users().messages().modify(
            userId="me",
            id=message_id,
            body={"addLabelIds": [label_id]},
        ).execute()
        print(f"Applied Gmail label '{label_name}' to draft message {message_id}.")
    except HttpError as exc:
        message = str(exc).lower()
        if "insufficient" in message or "403" in message:
            print(
                f"Warning: could not apply Gmail label '{label_name}' to draft message {message_id} "
                "(insufficient Gmail scope). Re-authenticate Gmail after deleting gmail_token.json."
            )
            return
        print(f"Warning: could not apply Gmail label '{label_name}' to draft message {message_id}: {exc}")
    except Exception as exc:
        print(f"Warning: could not apply Gmail label '{label_name}' to draft message {message_id}: {exc}")


def apply_label_to_message(message_id: str, label_name: str) -> None:
    if not message_id or not label_name:
        return
    label_id = ensure_gmail_label(label_name)
    if not label_id:
        print(f"Warning: Gmail label '{label_name}' could not be created or found.")
        return

    service = get_gmail_service()
    try:
        service.users().messages().modify(
            userId="me",
            id=message_id,
            body={"addLabelIds": [label_id]},
        ).execute()
        print(f"Applied Gmail label '{label_name}' to sent message {message_id}.")
    except HttpError as exc:
        message = str(exc).lower()
        if "insufficient" in message or "403" in message:
            print(
                f"Warning: could not apply Gmail label '{label_name}' to sent message {message_id} "
                "(insufficient Gmail scope). Re-authenticate Gmail after deleting gmail_token.json."
            )
            return
        print(f"Warning: could not apply Gmail label '{label_name}' to sent message {message_id}: {exc}")
    except Exception as exc:
        print(f"Warning: could not apply Gmail label '{label_name}' to sent message {message_id}: {exc}")


def _label_created_or_updated_draft(draft_id: str, label_name: str) -> None:
    if not draft_id or not label_name:
        return
    try:
        fresh_draft = get_draft(draft_id)
    except Exception as exc:
        print(f"Warning: could not fetch Gmail draft {draft_id} for label reapply: {exc}")
        return
    message_id = fresh_draft.get("message", {}).get("id", "")
    _apply_label_to_draft_message(message_id, label_name)


def _html_to_text(body: str) -> str:
    text = body.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    text = re.sub(r"</p\s*>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li>", "- ", text, flags=re.IGNORECASE)
    text = re.sub(r"</li>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return unescape(text).strip()


def _build_email_message(
    to_email: str,
    subject: str,
    body: str,
    from_email: str = "",
    cc: str = "",
    bcc: str = "",
    in_reply_to: str = "",
    references: str = "",
) -> EmailMessage:
    message = EmailMessage()
    message["To"] = to_email
    message["Subject"] = subject
    if from_email:
        message["From"] = formataddr(("Brian Nguyen", from_email))
    if cc:
        message["Cc"] = cc
    if bcc:
        message["Bcc"] = bcc
    if in_reply_to:
        message["In-Reply-To"] = in_reply_to
    if references:
        message["References"] = references
    message.set_content(_html_to_text(body))
    message.add_alternative(body, subtype="html")
    return message


def _raw_message(message: EmailMessage) -> str:
    raw_bytes = message.as_bytes()
    raw = base64.urlsafe_b64encode(raw_bytes).decode("utf-8")
    return raw


def build_draft_payload(
    to_email: str,
    subject: str,
    body: str,
    from_email: str = "",
    cc: str = "",
    bcc: str = "",
    in_reply_to: str = "",
    references: str = "",
    thread_id: str = "",
) -> Dict[str, Any]:
    message = _build_email_message(
        to_email,
        subject,
        body,
        from_email=from_email,
        cc=cc,
        bcc=bcc,
        in_reply_to=in_reply_to,
        references=references,
    )
    raw = _raw_message(message)
    payload: Dict[str, Any] = {"message": {"raw": raw}}
    if thread_id:
        payload["message"]["threadId"] = thread_id
    return payload


def build_send_payload(to_email: str, subject: str, body: str, from_email: str = "") -> Dict[str, Any]:
    message = _build_email_message(to_email, subject, body, from_email=from_email)
    raw = _raw_message(message)
    return {"raw": raw}


def _label_artifact(message_id: str, thread_id: str, label_name: str) -> None:
    if not label_name:
        return
    label_id = ensure_gmail_label(label_name)
    if not label_id:
        print(f"Warning: Gmail label '{label_name}' could not be created or found.")
        return

    service = get_gmail_service()
    try:
        if thread_id:
            service.users().threads().modify(
                userId="me",
                id=thread_id,
                body={"addLabelIds": [label_id]},
            ).execute()
            print(f"Applied Gmail label '{label_name}' to thread {thread_id}.")
            return
        if message_id:
            service.users().messages().modify(
                userId="me",
                id=message_id,
                body={"addLabelIds": [label_id]},
            ).execute()
            print(f"Applied Gmail label '{label_name}' to message {message_id}.")
    except Exception as exc:
        print(f"Warning: could not apply Gmail label '{label_name}': {exc}")


def create_draft(to_email: str, subject: str, body: str, from_email: str = "", label_name: str = "") -> Dict[str, Any]:
    service = get_gmail_service()
    payload = build_draft_payload(to_email, subject, body, from_email=from_email)
    draft = service.users().drafts().create(userId="me", body=payload).execute()
    if label_name:
        _label_created_or_updated_draft(draft.get("id", ""), label_name)
    return draft


def update_draft(
    draft_id: str,
    to_email: str,
    subject: str,
    body: str,
    from_email: str = "",
    cc: str = "",
    bcc: str = "",
    in_reply_to: str = "",
    references: str = "",
    thread_id: str = "",
    label_name: str = "",
) -> Dict[str, Any]:
    service = get_gmail_service()
    payload = build_draft_payload(
        to_email,
        subject,
        body,
        from_email=from_email,
        cc=cc,
        bcc=bcc,
        in_reply_to=in_reply_to,
        references=references,
        thread_id=thread_id,
    )
    draft = service.users().drafts().update(userId="me", id=draft_id, body=payload).execute()
    if label_name:
        _label_created_or_updated_draft(draft.get("id", ""), label_name)
    return draft


def send_email_message(to_email: str, subject: str, body: str, from_email: str = "", label_name: str = "") -> Dict[str, Any]:
    service = get_gmail_service()
    payload = build_send_payload(to_email, subject, body, from_email=from_email)
    sent = service.users().messages().send(userId="me", body=payload).execute()
    _label_artifact(sent.get("id", ""), sent.get("threadId", ""), label_name)
    return sent


def send_draft(draft_id: str) -> Dict[str, Any]:
    service = get_gmail_service()
    return service.users().drafts().send(userId="me", body={"id": draft_id}).execute()
