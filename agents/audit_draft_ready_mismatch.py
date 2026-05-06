from __future__ import annotations

import os
import sys
from collections import Counter
from typing import Any, Dict, List, Tuple

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agents import outreach_health_check as health


def _ops_ready_to_draft(lead: Dict[str, Any]) -> bool:
    return health._lead_ops_status(lead) == health.OPS_READY_TO_DRAFT_STATUS


def main() -> None:
    leads = health._load_leads()
    schema = health.get_data_source_schema()
    schema_properties = schema.get("properties", {})
    ops_status_exists = bool(health._first_existing(schema_properties, health.OPS_STATUS_CANDIDATES))

    raw_legacy_ready: List[Dict[str, Any]] = []
    mismatch_reasons: Counter[str] = Counter()
    mismatch_examples: List[Tuple[str, str]] = []

    for lead in leads:
        if health._draft_ready_reason(lead) is not None:
            continue
        raw_legacy_ready.append(lead)

        if ops_status_exists and _ops_ready_to_draft(lead):
            continue

        reason = health._legacy_draft_ready_mismatch_reason(lead, ops_status_exists=ops_status_exists)
        mismatch_reasons[reason or "<unknown>"] += 1
        if len(mismatch_examples) < 10:
            mismatch_examples.append((health._lead_name(lead), reason or "<unknown>"))

    print("Draft-ready mismatch audit")
    print(f"- records loaded: {len(leads)}")
    print(f"- raw legacy draft-ready count: {len(raw_legacy_ready)}")
    print(f"- ops_status_exists: {'yes' if ops_status_exists else 'no'}")
    print(f"- ops ready_to_draft count: {sum(1 for lead in leads if _ops_ready_to_draft(lead))}")
    print(f"- mismatch count: {sum(mismatch_reasons.values())}")
    print("Mismatch reasons")
    if mismatch_reasons:
        for reason, count in mismatch_reasons.most_common():
            print(f"- {reason}: {count}")
    else:
        print("- none")
    print("Example mismatches")
    if mismatch_examples:
        for name, reason in mismatch_examples:
            print(f"- {name}: {reason}")
    else:
        print("- none")


if __name__ == "__main__":
    main()
