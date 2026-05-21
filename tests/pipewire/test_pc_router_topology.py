"""Tests proving PC router/broadcast topology is quarantined.

The pc-router, pc-monitor, and pc-broadcast nodes are dormant Phase 3
concepts with no AuthorityCase for activation. These tests assert that
the topology retains the nodes (for historical completeness) but marks
them quarantined, the conf file is removed, and no allowlist permits
accidental activation into a broadcast/livestream path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.audio_topology import TopologyDescriptor

REPO_ROOT = Path(__file__).resolve().parents[2]
TOPOLOGY_PATH = REPO_ROOT / "config" / "audio-topology.yaml"
ALLOWLIST_PATH = REPO_ROOT / "config" / "audio-conf-allowlist.yaml"
CONF_DIR = REPO_ROOT / "config" / "pipewire"

PC_NODE_IDS = ("pc-router", "pc-monitor", "pc-broadcast")


@pytest.fixture()
def td() -> TopologyDescriptor:
    return TopologyDescriptor.from_yaml(TOPOLOGY_PATH)


class TestPcRouterQuarantine:
    """All three PC router nodes must be quarantined in the topology."""

    @pytest.mark.parametrize("node_id", PC_NODE_IDS)
    def test_node_exists_in_descriptor(self, td: TopologyDescriptor, node_id: str) -> None:
        node = td.node_by_id(node_id)
        assert node is not None

    @pytest.mark.parametrize("node_id", PC_NODE_IDS)
    def test_node_is_quarantined(self, td: TopologyDescriptor, node_id: str) -> None:
        node = td.node_by_id(node_id)
        assert node.params.get("quarantined") is True, (
            f"{node_id} must have quarantined=true in params"
        )

    @pytest.mark.parametrize("node_id", PC_NODE_IDS)
    def test_node_has_quarantine_reason(self, td: TopologyDescriptor, node_id: str) -> None:
        node = td.node_by_id(node_id)
        reason = node.params.get("quarantine_reason", "")
        assert isinstance(reason, str) and len(reason) > 10, (
            f"{node_id} must have a non-trivial quarantine_reason"
        )

    @pytest.mark.parametrize("node_id", PC_NODE_IDS)
    def test_node_description_says_quarantined(self, td: TopologyDescriptor, node_id: str) -> None:
        node = td.node_by_id(node_id)
        assert "QUARANTINED" in node.description


class TestPcRouterConfRemoved:
    """The PipeWire conf file must not exist — it's the activation path."""

    def test_pc_router_conf_absent(self) -> None:
        conf = CONF_DIR / "hapax-pc-router.conf"
        assert not conf.exists(), (
            "hapax-pc-router.conf must be removed to prevent accidental activation"
        )

    def test_allowlist_does_not_list_pc_router_conf(self) -> None:
        text = ALLOWLIST_PATH.read_text(encoding="utf-8")
        assert "- hapax-pc-router.conf" not in text, (
            "allowlist must not list hapax-pc-router.conf as a valid orphan"
        )


class TestNoBroadcastActivationPath:
    """PC audio must have no desired path to broadcast/livestream nodes."""

    BROADCAST_TARGETS = (
        "livestream-tap",
        "broadcast-master",
        "broadcast-normalized",
        "obs-broadcast-remap",
    )

    def test_pc_broadcast_has_no_desired_link_to_broadcast_chain(
        self, td: TopologyDescriptor
    ) -> None:
        """pc-broadcast edges must not reach any broadcast-chain node."""
        reachable: set[str] = set()
        frontier = {"pc-broadcast"}
        while frontier:
            current = frontier.pop()
            if current in reachable:
                continue
            reachable.add(current)
            for edge in td.edges_from(current):
                frontier.add(edge.target)

        for target in self.BROADCAST_TARGETS:
            assert target not in reachable, f"quarantined pc-broadcast must not reach {target}"

    def test_no_non_quarantined_node_routes_pc_to_l12(self, td: TopologyDescriptor) -> None:
        """No active (non-quarantined) node should route PC audio to L-12."""
        for node in td.nodes:
            if node.params.get("quarantined"):
                continue
            target = node.params.get("playback_target", "")
            if isinstance(target, str) and "ZOOM" in target:
                assert "pc" not in node.id.lower(), f"active node {node.id} routes PC audio to L-12"
