"""Pydantic models for the effect node graph system."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


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


class EffectGraph(BaseModel):
    name: str = ""
    description: str = ""
    transition_ms: int = 500
    nodes: dict[str, NodeInstance]
    edges: list[list[str]]
    modulations: list[ModulationBinding] = Field(default_factory=list)

    @property
    def parsed_edges(self) -> list[EdgeDef]:
        return [EdgeDef.from_list(e) for e in self.edges]

    def apply_patch(self, patch: GraphPatch) -> EffectGraph:
        """Apply a GraphPatch and return a new EffectGraph instance.

        Implements the chain-composition primitive that lets affordance-
        recruited node add/remove mutate the live graph without flipping
        between fixed presets. Per the operator's architectural directive
        (memory ``feedback_no_presets_use_parametric_modulation``): the
        director never picks a preset; chain composition emerges from
        per-impingement node add/remove + transition primitives.

        Semantics:
          * Removals run first (so a patch that removes ``X`` and adds
            a fresh ``X`` lands on the new instance, not a no-op).
          * ``remove_nodes`` also drops every edge that touches the
            removed node — leaving dangling edges to a non-existent node
            would fail downstream graph validation.
          * ``remove_edges`` matches on canonical (source_node, source_port,
            target_node, target_port) tuples via ``EdgeDef.from_list``.
            Both ``["a", "b"]`` and ``["a:out", "b:in"]`` resolve to the
            same canonical form, so a remove with one form correctly
            removes an edge added with the other form.
          * ``add_nodes`` overwrites any existing node with the same id
            (idempotent for re-add of an unchanged spec; replaces params
            for a re-add with new ones).
          * ``add_edges`` is deduplicated against the post-removal edge
            set (canonical-form match) so re-applying the same patch is
            a no-op.
          * Modulations are preserved as-is on the returned graph; if a
            removed node had bound modulations, the caller is expected
            to prune them via the affordance-pipeline outcome (modulation
            authority lives outside the patch primitive).

        The original graph is never mutated; a new ``EffectGraph`` is
        returned. This matches Pydantic's value-semantics expectations
        and lets the caller compare ``before`` and ``after`` for
        observability.
        """
        # Step 1: drop removed nodes and any edges touching them.
        removed_node_ids = set(patch.remove_nodes)
        new_nodes = {nid: node for nid, node in self.nodes.items() if nid not in removed_node_ids}
        # Add new nodes (overwriting on collision).
        for nid, node in patch.add_nodes.items():
            new_nodes[nid] = node

        # Step 2: drop edges that touch removed nodes, then drop edges
        # explicitly listed in remove_edges (canonical-form match).
        def _edge_touches_removed(edge: list[str]) -> bool:
            try:
                ed = EdgeDef.from_list(edge)
            except ValueError:
                return False
            src = ed.source_node.lstrip("@")
            return src in removed_node_ids or ed.target_node in removed_node_ids

        def _canonical(edge: list[str]) -> tuple[str, str, str, str] | None:
            try:
                ed = EdgeDef.from_list(edge)
            except ValueError:
                return None
            return (ed.source_node, ed.source_port, ed.target_node, ed.target_port)

        remove_edge_keys: set[tuple[str, str, str, str]] = set()
        for e in patch.remove_edges:
            key = _canonical(e)
            if key is not None:
                remove_edge_keys.add(key)

        new_edges: list[list[str]] = []
        seen_edge_keys: set[tuple[str, str, str, str]] = set()
        for e in self.edges:
            if _edge_touches_removed(e):
                continue
            key = _canonical(e)
            if key is None:
                continue
            if key in remove_edge_keys:
                continue
            if key in seen_edge_keys:
                continue
            seen_edge_keys.add(key)
            new_edges.append(e)

        # Step 3: append new edges (deduped against the post-removal set).
        for e in patch.add_edges:
            key = _canonical(e)
            if key is None:
                continue
            if key in seen_edge_keys:
                continue
            seen_edge_keys.add(key)
            new_edges.append(e)

        return EffectGraph(
            name=self.name,
            description=self.description,
            transition_ms=self.transition_ms,
            nodes=new_nodes,
            edges=new_edges,
            modulations=list(self.modulations),
        )


class GraphPatch(BaseModel):
    add_nodes: dict[str, NodeInstance] = Field(default_factory=dict)
    remove_nodes: list[str] = Field(default_factory=list)
    add_edges: list[list[str]] = Field(default_factory=list)
    remove_edges: list[list[str]] = Field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        """True iff the patch has no add/remove operations."""
        return (
            not self.add_nodes
            and not self.remove_nodes
            and not self.add_edges
            and not self.remove_edges
        )


class PresetFamily(BaseModel, frozen=True):
    """Ranked list of preset names for an atmospheric state cell."""

    presets: tuple[str, ...]

    def first_available(self, loaded_presets: set[str]) -> str | None:
        """Return the first preset in the family that exists in the loaded set."""
        for p in self.presets:
            if p in loaded_presets:
                return p
        return None
