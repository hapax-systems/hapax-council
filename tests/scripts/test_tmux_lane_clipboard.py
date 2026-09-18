"""Tests for the Hapax tmux lane clipboard profile."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE = REPO_ROOT / "config" / "tmux" / "hapax-lane.conf"
CONFIGURE = REPO_ROOT / "scripts" / "hapax-tmux-lane-configure"
LAUNCHERS = [
    REPO_ROOT / "scripts" / "hapax-codex",
    REPO_ROOT / "scripts" / "hapax-claude",
    REPO_ROOT / "scripts" / "hapax-vibe",
    REPO_ROOT / "scripts" / "hapax-kimi",
]


def test_profile_enables_native_clipboard_mouse_copy() -> None:
    text = PROFILE.read_text(encoding="utf-8")

    assert "set -g mouse on" in text
    assert "set -g set-clipboard on" in text
    assert "set -s set-clipboard on" in text
    assert "foot*:clipboard:RGB" in text
    assert "foot*:Ms=\\\\E]52;c;%p2%s\\\\007" in text
    assert "MouseDragEnd1Pane send-keys -X copy-selection-and-cancel" in text
    assert "DoubleClick1Pane" in text
    assert "TripleClick1Pane" in text


def test_tmux_backed_launchers_source_the_shared_profile() -> None:
    for launcher in LAUNCHERS:
        text = launcher.read_text(encoding="utf-8")
        assert "hapax-tmux-lane-configure" in text, launcher
        assert "configure_hapax_tmux_lane" in text, launcher


def test_helper_and_launchers_parse_with_bash() -> None:
    for script in [CONFIGURE, *LAUNCHERS]:
        result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        assert result.returncode == 0, f"bash -n failed for {script}:\n{result.stderr}"


def test_configure_helper_sources_profile_once(tmp_path: Path) -> None:
    fake_tmux = tmp_path / "tmux"
    log = tmp_path / "tmux.log"
    fake_tmux.write_text(
        f"""#!/usr/bin/env bash
case "$1" in
  show-options)
    exit 0
    ;;
  source-file)
    printf '%s\\n' "$*" >> {log}
    exit 0
    ;;
esac
exit 64
""",
        encoding="utf-8",
    )
    fake_tmux.chmod(0o755)

    env = os.environ.copy()
    env["HAPAX_COUNCIL_DIR"] = str(REPO_ROOT)
    result = subprocess.run(
        [str(CONFIGURE), str(fake_tmux)],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert f"source-file -q {PROFILE}" in log.read_text(encoding="utf-8")


def test_configure_helper_skips_when_profile_already_loaded(tmp_path: Path) -> None:
    fake_tmux = tmp_path / "tmux"
    log = tmp_path / "tmux.log"
    fake_tmux.write_text(
        f"""#!/usr/bin/env bash
case "$1" in
  show-options)
    printf '1\\n'
    exit 0
    ;;
  source-file)
    printf '%s\\n' "$*" >> {log}
    exit 0
    ;;
esac
exit 64
""",
        encoding="utf-8",
    )
    fake_tmux.chmod(0o755)

    env = os.environ.copy()
    env["HAPAX_COUNCIL_DIR"] = str(REPO_ROOT)
    result = subprocess.run(
        [str(CONFIGURE), str(fake_tmux)],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert not log.exists()


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is not installed")
def test_profile_parses_in_isolated_tmux_server(tmp_path: Path) -> None:
    socket_name = f"hapax-test-{os.getpid()}-{tmp_path.name}"
    tmux = shutil.which("tmux")
    assert tmux is not None

    subprocess.run(
        [tmux, "-L", socket_name, "-f", "/dev/null", "new-session", "-d", "-s", "test", "sleep 60"],
        check=True,
    )
    try:
        subprocess.run([tmux, "-L", socket_name, "source-file", "-q", str(PROFILE)], check=True)
        mouse = subprocess.check_output(
            [tmux, "-L", socket_name, "show-options", "-gqv", "mouse"],
            text=True,
        ).strip()
        clipboard = subprocess.check_output(
            [tmux, "-L", socket_name, "show-options", "-gqv", "set-clipboard"],
            text=True,
        ).strip()
        vi_keys = subprocess.check_output(
            [tmux, "-L", socket_name, "list-keys", "-T", "copy-mode-vi"],
            text=True,
        )
        root_keys = subprocess.check_output(
            [tmux, "-L", socket_name, "list-keys", "-T", "root"],
            text=True,
        )
    finally:
        subprocess.run([tmux, "-L", socket_name, "kill-server"], check=False)

    assert mouse == "on"
    assert clipboard == "on"
    assert "MouseDragEnd1Pane send-keys -X copy-selection-and-cancel" in vi_keys
    assert "DoubleClick1Pane" in root_keys
    assert "copy-selection-and-cancel" in root_keys
