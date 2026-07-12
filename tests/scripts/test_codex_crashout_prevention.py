"""Tests for Codex lane claim guards and projection-only claim diagnostics."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CC_CLAIM = REPO_ROOT / "scripts" / "cc-claim"
CC_TASK_GATE = REPO_ROOT / "hooks" / "scripts" / "cc-task-gate.impl.sh"
NO_STALE = REPO_ROOT / "hooks" / "scripts" / "no-stale-branches.sh"
FINDINGS_EXIT = 10
REFUSAL_EXIT = 2
CLAIM_AUDIT = REPO_ROOT / "scripts" / "codex-claim-audit"


def _task_root(home: Path) -> Path:
    root = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    (root / "active").mkdir(parents=True, exist_ok=True)
    (root / "closed").mkdir(parents=True, exist_ok=True)
    return root


def _write_task(
    home: Path,
    task_id: str,
    *,
    status: str = "offered",
    assigned_to: str = "unassigned",
    kind: str = "research",
) -> Path:
    path = _task_root(home) / "active" / f"{task_id}.md"
    path.write_text(
        f"""---
type: cc-task
task_id: {task_id}
title: "{task_id}"
status: {status}
assigned_to: {assigned_to}
kind: {kind}
depends_on: []
created_at: 2026-05-09T00:00:00Z
updated_at: 2026-05-09T00:00:00Z
claimed_at: null
pr: null
branch: null
---

# {task_id}

## Session log
""",
        encoding="utf-8",
    )
    return path


def _claim(home: Path, task_id: str, force: bool = False) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["HAPAX_AGENT_ROLE"] = "cx-test"
    env.pop("HAPAX_CC_TASK_GATE_OFF", None)
    cmd = ["bash", str(CC_CLAIM)]
    if force:
        cmd.append("--force")
    cmd.append(task_id)
    return subprocess.run(cmd, env=env, text=True, capture_output=True, check=False)


def _run_claim_audit(home: Path, *args: str, ps_text: str = "") -> subprocess.CompletedProcess[str]:
    ps_fixture = home / "claim-audit-ps.txt"
    ps_fixture.parent.mkdir(parents=True, exist_ok=True)
    ps_fixture.write_text(ps_text, encoding="utf-8")
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["HAPAX_CLAIM_AUDIT_PS_FIXTURE"] = str(ps_fixture)
    return subprocess.run(
        ["bash", str(CLAIM_AUDIT), *args],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _run_hook(
    script: Path, tool_name: str, command: str = "", home: str = "/tmp"
) -> subprocess.CompletedProcess[str]:
    payload = json.dumps({"tool_name": tool_name, "tool_input": {"command": command}})
    env = os.environ.copy()
    env["HOME"] = home
    env["HAPAX_AGENT_ROLE"] = "cx-test"
    env.pop("HAPAX_CC_TASK_GATE_OFF", None)
    env.pop("HAPAX_METHODOLOGY_EMERGENCY", None)
    return subprocess.run(
        ["bash", str(script)],
        input=payload,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_claim_blocks_when_active_task_exists(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(home, "task-a", status="offered")
    _write_task(home, "task-b", status="offered")
    first = _claim(home, "task-a")
    assert first.returncode == 0, first.stderr
    second = _claim(home, "task-b")
    assert second.returncode == 7
    assert "claim_slot_occupied" in second.stderr


def test_claim_force_cannot_override_multi_claim_block(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(home, "task-a", status="offered")
    _write_task(home, "task-b", status="offered")
    _claim(home, "task-a")
    second = _claim(home, "task-b", force=True)
    assert second.returncode == 8
    assert "ownership replacement is retired" in second.stderr


def test_terminal_task_status_does_not_detach_claim_ownership(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(home, "task-done", status="offered")
    _write_task(home, "task-new", status="offered")
    _claim(home, "task-done")
    note = _task_root(home) / "active" / "task-done.md"
    note.write_text(
        note.read_text(encoding="utf-8").replace("status: claimed", "status: done"),
        encoding="utf-8",
    )
    second = _claim(home, "task-new")
    assert second.returncode == 7
    assert "claim_slot_occupied" in second.stderr


def test_task_gate_recognizes_apply_patch(tmp_path: Path) -> None:
    result = _run_hook(CC_TASK_GATE, "apply_patch", home=str(tmp_path))
    assert result.returncode != 0


def test_task_gate_recognizes_exec_command_pty(tmp_path: Path) -> None:
    result = _run_hook(
        CC_TASK_GATE,
        "exec_command_pty",
        command="git commit -m 'test'",
        home=str(tmp_path),
    )
    assert result.returncode != 0


def test_task_gate_passes_read_only_exec_command_pty(tmp_path: Path) -> None:
    result = _run_hook(CC_TASK_GATE, "exec_command_pty", command="ls -la", home=str(tmp_path))
    assert result.returncode == 0, result.stderr


def test_no_stale_accepts_codex_shell_tools(tmp_path: Path) -> None:
    result = _run_hook(NO_STALE, "exec_command_pty", command="echo hello")
    assert result.returncode == 0


def test_no_stale_rejects_non_shell_tools() -> None:
    result = _run_hook(NO_STALE, "apply_patch")
    assert result.returncode == 0


def test_audit_detects_phantom_claim_without_mutation(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "phantom-task", status="claimed", assigned_to="cx-phantom")
    note.write_text(
        note.read_text(encoding="utf-8").replace(
            "claimed_at: null", "claimed_at: 2026-01-01T00:00:00Z"
        ),
        encoding="utf-8",
    )
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim = cache / "cc-active-task-cx-phantom"
    claim.write_text("phantom-task\n", encoding="utf-8")
    before = (note.read_bytes(), claim.read_bytes())

    result = _run_claim_audit(home, "--stale-hours=1")

    assert result.returncode == FINDINGS_EXIT
    assert "PHANTOM_CANDIDATE" in result.stdout
    assert (note.read_bytes(), claim.read_bytes()) == before


def test_audit_refuses_phantom_release_without_mutation(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "release-me", status="claimed", assigned_to="cx-stale")
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim = cache / "cc-active-task-cx-stale"
    claim.write_text("release-me\n", encoding="utf-8")
    before = (note.read_bytes(), claim.read_bytes())

    result = _run_claim_audit(home, "--release", "--stale-hours=1")

    assert result.returncode == REFUSAL_EXIT
    assert "REFUSED_EFFECT" in result.stderr
    assert (note.read_bytes(), claim.read_bytes()) == before


def test_audit_reports_quota_blocked_claim_from_receipt(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "quota-held", status="in_progress", assigned_to="alpha")
    cache = home / ".cache" / "hapax"
    claim = cache / "cc-active-task-alpha"
    claim.parent.mkdir(parents=True)
    claim.write_text("quota-held\n", encoding="utf-8")
    receipt_dir = cache / "relay" / "receipts"
    receipt_dir.mkdir(parents=True)
    resets_at = (datetime.now(UTC) + timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    receipt = receipt_dir / "alpha-quota-wall.yaml"
    receipt.write_text(f"status: quota_blocked\nresets_at: {resets_at}\n", encoding="utf-8")
    before = (note.read_bytes(), claim.read_bytes(), receipt.read_bytes())

    result = _run_claim_audit(home, "--stale-hours=999")

    assert result.returncode == FINDINGS_EXIT
    assert "QUOTA_BLOCKED" in result.stdout
    assert "quota-wall-receipt" in result.stdout
    assert (note.read_bytes(), claim.read_bytes(), receipt.read_bytes()) == before


def test_audit_refuses_quota_release_without_mutation(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "quota-release", status="in_progress", assigned_to="alpha")
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim = cache / "cc-active-task-alpha"
    claim.write_text("quota-release\n", encoding="utf-8")
    before = (note.read_bytes(), claim.read_bytes())

    result = _run_claim_audit(home, "--release", "--release-quota-blocked", "--stale-hours=999")

    assert result.returncode == REFUSAL_EXIT
    assert "REFUSED_EFFECT" in result.stderr
    assert (note.read_bytes(), claim.read_bytes()) == before


def test_audit_preserves_mismatched_claim_cache(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "expected-task", status="claimed", assigned_to="codex-stale")
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim = cache / "cc-active-task-codex-stale"
    claim.write_text("different-task\n", encoding="utf-8")
    before = (note.read_bytes(), claim.read_bytes())

    result = _run_claim_audit(home, "--stale-hours=999")

    assert result.returncode == FINDINGS_EXIT
    assert "CACHE_MISMATCH" in result.stdout
    assert "CACHE_STALE_CANDIDATE" in result.stdout
    assert (note.read_bytes(), claim.read_bytes()) == before


def test_audit_reports_terminal_cache_without_deleting_it(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "done-task", status="done", assigned_to="codex-done")
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim = cache / "cc-active-task-codex-done"
    claim.write_text("done-task\n", encoding="utf-8")
    before = (note.read_bytes(), claim.read_bytes())

    result = _run_claim_audit(home)

    assert result.returncode == FINDINGS_EXIT
    assert "CACHE_STALE_CANDIDATE" in result.stdout
    assert (note.read_bytes(), claim.read_bytes()) == before


def test_audit_reports_missing_claim_cache_in_read_only_mode(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(home, "missing-cache", status="in_progress", assigned_to="alpha")

    result = _run_claim_audit(home, "--stale-hours=999")

    assert result.returncode == FINDINGS_EXIT
    assert "CACHE_MISSING" in result.stdout
    assert "action=HOLD" in result.stdout


def test_audit_reports_stale_resumed_process_for_closed_task(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _task_root(home)
    ps_text = (
        "123 456 env CODEX_ROLE=codex-primary codex Resume governed task "
        "closed-task after session logout\n"
    )

    result = _run_claim_audit(home, "--stale-hours=999", ps_text=ps_text)

    assert result.returncode == FINDINGS_EXIT
    assert "PROCESS_TASK_NOT_ACTIVE" in result.stdout
    assert "task_state=missing" in result.stdout
