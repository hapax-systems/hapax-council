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


# ── link_chain — per-slot leaky queue defense-in-depth ──────────────────────


class _FakeElement:
    """Tracking double for a Gst element used in the link_chain assertion suite."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.properties: dict[str, object] = {}
        self.linked_to: list[_FakeElement] = []

    def get_name(self) -> str:
        return self.name

    def set_property(self, key: str, value: object) -> None:
        self.properties[key] = value

    def link(self, other: "_FakeElement") -> bool:
        self.linked_to.append(other)
        return True


class _FakeGst:
    def __init__(self) -> None:
        self.created: list[_FakeElement] = []

        class _Factory:
            @staticmethod
            def make(kind: str, name: str) -> _FakeElement:
                el = _FakeElement(f"{kind}:{name}")
                outer.created.append(el)
                return el

        outer = self
        self.ElementFactory = _Factory


def test_link_chain_inserts_n_minus_one_leaky_queues(registry):
    """11 leaky queues for 12 slots; configured per the task spec.

    Each queue must carry leaky=2 (downstream), max-size-buffers=1, and zero
    bytes/time so only the buffer count gates flow. ``downstream`` semantics
    drop the oldest queued buffer when full, leaving upstream non-blocking —
    this caps blast radius if any single glfeedback slot stalls the shared
    GL command stream.
    """
    pipe = SlotPipeline(registry, num_slots=12)
    pipe._slots = [_FakeElement(f"slot-{i}") for i in range(12)]
    fake_gst = _FakeGst()
    fake_pipeline = MagicMock()
    upstream = _FakeElement("upstream")
    downstream = _FakeElement("downstream")

    pipe.link_chain(fake_pipeline, fake_gst, upstream, downstream)

    queues = pipe._inter_slot_queues
    assert len(queues) == 11, "12 slots → 11 inter-slot queues"

    for i, q in enumerate(queues):
        assert q.name == f"queue:effect-slot-queue-{i}"
        assert q.properties["leaky"] == 2
        assert q.properties["max-size-buffers"] == 1
        assert q.properties["max-size-bytes"] == 0
        assert q.properties["max-size-time"] == 0


def test_link_chain_adds_each_queue_to_pipeline(registry):
    """Every queue must be added to the GstPipeline before being linked.

    Without ``pipeline.add(queue)`` GStreamer rejects the link_pads call;
    the queue would be a free-floating element and the bus would emit a
    ``not-linked`` error at PLAYING transition.
    """
    pipe = SlotPipeline(registry, num_slots=4)
    pipe._slots = [_FakeElement(f"slot-{i}") for i in range(4)]
    fake_gst = _FakeGst()
    fake_pipeline = MagicMock()
    upstream = _FakeElement("upstream")
    downstream = _FakeElement("downstream")

    pipe.link_chain(fake_pipeline, fake_gst, upstream, downstream)

    added = [call.args[0] for call in fake_pipeline.add.call_args_list]
    assert added == pipe._inter_slot_queues, (
        "pipeline.add must be called once per inter-slot queue, in order"
    )


def test_link_chain_link_order_is_alternating(registry):
    """The chain must read upstream → slot[0] → queue[0] → slot[1] → … → slot[N-1] → downstream.

    The alternation is what enables blast-radius capping: each slot has its
    own downstream queue so a single stuck slot can only fill a single queue
    before being bypassed via leaky drop. Verifies the linking sequence as
    observed via each element's ``linked_to`` list.
    """
    n = 5
    pipe = SlotPipeline(registry, num_slots=n)
    pipe._slots = [_FakeElement(f"slot-{i}") for i in range(n)]
    fake_gst = _FakeGst()
    fake_pipeline = MagicMock()
    upstream = _FakeElement("upstream")
    downstream = _FakeElement("downstream")

    pipe.link_chain(fake_pipeline, fake_gst, upstream, downstream)

    # upstream → slot[0]
    assert upstream.linked_to == [pipe._slots[0]]
    # slot[i] → queue[i] for i in 0..n-2
    for i in range(n - 1):
        assert pipe._slots[i].linked_to == [pipe._inter_slot_queues[i]], (
            f"slot[{i}] must link to queue[{i}], saw {pipe._slots[i].linked_to}"
        )
        # queue[i] → slot[i+1]
        assert pipe._inter_slot_queues[i].linked_to == [pipe._slots[i + 1]], (
            f"queue[{i}] must link to slot[{i + 1}], saw {pipe._inter_slot_queues[i].linked_to}"
        )
    # last slot → downstream
    assert pipe._slots[n - 1].linked_to == [downstream]


def test_link_chain_single_slot_has_no_queues(registry):
    """Boundary case: 1 slot → 0 queues, just upstream → slot → downstream."""
    pipe = SlotPipeline(registry, num_slots=1)
    pipe._slots = [_FakeElement("slot-0")]
    fake_gst = _FakeGst()
    fake_pipeline = MagicMock()
    upstream = _FakeElement("upstream")
    downstream = _FakeElement("downstream")

    pipe.link_chain(fake_pipeline, fake_gst, upstream, downstream)

    assert pipe._inter_slot_queues == []
    assert upstream.linked_to == [pipe._slots[0]]
    assert pipe._slots[0].linked_to == [downstream]
    fake_pipeline.add.assert_not_called()


def test_zero_shader_plan_enables_physical_bypass(pipeline, compiler):
    """A zero-node plan must keep logical slots but bypass physical GL passes."""

    g = EffectGraph(
        name="clean",
        nodes={"o": NodeInstance(type="output")},
        edges=[["@live", "o"]],
    )
    plan = compiler.compile(g)
    pipeline._slots = [MagicMock() for _ in range(8)]
    pipeline._slot_is_temporal = [True] * 8
    bypass_pad = object()
    chain_pad = object()
    pipeline._zero_shader_bypass_selector = MagicMock()
    pipeline._zero_shader_bypass_valve = MagicMock()
    pipeline._zero_shader_chain_valve = MagicMock()
    pipeline._zero_shader_bypass_pad = bypass_pad
    pipeline._zero_shader_chain_pad = chain_pad
    pipeline._zero_shader_bypass_active = False

    pipeline.activate_plan(plan)

    assert pipeline.slot_assignments == [None] * 8
    pipeline._zero_shader_chain_valve.set_property.assert_called_with("drop", True)
    pipeline._zero_shader_bypass_valve.set_property.assert_called_with("drop", False)
    pipeline._zero_shader_bypass_selector.set_property.assert_called_with("active-pad", bypass_pad)


def test_clean_plan_enables_physical_bypass_with_policy_nodes(pipeline, compiler):
    """Clean keeps obscuring metadata but bypasses static GL work at runtime."""

    g = EffectGraph(
        name="Clean",
        nodes={
            "color": NodeInstance(type="colorgrade"),
            "posterize": NodeInstance(type="posterize", params={"levels": 12}),
            "o": NodeInstance(type="output"),
        },
        edges=[["@live", "color"], ["color", "posterize"], ["posterize", "o"]],
    )
    plan = compiler.compile(g)
    pipeline._slots = [MagicMock() for _ in range(8)]
    pipeline._slot_is_temporal = [True] * 8
    bypass_pad = object()
    chain_pad = object()
    pipeline._zero_shader_bypass_selector = MagicMock()
    pipeline._zero_shader_bypass_valve = MagicMock()
    pipeline._zero_shader_chain_valve = MagicMock()
    pipeline._zero_shader_bypass_pad = bypass_pad
    pipeline._zero_shader_chain_pad = chain_pad
    pipeline._zero_shader_bypass_active = False

    pipeline.activate_plan(plan)

    assert pipeline.slot_assignments[:2] == ["colorgrade", "posterize"]
    pipeline._zero_shader_chain_valve.set_property.assert_called_with("drop", True)
    pipeline._zero_shader_bypass_valve.set_property.assert_called_with("drop", False)
    pipeline._zero_shader_bypass_selector.set_property.assert_called_with("active-pad", bypass_pad)


def test_non_empty_plan_disables_physical_bypass(pipeline, compiler):
    """Recruiting any shader node switches the already-linked chain back in."""

    g = EffectGraph(
        name="t",
        nodes={"c": NodeInstance(type="colorgrade"), "o": NodeInstance(type="output")},
        edges=[["@live", "c"], ["c", "o"]],
    )
    plan = compiler.compile(g)
    pipeline._slots = [MagicMock() for _ in range(8)]
    pipeline._slot_is_temporal = [True] * 8
    bypass_pad = object()
    chain_pad = object()
    pipeline._zero_shader_bypass_selector = MagicMock()
    pipeline._zero_shader_bypass_valve = MagicMock()
    pipeline._zero_shader_chain_valve = MagicMock()
    pipeline._zero_shader_bypass_pad = bypass_pad
    pipeline._zero_shader_chain_pad = chain_pad
    pipeline._zero_shader_bypass_active = True

    pipeline.activate_plan(plan)

    assert pipeline.slot_assignments[0] == "colorgrade"
    pipeline._zero_shader_chain_valve.set_property.assert_called_with("drop", False)
    pipeline._zero_shader_bypass_valve.set_property.assert_called_with("drop", True)
    pipeline._zero_shader_bypass_selector.set_property.assert_called_with("active-pad", chain_pad)


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


def _is_graph_preset(p: Path) -> bool:
    """Same shape filter as ``tests/effect_graph/test_smoke.py``: skip
    metadata files like ``shader_intensity_bounds.json`` that live in
    ``presets/`` but are not EffectGraph instances."""
    if p.name.startswith("_"):
        return False
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    return isinstance(raw, dict) and "nodes" in raw and "edges" in raw


def test_all_presets_fit(pipeline, compiler):
    for p in sorted(p for p in PRESETS_DIR.glob("*.json") if _is_graph_preset(p)):
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


def test_activate_plan_clamps_manifest_param_bounds(pipeline, compiler):
    g = EffectGraph(
        name="feedback-overbound",
        nodes={
            "f": NodeInstance(type="feedback", params={"decay": 0.91, "blend_mode": 3.0}),
            "o": NodeInstance(type="output"),
        },
        edges=[["@live", "f"], ["f", "o"]],
    )
    plan = compiler.compile(g)
    pipeline._slots = [MagicMock() for _ in range(8)]

    pipeline.activate_plan(plan)

    assert pipeline._slot_preset_params[0]["decay"] == pytest.approx(0.2)
    assert pipeline._slot_preset_params[0]["blend_mode"] == pytest.approx(1.0)


def test_activate_plan_clamps_live_surface_posterize_floor(pipeline, compiler):
    g = EffectGraph(
        name="posterize-floor",
        nodes={
            "p": NodeInstance(type="posterize", params={"levels": 4.0}),
            "o": NodeInstance(type="output"),
        },
        edges=[["@live", "p"], ["p", "o"]],
    )
    plan = compiler.compile(g)
    pipeline._slots = [MagicMock() for _ in range(8)]

    pipeline.activate_plan(plan)

    assert pipeline._slot_preset_params[0]["levels"] == pytest.approx(8.0)


def test_compiler_clamps_live_surface_effect_bounds(compiler):
    g = EffectGraph(
        name="live-surface-wide-bounds",
        nodes={
            "grade": NodeInstance(
                type="colorgrade",
                params={"brightness": 2.0, "contrast": 2.0, "saturation": 2.0},
            ),
            "noise": NodeInstance(
                type="noise_overlay", params={"intensity": 0.5, "animated": True}
            ),
            "drift": NodeInstance(type="drift", params={"amplitude": 6.0, "speed": 4.0}),
            "out": NodeInstance(type="output"),
        },
        edges=[["@live", "grade"], ["grade", "noise"], ["noise", "drift"], ["drift", "out"]],
    )

    plan = compiler.compile(g)
    params_by_type = {step.node_type: step.params for step in plan.steps}

    assert params_by_type["colorgrade"]["brightness"] == pytest.approx(1.10)
    assert params_by_type["colorgrade"]["contrast"] == pytest.approx(1.35)
    assert params_by_type["colorgrade"]["saturation"] == pytest.approx(1.35)
    assert params_by_type["noise_overlay"]["intensity"] == pytest.approx(0.10)
    assert params_by_type["noise_overlay"]["animated"] is False
    assert params_by_type["drift"]["amplitude"] == pytest.approx(0.70)
    assert params_by_type["drift"]["speed"] == pytest.approx(1.0)


def test_runtime_modulation_cannot_push_posterize_below_live_surface_floor(
    pipeline,
    compiler,
):
    g = EffectGraph(
        name="posterize-runtime-floor",
        nodes={
            "p": NodeInstance(type="posterize", params={"levels": 8.0}),
            "o": NodeInstance(type="output"),
        },
        edges=[["@live", "p"], ["p", "o"]],
    )
    plan = compiler.compile(g)
    pipeline._slots = [MagicMock() for _ in range(8)]
    pipeline.activate_plan(plan)

    pipeline.update_node_uniforms("posterize", {"levels": -6.0})

    assert pipeline._slot_base_params[0]["levels"] == pytest.approx(8.0)


def test_runtime_modulation_respects_high_risk_live_surface_caps(pipeline, compiler):
    g = EffectGraph(
        name="high-risk-runtime-caps",
        nodes={
            "glitch": NodeInstance(
                type="glitch_block", params={"intensity": 0.1, "rgb_split": 0.1}
            ),
            "out": NodeInstance(type="output"),
        },
        edges=[["@live", "glitch"], ["glitch", "out"]],
    )
    plan = compiler.compile(g)
    pipeline._slots = [MagicMock() for _ in range(8)]
    pipeline.activate_plan(plan)

    pipeline.update_node_uniforms("glitch_block", {"intensity": 0.9, "rgb_split": 0.9})

    assert pipeline._slot_base_params[0]["intensity"] == pytest.approx(0.25)
    assert pipeline._slot_base_params[0]["rgb_split"] == pytest.approx(0.25)


def test_runtime_live_surface_bounds_have_explicit_offline_opt_out(
    pipeline,
    compiler,
    monkeypatch,
):
    monkeypatch.setenv("HAPAX_LIVE_SURFACE_EFFECT_POLICY", "0")
    g = EffectGraph(
        name="offline-posterize",
        nodes={
            "p": NodeInstance(type="posterize", params={"levels": 4.0}),
            "o": NodeInstance(type="output"),
        },
        edges=[["@live", "p"], ["p", "o"]],
    )
    plan = compiler.compile(g)
    pipeline._slots = [MagicMock() for _ in range(8)]

    pipeline.activate_plan(plan)
    pipeline.update_node_uniforms("posterize", {"levels": -6.0})

    assert pipeline._slot_preset_params[0]["levels"] == pytest.approx(4.0)
    assert pipeline._slot_base_params[0]["levels"] == pytest.approx(2.0)


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
