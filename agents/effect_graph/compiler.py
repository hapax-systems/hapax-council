"""Graph compiler — validates and compiles effect graphs into execution plans."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from .registry import ShaderRegistry
from .types import EdgeDef, EffectGraph

log = logging.getLogger(__name__)
VALID_LAYER_SOURCES = {"@live", "@smooth", "@hls"}


class GraphValidationError(Exception):
    pass


@dataclass
class ExecutionStep:
    node_id: str
    node_type: str
    params: dict[str, Any]
    shader_source: str | None
    input_edges: list[EdgeDef]
    output_edges: list[EdgeDef]
    temporal: bool = False
    temporal_buffers: int = 0
    needs_dedicated_fbo: bool = False


@dataclass
class ExecutionPlan:
    name: str
    steps: list[ExecutionStep]
    layer_sources: set[str] = field(default_factory=set)
    transition_ms: int = 500


class GraphCompiler:
    def __init__(self, registry: ShaderRegistry) -> None:
        self._registry = registry

    def compile(self, graph: EffectGraph) -> ExecutionPlan:
        edges = graph.parsed_edges
        self._validate(graph, edges)
        order = self._topo_sort(graph, edges)
        steps = self._build(graph, edges, order)
        return ExecutionPlan(
            name=graph.name,
            steps=steps,
            layer_sources={e.source_node for e in edges if e.is_layer_source},
            transition_ms=graph.transition_ms,
        )

    def _validate(self, graph: EffectGraph, edges: list[EdgeDef]) -> None:
        if not any(n.type == "output" for n in graph.nodes.values()):
            raise GraphValidationError("Graph must have exactly one output node")
        for nid, n in graph.nodes.items():
            if n.type != "output" and not self._registry.get(n.type):
                raise GraphValidationError(f"Unknown node type '{n.type}' for node '{nid}'")
        for e in edges:
            if e.source_node.startswith("@") and e.source_node not in VALID_LAYER_SOURCES:
                raise GraphValidationError(f"Invalid layer source '{e.source_node}'")
        connected = set()
        for e in edges:
            if not e.is_layer_source:
                connected.add(e.source_node)
            connected.add(e.target_node)
        for nid in graph.nodes:
            if nid not in connected:
                raise GraphValidationError(f"Disconnected node '{nid}'")

    def _topo_sort(self, graph: EffectGraph, edges: list[EdgeDef]) -> list[str]:
        succs: dict[str, list[str]] = defaultdict(list)
        in_deg: dict[str, int] = {nid: 0 for nid in graph.nodes}
        for e in edges:
            if not e.is_layer_source and e.source_node in graph.nodes:
                succs[e.source_node].append(e.target_node)
                in_deg[e.target_node] = in_deg.get(e.target_node, 0) + 1
        queue = [n for n in graph.nodes if in_deg[n] == 0]
        order: list[str] = []
        while queue:
            n = queue.pop(0)
            order.append(n)
            for s in succs.get(n, []):
                in_deg[s] -= 1
                if in_deg[s] == 0:
                    queue.append(s)
        if len(order) != len(graph.nodes):
            raise GraphValidationError(f"Cycle detected: {set(graph.nodes) - set(order)}")
        return order

    def _build(
        self, graph: EffectGraph, edges: list[EdgeDef], order: list[str]
    ) -> list[ExecutionStep]:
        out_count: dict[str, int] = defaultdict(int)
        for e in edges:
            if not e.is_layer_source:
                out_count[e.source_node] += 1
        steps = []
        for nid in order:
            n = graph.nodes[nid]
            d = self._registry.get(n.type)
            steps.append(
                ExecutionStep(
                    node_id=nid,
                    node_type=n.type,
                    params=dict(n.params),
                    shader_source=d.glsl_source if d else None,
                    input_edges=[e for e in edges if e.target_node == nid],
                    output_edges=[e for e in edges if e.source_node == nid],
                    temporal=d.temporal if d else False,
                    temporal_buffers=d.temporal_buffers if d else 0,
                    needs_dedicated_fbo=out_count.get(nid, 0) > 1,
                )
            )
        return steps
