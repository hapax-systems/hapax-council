"""Shader registry — scans manifest JSON files and loads GLSL sources."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents.effect_graph.types import ParamDef, PortType

logger = logging.getLogger(__name__)


@dataclass
class LoadedShaderDef:
    """A shader definition with its GLSL source loaded from disk."""

    node_type: str
    inputs: dict[str, PortType]
    outputs: dict[str, PortType]
    params: dict[str, ParamDef]
    temporal: bool = False
    temporal_buffers: int = 0
    compute: bool = False
    glsl_source: str | None = None


class ShaderRegistry:
    """Scans a directory for shader manifests and provides typed lookup."""

    def __init__(self, shader_dir: Path) -> None:
        self._defs: dict[str, LoadedShaderDef] = {}
        self._load_all(shader_dir)

    def _load_all(self, shader_dir: Path) -> None:
        for manifest_path in sorted(shader_dir.glob("*.json")):
            try:
                raw = json.loads(manifest_path.read_text())
                node_type: str = raw["node_type"]

                inputs = {k: PortType(v) for k, v in raw.get("inputs", {}).items()}
                outputs = {k: PortType(v) for k, v in raw.get("outputs", {}).items()}
                params = {k: ParamDef.model_validate(v) for k, v in raw.get("params", {}).items()}

                glsl_source: str | None = None
                frag_name = raw.get("glsl_fragment")
                if frag_name:
                    frag_path = shader_dir / frag_name
                    if frag_path.is_file():
                        glsl_source = frag_path.read_text()

                self._defs[node_type] = LoadedShaderDef(
                    node_type=node_type,
                    inputs=inputs,
                    outputs=outputs,
                    params=params,
                    temporal=raw.get("temporal", False),
                    temporal_buffers=raw.get("temporal_buffers", 0),
                    compute=raw.get("compute", False),
                    glsl_source=glsl_source,
                )
            except Exception:
                logger.exception("Failed to load shader manifest %s", manifest_path)

    @property
    def node_types(self) -> list[str]:
        """Sorted list of registered node type names."""
        return sorted(self._defs)

    def get(self, node_type: str) -> LoadedShaderDef | None:
        """Look up a loaded shader def by node type, or None if unknown."""
        return self._defs.get(node_type)

    def schema(self, node_type: str) -> dict[str, Any]:
        """Export a JSON-serializable schema dict for a single node type."""
        defn = self._defs.get(node_type)
        if defn is None:
            return {}
        return self._def_to_schema(defn)

    def all_schemas(self) -> dict[str, dict[str, Any]]:
        """Export schemas for every registered node type."""
        return {nt: self._def_to_schema(d) for nt, d in sorted(self._defs.items())}

    @staticmethod
    def _def_to_schema(defn: LoadedShaderDef) -> dict[str, Any]:
        return {
            "node_type": defn.node_type,
            "inputs": {k: v.value for k, v in defn.inputs.items()},
            "outputs": {k: v.value for k, v in defn.outputs.items()},
            "params": {k: v.model_dump() for k, v in defn.params.items()},
            "temporal": defn.temporal,
            "temporal_buffers": defn.temporal_buffers,
            "compute": defn.compute,
            "has_glsl": defn.glsl_source is not None,
        }
