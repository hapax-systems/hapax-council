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
