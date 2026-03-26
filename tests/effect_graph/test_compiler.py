"""Tests for graph compiler."""

import json
from pathlib import Path

import pytest

from agents.effect_graph.compiler import GraphCompiler, GraphValidationError
from agents.effect_graph.registry import ShaderRegistry
from agents.effect_graph.types import EffectGraph, NodeInstance


@pytest.fixture
def registry(tmp_path: Path) -> ShaderRegistry:
    nodes_dir = tmp_path / "nodes"
    nodes_dir.mkdir()
    for nt, ins, outs, temp in [
        ("colorgrade", {"in": "frame"}, {"out": "frame"}, False),
        ("trail", {"in": "frame"}, {"out": "frame"}, True),
        ("blend", {"a": "frame", "b": "frame"}, {"out": "frame"}, False),
        ("scanlines", {"in": "frame"}, {"out": "frame"}, False),
        ("bloom", {"in": "frame"}, {"out": "frame"}, False),
        ("vignette", {"in": "frame"}, {"out": "frame"}, False),
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


def test_linear_graph(registry):
    compiler = GraphCompiler(registry)
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


def test_branching_graph(registry):
    compiler = GraphCompiler(registry)
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
    assert order.index("a") < order.index("m")
    assert order.index("b") < order.index("m")


def test_reject_cycle(registry):
    compiler = GraphCompiler(registry)
    g = EffectGraph(
        name="t",
        nodes={
            "a": NodeInstance(type="colorgrade"),
            "b": NodeInstance(type="colorgrade"),
            "o": NodeInstance(type="output"),
        },
        edges=[["@live", "a"], ["a", "b"], ["b", "a"], ["b", "o"]],
    )
    with pytest.raises(GraphValidationError, match="[Cc]ycle"):
        compiler.compile(g)


def test_reject_no_output(registry):
    compiler = GraphCompiler(registry)
    g = EffectGraph(name="t", nodes={"c": NodeInstance(type="colorgrade")}, edges=[["@live", "c"]])
    with pytest.raises(GraphValidationError, match="[Oo]utput"):
        compiler.compile(g)


def test_reject_unknown_type(registry):
    compiler = GraphCompiler(registry)
    g = EffectGraph(
        name="t",
        nodes={"x": NodeInstance(type="nope"), "o": NodeInstance(type="output")},
        edges=[["@live", "x"], ["x", "o"]],
    )
    with pytest.raises(GraphValidationError, match="[Uu]nknown"):
        compiler.compile(g)


def test_reject_disconnected(registry):
    compiler = GraphCompiler(registry)
    g = EffectGraph(
        name="t",
        nodes={
            "c": NodeInstance(type="colorgrade"),
            "orphan": NodeInstance(type="scanlines"),
            "o": NodeInstance(type="output"),
        },
        edges=[["@live", "c"], ["c", "o"]],
    )
    with pytest.raises(GraphValidationError, match="[Dd]isconnect"):
        compiler.compile(g)


def test_reject_bad_layer(registry):
    compiler = GraphCompiler(registry)
    g = EffectGraph(
        name="t",
        nodes={"o": NodeInstance(type="output")},
        edges=[["@invalid", "o"]],
    )
    with pytest.raises(GraphValidationError, match="[Ll]ayer|[Ss]ource"):
        compiler.compile(g)


def test_temporal_flagged(registry):
    compiler = GraphCompiler(registry)
    g = EffectGraph(
        name="t",
        nodes={"t": NodeInstance(type="trail"), "o": NodeInstance(type="output")},
        edges=[["@live", "t"], ["t", "o"]],
    )
    plan = compiler.compile(g)
    trail_step = next(s for s in plan.steps if s.node_id == "t")
    assert trail_step.temporal is True


def test_fanout_fbo(registry):
    compiler = GraphCompiler(registry)
    g = EffectGraph(
        name="t",
        nodes={
            "c": NodeInstance(type="colorgrade"),
            "s": NodeInstance(type="scanlines"),
            "b": NodeInstance(type="bloom"),
            "m": NodeInstance(type="blend"),
            "o": NodeInstance(type="output"),
        },
        edges=[
            ["@live", "c"],
            ["c", "s"],
            ["c", "b"],
            ["s", "m:a"],
            ["b", "m:b"],
            ["m", "o"],
        ],
    )
    plan = compiler.compile(g)
    c_step = next(s for s in plan.steps if s.node_id == "c")
    assert c_step.needs_dedicated_fbo is True
