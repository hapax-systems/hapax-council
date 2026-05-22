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


def test_idle_watchdog_uses_methodology_dispatch_for_offered_queue() -> None:
    text = IDLE_WATCHDOG.read_text(encoding="utf-8")
    assert "pick_next_offered" in text
    assert "methodology_dispatch_prompt" in text
    assert "METHODOLOGY_DISPATCH" in text
    assert "--print-prompt" in text
    assert "FAILED to launch Codex lane" in text
    assert "CC_CLAIM" not in text
    assert "Claimed task" not in text
    assert "No offered tasks in queue" in text
    assert "is_dispatch_refused_cached" in text
    assert "cache_dispatch_refusal" in text
    assert "REFUSE_CACHE_TTL_S" in text


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


def test_idle_watchdog_sends_queue_empty_when_no_tasks_available(tmp_path: Path) -> None:
    env = _base_env(
        tmp_path,
        session="hapax-codex-cx-red",
        pane="ready\ngpt-5.5 ~/projects/hapax-council",
    )

    result = subprocess.run([str(IDLE_WATCHDOG)], env=env, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    sent = Path(env["TMUX_SENT"]).read_text(encoding="utf-8")
    assert "No offered tasks in queue" in sent
    assert "cc-claim" not in sent


def test_idle_watchdog_sends_governed_dispatch_packet_for_offered_task(tmp_path: Path) -> None:
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
    dispatcher = Path(env["HOME"]) / ".local" / "bin" / "hapax-methodology-dispatch"
    dispatcher.parent.mkdir(parents=True)
    dispatch_calls = tmp_path / "dispatch-calls.txt"
    _write_executable(
        dispatcher,
        f"""
        #!/usr/bin/env bash
        printf '%s\n' "$*" >> {dispatch_calls}
        printf '%s\n' "SDLC GOVERNED DISPATCH."
        printf '%s\n' "Task: dispatchable-task"
        printf '%s\n' "Lane: cx-red"
        """,
    )

    result = subprocess.run([str(IDLE_WATCHDOG)], env=env, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    sent = Path(env["TMUX_SENT"]).read_text(encoding="utf-8")
    calls = dispatch_calls.read_text(encoding="utf-8")
    assert "SDLC GOVERNED DISPATCH." in sent
    assert "Task: dispatchable-task" in sent
    assert "--task dispatchable-task --lane cx-red --platform codex" in calls
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


def test_idle_watchdog_skips_cached_refusal_and_dispatches_next(tmp_path: Path) -> None:
    env = _base_env(
        tmp_path,
        session="hapax-codex-cx-red",
        pane="ready\ngpt-5.5 ~/projects/hapax-council",
    )
    task_dir = (
        Path(env["HOME"]) / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks" / "active"
    )
    task_dir.mkdir(parents=True)
    (task_dir / "refused-task.md").write_text(
        "---\nstatus: offered\nassigned_to: unassigned\nwsjf: 99\n---\n# Refused\n",
        encoding="utf-8",
    )
    (task_dir / "fallback-task.md").write_text(
        "---\nstatus: offered\nassigned_to: unassigned\nwsjf: 5\n---\n# Fallback\n",
        encoding="utf-8",
    )

    state_dir = Path(env["HAPAX_IDLE_STATE_DIR"])
    import time

    cache_file = state_dir / "cx-red.refused-task.refused"
    cache_file.write_text(f"{int(time.time())}\nBLOCKED: route_not_mutable_for_runtime\n")

    dispatcher = Path(env["HOME"]) / ".local" / "bin" / "hapax-methodology-dispatch"
    dispatcher.parent.mkdir(parents=True)
    dispatch_calls = tmp_path / "dispatch-calls.txt"
    _write_executable(
        dispatcher,
        f"""
        #!/usr/bin/env bash
        printf '%s\n' "$*" >> {dispatch_calls}
        printf '%s\n' "SDLC GOVERNED DISPATCH."
        printf '%s\n' "Task: fallback-task"
        """,
    )

    result = subprocess.run([str(IDLE_WATCHDOG)], env=env, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    calls = dispatch_calls.read_text(encoding="utf-8")
    assert "fallback-task" in calls
    assert "refused-task" not in calls


def test_idle_watchdog_invalidates_refusal_cache_on_task_modification(tmp_path: Path) -> None:
    env = _base_env(
        tmp_path,
        session="hapax-codex-cx-red",
        pane="ready\ngpt-5.5 ~/projects/hapax-council",
    )
    task_dir = (
        Path(env["HOME"]) / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks" / "active"
    )
    task_dir.mkdir(parents=True)
    task_file = task_dir / "modified-task.md"
    task_file.write_text(
        "---\nstatus: offered\nassigned_to: unassigned\nwsjf: 20\n---\n# Modified\n",
        encoding="utf-8",
    )

    state_dir = Path(env["HAPAX_IDLE_STATE_DIR"])
    cache_file = state_dir / "cx-red.modified-task.refused"
    cache_file.write_text("1000000000\nBLOCKED: route_not_mutable\n")

    import time

    os.utime(task_file, (time.time(), time.time()))

    dispatcher = Path(env["HOME"]) / ".local" / "bin" / "hapax-methodology-dispatch"
    dispatcher.parent.mkdir(parents=True)
    dispatch_calls = tmp_path / "dispatch-calls.txt"
    _write_executable(
        dispatcher,
        f"""
        #!/usr/bin/env bash
        printf '%s\n' "$*" >> {dispatch_calls}
        printf '%s\n' "SDLC GOVERNED DISPATCH."
        """,
    )

    result = subprocess.run([str(IDLE_WATCHDOG)], env=env, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    calls = dispatch_calls.read_text(encoding="utf-8")
    assert "modified-task" in calls


def test_rate_limit_watchdog_does_not_restart_dead_lane_for_terminal_task(
    tmp_path: Path,
) -> None:
    env = _base_env(
        tmp_path,
        session="hapax-claude-alpha",
        pane="blocked\nbypass permissions on",
    )
    home = Path(env["HOME"])
    (home / "projects" / "hapax-council--beta").mkdir(parents=True)
    local_bin = home / ".local" / "bin"
    local_bin.mkdir(parents=True)
    headless_called = tmp_path / "headless-called.txt"
    _write_executable(
        local_bin / "hapax-claude-headless",
        f"""
        #!/usr/bin/env bash
        printf '%s\n' "$*" >> {headless_called}
        """,
    )
    task_dir = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks" / "active"
    task_dir.mkdir(parents=True)
    (task_dir / "terminal-task.md").write_text(
        "---\nstatus: done\nassigned_to: beta\ntitle: Terminal task\n---\n# Done\n",
        encoding="utf-8",
    )

    result = subprocess.run([str(RATE_LIMIT_WATCHDOG)], env=env, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert not headless_called.exists()
    assert "DEAD with no active task" in result.stdout
