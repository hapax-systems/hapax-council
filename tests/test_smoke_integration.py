"""Integration smoke tests for capability parity (PRs #436-#440).

Exercises cross-module integration that unit tests don't cover:
1. Cross-import from daimonion and Reverie code paths
2. CapabilityRegistry holding tools + speech + visual simultaneously
3. ContextAssembler reading live /dev/shm files
4. VisualGovernance veto + fallback composition
5. SignalBus concurrent publish/snapshot from multiple threads
6. ExpressionCoordinator distributing fragments to speech and visual
"""

from __future__ import annotations

import json
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

from shared.capability import (
    Capability,
    CapabilityCategory,
    CapabilityRegistry,
    ResourceTier,
    SystemContext,
)
from shared.capability_adapters import PerceptionBackendAdapter
from shared.context import ContextAssembler, EnrichmentContext
from shared.expression import (
    ExpressionCoordinator,
    map_fragment_to_material_uniform,
    map_fragment_to_visual,
)
from shared.governance import FallbackChain, Veto, VetoChain
from shared.governance.primitives import Candidate
from shared.signal_bus import SignalBus, SignalModulationBinding

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_ctx(**overrides) -> SystemContext:
    defaults = {
        "stimmung_stance": "nominal",
        "consent_state": {},
        "guest_present": False,
        "active_backends": frozenset(),
        "working_mode": "rnd",
        "experiment_flags": {},
        "tpn_active": False,
    }
    defaults.update(overrides)
    return SystemContext(**defaults)


class _StubCapability:
    """Minimal Capability implementation for registry tests."""

    def __init__(self, name: str, category: CapabilityCategory, available: bool = True):
        self._name = name
        self._category = category
        self._available = available

    @property
    def name(self) -> str:
        return self._name

    @property
    def category(self) -> CapabilityCategory:
        return self._category

    @property
    def resource_tier(self) -> ResourceTier:
        return ResourceTier.LIGHT

    def available(self, ctx: SystemContext) -> bool:
        return self._available

    def degrade(self) -> str:
        return f"{self._name} degraded"


class _StubBackend:
    """Minimal perception backend for adapter tests."""

    def __init__(self, name: str, available: bool = True):
        self.name = name
        self.tier = MagicMock(value="fast")
        self._available = available

    def available(self) -> bool:
        return self._available


# ── 1. Cross-Import Integration ─────────────────────────────────────────────


class TestCrossImport(unittest.TestCase):
    """Verify shared modules import correctly from both daimonion and Reverie."""

    def test_daimonion_tool_definitions_import(self):
        """tool_definitions.py imports shared.capability.CapabilityRegistry."""
        from agents.hapax_daimonion.tool_definitions import build_registry

        reg = build_registry(guest_mode=True)
        assert reg is not None

    def test_visual_governance_import(self):
        """visual_governance.py imports shared.governance primitives."""
        from agents.effect_graph.visual_governance import VisualGovernance

        gov = VisualGovernance()
        assert gov is not None

    def test_capability_protocol_isinstance(self):
        """StubCapability satisfies the Capability protocol at runtime."""
        cap = _StubCapability("test", CapabilityCategory.TOOL)
        assert isinstance(cap, Capability)

    def test_perception_adapter_isinstance(self):
        """PerceptionBackendAdapter satisfies the Capability protocol."""
        backend = _StubBackend("ir_presence")
        adapter = PerceptionBackendAdapter(backend)
        assert isinstance(adapter, Capability)


# ── 2. Mixed-Category Registry ──────────────────────────────────────────────


class TestMixedRegistry(unittest.TestCase):
    """CapabilityRegistry holds tools + speech + visual + perception simultaneously."""

    def setUp(self):
        self.reg = CapabilityRegistry()
        self.tool = _StubCapability("search_qdrant", CapabilityCategory.TOOL)
        self.speech = _StubCapability("speech_output", CapabilityCategory.EXPRESSION)
        self.visual = _StubCapability("shader_bloom", CapabilityCategory.EXPRESSION)
        self.perception = PerceptionBackendAdapter(_StubBackend("ir_presence"))
        self.reg.register(self.tool)
        self.reg.register(self.speech)
        self.reg.register(self.visual)
        self.reg.register(self.perception)

    def test_all_four_registered(self):
        assert len(self.reg.all()) == 4

    def test_filter_by_category(self):
        ctx = _make_ctx()
        tools = self.reg.available(ctx, CapabilityCategory.TOOL)
        assert len(tools) == 1
        assert tools[0].name == "search_qdrant"

    def test_filter_expression(self):
        ctx = _make_ctx()
        expr = self.reg.available(ctx, CapabilityCategory.EXPRESSION)
        assert len(expr) == 2
        names = {c.name for c in expr}
        assert names == {"speech_output", "shader_bloom"}

    def test_filter_perception(self):
        ctx = _make_ctx()
        perc = self.reg.available(ctx, CapabilityCategory.PERCEPTION)
        assert len(perc) == 1
        assert perc[0].name == "ir_presence"

    def test_unavailable_filtered(self):
        """Unavailable capability excluded from available() but still in all()."""
        dead = _StubCapability("dead_backend", CapabilityCategory.PERCEPTION, available=False)
        self.reg.register(dead)
        ctx = _make_ctx()
        assert len(self.reg.all()) == 5
        assert len(self.reg.available(ctx, CapabilityCategory.PERCEPTION)) == 1

    def test_duplicate_name_raises(self):
        dup = _StubCapability("search_qdrant", CapabilityCategory.TOOL)
        with self.assertRaises(ValueError):
            self.reg.register(dup)


# ── 3. Context Assembler with SHM ──────────────────────────────────────────


class TestContextAssemblerSHM(unittest.TestCase):
    """ContextAssembler reads from filesystem paths (simulated /dev/shm)."""

    def setUp(self):
        self.tmpdir = TemporaryDirectory()
        self.tmp = Path(self.tmpdir.name)
        self.stimmung = self.tmp / "stimmung" / "state.json"
        self.stimmung.parent.mkdir(parents=True)
        self.dmn_buffer = self.tmp / "dmn" / "buffer.txt"
        self.dmn_buffer.parent.mkdir(parents=True)
        self.imagination = self.tmp / "imagination" / "current.json"
        self.imagination.parent.mkdir(parents=True)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _assembler(self, **kwargs):
        return ContextAssembler(
            stimmung_path=self.stimmung,
            dmn_buffer_path=self.dmn_buffer,
            imagination_path=self.imagination,
            **kwargs,
        )

    def test_missing_files_returns_nominal(self):
        """No SHM files → nominal defaults, no crash."""
        asm = self._assembler()
        ctx = asm.assemble()
        assert isinstance(ctx, EnrichmentContext)
        assert ctx.stimmung_stance == "nominal"
        assert ctx.dmn_observations == []
        assert ctx.imagination_fragments == []

    def test_reads_stimmung_stance(self):
        self.stimmung.write_text(json.dumps({"overall_stance": "degraded", "score": 42}))
        asm = self._assembler()
        ctx = asm.assemble()
        assert ctx.stimmung_stance == "degraded"
        assert ctx.stimmung_raw["score"] == 42

    def test_reads_dmn_buffer(self):
        self.dmn_buffer.write_text("I notice the operator seems tired")
        asm = self._assembler()
        ctx = asm.assemble()
        assert len(ctx.dmn_observations) == 1
        assert "tired" in ctx.dmn_observations[0]

    def test_reads_imagination_fragment(self):
        fragment = {"narrative": "A river of light", "dimensions": {"luminosity": 0.8}}
        self.imagination.write_text(json.dumps(fragment))
        asm = self._assembler()
        ctx = asm.assemble()
        assert len(ctx.imagination_fragments) == 1
        assert ctx.imagination_fragments[0]["narrative"] == "A river of light"

    def test_caching_ttl(self):
        """Second call within TTL returns cached snapshot."""
        self.stimmung.write_text(json.dumps({"overall_stance": "nominal"}))
        asm = self._assembler()
        ctx1 = asm.assemble()
        # Overwrite file — should still get cached result
        self.stimmung.write_text(json.dumps({"overall_stance": "critical"}))
        ctx2 = asm.assemble()
        assert ctx1 is ctx2  # same object = cache hit

    def test_invalidate_forces_reread(self):
        self.stimmung.write_text(json.dumps({"overall_stance": "nominal"}))
        asm = self._assembler()
        ctx1 = asm.assemble()
        self.stimmung.write_text(json.dumps({"overall_stance": "critical"}))
        asm.invalidate()
        ctx2 = asm.assemble()
        assert ctx2.stimmung_stance == "critical"
        assert ctx1 is not ctx2

    def test_callable_sources_integrated(self):
        """Goals, health, nudges, perception callables are invoked."""
        asm = self._assembler(
            goals_fn=lambda: [{"name": "ship"}],
            health_fn=lambda: {"status": "ok"},
            nudges_fn=lambda: [{"id": "n1"}],
            perception_fn=lambda: {"person_count": 1},
        )
        ctx = asm.assemble()
        assert len(ctx.active_goals) == 1
        assert ctx.health_summary["status"] == "ok"
        assert len(ctx.pending_nudges) == 1
        assert ctx.perception_snapshot["person_count"] == 1

    def test_failing_callable_returns_default(self):
        """A throwing callable returns default, doesn't crash assembler."""

        def boom():
            raise RuntimeError("service down")

        asm = self._assembler(goals_fn=boom, health_fn=boom)
        ctx = asm.assemble()
        assert ctx.active_goals == []
        assert ctx.health_summary == {}


# ── 4. Governance Composition (cross-module) ────────────────────────────────


class TestGovernanceComposition(unittest.TestCase):
    """VetoChain + FallbackChain composed across shared and visual_governance."""

    def test_veto_chain_composition(self):
        """Two VetoChains from different modules compose via |."""
        chain_a: VetoChain[SystemContext] = VetoChain(
            [Veto("consent", lambda ctx: not ctx.guest_present)]
        )
        chain_b: VetoChain[SystemContext] = VetoChain(
            [Veto("experiment", lambda ctx: ctx.working_mode == "rnd")]
        )
        combined = chain_a | chain_b
        assert len(combined.vetoes) == 2

        # Both pass
        ctx = _make_ctx(guest_present=False, working_mode="rnd")
        assert combined.evaluate(ctx).allowed

        # One fails
        ctx = _make_ctx(guest_present=True, working_mode="rnd")
        result = combined.evaluate(ctx)
        assert not result.allowed
        assert "consent" in result.denied_by

    def test_fallback_chain_composition(self):
        """Two FallbackChains compose via |."""
        chain_a: FallbackChain[SystemContext, str] = FallbackChain(
            [Candidate("critical", lambda ctx: ctx.stimmung_stance == "critical", "silhouette")],
            default="atmospheric",
        )
        chain_b: FallbackChain[SystemContext, str] = FallbackChain(
            [Candidate("tpn", lambda ctx: ctx.tpn_active, "minimal")],
            default="full",
        )
        combined = chain_a | chain_b

        # Critical wins (higher priority from chain_a)
        ctx = _make_ctx(stimmung_stance="critical", tpn_active=True)
        assert combined.select(ctx).action == "silhouette"

        # TPN wins when not critical
        ctx = _make_ctx(stimmung_stance="nominal", tpn_active=True)
        assert combined.select(ctx).action == "minimal"

        # Default from chain_a when neither matches
        ctx = _make_ctx(stimmung_stance="nominal", tpn_active=False)
        assert combined.select(ctx).action == "atmospheric"

    def test_visual_governance_veto_then_fallback(self):
        """VisualGovernance: consent veto fires before fallback can select."""
        from agents.effect_graph.visual_governance import VisualGovernance

        gov = VisualGovernance()
        # Consent pending → veto → None (suppressed)
        ctx = _make_ctx(consent_state={"phase": "consent_pending"})
        assert gov.evaluate(ctx, "nominal", "medium", ["ambient"]) is None

        # Critical without consent → fallback → silhouette
        ctx = _make_ctx(stimmung_stance="critical")
        assert gov.evaluate(ctx, "critical", "low", ["silhouette", "ambient"]) == "silhouette"


# ── 5. SignalBus Threading ──────────────────────────────────────────────────


class TestSignalBusThreading(unittest.TestCase):
    """SignalBus survives concurrent publish/snapshot from multiple threads."""

    def test_concurrent_publish_snapshot(self):
        """10 publisher threads + 5 reader threads, no crashes or data corruption."""
        bus = SignalBus()
        errors: list[str] = []
        iterations = 200

        def publisher(thread_id: int):
            for i in range(iterations):
                bus.publish(f"signal_{thread_id}", float(i))
                bus.publish_many({f"batch_{thread_id}_a": float(i), f"batch_{thread_id}_b": 1.0})

        def reader(thread_id: int):
            for _ in range(iterations):
                snap = bus.snapshot()
                if not isinstance(snap, dict):
                    errors.append(f"reader {thread_id}: snapshot not dict")
                for v in snap.values():
                    if not isinstance(v, float):
                        errors.append(f"reader {thread_id}: non-float value {v!r}")

        threads = []
        for i in range(10):
            threads.append(threading.Thread(target=publisher, args=(i,)))
        for i in range(5):
            threads.append(threading.Thread(target=reader, args=(i,)))

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"Threading errors: {errors}"

    def test_apply_bindings_with_smoothing(self):
        """ModulationBinding smoothing produces interpolated values."""
        bus = SignalBus()
        bus.publish("energy", 1.0)
        bindings = [
            SignalModulationBinding(target="bloom.alpha", signal="energy", scale=0.5, smoothing=0.8)
        ]
        # First application without current values
        result = bus.apply_bindings(bindings)
        assert abs(result["bloom.alpha"] - 0.5) < 0.001

        # Second with smoothing against previous
        result2 = bus.apply_bindings(bindings, current=result)
        # smoothing: 0.8 * 0.5 + 0.2 * 0.5 = 0.5 (converged since signal unchanged)
        assert abs(result2["bloom.alpha"] - 0.5) < 0.001

        # Change signal, smoothing should interpolate
        bus.publish("energy", 0.0)
        result3 = bus.apply_bindings(bindings, current=result2)
        # 0.8 * 0.5 + 0.2 * 0.0 = 0.4
        assert abs(result3["bloom.alpha"] - 0.4) < 0.001


# ── 6. ExpressionCoordinator Cross-Modal ────────────────────────────────────


class _MediumStubCapability(_StubCapability):
    """StubCapability with a declared medium for modality inference."""

    def __init__(self, name: str, category: CapabilityCategory, medium: str):
        super().__init__(name, category)
        self.medium = medium


class TestExpressionCoordinatorCrossModal(unittest.TestCase):
    """ExpressionCoordinator distributes fragments to both speech and visual."""

    def _make_speech_cap(self):
        return _MediumStubCapability("speech_voice", CapabilityCategory.EXPRESSION, "speech")

    def _make_visual_cap(self):
        return _MediumStubCapability("shader_visual", CapabilityCategory.EXPRESSION, "visual")

    def test_distributes_to_both_modalities(self):
        coord = ExpressionCoordinator()
        recruited = [
            ("speech_voice", self._make_speech_cap()),
            ("shader_visual", self._make_visual_cap()),
        ]
        fragment = {
            "narrative": "A deep amber glow",
            "dimensions": {"luminosity": 0.8, "warmth": 0.6},
            "material": "fire",
        }
        activations = coord.coordinate({"fragment": fragment}, recruited)
        assert len(activations) == 2
        names = {a["capability"] for a in activations}
        assert names == {"speech_voice", "shader_visual"}
        modalities = {a["modality"] for a in activations}
        assert "speech" in modalities
        assert "visual" in modalities
        # Both receive the same fragment
        for a in activations:
            assert a["fragment"]["narrative"] == "A deep amber glow"

    def test_last_fragment_tracked(self):
        coord = ExpressionCoordinator()
        recruited = [("speech_voice", self._make_speech_cap())]
        coord.coordinate({"fragment": {"narrative": "test"}}, recruited)
        assert coord.last_fragment is not None
        assert coord.last_fragment["narrative"] == "test"

    def test_no_fragment_returns_empty(self):
        coord = ExpressionCoordinator()
        recruited = [("speech_voice", self._make_speech_cap())]
        activations = coord.coordinate({"other_key": "data"}, recruited)
        assert activations == []

    def test_string_fragment_wrapped(self):
        """Plain string fragment auto-wrapped as {narrative: str}."""
        coord = ExpressionCoordinator()
        recruited = [("speech_voice", self._make_speech_cap())]
        activations = coord.coordinate({"fragment": "A quiet river"}, recruited)
        assert len(activations) == 1
        assert activations[0]["fragment"] == {"narrative": "A quiet river"}

    def test_fragment_to_shader_mapping(self):
        """map_fragment_to_visual correctly maps dimensions to shader params."""
        fragment = {"dimensions": {"intensity": 0.8, "diffusion": 0.5, "coherence": 0.3}}
        result = map_fragment_to_visual(fragment)
        assert result["noise.amplitude"] == 0.8
        assert result["rd.diffusion_a"] == 0.5
        assert result["noise.frequency_x"] == 0.3

    def test_material_to_uniform_mapping(self):
        assert map_fragment_to_material_uniform({"material": "water"}) == 0.0
        assert map_fragment_to_material_uniform({"material": "Fire"}) == 1.0
        assert map_fragment_to_material_uniform({"material": "void"}) == 4.0
        assert map_fragment_to_material_uniform({"material": "unknown"}) == 0.0
        assert map_fragment_to_material_uniform({}) == 0.0


if __name__ == "__main__":
    unittest.main()
