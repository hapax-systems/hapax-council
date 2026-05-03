"""Schema model tests — every model class roundtrips, frozen + extra-forbid
enforced, invariants reject malformed input."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.audio_graph.schema import (
    AudioGraph,
    AudioLink,
    AudioNode,
    BroadcastInvariant,
    ChannelMap,
    DownmixStrategy,
    FormatSpec,
    GainStage,
    LoopbackTopology,
    NodeKind,
)


class TestChannelMap:
    def test_construct_with_count_and_positions(self) -> None:
        cm = ChannelMap(count=2, positions=("FL", "FR"))
        assert cm.count == 2
        assert cm.positions == ("FL", "FR")

    def test_count_only_no_positions(self) -> None:
        cm = ChannelMap(count=2)
        assert cm.count == 2
        assert cm.positions == ()

    def test_positions_must_match_count(self) -> None:
        with pytest.raises(ValidationError):
            ChannelMap(count=2, positions=("FL", "FR", "RL"))

    def test_count_below_one_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ChannelMap(count=0)

    def test_count_above_64_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ChannelMap(count=65)

    def test_frozen(self) -> None:
        cm = ChannelMap(count=2, positions=("FL", "FR"))
        with pytest.raises(ValidationError):
            cm.count = 3  # type: ignore[misc]

    def test_extra_forbid(self) -> None:
        with pytest.raises(ValidationError):
            ChannelMap(count=2, positions=("FL", "FR"), unknown_field=42)  # type: ignore[call-arg]

    def test_round_trip_via_model_dump(self) -> None:
        cm = ChannelMap(count=4, positions=("FL", "FR", "RL", "RR"))
        cm2 = ChannelMap(**cm.model_dump())
        assert cm == cm2


class TestFormatSpec:
    def test_construct(self) -> None:
        fs = FormatSpec(rate_hz=48000, channels=2)
        assert fs.rate_hz == 48000
        assert fs.format == "s32"
        assert fs.channels == 2

    def test_rate_below_8k_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FormatSpec(rate_hz=4000, channels=2)

    def test_format_must_be_known(self) -> None:
        with pytest.raises(ValidationError):
            FormatSpec(rate_hz=48000, channels=2, format="bogus")  # type: ignore[arg-type]

    def test_extra_forbid(self) -> None:
        with pytest.raises(ValidationError):
            FormatSpec(rate_hz=48000, channels=2, extra=1)  # type: ignore[call-arg]

    def test_frozen(self) -> None:
        fs = FormatSpec(rate_hz=48000, channels=2)
        with pytest.raises(ValidationError):
            fs.channels = 3  # type: ignore[misc]


class TestAudioNode:
    def test_construct_filter_chain(self) -> None:
        node = AudioNode(
            id="my-chain",
            kind=NodeKind.FILTER_CHAIN,
            pipewire_name="my-chain",
        )
        assert node.id == "my-chain"
        assert node.kind == NodeKind.FILTER_CHAIN

    def test_id_must_be_kebab_lowercase(self) -> None:
        with pytest.raises(ValidationError):
            AudioNode(
                id="My-Chain",
                kind=NodeKind.FILTER_CHAIN,
                pipewire_name="my-chain",
            )

    def test_id_no_whitespace(self) -> None:
        with pytest.raises(ValidationError):
            AudioNode(
                id="my chain",
                kind=NodeKind.FILTER_CHAIN,
                pipewire_name="my-chain",
            )

    def test_alsa_source_requires_hw(self) -> None:
        with pytest.raises(ValidationError):
            AudioNode(
                id="alsa-src",
                kind=NodeKind.ALSA_SOURCE,
                pipewire_name="alsa_input.foo",
            )

    def test_alsa_source_with_hw_ok(self) -> None:
        node = AudioNode(
            id="alsa-src",
            kind=NodeKind.ALSA_SOURCE,
            pipewire_name="alsa_input.foo",
            hw="hw:CARD=L12",
            channels=ChannelMap(count=14, positions=tuple(f"AUX{i}" for i in range(14))),
        )
        assert node.hw == "hw:CARD=L12"

    def test_filter_chain_no_hw_required(self) -> None:
        node = AudioNode(
            id="my-chain",
            kind=NodeKind.FILTER_CHAIN,
            pipewire_name="my-chain",
        )
        assert node.hw is None

    def test_extra_forbid(self) -> None:
        with pytest.raises(ValidationError):
            AudioNode(
                id="my-chain",
                kind=NodeKind.FILTER_CHAIN,
                pipewire_name="my-chain",
                bogus_field=1,  # type: ignore[call-arg]
            )

    def test_frozen(self) -> None:
        node = AudioNode(
            id="my-chain",
            kind=NodeKind.FILTER_CHAIN,
            pipewire_name="my-chain",
        )
        with pytest.raises(ValidationError):
            node.id = "other"  # type: ignore[misc]

    def test_round_trip(self) -> None:
        node = AudioNode(
            id="my-chain",
            kind=NodeKind.FILTER_CHAIN,
            pipewire_name="my-chain",
            description="desc",
            params={"key": "value", "n": 5, "active": True},
        )
        d = node.model_dump()
        node2 = AudioNode(**d)
        assert node == node2


class TestAudioLink:
    def test_basic(self) -> None:
        link = AudioLink(source="a", target="b")
        assert link.makeup_gain_db == 0.0

    def test_gain_in_range(self) -> None:
        AudioLink(source="a", target="b", makeup_gain_db=24.0)
        AudioLink(source="a", target="b", makeup_gain_db=-50.0)

    def test_gain_above_30_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AudioLink(source="a", target="b", makeup_gain_db=50.0)

    def test_gain_below_minus_60_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AudioLink(source="a", target="b", makeup_gain_db=-100.0)

    def test_gain_nan_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AudioLink(source="a", target="b", makeup_gain_db=float("nan"))

    def test_extra_forbid(self) -> None:
        with pytest.raises(ValidationError):
            AudioLink(source="a", target="b", extra=1)  # type: ignore[call-arg]

    def test_frozen(self) -> None:
        link = AudioLink(source="a", target="b")
        with pytest.raises(ValidationError):
            link.source = "c"  # type: ignore[misc]


class TestGainStage:
    def test_basic(self) -> None:
        gs = GainStage(edge_source="a", edge_target="b", base_gain_db=3.0)
        assert gs.base_gain_db == 3.0

    def test_per_channel_overrides_in_range(self) -> None:
        gs = GainStage(
            edge_source="a",
            edge_target="b",
            base_gain_db=0.0,
            per_channel_overrides={"AUX1": 6.0, "AUX2": -12.0},
        )
        assert gs.per_channel_overrides["AUX1"] == 6.0

    def test_per_channel_overrides_out_of_range_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GainStage(
                edge_source="a",
                edge_target="b",
                per_channel_overrides={"AUX1": 100.0},
            )

    def test_declared_bleed_db_optional(self) -> None:
        gs = GainStage(edge_source="a", edge_target="b")
        assert gs.declared_bleed_db is None
        gs2 = GainStage(edge_source="a", edge_target="b", declared_bleed_db=27.0)
        assert gs2.declared_bleed_db == 27.0

    def test_downmix_strategy(self) -> None:
        gs = GainStage(
            edge_source="a",
            edge_target="b",
            downmix_strategy=DownmixStrategy.MIXDOWN,
            downmix_map={"FL": "AUX1+AUX2"},
        )
        assert gs.downmix_strategy == DownmixStrategy.MIXDOWN

    def test_extra_forbid(self) -> None:
        with pytest.raises(ValidationError):
            GainStage(edge_source="a", edge_target="b", bogus=1)  # type: ignore[call-arg]

    def test_frozen(self) -> None:
        gs = GainStage(edge_source="a", edge_target="b")
        with pytest.raises(ValidationError):
            gs.base_gain_db = 5.0  # type: ignore[misc]


class TestLoopbackTopology:
    def test_basic(self) -> None:
        lb = LoopbackTopology(node_id="n", source="s", sink="t")
        assert lb.source_dont_move is True
        assert lb.sink_dont_move is True
        assert lb.fail_closed_on_target_absent is True

    def test_apply_via_pactl_load_default_false(self) -> None:
        lb = LoopbackTopology(node_id="n", source="s", sink="t")
        assert lb.apply_via_pactl_load is False

    def test_latency_in_range(self) -> None:
        with pytest.raises(ValidationError):
            LoopbackTopology(node_id="n", source="s", sink="t", latency_msec=0)

    def test_extra_forbid(self) -> None:
        with pytest.raises(ValidationError):
            LoopbackTopology(node_id="n", source="s", sink="t", extra=1)  # type: ignore[call-arg]

    def test_frozen(self) -> None:
        lb = LoopbackTopology(node_id="n", source="s", sink="t")
        with pytest.raises(ValidationError):
            lb.node_id = "other"  # type: ignore[misc]


class TestBroadcastInvariant:
    def test_basic(self) -> None:
        bi = BroadcastInvariant(
            kind="private_never_broadcasts",
            description="...",
            check_fn_name="check_private_never_broadcasts",
        )
        assert bi.severity == "blocking"
        assert bi.continuous is False

    def test_severity_must_be_known(self) -> None:
        with pytest.raises(ValidationError):
            BroadcastInvariant(
                kind="x",
                severity="bogus",  # type: ignore[arg-type]
                description="...",
                check_fn_name="...",
            )


class TestAudioGraph:
    def test_empty_graph(self) -> None:
        g = AudioGraph()
        assert g.nodes == ()
        assert g.links == ()
        assert g.schema_version == 1

    def test_construct_with_nodes_and_links(self) -> None:
        n1 = AudioNode(id="a", kind=NodeKind.NULL_SINK, pipewire_name="a")
        n2 = AudioNode(id="b", kind=NodeKind.NULL_SINK, pipewire_name="b")
        link = AudioLink(source="a", target="b")
        g = AudioGraph(nodes=(n1, n2), links=(link,))
        assert len(g.nodes) == 2
        assert len(g.links) == 1

    def test_dangling_link_rejected(self) -> None:
        n1 = AudioNode(id="a", kind=NodeKind.NULL_SINK, pipewire_name="a")
        with pytest.raises(ValidationError):
            AudioGraph(nodes=(n1,), links=(AudioLink(source="a", target="missing"),))

    def test_duplicate_node_id_rejected(self) -> None:
        n1 = AudioNode(id="a", kind=NodeKind.NULL_SINK, pipewire_name="a")
        n2 = AudioNode(id="a", kind=NodeKind.NULL_SINK, pipewire_name="a-2")
        with pytest.raises(ValidationError):
            AudioGraph(nodes=(n1, n2))

    def test_dangling_gain_stage_rejected(self) -> None:
        n1 = AudioNode(id="a", kind=NodeKind.NULL_SINK, pipewire_name="a")
        with pytest.raises(ValidationError):
            AudioGraph(
                nodes=(n1,),
                gain_stages=(GainStage(edge_source="a", edge_target="missing"),),
            )

    def test_dangling_loopback_rejected(self) -> None:
        n1 = AudioNode(id="a", kind=NodeKind.NULL_SINK, pipewire_name="a")
        with pytest.raises(ValidationError):
            AudioGraph(
                nodes=(n1,),
                loopbacks=(LoopbackTopology(node_id="missing", source="x", sink="y"),),
            )

    def test_node_by_id(self) -> None:
        n1 = AudioNode(id="a", kind=NodeKind.NULL_SINK, pipewire_name="a")
        g = AudioGraph(nodes=(n1,))
        assert g.node_by_id("a") == n1
        with pytest.raises(KeyError):
            g.node_by_id("missing")

    def test_links_from_to(self) -> None:
        n1 = AudioNode(id="a", kind=NodeKind.NULL_SINK, pipewire_name="a")
        n2 = AudioNode(id="b", kind=NodeKind.NULL_SINK, pipewire_name="b")
        n3 = AudioNode(id="c", kind=NodeKind.NULL_SINK, pipewire_name="c")
        l1 = AudioLink(source="a", target="b")
        l2 = AudioLink(source="b", target="c")
        g = AudioGraph(nodes=(n1, n2, n3), links=(l1, l2))
        assert g.links_from("a") == (l1,)
        assert g.links_to("c") == (l2,)
        assert g.links_from("c") == ()

    def test_round_trip(self) -> None:
        n1 = AudioNode(id="a", kind=NodeKind.NULL_SINK, pipewire_name="a")
        g1 = AudioGraph(nodes=(n1,), description="desc")
        g2 = AudioGraph(**g1.model_dump())
        assert g1 == g2

    def test_extra_forbid(self) -> None:
        with pytest.raises(ValidationError):
            AudioGraph(bogus=1)  # type: ignore[call-arg]

    def test_frozen(self) -> None:
        g = AudioGraph()
        with pytest.raises(ValidationError):
            g.description = "x"  # type: ignore[misc]
