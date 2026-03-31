"""Shader registry — loads node type definitions from manifest files."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from .types import ParamDef, PortType

log = logging.getLogger(__name__)


@dataclass
class LoadedShaderDef:
    node_type: str
    inputs: dict[str, PortType]
    outputs: dict[str, PortType]
    params: dict[str, ParamDef]
    temporal: bool
    temporal_buffers: int
    compute: bool
    glsl_source: str | None


class ShaderRegistry:
    def __init__(self, nodes_dir: Path) -> None:
        self._nodes_dir = nodes_dir
        self._defs: dict[str, LoadedShaderDef] = {}
        if nodes_dir.is_dir():
            for p in sorted(nodes_dir.glob("*.json")):
                try:
                    self._load(p)
                except Exception:
                    log.warning("Failed to load node type from %s", p, exc_info=True)

    def _load(self, path: Path) -> None:
        raw = json.loads(path.read_text())
        nt = raw["node_type"]
        params = {k: ParamDef(**v) for k, v in raw.get("params", {}).items()}
        inputs = {k: PortType(v) for k, v in raw.get("inputs", {}).items()}
        outputs = {k: PortType(v) for k, v in raw.get("outputs", {}).items()}
        glsl = None
        fn = raw.get("glsl_fragment", "")
        if fn and (self._nodes_dir / fn).is_file():
            glsl = (self._nodes_dir / fn).read_text()
        self._defs[nt] = LoadedShaderDef(
            node_type=nt,
            inputs=inputs,
            outputs=outputs,
            params=params,
            temporal=raw.get("temporal", False),
            temporal_buffers=raw.get("temporal_buffers", 0),
            compute=raw.get("compute", False),
            glsl_source=glsl,
        )

    @property
    def node_types(self) -> list[str]:
        return sorted(self._defs)

    def get(self, node_type: str) -> LoadedShaderDef | None:
        return self._defs.get(node_type)

    def schema(self, node_type: str) -> dict[str, object] | None:
        d = self._defs.get(node_type)
        if not d:
            return None
        return {
            "node_type": d.node_type,
            "inputs": {k: v.value for k, v in d.inputs.items()},
            "outputs": {k: v.value for k, v in d.outputs.items()},
            "params": {k: v.model_dump() for k, v in d.params.items()},
            "temporal": d.temporal,
            "temporal_buffers": d.temporal_buffers,
            "compute": d.compute,
        }

    def all_schemas(self) -> dict[str, object]:
        return {k: self.schema(k) for k in self._defs}
