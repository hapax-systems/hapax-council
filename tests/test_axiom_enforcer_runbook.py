"""Runbook pin for the axiom enforcer kill switch."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = REPO_ROOT / "docs" / "runbooks" / "axiom-enforcer-kill-switch.md"


def test_axiom_enforcer_kill_switch_runbook_exists() -> None:
    assert RUNBOOK.exists()


def test_axiom_enforcer_kill_switch_runbook_documents_off_on_and_audit_paths() -> None:
    body = RUNBOOK.read_text(encoding="utf-8")
    for required in (
        "AXIOM_ENFORCE_BLOCK=0",
        "AXIOM_ENFORCE_BLOCK=1",
        "profiles/.enforcement-audit.jsonl",
        "profiles/.quarantine",
        "systemctl --user edit",
        "systemctl --user revert",
    ):
        assert required in body
