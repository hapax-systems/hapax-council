"""Tests for kuwahara shader node manifest (HOMAGE Ward Umbrella Phase 2)."""

from __future__ import annotations

import json
from pathlib import Path

from agents.effect_graph.registry import ShaderRegistry

NODES_DIR = Path(__file__).resolve().parents[2] / "agents" / "shaders" / "nodes"


def test_kuwahara_manifest_loads():
    """kuwahara.json loads cleanly via ShaderRegistry."""
    registry = ShaderRegistry(NODES_DIR)
    defs = registry.defs() if hasattr(registry, "defs") else registry._defs  # type: ignore[attr-defined]
    assert "kuwahara" in defs


def test_kuwahara_manifest_shape():
    """kuwahara manifest has the expected shape matching convention."""
    raw = json.loads((NODES_DIR / "kuwahara.json").read_text())
    assert raw["node_type"] == "kuwahara"
    assert raw["backend"] == "wgsl_render"
    assert raw["glsl_fragment"] == "kuwahara.frag"
    assert raw["inputs"] == {"in": "frame"}
    assert raw["outputs"] == {"out": "frame"}
    assert "radius" in raw["params"]
    assert raw["params"]["radius"]["default"] == 3.0
    assert raw["params"]["radius"]["min"] == 1.0
    assert raw["params"]["radius"]["max"] == 8.0
    assert raw["temporal"] is False


def test_kuwahara_frag_exists_and_is_glsl_100():
    """kuwahara.frag exists and uses the project's GLSL 1.00 ES convention."""
    src = (NODES_DIR / "kuwahara.frag").read_text()
    assert "#version 100" in src
    assert "uniform sampler2D tex;" in src
    assert "uniform float u_radius;" in src
    assert "gl_FragColor" in src
