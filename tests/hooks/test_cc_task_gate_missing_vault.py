"""Defect 3 of vault-nfs-mount-boot-race-and-gate-fail-closed-20261003: a MISSING
vault SUBSTRATE must fail OPEN with a loud alert (INV-5 — a blocked lane must still
think, take notes, and report), not fail-closed-stuck.

During the 2026-10-03 reboot the vault NFS mount lost the boot race; shadow writers
created `20-projects/hapax-cc-tasks/active/` and wrote 9 stray notes into it, so
"active/ absent or empty" was FALSE (seat disposition 2026-10-03T23:52Z). The gate
still could not find the CLAIMED task's note and failed closed
("claimed task ... not found in vault"), blocking the operator's repair.

Fix: distinguish an unmounted/absent vault from a genuinely-missing note by a
POSITIVE vault-identity marker that only the real vault carries and a shadow writer
never creates — the vault root's `.git` / `.obsidian`, resolved from the cc-tasks
root binding (no hard-coded home path). Missing marker => fail-open-with-alert;
marker present + note genuinely missing => still fail-closed.

Self-contained per project conventions (no shared conftest).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOKS_SRC = REPO_ROOT / "hooks" / "scripts"
_CLOSURE = (
    "cc-task-gate.impl.sh",
    "agent-role.sh",
    "escape-grant.sh",
    "cc-task-gate-bootstrap.py",
)
_IDENTITY_ENV = (
    "HAPAX_AGENT_ROLE",
    "HAPAX_AGENT_NAME",
    "HAPAX_WORKTREE_ROLE",
    "HAPAX_AGENT_SLOT",
    "HAPAX_SESSION_ID",
    "HAPAX_AGENT_INTERFACE",
    "CLAUDE_ROLE",
    "CLAUDE_CODE_SESSION_ID",
    "CODEX_ROLE",
    "CODEX_SESSION",
    "CODEX_SESSION_NAME",
    "CODEX_THREAD_ID",
    "CODEX_THREAD_NAME",
    "HAPAX_CC_TASK_GATE_OFF",
    "HAPAX_METHODOLOGY_EMERGENCY",
)


def _stage_gate(tmp_path: Path) -> Path:
    gate_dir = tmp_path / "gate"
    gate_dir.mkdir(parents=True, exist_ok=True)
    for name in _CLOSURE:
        shutil.copy2(HOOKS_SRC / name, gate_dir / name)
        (gate_dir / name).chmod(0o755)
    return gate_dir / "cc-task-gate.impl.sh"


def _run(
    gate_impl: Path, payload: dict, tmp_path: Path, *, role: str
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    for key in _IDENTITY_ENV:
        env.pop(key, None)
    env["HAPAX_AGENT_ROLE"] = role
    return subprocess.run(
        [str(gate_impl)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp_path),
        timeout=15,
        check=False,
    )


def _active(home: Path) -> Path:
    return home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks" / "active"


def _stray_note(active: Path, name: str) -> None:
    active.mkdir(parents=True, exist_ok=True)
    (active / f"{name}.md").write_text("---\ntype: cc-task\n---\n# stray\n")


def _vault_marker(home: Path) -> None:
    # The positive vault-identity marker a shadow writer never creates.
    (home / "Documents" / "Personal" / ".git").mkdir(parents=True, exist_ok=True)


def _claim(home: Path, role: str, task_id: str) -> None:
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / f"cc-active-task-{role}").write_text(task_id + "\n")


def _edit(path: str) -> dict:
    return {"tool_name": "Edit", "tool_input": {"file_path": path}}


def test_missing_vault_substrate_fails_open_with_alert(tmp_path: Path):
    """Shadow tree: active/ has stray notes but NOT the claimed task, and NO vault
    marker (the mount is gone) => fail OPEN with a loud alert, never fail-closed-stuck."""
    gate = _stage_gate(tmp_path)
    active = _active(tmp_path)
    # Reproduce the shadow: stray incident rows present, claimed note absent.
    _stray_note(active, "p0-incident-systemd-service-failed-x")
    _stray_note(active, "post-maintenance-recovery-20260902")
    _claim(tmp_path, "delta", "t1-claimed")
    # Deliberately NO _vault_marker(tmp_path): the real vault is not mounted.
    result = _run(gate, _edit("/tmp/x"), tmp_path, role="delta")
    assert result.returncode == 0, (
        f"a missing vault substrate must FAIL OPEN (INV-5), not block the repair; "
        f"rc={result.returncode} stderr={result.stderr}"
    )
    assert "vault" in result.stderr.lower() and (
        "fail" in result.stderr.lower() and "open" in result.stderr.lower()
    ), f"the fail-open must be loudly alerted; stderr={result.stderr}"


def test_present_vault_genuinely_missing_note_still_blocks(tmp_path: Path):
    """Real vault (marker present), claimed note genuinely absent => still fail-closed.
    Narrowness guard: the fix must not fail-open a mounted vault."""
    gate = _stage_gate(tmp_path)
    active = _active(tmp_path)
    _stray_note(active, "some-other-task-abc")
    _vault_marker(tmp_path)  # real vault identity present
    _claim(tmp_path, "delta", "t1-claimed")
    result = _run(gate, _edit("/tmp/x"), tmp_path, role="delta")
    assert result.returncode == 2, (
        f"a present vault with a genuinely-missing note must stay fail-closed; "
        f"rc={result.returncode} stderr={result.stderr}"
    )
    assert "not found in vault" in result.stderr.lower()
