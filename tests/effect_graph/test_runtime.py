"""Tests for graph runtime."""

import json
from pathlib import Path

import pytest

from agents.effect_graph.compiler import GraphCompiler
from agents.effect_graph.modulator import UniformModulator
from agents.effect_graph.registry import ShaderRegistry
from agents.effect_graph.runtime import GraphRuntime
from agents.effect_graph.types import (
    EffectGraph,
    GraphPatch,
    LayerPalette,
    ModulationBinding,
    NodeInstance,
)


@pytest.fixture
def registry(tmp_path: Path) -> ShaderRegistry:
    nodes_dir = tmp_path / "nodes"
    nodes_dir.mkdir()
    for nt, ins, outs, temp in [
        ("colorgrade", {"in": "frame"}, {"out": "frame"}, False),
        ("trail", {"in": "frame"}, {"out": "frame"}, True),
        ("bloom", {"in": "frame"}, {"out": "frame"}, False),
        ("scanlines", {"in": "frame"}, {"out": "frame"}, False),
        ("vignette", {"in": "frame"}, {"out": "frame"}, False),
        ("noise_overlay", {"in": "frame"}, {"out": "frame"}, False),
        ("output", {"in": "frame"}, {}, False),
    ]:
        (nodes_dir / f"{nt}.json").write_text(
            json.dumps(
                {
                    "node_type": nt,
                    "glsl_fragment": "",
                    "inputs": ins,
                    "outputs": outs,
                    "params": {},
                    "temporal": temp,
                    "temporal_buffers": 1 if temp else 0,
                }
            )
        )
    return ShaderRegistry(nodes_dir)


@pytest.fixture
def runtime(registry: ShaderRegistry) -> GraphRuntime:
    return GraphRuntime(
        registry=registry,
        compiler=GraphCompiler(registry),
        modulator=UniformModulator(),
    )


def test_initial_state(runtime):
    assert runtime.current_graph is None
    assert runtime.current_plan is None


def test_load_graph(runtime):
    g = EffectGraph(
        name="t",
        nodes={"c": NodeInstance(type="colorgrade"), "o": NodeInstance(type="output")},
        edges=[["@live", "c"], ["c", "o"]],
    )
    runtime.load_graph(g)
    assert runtime.current_graph.name == "t"
    assert runtime.current_plan is not None


def test_patch_params(runtime):
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


def test_topology_mutation(runtime):
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
    assert ["c", "o"] not in runtime.current_graph.edges


def test_remove_node(runtime):
    g = EffectGraph(
        name="t",
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


def test_layer_palette(runtime):
    runtime.set_layer_palette("live", LayerPalette(saturation=0.5, hue_rotate=-10))
    p = runtime.get_layer_palette("live")
    assert p.saturation == 0.5


def test_modulations_from_graph(runtime):
    g = EffectGraph(
        name="t",
        nodes={"c": NodeInstance(type="colorgrade"), "o": NodeInstance(type="output")},
        edges=[["@live", "c"], ["c", "o"]],
        modulations=[ModulationBinding(node="c", param="saturation", source="audio_rms")],
    )
    runtime.load_graph(g)
    assert len(runtime.modulator.bindings) == 1


def test_get_graph_state(runtime):
    g = EffectGraph(
        name="t",
        nodes={"c": NodeInstance(type="colorgrade"), "o": NodeInstance(type="output")},
        edges=[["@live", "c"], ["c", "o"]],
    )
    runtime.load_graph(g)
    state = runtime.get_graph_state()
    assert state["graph"] is not None
    assert "layer_palettes" in state
