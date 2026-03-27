"""Graph runtime — manages the live effect graph and its mutations."""

from __future__ import annotations

import copy
import logging
from typing import Any

from .compiler import GraphCompiler
from .modulator import UniformModulator
from .registry import ShaderRegistry
from .types import EffectGraph, GraphPatch, LayerPalette

log = logging.getLogger(__name__)


class GraphRuntime:
    def __init__(
        self, registry: ShaderRegistry, compiler: GraphCompiler, modulator: UniformModulator
    ) -> None:
        self._registry = registry
        self._compiler = compiler
        self._modulator = modulator
        self._current_graph: EffectGraph | None = None
        self._current_plan: Any = None
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
    def current_plan(self) -> Any:
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
        for k, v in graph.layer_palettes.items():
            if k in self._layer_palettes:
                self._layer_palettes[k] = v
        if self._on_plan_changed:
            self._on_plan_changed(old, plan)
        log.info("Loaded graph '%s' (%d nodes)", graph.name, len(graph.nodes))

    def patch_node_params(self, node_id: str, params: dict[str, Any]) -> None:
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
        g = copy.deepcopy(self._current_graph)
        for nid in patch.remove_nodes:
            g.nodes.pop(nid, None)
        for nid, n in patch.add_nodes.items():
            g.nodes[nid] = n
        for e in patch.remove_edges:
            if e in g.edges:
                g.edges.remove(e)
        g.edges.extend(patch.add_edges)
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

    def set_layer_palette(self, layer: str, palette: LayerPalette) -> None:
        if layer in self._layer_palettes:
            self._layer_palettes[layer] = palette

    def get_layer_palette(self, layer: str) -> LayerPalette:
        return self._layer_palettes.get(layer, LayerPalette())

    def get_graph_state(self) -> dict[str, Any]:
        if not self._current_graph:
            return {"graph": None, "layer_palettes": {}, "modulations": []}
        return {
            "graph": self._current_graph.model_dump(),
            "layer_palettes": {k: v.model_dump() for k, v in self._layer_palettes.items()},
            "modulations": [b.model_dump() for b in self._modulator.bindings],
        }
