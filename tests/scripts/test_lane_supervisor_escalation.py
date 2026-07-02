"""Tests for hapax-lane-supervisor escalation + roster/worktree correctness.

Covers the FM-11 reform fix: a chronic respawn failure (e.g. codex rc=4 "not
found in PATH") and a rostered-but-missing worktree must ESCALATE via ntfy
instead of being logged-and-forgotten while the oneshot exits 0 every cycle.

The real script is driven as a subprocess with env overrides; the notification
is captured through HAPAX_SUPERVISOR_NOTIFY_CMD (a recorder stub) and codex is
faked through HAPAX_CODEX_BIN so we can force a rc and a respawn outcome.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "hapax-lane-supervisor"
LANE = "cx-supervisortest"


def _make_exec(path: Path, body: str) -> Path:
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(0o755)
    return path


def _base_env(tmp_path: Path, *, notify_record: Path, codex_rc: int) -> dict[str, str]:
    state = tmp_path / "state"
    worktrees = tmp_path / "worktrees"
    state.mkdir(exist_ok=True)
    worktrees.mkdir(exist_ok=True)
    codex_stub = _make_exec(tmp_path / "codex-stub.sh", f"exit {codex_rc}\n")
    notify_stub = _make_exec(
        tmp_path / "notify-stub.sh",
        f'printf "%s\\t%s\\n" "$1" "$2" >> "{notify_record}"\n',
    )
    env = dict(os.environ)
    env.update(
        HAPAX_SUPERVISOR_STATE_DIR=str(state),
        HAPAX_SUPERVISOR_WORKTREE_ROOT=str(worktrees),
        HAPAX_SUPERVISOR_VAULT_ROOT=str(tmp_path / "vault"),
        HAPAX_SUPERVISOR_CLAUDE_LANES="",
        HAPAX_SUPERVISOR_CODEX_LANES=LANE,
        HAPAX_SUPERVISOR_AGY_LANES="",
        HAPAX_SUPERVISOR_PROC_SCAN_LAUNCHERS="0",
        # Deterministic worktree presence: dir-check only, no git fallback.
        HAPAX_SUPERVISOR_GIT_WORKTREE_DETECT="0",
        HAPAX_SUPERVISOR_RESTART_COOLDOWN_S="0",
        HAPAX_SUPERVISOR_BURST_LIMIT="1000",
        HAPAX_SUPERVISOR_LAUNCH_TIMEOUT_S="10",
        HAPAX_SUPERVISOR_ESCALATE_REFIRE_S="3600",
        HAPAX_SUPERVISOR_NOTIFY_CMD=str(notify_stub),
        HAPAX_CODEX_BIN=str(codex_stub),
    )
    return env


def _run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60
    )


def _make_worktree(env: dict[str, str], lane: str = LANE) -> None:
    Path(env["HAPAX_SUPERVISOR_WORKTREE_ROOT"], f"hapax-council--{lane}").mkdir(
        parents=True, exist_ok=True
    )


def _notify_lines(record: Path) -> list[str]:
    if not record.exists():
        return []
    return [ln for ln in record.read_text().splitlines() if ln.strip()]


def test_respawn_failure_escalates_after_threshold(tmp_path: Path) -> None:
    record = tmp_path / "notify.log"
    env = _base_env(tmp_path, notify_record=record, codex_rc=4)
    env["HAPAX_SUPERVISOR_ESCALATE_RESPAWN_FAILS"] = "2"
    _make_worktree(env)  # present worktree so the sweep reaches the respawn path

    r1 = _run(env)
    assert r1.returncode == 0, r1.stderr
    assert _notify_lines(record) == [], "first failure is below threshold"

    _run(env)  # second consecutive failure crosses the threshold
    lines = _notify_lines(record)
    assert len(lines) == 1, f"expected one escalation, got {lines}"
    assert "respawn" in lines[0].lower()
    assert "rc=4" in lines[0]
    assert LANE in lines[0]

    _run(env)  # third failure is inside the re-fire window — no duplicate
    assert len(_notify_lines(record)) == 1, "must not re-escalate within refire window"


def test_respawn_failure_below_threshold_no_escalation(tmp_path: Path) -> None:
    record = tmp_path / "notify.log"
    env = _base_env(tmp_path, notify_record=record, codex_rc=4)
    env["HAPAX_SUPERVISOR_ESCALATE_RESPAWN_FAILS"] = "5"
    _make_worktree(env)
    _run(env)
    _run(env)
    assert _notify_lines(record) == []


def test_successful_respawn_does_not_escalate_and_resets(tmp_path: Path) -> None:
    record = tmp_path / "notify.log"
    env = _base_env(tmp_path, notify_record=record, codex_rc=4)
    env["HAPAX_SUPERVISOR_ESCALATE_RESPAWN_FAILS"] = "2"
    _make_worktree(env)

    _run(env)  # one failure: streak -> 1, below threshold 2
    streak = Path(env["HAPAX_SUPERVISOR_STATE_DIR"], f"{LANE}.respawn-fail-streak")
    assert streak.read_text().strip() == "1"

    ok_stub = _make_exec(tmp_path / "codex-ok.sh", "exit 0\n")
    env["HAPAX_CODEX_BIN"] = str(ok_stub)
    _run(env)  # success clears the streak and never escalates
    assert not streak.exists(), "a successful respawn must clear the failure streak"
    assert _notify_lines(record) == []


def test_missing_worktree_escalates_after_threshold(tmp_path: Path) -> None:
    record = tmp_path / "notify.log"
    env = _base_env(tmp_path, notify_record=record, codex_rc=0)
    env["HAPAX_SUPERVISOR_ESCALATE_MISSING_WORKTREE_CYCLES"] = "2"
    # No worktree created → lane_has_worktree() is false every cycle.

    r1 = _run(env)
    assert r1.returncode == 0, r1.stderr
    assert _notify_lines(record) == [], "first missing cycle is below threshold"

    _run(env)  # second missing cycle crosses the threshold
    lines = _notify_lines(record)
    assert len(lines) == 1, f"expected one escalation, got {lines}"
    assert "worktree" in lines[0].lower()
    assert LANE in lines[0]

    _run(env)  # third missing cycle is inside the re-fire window — no duplicate
    assert len(_notify_lines(record)) == 1, "must not re-escalate within refire window"


def test_missing_worktree_below_threshold_no_escalation(tmp_path: Path) -> None:
    record = tmp_path / "notify.log"
    env = _base_env(tmp_path, notify_record=record, codex_rc=0)
    env["HAPAX_SUPERVISOR_ESCALATE_MISSING_WORKTREE_CYCLES"] = "5"
    _run(env)
    _run(env)
    assert _notify_lines(record) == []


def test_present_worktree_clears_missing_streak(tmp_path: Path) -> None:
    record = tmp_path / "notify.log"
    env = _base_env(tmp_path, notify_record=record, codex_rc=0)
    env["HAPAX_SUPERVISOR_ESCALATE_MISSING_WORKTREE_CYCLES"] = "1"

    _run(env)  # missing cycle 1 escalates (threshold 1)
    assert len(_notify_lines(record)) == 1
    streak = Path(env["HAPAX_SUPERVISOR_STATE_DIR"], f"{LANE}.no-worktree-streak")
    assert streak.read_text().strip() == "1"

    _make_worktree(env)  # provision → next cycle clears the streak
    _run(env)
    assert not streak.exists(), "a present worktree must clear the missing-worktree streak"
    assert len(_notify_lines(record)) == 1, "no further escalation once provisioned"


def test_default_codex_agy_roster_is_empty(tmp_path: Path) -> None:
    """The stale phantom codex/agy defaults are retired (default empty)."""
    record = tmp_path / "notify.log"
    env = _base_env(tmp_path, notify_record=record, codex_rc=4)
    del env["HAPAX_SUPERVISOR_CODEX_LANES"]
    del env["HAPAX_SUPERVISOR_AGY_LANES"]
    env["HAPAX_SUPERVISOR_ESCALATE_RESPAWN_FAILS"] = "1"
    env["HAPAX_SUPERVISOR_ESCALATE_MISSING_WORKTREE_CYCLES"] = "1"

    r = _run(env)
    assert r.returncode == 0, r.stderr
    assert _notify_lines(record) == [], "an empty roster touches nothing"
    combined = r.stdout + r.stderr
    for phantom in (
        "cx-cpu-bridge",
        "cx-effect-drift-current",
        "cx-preset-storm",
        "cx-visual-bandwidth",
    ):
        assert phantom not in combined, f"retired phantom lane {phantom} resurfaced"
