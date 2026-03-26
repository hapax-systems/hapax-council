"""Tests for shader registry."""

import json
from pathlib import Path

import pytest

from agents.effect_graph.registry import ShaderRegistry


@pytest.fixture
def shader_dir(tmp_path: Path) -> Path:
    nodes_dir = tmp_path / "nodes"
    nodes_dir.mkdir()
    (nodes_dir / "colorgrade.json").write_text(
        json.dumps(
            {
                "node_type": "colorgrade",
                "glsl_fragment": "colorgrade.frag",
                "inputs": {"in": "frame"},
                "outputs": {"out": "frame"},
                "params": {"saturation": {"type": "float", "default": 1.0, "min": 0.0, "max": 2.0}},
                "temporal": False,
            }
        )
    )
    (nodes_dir / "colorgrade.frag").write_text("void main() { gl_FragColor = vec4(1.0); }")
    (nodes_dir / "output.json").write_text(
        json.dumps(
            {
                "node_type": "output",
                "glsl_fragment": "",
                "inputs": {"in": "frame"},
                "outputs": {},
                "params": {},
                "temporal": False,
            }
        )
    )
    (nodes_dir / "trail.json").write_text(
        json.dumps(
            {
                "node_type": "trail",
                "glsl_fragment": "trail.frag",
                "inputs": {"in": "frame"},
                "outputs": {"out": "frame"},
                "params": {"fade": {"type": "float", "default": 0.04}},
                "temporal": True,
                "temporal_buffers": 1,
            }
        )
    )
    (nodes_dir / "trail.frag").write_text("void main() { gl_FragColor = vec4(0.0); }")
    return tmp_path


def test_loads_manifests(shader_dir: Path):
    reg = ShaderRegistry(shader_dir / "nodes")
    assert "colorgrade" in reg.node_types


def test_get_shader_def(shader_dir: Path):
    reg = ShaderRegistry(shader_dir / "nodes")
    sd = reg.get("colorgrade")
    assert sd is not None
    assert sd.glsl_source is not None


def test_unknown_type(shader_dir: Path):
    reg = ShaderRegistry(shader_dir / "nodes")
    assert reg.get("nonexistent") is None


def test_node_types_sorted(shader_dir: Path):
    reg = ShaderRegistry(shader_dir / "nodes")
    types = reg.node_types
    assert types == sorted(types)


def test_schema_export(shader_dir: Path):
    reg = ShaderRegistry(shader_dir / "nodes")
    schema = reg.schema("colorgrade")
    assert schema["node_type"] == "colorgrade"
    assert "params" in schema


def test_output_no_shader(shader_dir: Path):
    reg = ShaderRegistry(shader_dir / "nodes")
    sd = reg.get("output")
    assert sd is not None
    assert sd.glsl_source is None


def test_temporal_node(shader_dir: Path):
    reg = ShaderRegistry(shader_dir / "nodes")
    sd = reg.get("trail")
    assert sd.temporal is True
    assert sd.temporal_buffers == 1


def test_real_nodes():
    """Verify the actual shader nodes directory loads."""
    reg = ShaderRegistry(Path("agents/shaders/nodes"))
    assert len(reg.node_types) >= 9
