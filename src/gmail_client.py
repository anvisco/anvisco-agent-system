from __future__ import annotations

import base64
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from src.config import settings


GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.readonly",
]


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
            scopes=GMAIL_SCOPES,
        )

    if settings.gmail_token_path:
        try:
            creds = Credentials.from_authorized_user_file(settings.gmail_token_path, GMAIL_SCOPES)
        except FileNotFoundError:
            pass

    if creds and creds.refresh_token and (creds.expired or not creds.valid):
        creds.refresh(Request())
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
        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), GMAIL_SCOPES)
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


def search_messages(query: str, max_results: int = 10) -> list[Dict[str, Any]]:
    service = get_gmail_service()
    response = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
    return list(response.get("messages", []))


def get_thread(thread_id: str) -> Dict[str, Any]:
    return get_gmail_service().users().threads().get(userId="me", id=thread_id, format="metadata").execute()


def build_draft_payload(to_email: str, subject: str, body: str) -> Dict[str, Any]:
    message = EmailMessage()
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)
    raw_bytes = message.as_bytes()
    raw = base64.urlsafe_b64encode(raw_bytes).decode("utf-8")
    return {"message": {"raw": raw}}


def create_draft(to_email: str, subject: str, body: str) -> Dict[str, Any]:
    service = get_gmail_service()
    payload = build_draft_payload(to_email, subject, body)
    return service.users().drafts().create(userId="me", body=payload).execute()
