"""Focused tests for Codex session health reporting."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HEALTH = REPO_ROOT / "scripts" / "hapax-codex-health"


def _kde_health_env(tmp_path: Path, *, tmux_session_exists: bool = False) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    has_session_exit = 0 if tmux_session_exists else 1
    fake_tmux = bin_dir / "tmux"
    fake_tmux.write_text(
        f"""#!/bin/sh
if [ "$1" = "has-session" ]; then
  exit {has_session_exit}
fi
exit 0
""",
        encoding="utf-8",
    )
    fake_tmux.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = str(bin_dir)
    env["HOME"] = str(tmp_path / "home")
    env["XDG_CACHE_HOME"] = str(tmp_path / "cache")
    env["XDG_CURRENT_DESKTOP"] = "KDE"
    env["DESKTOP_SESSION"] = "plasma"
    return env


def test_health_json_degrades_under_kde_without_hyprctl(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(HEALTH), "--json", "cx-gold"],
        capture_output=True,
        text=True,
        env=_kde_health_env(tmp_path, tmux_session_exists=True),
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    observation = report["desktop_observation"]
    assert observation["mode"] == "kde_no_window_observer"
    assert observation["hyprctl_available"] is False
    assert observation["visible_windows_observed"] is False
    assert "KDE/no-window-observer" in observation["note"]
    assert report["lanes"][0]["session"] == "cx-gold"
    assert report["lanes"][0]["foot_visible"] is False


def test_health_obsidian_dashboard_records_kde_no_window_observer(tmp_path: Path) -> None:
    dashboard = tmp_path / "codex-session-health.md"
    result = subprocess.run(
        [sys.executable, str(HEALTH), "--write-obsidian", str(dashboard), "cx-red"],
        capture_output=True,
        text=True,
        env=_kde_health_env(tmp_path, tmux_session_exists=True),
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    text = dashboard.read_text(encoding="utf-8")
    assert "Desktop observation: `kde_no_window_observer`" in text
    assert "KDE/no-window-observer" in text
    assert "screen_required_visibility_not_observed" in text


def test_health_json_detects_agy_tmux_control_plane(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_tmux = bin_dir / "tmux"
    fake_tmux.write_text(
        """#!/bin/sh
if [ "$1" = "has-session" ] && [ "$2" = "-t" ] && [ "$3" = "hapax-agy-agy-2" ]; then
  exit 0
fi
exit 1
""",
        encoding="utf-8",
    )
    fake_tmux.chmod(0o755)
    cache = tmp_path / "cache"
    claims = cache / "hapax"
    claims.mkdir(parents=True)
    (claims / "cc-active-task-agy-2").write_text("demo-task\n", encoding="utf-8")
    env = {
        **os.environ,
        "PATH": str(bin_dir),
        "HOME": str(tmp_path / "home"),
        "XDG_CACHE_HOME": str(cache),
    }

    result = subprocess.run(
        [sys.executable, str(HEALTH), "--json", "agy-2"],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    lane = json.loads(result.stdout)["lanes"][0]
    assert lane["session"] == "agy-2"
    assert lane["tmux"] is True
    assert lane["tmux_control_plane"] == "hapax-agy-agy-2"
    assert lane["tmux_control_plane_targets"] == ["hapax-codex-agy-2", "hapax-agy-agy-2"]
    assert "worker_claim_without_tmux_control_plane" not in lane["warnings"]
