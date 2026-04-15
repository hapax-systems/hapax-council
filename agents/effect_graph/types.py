"""Pydantic models for the effect node graph system."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PortType(StrEnum):
    FRAME = "frame"
    SCALAR = "scalar"
    COLOR = "color"


class ParamDef(BaseModel):
    type: str
    default: object
    min: float | None = None
    max: float | None = None
    enum_values: list[str] | None = None
    description: str = ""


class NodeInstance(BaseModel):
    type: str
    params: dict[str, object] = Field(default_factory=dict)


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
    # Asymmetric envelope: fast attack for transients, slow decay for smooth falloff.
    # When set, these override `smoothing`. Leave both at None to use `smoothing`.
    attack: float | None = Field(default=None, ge=0.0, le=1.0)
    decay: float | None = Field(default=None, ge=0.0, le=1.0)


class PresetInput(BaseModel):
    """Preset-level binding from a SourceRegistry source pad to a layer slot.

    Phase 7 of the source-registry completion epic (parent task I26).
    ``pad`` references a ``SourceRegistry`` ``source_id``. ``as_`` is the
    internal layer name the shader chain references. The preset loader
    resolves ``pad`` against the live ``SourceRegistry`` at load-time and
    raises :class:`~agents.effect_graph.compiler.PresetLoadError` on any
    unknown pad — no silent fallthrough.

    ``as`` is a Python keyword; the field is stored as ``as_`` and
    addressed via the ``"as"`` alias in incoming JSON so presets can
    write the natural key.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    pad: str = Field(..., min_length=1)
    as_: str = Field(..., min_length=1, alias="as")

    @field_validator("pad")
    @classmethod
    def _nonempty_pad(cls, v: str) -> str:
        if not v.strip():
            msg = "pad must be non-empty"
            raise ValueError(msg)
        return v

    @field_validator("as_")
    @classmethod
    def _nonempty_layer(cls, v: str) -> str:
        if not v.strip():
            msg = "as must be non-empty"
            raise ValueError(msg)
        return v


class EffectGraph(BaseModel):
    name: str = ""
    description: str = ""
    transition_ms: int = 500
    nodes: dict[str, NodeInstance]
    edges: list[list[str]]
    modulations: list[ModulationBinding] = Field(default_factory=list)
    # Phase 7 of the source-registry completion epic (parent task I26):
    # optional per-preset source pad bindings. When present, the preset
    # loader resolves each ``pad`` against the live ``SourceRegistry``
    # and maps its backend handle to the declared ``as`` layer slot.
    # Presets that leave ``inputs`` unset preserve current behavior
    # (no main-layer bindings).
    inputs: list[PresetInput] | None = None

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
