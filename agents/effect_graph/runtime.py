"""Graph runtime — manages the live effect graph and its mutations."""

from __future__ import annotations

import copy
import logging
from typing import Any

from .compiler import ExecutionPlan, GraphCompiler
from .modulator import UniformModulator
from .registry import ShaderRegistry
from .types import EffectGraph, GraphPatch, LayerPalette

log = logging.getLogger(__name__)


class GraphRuntime:
    """Manages the live effect graph. Three mutation levels."""

    def __init__(
        self,
        registry: ShaderRegistry,
        compiler: GraphCompiler,
        modulator: UniformModulator,
    ) -> None:
        self._registry = registry
        self._compiler = compiler
        self._modulator = modulator
        self._current_graph: EffectGraph | None = None
        self._current_plan: ExecutionPlan | None = None
        self._layer_palettes: dict[str, LayerPalette] = {
            "live": LayerPalette(),
            "smooth": LayerPalette(),
            "hls": LayerPalette(),
        }
        self._on_plan_changed: Any = None
        self._on_params_changed: Any = None

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
        """Full graph replace (Level 3 mutation)."""
        old_plan = self._current_plan
        plan = self._compiler.compile(graph)
        self._current_graph = copy.deepcopy(graph)
        self._current_plan = plan
        self._modulator.replace_all(list(graph.modulations))
        for layer_name, palette in graph.layer_palettes.items():
            if layer_name in self._layer_palettes:
                self._layer_palettes[layer_name] = palette
        if self._on_plan_changed:
            self._on_plan_changed(old_plan, plan)
        log.info("Loaded graph '%s' with %d nodes", graph.name, len(graph.nodes))

    def patch_node_params(self, node_id: str, params: dict[str, Any]) -> None:
        """Parameter patch (Level 1 mutation)."""
        if self._current_graph is None:
            return
        node = self._current_graph.nodes.get(node_id)
        if node is None:
            return
        node.params.update(params)
        if self._on_params_changed:
            self._on_params_changed(node_id, node.params)

    def apply_patch(self, patch: GraphPatch) -> None:
        """Topology mutation (Level 2 mutation)."""
        if self._current_graph is None:
            return
        graph = copy.deepcopy(self._current_graph)
        for node_id in patch.remove_nodes:
            graph.nodes.pop(node_id, None)
        for node_id, node in patch.add_nodes.items():
            graph.nodes[node_id] = node
        for edge in patch.remove_edges:
            if edge in graph.edges:
                graph.edges.remove(edge)
        for edge in patch.add_edges:
            graph.edges.append(edge)
        old_plan = self._current_plan
        plan = self._compiler.compile(graph)
        self._current_graph = graph
        self._current_plan = plan
        if self._on_plan_changed:
            self._on_plan_changed(old_plan, plan)

    def remove_node(self, node_id: str) -> None:
        if self._current_graph is None:
            return
        edges_to_remove = [e for e in self._current_graph.edges if node_id in e]
        self.apply_patch(GraphPatch(remove_nodes=[node_id], remove_edges=edges_to_remove))

    def set_layer_palette(self, layer: str, palette: LayerPalette) -> None:
        if layer in self._layer_palettes:
            self._layer_palettes[layer] = palette

    def get_layer_palette(self, layer: str) -> LayerPalette:
        return self._layer_palettes.get(layer, LayerPalette())

    def get_graph_state(self) -> dict[str, Any]:
        if self._current_graph is None:
            return {"graph": None, "layer_palettes": {}, "modulations": []}
        return {
            "graph": self._current_graph.model_dump(),
            "layer_palettes": {k: v.model_dump() for k, v in self._layer_palettes.items()},
            "modulations": [b.model_dump() for b in self._modulator.bindings],
        }
