"""Tests for the private monitor exact-target recovery CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-private-monitor-recover"
MPC_TARGET = "alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.multichannel-output"
BRIDGE_NODES = (
    "hapax-private-monitor-capture",
    "hapax-private-playback",
    "hapax-notification-private-monitor-capture",
    "hapax-notification-private-playback",
)


def _node(name: str) -> dict[str, object]:
    return {
        "id": len(name),
        "type": "PipeWire:Interface:Node",
        "info": {"props": {"node.name": name, "media.class": "Audio/Sink"}},
    }


def _write_dump(path: Path, *, include_target: bool = True, include_bridge: bool = True) -> Path:
    nodes = []
    if include_target:
        nodes.append(_node(MPC_TARGET))
    if include_bridge:
        nodes.extend(_node(name) for name in BRIDGE_NODES)
    dump = path / "pw-dump.json"
    dump.write_text(json.dumps(nodes), encoding="utf-8")
    return dump


def _repo_root(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    bridge = repo / "config" / "pipewire" / "hapax-private-monitor-bridge.conf"
    bridge.parent.mkdir(parents=True)
    bridge.write_text(
        dedent(
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
                    target.object = "{MPC_TARGET}"
                    node.dont-fallback = true
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
                    target.object = "{MPC_TARGET}"
                    node.dont-fallback = true
                    node.dont-reconnect = true
                    node.dont-move = true
                    node.linger = true
                    state.restore = false
                  }}
                }}
              }}
            ]
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    return repo


def _run(
    tmp_path: Path,
    *,
    include_target: bool = True,
    include_bridge: bool = True,
    install: bool = True,
    preinstalled: str | None = None,
) -> subprocess.CompletedProcess[str]:
    repo = _repo_root(tmp_path)
    dump = _write_dump(tmp_path, include_target=include_target, include_bridge=include_bridge)
    install_path = tmp_path / "installed" / "hapax-private-monitor-bridge.conf"
    if preinstalled is not None:
        install_path.parent.mkdir(parents=True)
        install_path.write_text(preinstalled, encoding="utf-8")
    status_path = tmp_path / "status.json"
    args = [
        sys.executable,
        str(SCRIPT),
        "--repo-root",
        str(repo),
        "--dump-file",
        str(dump),
        "--install-path",
        str(install_path),
        "--status-path",
        str(status_path),
    ]
    if install:
        args.append("--install")
    return subprocess.run(args, capture_output=True, text=True, check=False, timeout=5)


def _status(tmp_path: Path) -> dict[str, object]:
    return json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))


def test_ready_installs_bridge_and_writes_sanitized_status(tmp_path: Path) -> None:
    result = _run(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    status = _status(tmp_path)
    assert status["state"] == "ready"
    assert status["route_id"] == "route:private.mpc_live_iii_monitor"
    assert status["target_ref"] == "audio.mpc_private_monitor"
    assert status["fallback_policy"] == "no_default_fallback"
    serialized = json.dumps(status) + result.stdout
    assert MPC_TARGET not in serialized
    assert "alsa_output.usb-" not in serialized


def test_missing_exact_target_is_blocked_absent_without_fallback(tmp_path: Path) -> None:
    result = _run(tmp_path, include_target=False)

    assert result.returncode == 2
    status = _status(tmp_path)
    assert status["state"] == "blocked_absent"
    assert status["reason_code"] == "mpc_private_monitor_target_absent"
    assert status["fallback_policy"] == "no_default_fallback"


def test_installed_bridge_drift_blocks_when_not_repaired(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        install=False,
        preinstalled='target.object = "hapax-voice-fx-capture"\n',
    )

    assert result.returncode == 2
    status = _status(tmp_path)
    assert status["state"] == "blocked_absent"
    assert status["reason_code"] == "private_monitor_bridge_drift"


def test_install_repairs_bridge_drift_when_exact_target_is_present(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        install=True,
        preinstalled='target.object = "hapax-voice-fx-capture"\n',
    )

    assert result.returncode == 0, result.stdout + result.stderr
    status = _status(tmp_path)
    assert status["state"] == "ready"
    assert status["bridge"]["repaired"] is True


def test_installed_but_unloaded_bridge_is_blocked_absent(tmp_path: Path) -> None:
    result = _run(tmp_path, include_bridge=False)

    assert result.returncode == 2
    status = _status(tmp_path)
    assert status["state"] == "blocked_absent"
    assert status["reason_code"] == "private_monitor_bridge_not_loaded"
