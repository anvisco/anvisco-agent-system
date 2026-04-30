from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, List

from google_auth_oauthlib.flow import InstalledAppFlow

from src.config import settings


CLIENT_TYPES = ("installed", "web")
REQUIRED_CLIENT_KEYS = {"client_id", "client_secret", "auth_uri", "token_uri"}
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.readonly",
]
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOWNLOADS_DIR = Path.home() / "Downloads"
TARGET_DIR = PROJECT_ROOT / "credentials"
TARGET_FILE = TARGET_DIR / "gmail_credentials.json"
BACKUP_FILE = TARGET_DIR / "gmail_credentials_backup.json"
TOKEN_FILE = Path(settings.gmail_token_path) if settings.gmail_token_path else TARGET_DIR / "gmail_token.json"


def is_valid_google_oauth_file(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() != ".json":
        return False

    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print(f"Skipping invalid JSON candidate: {path}")
        return False

    if not isinstance(data, dict):
        print(f"Skipping invalid JSON candidate: {path}")
        return False

    return _has_oauth_desktop_client(data)


def _has_oauth_desktop_client(data: Any) -> bool:
    if not isinstance(data, dict):
        return False

    for client_type in CLIENT_TYPES:
        client = data.get(client_type)
        if isinstance(client, dict) and REQUIRED_CLIENT_KEYS.issubset(client.keys()):
            return True
    return False


def _load_valid_source(source: Path) -> bool:
    if not source.exists():
        print(f"Source path used: {source}")
        print("Source file does not exist.")
        return False

    if not source.is_file():
        print(f"Source path used: {source}")
        print("Source path is not a file.")
        return False

    try:
        data: Any = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Source path used: {source}")
        print(f"Source file is not valid JSON: {exc}")
        return False

    if not isinstance(data, dict):
        print(f"Source path used: {source}")
        print("Source file is not a Google OAuth Desktop App JSON file.")
        return False

    if not _has_oauth_desktop_client(data):
        print(f"Source path used: {source}")
        print("Source file is not a Google OAuth Desktop App JSON file.")
        return False

    return True


def find_candidates() -> List[Path]:
    search_roots = [PROJECT_ROOT, DOWNLOADS_DIR, TARGET_DIR]
    candidates: List[Path] = []
    seen: set[Path] = set()

    for root in search_roots:
        if not root.exists():
            continue
        for path in root.rglob("*.json"):
            if path in seen:
                continue
            seen.add(path)
            if is_valid_google_oauth_file(path):
                candidates.append(path)

    return candidates


def _backup_path() -> Path:
    if not BACKUP_FILE.exists():
        return BACKUP_FILE

    index = 1
    while True:
        backup = TARGET_DIR / f"gmail_credentials_backup_{index}.json"
        if not backup.exists():
            return backup
        index += 1


def copy_credentials(source: Path) -> bool:
    print(f"Source path used: {source}")
    print(f"Target exists: {'yes' if TARGET_FILE.exists() else 'no'}")

    if not _load_valid_source(source):
        print("Copied: no")
        print("Backup created: no")
        print("Download a Google OAuth Desktop App JSON file and place it at credentials/gmail_credentials.json")
        return False

    TARGET_DIR.mkdir(parents=True, exist_ok=True)

    if TARGET_FILE.exists() and source.resolve() == TARGET_FILE.resolve():
        print("Source and target are the same file; no copy needed")
        print("Copied: no")
        print("Backup created: no")
        return True

    backup_created = False
    if TARGET_FILE.exists():
        try:
            TARGET_FILE.rename(_backup_path())
            backup_created = True
            print("Renamed locked credentials file")
        except OSError as exc:
            print(f"Could not back up existing credentials file: {exc}")
            print("Close any app using credentials/gmail_credentials.json, then run this script again.")
            print("Copied: no")
            print("Backup created: no")
            return False

    shutil.copy2(source, TARGET_FILE)
    print("Copied new credentials file")
    print("Copied: yes")
    print(f"Backup created: {'yes' if backup_created else 'no'}")
    return True


def authenticate_gmail() -> bool:
    if TOKEN_FILE.exists():
        print("Token already exists")
        return True

    if not TARGET_FILE.is_file():
        print("Gmail credentials file is missing; skipping authentication")
        return False

    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    flow = InstalledAppFlow.from_client_secrets_file(str(TARGET_FILE), GMAIL_SCOPES)
    print("Opening browser for Gmail authentication...")
    creds = flow.run_local_server(port=0)
    print("Authentication successful")
    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    print("Token saved to credentials/gmail_token.json")
    return True


def main() -> None:
    candidates = find_candidates()

    if len(candidates) == 1:
        source = candidates[0]
        if copy_credentials(source):
            print(f"Copied Gmail OAuth credentials from {source} to {TARGET_FILE}")
            authenticate_gmail()
        return

    if len(candidates) > 1:
        print("Multiple valid Gmail OAuth credential files were found:")
        for candidate in candidates:
            print(f"- {candidate}")
        print("Choose one manually, then copy it to credentials/gmail_credentials.json")
        print("Copied: no")
        print("Backup created: no")
        return

    print("No valid Google OAuth Desktop credentials file was found.")
    print("Source path used: none")
    print(f"Target exists: {'yes' if TARGET_FILE.exists() else 'no'}")
    print("Copied: no")
    print("Backup created: no")
    print("Download a Google OAuth Desktop App JSON file and place it at credentials/gmail_credentials.json")


if __name__ == "__main__":
    main()
