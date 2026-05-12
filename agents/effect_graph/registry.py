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
    node_type: str
    inputs: dict[str, PortType]
    outputs: dict[str, PortType]
    params: dict[str, ParamDef]
    temporal: bool
    compute: bool
    glsl_source: str | None
    requires_content_slots: bool = False
    backend: str = "wgsl_render"
    # Slot-family routing tag (yt-content-reverie-sierpinski-separation
    # design 2026-04-21). When ``requires_content_slots`` is True, the
    # Rust runtime binds content_slot_0..3 to sources whose SHM-path
    # prefix matches this family. Default ``"narrative"`` keeps the
    # generative substrate's contract — Reverie's content_layer pulls
    # narrative sources only and never sees raw YouTube frames.
    # ``"youtube_pip"`` routes YT-slot sources to a foreground ward
    # (Sierpinski) for prominent display. Empty/missing-family passes
    # bind a 1×1 transparent placeholder rather than cross-bleed.
    slot_family: str = "narrative"
    # Optional machine-readable safety contract for nodes that bind
    # content_slot_* textures. This is intentionally carried through the
    # registry instead of hard-coding node names in policy code: content
    # slots are a live compositing substrate, and eligibility needs to be
    # based on declared runtime behavior.
    content_slot_policy: dict[str, Any] | None = None


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
            compute=raw.get("compute", False),
            glsl_source=glsl,
            requires_content_slots=raw.get("requires_content_slots", False),
            backend=raw.get("backend", "wgsl_render"),
            slot_family=raw.get("slot_family", "narrative"),
            content_slot_policy=raw.get("content_slot_policy"),
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
            "compute": d.compute,
            "requires_content_slots": d.requires_content_slots,
            "backend": d.backend,
            "slot_family": d.slot_family,
            "content_slot_policy": d.content_slot_policy,
        }

    def all_schemas(self) -> dict[str, object]:
        return {k: self.schema(k) for k in self._defs}
