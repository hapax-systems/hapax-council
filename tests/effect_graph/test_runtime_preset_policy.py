from __future__ import annotations

import pytest

from agents.effect_graph.compiler import GraphCompiler
from agents.effect_graph.modulator import UniformModulator
from agents.effect_graph.registry import ShaderRegistry
from agents.effect_graph.runtime import GraphRuntime
from agents.effect_graph.types import EffectGraph, NodeInstance
from agents.studio_compositor.preset_policy import PresetPolicyError

from .test_smoke import NODES_DIR


def _runtime() -> GraphRuntime:
    registry = ShaderRegistry(NODES_DIR)
    return GraphRuntime(
        registry=registry,
        compiler=GraphCompiler(registry),
        modulator=UniformModulator(),
    )


def _graph(name: str) -> EffectGraph:
    return EffectGraph(
        name=name,
        nodes={
            "c": NodeInstance(type="colorgrade"),
            "o": NodeInstance(type="output"),
        },
        edges=[["@live", "c"], ["c", "o"]],
    )


def test_graph_runtime_blocks_denylisted_graph_name(monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_COMPOSITOR_PRESET_DENYLIST", "chrome_mirror_brushed")
    runtime = _runtime()

    with pytest.raises(PresetPolicyError):
        runtime.load_graph(_graph("Chrome Mirror Brushed"))

    assert runtime.current_graph is None


def test_graph_runtime_honors_camera_legible_allowlist(monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_CAMERA_LEGIBLE_FX_ONLY", "1")
    monkeypatch.setenv("HAPAX_CAMERA_LEGIBLE_PRESET_ALLOWLIST", "clean")
    runtime = _runtime()

    runtime.load_graph(_graph("Clean"))

    assert runtime.current_graph is not None
    assert runtime.current_graph.name == "Clean"


def test_graph_runtime_blocks_camera_legible_graph_body_violation(monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_CAMERA_LEGIBLE_FX_ONLY", "1")
    monkeypatch.setenv("HAPAX_CAMERA_LEGIBLE_PRESET_ALLOWLIST", "clean")
    runtime = _runtime()
    graph = EffectGraph(
        name="Clean",
        nodes={
            "post": NodeInstance(type="postprocess", params={"anonymize": 1.0}),
            "o": NodeInstance(type="output"),
        },
        edges=[["@live", "post"], ["post", "o"]],
    )

    with pytest.raises(PresetPolicyError) as exc:
        runtime.load_graph(graph)

    assert exc.value.decision.reason == "camera_legible_anonymize"
    assert runtime.current_graph is None
