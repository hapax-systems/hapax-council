"""Tests for methodology-gated lane watchdog prompts."""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
IDLE_WATCHDOG = REPO_ROOT / "scripts" / "hapax-lane-idle-watchdog"
RATE_LIMIT_WATCHDOG = REPO_ROOT / "scripts" / "hapax-lane-rate-limit-watchdog"
WATCHDOG_SCRIPTS = (IDLE_WATCHDOG, RATE_LIMIT_WATCHDOG)
FORBIDDEN_GENERIC_PROMPTS = (
    "highest-WSJF",
    "highest WSJF",
    "Claim and start:",
    "Claim the highest",
    "claim the next",
    "claim next",
    "cc-claim <task_id>",
    "find the highest",
)


def _write_executable(path: Path, text: str) -> None:
    path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")
    path.chmod(0o755)


def _write_fake_tmux(bin_dir: Path) -> None:
    _write_executable(
        bin_dir / "tmux",
        """
        #!/usr/bin/env bash
        cmd="$1"
        shift || true
        case "$cmd" in
          list-sessions)
            printf '%s\n' "${TMUX_SESSION:?}"
            ;;
          capture-pane)
            printf '%s\n' "${TMUX_PANE:?}"
            ;;
          send-keys)
            printf '%s\n' "$*" >> "${TMUX_SENT:?}"
            ;;
          has-session)
            exit 1
            ;;
          *)
            exit 0
            ;;
        esac
        """,
    )


def _base_env(tmp_path: Path, *, session: str, pane: str) -> dict[str, str]:
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    state_dir = tmp_path / "idle-state"
    home.mkdir()
    bin_dir.mkdir()
    state_dir.mkdir()
    _write_fake_tmux(bin_dir)

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "PATH": f"{bin_dir}:{env['PATH']}",
            "TMUX_SESSION": session,
            "TMUX_PANE": pane,
            "TMUX_SENT": str(tmp_path / "sent.txt"),
            "HAPAX_IDLE_THRESHOLD_S": "0",
            "HAPAX_IDLE_COOLDOWN_S": "0",
            "HAPAX_IDLE_STATE_DIR": str(state_dir),
            "HAPAX_IDLE_SKIP_LANES": "",
            "HAPAX_LANE_WATCHDOG_COOLDOWN_DIR": str(tmp_path / "rate-state"),
        }
    )
    return env


def test_lane_watchdogs_hold_new_assignments_for_methodology_launch() -> None:
    for script in WATCHDOG_SCRIPTS:
        text = script.read_text(encoding="utf-8")
        assert "hapax-methodology-dispatch" in text
        assert "--launch" in text
        assert "Do not claim work from the pool" in text
        assert "--print-prompt" not in text


def test_lane_watchdogs_do_not_emit_generic_pool_claim_prompts() -> None:
    for script in WATCHDOG_SCRIPTS:
        text = script.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_GENERIC_PROMPTS:
            assert forbidden not in text


def test_lane_watchdog_shell_syntax() -> None:
    for script in WATCHDOG_SCRIPTS:
        result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr


def test_idle_watchdog_sends_hold_not_assignment_when_lane_has_no_task(tmp_path: Path) -> None:
    env = _base_env(
        tmp_path,
        session="hapax-codex-cx-red",
        pane="ready\ngpt-5.5 ~/projects/hapax-council",
    )

    result = subprocess.run([str(IDLE_WATCHDOG)], env=env, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    sent = Path(env["TMUX_SENT"]).read_text(encoding="utf-8")
    assert "Do not claim work from the pool" in sent
    assert "hapax-methodology-dispatch --launch" in sent
    assert "Task:" not in sent
    assert "cc-claim" not in sent


def test_idle_watchdog_preserves_active_task_resume_prompt(tmp_path: Path) -> None:
    env = _base_env(
        tmp_path,
        session="hapax-codex-cx-red",
        pane="ready\ngpt-5.5 ~/projects/hapax-council",
    )
    task_dir = (
        Path(env["HOME"]) / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks" / "active"
    )
    task_dir.mkdir(parents=True)
    (task_dir / "owned-task.md").write_text(
        "---\nstatus: claimed\nassigned_to: cx-red\n---\n# Owned\n",
        encoding="utf-8",
    )

    result = subprocess.run([str(IDLE_WATCHDOG)], env=env, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    sent = Path(env["TMUX_SENT"]).read_text(encoding="utf-8")
    assert "active task: owned-task" in sent
    assert "Do not claim work from the pool" not in sent


def test_rate_limit_watchdog_sends_hold_not_assignment_when_lane_has_no_task(
    tmp_path: Path,
) -> None:
    env = _base_env(
        tmp_path,
        session="hapax-claude-beta",
        pane="blocked\nbypass permissions on",
    )

    result = subprocess.run([str(RATE_LIMIT_WATCHDOG)], env=env, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    sent = Path(env["TMUX_SENT"]).read_text(encoding="utf-8")
    assert "Do not claim work from the pool" in sent
    assert "hapax-methodology-dispatch --launch" in sent
    assert "Task:" not in sent
    assert "cc-claim" not in sent
