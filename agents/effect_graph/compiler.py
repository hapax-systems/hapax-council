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
    """Raised when a graph fails validation."""


@dataclass
class ExecutionStep:
    """One node in the compiled execution plan."""

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
    """Compiled graph ready for GStreamer element chain construction."""

    name: str
    steps: list[ExecutionStep]
    layer_sources: set[str] = field(default_factory=set)
    transition_ms: int = 500


class GraphCompiler:
    """Validates and compiles EffectGraph into ExecutionPlan."""

    def __init__(self, registry: ShaderRegistry) -> None:
        self._registry = registry

    def compile(self, graph: EffectGraph) -> ExecutionPlan:
        edges = graph.parsed_edges
        self._validate(graph, edges)
        order = self._topological_sort(graph, edges)
        steps = self._build_steps(graph, edges, order)
        layer_sources = {e.source_node for e in edges if e.is_layer_source}
        return ExecutionPlan(
            name=graph.name,
            steps=steps,
            layer_sources=layer_sources,
            transition_ms=graph.transition_ms,
        )

    def _validate(self, graph: EffectGraph, edges: list[EdgeDef]) -> None:
        has_output = any(n.type == "output" for n in graph.nodes.values())
        if not has_output:
            raise GraphValidationError("Graph must have exactly one output node")

        for node_id, node in graph.nodes.items():
            if node.type == "output":
                continue
            defn = self._registry.get(node.type)
            if defn is None:
                raise GraphValidationError(f"Unknown node type '{node.type}' for node '{node_id}'")

        for edge in edges:
            if edge.source_node.startswith("@") and edge.source_node not in VALID_LAYER_SOURCES:
                raise GraphValidationError(
                    f"Invalid layer source '{edge.source_node}'. "
                    f"Valid sources: {VALID_LAYER_SOURCES}"
                )

        connected = set()
        for edge in edges:
            if not edge.is_layer_source:
                connected.add(edge.source_node)
            connected.add(edge.target_node)
        for node_id in graph.nodes:
            if node_id not in connected:
                raise GraphValidationError(
                    f"Disconnected node '{node_id}' — not connected to any edge"
                )

    def _topological_sort(self, graph: EffectGraph, edges: list[EdgeDef]) -> list[str]:
        successors: dict[str, list[str]] = defaultdict(list)
        for edge in edges:
            if not edge.is_layer_source and edge.source_node in graph.nodes:
                successors[edge.source_node].append(edge.target_node)

        queue = []
        for nid in graph.nodes:
            non_layer_inputs = sum(
                1
                for e in edges
                if e.target_node == nid and not e.is_layer_source and e.source_node in graph.nodes
            )
            if non_layer_inputs == 0:
                queue.append(nid)

        in_degree: dict[str, int] = {}
        for nid in graph.nodes:
            in_degree[nid] = sum(
                1
                for e in edges
                if e.target_node == nid and not e.is_layer_source and e.source_node in graph.nodes
            )

        order: list[str] = []
        while queue:
            node = queue.pop(0)
            order.append(node)
            for succ in successors.get(node, []):
                in_degree[succ] -= 1
                if in_degree[succ] == 0:
                    queue.append(succ)

        if len(order) != len(graph.nodes):
            raise GraphValidationError(
                f"Cycle detected in graph — nodes not in topological order: "
                f"{set(graph.nodes) - set(order)}"
            )
        return order

    def _build_steps(
        self, graph: EffectGraph, edges: list[EdgeDef], order: list[str]
    ) -> list[ExecutionStep]:
        out_count: dict[str, int] = defaultdict(int)
        for edge in edges:
            if not edge.is_layer_source:
                out_count[edge.source_node] += 1

        steps: list[ExecutionStep] = []
        for node_id in order:
            node = graph.nodes[node_id]
            defn = self._registry.get(node.type)
            input_edges = [e for e in edges if e.target_node == node_id]
            output_edges = [e for e in edges if e.source_node == node_id]
            steps.append(
                ExecutionStep(
                    node_id=node_id,
                    node_type=node.type,
                    params=dict(node.params),
                    shader_source=defn.glsl_source if defn else None,
                    input_edges=input_edges,
                    output_edges=output_edges,
                    temporal=defn.temporal if defn else False,
                    temporal_buffers=defn.temporal_buffers if defn else 0,
                    needs_dedicated_fbo=out_count.get(node_id, 0) > 1,
                )
            )
        return steps
