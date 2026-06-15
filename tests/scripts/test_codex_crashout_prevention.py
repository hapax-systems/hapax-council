"""Tests for the codex-lane-crashout-prevention fixes.

Covers:
  1. cc-claim multi-claim prevention (blocks claiming while active task exists)
  2. cc-task-gate recognizes Codex tool names (apply_patch, exec_command_pty)
  3. no-stale-branches recognizes Codex shell tool names
  4. codex-claim-audit detects phantom claims
"""

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CC_CLAIM = REPO_ROOT / "scripts" / "cc-claim"
# Gate logic lives in the impl behind the shim (reform FM-6); exec it directly.
CC_TASK_GATE = REPO_ROOT / "hooks" / "scripts" / "cc-task-gate.impl.sh"
NO_STALE = REPO_ROOT / "hooks" / "scripts" / "no-stale-branches.sh"
FINDINGS_EXIT = 10  # codex-claim-audit v2: findings exit code (distinct from crash)
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
    root = _task_root(home)
    path = root / "active" / f"{task_id}.md"
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


def _run_claim_audit(
    home: Path,
    *args: str,
    ps_text: str = "",
    gh_state: str = "CLOSED",
) -> subprocess.CompletedProcess[str]:
    ps_fixture = home / "claim-audit-ps.txt"
    ps_fixture.parent.mkdir(parents=True, exist_ok=True)
    ps_fixture.write_text(ps_text, encoding="utf-8")
    # Inject a gh stub so _gh_pr_is_open can produce deterministic results.
    # Default is CLOSED so pre-existing tests (which pre-date the fail-safe gh)
    # continue to release claims as before.
    gh_stub = home / "bin" / "gh"
    gh_stub.parent.mkdir(parents=True, exist_ok=True)
    gh_stub.write_text(
        f"#!/usr/bin/env bash\n"
        f'if [[ "$1" == "pr" && "$2" == "view" ]]; then echo \'{gh_state}\'; exit 0; fi\n'
        f'if [[ "$1" == "pr" && "$2" == "list" ]]; then echo \'\'; exit 0; fi\n'
        f"exit 1\n",
        encoding="utf-8",
    )
    gh_stub.chmod(0o755)
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["HAPAX_CLAIM_AUDIT_PS_FIXTURE"] = str(ps_fixture)
    env["HAPAX_GH_CMD"] = str(gh_stub)
    env["PATH"] = f"{gh_stub.parent}:{env.get('PATH', '/usr/bin:/bin')}"
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
    payload = json.dumps(
        {
            "tool_name": tool_name,
            "tool_input": {"command": command},
        }
    )
    env = os.environ.copy()
    env["HOME"] = home
    env["HAPAX_AGENT_ROLE"] = "cx-test"
    return subprocess.run(
        ["bash", str(script)],
        input=payload,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


# --- cc-claim multi-claim prevention ---


def test_claim_blocks_when_active_task_exists(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(home, "task-a", status="offered")
    _write_task(home, "task-b", status="offered")

    r1 = _claim(home, "task-a")
    assert r1.returncode == 0, r1.stderr

    r2 = _claim(home, "task-b")
    assert r2.returncode == 7, f"Expected exit 7, got {r2.returncode}: {r2.stderr}"
    assert "already has active task" in r2.stderr


def test_claim_force_overrides_multi_claim_block(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(home, "task-a", status="offered")
    _write_task(home, "task-b", status="offered")

    _claim(home, "task-a")
    r2 = _claim(home, "task-b", force=True)
    assert r2.returncode == 0, r2.stderr


def test_claim_allows_after_terminal_status(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(home, "task-done", status="offered")
    _write_task(home, "task-new", status="offered")

    _claim(home, "task-done")
    note = _task_root(home) / "active" / "task-done.md"
    text = note.read_text(encoding="utf-8")
    note.write_text(text.replace("status: claimed", "status: done"), encoding="utf-8")

    r2 = _claim(home, "task-new")
    assert r2.returncode == 0, r2.stderr


# --- cc-task-gate Codex tool name recognition ---


def test_task_gate_recognizes_apply_patch(tmp_path: Path) -> None:
    """apply_patch (Codex mutation tool) should be gated, not pass through."""
    r = _run_hook(CC_TASK_GATE, "apply_patch", home=str(tmp_path))
    assert r.returncode != 0, "apply_patch should be gated by cc-task-gate"


def test_task_gate_recognizes_exec_command_pty(tmp_path: Path) -> None:
    """exec_command_pty with destructive command should be gated."""
    r = _run_hook(
        CC_TASK_GATE,
        "exec_command_pty",
        command="git commit -m 'test'",
        home=str(tmp_path),
    )
    assert r.returncode != 0, "exec_command_pty with git commit should be gated"


def test_task_gate_passes_read_only_exec_command_pty(tmp_path: Path) -> None:
    """exec_command_pty with read-only command should pass through."""
    r = _run_hook(CC_TASK_GATE, "exec_command_pty", command="ls -la", home=str(tmp_path))
    assert r.returncode == 0, f"Read-only exec_command_pty should pass: {r.stderr}"


# --- no-stale-branches Codex tool name recognition ---


def test_no_stale_accepts_codex_shell_tools(tmp_path: Path) -> None:
    """exec_command_pty should be accepted as a shell tool (not exit early)."""
    r = _run_hook(NO_STALE, "exec_command_pty", command="echo hello")
    assert r.returncode == 0


def test_no_stale_rejects_non_shell_tools() -> None:
    """apply_patch is not a shell tool — no-stale-branches should exit 0 (pass through)."""
    r = _run_hook(NO_STALE, "apply_patch")
    assert r.returncode == 0


# --- codex-claim-audit ---


def test_audit_detects_phantom_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(
        home,
        "phantom-task",
        status="claimed",
        assigned_to="cx-phantom",
    )
    note = _task_root(home) / "active" / "phantom-task.md"
    text = note.read_text(encoding="utf-8")
    note.write_text(
        text.replace("claimed_at: null", "claimed_at: 2026-01-01T00:00:00Z"),
        encoding="utf-8",
    )

    r = _run_claim_audit(home, "--stale-hours=1")
    assert r.returncode == FINDINGS_EXIT
    assert "PHANTOM" in r.stdout
    assert "phantom-task" in r.stdout


def test_audit_releases_phantom_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(
        home,
        "release-me",
        status="claimed",
        assigned_to="cx-stale",
    )
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim_file = cache / "cc-active-task-cx-stale"
    claim_file.write_text("release-me\n", encoding="utf-8")
    text = note.read_text(encoding="utf-8")
    note.write_text(
        text.replace("claimed_at: null", "claimed_at: 2026-01-01T00:00:00Z"),
        encoding="utf-8",
    )

    r = _run_claim_audit(home, "--release", "--stale-hours=1")
    assert r.returncode == 0
    assert "CLEARED stale claim cache cc-active-task-cx-stale" in r.stdout
    assert not claim_file.exists()
    updated = note.read_text(encoding="utf-8")
    assert "status: offered" in updated
    assert "assigned_to: unassigned" in updated


def test_audit_reports_quota_blocked_claim_from_receipt(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(
        home,
        "quota-held",
        status="in_progress",
        assigned_to="alpha",
    )
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (cache / "cc-active-task-alpha").write_text("quota-held\n", encoding="utf-8")
    receipt_dir = cache / "relay" / "receipts"
    receipt_dir.mkdir(parents=True)
    resets_at = (datetime.now(UTC) + timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    (receipt_dir / "alpha-quota-wall.yaml").write_text(
        "\n".join(
            [
                "role: alpha",
                "status: quota_blocked",
                "detected_at: 2026-06-04T00:00:00Z",
                "signal_kind: rate_limit_event",
                f"resets_at: {resets_at}",
                "action: exit_clean_await_restart",
                "",
            ]
        ),
        encoding="utf-8",
    )

    r = _run_claim_audit(home, "--stale-hours=999")

    assert r.returncode == FINDINGS_EXIT
    assert "quota-blocked claim(s) found" in r.stdout
    assert "QUOTA_BLOCKED: quota-held assigned=alpha" in r.stdout
    assert "quota-wall-receipt:" in r.stdout


def test_audit_release_does_not_release_quota_blocked_without_explicit_flag(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    note = _write_task(
        home,
        "quota-held",
        status="in_progress",
        assigned_to="alpha",
    )
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim_file = cache / "cc-active-task-alpha"
    claim_file.write_text("quota-held\n", encoding="utf-8")
    receipt_dir = cache / "relay" / "receipts"
    receipt_dir.mkdir(parents=True)
    (receipt_dir / "alpha-quota-wall.yaml").write_text(
        "\n".join(
            [
                "role: alpha",
                "status: quota_blocked",
                "detected_at: 2026-06-04T00:00:00Z",
                "signal_kind: api_retry_429",
                "resets_at: unknown",
                "",
            ]
        ),
        encoding="utf-8",
    )

    r = _run_claim_audit(home, "--release", "--stale-hours=999")

    assert r.returncode == FINDINGS_EXIT
    assert "HELD: pass --release-quota-blocked" in r.stdout
    assert claim_file.exists()
    updated = note.read_text(encoding="utf-8")
    assert "status: in_progress" in updated
    assert "assigned_to: alpha" in updated


def test_audit_releases_quota_blocked_claim_and_preserves_pr_branch(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    note = _write_task(
        home,
        "quota-release",
        status="in_progress",
        assigned_to="alpha",
    )
    note.write_text(
        note.read_text(encoding="utf-8")
        .replace("pr: null", "pr: 3867")
        .replace("branch: null", "branch: alpha/audio-work"),
        encoding="utf-8",
    )
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim_file = cache / "cc-active-task-alpha"
    claim_file.write_text("quota-release\n", encoding="utf-8")
    receipt_dir = cache / "relay" / "receipts"
    receipt_dir.mkdir(parents=True)
    (receipt_dir / "alpha-quota-wall.yaml").write_text(
        "\n".join(
            [
                "role: alpha",
                "status: quota_blocked",
                "detected_at: 2026-06-04T00:00:00Z",
                "signal_kind: api_retry_429",
                "resets_at: unknown",
                "action: exit_clean_await_restart",
                "",
            ]
        ),
        encoding="utf-8",
    )

    r = _run_claim_audit(
        home,
        "--release",
        "--release-quota-blocked",
        "--stale-hours=999",
    )

    assert r.returncode == 0
    assert "RELEASED back to offered for governed redispatch" in r.stdout
    assert not claim_file.exists()
    updated = note.read_text(encoding="utf-8")
    assert "status: offered" in updated
    assert "assigned_to: unassigned" in updated
    assert "pr: 3867" in updated
    assert "branch: alpha/audio-work" in updated
    assert "released quota-blocked claim" in updated


def test_audit_reports_quota_blocked_claim_from_dispatch_ledger(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(
        home,
        "ledger-held",
        status="claimed",
        assigned_to="theta",
    )
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (cache / "cc-active-task-theta").write_text("ledger-held\n", encoding="utf-8")
    ledger_dir = cache / "orchestration"
    ledger_dir.mkdir(parents=True)
    timestamp = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    (ledger_dir / "methodology-dispatch.jsonl").write_text(
        json.dumps(
            {
                "timestamp": timestamp,
                "task_id": "ledger-held",
                "lane": "theta",
                "platform": "claude",
                "ok": False,
                "reason": "route policy hold: quota_telemetry_stale_or_unknown; claude.interactive.full: blocked: account_live_quota_receipt_absent",
                "route_policy_action": "hold",
                "route_policy_outcome": "hold",
                "route_policy_reason_codes": [
                    "quota_telemetry_stale_or_unknown",
                    "claude.interactive.full: blocked: account_live_quota_receipt_absent",
                ],
                "route_decision_id": "rd-test-quota",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    r = _run_claim_audit(home, "--stale-hours=999")

    assert r.returncode == FINDINGS_EXIT
    assert "QUOTA_BLOCKED: ledger-held assigned=theta" in r.stdout
    assert "methodology-dispatch:rd-test-quota" in r.stdout


def test_audit_reports_quota_blocked_claim_from_route_decision_ledger(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    _write_task(
        home,
        "route-held",
        status="claimed",
        assigned_to="alpha",
    )
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (cache / "cc-active-task-alpha").write_text("route-held\n", encoding="utf-8")
    ledger_dir = cache / "orchestration"
    ledger_dir.mkdir(parents=True)
    timestamp = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    (ledger_dir / "route-decisions.jsonl").write_text(
        json.dumps(
            {
                "created_at": timestamp,
                "task_id": "route-held",
                "lane": "alpha",
                "platform": "claude",
                "decision": "hold",
                "policy_outcome": "hold",
                "message": "claude.interactive.full: quota blocked: account_live_quota_receipt_absent",
                "reason_codes": [
                    "quota_telemetry_stale_or_unknown",
                    "claude.interactive.full: quota blocked: account_live_quota_receipt_absent",
                ],
                "decision_id": "rd-route-quota",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    r = _run_claim_audit(home, "--stale-hours=999")

    assert r.returncode == FINDINGS_EXIT
    assert "QUOTA_BLOCKED: route-held assigned=alpha" in r.stdout
    assert "route-decisions:rd-route-quota" in r.stdout


def test_audit_preserves_mismatched_claim_cache(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(
        home,
        "release-me",
        status="claimed",
        assigned_to="codex-stale",
    )
    live_note = _write_task(
        home,
        "different-task",
        status="claimed",
        assigned_to="codex-stale",
    )
    live_text = live_note.read_text(encoding="utf-8")
    live_note.write_text(live_text.replace("pr: null", "pr: 9999"), encoding="utf-8")
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim_file = cache / "cc-active-task-codex-stale"
    claim_file.write_text("different-task\n", encoding="utf-8")
    text = note.read_text(encoding="utf-8")
    note.write_text(
        text.replace("claimed_at: null", "claimed_at: 2026-01-01T00:00:00Z"),
        encoding="utf-8",
    )

    r = _run_claim_audit(home, "--release", "--stale-hours=1")
    assert r.returncode == FINDINGS_EXIT
    assert "KEPT claim cache cc-active-task-codex-stale" in r.stdout
    assert claim_file.read_text(encoding="utf-8") == "different-task\n"
    # v2: cache clear preflight fails on mismatch → note is NOT released.
    # The cache names "different-task" but the phantom is "release-me", so
    # _clear_claim_cache_for_release returns 1 and the note stays claimed.
    updated = note.read_text(encoding="utf-8")
    assert "status: claimed" in updated
    assert "HELD" in r.stdout or "claim release preflight failed" in r.stdout


def test_audit_release_clears_already_released_claim_cache(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(
        home,
        "already-released",
        status="offered",
        assigned_to="unassigned",
    )
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim_file = cache / "cc-active-task-codex-queue"
    claim_file.write_text("already-released\n", encoding="utf-8")

    r = _run_claim_audit(home, "--release", "--stale-hours=1")
    assert r.returncode == 0
    assert "CLEARED stale claim cache cc-active-task-codex-queue" in r.stdout
    assert "no phantom claims or claim/lane coherence issues found" in r.stdout
    assert not claim_file.exists()


def test_audit_release_clears_claim_cache_for_closed_task(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(
        home,
        "closed-task",
        status="done",
        assigned_to="codex-closed",
    )
    closed_note = _task_root(home) / "closed" / note.name
    note.replace(closed_note)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim_file = cache / "cc-active-task-codex-closed"
    claim_file.write_text("closed-task\n", encoding="utf-8")

    r = _run_claim_audit(home, "--release", "--stale-hours=1")
    assert r.returncode == 0
    assert "CLEARED stale claim cache cc-active-task-codex-closed" in r.stdout
    assert "status=not_active" in r.stdout
    assert not claim_file.exists()


def test_audit_reports_missing_claim_cache_in_read_only_mode(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(
        home,
        "missing-cache",
        status="in_progress",
        assigned_to="alpha",
    )

    r = _run_claim_audit(home, "--stale-hours=999")

    assert r.returncode == FINDINGS_EXIT
    assert "claim coherence issue" in r.stdout
    assert "CACHE_MISSING: missing-cache assigned=alpha" in r.stdout


def test_audit_reports_mismatched_claim_cache_in_read_only_mode(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(
        home,
        "expected-task",
        status="claimed",
        assigned_to="codex-mismatch",
    )
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (cache / "cc-active-task-codex-mismatch").write_text("other-task\n", encoding="utf-8")

    r = _run_claim_audit(home, "--stale-hours=999")

    assert r.returncode == FINDINGS_EXIT
    assert "CACHE_MISMATCH: expected-task assigned=codex-mismatch" in r.stdout
    assert "cache_task=other-task" in r.stdout


def test_audit_reports_stale_resumed_process_for_closed_task(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(
        home,
        "closed-task",
        status="done",
        assigned_to="codex-primary",
    )
    closed_note = _task_root(home) / "closed" / note.name
    note.replace(closed_note)
    ps_text = (
        "123 456 env CODEX_ROLE=codex-primary codex Resume governed task "
        "closed-task after session logout\n"
    )

    r = _run_claim_audit(home, "--stale-hours=999", ps_text=ps_text)

    assert r.returncode == FINDINGS_EXIT
    assert "live process coherence issue" in r.stdout
    assert "PROCESS_TASK_NOT_ACTIVE" in r.stdout
    assert "task_state=closed:done" in r.stdout


def test_audit_accepts_coherent_resumed_process(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(
        home,
        "live-task",
        status="claimed",
        assigned_to="codex-live",
    )
    text = note.read_text(encoding="utf-8")
    note.write_text(
        text.replace("claimed_at: null", "claimed_at: 2026-05-09T00:00:00Z"),
        encoding="utf-8",
    )
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (cache / "cc-active-task-codex-live").write_text("live-task\n", encoding="utf-8")
    ps_text = (
        "123 456 env CODEX_ROLE=codex-live codex Resume governed task "
        "live-task after session logout\n"
    )

    r = _run_claim_audit(home, "--stale-hours=99999", ps_text=ps_text)

    assert r.returncode == 0
    assert "no phantom claims or claim/lane coherence issues found" in r.stdout
