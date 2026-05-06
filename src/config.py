import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: str | None, default: int = 0) -> int:
    if value is None or not value.strip():
        return default
    return int(value)


@dataclass(frozen=True)
class Settings:
    notion_api_key: str
    notion_database_id: str
    canada_city_queue_database_id: str
    city_queue_database_id: str
    gmail_credentials_path: str
    gmail_token_path: str
    gmail_client_id: str
    gmail_client_secret: str
    gmail_refresh_token: str
    gmail_send_as_email: str
    gmail_label: str
    send_mode: str
    auto_send_first_emails: bool
    require_admin_approval_for_send: bool
    dry_run: bool
    create_gmail_drafts: bool
    daily_lead_limit: int


settings = Settings(
    notion_api_key=os.getenv("NOTION_API_KEY", "").strip(),
    notion_database_id=os.getenv("NOTION_DATABASE_ID", "").strip(),
    canada_city_queue_database_id=os.getenv("CANADA_CITY_QUEUE_DATABASE_ID", "").strip(),
    city_queue_database_id=os.getenv("CITY_QUEUE_DATABASE_ID", "").strip(),
    gmail_credentials_path=os.getenv("GMAIL_CREDENTIALS_PATH", "").strip(),
    gmail_token_path=os.getenv("GMAIL_TOKEN_PATH", "").strip(),
    gmail_client_id=os.getenv("GMAIL_CLIENT_ID", "").strip(),
    gmail_client_secret=os.getenv("GMAIL_CLIENT_SECRET", "").strip(),
    gmail_refresh_token=os.getenv("GMAIL_REFRESH_TOKEN", "").strip(),
    gmail_send_as_email=os.getenv("GMAIL_SEND_AS_EMAIL", "brian@anvisco.com").strip(),
    gmail_label=os.getenv("GMAIL_LABEL", "Anvis/Leads").strip(),
    send_mode=(
        "auto_send_gated"
        if os.getenv("SEND_MODE", "auto_draft").strip().lower() == "auto_send"
        else os.getenv("SEND_MODE", "auto_draft").strip().lower()
    ),
    auto_send_first_emails=_as_bool(os.getenv("AUTO_SEND_FIRST_EMAILS"), default=False),
    require_admin_approval_for_send=_as_bool(os.getenv("REQUIRE_ADMIN_APPROVAL_FOR_SEND"), default=True),
    dry_run=_as_bool(os.getenv("DRY_RUN"), default=True),
    create_gmail_drafts=_as_bool(os.getenv("CREATE_GMAIL_DRAFTS"), default=True),
    daily_lead_limit=_as_int(os.getenv("DAILY_LEAD_LIMIT"), default=25),
)
