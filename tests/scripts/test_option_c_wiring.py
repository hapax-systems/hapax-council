"""mk5 Phones private-monitor wiring regression pins."""

from __future__ import annotations

import importlib.util
import sys
import types
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

WP_PRIVATE_PIN = REPO_ROOT / "config" / "wireplumber" / "56-hapax-private-pin-s4-track-1.conf"
LEAK_GUARD_SCRIPT = REPO_ROOT / "scripts" / "hapax-private-broadcast-leak-guard"
TOPOLOGY_AUDIT_SCRIPT = REPO_ROOT / "scripts" / "hapax-audio-topology"
AUDIO_TOPOLOGY_YAML = REPO_ROOT / "config" / "audio-topology.yaml"

MPC_SINK = "alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.pro-output-0"
MK5_SINK = "alsa_output.usb-MOTU_UltraLite-mk5_UL5LFEC2B0-00.pro-output-0"
S4_USB_SINK = "alsa_output.usb-Torso_Electronics_S-4_fedcba9876543220-03.multichannel-output"


def _load_module(path: Path, name: str) -> types.ModuleType:
    loader = SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def leak_guard() -> types.ModuleType:
    return _load_module(LEAK_GUARD_SCRIPT, "leak_guard_mpc_private")


@pytest.fixture(scope="module")
def topology_audit() -> types.ModuleType:
    return _load_module(TOPOLOGY_AUDIT_SCRIPT, "topology_audit_mpc_private")


@pytest.fixture(scope="module")
def topology_yaml() -> dict[str, object]:
    return yaml.safe_load(AUDIO_TOPOLOGY_YAML.read_text(encoding="utf-8"))


def test_wireplumber_pin_targets_mk5_not_mpc_s4_or_yeti() -> None:
    body = WP_PRIVATE_PIN.read_text(encoding="utf-8")
    assert MK5_SINK in body
    assert "Akai_Professional_MPC_LIVE_III" not in body
    assert "Torso_Electronics_S-4" not in body
    assert "Blue_Microphones_Yeti" not in body
    assert 'node.name = "hapax-private-playback"' in body
    assert 'node.name = "hapax-notification-private-playback"' not in body


def test_wireplumber_pin_preserves_fail_closed_props() -> None:
    body = WP_PRIVATE_PIN.read_text(encoding="utf-8")
    assert "node.dont-fallback = true" in body
    assert "node.dont-reconnect = true" in body
    assert "node.dont-move = true" in body
    assert "node.linger = true" in body
    assert "priority.session = -1" in body


def test_private_to_mpc_aux8_9_is_allowed(leak_guard: types.ModuleType) -> None:
    text = (
        f"hapax-private-playback:output_FL\n  |-> {MPC_SINK}:playback_AUX8\n"
        f"hapax-private-playback:output_FR\n  |-> {MPC_SINK}:playback_AUX9\n"
    )
    edges = leak_guard.parse_pw_link(text)
    assert leak_guard.detect_forbidden(edges) == []


def test_private_to_other_mpc_ports_or_s4_is_forbidden(leak_guard: types.ModuleType) -> None:
    text = (
        f"hapax-private-playback:output_FL\n  |-> {MPC_SINK}:playback_AUX0\n"
        f"hapax-notification-private-playback:output_FR\n  |-> {S4_USB_SINK}:playback_AUX1\n"
    )
    edges = leak_guard.parse_pw_link(text)
    leaks = leak_guard.detect_forbidden(edges)
    assert {(leak.source_node, leak.target_node) for leak in leaks} == {
        ("hapax-private-playback", MPC_SINK),
        ("hapax-notification-private-playback", S4_USB_SINK),
    }


def test_notification_private_to_mpc_aux8_9_is_forbidden(leak_guard: types.ModuleType) -> None:
    text = (
        f"hapax-notification-private-playback:output_FL\n  |-> {MPC_SINK}:playback_AUX8\n"
        f"hapax-notification-private-playback:output_FR\n  |-> {MPC_SINK}:playback_AUX9\n"
    )
    edges = leak_guard.parse_pw_link(text)
    leaks = leak_guard.detect_forbidden(edges)
    assert {(leak.source_node, leak.target_node) for leak in leaks} == {
        ("hapax-notification-private-playback", MPC_SINK),
    }


def test_topology_mk5_carries_private_monitor_annotation(
    topology_yaml: dict[str, object],
) -> None:
    nodes = topology_yaml["nodes"]
    assert isinstance(nodes, list)
    by_id = {node["id"]: node for node in nodes if isinstance(node, dict)}
    mk5 = by_id["mk5-output"]
    assert mk5["pipewire_name"] == MK5_SINK
    params = mk5.get("params", {})
    assert params.get("private_monitor_endpoint") is True
    assert params.get("private_monitor_positions") == "AUX10 AUX11"
    assert params.get("private_monitor_route") == "private-monitor-via-mk5-phones"
    assert by_id["s4-output"].get("params", {}).get("private_monitor_endpoint") is not True


def test_topology_private_monitor_edges_target_mk5(topology_yaml: dict[str, object]) -> None:
    nodes = topology_yaml["nodes"]
    by_id = {node["id"]: node for node in nodes if isinstance(node, dict)}
    assert by_id["private-monitor-output"]["target_object"] == MK5_SINK
    assert by_id["notification-private-monitor-output"].get("target_object") is None
    assert (
        by_id["notification-private-monitor-output"]["params"]["disabled_until_route_authority"]
        is True
    )

    edges = topology_yaml["edges"]
    edge_set = {(edge["source"], edge["target"]) for edge in edges if isinstance(edge, dict)}
    assert ("private-monitor-output", "mk5-output") in edge_set
    assert ("private-monitor-output", "mpc-usb-output") not in edge_set
    assert ("notification-private-monitor-output", "mpc-usb-output") not in edge_set
    assert ("private-monitor-output", "s4-output") not in edge_set


def test_classifier_recognizes_mk5_private_monitor_edge(
    topology_audit: types.ModuleType,
) -> None:
    from shared.audio_topology import ChannelMap, Node, NodeKind

    bridge = Node(
        id="private-monitor-output",
        kind=NodeKind.LOOPBACK,
        pipewire_name="hapax-private-playback",
        description="private monitor bridge to mk5 Phones",
        target_object=MK5_SINK,
        channels=ChannelMap(count=2, positions=["FL", "FR"]),
        params={"private_monitor_bridge": True},
    )
    mk5 = Node(
        id="mk5-output",
        kind=NodeKind.ALSA_SINK,
        pipewire_name=MK5_SINK,
        description="MOTU UltraLite mk5",
        target_object=None,
        hw="hw:UltraLitemk5",
        channels=ChannelMap(count=14, positions=[f"AUX{i}" for i in range(14)]),
        params={
            "private_monitor_endpoint": True,
            "private_monitor_route": "private-monitor-via-mk5-phones",
        },
    )
    declared_by_name = {bridge.pipewire_name: bridge, mk5.pipewire_name: mk5}
    classification = topology_audit._classify_live_extra_edge(
        bridge.pipewire_name,
        mk5.pipewire_name,
        declared_by_name,
        dict(declared_by_name),
    )
    assert classification == "private-monitor-mk5-phones-binding"


def test_inspector_private_monitor_bridge_allows_mk5_endpoint() -> None:
    from shared.audio_topology_inspector import (
        _PRIVATE_MONITOR_BRIDGES,
        ALLOWED_RUNTIME_EDGE_CLASSIFICATIONS,
    )

    assert "private-monitor-mk5-phones-binding" in ALLOWED_RUNTIME_EDGE_CLASSIFICATIONS
    assert tuple(_PRIVATE_MONITOR_BRIDGES) == ("private-monitor-output",)
    _capture_id, _source_id, allowed_endpoints = _PRIVATE_MONITOR_BRIDGES["private-monitor-output"]
    assert tuple(allowed_endpoints) == ("mk5-output",)
