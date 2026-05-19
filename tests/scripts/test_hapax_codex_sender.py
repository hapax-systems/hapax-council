"""Focused tests for Codex sender transport language."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SENDER = REPO_ROOT / "scripts" / "hapax-codex-send"
BASH = Path("/usr/bin/bash")


def _sender_env_without_hyprctl(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    env = os.environ.copy()
    env["PATH"] = str(bin_dir)
    env["HOME"] = str(tmp_path / "home")
    env["XDG_CACHE_HOME"] = str(tmp_path / "cache")
    env["XDG_CURRENT_DESKTOP"] = "KDE"
    return env


def test_codex_send_help_names_tmux_as_reliable_control_plane() -> None:
    result = subprocess.run(
        [str(BASH), str(SENDER), "--help"],
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "reliable control plane is tmux" in result.stdout
    assert "legacy Hyprland-specific fallback" in result.stdout
    assert "ACK-gated sends require tmux" in result.stdout
    assert "Sends MESSAGE to a visible Hapax Codex session" not in result.stdout
    assert "Visible foot delivery targets the window address directly" not in result.stdout


def test_codex_send_foot_without_hyprctl_points_kde_users_to_tmux(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            str(BASH),
            str(SENDER),
            "--session",
            "cx-gold",
            "--transport",
            "foot",
            "--",
            "status",
        ],
        capture_output=True,
        text=True,
        env=_sender_env_without_hyprctl(tmp_path),
        timeout=5,
    )

    assert result.returncode == 10
    assert "legacy Hyprland foot transport requires hyprctl" in result.stderr
    assert "use tmux for KDE/reliable control-plane delivery" in result.stderr
