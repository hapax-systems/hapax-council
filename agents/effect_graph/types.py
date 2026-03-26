"""Pydantic models for the effect node graph system."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class PortType(StrEnum):
    FRAME = "frame"
    SCALAR = "scalar"
    COLOR = "color"


class ParamDef(BaseModel):
    type: str
    default: Any
    min: float | None = None
    max: float | None = None
    enum_values: list[str] | None = None
    description: str = ""


class ShaderDef(BaseModel):
    node_type: str
    glsl_fragment: str
    inputs: dict[str, PortType]
    outputs: dict[str, PortType]
    params: dict[str, ParamDef]
    temporal: bool = False
    temporal_buffers: int = 0
    compute: bool = False


class NodeInstance(BaseModel):
    type: str
    params: dict[str, Any] = Field(default_factory=dict)


class EdgeDef(BaseModel):
    source_node: str
    source_port: str = "out"
    target_node: str
    target_port: str = "in"

    @property
    def is_layer_source(self) -> bool:
        return self.source_node.startswith("@")

    @classmethod
    def from_list(cls, edge: list[str]) -> EdgeDef:
        if len(edge) != 2:
            msg = f"Edge must be [source, target], got {edge}"
            raise ValueError(msg)
        src_raw, tgt_raw = edge
        if ":" in src_raw and not src_raw.startswith("@"):
            src_node, src_port = src_raw.split(":", 1)
        else:
            src_node, src_port = src_raw, "out"
        if ":" in tgt_raw:
            tgt_node, tgt_port = tgt_raw.split(":", 1)
        else:
            tgt_node, tgt_port = tgt_raw, "in"
        return cls(
            source_node=src_node, source_port=src_port, target_node=tgt_node, target_port=tgt_port
        )


class ModulationBinding(BaseModel):
    node: str
    param: str
    source: str
    scale: float = 1.0
    offset: float = 0.0
    smoothing: float = Field(default=0.85, ge=0.0, le=1.0)


class LayerPalette(BaseModel):
    saturation: float = Field(default=1.0, ge=0.0, le=2.0)
    brightness: float = Field(default=1.0, ge=0.0, le=2.0)
    contrast: float = Field(default=1.0, ge=0.0, le=2.0)
    sepia: float = Field(default=0.0, ge=0.0, le=1.0)
    hue_rotate: float = Field(default=0.0, ge=-180.0, le=180.0)


class EffectGraph(BaseModel):
    name: str = ""
    description: str = ""
    transition_ms: int = 500
    nodes: dict[str, NodeInstance]
    edges: list[list[str]]
    modulations: list[ModulationBinding] = Field(default_factory=list)
    layer_palettes: dict[str, LayerPalette] = Field(default_factory=dict)

    @property
    def parsed_edges(self) -> list[EdgeDef]:
        return [EdgeDef.from_list(e) for e in self.edges]


class GraphPatch(BaseModel):
    add_nodes: dict[str, NodeInstance] = Field(default_factory=dict)
    remove_nodes: list[str] = Field(default_factory=list)
    add_edges: list[list[str]] = Field(default_factory=list)
    remove_edges: list[list[str]] = Field(default_factory=list)


class PresetFamily(BaseModel, frozen=True):
    """Ranked list of preset names for an atmospheric state cell."""

    presets: tuple[str, ...]

    def first_available(self, loaded_presets: set[str]) -> str | None:
        """Return the first preset in the family that exists in the loaded set."""
        for p in self.presets:
            if p in loaded_presets:
                return p
        return None
