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


def test_registry_backend_default(real_registry):
    """Phase 3a: every shipped manifest declares backend=wgsl_render."""
    # All node manifests committed in Phase 3a have an explicit backend.
    # The default ("wgsl_render") is preserved when the field is missing.
    d = real_registry.get("colorgrade")
    assert d is not None and d.backend == "wgsl_render"


def test_registry_backend_default_when_field_missing(tmp_path: Path):
    """A manifest without a backend field defaults to wgsl_render."""
    nodes = tmp_path / "nodes"
    nodes.mkdir()
    (nodes / "noback.json").write_text(
        json.dumps(
            {
                "node_type": "noback",
                "glsl_fragment": "noback.frag",
                "inputs": {"in": "frame"},
                "outputs": {"out": "frame"},
                "params": {},
                "temporal": False,
            }
        )
    )
    reg = ShaderRegistry(nodes)
    d = reg.get("noback")
    assert d is not None
    assert d.backend == "wgsl_render"


def test_registry_backend_explicit_value_preserved(tmp_path: Path):
    """A manifest with backend=cairo round-trips to the loaded def."""
    nodes = tmp_path / "nodes"
    nodes.mkdir()
    (nodes / "fakeworm.json").write_text(
        json.dumps(
            {
                "node_type": "fakeworm",
                "backend": "cairo",
                "inputs": {},
                "outputs": {"out": "frame"},
                "params": {},
                "temporal": False,
            }
        )
    )
    reg = ShaderRegistry(nodes)
    d = reg.get("fakeworm")
    assert d is not None
    assert d.backend == "cairo"


def test_registry_schema_includes_backend(real_registry):
    """ShaderRegistry.schema(node_type) exposes backend for UI/API consumers."""
    schema = real_registry.schema("colorgrade")
    assert schema is not None
    assert schema["backend"] == "wgsl_render"


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


# --- Phase 5a: multi-output compile ---


def test_compile_default_target_is_main(compiler):
    """Single-output graph defaults to one target named ``main``."""
    g = EffectGraph(
        name="t",
        nodes={
            "c": NodeInstance(type="colorgrade"),
            "o": NodeInstance(type="output"),
        },
        edges=[["@live", "c"], ["c", "o"]],
    )
    plan = compiler.compile(g)
    assert plan.target_names == ("main",)
    assert "main" in plan.targets
    # Backwards-compat: steps property is the union of every target.
    assert len(plan.steps) == len(plan.targets["main"])


def test_compile_explicit_target_name(compiler):
    """params.target on the output node sets the target name."""
    g = EffectGraph(
        name="t",
        nodes={
            "c": NodeInstance(type="colorgrade"),
            "o": NodeInstance(type="output", params={"target": "preview"}),
        },
        edges=[["@live", "c"], ["c", "o"]],
    )
    plan = compiler.compile(g)
    assert plan.target_names == ("preview",)
    assert "preview" in plan.targets


def test_compile_two_outputs_two_targets(compiler):
    """Two output nodes → two targets, each with its own per-target step list."""
    g = EffectGraph(
        name="t",
        nodes={
            "c": NodeInstance(type="colorgrade"),
            "main_out": NodeInstance(type="output", params={"target": "main"}),
            "hud_out": NodeInstance(type="output", params={"target": "hud"}),
        },
        edges=[
            ["@live", "c"],
            ["c", "main_out"],
            ["c", "hud_out"],
        ],
    )
    plan = compiler.compile(g)
    assert plan.target_names == ("hud", "main")
    # Each target's step list contains the colorgrade node + its output.
    main_ids = [s.node_id for s in plan.targets["main"]]
    hud_ids = [s.node_id for s in plan.targets["hud"]]
    assert "c" in main_ids
    assert "c" in hud_ids
    assert "main_out" in main_ids
    assert "hud_out" in hud_ids


def test_compile_per_target_topo_sort_independent(compiler):
    """Each target gets its own topological order; predecessors of one
    output don't pollute the order of another output's chain."""
    g = EffectGraph(
        name="t",
        nodes={
            "shared": NodeInstance(type="colorgrade"),
            "a_only": NodeInstance(type="bloom"),
            "b_only": NodeInstance(type="scanlines"),
            "main_out": NodeInstance(type="output", params={"target": "main"}),
            "hud_out": NodeInstance(type="output", params={"target": "hud"}),
        },
        edges=[
            ["@live", "shared"],
            ["shared", "a_only"],
            ["a_only", "main_out"],
            ["shared", "b_only"],
            ["b_only", "hud_out"],
        ],
    )
    plan = compiler.compile(g)
    main_ids = [s.node_id for s in plan.targets["main"]]
    hud_ids = [s.node_id for s in plan.targets["hud"]]
    # main contains shared + a_only + main_out, in dependency order.
    assert main_ids.index("shared") < main_ids.index("a_only")
    assert main_ids.index("a_only") < main_ids.index("main_out")
    assert "b_only" not in main_ids
    assert "hud_out" not in main_ids
    # hud contains shared + b_only + hud_out, in dependency order.
    assert hud_ids.index("shared") < hud_ids.index("b_only")
    assert hud_ids.index("b_only") < hud_ids.index("hud_out")
    assert "a_only" not in hud_ids
    assert "main_out" not in hud_ids


def test_compile_rejects_duplicate_target_names(compiler):
    """Two outputs with the same target name are an error."""
    g = EffectGraph(
        name="t",
        nodes={
            "c": NodeInstance(type="colorgrade"),
            "out1": NodeInstance(type="output", params={"target": "main"}),
            "out2": NodeInstance(type="output", params={"target": "main"}),
        },
        edges=[
            ["@live", "c"],
            ["c", "out1"],
            ["c", "out2"],
        ],
    )
    with pytest.raises(GraphValidationError, match="duplicate target names"):
        compiler.compile(g)


def test_execution_plan_steps_property_concatenates_targets(compiler):
    """The backwards-compat steps property returns concatenated target
    steps in stable (sorted) target name order."""
    g = EffectGraph(
        name="t",
        nodes={
            "c": NodeInstance(type="colorgrade"),
            "main_out": NodeInstance(type="output", params={"target": "main"}),
            "hud_out": NodeInstance(type="output", params={"target": "hud"}),
        },
        edges=[
            ["@live", "c"],
            ["c", "main_out"],
            ["c", "hud_out"],
        ],
    )
    plan = compiler.compile(g)
    # Sorted target names: ("hud", "main"). steps is hud's then main's.
    expected = list(plan.targets["hud"]) + list(plan.targets["main"])
    assert plan.steps == expected


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
    assert g.name == "Ghost"
    assert len(g.edges) == 8
    assert ["colorgrade", "posterize_subtle"] in g.edges
    assert ["posterize_subtle", "trail"] in g.edges


def test_trails():
    g = EffectGraph(**json.loads((PRESETS_DIR / "trails.json").read_text()))
    # PR #2809 ("bulk-add 141 audio modulations to 77 low-variance presets")
    # added two further audio bindings on top of the original single binding;
    # the assertion follows the preset rather than re-pinning a stale count.
    assert g.name == "Trails" and len(g.modulations) == 3


def test_clean():
    g = EffectGraph(**json.loads((PRESETS_DIR / "clean.json").read_text()))
    assert g.name == "Clean" and g.transition_ms == 300


# --- Integration ---


def test_preset_compile_roundtrip(real_registry, monkeypatch):
    monkeypatch.setenv("HAPAX_LIVE_SURFACE_EFFECT_POLICY", "0")
    compiler = GraphCompiler(real_registry)
    modulator = UniformModulator()
    runtime = GraphRuntime(registry=real_registry, compiler=compiler, modulator=modulator)
    for name in ["ghost", "trails", "clean"]:
        g = EffectGraph(**json.loads((PRESETS_DIR / f"{name}.json").read_text()))
        runtime.load_graph(g)
        assert runtime.current_plan is not None
        assert len(runtime.current_plan.steps) > 0
