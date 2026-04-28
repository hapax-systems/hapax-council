"""Regression tests for the private/broadcast voice leak guard."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "audio-leak-guard.sh"


def _write_wireplumber_config(
    tmp_path: Path,
    *,
    assistant_target: str = "hapax-private",
    broadcast_target: str = "hapax-voice-fx-capture",
) -> Path:
    conf_dir = tmp_path / "wireplumber.conf.d"
    conf_dir.mkdir()
    (conf_dir / "50-hapax-voice-duck.conf").write_text(
        f"""
[
  {{
    name = libpipewire-module-loopback, type = pw-module
    arguments = {{
      node.name = "loopback.sink.role.assistant"
      capture.props = {{
        policy.role-based.preferred-target = "{assistant_target}"
      }}
    }}
    provides = loopback.sink.role.assistant
  }}

  {{
    name = libpipewire-module-loopback, type = pw-module
    arguments = {{
      node.name = "loopback.sink.role.broadcast"
      capture.props = {{
        policy.role-based.preferred-target = "{broadcast_target}"
      }}
    }}
    provides = loopback.sink.role.broadcast
  }}
]
""",
        encoding="utf-8",
    )
    return conf_dir


def _write_pipewire_config(
    tmp_path: Path,
    *,
    private_target: str | None = None,
    notification_target: str | None = None,
) -> Path:
    conf_dir = tmp_path / "pipewire.conf.d"
    conf_dir.mkdir()
    private_playback = ""
    if private_target is not None:
        private_playback = f"""
context.modules = [
  {{ name = libpipewire-module-loopback
    args = {{
      playback.props = {{
        node.name = "hapax-private-playback"
        target.object = "{private_target}"
      }}
    }}
  }}
]
"""
    (conf_dir / "hapax-stream-split.conf").write_text(
        f"""
context.objects = [
  {{ factory = adapter
    args = {{
      factory.name = support.null-audio-sink
      node.name = "hapax-private"
    }}
  }}
]
{private_playback}
""",
        encoding="utf-8",
    )
    notification_playback = ""
    if notification_target is not None:
        notification_playback = f"""
context.modules = [
  {{ name = libpipewire-module-loopback
    args = {{
      playback.props = {{
        node.name = "hapax-notification-private-playback"
        target.object = "{notification_target}"
      }}
    }}
  }}
]
"""
    (conf_dir / "hapax-notification-private.conf").write_text(
        f"""
context.objects = [
  {{ factory = adapter
    args = {{
      factory.name = support.null-audio-sink
      node.name = "hapax-notification-private"
    }}
  }}
]
{notification_playback}
""",
        encoding="utf-8",
    )
    return conf_dir


def _run_guard(
    conf_dir: Path,
    tmp_path: Path,
    *,
    pipewire_conf_dir: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    env["HAPAX_WIREPLUMBER_CONF_DIR"] = str(conf_dir)
    env["HAPAX_PIPEWIRE_CONF_DIR"] = str(pipewire_conf_dir or _write_pipewire_config(tmp_path))
    env["HAPAX_AUDIO_LEAK_GUARD_STATIC_ONLY"] = "1"
    return subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
        check=False,
    )


def test_allows_broadcast_target_when_assistant_is_private(tmp_path: Path) -> None:
    conf_dir = _write_wireplumber_config(tmp_path)

    result = _run_guard(conf_dir, tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "role.assistant preferred-target NOT pinned" not in result.stdout
    assert "OK  preferred-target = hapax-private" in result.stdout
    assert "OK  role.broadcast routes to hapax-voice-fx-capture" in result.stdout


def test_fails_when_assistant_targets_broadcast_chain(tmp_path: Path) -> None:
    conf_dir = _write_wireplumber_config(
        tmp_path,
        assistant_target="hapax-voice-fx-capture",
    )

    result = _run_guard(conf_dir, tmp_path)

    assert result.returncode == 1
    assert "FAIL role.assistant preferred-target NOT pinned" in result.stdout
    assert "LEAK RISK DETECTED" in result.stdout


def test_fails_when_broadcast_route_is_missing(tmp_path: Path) -> None:
    conf_dir = _write_wireplumber_config(
        tmp_path,
        broadcast_target="hapax-private",
    )

    result = _run_guard(conf_dir, tmp_path)

    assert result.returncode == 1
    assert "FAIL role.broadcast preferred-target missing hapax-voice-fx-capture" in result.stdout
    assert "LEAK RISK DETECTED" in result.stdout


def test_fails_when_private_sink_targets_l12(tmp_path: Path) -> None:
    conf_dir = _write_wireplumber_config(tmp_path)
    pipewire_conf_dir = _write_pipewire_config(
        tmp_path,
        private_target="alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40",
    )

    result = _run_guard(conf_dir, tmp_path, pipewire_conf_dir=pipewire_conf_dir)

    assert result.returncode == 1
    assert "FAIL hapax-private-playback static target is broadcast/default path" in result.stdout
    assert "LEAK RISK DETECTED" in result.stdout


def test_fails_when_notification_sink_targets_default_broadcast_path(tmp_path: Path) -> None:
    conf_dir = _write_wireplumber_config(tmp_path)
    pipewire_conf_dir = _write_pipewire_config(
        tmp_path,
        notification_target="hapax-pc-loudnorm",
    )

    result = _run_guard(conf_dir, tmp_path, pipewire_conf_dir=pipewire_conf_dir)

    assert result.returncode == 1
    assert (
        "FAIL hapax-notification-private static target is broadcast/default path" in result.stdout
    )
    assert "LEAK RISK DETECTED" in result.stdout
