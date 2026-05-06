"""Graph runtime — manages the live effect graph and its mutations."""

from __future__ import annotations

import copy
import logging
from collections.abc import Callable

from .compiler import ExecutionPlan, GraphCompiler
from .modulator import UniformModulator
from .registry import ShaderRegistry
from .types import EffectGraph, GraphPatch

log = logging.getLogger(__name__)


class GraphRuntime:
    def __init__(
        self, registry: ShaderRegistry, compiler: GraphCompiler, modulator: UniformModulator
    ) -> None:
        self._registry = registry
        self._compiler = compiler
        self._modulator = modulator
        self._current_graph: EffectGraph | None = None
        self._current_plan: ExecutionPlan | None = None
        self._on_plan_changed: Callable[[ExecutionPlan | None, ExecutionPlan], None] | None = None
        self._on_params_changed: Callable[[str, dict[str, object]], None] | None = None

    @property
    def current_graph(self) -> EffectGraph | None:
        return self._current_graph

    @property
    def current_plan(self) -> ExecutionPlan | None:
        return self._current_plan

    @property
    def modulator(self) -> UniformModulator:
        return self._modulator

    def load_graph(self, graph: EffectGraph) -> None:
        old = self._current_plan
        plan = self._compiler.compile(graph)
        self._current_graph = copy.deepcopy(graph)
        self._current_plan = plan
        self._modulator.replace_all(list(graph.modulations))
        # NOTE: Reverie (hapax-imagination) pipeline is NOT driven by compositor
        # presets. Reverie content is recruited exclusively by the DMN escalation
        # process. Compositor presets only affect the GStreamer camera FX chain.
        if self._on_plan_changed:
            self._on_plan_changed(old, plan)
        log.info("Loaded graph '%s' (%d nodes)", graph.name, len(graph.nodes))

    def patch_node_params(self, node_id: str, params: dict[str, object]) -> None:
        if not self._current_graph:
            return
        node = self._current_graph.nodes.get(node_id)
        if not node:
            return
        node.params.update(params)
        if self._on_params_changed:
            self._on_params_changed(node_id, node.params)

    def apply_patch(self, patch: GraphPatch) -> None:
        if not self._current_graph:
            return
        g = copy.deepcopy(self._current_graph).apply_patch(patch)
        old = self._current_plan
        plan = self._compiler.compile(g)
        self._current_graph = g
        self._current_plan = plan
        if self._on_plan_changed:
            self._on_plan_changed(old, plan)

    def remove_node(self, node_id: str) -> None:
        if not self._current_graph:
            return

        def _edge_touches(edge: list[str], nid: str) -> bool:
            for endpoint in edge:
                name = endpoint.split(":", 1)[0] if ":" in endpoint else endpoint
                if name == nid:
                    return True
            return False

        self.apply_patch(
            GraphPatch(
                remove_nodes=[node_id],
                remove_edges=[e for e in self._current_graph.edges if _edge_touches(e, node_id)],
            )
        )

    def get_graph_state(self) -> dict[str, object]:
        if not self._current_graph:
            return {"graph": None, "modulations": []}
        return {
            "graph": self._current_graph.model_dump(),
            "modulations": [b.model_dump() for b in self._modulator.bindings],
        }
