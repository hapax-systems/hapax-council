"""Tests for the hapax-pc-router fork node topology (PR A)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from shared.audio_topology import NodeKind, TopologyDescriptor

TOPOLOGY_PATH = Path(__file__).parent.parent.parent / "config" / "audio-topology.yaml"

ROUTER_PW_NAME = "hapax-pc-router"
MONITOR_PW_NAME = "hapax-pc-monitor"
BROADCAST_PW_NAME = "hapax-pc-broadcast"


class TestPcRouterTopologyDescriptor:
    """Validate the three new nodes parse correctly from the YAML descriptor."""

    def setup_method(self) -> None:
        self.td = TopologyDescriptor.from_yaml(TOPOLOGY_PATH)

    def test_pc_router_node_exists(self) -> None:
        node = self.td.node_by_id("pc-router")
        assert node.kind == NodeKind.TAP
        assert node.pipewire_name == ROUTER_PW_NAME

    def test_pc_monitor_node_exists(self) -> None:
        node = self.td.node_by_id("pc-monitor")
        assert node.kind == NodeKind.FILTER_CHAIN
        assert node.pipewire_name == MONITOR_PW_NAME
        assert node.target_object == ROUTER_PW_NAME

    def test_pc_broadcast_node_exists(self) -> None:
        node = self.td.node_by_id("pc-broadcast")
        assert node.kind == NodeKind.FILTER_CHAIN
        assert node.pipewire_name == BROADCAST_PW_NAME
        assert node.target_object == ROUTER_PW_NAME

    def test_monitor_target_is_yeti(self) -> None:
        """Monitor playback must point at the Blue Yeti (private, off-L-12)."""
        node = self.td.node_by_id("pc-monitor")
        target = node.params.get("playback_target", "")
        assert "Yeti" in target, f"pc-monitor playback_target must contain 'Yeti'; got {target!r}"
        assert "ZOOM" not in target, (
            "pc-monitor playback_target must NOT point at L-12 (broadcast invariant)"
        )

    def test_broadcast_target_is_l12(self) -> None:
        """Broadcast playback must point at L-12 USB return."""
        node = self.td.node_by_id("pc-broadcast")
        target = node.params.get("playback_target", "")
        assert "ZOOM" in target

    def test_broadcast_positions_are_rl_rr(self) -> None:
        node = self.td.node_by_id("pc-broadcast")
        positions = node.params.get("playback_positions", "")
        assert "RL" in positions and "RR" in positions

    def test_router_to_monitor_edge_exists(self) -> None:
        edges = self.td.edges_from("pc-router")
        targets = {e.target for e in edges}
        assert "pc-monitor" in targets

    def test_router_to_broadcast_edge_exists(self) -> None:
        edges = self.td.edges_from("pc-router")
        targets = {e.target for e in edges}
        assert "pc-broadcast" in targets

    def test_monitor_and_broadcast_have_independent_outputs(self) -> None:
        """Monitor and broadcast must target different downstream sinks."""
        monitor_node = self.td.node_by_id("pc-monitor")
        broadcast_node = self.td.node_by_id("pc-broadcast")
        m = monitor_node.params.get("playback_target", "")
        b = broadcast_node.params.get("playback_target", "")
        assert m != b, (
            f"pc-monitor and pc-broadcast must have independent output targets "
            f"(both point at {m!r})"
        )

    def test_monitor_is_annotated_private(self) -> None:
        node = self.td.node_by_id("pc-monitor")
        assert node.params.get("private_monitor_endpoint") is True

    def test_monitor_has_forbidden_broadcast_annotation(self) -> None:
        node = self.td.node_by_id("pc-monitor")
        assert node.params.get("forbidden_target_family") == "l12-broadcast"


@pytest.mark.live
@pytest.mark.skipif(
    shutil.which("pactl") is None or shutil.which("pw-link") is None,
    reason="requires live PipeWire CLI tools",
)
class TestPcRouterLiveGraph:
    """Post-restart assertions against the live PipeWire graph."""

    def setup_method(self) -> None:
        sinks = self._pactl_short_sinks()
        if ROUTER_PW_NAME not in sinks:
            pytest.skip("hapax-pc-router graph is not deployed in this live PipeWire session")

    def _pactl_short_sinks(self) -> str:
        result = subprocess.run(
            ["pactl", "list", "short", "sinks"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout

    def _pw_link_list(self) -> str:
        result = subprocess.run(
            ["pw-link", "-l"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout

    def test_pc_router_sink_present(self) -> None:
        assert "hapax-pc-router" in self._pactl_short_sinks()

    def test_pc_monitor_sink_present(self) -> None:
        assert "hapax-pc-monitor" in self._pactl_short_sinks()

    def test_pc_broadcast_sink_present(self) -> None:
        assert "hapax-pc-broadcast" in self._pactl_short_sinks()

    def test_pc_router_has_two_monitor_consumers(self) -> None:
        """hapax-pc-router monitor port must link to both subscribers."""
        pw_links = self._pw_link_list()
        monitor_refs = pw_links.count("hapax-pc-router")
        assert monitor_refs >= 2

    def test_monitor_does_not_link_to_broadcast_target(self) -> None:
        """pc-monitor output must not connect to L-12."""
        pw_links = self._pw_link_list()
        lines = [line for line in pw_links.splitlines() if "hapax-pc-monitor-playback" in line]
        for line in lines:
            assert "ZOOM" not in line and "L-12" not in line
