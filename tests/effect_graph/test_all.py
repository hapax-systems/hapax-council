"""Comprehensive tests for the effect node graph system."""

import json
from pathlib import Path

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
)

# --- Types ---


def test_param_def():
    p = ParamDef(type="float", default=0.5, min=0.0, max=1.0)
    assert p.default == 0.5


def test_edge_def_simple():
    e = EdgeDef.from_list(["a", "b"])
    assert e.source_node == "a" and e.target_node == "b"


def test_edge_def_ports():
    e = EdgeDef.from_list(["@live", "blend:a"])
    assert e.target_port == "a" and e.is_layer_source


def test_edge_def_bad():
    with pytest.raises(ValueError):
        EdgeDef.from_list(["only"])


def test_layer_palette_validation():
    with pytest.raises(ValidationError):
        LayerPalette(saturation=5.0)


def test_smoothing_validation():
    with pytest.raises(ValidationError):
        ModulationBinding(node="x", param="y", source="z", smoothing=1.5)


def test_effect_graph_parsed_edges():
    g = EffectGraph(
        name="t",
        nodes={"c": NodeInstance(type="colorgrade"), "o": NodeInstance(type="output")},
        edges=[["@live", "c"], ["c", "o"]],
    )
    assert len(g.parsed_edges) == 2


# --- Registry ---


@pytest.fixture
def real_registry():
    return ShaderRegistry(Path("agents/shaders/nodes"))


def test_registry_loads(real_registry):
    assert len(real_registry.node_types) >= 9


def test_registry_get(real_registry):
    d = real_registry.get("colorgrade")
    assert d is not None and d.glsl_source is not None


def test_registry_output_no_shader(real_registry):
    d = real_registry.get("output")
    assert d is not None and d.glsl_source is None


def test_registry_trail_temporal(real_registry):
    d = real_registry.get("trail")
    assert d is not None and d.temporal


# --- Compiler ---


@pytest.fixture
def compiler(real_registry):
    return GraphCompiler(real_registry)


def test_compile_linear(compiler):
    g = EffectGraph(
        name="t",
        nodes={
            "c": NodeInstance(type="colorgrade"),
            "s": NodeInstance(type="scanlines"),
            "o": NodeInstance(type="output"),
        },
        edges=[["@live", "c"], ["c", "s"], ["s", "o"]],
    )
    plan = compiler.compile(g)
    order = [s.node_id for s in plan.steps]
    assert order.index("c") < order.index("s") < order.index("o")


def test_compile_branch(compiler):
    g = EffectGraph(
        name="t",
        nodes={
            "a": NodeInstance(type="colorgrade"),
            "b": NodeInstance(type="colorgrade"),
            "m": NodeInstance(type="blend"),
            "o": NodeInstance(type="output"),
        },
        edges=[["@live", "a"], ["@smooth", "b"], ["a", "m:a"], ["b", "m:b"], ["m", "o"]],
    )
    plan = compiler.compile(g)
    order = [s.node_id for s in plan.steps]
    assert order.index("a") < order.index("m") and order.index("b") < order.index("m")


def test_reject_cycle(compiler):
    g = EffectGraph(
        name="t",
        nodes={
            "a": NodeInstance(type="colorgrade"),
            "b": NodeInstance(type="colorgrade"),
            "o": NodeInstance(type="output"),
        },
        edges=[["@live", "a"], ["a", "b"], ["b", "a"], ["b", "o"]],
    )
    with pytest.raises(GraphValidationError):
        compiler.compile(g)


def test_reject_no_output(compiler):
    g = EffectGraph(name="t", nodes={"c": NodeInstance(type="colorgrade")}, edges=[["@live", "c"]])
    with pytest.raises(GraphValidationError):
        compiler.compile(g)


def test_reject_unknown(compiler):
    g = EffectGraph(
        name="t",
        nodes={"x": NodeInstance(type="nope"), "o": NodeInstance(type="output")},
        edges=[["@live", "x"], ["x", "o"]],
    )
    with pytest.raises(GraphValidationError):
        compiler.compile(g)


def test_reject_disconnected(compiler):
    g = EffectGraph(
        name="t",
        nodes={
            "c": NodeInstance(type="colorgrade"),
            "z": NodeInstance(type="scanlines"),
            "o": NodeInstance(type="output"),
        },
        edges=[["@live", "c"], ["c", "o"]],
    )
    with pytest.raises(GraphValidationError):
        compiler.compile(g)


def test_reject_bad_layer(compiler):
    g = EffectGraph(name="t", nodes={"o": NodeInstance(type="output")}, edges=[["@invalid", "o"]])
    with pytest.raises(GraphValidationError):
        compiler.compile(g)


def test_fanout_fbo(compiler):
    g = EffectGraph(
        name="t",
        nodes={
            "c": NodeInstance(type="colorgrade"),
            "s": NodeInstance(type="scanlines"),
            "b": NodeInstance(type="bloom"),
            "m": NodeInstance(type="blend"),
            "o": NodeInstance(type="output"),
        },
        edges=[["@live", "c"], ["c", "s"], ["c", "b"], ["s", "m:a"], ["b", "m:b"], ["m", "o"]],
    )
    plan = compiler.compile(g)
    assert next(s for s in plan.steps if s.node_id == "c").needs_dedicated_fbo


# --- Modulator ---


def test_modulator_tick():
    m = UniformModulator()
    m.add_binding(
        ModulationBinding(node="b", param="a", source="rms", scale=1.0, offset=0.0, smoothing=0.0)
    )
    assert m.tick({"rms": 0.8})[("b", "a")] == pytest.approx(0.8)


def test_modulator_missing():
    m = UniformModulator()
    m.add_binding(ModulationBinding(node="b", param="a", source="nope"))
    assert ("b", "a") not in m.tick({"rms": 0.5})


def test_modulator_replace():
    m = UniformModulator()
    m.add_binding(ModulationBinding(node="a", param="x", source="rms"))
    m.replace_all([ModulationBinding(node="b", param="y", source="beat")])
    assert len(m.bindings) == 1 and m.bindings[0].node == "b"


# --- Runtime ---


@pytest.fixture
def runtime(real_registry):
    return GraphRuntime(
        registry=real_registry, compiler=GraphCompiler(real_registry), modulator=UniformModulator()
    )


def test_runtime_load(runtime):
    g = EffectGraph(
        name="t",
        nodes={"c": NodeInstance(type="colorgrade"), "o": NodeInstance(type="output")},
        edges=[["@live", "c"], ["c", "o"]],
    )
    runtime.load_graph(g)
    assert runtime.current_graph.name == "t" and runtime.current_plan is not None


def test_runtime_patch(runtime):
    g = EffectGraph(
        name="t",
        nodes={
            "c": NodeInstance(type="colorgrade", params={"saturation": 1.0}),
            "o": NodeInstance(type="output"),
        },
        edges=[["@live", "c"], ["c", "o"]],
    )
    runtime.load_graph(g)
    runtime.patch_node_params("c", {"saturation": 0.5})
    assert runtime.current_graph.nodes["c"].params["saturation"] == 0.5


def test_runtime_topology(runtime):
    g = EffectGraph(
        name="t",
        nodes={"c": NodeInstance(type="colorgrade"), "o": NodeInstance(type="output")},
        edges=[["@live", "c"], ["c", "o"]],
    )
    runtime.load_graph(g)
    runtime.apply_patch(
        GraphPatch(
            add_nodes={"b": NodeInstance(type="bloom")},
            add_edges=[["c", "b"], ["b", "o"]],
            remove_edges=[["c", "o"]],
        )
    )
    assert "b" in runtime.current_graph.nodes


def test_runtime_palette(runtime):
    runtime.set_layer_palette("live", LayerPalette(saturation=0.5))
    assert runtime.get_layer_palette("live").saturation == 0.5


def test_runtime_modulations(runtime):
    g = EffectGraph(
        name="t",
        nodes={"c": NodeInstance(type="colorgrade"), "o": NodeInstance(type="output")},
        edges=[["@live", "c"], ["c", "o"]],
        modulations=[ModulationBinding(node="c", param="saturation", source="audio_rms")],
    )
    runtime.load_graph(g)
    assert len(runtime.modulator.bindings) == 1


def test_runtime_state(runtime):
    g = EffectGraph(
        name="t",
        nodes={"c": NodeInstance(type="colorgrade"), "o": NodeInstance(type="output")},
        edges=[["@live", "c"], ["c", "o"]],
    )
    runtime.load_graph(g)
    s = runtime.get_graph_state()
    assert s["graph"] is not None


# --- Presets ---


PRESETS_DIR = Path(__file__).parent.parent.parent / "presets"


def test_ghost():
    g = EffectGraph(**json.loads((PRESETS_DIR / "ghost.json").read_text()))
    assert g.name == "Ghost" and len(g.edges) == 3


def test_trails():
    g = EffectGraph(**json.loads((PRESETS_DIR / "trails.json").read_text()))
    assert g.name == "Trails" and len(g.modulations) == 2


def test_clean():
    g = EffectGraph(**json.loads((PRESETS_DIR / "clean.json").read_text()))
    assert g.name == "Clean" and g.transition_ms == 300


# --- Integration ---


def test_preset_compile_roundtrip(real_registry):
    compiler = GraphCompiler(real_registry)
    modulator = UniformModulator()
    runtime = GraphRuntime(registry=real_registry, compiler=compiler, modulator=modulator)
    for name in ["ghost", "trails", "clean"]:
        g = EffectGraph(**json.loads((PRESETS_DIR / f"{name}.json").read_text()))
        runtime.load_graph(g)
        assert runtime.current_plan is not None
        assert len(runtime.current_plan.steps) > 0
