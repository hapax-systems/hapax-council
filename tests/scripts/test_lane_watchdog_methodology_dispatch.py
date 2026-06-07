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
    codex_send = home / "projects" / "hapax-council" / "scripts" / "hapax-codex-send"
    codex_send.parent.mkdir(parents=True)
    _write_executable(
        codex_send,
        """
        #!/usr/bin/env bash
        printf '%s\n' "$*" >> "${CODEX_SENT:?}"
        """,
    )

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "PATH": f"{bin_dir}:{env['PATH']}",
            "TMUX_SESSION": session,
            "TMUX_PANE": pane,
            "TMUX_SENT": str(tmp_path / "sent.txt"),
            "CODEX_SENT": str(tmp_path / "codex-sent.txt"),
            "HAPAX_IDLE_THRESHOLD_S": "0",
            "HAPAX_IDLE_COOLDOWN_S": "0",
            "HAPAX_IDLE_STATE_DIR": str(state_dir),
            "HAPAX_IDLE_SKIP_LANES": "",
            # This suite asserts nudge/relaunch behavior; pin the SDLC pressure
            # gate OPEN so it stays deterministic regardless of host CPU load.
            "HAPAX_SDLC_PRESSURE_GATE_OFF": "1",
            "HAPAX_LANE_WATCHDOG_COOLDOWN_DIR": str(tmp_path / "rate-state"),
            # Sandbox the headless runtime dir so the watchdog never reads the
            # host's real /run/user/<uid>/hapax-claude pipes/pidfiles.
            "HAPAX_HEADLESS_PIPE_DIR": str(tmp_path / "headless-run"),
        }
    )
    return env


def test_idle_watchdog_does_not_assign_offered_queue_work() -> None:
    text = IDLE_WATCHDOG.read_text(encoding="utf-8")
    assert "pick_next_offered" not in text
    assert "methodology_dispatch_prompt" not in text
    assert "--print-prompt" not in text
    assert "Await governed dispatch" in text
    assert "hapax-methodology-dispatch --launch" in text
    assert 'CODEX_SEND" --session "$lane" --require-ack' in text
    assert "do not self-select queue work" in text
    assert "claude --resume" not in text
    assert "codex --resume" not in text
    assert "SKIPPING missing Codex lane" in text
    assert "HAPAX_LOCAL_DEV_MAINTENANCE_MODE" in text
    assert "APPENDIX-ONLY skip nudge" in text
    assert "CC_CLAIM" not in text
    assert "Claimed task" not in text


def test_rate_limit_watchdog_holds_for_methodology_launch() -> None:
    text = RATE_LIMIT_WATCHDOG.read_text(encoding="utf-8")
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


def test_idle_watchdog_sends_await_dispatch_when_no_claim(tmp_path: Path) -> None:
    env = _base_env(
        tmp_path,
        session="hapax-codex-cx-red",
        pane="ready\ngpt-5.5 ~/projects/hapax-council",
    )

    result = subprocess.run([str(IDLE_WATCHDOG)], env=env, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    sent = Path(env["CODEX_SENT"]).read_text(encoding="utf-8")
    assert "Await governed dispatch" in sent
    assert "scripts/hapax-methodology-dispatch --task <id>" in sent
    assert "--require-ack" in sent
    assert "cc-claim" not in sent
    assert not Path(env["TMUX_SENT"]).exists()


def test_idle_watchdog_appendix_only_skips_unclaimed_local_nudge(tmp_path: Path) -> None:
    env = _base_env(
        tmp_path,
        session="hapax-codex-cx-red",
        pane="ready\ngpt-5.5 ~/projects/hapax-council",
    )
    env["HAPAX_LOCAL_DEV_MAINTENANCE_MODE"] = "appendix-only"

    result = subprocess.run([str(IDLE_WATCHDOG)], env=env, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert "APPENDIX-ONLY skip nudge hapax-codex-cx-red" in result.stdout
    assert "appendix-only suppressed 1 unclaimed local idle lane nudge(s)" in result.stdout
    assert not Path(env["CODEX_SENT"]).exists()
    assert not Path(env["TMUX_SENT"]).exists()


def test_idle_watchdog_appendix_only_preserves_active_task_resume_prompt(
    tmp_path: Path,
) -> None:
    env = _base_env(
        tmp_path,
        session="hapax-codex-cx-red",
        pane="ready\ngpt-5.5 ~/projects/hapax-council",
    )
    env["HAPAX_LOCAL_DEV_MAINTENANCE_MODE"] = "appendix-only"
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
    sent = Path(env["CODEX_SENT"]).read_text(encoding="utf-8")
    assert "active task: owned-task" in sent
    assert "--require-ack" in sent
    assert "APPENDIX-ONLY skip nudge" not in result.stdout


def test_idle_watchdog_appendix_only_disables_required_claude_launch(
    tmp_path: Path,
) -> None:
    env = _base_env(
        tmp_path,
        session="hapax-codex-cx-red",
        pane="ready\ngpt-5.5 ~/projects/hapax-council",
    )
    env["HAPAX_LOCAL_DEV_MAINTENANCE_MODE"] = "appendix-only"
    home = Path(env["HOME"])
    launcher = home / ".local" / "bin" / "hapax-claude"
    launcher.parent.mkdir(parents=True)
    launched = tmp_path / "claude-launched.txt"
    _write_executable(
        launcher,
        f"""
        #!/usr/bin/env bash
        printf '%s\n' "$*" >> "{launched}"
        """,
    )
    (home / "projects" / "hapax-council--beta").mkdir(parents=True)

    result = subprocess.run([str(IDLE_WATCHDOG)], env=env, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert "appendix-only local-dev maintenance" in result.stdout
    assert not launched.exists()


def test_idle_watchdog_does_not_dispatch_offered_task_from_idle_lane(tmp_path: Path) -> None:
    env = _base_env(
        tmp_path,
        session="hapax-codex-cx-red",
        pane="ready\ngpt-5.5 ~/projects/hapax-council",
    )
    task_dir = (
        Path(env["HOME"]) / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks" / "active"
    )
    task_dir.mkdir(parents=True)
    (task_dir / "dispatchable-task.md").write_text(
        "---\nstatus: offered\nassigned_to: unassigned\nwsjf: 20\n---\n# Task\n",
        encoding="utf-8",
    )
    dispatch_calls = tmp_path / "dispatch-calls.txt"
    bin_dir = Path(env["PATH"].split(":", 1)[0])
    _write_executable(
        bin_dir / "hapax-methodology-dispatch",
        f"""
        #!/usr/bin/env bash
        printf '%s\\n' "$*" >> "{dispatch_calls}"
        """,
    )

    result = subprocess.run([str(IDLE_WATCHDOG)], env=env, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    sent = Path(env["CODEX_SENT"]).read_text(encoding="utf-8")
    assert "SDLC GOVERNED DISPATCH." not in sent
    assert "Task: dispatchable-task" not in sent
    assert not dispatch_calls.exists()
    assert "Await governed dispatch" in sent
    assert "--require-ack" in sent
    assert "cc-claim" not in sent
    assert not Path(env["TMUX_SENT"]).exists()


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
    sent = Path(env["CODEX_SENT"]).read_text(encoding="utf-8")
    assert "active task: owned-task" in sent
    assert "--require-ack" in sent
    assert "Do not claim work from the pool" not in sent
    assert not Path(env["TMUX_SENT"]).exists()


def test_idle_watchdog_does_not_raw_tmux_fallback_when_codex_ack_fails(
    tmp_path: Path,
) -> None:
    env = _base_env(
        tmp_path,
        session="hapax-codex-cx-red",
        pane="ready\ngpt-5.5 ~/projects/hapax-council",
    )
    codex_send = Path(env["HOME"]) / "projects" / "hapax-council" / "scripts" / "hapax-codex-send"
    _write_executable(
        codex_send,
        """
        #!/usr/bin/env bash
        printf '%s\n' "$*" >> "${CODEX_SENT:?}"
        exit 1
        """,
    )

    result = subprocess.run([str(IDLE_WATCHDOG)], env=env, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert "--require-ack" in Path(env["CODEX_SENT"]).read_text(encoding="utf-8")
    assert "FAILED to dispatch hapax-codex-cx-red" in result.stdout
    assert not Path(env["TMUX_SENT"]).exists()


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


def test_rate_limit_watchdog_delegates_dead_lane_restart_to_supervisor() -> None:
    """FM-11 clean split (coordination-reform 2026-05-30, Phase 6): dead-lane
    liveness moved out of the rate-limit watchdog into the dedicated
    hapax-lane-supervisor. The watchdog no longer carries the task-gated,
    greek-only "leave dead" logic — a dead lane is ALWAYS respawned by the
    supervisor regardless of task presence (operator standing mandate).
    """
    text = RATE_LIMIT_WATCHDOG.read_text(encoding="utf-8")
    # The old leave-dead behaviour and its dead-lane block are gone.
    assert "DEAD with no active task" not in text
    assert "not restarting" not in text
    assert "Dead-lane auto-restart" not in text
    assert "EXPECTED_LANES" not in text

    # The supervisor exists and owns dead-lane respawn (asserted in detail by
    # tests/scripts/test_lane_supervisor.py).
    supervisor = REPO_ROOT / "scripts" / "hapax-lane-supervisor"
    assert supervisor.exists(), "hapax-lane-supervisor must own lane liveness"
    sup_text = supervisor.read_text(encoding="utf-8")
    assert "respawn" in sup_text
    assert "no active task" in sup_text  # the always-restart (idle-await) path
