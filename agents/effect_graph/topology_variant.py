"""Topology variant generation for effect graph presets.

Turns presets from fixed node chains into grammar seeds that can generate
structural variants — node substitutions, edge rerouting, and multi-source
graph inputs — while preserving compile safety and provenance.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel

from .compiler import GraphCompiler, GraphValidationError
from .registry import ShaderRegistry
from .types import EdgeDef, EffectGraph, NodeInstance

log = logging.getLogger(__name__)

type SourcePosture = Literal["public", "private", "public_archive", "unknown"]

VALID_SOURCES = frozenset({"@live", "@smooth", "@hls", "@reverie", "@pool", "@homage", "@archive"})
PRIVATE_ONLY_SOURCES = frozenset({"@pool", "@archive"})


class SourceRoute(BaseModel):
    source_id: str
    posture: SourcePosture
    provenance: str

    def is_public_safe(self) -> bool:
        return self.posture in ("public", "public_archive")


class TopologyVariant(BaseModel):
    base_preset: str
    variant_id: str
    graph: EffectGraph
    active_nodes: list[str]
    source_routes: list[SourceRoute]
    generated_at: str
    generation_seed: int


class VariantGenerationResult(BaseModel):
    ok: bool
    variant: TopologyVariant | None = None
    error: str | None = None
    fallback_to_base: bool = False


class TopologyVariantGenerator:
    """Generates structural variants of effect graph presets."""

    def __init__(
        self,
        registry: ShaderRegistry,
        compiler: GraphCompiler,
        substitution_pool: dict[str, list[str]] | None = None,
    ) -> None:
        self._registry = registry
        self._compiler = compiler
        self._substitution_pool = substitution_pool or _default_substitution_pool()

    def generate_variant(
        self,
        base_graph: EffectGraph,
        *,
        source_routes: list[SourceRoute] | None = None,
        seed: int | None = None,
    ) -> VariantGenerationResult:
        rng = random.Random(seed)
        variant_seed = seed if seed is not None else rng.randint(0, 2**32 - 1)

        for route in source_routes or []:
            if route.source_id not in VALID_SOURCES:
                return VariantGenerationResult(
                    ok=False,
                    error=f"unknown source: {route.source_id}",
                )
            if not route.provenance:
                return VariantGenerationResult(
                    ok=False,
                    error=f"source {route.source_id} has no provenance",
                )

        candidate = self._apply_substitutions(base_graph, rng)
        if source_routes:
            candidate = self._route_sources(candidate, source_routes)

        try:
            self._compiler.compile(candidate)
        except GraphValidationError as exc:
            log.warning(
                "variant compile failed for %s, falling back to base: %s",
                base_graph.name,
                exc,
            )
            fallback = base_graph
            if source_routes:
                fallback = self._route_sources(base_graph, source_routes)
            return VariantGenerationResult(
                ok=True,
                variant=self._build_variant(
                    base_graph, fallback, source_routes or [], variant_seed
                ),
                fallback_to_base=True,
            )

        return VariantGenerationResult(
            ok=True,
            variant=self._build_variant(base_graph, candidate, source_routes or [], variant_seed),
        )

    def _apply_substitutions(self, graph: EffectGraph, rng: random.Random) -> EffectGraph:
        new_nodes = dict(graph.nodes)
        for node_id, node in graph.nodes.items():
            candidates = self._substitution_pool.get(node.type, [])
            if not candidates:
                continue
            if rng.random() < 0.3:
                replacement_type = rng.choice(candidates)
                if self._registry.get(replacement_type) is not None:
                    new_nodes[node_id] = NodeInstance(
                        type=replacement_type, params=dict(node.params)
                    )

        return EffectGraph(
            name=graph.name,
            description=graph.description,
            transition_ms=graph.transition_ms,
            nodes=new_nodes,
            edges=list(graph.edges),
            modulations=list(graph.modulations),
        )

    def _route_sources(self, graph: EffectGraph, routes: list[SourceRoute]) -> EffectGraph:
        source_map = {r.source_id: r for r in routes}
        new_edges: list[list[str]] = []
        for edge in graph.edges:
            parsed = EdgeDef.from_list(edge)
            if parsed.is_layer_source and parsed.source_node in source_map:
                route = source_map[parsed.source_node]
                if route.source_id in PRIVATE_ONLY_SOURCES and route.posture == "public":
                    continue
                new_edges.append(edge)
            else:
                new_edges.append(edge)

        return EffectGraph(
            name=graph.name,
            description=graph.description,
            transition_ms=graph.transition_ms,
            nodes=dict(graph.nodes),
            edges=new_edges,
            modulations=list(graph.modulations),
        )

    def _build_variant(
        self,
        base: EffectGraph,
        candidate: EffectGraph,
        routes: list[SourceRoute],
        seed: int,
    ) -> TopologyVariant:
        variant_data = json.dumps(
            {"base": base.name, "nodes": sorted(candidate.nodes.keys()), "seed": seed},
            sort_keys=True,
        )
        variant_id = hashlib.sha256(variant_data.encode()).hexdigest()[:12]

        return TopologyVariant(
            base_preset=base.name,
            variant_id=variant_id,
            graph=candidate,
            active_nodes=sorted(candidate.nodes.keys()),
            source_routes=routes,
            generated_at=datetime.now(UTC).isoformat(),
            generation_seed=seed,
        )


def _default_substitution_pool() -> dict[str, list[str]]:
    return {
        "colorgrade": ["palette", "palette_remap", "color_map"],
        "bloom": ["glow", "sharpen"],
        "drift": ["warp", "fluid_sim"],
        "vhs": ["scanlines", "glitch_block", "noise_overlay"],
        "edge_detect": ["emboss", "halftone"],
        "trail": ["echo", "stutter"],
        "dither": ["threshold", "ascii"],
    }
