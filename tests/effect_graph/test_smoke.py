"""Systematic smoke tests for the effect node graph system.

Exercises every module, every node type, every preset, every API path,
and every mutation level. Backend only — no GStreamer or frontend.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from agents.effect_graph.compiler import GraphCompiler, GraphValidationError
from agents.effect_graph.modulator import UniformModulator
from agents.effect_graph.registry import ShaderRegistry
from agents.effect_graph.runtime import GraphRuntime
from agents.effect_graph.types import (
    EdgeDef,
    EffectGraph,
    GraphPatch,
    LayerPalette,
    ModulationBinding,
    NodeInstance,
    ParamDef,
    PortType,
)

NODES_DIR = Path(__file__).parent.parent.parent / "agents" / "shaders" / "nodes"
PRESETS_DIR = Path(__file__).parent.parent.parent / "presets"


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(scope="module")
def registry() -> ShaderRegistry:
    return ShaderRegistry(NODES_DIR)


@pytest.fixture(scope="module")
def compiler(registry: ShaderRegistry) -> GraphCompiler:
    return GraphCompiler(registry)


@pytest.fixture
def runtime(registry: ShaderRegistry, compiler: GraphCompiler) -> GraphRuntime:
    return GraphRuntime(registry=registry, compiler=compiler, modulator=UniformModulator())


def _minimal_graph(**overrides: Any) -> EffectGraph:
    base = {
        "name": "test",
        "nodes": {
            "c": NodeInstance(type="colorgrade"),
            "o": NodeInstance(type="output"),
        },
        "edges": [["@live", "c"], ["c", "o"]],
    }
    base.update(overrides)
    return EffectGraph(**base)


# ============================================================================
# 1. TYPE MODELS — validation, construction, edge cases
# ============================================================================


class TestParamDef:
    def test_float_with_range(self):
        p = ParamDef(type="float", default=0.5, min=0.0, max=1.0, description="test")
        assert p.default == 0.5 and p.min == 0.0 and p.max == 1.0

    def test_enum_with_values(self):
        p = ParamDef(type="enum", default="a", enum_values=["a", "b", "c"])
        assert p.enum_values == ["a", "b", "c"]

    def test_vec2_default(self):
        p = ParamDef(type="vec2", default=[1.0, 2.0])
        assert p.default == [1.0, 2.0]

    def test_bool_default(self):
        p = ParamDef(type="bool", default=False)
        assert p.default is False

    def test_int_with_range(self):
        p = ParamDef(type="int", default=8, min=2, max=32)
        assert p.default == 8

    def test_minimal(self):
        p = ParamDef(type="float", default=1.0)
        assert p.min is None and p.max is None and p.description == ""


class TestPortType:
    def test_values(self):
        assert PortType.FRAME == "frame"
        assert PortType.SCALAR == "scalar"
        assert PortType.COLOR == "color"

    def test_from_string(self):
        assert PortType("frame") == PortType.FRAME


class TestEdgeDef:
    def test_simple(self):
        e = EdgeDef.from_list(["a", "b"])
        assert e.source_node == "a" and e.source_port == "out"
        assert e.target_node == "b" and e.target_port == "in"

    def test_target_port(self):
        e = EdgeDef.from_list(["a", "b:x"])
        assert e.target_port == "x"

    def test_source_port(self):
        e = EdgeDef.from_list(["a:y", "b"])
        assert e.source_port == "y"

    def test_both_ports(self):
        e = EdgeDef.from_list(["a:y", "b:x"])
        assert e.source_port == "y" and e.target_port == "x"

    def test_layer_source_live(self):
        e = EdgeDef.from_list(["@live", "c"])
        assert e.is_layer_source and e.source_node == "@live" and e.source_port == "out"

    def test_layer_source_smooth(self):
        e = EdgeDef.from_list(["@smooth", "c"])
        assert e.is_layer_source

    def test_layer_source_hls(self):
        e = EdgeDef.from_list(["@hls", "c"])
        assert e.is_layer_source

    def test_not_layer_source(self):
        e = EdgeDef.from_list(["color", "trail"])
        assert not e.is_layer_source

    def test_layer_with_target_port(self):
        e = EdgeDef.from_list(["@live", "blend:a"])
        assert e.source_node == "@live" and e.target_port == "a"

    def test_bad_length_1(self):
        with pytest.raises(ValueError):
            EdgeDef.from_list(["only"])

    def test_bad_length_3(self):
        with pytest.raises(ValueError):
            EdgeDef.from_list(["a", "b", "c"])

    def test_empty(self):
        with pytest.raises(ValueError):
            EdgeDef.from_list([])


class TestNodeInstance:
    def test_with_params(self):
        n = NodeInstance(type="colorgrade", params={"saturation": 0.5, "brightness": 1.2})
        assert n.params["saturation"] == 0.5

    def test_empty_params(self):
        n = NodeInstance(type="output")
        assert n.params == {}

    def test_nested_params(self):
        n = NodeInstance(type="color_map", params={"gradient": [{"pos": 0, "color": [1, 0, 0]}]})
        assert isinstance(n.params["gradient"], list)


class TestModulationBinding:
    def test_defaults(self):
        m = ModulationBinding(node="a", param="b", source="audio_rms")
        assert m.scale == 1.0 and m.offset == 0.0 and m.smoothing == 0.85

    def test_custom(self):
        m = ModulationBinding(
            node="a", param="b", source="s", scale=2.0, offset=-0.5, smoothing=0.5
        )
        assert m.scale == 2.0

    def test_smoothing_min(self):
        m = ModulationBinding(node="a", param="b", source="s", smoothing=0.0)
        assert m.smoothing == 0.0

    def test_smoothing_max(self):
        m = ModulationBinding(node="a", param="b", source="s", smoothing=1.0)
        assert m.smoothing == 1.0

    def test_smoothing_above_max(self):
        with pytest.raises(ValidationError):
            ModulationBinding(node="a", param="b", source="s", smoothing=1.01)

    def test_smoothing_below_min(self):
        with pytest.raises(ValidationError):
            ModulationBinding(node="a", param="b", source="s", smoothing=-0.01)


class TestLayerPalette:
    def test_defaults(self):
        lp = LayerPalette()
        assert lp.saturation == 1.0 and lp.brightness == 1.0 and lp.contrast == 1.0
        assert lp.sepia == 0.0 and lp.hue_rotate == 0.0

    def test_custom(self):
        lp = LayerPalette(saturation=0.5, hue_rotate=-45.0)
        assert lp.saturation == 0.5

    def test_saturation_too_high(self):
        with pytest.raises(ValidationError):
            LayerPalette(saturation=2.1)

    def test_saturation_too_low(self):
        with pytest.raises(ValidationError):
            LayerPalette(saturation=-0.1)

    def test_sepia_range(self):
        with pytest.raises(ValidationError):
            LayerPalette(sepia=1.1)

    def test_hue_rotate_range(self):
        with pytest.raises(ValidationError):
            LayerPalette(hue_rotate=181.0)

    def test_hue_rotate_negative(self):
        lp = LayerPalette(hue_rotate=-180.0)
        assert lp.hue_rotate == -180.0


class TestEffectGraph:
    def test_minimal(self):
        g = _minimal_graph()
        assert len(g.nodes) == 2 and len(g.edges) == 2

    def test_parsed_edges(self):
        g = _minimal_graph()
        edges = g.parsed_edges
        assert len(edges) == 2
        assert edges[0].source_node == "@live"
        assert edges[1].target_node == "o"

    def test_with_modulations(self):
        g = EffectGraph(
            nodes={"c": NodeInstance(type="colorgrade"), "o": NodeInstance(type="output")},
            edges=[["@live", "c"], ["c", "o"]],
            modulations=[ModulationBinding(node="c", param="saturation", source="audio_rms")],
        )
        assert len(g.modulations) == 1

    def test_with_layer_palettes(self):
        g = EffectGraph(
            nodes={"c": NodeInstance(type="colorgrade"), "o": NodeInstance(type="output")},
            edges=[["@live", "c"], ["c", "o"]],
            layer_palettes={"live": LayerPalette(saturation=0.5)},
        )
        assert g.layer_palettes["live"].saturation == 0.5

    def test_transition_ms_default(self):
        g = _minimal_graph()
        assert g.transition_ms == 500

    def test_transition_ms_custom(self):
        g = _minimal_graph(transition_ms=300)
        assert g.transition_ms == 300


class TestGraphPatch:
    def test_empty(self):
        p = GraphPatch()
        assert len(p.add_nodes) == 0 and len(p.remove_nodes) == 0

    def test_add(self):
        p = GraphPatch(
            add_nodes={"bloom": NodeInstance(type="bloom")},
            add_edges=[["c", "bloom"], ["bloom", "o"]],
        )
        assert "bloom" in p.add_nodes

    def test_remove(self):
        p = GraphPatch(remove_nodes=["scan"], remove_edges=[["c", "scan"]])
        assert "scan" in p.remove_nodes


# ============================================================================
# 2. SHADER REGISTRY — manifest loading, all 54 node types
# ============================================================================


class TestRegistryLoading:
    def test_loads_all_nodes(self, registry: ShaderRegistry):
        assert len(registry.node_types) == 57

    def test_sorted(self, registry: ShaderRegistry):
        types = registry.node_types
        assert types == sorted(types)

    def test_unknown_returns_none(self, registry: ShaderRegistry):
        assert registry.get("nonexistent_xyz") is None


class TestRegistryNodeCategories:
    """Verify every node type loads with correct metadata."""

    EXPECTED_PROCESSING = [
        "ascii",
        "bloom",
        "breathing",
        "chromatic_aberration",
        "circular_mask",
        "color_map",
        "colorgrade",
        "dither",
        "drift",
        "droste",
        "edge_detect",
        "emboss",
        "fisheye",
        "glitch_block",
        "halftone",
        "invert",
        "kaleidoscope",
        "mirror",
        "noise_overlay",
        "pixsort",
        "posterize",
        "rutt_etra",
        "scanlines",
        "sharpen",
        "strobe",
        "syrup",
        "thermal",
        "threshold",
        "tile",
        "transform",
        "tunnel",
        "vhs",
        "vignette",
        "voronoi_overlay",
        "warp",
    ]
    EXPECTED_TEMPORAL = ["diff", "echo", "feedback", "slitscan", "stutter", "trail"]
    EXPECTED_COMPOSITING = ["blend", "chroma_key", "crossfade", "displacement_map", "luma_key"]
    EXPECTED_GENERATIVE = ["noise_gen", "solid", "waveform_render"]
    EXPECTED_META = ["output", "palette"]

    def test_all_processing_nodes_exist(self, registry: ShaderRegistry):
        for nt in self.EXPECTED_PROCESSING:
            d = registry.get(nt)
            assert d is not None, f"Missing processing node: {nt}"
            assert not d.temporal, f"{nt} should not be temporal"
            assert "in" in d.inputs, f"{nt} missing 'in' port"

    def test_all_temporal_nodes_exist(self, registry: ShaderRegistry):
        for nt in self.EXPECTED_TEMPORAL:
            d = registry.get(nt)
            assert d is not None, f"Missing temporal node: {nt}"
            assert d.temporal, f"{nt} should be temporal"
            assert d.temporal_buffers >= 1, f"{nt} needs temporal_buffers >= 1"

    def test_all_compositing_nodes_exist(self, registry: ShaderRegistry):
        for nt in self.EXPECTED_COMPOSITING:
            d = registry.get(nt)
            assert d is not None, f"Missing compositing node: {nt}"
            assert len(d.inputs) >= 2, f"{nt} should have >= 2 inputs, got {d.inputs}"

    def test_all_generative_nodes_exist(self, registry: ShaderRegistry):
        for nt in self.EXPECTED_GENERATIVE:
            d = registry.get(nt)
            assert d is not None, f"Missing generative node: {nt}"
            assert len(d.inputs) == 0, f"{nt} should have 0 inputs"
            assert "out" in d.outputs, f"{nt} missing 'out' port"

    def test_output_node(self, registry: ShaderRegistry):
        d = registry.get("output")
        assert d is not None
        assert d.glsl_source is None
        assert "in" in d.inputs
        assert len(d.outputs) == 0

    def test_palette_node(self, registry: ShaderRegistry):
        d = registry.get("palette")
        assert d is not None
        assert d.glsl_source is not None  # shares colorgrade.frag


class TestRegistryShaderContent:
    """Verify shader source code is loaded for nodes that need it."""

    def test_processing_nodes_have_shaders(self, registry: ShaderRegistry):
        for nt in registry.node_types:
            d = registry.get(nt)
            if nt in ("output",):
                # output is a sink with no GLSL
                assert d.glsl_source is None or d.glsl_source == "", f"{nt} shouldn't have shader"
            elif d.inputs:  # Not generative
                assert d.glsl_source, f"{nt} missing GLSL source"

    def test_shaders_contain_main(self, registry: ShaderRegistry):
        for nt in registry.node_types:
            d = registry.get(nt)
            if d.glsl_source:
                assert "void main()" in d.glsl_source or "void main ()" in d.glsl_source, (
                    f"{nt} shader missing main()"
                )

    def test_shaders_contain_gl_fragcolor(self, registry: ShaderRegistry):
        for nt in registry.node_types:
            d = registry.get(nt)
            if d.glsl_source:
                assert "gl_FragColor" in d.glsl_source, f"{nt} shader missing gl_FragColor"


class TestRegistrySchemaExport:
    def test_schema_for_each_node(self, registry: ShaderRegistry):
        for nt in registry.node_types:
            s = registry.schema(nt)
            assert s is not None, f"No schema for {nt}"
            assert s["node_type"] == nt
            assert "inputs" in s and "outputs" in s and "params" in s

    def test_all_schemas(self, registry: ShaderRegistry):
        schemas = registry.all_schemas()
        assert len(schemas) == 57

    def test_schema_params_are_serializable(self, registry: ShaderRegistry):
        """Ensure all schemas can be JSON-serialized (for API)."""
        schemas = registry.all_schemas()
        serialized = json.dumps(schemas)
        assert len(serialized) > 0
        roundtrip = json.loads(serialized)
        assert len(roundtrip) == 57


class TestRegistryParamCompleteness:
    """Verify key nodes have expected params."""

    def test_colorgrade_params(self, registry: ShaderRegistry):
        d = registry.get("colorgrade")
        for p in ("saturation", "brightness", "contrast", "sepia", "hue_rotate"):
            assert p in d.params, f"colorgrade missing param: {p}"

    def test_trail_params(self, registry: ShaderRegistry):
        d = registry.get("trail")
        for p in ("fade", "opacity"):
            assert p in d.params, f"trail missing param: {p}"

    def test_bloom_params(self, registry: ShaderRegistry):
        d = registry.get("bloom")
        for p in ("threshold", "radius", "alpha"):
            assert p in d.params, f"bloom missing param: {p}"

    def test_vhs_params(self, registry: ShaderRegistry):
        d = registry.get("vhs")
        assert "chroma_shift" in d.params

    def test_blend_params(self, registry: ShaderRegistry):
        d = registry.get("blend")
        assert "alpha" in d.params
        assert "a" in d.inputs and "b" in d.inputs


# ============================================================================
# 3. GRAPH COMPILER — validation, topo sort, execution plans
# ============================================================================


class TestCompilerValidation:
    def test_rejects_no_output(self, compiler: GraphCompiler):
        g = EffectGraph(
            nodes={"c": NodeInstance(type="colorgrade")},
            edges=[["@live", "c"]],
        )
        with pytest.raises(GraphValidationError, match="output"):
            compiler.compile(g)

    def test_rejects_unknown_type(self, compiler: GraphCompiler):
        g = EffectGraph(
            nodes={"x": NodeInstance(type="fake"), "o": NodeInstance(type="output")},
            edges=[["@live", "x"], ["x", "o"]],
        )
        with pytest.raises(GraphValidationError, match="[Uu]nknown"):
            compiler.compile(g)

    def test_rejects_cycle(self, compiler: GraphCompiler):
        g = EffectGraph(
            nodes={
                "a": NodeInstance(type="colorgrade"),
                "b": NodeInstance(type="colorgrade"),
                "o": NodeInstance(type="output"),
            },
            edges=[["@live", "a"], ["a", "b"], ["b", "a"], ["b", "o"]],
        )
        with pytest.raises(GraphValidationError, match="[Cc]ycle"):
            compiler.compile(g)

    def test_rejects_disconnected(self, compiler: GraphCompiler):
        g = EffectGraph(
            nodes={
                "c": NodeInstance(type="colorgrade"),
                "orphan": NodeInstance(type="bloom"),
                "o": NodeInstance(type="output"),
            },
            edges=[["@live", "c"], ["c", "o"]],
        )
        with pytest.raises(GraphValidationError, match="[Dd]isconnect"):
            compiler.compile(g)

    def test_rejects_invalid_layer(self, compiler: GraphCompiler):
        g = EffectGraph(
            nodes={"o": NodeInstance(type="output")},
            edges=[["@invalid", "o"]],
        )
        with pytest.raises(GraphValidationError):
            compiler.compile(g)

    def test_accepts_all_valid_layers(self, compiler: GraphCompiler):
        """All three layer sources should be accepted."""
        for layer in ("@live", "@smooth", "@hls"):
            g = EffectGraph(
                nodes={"c": NodeInstance(type="colorgrade"), "o": NodeInstance(type="output")},
                edges=[[layer, "c"], ["c", "o"]],
            )
            plan = compiler.compile(g)
            assert layer in plan.layer_sources


class TestCompilerTopologicalSort:
    def test_linear_order(self, compiler: GraphCompiler):
        g = EffectGraph(
            nodes={
                "a": NodeInstance(type="colorgrade"),
                "b": NodeInstance(type="bloom"),
                "c": NodeInstance(type="scanlines"),
                "o": NodeInstance(type="output"),
            },
            edges=[["@live", "a"], ["a", "b"], ["b", "c"], ["c", "o"]],
        )
        plan = compiler.compile(g)
        order = [s.node_id for s in plan.steps]
        assert order.index("a") < order.index("b") < order.index("c") < order.index("o")

    def test_diamond_order(self, compiler: GraphCompiler):
        """A → B, A → C, B+C → blend → out."""
        g = EffectGraph(
            nodes={
                "a": NodeInstance(type="colorgrade"),
                "b": NodeInstance(type="bloom"),
                "c": NodeInstance(type="scanlines"),
                "m": NodeInstance(type="blend"),
                "o": NodeInstance(type="output"),
            },
            edges=[
                ["@live", "a"],
                ["a", "b"],
                ["a", "c"],
                ["b", "m:a"],
                ["c", "m:b"],
                ["m", "o"],
            ],
        )
        plan = compiler.compile(g)
        order = [s.node_id for s in plan.steps]
        assert order.index("a") < order.index("b")
        assert order.index("a") < order.index("c")
        assert order.index("b") < order.index("m")
        assert order.index("c") < order.index("m")

    def test_multi_source(self, compiler: GraphCompiler):
        """Two layer sources feeding into a blend."""
        g = EffectGraph(
            nodes={
                "ca": NodeInstance(type="colorgrade"),
                "cb": NodeInstance(type="colorgrade"),
                "m": NodeInstance(type="blend"),
                "o": NodeInstance(type="output"),
            },
            edges=[
                ["@live", "ca"],
                ["@smooth", "cb"],
                ["ca", "m:a"],
                ["cb", "m:b"],
                ["m", "o"],
            ],
        )
        plan = compiler.compile(g)
        assert "@live" in plan.layer_sources and "@smooth" in plan.layer_sources


class TestCompilerExecutionPlan:
    def test_step_has_shader_source(self, compiler: GraphCompiler):
        g = _minimal_graph()
        plan = compiler.compile(g)
        color_step = next(s for s in plan.steps if s.node_id == "c")
        assert color_step.shader_source is not None
        assert "void main()" in color_step.shader_source

    def test_output_step_no_shader(self, compiler: GraphCompiler):
        g = _minimal_graph()
        plan = compiler.compile(g)
        out_step = next(s for s in plan.steps if s.node_id == "o")
        assert out_step.shader_source is None or out_step.shader_source == ""

    def test_temporal_step_flagged(self, compiler: GraphCompiler):
        g = EffectGraph(
            nodes={"t": NodeInstance(type="trail"), "o": NodeInstance(type="output")},
            edges=[["@live", "t"], ["t", "o"]],
        )
        plan = compiler.compile(g)
        trail_step = next(s for s in plan.steps if s.node_id == "t")
        assert trail_step.temporal and trail_step.temporal_buffers >= 1

    def test_fanout_fbo(self, compiler: GraphCompiler):
        g = EffectGraph(
            nodes={
                "c": NodeInstance(type="colorgrade"),
                "b1": NodeInstance(type="bloom"),
                "b2": NodeInstance(type="scanlines"),
                "m": NodeInstance(type="blend"),
                "o": NodeInstance(type="output"),
            },
            edges=[
                ["@live", "c"],
                ["c", "b1"],
                ["c", "b2"],
                ["b1", "m:a"],
                ["b2", "m:b"],
                ["m", "o"],
            ],
        )
        plan = compiler.compile(g)
        c_step = next(s for s in plan.steps if s.node_id == "c")
        assert c_step.needs_dedicated_fbo

    def test_transition_ms_propagated(self, compiler: GraphCompiler):
        g = _minimal_graph(transition_ms=750)
        plan = compiler.compile(g)
        assert plan.transition_ms == 750

    def test_params_propagated(self, compiler: GraphCompiler):
        g = EffectGraph(
            nodes={
                "c": NodeInstance(type="colorgrade", params={"saturation": 0.3}),
                "o": NodeInstance(type="output"),
            },
            edges=[["@live", "c"], ["c", "o"]],
        )
        plan = compiler.compile(g)
        c_step = next(s for s in plan.steps if s.node_id == "c")
        assert c_step.params["saturation"] == 0.3

    def test_input_output_edges(self, compiler: GraphCompiler):
        g = EffectGraph(
            nodes={
                "a": NodeInstance(type="colorgrade"),
                "b": NodeInstance(type="bloom"),
                "o": NodeInstance(type="output"),
            },
            edges=[["@live", "a"], ["a", "b"], ["b", "o"]],
        )
        plan = compiler.compile(g)
        a_step = next(s for s in plan.steps if s.node_id == "a")
        assert len(a_step.input_edges) == 1  # @live → a
        assert len(a_step.output_edges) == 1  # a → b


# ============================================================================
# 4. UNIFORM MODULATOR — signal binding, tick, smoothing
# ============================================================================


class TestModulatorBindings:
    def test_add(self):
        m = UniformModulator()
        m.add_binding(ModulationBinding(node="a", param="x", source="rms"))
        assert len(m.bindings) == 1

    def test_add_replaces_same_key(self):
        m = UniformModulator()
        m.add_binding(ModulationBinding(node="a", param="x", source="rms", scale=1.0))
        m.add_binding(ModulationBinding(node="a", param="x", source="beat", scale=2.0))
        assert len(m.bindings) == 1
        assert m.bindings[0].source == "beat"

    def test_remove(self):
        m = UniformModulator()
        m.add_binding(ModulationBinding(node="a", param="x", source="rms"))
        m.remove_binding("a", "x")
        assert len(m.bindings) == 0

    def test_remove_nonexistent(self):
        m = UniformModulator()
        m.remove_binding("a", "x")  # should not raise

    def test_replace_all(self):
        m = UniformModulator()
        m.add_binding(ModulationBinding(node="a", param="x", source="rms"))
        m.add_binding(ModulationBinding(node="b", param="y", source="beat"))
        m.replace_all([ModulationBinding(node="c", param="z", source="flow")])
        assert len(m.bindings) == 1 and m.bindings[0].node == "c"

    def test_replace_all_clears_smoothed(self):
        m = UniformModulator()
        m.add_binding(ModulationBinding(node="a", param="x", source="rms", smoothing=0.5))
        m.tick({"rms": 1.0})  # accumulate smoothed state
        m.replace_all([])
        assert len(m._smoothed) == 0


class TestModulatorTick:
    def test_basic_passthrough(self):
        m = UniformModulator()
        m.add_binding(
            ModulationBinding(
                node="a", param="x", source="rms", scale=1.0, offset=0.0, smoothing=0.0
            )
        )
        updates = m.tick({"rms": 0.7})
        assert updates[("a", "x")] == pytest.approx(0.7)

    def test_scale(self):
        m = UniformModulator()
        m.add_binding(
            ModulationBinding(
                node="a", param="x", source="rms", scale=2.0, offset=0.0, smoothing=0.0
            )
        )
        updates = m.tick({"rms": 0.5})
        assert updates[("a", "x")] == pytest.approx(1.0)

    def test_offset(self):
        m = UniformModulator()
        m.add_binding(
            ModulationBinding(
                node="a", param="x", source="rms", scale=1.0, offset=0.3, smoothing=0.0
            )
        )
        updates = m.tick({"rms": 0.5})
        assert updates[("a", "x")] == pytest.approx(0.8)

    def test_scale_and_offset(self):
        m = UniformModulator()
        m.add_binding(
            ModulationBinding(
                node="a", param="x", source="rms", scale=0.5, offset=0.7, smoothing=0.0
            )
        )
        updates = m.tick({"rms": 0.6})
        assert updates[("a", "x")] == pytest.approx(1.0)

    def test_missing_signal_skipped(self):
        m = UniformModulator()
        m.add_binding(ModulationBinding(node="a", param="x", source="nonexistent"))
        updates = m.tick({"rms": 0.5})
        assert ("a", "x") not in updates

    def test_multiple_bindings(self):
        m = UniformModulator()
        m.add_binding(ModulationBinding(node="a", param="x", source="rms", smoothing=0.0))
        m.add_binding(ModulationBinding(node="b", param="y", source="beat", smoothing=0.0))
        updates = m.tick({"rms": 0.5, "beat": 0.8})
        assert ("a", "x") in updates and ("b", "y") in updates

    def test_zero_signal(self):
        m = UniformModulator()
        m.add_binding(ModulationBinding(node="a", param="x", source="rms", smoothing=0.0))
        updates = m.tick({"rms": 0.0})
        assert updates[("a", "x")] == pytest.approx(0.0)


class TestModulatorSmoothing:
    def test_first_tick_no_smoothing_effect(self):
        m = UniformModulator()
        m.add_binding(ModulationBinding(node="a", param="x", source="rms", smoothing=0.9))
        updates = m.tick({"rms": 1.0})
        assert updates[("a", "x")] == pytest.approx(1.0)

    def test_smoothing_decays(self):
        m = UniformModulator()
        m.add_binding(ModulationBinding(node="a", param="x", source="rms", smoothing=0.5))
        m.tick({"rms": 1.0})
        u2 = m.tick({"rms": 0.0})
        # smoothed = 0.5 * 1.0 + 0.5 * 0.0 = 0.5
        assert u2[("a", "x")] == pytest.approx(0.5)

    def test_smoothing_converges(self):
        m = UniformModulator()
        m.add_binding(ModulationBinding(node="a", param="x", source="rms", smoothing=0.5))
        m.tick({"rms": 1.0})
        for _ in range(20):
            u = m.tick({"rms": 0.0})
        assert u[("a", "x")] < 0.001  # should converge to 0

    def test_no_smoothing(self):
        m = UniformModulator()
        m.add_binding(ModulationBinding(node="a", param="x", source="rms", smoothing=0.0))
        m.tick({"rms": 1.0})
        u2 = m.tick({"rms": 0.0})
        assert u2[("a", "x")] == pytest.approx(0.0)  # no smoothing = instant


# ============================================================================
# 5. GRAPH RUNTIME — mutation levels, state, callbacks
# ============================================================================


class TestRuntimeInitial:
    def test_initial_state(self, runtime: GraphRuntime):
        assert runtime.current_graph is None
        assert runtime.current_plan is None

    def test_initial_palettes(self, runtime: GraphRuntime):
        for layer in ("live", "smooth", "hls"):
            p = runtime.get_layer_palette(layer)
            assert p.saturation == 1.0

    def test_initial_state_export(self, runtime: GraphRuntime):
        state = runtime.get_graph_state()
        assert state["graph"] is None


class TestRuntimeLevel1ParamPatch:
    def test_patch_updates_graph(self, runtime: GraphRuntime):
        runtime.load_graph(_minimal_graph())
        runtime.patch_node_params("c", {"saturation": 0.3})
        assert runtime.current_graph.nodes["c"].params["saturation"] == 0.3

    def test_patch_preserves_other_params(self, runtime: GraphRuntime):
        g = EffectGraph(
            nodes={
                "c": NodeInstance(type="colorgrade", params={"saturation": 1.0, "brightness": 1.0}),
                "o": NodeInstance(type="output"),
            },
            edges=[["@live", "c"], ["c", "o"]],
        )
        runtime.load_graph(g)
        runtime.patch_node_params("c", {"saturation": 0.5})
        assert runtime.current_graph.nodes["c"].params["brightness"] == 1.0

    def test_patch_nonexistent_node(self, runtime: GraphRuntime):
        runtime.load_graph(_minimal_graph())
        runtime.patch_node_params("nonexistent", {"x": 1})  # should not raise

    def test_patch_no_graph(self, runtime: GraphRuntime):
        runtime.patch_node_params("c", {"x": 1})  # should not raise

    def test_patch_fires_callback(self, runtime: GraphRuntime):
        calls = []
        runtime._on_params_changed = lambda nid, p: calls.append((nid, dict(p)))
        runtime.load_graph(_minimal_graph())
        runtime.patch_node_params("c", {"saturation": 0.5})
        assert len(calls) == 1
        assert calls[0][0] == "c"


class TestRuntimeLevel2TopologyMutation:
    def test_add_node(self, runtime: GraphRuntime):
        runtime.load_graph(_minimal_graph())
        runtime.apply_patch(
            GraphPatch(
                add_nodes={"bloom": NodeInstance(type="bloom")},
                add_edges=[["c", "bloom"], ["bloom", "o"]],
                remove_edges=[["c", "o"]],
            )
        )
        assert "bloom" in runtime.current_graph.nodes

    def test_remove_node(self, runtime: GraphRuntime):
        g = EffectGraph(
            nodes={
                "c": NodeInstance(type="colorgrade"),
                "s": NodeInstance(type="scanlines"),
                "o": NodeInstance(type="output"),
            },
            edges=[["@live", "c"], ["c", "s"], ["s", "o"]],
        )
        runtime.load_graph(g)
        runtime.apply_patch(
            GraphPatch(
                remove_nodes=["s"],
                add_edges=[["c", "o"]],
                remove_edges=[["c", "s"], ["s", "o"]],
            )
        )
        assert "s" not in runtime.current_graph.nodes
        assert ["c", "o"] in runtime.current_graph.edges

    def test_remove_node_helper(self, runtime: GraphRuntime):
        g = EffectGraph(
            nodes={
                "c": NodeInstance(type="colorgrade"),
                "s": NodeInstance(type="scanlines"),
                "o": NodeInstance(type="output"),
            },
            edges=[["@live", "c"], ["c", "o"], ["c", "s"]],
        )
        runtime.load_graph(g)
        # remove_node removes node + its edges — works for leaf nodes
        runtime.remove_node("s")
        assert "s" not in runtime.current_graph.nodes
        assert runtime.current_plan is not None

    def test_mutation_recompiles(self, runtime: GraphRuntime):
        runtime.load_graph(_minimal_graph())
        old_plan = runtime.current_plan
        runtime.apply_patch(
            GraphPatch(
                add_nodes={"bloom": NodeInstance(type="bloom")},
                add_edges=[["c", "bloom"], ["bloom", "o"]],
                remove_edges=[["c", "o"]],
            )
        )
        assert runtime.current_plan is not old_plan

    def test_mutation_fires_callback(self, runtime: GraphRuntime):
        calls = []
        runtime._on_plan_changed = lambda old, new: calls.append(True)
        runtime.load_graph(_minimal_graph())
        calls.clear()
        runtime.apply_patch(
            GraphPatch(
                add_nodes={"bloom": NodeInstance(type="bloom")},
                add_edges=[["c", "bloom"], ["bloom", "o"]],
                remove_edges=[["c", "o"]],
            )
        )
        assert len(calls) == 1

    def test_mutation_no_graph(self, runtime: GraphRuntime):
        runtime.apply_patch(GraphPatch())  # should not raise


class TestRuntimeLevel3FullReplace:
    def test_load_replaces(self, runtime: GraphRuntime):
        runtime.load_graph(_minimal_graph(name="first"))
        runtime.load_graph(_minimal_graph(name="second"))
        assert runtime.current_graph.name == "second"

    def test_load_replaces_modulations(self, runtime: GraphRuntime):
        g1 = EffectGraph(
            nodes={"c": NodeInstance(type="colorgrade"), "o": NodeInstance(type="output")},
            edges=[["@live", "c"], ["c", "o"]],
            modulations=[ModulationBinding(node="c", param="saturation", source="rms")],
        )
        runtime.load_graph(g1)
        assert len(runtime.modulator.bindings) == 1

        g2 = _minimal_graph()
        runtime.load_graph(g2)
        assert len(runtime.modulator.bindings) == 0

    def test_load_applies_palettes(self, runtime: GraphRuntime):
        g = EffectGraph(
            nodes={"c": NodeInstance(type="colorgrade"), "o": NodeInstance(type="output")},
            edges=[["@live", "c"], ["c", "o"]],
            layer_palettes={"live": LayerPalette(saturation=0.3)},
        )
        runtime.load_graph(g)
        assert runtime.get_layer_palette("live").saturation == 0.3

    def test_load_fires_callback(self, runtime: GraphRuntime):
        calls = []
        runtime._on_plan_changed = lambda old, new: calls.append(True)
        runtime.load_graph(_minimal_graph())
        assert len(calls) == 1

    def test_deepcopy_isolation(self, runtime: GraphRuntime):
        g = _minimal_graph()
        runtime.load_graph(g)
        g.nodes["c"].params["saturation"] = 999
        assert runtime.current_graph.nodes["c"].params.get("saturation") != 999


class TestRuntimeLayerPalettes:
    def test_set_and_get(self, runtime: GraphRuntime):
        runtime.set_layer_palette("live", LayerPalette(saturation=0.5, hue_rotate=-30))
        p = runtime.get_layer_palette("live")
        assert p.saturation == 0.5 and p.hue_rotate == -30

    def test_independent_layers(self, runtime: GraphRuntime):
        runtime.set_layer_palette("live", LayerPalette(saturation=0.5))
        runtime.set_layer_palette("smooth", LayerPalette(saturation=0.8))
        assert runtime.get_layer_palette("live").saturation == 0.5
        assert runtime.get_layer_palette("smooth").saturation == 0.8

    def test_unknown_layer_returns_default(self, runtime: GraphRuntime):
        p = runtime.get_layer_palette("nonexistent")
        assert p.saturation == 1.0

    def test_set_unknown_layer_ignored(self, runtime: GraphRuntime):
        runtime.set_layer_palette("nonexistent", LayerPalette(saturation=0.1))
        # Should not raise, palette not stored


class TestRuntimeStateExport:
    def test_no_graph(self, runtime: GraphRuntime):
        state = runtime.get_graph_state()
        assert state["graph"] is None
        assert state["layer_palettes"] == {}
        assert state["modulations"] == []

    def test_with_graph(self, runtime: GraphRuntime):
        runtime.load_graph(_minimal_graph(name="test"))
        state = runtime.get_graph_state()
        assert state["graph"]["name"] == "test"
        assert "live" in state["layer_palettes"]

    def test_state_serializable(self, runtime: GraphRuntime):
        runtime.load_graph(_minimal_graph())
        state = runtime.get_graph_state()
        serialized = json.dumps(state)
        assert len(serialized) > 0


# ============================================================================
# 6. PRESET LOADING — all 28 presets parse, validate, compile
# ============================================================================


class TestPresetParsing:
    """Every preset file must parse into a valid EffectGraph."""

    @pytest.fixture(scope="class")
    def preset_files(self) -> list[Path]:
        return sorted(p for p in PRESETS_DIR.glob("*.json") if not p.name.startswith("_"))

    def test_preset_count(self, preset_files: list[Path]):
        assert len(preset_files) >= 28, f"Expected >=28 presets, got {len(preset_files)}"

    def test_all_presets_parse(self, preset_files: list[Path]):
        for p in preset_files:
            raw = json.loads(p.read_text())
            g = EffectGraph(**raw)
            assert g.name, f"{p.stem} has no name"
            assert len(g.nodes) >= 2, f"{p.stem} has fewer than 2 nodes"
            assert len(g.edges) >= 1, f"{p.stem} has no edges"

    def test_all_presets_have_output(self, preset_files: list[Path]):
        for p in preset_files:
            raw = json.loads(p.read_text())
            g = EffectGraph(**raw)
            has_output = any(n.type == "output" for n in g.nodes.values())
            assert has_output, f"{p.stem} has no output node"

    def test_all_presets_have_layer_source(self, preset_files: list[Path]):
        for p in preset_files:
            if p.stem.startswith("reverie_"):
                continue  # Reverie presets are generative (noise_gen root, no @live)
            raw = json.loads(p.read_text())
            g = EffectGraph(**raw)
            has_layer = any(e[0].startswith("@") for e in g.edges)
            assert has_layer, f"{p.stem} has no layer source"


class TestPresetCompilation:
    """Every preset must compile successfully against the real registry."""

    def test_all_presets_compile(self, compiler: GraphCompiler):
        for p in sorted(p for p in PRESETS_DIR.glob("*.json") if not p.name.startswith("_")):
            raw = json.loads(p.read_text())
            g = EffectGraph(**raw)
            plan = compiler.compile(g)
            assert len(plan.steps) >= 2, f"{p.stem} compiled to fewer than 2 steps"
            if not p.stem.startswith("reverie_"):
                assert plan.layer_sources, f"{p.stem} has no layer sources"

    def test_all_preset_node_types_exist(self, registry: ShaderRegistry):
        """Every node type used in presets must exist in the registry."""
        for p in sorted(p for p in PRESETS_DIR.glob("*.json") if not p.name.startswith("_")):
            raw = json.loads(p.read_text())
            g = EffectGraph(**raw)
            for nid, node in g.nodes.items():
                if node.type == "output":
                    continue
                assert registry.get(node.type), (
                    f"{p.stem}: unknown node type '{node.type}' in node '{nid}'"
                )


class TestPresetRuntime:
    """Presets load correctly into the runtime."""

    def test_all_presets_load(self, runtime: GraphRuntime):
        for p in sorted(p for p in PRESETS_DIR.glob("*.json") if not p.name.startswith("_")):
            raw = json.loads(p.read_text())
            g = EffectGraph(**raw)
            runtime.load_graph(g)
            assert runtime.current_graph.name == g.name, f"{p.stem} name mismatch"
            assert runtime.current_plan is not None, f"{p.stem} has no plan"

    def test_preset_modulations_applied(self, runtime: GraphRuntime):
        """Presets with modulations should have them loaded into the modulator."""
        for p in sorted(p for p in PRESETS_DIR.glob("*.json") if not p.name.startswith("_")):
            raw = json.loads(p.read_text())
            g = EffectGraph(**raw)
            runtime.load_graph(g)
            assert len(runtime.modulator.bindings) == len(g.modulations), (
                f"{p.stem}: expected {len(g.modulations)} bindings, got {len(runtime.modulator.bindings)}"
            )


# ============================================================================
# 7. INTEGRATION — end-to-end flows
# ============================================================================


class TestEndToEnd:
    def test_load_patch_export(self, runtime: GraphRuntime):
        """Load a graph, patch params, export state."""
        runtime.load_graph(_minimal_graph(name="e2e"))
        runtime.patch_node_params("c", {"saturation": 0.5})
        state = runtime.get_graph_state()
        assert state["graph"]["nodes"]["c"]["params"]["saturation"] == 0.5

    def test_load_mutate_load(self, runtime: GraphRuntime):
        """Load → mutate topology → load new graph (full replace)."""
        runtime.load_graph(_minimal_graph(name="first"))
        runtime.apply_patch(
            GraphPatch(
                add_nodes={"bloom": NodeInstance(type="bloom")},
                add_edges=[["c", "bloom"], ["bloom", "o"]],
                remove_edges=[["c", "o"]],
            )
        )
        assert "bloom" in runtime.current_graph.nodes

        # Full replace should clear the mutation
        runtime.load_graph(_minimal_graph(name="second"))
        assert "bloom" not in runtime.current_graph.nodes

    def test_modulator_drives_params(self, runtime: GraphRuntime):
        """Load graph with modulation, tick, verify params update."""
        g = EffectGraph(
            name="mod",
            nodes={
                "c": NodeInstance(type="colorgrade", params={"saturation": 1.0}),
                "o": NodeInstance(type="output"),
            },
            edges=[["@live", "c"], ["c", "o"]],
            modulations=[
                ModulationBinding(
                    node="c",
                    param="saturation",
                    source="audio_rms",
                    scale=0.5,
                    offset=0.5,
                    smoothing=0.0,
                )
            ],
        )
        patched = []
        runtime._on_params_changed = lambda nid, p: patched.append((nid, dict(p)))
        runtime.load_graph(g)
        updates = runtime.modulator.tick({"audio_rms": 0.8})
        # value = 0.8 * 0.5 + 0.5 = 0.9
        assert updates[("c", "saturation")] == pytest.approx(0.9)

    def test_preset_roundtrip(self, runtime: GraphRuntime, compiler: GraphCompiler):
        """Load preset, export, reimport, compare."""
        raw = json.loads((PRESETS_DIR / "ghost.json").read_text())
        g = EffectGraph(**raw)
        runtime.load_graph(g)
        state = runtime.get_graph_state()

        # Reimport from state
        g2 = EffectGraph(**state["graph"])
        plan2 = compiler.compile(g2)
        assert plan2.name == "Ghost"
        assert len(plan2.steps) == len(runtime.current_plan.steps)

    def test_complex_graph_all_node_categories(self, compiler: GraphCompiler):
        """A graph using processing, temporal, and compositing nodes together."""
        g = EffectGraph(
            name="complex",
            nodes={
                "color": NodeInstance(type="colorgrade", params={"saturation": 0.8}),
                "trail": NodeInstance(type="trail", params={"fade": 0.03}),
                "bloom": NodeInstance(type="bloom", params={"threshold": 0.4}),
                "scan": NodeInstance(type="scanlines"),
                "vig": NodeInstance(type="vignette"),
                "out": NodeInstance(type="output"),
            },
            edges=[
                ["@live", "color"],
                ["color", "trail"],
                ["trail", "bloom"],
                ["bloom", "scan"],
                ["scan", "vig"],
                ["vig", "out"],
            ],
        )
        plan = compiler.compile(g)
        assert len(plan.steps) == 6
        order = [s.node_id for s in plan.steps]
        assert order.index("color") < order.index("trail") < order.index("bloom")

        # Verify temporal flag
        trail_step = next(s for s in plan.steps if s.node_id == "trail")
        assert trail_step.temporal

    def test_dual_source_blend(self, compiler: GraphCompiler):
        """Live + smooth → blend → effects → output."""
        g = EffectGraph(
            name="dual",
            nodes={
                "grade_live": NodeInstance(type="colorgrade"),
                "grade_smooth": NodeInstance(type="colorgrade"),
                "mix": NodeInstance(type="blend", params={"alpha": 0.3}),
                "bloom": NodeInstance(type="bloom"),
                "out": NodeInstance(type="output"),
            },
            edges=[
                ["@live", "grade_live"],
                ["@smooth", "grade_smooth"],
                ["grade_live", "mix:a"],
                ["grade_smooth", "mix:b"],
                ["mix", "bloom"],
                ["bloom", "out"],
            ],
        )
        plan = compiler.compile(g)
        assert "@live" in plan.layer_sources
        assert "@smooth" in plan.layer_sources
        assert len(plan.steps) == 5
