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
    # The installer refuses every root but the primary checkout, so the cutover must not invoke
    # it at all (review finding on #4622, round 3): the governed deploy installs the units.
    assert "install-units.sh" not in cutover.split("```bash", 1)[1].split("```", 1)[0]
    assert "hapax-source-activate" in cutover
    assert "cd ~/projects/hapax-council" not in cutover
    assert "HOLD" in cutover
    assert "$HOME/projects/hapax-council/scripts/hapax-backup-critical-offsite" not in runbook
    assert f"{ACTIVATION_ROOT}/scripts/hapax-backup-critical-offsite" in runbook


def test_the_watchdog_unit_this_change_touches_executes_from_the_activation_worktree() -> None:
    """Round four (all three families): the watchdog script changed in this PR, and its unit
    still ran the mutable checkout. Every unit a change touches follows the convention."""
    service = (REPO / "systemd" / "units" / "hapax-backup-watchdog.service").read_text(
        encoding="utf-8"
    )
    exec_start = _unit_value(service, "Service", "ExecStart") or ""
    assert exec_start == f"{ACTIVATION_ROOT}/scripts/hapax-backup-watchdog"
    assert _unit_value(service, "Service", "WorkingDirectory") == ACTIVATION_ROOT
    assert "projects" not in service


def test_the_llm_backup_unit_this_change_touches_executes_from_the_activation_worktree() -> None:
    """The compatibility receipt changed in this PR, so its live consumer must use the same
    governed source root as the critical off-site and watchdog consumers."""
    service = (REPO / "systemd" / "units" / "llm-backup.service").read_text(encoding="utf-8")
    exec_start = _unit_value(service, "Service", "ExecStart") or ""
    assert exec_start == f"{ACTIVATION_ROOT}/systemd/scripts/backup.sh"
    assert _unit_value(service, "Service", "WorkingDirectory") == ACTIVATION_ROOT
    assert "projects" not in service
