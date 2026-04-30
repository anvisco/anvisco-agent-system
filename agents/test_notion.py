from src.config import settings
from src.notion_client import create_test_lead, update_test_lead


def main() -> None:
    print(f"Running Notion test flow (DRY_RUN={settings.dry_run})")
    create_test_lead()
    update_test_lead()


if __name__ == "__main__":
    main()
