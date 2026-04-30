from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict, List


REQUIRED_KEYS = {"installed", "client_id", "client_secret", "auth_uri", "token_uri"}
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOWNLOADS_DIR = Path.home() / "Downloads"
TARGET_DIR = PROJECT_ROOT / "credentials"
TARGET_FILE = TARGET_DIR / "gmail_credentials.json"
BACKUP_FILE = TARGET_DIR / "gmail_credentials_backup.json"


def is_valid_google_oauth_file(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() != ".json":
        return False

    try:
        data: Dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False

    if "installed" not in data:
        return False

    installed = data.get("installed")
    if not isinstance(installed, dict):
        return False

    return REQUIRED_KEYS.issubset({"installed", *installed.keys()})


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
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    if TARGET_FILE.exists():
        try:
            TARGET_FILE.unlink()
            print("Deleted existing credentials file")
        except OSError:
            try:
                TARGET_FILE.rename(_backup_path())
                print("Renamed locked credentials file")
            except OSError as exc:
                print(f"Could not replace locked credentials file: {exc}")
                print("Close any app using credentials/gmail_credentials.json, then run this script again.")
                return False
    shutil.copy2(source, TARGET_FILE)
    print("Copied new credentials file")
    return True


def main() -> None:
    candidates = find_candidates()

    if len(candidates) == 1:
        source = candidates[0]
        if copy_credentials(source):
            print(f"Copied Gmail OAuth credentials from {source} to {TARGET_FILE}")
        return

    if len(candidates) > 1:
        print("Multiple valid Gmail OAuth credential files were found:")
        for candidate in candidates:
            print(f"- {candidate}")
        print("Choose one manually, then copy it to credentials/gmail_credentials.json")
        return

    print("No valid Google OAuth Desktop credentials file was found.")
    print("Download OAuth Desktop App credentials from Google Cloud, then place the JSON at credentials/gmail_credentials.json")


if __name__ == "__main__":
    main()
