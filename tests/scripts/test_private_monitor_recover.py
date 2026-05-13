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


def _node(name: str, props: dict[str, object] | None = None) -> dict[str, object]:
    node_props = {"node.name": name, "media.class": "Audio/Sink"}
    if props:
        node_props.update(props)
    return {
        "id": len(name),
        "type": "PipeWire:Interface:Node",
        "info": {"props": node_props},
    }


def _bridge_nodes(*, fail_closed: bool = True) -> list[dict[str, object]]:
    if not fail_closed:
        return [_node(name) for name in BRIDGE_NODES]
    return [
        _node(
            "hapax-private-monitor-capture",
            {
                "media.class": "Stream/Input/Audio",
                "target.object": "hapax-private",
                "stream.capture.sink": True,
            },
        ),
        _node(
            "hapax-private-playback",
            {
                "media.class": "Stream/Output/Audio",
                "target.object": MPC_TARGET,
                "node.dont-fallback": True,
                "node.dont-reconnect": True,
                "node.dont-move": True,
                "node.linger": True,
                "state.restore": False,
            },
        ),
        _node(
            "hapax-notification-private-monitor-capture",
            {
                "media.class": "Stream/Input/Audio",
                "target.object": "hapax-notification-private",
                "stream.capture.sink": True,
            },
        ),
        _node(
            "hapax-notification-private-playback",
            {
                "media.class": "Stream/Output/Audio",
                "target.object": MPC_TARGET,
                "node.dont-fallback": True,
                "node.dont-reconnect": True,
                "node.dont-move": True,
                "node.linger": True,
                "state.restore": False,
            },
        ),
    ]


def _write_dump(
    path: Path,
    *,
    include_target: bool = True,
    include_bridge: bool = True,
    bridge_fail_closed: bool = True,
) -> Path:
    nodes = []
    if include_target:
        nodes.append(_node(MPC_TARGET))
    if include_bridge:
        nodes.extend(_bridge_nodes(fail_closed=bridge_fail_closed))
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
    bridge_fail_closed: bool = True,
    install: bool = True,
    preinstalled: str | None = None,
    stale_generated: bool = False,
) -> subprocess.CompletedProcess[str]:
    repo = _repo_root(tmp_path)
    dump = _write_dump(
        tmp_path,
        include_target=include_target,
        include_bridge=include_bridge,
        bridge_fail_closed=bridge_fail_closed,
    )
    install_path = tmp_path / "installed" / "hapax-private-monitor-bridge.conf"
    if preinstalled is not None:
        install_path.parent.mkdir(parents=True)
        install_path.write_text(preinstalled, encoding="utf-8")
    if stale_generated:
        install_path.parent.mkdir(parents=True, exist_ok=True)
        (install_path.parent / "private-monitor-output.conf").write_text(
            'target.object = "alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.multichannel-output"\n',
            encoding="utf-8",
        )
        (install_path.parent / "notification-private-monitor-output.conf").write_text(
            'target.object = "alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.multichannel-output"\n',
            encoding="utf-8",
        )
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
    assert status["bridge_nodes_fail_closed"] is True
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


def test_loaded_bridge_missing_fail_closed_properties_is_blocked(tmp_path: Path) -> None:
    result = _run(tmp_path, bridge_fail_closed=False)

    assert result.returncode == 2
    status = _status(tmp_path)
    assert status["state"] == "blocked_absent"
    assert status["reason_code"] == "private_monitor_bridge_property_drift"
    assert status["bridge_nodes_present"] is True
    assert status["bridge_nodes_fail_closed"] is False


def test_install_disables_stale_generated_private_monitor_fragments(tmp_path: Path) -> None:
    result = _run(tmp_path, stale_generated=True)

    assert result.returncode == 0, result.stdout + result.stderr
    install_dir = tmp_path / "installed"
    assert not (install_dir / "private-monitor-output.conf").exists()
    assert not (install_dir / "notification-private-monitor-output.conf").exists()
    disabled = sorted(
        path.name for path in install_dir.glob("*.disabled-by-hapax-private-monitor-recover*")
    )
    assert disabled == [
        "notification-private-monitor-output.conf.disabled-by-hapax-private-monitor-recover",
        "private-monitor-output.conf.disabled-by-hapax-private-monitor-recover",
    ]
    status = _status(tmp_path)
    assert sorted(status["bridge"]["stale_generated_disabled"]) == [
        "notification-private-monitor-output.conf",
        "private-monitor-output.conf",
    ]
    assert status["bridge"]["requires_pipewire_reload"] is True
