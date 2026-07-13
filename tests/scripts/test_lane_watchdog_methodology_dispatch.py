"""Gate-0A effect-containment tests for the idle watchdog."""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WATCHDOG = REPO_ROOT / "scripts" / "hapax-lane-idle-watchdog"
TMUX_OBSERVER_LITERAL = (
    "TMUX_OBSERVER=(/usr/bin/env -i HOME=/nonexistent LANG=C.UTF-8 "
    "PATH=/usr/bin:/bin /usr/bin/tmux -f /dev/null)"
)


def _write_executable(path: Path, text: str) -> None:
    path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")
    path.chmod(0o755)


def _env(tmp_path: Path, *, sessions: str, pane: str, pane_cmd: str = "codex") -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "tmux",
        """
        #!/usr/bin/env bash
        command="$1"
        shift || true
        case "$command" in
          list-sessions)
            printf '%b' "${TMUX_SESSIONS:-}"
            ;;
          capture-pane)
            printf '%b\n' "${TMUX_PANE:-}"
            ;;
          display-message)
            printf '%s\n' "${TMUX_PANE_CMD:-unknown}"
            ;;
          send-keys|new-session|kill-session|respawn-pane)
            printf '%s %s\n' "$command" "$*" >> "${TMUX_MUTATIONS:?}"
            exit 99
            ;;
          *)
            printf 'unexpected tmux command: %s\n' "$command" >&2
            exit 98
            ;;
        esac
        """,
    )
    test_watchdog = tmp_path / "hapax-lane-idle-watchdog"
    test_watchdog.write_text(
        WATCHDOG.read_text(encoding="utf-8").replace(
            TMUX_OBSERVER_LITERAL,
            f"TMUX_OBSERVER=({bin_dir / 'tmux'})",
        ),
        encoding="utf-8",
    )
    test_watchdog.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "TMUX_SESSIONS": sessions,
            "TMUX_PANE": pane,
            "TMUX_PANE_CMD": pane_cmd,
            "TMUX_MUTATIONS": str(tmp_path / "tmux-mutations"),
            "HAPAX_IDLE_SKIP_LANES": "",
            "HAPAX_REQUIRED_CLAUDE_LANES": "",
            "HAPAX_REQUIRED_CODEX_LANES": "",
            "HAPAX_TEST_WATCHDOG": str(test_watchdog),
        }
    )
    return env


def _run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [env["HAPAX_TEST_WATCHDOG"], *args], env=env, capture_output=True, text=True
    )


def test_watchdog_source_has_no_effect_or_claim_selection_path() -> None:
    text = WATCHDOG.read_text(encoding="utf-8")
    forbidden = (
        "send-keys",
        "new-session",
        "kill-session",
        "hapax-claude-send",
        "hapax-codex-send",
        "hapax-alert",
        "curl ",
        "cc-claim",
        "find_claimed_task",
        "pick_next",
        "assigned_to",
        "platform_suitability",
        "TASK_ROOT",
        "REQUEST_ROOT",
        "mkdir ",
        "rm -f",
        "> $",
    )
    for token in forbidden:
        assert token not in text
    assert "HOLD effect_state=held_not_admitted" in text
    assert "execution_authority_admission_lease_absent" in text
    assert "effects=0" in text
    assert TMUX_OBSERVER_LITERAL in text


def test_watchdog_does_not_mint_boutique_carrier_schema() -> None:
    text = WATCHDOG.read_text(encoding="utf-8")
    assert "carrier" not in text.lower()
    assert "schema" not in text.lower()
    assert "may_authorize=false" in text


def test_watchdog_shell_syntax() -> None:
    result = subprocess.run(["bash", "-n", str(WATCHDOG)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_idle_codex_is_observed_and_nudge_candidate_holds(tmp_path: Path) -> None:
    env = _env(
        tmp_path,
        sessions="hapax-codex-cx-red\n",
        pane="ready\ngpt-5.5 ~/projects/hapax-council",
    )
    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert "OBSERVE support_only=true status=idle target=cx-red" in result.stdout
    assert "action=lane.nudge target=cx-red" in result.stdout
    assert "effect_state=held_not_admitted" in result.stdout
    assert "effects=0" in result.stdout
    assert not Path(env["TMUX_MUTATIONS"]).exists()


def test_active_codex_has_no_effect_candidate(tmp_path: Path) -> None:
    env = _env(
        tmp_path,
        sessions="hapax-codex-cx-red\n",
        pane="Working (12s)\ngpt-5.5 ~/projects/hapax-council",
    )
    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert "status=active_or_blocked target=cx-red" in result.stdout
    assert "action=lane.nudge" not in result.stdout
    assert not Path(env["TMUX_MUTATIONS"]).exists()


def test_context_full_claude_projects_clear_and_nudge_holds(tmp_path: Path) -> None:
    env = _env(
        tmp_path,
        sessions="hapax-claude-beta\n",
        pane="/clear to save\n❯ ",
        pane_cmd="node",
    )
    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert "action=lane.context.clear target=beta" in result.stdout
    assert "action=lane.nudge target=beta" in result.stdout
    assert not Path(env["TMUX_MUTATIONS"]).exists()


def test_missing_required_lanes_project_launch_holds_only(tmp_path: Path) -> None:
    env = _env(tmp_path, sessions="", pane="")
    env["HAPAX_REQUIRED_CLAUDE_LANES"] = "beta gamma"
    env["HAPAX_REQUIRED_CODEX_LANES"] = "cx-red"
    result = _run(env, "--check")
    assert result.returncode == 0, result.stderr
    assert "action=lane.launch target=beta" in result.stdout
    assert "action=lane.launch target=gamma" in result.stdout
    assert "action=lane.launch target=cx-red" in result.stdout
    assert result.stdout.count("effect_state=held_not_admitted") == 3
    assert not Path(env["TMUX_MUTATIONS"]).exists()


def test_hostile_pane_text_is_never_executed(tmp_path: Path) -> None:
    sentinel = tmp_path / "executed"
    env = _env(
        tmp_path,
        sessions="hapax-codex-cx-red\n",
        pane=f"$(touch {sentinel})\ngpt-5.5 ~/projects/hapax-council",
    )
    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert not sentinel.exists()
    assert not Path(env["TMUX_MUTATIONS"]).exists()


def test_skip_lane_is_observation_only(tmp_path: Path) -> None:
    env = _env(
        tmp_path,
        sessions="hapax-claude-alpha\n",
        pane="❯ ",
        pane_cmd="node",
    )
    env["HAPAX_IDLE_SKIP_LANES"] = "alpha"
    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert "status=skipped target=alpha" in result.stdout
    assert "action=lane.nudge" not in result.stdout


def test_unsupported_mode_fails_without_effect(tmp_path: Path) -> None:
    env = _env(tmp_path, sessions="", pane="")
    result = _run(env, "--launch")
    assert result.returncode == 2
    assert "unsupported mode" in result.stderr
    assert not Path(env["TMUX_MUTATIONS"]).exists()
