"""Compiler tests — deterministic byte-for-byte output, schema match."""

from __future__ import annotations

from shared.audio_graph.compiler import (
    CompiledArtefacts,
    PactlLoad,
    PostApplyProbe,
    RollbackPlan,
    compile_descriptor,
)
from shared.audio_graph.invariants import InvariantKind, InvariantSeverity
from shared.audio_graph.schema import (
    AudioGraph,
    AudioLink,
    AudioNode,
    ChannelMap,
    DownmixStrategy,
    GainStage,
    LoopbackTopology,
    NodeKind,
)


def _node(
    id_: str,
    *,
    kind: NodeKind = NodeKind.NULL_SINK,
    pipewire_name: str | None = None,
    channels: ChannelMap | None = None,
    params: dict[str, str | int | float | bool] | None = None,
) -> AudioNode:
    return AudioNode(
        id=id_,
        kind=kind,
        pipewire_name=pipewire_name or id_,
        channels=channels or ChannelMap(count=2, positions=("FL", "FR")),
        params=params or {},
    )


class TestCompilerOutputShape:
    def test_returns_compiled_artefacts(self) -> None:
        g = AudioGraph()
        out = compile_descriptor(g)
        assert isinstance(out, CompiledArtefacts)

    def test_empty_graph_emits_no_confs(self) -> None:
        g = AudioGraph()
        out = compile_descriptor(g)
        assert out.confs_to_write == {}
        assert out.pactl_loadmodule_invocations == ()
        assert out.postapply_probes == ()
        assert isinstance(out.rollback_plan, RollbackPlan)
        assert len(out.rollback_plan.snapshot_id) == 64  # sha256 hex

    def test_has_five_artefact_fields(self) -> None:
        out = compile_descriptor(AudioGraph())
        assert hasattr(out, "confs_to_write")
        assert hasattr(out, "pactl_loadmodule_invocations")
        assert hasattr(out, "preflight_checks")
        assert hasattr(out, "postapply_probes")
        assert hasattr(out, "rollback_plan")


class TestCompilerInvariantGate:
    def test_blocking_violation_refuses_emission(self) -> None:
        # private node with edge to broadcast — guaranteed BLOCKING violation
        priv = _node("private-sink", params={"private_monitor_endpoint": True})
        bcast = _node("hapax-livestream-tap")
        link = AudioLink(source="private-sink", target="hapax-livestream-tap")
        g = AudioGraph(nodes=(priv, bcast), links=(link,))
        out = compile_descriptor(g)

        assert out.confs_to_write == {}
        assert out.pactl_loadmodule_invocations == ()
        assert out.postapply_probes == ()
        # Preflight checks SHOULD include the blocking violation
        assert any(
            v.kind == InvariantKind.PRIVATE_NEVER_BROADCASTS
            and v.severity == InvariantSeverity.BLOCKING
            for v in out.preflight_checks
        )

    def test_clean_graph_emits_confs(self) -> None:
        n = _node("hapax-livestream-tap", kind=NodeKind.NULL_SINK)
        g = AudioGraph(nodes=(n,))
        out = compile_descriptor(g)
        assert "hapax-livestream-tap.conf" in out.confs_to_write


class TestCompilerDeterminism:
    def test_same_input_same_bytes(self) -> None:
        n1 = _node("a")
        n2 = _node("b")
        g = AudioGraph(nodes=(n1, n2))
        out_a = compile_descriptor(g).model_dump_json()
        out_b = compile_descriptor(g).model_dump_json()
        assert out_a == out_b

    def test_node_order_does_not_affect_output(self) -> None:
        # Nodes given in different order should produce same compiled output
        # (because the compiler sorts by id internally).
        n1 = _node("a")
        n2 = _node("b")
        n3 = _node("c")
        g_abc = AudioGraph(nodes=(n1, n2, n3))
        g_cba = AudioGraph(nodes=(n3, n2, n1))
        # The graphs themselves differ in node ordering but compiled
        # confs_to_write keys should be identical (sorted) and bodies
        # identical.
        out_abc = compile_descriptor(g_abc)
        out_cba = compile_descriptor(g_cba)
        assert out_abc.confs_to_write == out_cba.confs_to_write

    def test_rollback_id_content_addressed(self) -> None:
        n = _node("a")
        g = AudioGraph(nodes=(n,))
        out_1 = compile_descriptor(g)
        out_2 = compile_descriptor(g)
        assert out_1.rollback_plan.snapshot_id == out_2.rollback_plan.snapshot_id

    def test_rollback_id_changes_with_input(self) -> None:
        g_a = AudioGraph(nodes=(_node("a"),))
        g_b = AudioGraph(nodes=(_node("b"),))
        out_a = compile_descriptor(g_a)
        out_b = compile_descriptor(g_b)
        assert out_a.rollback_plan.snapshot_id != out_b.rollback_plan.snapshot_id


class TestCompilerConfEmission:
    def test_null_sink_emits_support_null_audio_sink(self) -> None:
        n = _node(
            "hapax-livestream-tap",
            kind=NodeKind.NULL_SINK,
            channels=ChannelMap(count=2, positions=("FL", "FR")),
        )
        g = AudioGraph(nodes=(n,))
        out = compile_descriptor(g)
        body = out.confs_to_write["hapax-livestream-tap.conf"]
        assert "support.null-audio-sink" in body
        assert "hapax-livestream-tap" in body

    def test_loopback_emits_module_loopback(self) -> None:
        n = AudioNode(
            id="my-loopback",
            kind=NodeKind.LOOPBACK,
            pipewire_name="hapax-my-loopback",
            target_object="hapax-livestream-tap",
        )
        g = AudioGraph(nodes=(n,))
        out = compile_descriptor(g)
        body = out.confs_to_write["hapax-my-loopback.conf"]
        assert "libpipewire-module-loopback" in body

    def test_filter_chain_with_blob_emits_verbatim(self) -> None:
        n = AudioNode(
            id="my-chain",
            kind=NodeKind.FILTER_CHAIN,
            pipewire_name="hapax-my-chain",
            filter_graph={"__raw_text__": "{ nodes = [] inputs = [] outputs = [] }"},
        )
        g = AudioGraph(nodes=(n,))
        out = compile_descriptor(g)
        body = out.confs_to_write["hapax-my-chain.conf"]
        assert "libpipewire-module-filter-chain" in body
        assert "nodes = []" in body

    def test_filter_chain_without_blob_emits_stub(self) -> None:
        n = AudioNode(id="my-chain", kind=NodeKind.FILTER_CHAIN, pipewire_name="hapax-my-chain")
        g = AudioGraph(nodes=(n,))
        out = compile_descriptor(g)
        body = out.confs_to_write["hapax-my-chain.conf"]
        assert "TODO" in body  # stub marker

    def test_alsa_endpoints_no_conf(self) -> None:
        n = AudioNode(
            id="alsa-src",
            kind=NodeKind.ALSA_SOURCE,
            pipewire_name="alsa_input.foo",
            hw="hw:CARD=Foo",
        )
        g = AudioGraph(nodes=(n,))
        out = compile_descriptor(g)
        # ALSA endpoints don't get conf files
        assert out.confs_to_write == {}


class TestCompilerPactlEmission:
    def test_no_pactl_when_no_pactl_loopbacks(self) -> None:
        lb = LoopbackTopology(node_id="x", source="s", sink="t", apply_via_pactl_load=False)
        n = AudioNode(id="x", kind=NodeKind.LOOPBACK, pipewire_name="x")
        g = AudioGraph(nodes=(n,), loopbacks=(lb,))
        out = compile_descriptor(g)
        assert out.pactl_loadmodule_invocations == ()

    def test_pactl_emitted_for_pactl_loopbacks(self) -> None:
        lb = LoopbackTopology(
            node_id="x", source="my-src", sink="my-sink", apply_via_pactl_load=True
        )
        n = AudioNode(id="x", kind=NodeKind.LOOPBACK, pipewire_name="x")
        g = AudioGraph(nodes=(n,), loopbacks=(lb,))
        out = compile_descriptor(g)
        assert len(out.pactl_loadmodule_invocations) == 1
        pl = out.pactl_loadmodule_invocations[0]
        assert isinstance(pl, PactlLoad)
        assert pl.source == "my-src"
        assert pl.sink == "my-sink"

    def test_pactl_sorted_by_source_sink(self) -> None:
        lb1 = LoopbackTopology(node_id="x1", source="b", sink="z", apply_via_pactl_load=True)
        lb2 = LoopbackTopology(node_id="x2", source="a", sink="z", apply_via_pactl_load=True)
        n1 = AudioNode(id="x1", kind=NodeKind.LOOPBACK, pipewire_name="x1")
        n2 = AudioNode(id="x2", kind=NodeKind.LOOPBACK, pipewire_name="x2")
        g = AudioGraph(nodes=(n1, n2), loopbacks=(lb1, lb2))
        out = compile_descriptor(g)
        assert out.pactl_loadmodule_invocations[0].source == "a"
        assert out.pactl_loadmodule_invocations[1].source == "b"


class TestCompilerProbes:
    def test_egress_probe_emitted(self) -> None:
        tap = AudioNode(
            id="livestream-tap", kind=NodeKind.NULL_SINK, pipewire_name="hapax-livestream-tap"
        )
        obs = AudioNode(
            id="hapax-obs-broadcast-remap",
            kind=NodeKind.LOOPBACK,
            pipewire_name="hapax-obs-broadcast-remap",
        )
        g = AudioGraph(nodes=(tap, obs))
        out = compile_descriptor(g)
        names = [p.name for p in out.postapply_probes]
        assert "obs-egress-band" in names

    def test_private_leak_probe_emitted(self) -> None:
        priv = AudioNode(
            id="role-assistant",
            kind=NodeKind.NULL_SINK,
            pipewire_name="hapax-role-assistant",
            params={"private_monitor_endpoint": True},
        )
        obs = AudioNode(
            id="hapax-obs-broadcast-remap",
            kind=NodeKind.LOOPBACK,
            pipewire_name="hapax-obs-broadcast-remap",
        )
        g = AudioGraph(nodes=(priv, obs))
        out = compile_descriptor(g)
        names = [p.name for p in out.postapply_probes]
        assert any("private-role-assistant" in n for n in names)

    def test_downmix_probe_emitted(self) -> None:
        a = AudioNode(
            id="a",
            kind=NodeKind.FILTER_CHAIN,
            pipewire_name="hapax-a",
            channels=ChannelMap(count=14, positions=tuple(f"AUX{i}" for i in range(14))),
        )
        b = AudioNode(id="b", kind=NodeKind.FILTER_CHAIN, pipewire_name="hapax-b")
        gs = GainStage(
            edge_source="a", edge_target="b", downmix_strategy=DownmixStrategy.CHANNEL_PICK
        )
        g = AudioGraph(nodes=(a, b), gain_stages=(gs,))
        out = compile_descriptor(g)
        names = [p.name for p in out.postapply_probes]
        assert any("downmix-a-to-b" in n for n in names)

    def test_probes_sorted_by_name(self) -> None:
        # Multiple private nodes — should be sorted
        priv1 = AudioNode(
            id="role-zoo",
            kind=NodeKind.NULL_SINK,
            pipewire_name="zoo",
            params={"private_monitor_endpoint": True},
        )
        priv2 = AudioNode(
            id="role-aaa",
            kind=NodeKind.NULL_SINK,
            pipewire_name="aaa",
            params={"private_monitor_endpoint": True},
        )
        obs = AudioNode(
            id="hapax-obs-broadcast-remap",
            kind=NodeKind.LOOPBACK,
            pipewire_name="hapax-obs-broadcast-remap",
        )
        g = AudioGraph(nodes=(priv1, priv2, obs))
        out = compile_descriptor(g)
        names = [p.name for p in out.postapply_probes]
        assert names == sorted(names)


class TestCompilerArtefactsImmutable:
    def test_artefacts_frozen(self) -> None:
        out = compile_descriptor(AudioGraph())
        # Pydantic v2 frozen raises ValidationError on attribute set
        try:
            out.confs_to_write = {"x": "y"}  # type: ignore[misc]
        except Exception:
            return
        raise AssertionError("CompiledArtefacts should be frozen")

    def test_pactl_load_immutable(self) -> None:
        pl = PactlLoad(source="a", sink="b")
        try:
            pl.source = "c"  # type: ignore[misc]
        except Exception:
            return
        raise AssertionError("PactlLoad should be frozen")

    def test_postapply_probe_immutable(self) -> None:
        p = PostApplyProbe(
            name="x",
            sink_to_inject="a",
            source_to_capture="b",
            inject_channels=2,
            expected_outcome="detected",
        )
        try:
            p.name = "y"  # type: ignore[misc]
        except Exception:
            return
        raise AssertionError("PostApplyProbe should be frozen")
