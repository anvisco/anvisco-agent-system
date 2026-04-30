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


def copy_credentials(source: Path) -> None:
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, TARGET_FILE)


def main() -> None:
    candidates = find_candidates()

    if len(candidates) == 1:
        source = candidates[0]
        copy_credentials(source)
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
