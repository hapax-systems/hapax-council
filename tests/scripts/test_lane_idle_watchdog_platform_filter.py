"""Platform-bound read-only behavior for the idle watchdog."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "hapax-lane-idle-watchdog"
TMUX_OBSERVER_LITERAL = (
    "TMUX_OBSERVER=(/usr/bin/env -i HOME=/nonexistent LANG=C.UTF-8 "
    "PATH=/usr/bin:/bin /usr/bin/tmux -f /dev/null)"
)


def _fake_tmux(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    tmux = bin_dir / "tmux"
    tmux.write_text(
        """#!/usr/bin/env bash
case "$1" in
  list-sessions) printf '%b' "${SESSIONS:-}" ;;
  capture-pane) printf '%b\n' "${PANE:-}" ;;
  display-message) printf '%s\n' "${PANE_CMD:-unknown}" ;;
  *) printf '%s\n' "$*" >> "${MUTATIONS:?}"; exit 97 ;;
esac
""",
        encoding="utf-8",
    )
    tmux.chmod(0o755)
    test_script = tmp_path / "hapax-lane-idle-watchdog"
    test_script.write_text(
        SCRIPT.read_text(encoding="utf-8").replace(
            TMUX_OBSERVER_LITERAL,
            f"TMUX_OBSERVER=({tmux})",
        ),
        encoding="utf-8",
    )
    test_script.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "SESSIONS": "",
            "PANE": "",
            "PANE_CMD": "unknown",
            "MUTATIONS": str(tmp_path / "mutations"),
            "HAPAX_IDLE_SKIP_LANES": "",
            "HAPAX_REQUIRED_CLAUDE_LANES": "",
            "HAPAX_REQUIRED_CODEX_LANES": "",
            "HAPAX_TEST_WATCHDOG": str(test_script),
        }
    )
    return env


def _run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([env["HAPAX_TEST_WATCHDOG"]], env=env, capture_output=True, text=True)


def test_removed_task_picker_and_platform_suitability_authority() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert TMUX_OBSERVER_LITERAL in text
    for forbidden in (
        "find_next_wsjf_task",
        "platform_suitability",
        "highest_wsjf",
        "offered",
        "claimed",
        "in_progress",
        "assigned_to",
    ):
        assert forbidden not in text


def test_only_known_lane_platform_names_are_observed(tmp_path: Path) -> None:
    env = _fake_tmux(tmp_path)
    env["SESSIONS"] = "hapax-codex-cx-red\nunrelated-session\n"
    env["PANE"] = "ready\ngpt-5.5 ~/projects/hapax-council"
    env["PANE_CMD"] = "codex"
    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert "target=cx-red" in result.stdout
    assert "unrelated-session" not in result.stdout
    assert not Path(env["MUTATIONS"]).exists()


def test_claude_and_codex_share_same_fail_closed_hold_semantics(tmp_path: Path) -> None:
    env = _fake_tmux(tmp_path)
    env["SESSIONS"] = "hapax-claude-beta\nhapax-codex-cx-red\n"
    env["PANE"] = "❯ ready\ngpt-5.5 ~/projects/hapax-council"
    env["PANE_CMD"] = "node"
    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert "action=lane.nudge target=beta" in result.stdout
    assert "action=lane.nudge target=cx-red" in result.stdout
    assert result.stdout.count("reason=execution_authority_admission_lease_absent") == 2
    assert not Path(env["MUTATIONS"]).exists()


def test_existing_required_lane_is_not_a_launch_candidate(tmp_path: Path) -> None:
    env = _fake_tmux(tmp_path)
    env["SESSIONS"] = "hapax-codex-cx-red\n"
    env["PANE"] = "Working (3s)\ngpt-5.5 ~/projects/hapax-council"
    env["PANE_CMD"] = "codex"
    env["HAPAX_REQUIRED_CODEX_LANES"] = "cx-red"
    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert "action=lane.launch target=cx-red" not in result.stdout
    assert "action=lane.revive target=cx-red" not in result.stdout


def test_hostile_required_lane_name_cannot_escape_as_command(tmp_path: Path) -> None:
    env = _fake_tmux(tmp_path)
    sentinel = tmp_path / "must-not-exist"
    env["HAPAX_REQUIRED_CODEX_LANES"] = f"$(touch {sentinel})"
    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert "action=lane.launch" in result.stdout
    assert not sentinel.exists()
    assert not Path(env["MUTATIONS"]).exists()
