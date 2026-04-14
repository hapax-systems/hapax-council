"""Tests for slot-based pipeline builder."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agents.effect_graph.compiler import GraphCompiler
from agents.effect_graph.pipeline import PASSTHROUGH_SHADER, SlotPipeline
from agents.effect_graph.registry import ShaderRegistry
from agents.effect_graph.types import EffectGraph, NodeInstance

NODES_DIR = Path(__file__).parent.parent.parent / "agents" / "shaders" / "nodes"
PRESETS_DIR = Path(__file__).parent.parent.parent / "presets"


@pytest.fixture(scope="module")
def registry():
    return ShaderRegistry(NODES_DIR)


@pytest.fixture(scope="module")
def compiler(registry):
    return GraphCompiler(registry)


@pytest.fixture
def pipeline(registry):
    return SlotPipeline(registry, num_slots=8)


def test_passthrough_shader():
    assert "void main()" in PASSTHROUGH_SHADER
    assert "gl_FragColor" in PASSTHROUGH_SHADER


def test_initial_state(pipeline):
    assert pipeline.num_slots == 8
    assert all(s is None for s in pipeline.slot_assignments)


def test_activate_assigns_slots(pipeline, compiler):
    g = EffectGraph(
        name="t",
        nodes={
            "c": NodeInstance(type="colorgrade", params={"saturation": 0.5}),
            "b": NodeInstance(type="bloom"),
            "o": NodeInstance(type="output"),
        },
        edges=[["@live", "c"], ["c", "b"], ["b", "o"]],
    )
    plan = compiler.compile(g)
    pipeline._slots = [MagicMock() for _ in range(8)]
    pipeline.activate_plan(plan)
    assert pipeline.slot_assignments[0] == "colorgrade"
    assert pipeline.slot_assignments[1] == "bloom"
    assert pipeline.slot_assignments[2] is None


def test_activate_sets_shader(pipeline, compiler):
    g = EffectGraph(
        name="t",
        nodes={"c": NodeInstance(type="colorgrade"), "o": NodeInstance(type="output")},
        edges=[["@live", "c"], ["c", "o"]],
    )
    plan = compiler.compile(g)
    mocks = [MagicMock() for _ in range(8)]
    pipeline._slots = mocks
    pipeline.activate_plan(plan)

    # Shader source is stored in pending frag for GL-thread compilation
    assert pipeline._slot_pending_frag[0] is not None
    assert "void main()" in pipeline._slot_pending_frag[0]


def test_find_slot(pipeline, compiler):
    g = EffectGraph(
        name="t",
        nodes={
            "c": NodeInstance(type="colorgrade"),
            "b": NodeInstance(type="bloom"),
            "o": NodeInstance(type="output"),
        },
        edges=[["@live", "c"], ["c", "b"], ["b", "o"]],
    )
    plan = compiler.compile(g)
    pipeline._slots = [MagicMock() for _ in range(8)]
    pipeline.activate_plan(plan)
    assert pipeline.find_slot_for_node("colorgrade") == 0
    assert pipeline.find_slot_for_node("bloom") == 1
    assert pipeline.find_slot_for_node("nope") is None


def test_all_presets_fit(pipeline, compiler):
    for p in sorted(p for p in PRESETS_DIR.glob("*.json") if not p.name.startswith("_")):
        g = EffectGraph(**json.loads(p.read_text()))
        plan = compiler.compile(g)
        shader_steps = [s for s in plan.steps if s.node_type != "output" and s.shader_source]
        assert len(shader_steps) <= 8, f"{p.stem} needs {len(shader_steps)} slots"


def test_ghost_preset(pipeline, compiler):
    g = EffectGraph(**json.loads((PRESETS_DIR / "ghost.json").read_text()))
    plan = compiler.compile(g)
    pipeline._slots = [MagicMock() for _ in range(8)]
    pipeline.activate_plan(plan)
    assigned = [a for a in pipeline.slot_assignments if a]
    assert "trail" in assigned and "bloom" in assigned


class TestGlfeedbackDiffCheck:
    """Activate-plan should not re-set fragment to its current value.

    Per delta 2026-04-14 glfeedback-shader-recompile-storm drop: every
    byte-identical re-set cascades a Rust-side accum-buffer clear and a
    shader recompile, producing one visual flicker per plan activation
    on any feedback-using effect.
    """

    def _temporal_pipeline(self, registry, compiler):
        pipe = SlotPipeline(registry, num_slots=8)
        pipe._slots = [MagicMock() for _ in range(8)]
        pipe._slot_is_temporal = [True] * 8
        return pipe

    def _plan(self, compiler, type1: str = "colorgrade", type2: str | None = None):
        nodes = {
            "a": NodeInstance(type=type1),
            "o": NodeInstance(type="output"),
        }
        edges: list[list[str]] = [["@live", "a"]]
        if type2:
            nodes["b"] = NodeInstance(type=type2)
            edges.append(["a", "b"])
            edges.append(["b", "o"])
        else:
            edges.append(["a", "o"])
        g = EffectGraph(name="t", nodes=nodes, edges=edges)
        return compiler.compile(g)

    def test_repeat_plan_skips_fragment_set_property(self, registry, compiler):
        pipe = self._temporal_pipeline(registry, compiler)
        plan = self._plan(compiler)

        pipe.activate_plan(plan)
        calls_after_first = sum(
            1 for c in pipe._slots[0].set_property.call_args_list if c.args[0] == "fragment"
        )
        assert calls_after_first == 1, (
            "first activation must set fragment once on the colorgrade slot"
        )

        passthrough_mock = pipe._slots[3]
        passthrough_calls_first = sum(
            1 for c in passthrough_mock.set_property.call_args_list if c.args[0] == "fragment"
        )
        assert passthrough_calls_first == 1

        for mock in pipe._slots:
            mock.reset_mock()

        pipe.activate_plan(plan)
        for i, mock in enumerate(pipe._slots):
            frag_calls = [c for c in mock.set_property.call_args_list if c.args[0] == "fragment"]
            assert len(frag_calls) == 0, (
                f"slot {i}: identical re-activation must not re-set fragment "
                f"(got {len(frag_calls)} set_property calls)"
            )

    def test_plan_with_real_change_sets_fragment(self, registry, compiler):
        pipe = self._temporal_pipeline(registry, compiler)
        plan_a = self._plan(compiler, type1="colorgrade")
        plan_b = self._plan(compiler, type1="bloom")

        pipe.activate_plan(plan_a)
        for mock in pipe._slots:
            mock.reset_mock()

        pipe.activate_plan(plan_b)
        slot0_frag_calls = [
            c for c in pipe._slots[0].set_property.call_args_list if c.args[0] == "fragment"
        ]
        assert len(slot0_frag_calls) == 1, "slot 0 changed colorgrade → bloom, must set fragment"

        for i in range(1, 8):
            frag_calls = [
                c for c in pipe._slots[i].set_property.call_args_list if c.args[0] == "fragment"
            ]
            assert len(frag_calls) == 0, (
                f"slot {i} (passthrough) unchanged across plans, must not re-set fragment"
            )

    def test_last_frag_memo_reset_on_recreate(self, registry, compiler):
        pipe = self._temporal_pipeline(registry, compiler)
        plan = self._plan(compiler)
        pipe.activate_plan(plan)
        assert any(f is not None for f in pipe._slot_last_frag)

        Gst = MagicMock()
        factory = MagicMock()
        factory.find.return_value = None
        Gst.ElementFactory = factory
        pipe.create_slots(Gst)
        # glshader branch (fallback): memo entries start as None since
        # the compile happens later via the ``create-shader`` signal.
        assert all(f is None for f in pipe._slot_last_frag), (
            "create_slots(glshader fallback) must reset _slot_last_frag to None"
        )

    def test_create_slots_glfeedback_path_primes_memo_with_passthrough(self, registry, compiler):
        """Beta audit pass 2 L-01 regression pin.

        When ``glfeedback`` is available, ``create_slots`` calls
        ``set_property("fragment", PASSTHROUGH_SHADER)`` on every slot.
        The Python memo ``_slot_last_frag[i]`` MUST be primed to
        ``PASSTHROUGH_SHADER`` at the same time so that the first
        ``activate_plan`` after startup doesn't over-count the
        ``COMP_GLFEEDBACK_RECOMPILE_TOTAL`` metric by one per slot
        (up to 24) when the passthrough fragment is "unchanged" from
        the constructor's own call.
        """
        from agents.effect_graph.pipeline import PASSTHROUGH_SHADER, SlotPipeline

        pipe = SlotPipeline(registry, num_slots=8)
        Gst = MagicMock()
        factory = MagicMock()
        # Force the glfeedback branch.
        factory.find.return_value = MagicMock()
        Gst.ElementFactory = factory
        pipe.create_slots(Gst)

        assert pipe._slot_is_temporal == [True] * 8, (
            "glfeedback branch must mark every slot as temporal"
        )
        assert pipe._slot_last_frag == [PASSTHROUGH_SHADER] * 8, (
            "glfeedback create_slots must prime memo to PASSTHROUGH_SHADER "
            "to match the set_property call — otherwise the first "
            "activate_plan over-counts the recompile metric"
        )

    def test_recompile_and_accum_clear_counters_increment(self, registry, compiler):
        """Phase 10 / delta metric-coverage-gaps C7 + C8 proof-of-fix counters.

        A real change to slot 0 must bump both compositor_glfeedback_recompile_total
        and compositor_glfeedback_accum_clear_total. A no-op repeat must not.
        """
        from agents.studio_compositor import metrics as comp_metrics

        comp_metrics._init_metrics()
        if (
            comp_metrics.COMP_GLFEEDBACK_RECOMPILE_TOTAL is None
            or comp_metrics.COMP_GLFEEDBACK_ACCUM_CLEAR_TOTAL is None
        ):
            import pytest as _pt

            _pt.skip("prometheus_client not available in this environment")

        def _total(counter) -> float:
            for metric in counter.collect():
                for sample in metric.samples:
                    if sample.name.endswith("_total"):
                        return sample.value
            return 0.0

        baseline_recomp = _total(comp_metrics.COMP_GLFEEDBACK_RECOMPILE_TOTAL)
        baseline_clear = _total(comp_metrics.COMP_GLFEEDBACK_ACCUM_CLEAR_TOTAL)

        pipe = self._temporal_pipeline(registry, compiler)
        plan = self._plan(compiler, type1="colorgrade")
        pipe.activate_plan(plan)

        after_first_recomp = _total(comp_metrics.COMP_GLFEEDBACK_RECOMPILE_TOTAL)
        after_first_clear = _total(comp_metrics.COMP_GLFEEDBACK_ACCUM_CLEAR_TOTAL)
        assert after_first_recomp > baseline_recomp, (
            "first activate_plan must bump COMP_GLFEEDBACK_RECOMPILE_TOTAL"
        )
        assert after_first_clear > baseline_clear, (
            "first activate_plan must bump COMP_GLFEEDBACK_ACCUM_CLEAR_TOTAL"
        )

        pipe.activate_plan(plan)
        assert _total(comp_metrics.COMP_GLFEEDBACK_RECOMPILE_TOTAL) == after_first_recomp, (
            "repeat activate_plan must NOT bump recompile counter"
        )
        assert _total(comp_metrics.COMP_GLFEEDBACK_ACCUM_CLEAR_TOTAL) == after_first_clear, (
            "repeat activate_plan must NOT bump accum-clear counter"
        )
