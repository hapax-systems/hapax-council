"""Tests for ShaderRegistry manifest loading and lookup."""

from __future__ import annotations

import json
from pathlib import Path

from agents.effect_graph.registry import LoadedShaderDef, ShaderRegistry
from agents.effect_graph.types import PortType


def _write_manifest(directory: Path, manifest: dict, frag_source: str | None = None) -> None:
    """Helper: write a JSON manifest and optional .frag file into directory."""
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / f"{manifest['node_type']}.json"
    manifest_path.write_text(json.dumps(manifest))
    frag_name = manifest.get("glsl_fragment")
    if frag_name and frag_source is not None:
        (directory / frag_name).write_text(frag_source)


COLORGRADE_MANIFEST = {
    "node_type": "colorgrade",
    "glsl_fragment": "colorgrade.frag",
    "inputs": {"in": "frame"},
    "outputs": {"out": "frame"},
    "params": {
        "saturation": {
            "type": "float",
            "default": 1.0,
            "min": 0.0,
            "max": 2.0,
            "description": "Color saturation",
        }
    },
    "temporal": False,
    "temporal_buffers": 0,
}

COLORGRADE_GLSL = """\
#version 330 core
uniform float saturation;
void main() { gl_FragColor = vec4(1.0); }
"""

OUTPUT_MANIFEST = {
    "node_type": "output",
    "inputs": {"in": "frame"},
    "outputs": {},
    "params": {},
}

TEMPORAL_MANIFEST = {
    "node_type": "trails",
    "glsl_fragment": "trails.frag",
    "inputs": {"in": "frame"},
    "outputs": {"out": "frame"},
    "params": {
        "decay": {
            "type": "float",
            "default": 0.9,
            "min": 0.0,
            "max": 1.0,
            "description": "Trail decay rate",
        }
    },
    "temporal": True,
    "temporal_buffers": 2,
}

TEMPORAL_GLSL = "void main() {}"


class TestShaderRegistryLoading:
    def test_loads_manifest(self, tmp_path: Path) -> None:
        _write_manifest(tmp_path, COLORGRADE_MANIFEST, COLORGRADE_GLSL)
        reg = ShaderRegistry(tmp_path)
        defn = reg.get("colorgrade")
        assert defn is not None
        assert isinstance(defn, LoadedShaderDef)
        assert defn.node_type == "colorgrade"

    def test_glsl_source_populated(self, tmp_path: Path) -> None:
        _write_manifest(tmp_path, COLORGRADE_MANIFEST, COLORGRADE_GLSL)
        reg = ShaderRegistry(tmp_path)
        defn = reg.get("colorgrade")
        assert defn is not None
        assert defn.glsl_source == COLORGRADE_GLSL

    def test_inputs_outputs_parsed(self, tmp_path: Path) -> None:
        _write_manifest(tmp_path, COLORGRADE_MANIFEST, COLORGRADE_GLSL)
        reg = ShaderRegistry(tmp_path)
        defn = reg.get("colorgrade")
        assert defn is not None
        assert defn.inputs == {"in": PortType.FRAME}
        assert defn.outputs == {"out": PortType.FRAME}

    def test_params_parsed(self, tmp_path: Path) -> None:
        _write_manifest(tmp_path, COLORGRADE_MANIFEST, COLORGRADE_GLSL)
        reg = ShaderRegistry(tmp_path)
        defn = reg.get("colorgrade")
        assert defn is not None
        assert "saturation" in defn.params
        assert defn.params["saturation"].default == 1.0
        assert defn.params["saturation"].min == 0.0
        assert defn.params["saturation"].max == 2.0


class TestShaderRegistryLookup:
    def test_unknown_type_returns_none(self, tmp_path: Path) -> None:
        _write_manifest(tmp_path, COLORGRADE_MANIFEST, COLORGRADE_GLSL)
        reg = ShaderRegistry(tmp_path)
        assert reg.get("nonexistent") is None

    def test_node_types_sorted(self, tmp_path: Path) -> None:
        _write_manifest(tmp_path, COLORGRADE_MANIFEST, COLORGRADE_GLSL)
        _write_manifest(tmp_path, OUTPUT_MANIFEST)
        _write_manifest(tmp_path, TEMPORAL_MANIFEST, TEMPORAL_GLSL)
        reg = ShaderRegistry(tmp_path)
        assert reg.node_types == ["colorgrade", "output", "trails"]


class TestShaderRegistrySchema:
    def test_schema_serializable(self, tmp_path: Path) -> None:
        _write_manifest(tmp_path, COLORGRADE_MANIFEST, COLORGRADE_GLSL)
        reg = ShaderRegistry(tmp_path)
        schema = reg.schema("colorgrade")
        assert schema["node_type"] == "colorgrade"
        assert schema["has_glsl"] is True
        # Verify JSON-round-trippable
        roundtripped = json.loads(json.dumps(schema))
        assert roundtripped == schema

    def test_schema_unknown_returns_empty(self, tmp_path: Path) -> None:
        reg = ShaderRegistry(tmp_path)
        assert reg.schema("nope") == {}

    def test_all_schemas(self, tmp_path: Path) -> None:
        _write_manifest(tmp_path, COLORGRADE_MANIFEST, COLORGRADE_GLSL)
        _write_manifest(tmp_path, OUTPUT_MANIFEST)
        reg = ShaderRegistry(tmp_path)
        schemas = reg.all_schemas()
        assert set(schemas.keys()) == {"colorgrade", "output"}


class TestOutputNode:
    def test_no_shader_file_glsl_none(self, tmp_path: Path) -> None:
        _write_manifest(tmp_path, OUTPUT_MANIFEST)
        reg = ShaderRegistry(tmp_path)
        defn = reg.get("output")
        assert defn is not None
        assert defn.glsl_source is None
        assert defn.inputs == {"in": PortType.FRAME}
        assert defn.outputs == {}


class TestTemporalNode:
    def test_temporal_flags(self, tmp_path: Path) -> None:
        _write_manifest(tmp_path, TEMPORAL_MANIFEST, TEMPORAL_GLSL)
        reg = ShaderRegistry(tmp_path)
        defn = reg.get("trails")
        assert defn is not None
        assert defn.temporal is True
        assert defn.temporal_buffers == 2

    def test_temporal_schema_fields(self, tmp_path: Path) -> None:
        _write_manifest(tmp_path, TEMPORAL_MANIFEST, TEMPORAL_GLSL)
        reg = ShaderRegistry(tmp_path)
        schema = reg.schema("trails")
        assert schema["temporal"] is True
        assert schema["temporal_buffers"] == 2
