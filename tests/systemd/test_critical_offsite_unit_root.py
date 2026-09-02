"""The critical off-site backup unit must execute the governed activation worktree, never a
development checkout (three-family review finding on #4622): bytes unrelated to the activated SHA
must not be able to become the estate's off-site backup code."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SERVICE = REPO / "systemd" / "units" / "hapax-backup-critical-offsite.service"
RUNBOOK = REPO / "docs" / "runbooks" / "llm-stack-backup-reconciliation.md"
ACTIVATION_ROOT = "%h/.cache/hapax/source-activation/worktree"


def _unit_value(text: str, section: str, key: str) -> str | None:
    in_section = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_section = stripped == f"[{section}]"
            continue
        if in_section and "=" in stripped:
            unit_key, _, value = stripped.partition("=")
            if unit_key.strip() == key:
                return value.strip()
    return None


def test_critical_offsite_unit_executes_from_the_activation_worktree() -> None:
    service = SERVICE.read_text(encoding="utf-8")
    exec_start = _unit_value(service, "Service", "ExecStart") or ""
    assert exec_start == f"{ACTIVATION_ROOT}/scripts/hapax-backup-critical-offsite"
    assert _unit_value(service, "Service", "WorkingDirectory") == ACTIVATION_ROOT
    assert "projects" not in service, "a mutable development checkout is not a production root"


def test_runbook_cutover_installs_from_the_activation_worktree_and_names_the_hold() -> None:
    """The cutover must not link units from a development checkout, and it must say why podium's
    activation worktree does not advance on its own (the operator's HOLD ratify-line)."""
    runbook = RUNBOOK.read_text(encoding="utf-8")
    cutover = runbook.split("## Cutover on podium", 1)[1]
    assert (
        "cd ~/.cache/hapax/source-activation/worktree && systemd/scripts/install-units.sh"
        in cutover
    )
    assert "cd ~/projects/hapax-council" not in cutover
    assert "HOLD" in cutover
    assert "$HOME/projects/hapax-council/scripts/hapax-backup-critical-offsite" not in runbook
    assert f"{ACTIVATION_ROOT}/scripts/hapax-backup-critical-offsite" in runbook
