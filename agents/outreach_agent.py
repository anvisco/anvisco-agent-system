from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PYTHON = sys.executable

_KEY_ENV_VARS = (
    "DRY_RUN",
    "SEND_DRY_RUN",
    "OPS_STATUS_DRY_RUN",
    "CREATE_GMAIL_DRAFTS",
    "SEND_APPROVED_DRAFTS",
    "MAX_SENDS_PER_RUN",
    "ALLOW_LEGACY_STATUS_FALLBACK",
)

_FULL_DRY_OVERRIDES: Dict[str, str] = {
    "DRY_RUN": "true",
    "SEND_DRY_RUN": "true",
    "OPS_STATUS_DRY_RUN": "true",
    "RECONCILE_DRY_RUN": "true",
    "CREATE_GMAIL_DRAFTS": "false",
    "AUTO_SEND_FIRST_EMAILS": "false",
    "SEND_APPROVED_DRAFTS": "false",
    "ALLOW_LEGACY_STATUS_FALLBACK": "false",
    "MAX_SENDS_PER_RUN": "unlimited",
}

# Safety invariants verified before full-cycle-dry-run executes any step.
_FULL_DRY_GUARDS: Dict[str, str] = {
    "SEND_DRY_RUN": "true",
    "CREATE_GMAIL_DRAFTS": "false",
    "SEND_APPROVED_DRAFTS": "false",
}


@dataclass
class Step:
    name: str
    cmd: List[str]
    critical: bool = True  # abort mode on non-zero exit; False = warn and continue


@dataclass
class StepResult:
    num: int
    name: str
    display_cmd: str
    exit_code: Optional[int]
    status: str  # ok / warning / failed / skipped


# ── Path helpers ──────────────────────────────────────────────────────────────

def _ap(*parts: str) -> str:
    return os.path.join(_ROOT, *parts)


def _display_cmd(cmd: List[str]) -> str:
    parts: List[str] = []
    for part in cmd:
        if part == _PYTHON:
            parts.append("python")
            continue
        try:
            rel = os.path.relpath(part, _ROOT).replace("\\", "/")
            parts.append(rel)
        except ValueError:
            parts.append(part)
    return " ".join(parts)


# ── Mode step tables ──────────────────────────────────────────────────────────

def _mode_weekly_intake() -> List[Step]:
    return [
        Step("run_lead_scraper",
             [_PYTHON, _ap("agents", "run_lead_scraper.py")],
             critical=True),
        Step("update_ops_status",
             [_PYTHON, _ap("agents", "update_outreach_ops_status.py")],
             critical=True),
        Step("generate_drafts_email1",
             [_PYTHON, _ap("agents", "generate_drafts_from_notion.py"), "--mode", "email1"],
             critical=True),
        Step("health_check",
             [_PYTHON, _ap("agents", "outreach_health_check.py")],
             critical=False),
    ]


def _mode_monday_send() -> List[Step]:
    return [
        Step("update_ops_status_pre",
             [_PYTHON, _ap("agents", "update_outreach_ops_status.py")],
             critical=True),
        Step("send_approved_drafts",
             [_PYTHON, _ap("agents", "send_approved_gmail_drafts.py")],
             critical=True),
        Step("update_ops_status_post",
             [_PYTHON, _ap("agents", "update_outreach_ops_status.py")],
             critical=True),
        Step("check_gmail_replies",
             [_PYTHON, _ap("agents", "check_gmail_replies.py")],
             critical=False),
        Step("health_check",
             [_PYTHON, _ap("agents", "outreach_health_check.py")],
             critical=False),
    ]


def _mode_draft_email1() -> List[Step]:
    return [
        Step("update_ops_status",
             [_PYTHON, _ap("agents", "update_outreach_ops_status.py")],
             critical=True),
        Step("generate_drafts_email1",
             [_PYTHON, _ap("agents", "generate_drafts_from_notion.py"), "--mode", "email1"],
             critical=True),
        Step("health_check",
             [_PYTHON, _ap("agents", "outreach_health_check.py")],
             critical=False),
    ]


def _mode_send_ready() -> List[Step]:
    return [
        Step("update_ops_status_pre",
             [_PYTHON, _ap("agents", "update_outreach_ops_status.py")],
             critical=True),
        Step("send_approved_drafts",
             [_PYTHON, _ap("agents", "send_approved_gmail_drafts.py")],
             critical=True),
        Step("update_ops_status_post",
             [_PYTHON, _ap("agents", "update_outreach_ops_status.py")],
             critical=True),
        Step("health_check",
             [_PYTHON, _ap("agents", "outreach_health_check.py")],
             critical=False),
    ]


def _mode_followup_check() -> List[Step]:
    return [
        Step("update_ops_status",
             [_PYTHON, _ap("agents", "update_outreach_ops_status.py")],
             critical=True),
        Step("health_check",
             [_PYTHON, _ap("agents", "outreach_health_check.py")],
             critical=False),
    ]


def _mode_draft_followups() -> List[Step]:
    return [
        Step("update_ops_status",
             [_PYTHON, _ap("agents", "update_outreach_ops_status.py")],
             critical=True),
        Step("generate_drafts_followups",
             [_PYTHON, _ap("agents", "generate_drafts_from_notion.py"), "--mode", "followups"],
             critical=True),
        Step("health_check",
             [_PYTHON, _ap("agents", "outreach_health_check.py")],
             critical=False),
    ]


def _mode_reconcile() -> List[Step]:
    return [
        Step("reconcile_drafts",
             [_PYTHON, _ap("agents", "reconcile_gmail_drafts_with_notion.py")],
             critical=True),
        Step("update_ops_status",
             [_PYTHON, _ap("agents", "update_outreach_ops_status.py")],
             critical=True),
        Step("health_check",
             [_PYTHON, _ap("agents", "outreach_health_check.py")],
             critical=False),
    ]


def _mode_replies() -> List[Step]:
    return [
        Step("check_gmail_replies",
             [_PYTHON, _ap("agents", "check_gmail_replies.py")],
             critical=True),
        Step("update_ops_status",
             [_PYTHON, _ap("agents", "update_outreach_ops_status.py")],
             critical=True),
        Step("health_check",
             [_PYTHON, _ap("agents", "outreach_health_check.py")],
             critical=False),
    ]


def _mode_health() -> List[Step]:
    return [
        Step("health_check",
             [_PYTHON, _ap("agents", "outreach_health_check.py")],
             critical=True),
    ]


def _mode_full_cycle_dry_run() -> List[Step]:
    return [
        Step("run_lead_scraper",
             [_PYTHON, _ap("agents", "run_lead_scraper.py")],
             critical=True),
        Step("update_ops_status",
             [_PYTHON, _ap("agents", "update_outreach_ops_status.py")],
             critical=True),
        Step("generate_drafts_email1",
             [_PYTHON, _ap("agents", "generate_drafts_from_notion.py"), "--mode", "email1"],
             critical=True),
        Step("send_approved_drafts",
             [_PYTHON, _ap("agents", "send_approved_gmail_drafts.py")],
             critical=True),
        Step("check_gmail_replies",
             [_PYTHON, _ap("agents", "check_gmail_replies.py")],
             critical=False),
        Step("health_check",
             [_PYTHON, _ap("agents", "outreach_health_check.py")],
             critical=False),
    ]


_MODES = {
    "weekly-intake":      _mode_weekly_intake,
    "monday-send":        _mode_monday_send,
    "draft-email1":       _mode_draft_email1,
    "send-ready":         _mode_send_ready,
    "followup-check":     _mode_followup_check,
    "draft-followups":    _mode_draft_followups,
    "reconcile":          _mode_reconcile,
    "replies":            _mode_replies,
    "health":             _mode_health,
    "full-cycle-dry-run": _mode_full_cycle_dry_run,
}


# ── Env builders ──────────────────────────────────────────────────────────────

def _env_weekly_intake() -> Dict[str, str]:
    env = os.environ.copy()
    env.setdefault("AUTO_SEND_FIRST_EMAILS", "false")
    env["ALLOW_LEGACY_STATUS_FALLBACK"] = "false"
    return env


def _env_monday_send() -> Dict[str, str]:
    env = os.environ.copy()
    if not env.get("MAX_SENDS_PER_RUN"):
        env["MAX_SENDS_PER_RUN"] = "unlimited"
    env["ALLOW_LEGACY_STATUS_FALLBACK"] = "false"
    return env


def _env_full_dry_run() -> Dict[str, str]:
    env = os.environ.copy()
    env.update(_FULL_DRY_OVERRIDES)
    return env


def _env_default() -> Dict[str, str]:
    env = os.environ.copy()
    env["ALLOW_LEGACY_STATUS_FALLBACK"] = "false"
    return env


def _build_env(mode: str) -> Dict[str, str]:
    if mode == "weekly-intake":
        return _env_weekly_intake()
    if mode == "monday-send":
        return _env_monday_send()
    if mode == "full-cycle-dry-run":
        return _env_full_dry_run()
    return _env_default()


# ── Safety guard ──────────────────────────────────────────────────────────────

def _verify_full_dry_run_env(env: Dict[str, str]) -> List[str]:
    violations: List[str] = []
    for var, expected in _FULL_DRY_GUARDS.items():
        actual = env.get(var, "").strip().lower()
        if actual != expected:
            violations.append(
                f"{var}={env.get(var, '<unset>')!r} (required {expected!r})"
            )
    return violations


# ── Output helpers ────────────────────────────────────────────────────────────

def _print_banner(mode: str, env: Dict[str, str], steps: List[Step]) -> None:
    sends_on = env.get("SEND_APPROVED_DRAFTS", "false").strip().lower() in {
        "1", "true", "yes", "on"
    }
    create_raw = env.get("CREATE_GMAIL_DRAFTS", "<unset>")
    # generate_drafts_from_notion defaults CREATE_GMAIL_DRAFTS to true when unset
    drafts_on_display = (
        "unset (true by default)"
        if create_raw == "<unset>"
        else create_raw
    )

    print("=" * 64)
    print("outreach_agent.py")
    print(f"  mode:                    {mode}")
    print(f"  workflow source:         Ops Status")
    print(f"  sends enabled:           {'yes' if sends_on else 'no'}")
    print(f"  draft creation:          {drafts_on_display}")
    print(f"  SEND_DRY_RUN:            {env.get('SEND_DRY_RUN', '<unset>')}")
    print(f"  CREATE_GMAIL_DRAFTS:     {create_raw}")
    print(f"  SEND_APPROVED_DRAFTS:    {env.get('SEND_APPROVED_DRAFTS', '<unset>')}")
    print(f"  MAX_SENDS_PER_RUN:       {env.get('MAX_SENDS_PER_RUN', '<unset>')}")
    print(f"  ALLOW_LEGACY_FALLBACK:   {env.get('ALLOW_LEGACY_STATUS_FALLBACK', '<unset>')}")
    print(f"  steps ({len(steps)}):")
    for i, step in enumerate(steps, 1):
        flag = "critical" if step.critical else "warn-only"
        print(f"    {i}. [{flag:9}] {step.name} - {_display_cmd(step.cmd)}")
    print("=" * 64)
    print()
    sys.stdout.flush()


def _print_step_header(num: int, step: Step, env: Dict[str, str]) -> None:
    flag = "CRITICAL" if step.critical else "warn-only"
    print(f"-- Step {num} [{flag}]: {step.name}")
    print(f"   cmd: {_display_cmd(step.cmd)}")
    for var in _KEY_ENV_VARS:
        print(f"   {var}={env.get(var, '<unset>')}")
    print()
    sys.stdout.flush()


def _print_summary(results: List[StepResult]) -> None:
    print()
    print("=" * 64)
    print("Step Summary")
    print(f"  {'#':<4} {'Step':<36} {'Exit':<6} Status")
    print("  " + "-" * 56)
    for r in results:
        exit_str = str(r.exit_code) if r.exit_code is not None else "-"
        print(f"  {r.num:<4} {r.name:<36} {exit_str:<6} {r.status}")
    print("=" * 64)


# ── Runner ────────────────────────────────────────────────────────────────────

def _run_step(num: int, step: Step, env: Dict[str, str]) -> StepResult:
    _print_step_header(num, step, env)
    proc = subprocess.run(step.cmd, env=env, cwd=_ROOT)
    code = proc.returncode
    if code == 0:
        status = "ok"
    elif step.critical:
        status = "failed"
    else:
        status = "warning"
    print(f"   exit {code} ({status})")
    return StepResult(num, step.name, _display_cmd(step.cmd), code, status)


def run_mode(mode: str) -> int:
    steps = _MODES[mode]()
    env = _build_env(mode)

    if mode == "full-cycle-dry-run":
        violations = _verify_full_dry_run_env(env)
        if violations:
            print("ERROR: full-cycle-dry-run safety guard failed.")
            print("The following env vars do not meet dry-run requirements:")
            for v in violations:
                print(f"  {v}")
            print("Aborting — no steps were run.")
            return 1

    _print_banner(mode, env, steps)

    results: List[StepResult] = []
    aborted = False
    final_code = 0

    for i, step in enumerate(steps, 1):
        if aborted:
            results.append(
                StepResult(i, step.name, _display_cmd(step.cmd), None, "skipped")
            )
            continue

        result = _run_step(i, step, env)
        results.append(result)

        if result.exit_code != 0:
            if step.critical:
                aborted = True
                final_code = result.exit_code
            else:
                if final_code == 0:
                    final_code = result.exit_code

    _print_summary(results)

    if aborted:
        failed = next((r for r in results if r.status == "failed"), None)
        name = failed.name if failed else "unknown"
        code = failed.exit_code if failed else final_code
        print(f"\nMode '{mode}' aborted: critical step '{name}' failed (exit {code}).")

    return final_code


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="outreach_agent.py",
        description=(
            "Anvis outreach command-center agent.\n"
            "Routes workflow modes to existing agent scripts via subprocess.\n"
            "Does not contain business logic."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=sorted(_MODES.keys()),
        metavar="MODE",
        help="Workflow mode to run. Choices: " + ", ".join(sorted(_MODES.keys())),
    )
    args = parser.parse_args()
    return run_mode(args.mode)


if __name__ == "__main__":
    sys.exit(main())
