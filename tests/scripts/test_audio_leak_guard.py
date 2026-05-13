"""Regression tests for the private/broadcast voice leak guard."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "audio-leak-guard.sh"
MPC_TARGET = "alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.multichannel-output"
S4_TARGET = "alsa_output.usb-Torso_Electronics_S-4_fedcba9876543220-03.multichannel-output"
YETI_TARGET = "alsa_output.usb-Blue_Microphones_Yeti_Stereo_Microphone_REV8-00.analog-stereo"


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


def _write_private_monitor_bridge(
    conf_dir: Path,
    *,
    target: str = MPC_TARGET,
    include_dont_fallback: bool = True,
) -> None:
    dont_fallback = "node.dont-fallback = true" if include_dont_fallback else ""
    conf_dir.joinpath("hapax-private-monitor-bridge.conf").write_text(
        f"""
context.modules = [
  {{ name = libpipewire-module-loopback
    args = {{
      capture.props = {{
        node.name = "hapax-private-monitor-capture"
        stream.capture.sink = true
        target.object = "hapax-private"
      }}
      playback.props = {{
        node.name = "hapax-private-playback"
        target.object = "{target}"
        {dont_fallback}
        node.dont-reconnect = true
        node.dont-move = true
        node.linger = true
        state.restore = false
      }}
    }}
  }}
  {{ name = libpipewire-module-loopback
    args = {{
      capture.props = {{
        node.name = "hapax-notification-private-monitor-capture"
        stream.capture.sink = true
        target.object = "hapax-notification-private"
      }}
      playback.props = {{
        node.name = "hapax-notification-private-playback"
        target.object = "{target}"
        node.dont-fallback = true
        node.dont-reconnect = true
        node.dont-move = true
        node.linger = true
        state.restore = false
      }}
    }}
  }}
]
""",
        encoding="utf-8",
    )


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


def test_allows_explicit_mpc_private_monitor_bridge(tmp_path: Path) -> None:
    conf_dir = _write_wireplumber_config(tmp_path)
    pipewire_conf_dir = _write_pipewire_config(tmp_path)
    _write_private_monitor_bridge(pipewire_conf_dir)

    result = _run_guard(conf_dir, tmp_path, pipewire_conf_dir=pipewire_conf_dir)

    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        "OK  hapax-private-playback static target is MPC Live III private monitor" in result.stdout
    )
    assert (
        "OK  hapax-notification-private-playback static target is MPC Live III private monitor"
        in result.stdout
    )


def test_fails_when_explicit_private_monitor_bridge_targets_yeti(tmp_path: Path) -> None:
    conf_dir = _write_wireplumber_config(tmp_path)
    pipewire_conf_dir = _write_pipewire_config(tmp_path)
    _write_private_monitor_bridge(pipewire_conf_dir, target=YETI_TARGET)

    result = _run_guard(conf_dir, tmp_path, pipewire_conf_dir=pipewire_conf_dir)

    assert result.returncode == 1
    assert "static target is not the approved private monitor" in result.stdout


def test_fails_when_explicit_private_monitor_bridge_targets_s4(tmp_path: Path) -> None:
    conf_dir = _write_wireplumber_config(tmp_path)
    pipewire_conf_dir = _write_pipewire_config(tmp_path)
    _write_private_monitor_bridge(pipewire_conf_dir, target=S4_TARGET)

    result = _run_guard(conf_dir, tmp_path, pipewire_conf_dir=pipewire_conf_dir)

    assert result.returncode == 1
    assert "static target is broadcast/default path" in result.stdout


def test_fails_when_explicit_private_monitor_bridge_targets_l12(tmp_path: Path) -> None:
    conf_dir = _write_wireplumber_config(tmp_path)
    pipewire_conf_dir = _write_pipewire_config(tmp_path)
    _write_private_monitor_bridge(
        pipewire_conf_dir,
        target="alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40",
    )

    result = _run_guard(conf_dir, tmp_path, pipewire_conf_dir=pipewire_conf_dir)

    assert result.returncode == 1
    assert "FAIL hapax-private-playback static target is broadcast/default path" in result.stdout
    assert "LEAK RISK DETECTED" in result.stdout


def test_fails_when_explicit_private_monitor_bridge_can_fallback(tmp_path: Path) -> None:
    conf_dir = _write_wireplumber_config(tmp_path)
    pipewire_conf_dir = _write_pipewire_config(tmp_path)
    _write_private_monitor_bridge(pipewire_conf_dir, include_dont_fallback=False)

    result = _run_guard(conf_dir, tmp_path, pipewire_conf_dir=pipewire_conf_dir)

    assert result.returncode == 1
    assert "FAIL hapax-private-playback missing fail-closed property" in result.stdout
    assert "LEAK RISK DETECTED" in result.stdout
