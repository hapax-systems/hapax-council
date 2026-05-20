"""Static and smoke tests for optional-runtime restart-storm containment."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNITS_DIR = REPO_ROOT / "systemd" / "units"


def test_m8_stem_recorder_absent_source_exits_cleanly(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    pactl = fake_bin / "pactl"
    pactl.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    pactl.chmod(pactl.stat().st_mode | stat.S_IXUSR)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "HAPAX_M8_STEM_DIR": str(tmp_path / "stems"),
            "HAPAX_M8_SOURCE_WAIT_SECONDS": "0",
        }
    )

    result = subprocess.run(
        [str(REPO_ROOT / "scripts" / "m8-stem-recorder.sh")],
        check=False,
        env=env,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0
    assert "no M8 USB audio source found" in result.stderr


def test_midi_bridge_unit_is_guarded_and_not_unconditioned_restart() -> None:
    script = REPO_ROOT / "scripts" / "hapax-midi-bridge-client"
    unit = UNITS_DIR / "hapax-midi-bridge-client.service"

    assert script.exists()
    assert script.stat().st_mode & stat.S_IXUSR
    script_body = script.read_text(encoding="utf-8")
    assert "/dev/tcp/${HOST}/${PORT}" in script_body
    assert "exit 0" in script_body
    assert "exec /usr/bin/aseqnet" in script_body

    unit_body = unit.read_text(encoding="utf-8")
    assert (
        "ExecStart=%h/.cache/hapax/source-activation/worktree/scripts/hapax-midi-bridge-client"
        in unit_body
    )
    assert "Restart=on-failure" in unit_body
    assert "Restart=always" not in unit_body
    assert "RestartSec=30s" in unit_body
    assert "StartLimitBurst=4" in unit_body


def test_youtube_player_unit_is_source_activated_and_import_safe() -> None:
    unit = UNITS_DIR / "youtube-player.service"
    body = unit.read_text(encoding="utf-8")

    assert "WorkingDirectory=%h/.cache/hapax/source-activation/worktree" in body
    assert "Environment=PYTHONPATH=%h/.cache/hapax/source-activation/worktree" in body
    assert "ExecStart=%h/.cache/hapax/source-activation/worktree/.venv/bin/python" in body
    assert "scripts/youtube-player.py" in body
    assert "Restart=on-failure" in body
    assert "StartLimitBurst=6" in body


def test_content_id_watcher_uses_source_activation_venv_under_sandbox() -> None:
    unit = UNITS_DIR / "hapax-content-id-watcher.service"
    body = unit.read_text(encoding="utf-8")

    assert "WorkingDirectory=%h/.cache/hapax/source-activation/worktree" in body
    assert "Environment=PYTHONPATH=%h/.cache/hapax/source-activation/worktree" in body
    assert "ExecStart=%h/.cache/hapax/source-activation/worktree/.venv/bin/python" in body
    assert "%h/.local/bin/uv run" not in body
    assert "ProtectSystem=strict" in body
    assert "ReadWritePaths=/dev/shm" in body
    assert "MemoryMax=512M" in body
    assert "Restart=on-failure" in body
    assert "Restart=always" not in body
    assert "StartLimitBurst=4" in body
