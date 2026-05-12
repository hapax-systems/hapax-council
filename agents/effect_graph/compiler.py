"""Graph compiler — validates and compiles effect graphs into execution plans."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field

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
    params: dict[str, object]
    shader_source: str | None
    input_edges: list[EdgeDef]
    output_edges: list[EdgeDef]
    temporal: bool = False


@dataclass
class ExecutionPlan:
    """Compiled execution plan with one entry per render target.

    Phase 5a (Compositor Unification Epic): a graph may declare
    multiple ``type=output`` nodes, each tagged with a target name via
    ``params.target``. The compiler walks back from each output node
    and produces a topo-sorted ExecutionStep list per target. The
    ``targets`` dict is the canonical storage; the ``steps`` property
    is the backwards-compat union for legacy callers.

    Existing single-output graphs default to a single target named
    ``"main"``, so no preset migration is needed.
    """

    name: str
    targets: dict[str, list[ExecutionStep]] = field(default_factory=dict)
    layer_sources: set[str] = field(default_factory=set)
    transition_ms: int = 500

    @property
    def steps(self) -> list[ExecutionStep]:
        """Backwards-compat: union of all targets' steps in stable order.

        Concatenated by target name (sorted) so callers that pre-date
        Phase 5a get a deterministic flat list. The single-target case
        (one output node, target ``"main"``) is identical to the
        pre-5a behavior — every existing test and runtime call site
        keeps working unchanged.
        """
        out: list[ExecutionStep] = []
        for target_name in sorted(self.targets):
            out.extend(self.targets[target_name])
        return out

    @property
    def target_names(self) -> tuple[str, ...]:
        """Sorted tuple of target names in this plan."""
        return tuple(sorted(self.targets))


class GraphCompiler:
    def __init__(self, registry: ShaderRegistry) -> None:
        self._registry = registry

    def compile(self, graph: EffectGraph) -> ExecutionPlan:
        edges = graph.parsed_edges
        self._validate(graph, edges)
        # Phase 5a: each output node becomes a target. The target name
        # comes from the output node's params.target (default "main").
        outputs = [
            (nid, str(n.params.get("target", "main")))
            for nid, n in graph.nodes.items()
            if n.type == "output"
        ]
        target_names = [t for _, t in outputs]
        if len(target_names) != len(set(target_names)):
            raise GraphValidationError(
                f"Graph {graph.name!r}: duplicate target names {sorted(target_names)}"
            )
        targets: dict[str, list[ExecutionStep]] = {}
        for output_id, target_name in outputs:
            reachable = self._reachable_subgraph(graph, edges, output_id)
            order = self._topo_sort(graph, edges, restrict_to=reachable)
            steps = self._build(graph, edges, order)
            targets[target_name] = steps
        return ExecutionPlan(
            name=graph.name,
            targets=targets,
            layer_sources={e.source_node for e in edges if e.is_layer_source},
            transition_ms=graph.transition_ms,
        )

    def _validate(self, graph: EffectGraph, edges: list[EdgeDef]) -> None:
        output_count = sum(1 for n in graph.nodes.values() if n.type == "output")
        if output_count < 1:
            raise GraphValidationError(
                f"Graph must have at least one output node, got {output_count}"
            )
        for nid, n in graph.nodes.items():
            if n.type != "output" and not self._registry.get(n.type):
                raise GraphValidationError(f"Unknown node type '{n.type}' for node '{nid}'")
        for e in edges:
            if e.source_node.startswith("@") and e.source_node not in VALID_LAYER_SOURCES:
                raise GraphValidationError(f"Invalid layer source '{e.source_node}'")
            # Validate port existence on non-layer edges
            if not e.is_layer_source:
                src_node = graph.nodes.get(e.source_node)
                if src_node and src_node.type != "output":
                    src_def = self._registry.get(src_node.type)
                    if src_def and e.source_port not in src_def.outputs:
                        raise GraphValidationError(
                            f"Node '{e.source_node}' ({src_node.type}) has no output port "
                            f"'{e.source_port}', available: {list(src_def.outputs)}"
                        )
            tgt_node = graph.nodes.get(e.target_node)
            if tgt_node and tgt_node.type != "output":
                tgt_def = self._registry.get(tgt_node.type)
                if tgt_def and e.target_port not in tgt_def.inputs:
                    raise GraphValidationError(
                        f"Node '{e.target_node}' ({tgt_node.type}) has no input port "
                        f"'{e.target_port}', available: {list(tgt_def.inputs)}"
                    )
        connected = set()
        for e in edges:
            if not e.is_layer_source:
                connected.add(e.source_node)
            connected.add(e.target_node)
        for nid in graph.nodes:
            if nid not in connected:
                raise GraphValidationError(f"Disconnected node '{nid}'")

    def _topo_sort(
        self,
        graph: EffectGraph,
        edges: list[EdgeDef],
        restrict_to: set[str] | None = None,
    ) -> list[str]:
        """Kahn topological sort.

        When ``restrict_to`` is supplied (Phase 5a per-target compile),
        only nodes in the subset are considered. Edges to/from nodes
        outside the subset are ignored — this lets each output node
        produce an independent topological order even if other targets
        share predecessors.
        """
        node_set = set(graph.nodes) if restrict_to is None else (set(graph.nodes) & restrict_to)
        succs: dict[str, list[str]] = defaultdict(list)
        in_deg: dict[str, int] = dict.fromkeys(node_set, 0)
        for e in edges:
            if e.is_layer_source:
                continue
            if e.source_node not in node_set or e.target_node not in node_set:
                continue
            succs[e.source_node].append(e.target_node)
            in_deg[e.target_node] = in_deg.get(e.target_node, 0) + 1
        queue = [n for n in node_set if in_deg[n] == 0]
        order: list[str] = []
        while queue:
            n = queue.pop(0)
            order.append(n)
            for s in succs.get(n, []):
                in_deg[s] -= 1
                if in_deg[s] == 0:
                    queue.append(s)
        if len(order) != len(node_set):
            raise GraphValidationError(f"Cycle detected: {node_set - set(order)}")
        return order

    def _reachable_subgraph(
        self,
        graph: EffectGraph,
        edges: list[EdgeDef],
        target_node: str,
    ) -> set[str]:
        """Return the set of nodes whose output ``target_node`` depends on.

        BFS backwards along incoming edges starting from ``target_node``.
        Layer-source edges (``@live``, ``@smooth``, etc.) are not part
        of the node graph and don't expand the reachable set.

        Used by Phase 5a per-target compile: each output node's
        reachable set defines the steps that contribute to that
        target.
        """
        preds: dict[str, list[str]] = defaultdict(list)
        for e in edges:
            if e.is_layer_source:
                continue
            if e.source_node not in graph.nodes:
                continue
            preds[e.target_node].append(e.source_node)
        seen: set[str] = {target_node}
        queue: list[str] = [target_node]
        while queue:
            current = queue.pop(0)
            for predecessor in preds.get(current, ()):
                if predecessor in seen:
                    continue
                seen.add(predecessor)
                queue.append(predecessor)
        return seen

    def _build(
        self, graph: EffectGraph, edges: list[EdgeDef], order: list[str]
    ) -> list[ExecutionStep]:
        steps = []
        for nid in order:
            n = graph.nodes[nid]
            d = self._registry.get(n.type)
            # Merge registry defaults with instance overrides so unset params
            # get their declared defaults (e.g. zoom=1.0) instead of GLSL 0.0
            merged_params: dict[str, object] = {}
            if d:
                for pname, pdef in d.params.items():
                    merged_params[pname] = pdef.default
            merged_params.update(n.params)
            if d:
                try:
                    from agents.studio_compositor.preset_policy import (
                        apply_live_surface_param_bounds,
                    )

                    merged_params = apply_live_surface_param_bounds(n.type, merged_params)
                except ImportError:
                    log.debug(
                        "live-surface param policy unavailable for %s",
                        n.type,
                        exc_info=True,
                    )
            steps.append(
                ExecutionStep(
                    node_id=nid,
                    node_type=n.type,
                    params=merged_params,
                    shader_source=d.glsl_source if d else None,
                    input_edges=[e for e in edges if e.target_node == nid],
                    output_edges=[e for e in edges if e.source_node == nid],
                    temporal=d.temporal if d else False,
                )
            )
        return steps
