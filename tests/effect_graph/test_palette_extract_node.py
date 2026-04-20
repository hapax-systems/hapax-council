"""Tests for palette_extract shader node manifest (HOMAGE Ward Umbrella Phase 2)."""

from __future__ import annotations

import json
from pathlib import Path

from agents.effect_graph.registry import ShaderRegistry

NODES_DIR = Path(__file__).resolve().parents[2] / "agents" / "shaders" / "nodes"


def test_palette_extract_manifest_loads():
    """palette_extract.json loads cleanly via ShaderRegistry."""
    registry = ShaderRegistry(NODES_DIR)
    assert "palette_extract" in registry._defs  # type: ignore[attr-defined]


def test_palette_extract_manifest_shape():
    """palette_extract manifest declares expected fields + defaults."""
    raw = json.loads((NODES_DIR / "palette_extract.json").read_text())
    assert raw["node_type"] == "palette_extract"
    assert raw["backend"] == "wgsl_render"
    assert raw["glsl_fragment"] == "palette_extract.frag"
    assert raw["inputs"] == {"in": "frame"}
    assert raw["outputs"] == {"out": "frame"}
    p = raw["params"]
    assert p["swatch_count"]["default"] == 8.0
    assert p["swatch_count"]["min"] >= 3.0
    assert p["swatch_count"]["max"] <= 16.0
    assert p["strip_height"]["default"] == 0.08
    assert p["strip_opacity"]["default"] == 0.95
    assert raw["temporal"] is False


def test_palette_extract_frag_format():
    """palette_extract.frag follows the project's GLSL 1.00 ES convention."""
    src = (NODES_DIR / "palette_extract.frag").read_text()
    assert "#version 100" in src
    assert "uniform sampler2D tex;" in src
    for u in ("u_swatch_count", "u_strip_height", "u_strip_opacity", "u_width", "u_height"):
        assert f"uniform float {u};" in src
    assert "gl_FragColor" in src
