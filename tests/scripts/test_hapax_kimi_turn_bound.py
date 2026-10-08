"""Per-role turn-bound wiring for the hapax-kimi launcher."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-kimi"


def _make_executable(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _fake_kimi(bin_dir: Path, capture: Path) -> None:
    _make_executable(
        bin_dir / "kimi",
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"${KIMI_LOOP_MAX_STEPS_PER_TURN-__unset__}\" "
        '"$HAPAX_AGENT_ROLE" "$@" > "$HAPAX_FAKE_KIMI_CAPTURE"\n',
    )
    capture.parent.mkdir(parents=True, exist_ok=True)
    capture.write_text("", encoding="utf-8")


def _fake_tmux(bin_dir: Path, capture: Path) -> None:
    _make_executable(
        bin_dir / "tmux",
        "#!/usr/bin/env bash\n"
        'if [ "$1" = has-session ]; then exit 1; fi\n'
        'printf \'%s\\n\' "$@" > "$HAPAX_FAKE_TMUX_CAPTURE"\n',
    )
    capture.parent.mkdir(parents=True, exist_ok=True)
    capture.write_text("", encoding="utf-8")


def _run(
    tmp_path: Path,
    role: str,
    *,
    bounds_file: Path | None = None,
    terminal_none: bool = True,
    args: tuple[str, ...] = (),
) -> tuple[subprocess.CompletedProcess[str], Path, Path | None, Path]:
    """Run the launcher against private fake kimi/tmux binaries."""

    run_root = tmp_path / f"run-{uuid4().hex}"
    run_root.mkdir()
    bin_dir = run_root / "bin"
    bin_dir.mkdir(exist_ok=True)
    kimi_capture = run_root / "kimi-capture.txt"
    tmux_capture = run_root / "tmux-capture.txt"
    _fake_kimi(bin_dir, kimi_capture)
    _fake_tmux(bin_dir, tmux_capture)

    home = run_root / "home"
    home.mkdir(exist_ok=True)
    (home / ".cache" / "hapax").mkdir(parents=True, exist_ok=True)
    work = run_root / "work"
    work.mkdir(exist_ok=True)
    spawn_dir = home / ".cache" / "hapax" / "kimi-spawns"
    env = {
        **os.environ,
        "HOME": str(home),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "KIMI_BIN": str(bin_dir / "kimi"),
        "HAPAX_KIMI_WORKDIR": str(work),
        "HAPAX_COUNCIL_DIR": str(tmp_path / "council"),
        "HAPAX_FAKE_KIMI_CAPTURE": str(kimi_capture),
        "HAPAX_FAKE_TMUX_CAPTURE": str(tmux_capture),
    }
    env.pop("KIMI_LOOP_MAX_STEPS_PER_TURN", None)
    if bounds_file is not None:
        env["HAPAX_KIMI_TURN_BOUNDS_FILE"] = str(bounds_file)
    else:
        env["HAPAX_KIMI_TURN_BOUNDS_FILE"] = str(home / ".config" / "missing.conf")

    command = [str(SCRIPT), role, *args]
    if terminal_none:
        command += ["--terminal", "none"]
    result = subprocess.run(
        command,
        cwd=run_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    return result, kimi_capture, tmux_capture, spawn_dir


def _kimi_record(capture: Path) -> list[str]:
    return capture.read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize(
    ("role", "bound"),
    [("kimi-seat", "30"), ("glm-steward", "30"), ("one-shot-worker", "0")],
)
def test_role_default_reaches_kimi_environment(tmp_path: Path, role: str, bound: str) -> None:
    result, capture, _, _ = _run(tmp_path, role)

    assert result.returncode == 0, result.stderr
    assert _kimi_record(capture)[:2] == [bound, role]


def test_parameter_file_overrides_both_role_classes_without_code_change(
    tmp_path: Path,
) -> None:
    bounds_file = tmp_path / "bounds.conf"
    bounds_file.write_text(
        "# role max_steps_per_turn\nkimi-seat 17\none-shot-worker 4\n",
        encoding="utf-8",
    )

    seat, seat_capture, _, _ = _run(tmp_path, "kimi-seat", bounds_file=bounds_file)
    worker, worker_capture, _, _ = _run(tmp_path, "one-shot-worker", bounds_file=bounds_file)

    assert seat.returncode == 0, seat.stderr
    assert worker.returncode == 0, worker.stderr
    assert _kimi_record(seat_capture)[0] == "17"
    assert _kimi_record(worker_capture)[0] == "4"


def test_tmux_runner_carries_the_bound_and_resume_arguments(tmp_path: Path) -> None:
    result, _, tmux_capture, spawn_dir = _run(
        tmp_path, "kimi-seat", terminal_none=False, args=("--continue",)
    )

    assert result.returncode == 0, result.stderr
    tmux_args = _kimi_record(tmux_capture)
    assert tmux_args[:4] == ["new-session", "-d", "-s", "hapax-kimi-kimi-seat"]
    runners = list(spawn_dir.glob("run-*.sh"))
    assert len(runners) == 1
    runner = runners[0].read_text(encoding="utf-8")
    assert "export KIMI_LOOP_MAX_STEPS_PER_TURN=30" in runner
    assert "--continue" in runner
    assert "--auto" in runner


def test_invalid_parameter_record_fails_closed_before_a_lane_is_created(
    tmp_path: Path,
) -> None:
    bounds_file = tmp_path / "bounds.conf"
    bounds_file.write_text("kimi-seat seven\n", encoding="utf-8")

    result, _, tmux_capture, spawn_dir = _run(
        tmp_path, "kimi-seat", bounds_file=bounds_file, terminal_none=False
    )

    assert result.returncode != 0
    assert "invalid max_steps_per_turn" in result.stderr
    assert not list(spawn_dir.glob("run-*.sh"))
    assert not tmux_capture.exists() or not tmux_capture.read_text(encoding="utf-8")


def test_duplicate_role_parameter_fails_closed(tmp_path: Path) -> None:
    bounds_file = tmp_path / "bounds.conf"
    bounds_file.write_text("kimi-seat 20\nkimi-seat 21\n", encoding="utf-8")

    result, _, _, _ = _run(tmp_path, "kimi-seat", bounds_file=bounds_file)

    assert result.returncode != 0
    assert "duplicate role" in result.stderr


def test_turn_bound_is_separate_from_the_thinking_effort_arm() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    for forbidden in ("KIMI_THINKING_EFFORT", "HAPAX_KIMI_EFFORT", "thinkingEffort"):
        assert forbidden not in text
