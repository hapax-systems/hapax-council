"""Shader registry — loads node type definitions from manifest files."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .types import ParamDef, PortType

log = logging.getLogger(__name__)


@dataclass
class LoadedShaderDef:
    """ShaderDef with loaded GLSL source code."""

    node_type: str
    inputs: dict[str, PortType]
    outputs: dict[str, PortType]
    params: dict[str, ParamDef]
    temporal: bool
    temporal_buffers: int
    compute: bool
    glsl_source: str | None


class ShaderRegistry:
    """Scans a directory of .json manifests and .frag shaders."""

    def __init__(self, nodes_dir: Path) -> None:
        self._nodes_dir = nodes_dir
        self._defs: dict[str, LoadedShaderDef] = {}
        self._load_all()

    def _load_all(self) -> None:
        if not self._nodes_dir.is_dir():
            log.warning("Shader nodes directory does not exist: %s", self._nodes_dir)
            return
        for manifest_path in sorted(self._nodes_dir.glob("*.json")):
            try:
                self._load_manifest(manifest_path)
            except Exception:
                log.exception("Failed to load shader manifest: %s", manifest_path)

    def _load_manifest(self, path: Path) -> None:
        raw = json.loads(path.read_text())
        node_type = raw["node_type"]
        params: dict[str, ParamDef] = {}
        for name, pdef in raw.get("params", {}).items():
            params[name] = ParamDef(**pdef)
        inputs = {k: PortType(v) for k, v in raw.get("inputs", {}).items()}
        outputs = {k: PortType(v) for k, v in raw.get("outputs", {}).items()}

        glsl_source: str | None = None
        frag_name = raw.get("glsl_fragment", "")
        if frag_name:
            frag_path = self._nodes_dir / frag_name
            if frag_path.is_file():
                glsl_source = frag_path.read_text()
            else:
                log.warning("Shader file not found: %s", frag_path)

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

    @property
    def node_types(self) -> list[str]:
        return sorted(self._defs.keys())

    def get(self, node_type: str) -> LoadedShaderDef | None:
        return self._defs.get(node_type)

    def schema(self, node_type: str) -> dict[str, Any] | None:
        defn = self._defs.get(node_type)
        if defn is None:
            return None
        return {
            "node_type": defn.node_type,
            "inputs": {k: v.value for k, v in defn.inputs.items()},
            "outputs": {k: v.value for k, v in defn.outputs.items()},
            "params": {name: pdef.model_dump() for name, pdef in defn.params.items()},
            "temporal": defn.temporal,
            "temporal_buffers": defn.temporal_buffers,
            "compute": defn.compute,
        }

    def all_schemas(self) -> dict[str, Any]:
        return {node_type: self.schema(node_type) for node_type in self._defs}
