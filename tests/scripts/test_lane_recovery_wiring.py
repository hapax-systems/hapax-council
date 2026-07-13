"""The lane reaper is an inspection-only, visibly held recovery surface."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
REAPER = REPO / "scripts" / "hapax-lane-reaper"
GOVERNOR = REPO / "shared" / "recovery_governor.py"
TMUX_OBSERVER_LITERAL = (
    "TMUX_OBSERVER=(/usr/bin/env -i HOME=/nonexistent LANG=C.UTF-8 "
    "PATH=/usr/bin:/bin /usr/bin/tmux -f /dev/null)"
)


def _executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _stub_environment(tmp_path: Path, *, mode: str) -> tuple[dict[str, str], Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    effect_log = tmp_path / "git-calls.log"

    _executable(
        bin_dir / "tmux",
        """#!/usr/bin/env bash
case "$1" in
  list-sessions) printf 'hapax-codex-cx-hostile\\n' ;;
  list-panes) printf '999999\\n' ;;
  capture-pane)
    if [[ "${STUB_MODE:-dead}" == "stuck" ]]; then
      printf '429 quota Usage limit\\n'
    else
      printf 'shell prompt\\n'
    fi
    ;;
  display-message) printf '1\\n' ;;
esac
""",
    )
    test_reaper = tmp_path / "hapax-lane-reaper"
    test_reaper.write_text(
        REAPER.read_text(encoding="utf-8")
        .replace(
            TMUX_OBSERVER_LITERAL,
            f"TMUX_OBSERVER=({bin_dir / 'tmux'})",
        )
        .replace("/usr/bin/git", str(bin_dir / "git"))
        .replace("/usr/bin/ps", str(bin_dir / "ps")),
        encoding="utf-8",
    )
    test_reaper.chmod(0o755)
    _executable(
        bin_dir / "ps",
        """#!/usr/bin/env bash
if [[ "${STUB_MODE:-dead}" == "stuck" ]]; then
  printf 'node\\n'
fi
""",
    )
    _executable(
        bin_dir / "git",
        """#!/usr/bin/env bash
printf '%s\\n' "$*" >>"$EFFECT_LOG"
case "$*" in
  *status*--porcelain*) exit 0 ;;
  *symbolic-ref*) printf 'codex/hostile\\n' ;;
  *rev-list*) printf '0\\n' ;;
  *worktree*remove*) printf 'forbidden effect\\n' >&2; exit 99 ;;
esac
""",
    )

    home = tmp_path / "home"
    claim = home / ".cache" / "hapax" / "cc-active-task-cx-hostile"
    claim.parent.mkdir(parents=True)
    claim.write_text("cc-task-hostile\n", encoding="utf-8")
    council = tmp_path / "council"
    (tmp_path / "council--cx-hostile").mkdir()

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "HOME": str(home),
            "HAPAX_COUNCIL_DIR": str(council),
            "EFFECT_LOG": str(effect_log),
            "STUB_MODE": mode,
            "HAPAX_RECOVERY_GOVERNOR_OFF": "1",
            "HAPAX_TEST_REAPER": str(test_reaper),
        }
    )
    return env, claim, effect_log


def _run_reaper(tmp_path: Path, *, mode: str) -> tuple[subprocess.CompletedProcess, Path, Path]:
    env, claim, effect_log = _stub_environment(tmp_path, mode=mode)
    proc = subprocess.run(
        [env["HAPAX_TEST_REAPER"], "--threshold", "0"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return proc, claim, effect_log


def test_reaper_source_contains_no_effect_adapter() -> None:
    text = REAPER.read_text(encoding="utf-8")
    forbidden = (
        "sed -i",
        "rm -f",
        "worktree remove",
        "os.kill(",
        "kill-session",
        "curl -",
        "hapax-alert",
        "systemctl --user start",
        "mkdir -p",
        "recovery_governor --permit",
        "recovery_governor --record",
    )
    assert all(token not in text for token in forbidden)
    assert "HOLD lane=" in text
    assert "effects_executed=0" in text
    assert TMUX_OBSERVER_LITERAL in text


def test_governor_source_contains_no_effect_adapter() -> None:
    text = GOVERNOR.read_text(encoding="utf-8")
    forbidden = (
        ".write_text(",
        ".mkdir(",
        "os.kill(",
        "send_notification",
        "_mint_escalation_task",
        "subprocess.run(",
        "admission_state",
    )
    assert all(token not in text for token in forbidden)


def test_dead_lane_and_hostile_claim_are_inspected_but_unchanged(tmp_path: Path) -> None:
    proc, claim, effect_log = _run_reaper(tmp_path, mode="dead")

    assert proc.returncode == 0, proc.stderr
    assert "state=recovery-candidate" in proc.stderr
    assert "effect=release-task" in proc.stderr
    assert "effect=remove-worktree" in proc.stderr
    assert "effect=terminate-process" in proc.stderr
    assert "effects_executed=0" in proc.stderr
    assert claim.read_text(encoding="utf-8") == "cc-task-hostile\n"
    assert "worktree remove" not in effect_log.read_text(encoding="utf-8")
    assert not list(tmp_path.rglob("recovery-escalation-*.md"))


def test_quota_signal_cannot_release_task_or_notify(tmp_path: Path) -> None:
    proc, claim, _ = _run_reaper(tmp_path, mode="stuck")

    assert proc.returncode == 0, proc.stderr
    assert "state=quota-signal" in proc.stderr
    assert "effect=release-task" in proc.stderr
    assert "effect=notify" in proc.stderr
    assert "effects_executed=0" in proc.stderr
    assert claim.read_text(encoding="utf-8") == "cc-task-hostile\n"


def test_governor_cli_effect_requests_hold_even_with_bypass_env(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    env = os.environ.copy()
    env.update(
        {
            "HAPAX_RECOVERY_GOVERNOR_OFF": "1",
            "HAPAX_RECOVERY_GOVERNOR_MODE": "enforce",
            "HOME": str(tmp_path / "home"),
        }
    )
    proc = subprocess.run(
        [sys.executable, "-m", "shared.recovery_governor", "--permit", "lane:hostile"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == rg_backoff_exit_code()
    assert "HOLD" in proc.stderr
    assert not state_dir.exists()
    assert not (tmp_path / "home" / ".cache" / "hapax" / "recovery").exists()


def rg_backoff_exit_code() -> int:
    # Keep this wiring test independent of an in-process module singleton.
    return 75


def test_governor_state_read_is_still_available() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "shared.recovery_governor", "--state"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.stdout.strip() in {"open", "paced", "closed", "degraded"}
    assert proc.returncode in {0, 1, 2}
