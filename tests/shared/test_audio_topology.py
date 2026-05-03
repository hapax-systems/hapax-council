"""Tests for shared.audio_topology — descriptor schema round-trips + validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.audio_topology import (
    ChannelMap,
    Edge,
    Node,
    NodeKind,
    TopologyDescriptor,
)


class TestChannelMap:
    def test_stereo_default(self) -> None:
        cm = ChannelMap(count=2, positions=["FL", "FR"])
        assert cm.count == 2

    def test_positions_length_must_match(self) -> None:
        with pytest.raises(ValidationError, match="positions length"):
            ChannelMap(count=2, positions=["FL", "FR", "FC"])

    def test_positions_empty_allowed(self) -> None:
        """Count-only (no position list) means 'let PipeWire default'."""
        cm = ChannelMap(count=2)
        assert cm.positions == []

    def test_multitrack_l6(self) -> None:
        cm = ChannelMap(count=12, positions=[f"AUX{i}" for i in range(12)])
        assert len(cm.positions) == 12


class TestNode:
    def test_alsa_source_requires_hw(self) -> None:
        with pytest.raises(ValidationError, match="hw"):
            Node(
                id="l6-capture",
                kind=NodeKind.ALSA_SOURCE,
                pipewire_name="alsa_input.usb-ZOOM_L6-00",
            )

    def test_alsa_sink_requires_hw(self) -> None:
        with pytest.raises(ValidationError, match="hw"):
            Node(
                id="ryzen-out",
                kind=NodeKind.ALSA_SINK,
                pipewire_name="alsa_output.pci-0000_73_00.6.analog-stereo",
            )

    def test_filter_chain_no_hw_required(self) -> None:
        """filter_chain nodes bind via target_object, not ALSA PCM."""
        n = Node(
            id="voice-fx",
            kind=NodeKind.FILTER_CHAIN,
            pipewire_name="hapax-voice-fx-capture",
            target_object="alsa_output.pci-0000_73_00.6.analog-stereo",
        )
        assert n.hw is None
        assert n.target_object is not None

    def test_id_must_be_kebab(self) -> None:
        with pytest.raises(ValidationError, match="kebab-case"):
            Node(
                id="HapaxVoiceFX",  # PascalCase — rejected
                kind=NodeKind.FILTER_CHAIN,
                pipewire_name="x",
            )

    def test_id_rejects_whitespace(self) -> None:
        with pytest.raises(ValidationError, match="kebab-case"):
            Node(id="voice fx", kind=NodeKind.FILTER_CHAIN, pipewire_name="x")


class TestEdge:
    def test_gain_must_be_in_range(self) -> None:
        with pytest.raises(ValidationError, match="-60, \\+30"):
            Edge(source="a", target="b", makeup_gain_db=50.0)

    def test_negative_gain_allowed(self) -> None:
        e = Edge(source="a", target="b", makeup_gain_db=-12.0)
        assert e.makeup_gain_db == -12.0

    def test_zero_gain_default(self) -> None:
        e = Edge(source="a", target="b")
        assert e.makeup_gain_db == 0.0

    def test_gain_nan_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Edge(source="a", target="b", makeup_gain_db=float("nan"))

    def test_ports_optional(self) -> None:
        e = Edge(source="a", target="b")
        assert e.source_port is None
        assert e.target_port is None


class TestTopologyDescriptor:
    def _minimal(self) -> TopologyDescriptor:
        return TopologyDescriptor(
            schema_version=2,
            description="minimal",
            nodes=[
                Node(
                    id="l6-capture",
                    kind=NodeKind.ALSA_SOURCE,
                    pipewire_name="alsa_input.usb-ZOOM_L6-00",
                    hw="hw:L6,0",
                ),
                Node(
                    id="livestream-tap",
                    kind=NodeKind.TAP,
                    pipewire_name="hapax-livestream-tap",
                ),
            ],
            edges=[Edge(source="l6-capture", target="livestream-tap")],
        )

    def test_construct_minimal(self) -> None:
        d = self._minimal()
        assert len(d.nodes) == 2
        assert len(d.edges) == 1

    def test_rejects_duplicate_node_ids(self) -> None:
        with pytest.raises(ValidationError, match="Duplicate"):
            TopologyDescriptor(
                nodes=[
                    Node(
                        id="l6",
                        kind=NodeKind.ALSA_SOURCE,
                        pipewire_name="x",
                        hw="hw:L6,0",
                    ),
                    Node(
                        id="l6",  # dup
                        kind=NodeKind.ALSA_SINK,
                        pipewire_name="y",
                        hw="hw:L6,1",
                    ),
                ],
            )

    def test_rejects_dangling_edge_source(self) -> None:
        with pytest.raises(ValidationError, match="source not in"):
            TopologyDescriptor(
                nodes=[
                    Node(id="a", kind=NodeKind.TAP, pipewire_name="a"),
                ],
                edges=[Edge(source="nonexistent", target="a")],
            )

    def test_rejects_dangling_edge_target(self) -> None:
        with pytest.raises(ValidationError, match="target not in"):
            TopologyDescriptor(
                nodes=[
                    Node(id="a", kind=NodeKind.TAP, pipewire_name="a"),
                ],
                edges=[Edge(source="a", target="nonexistent")],
            )

    def test_node_by_id(self) -> None:
        d = self._minimal()
        n = d.node_by_id("l6-capture")
        assert n.kind == NodeKind.ALSA_SOURCE

    def test_node_by_id_raises(self) -> None:
        d = self._minimal()
        with pytest.raises(KeyError):
            d.node_by_id("missing")

    def test_edges_from_and_to(self) -> None:
        d = self._minimal()
        assert len(d.edges_from("l6-capture")) == 1
        assert len(d.edges_to("livestream-tap")) == 1
        assert d.edges_from("livestream-tap") == []

    def test_yaml_round_trip(self) -> None:
        d = self._minimal()
        text = d.to_yaml()
        reloaded = TopologyDescriptor.from_yaml(text)
        assert reloaded.nodes == d.nodes
        assert reloaded.edges == d.edges
        assert reloaded.schema_version == 2

    def test_yaml_captures_filter_chain(self) -> None:
        """Real-world descriptor round-trip with all node kinds."""
        d = TopologyDescriptor(
            description="workstation reference topology",
            nodes=[
                Node(
                    id="l6-capture",
                    kind=NodeKind.ALSA_SOURCE,
                    pipewire_name="alsa_input.usb-ZOOM_L6-00.multitrack",
                    hw="hw:L6,0",
                    channels=ChannelMap(count=12, positions=[f"AUX{i}" for i in range(12)]),
                ),
                Node(
                    id="voice-fx",
                    kind=NodeKind.FILTER_CHAIN,
                    pipewire_name="hapax-voice-fx-capture",
                    target_object="alsa_output.pci-0000_73_00.6.analog-stereo",
                ),
                Node(
                    id="main-mix-tap",
                    kind=NodeKind.FILTER_CHAIN,
                    pipewire_name="hapax-l6-evilpet-capture",
                    target_object="alsa_input.usb-ZOOM_L6-00.multitrack",
                    params={"makeup_gain_linear": 4.0},
                ),
                Node(
                    id="livestream-tap",
                    kind=NodeKind.TAP,
                    pipewire_name="hapax-livestream-tap",
                ),
                Node(
                    id="ryzen-out",
                    kind=NodeKind.ALSA_SINK,
                    pipewire_name="alsa_output.pci-0000_73_00.6.analog-stereo",
                    hw="hw:0,0",
                ),
            ],
            edges=[
                Edge(
                    source="l6-capture",
                    source_port="AUX10",
                    target="main-mix-tap",
                    target_port="FL",
                    makeup_gain_db=12.0,
                ),
                Edge(
                    source="l6-capture",
                    source_port="AUX11",
                    target="main-mix-tap",
                    target_port="FR",
                    makeup_gain_db=12.0,
                ),
                Edge(source="main-mix-tap", target="livestream-tap"),
                Edge(source="voice-fx", target="ryzen-out"),
            ],
        )
        text = d.to_yaml()
        reloaded = TopologyDescriptor.from_yaml(text)
        assert reloaded == d

    def test_schema_version_pinned(self) -> None:
        with pytest.raises(ValidationError):
            TopologyDescriptor(
                schema_version=3,  # future; not yet supported
                nodes=[Node(id="a", kind=NodeKind.TAP, pipewire_name="x")],
            )
