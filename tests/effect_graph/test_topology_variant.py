"""Tests for effect graph topology variant generation and source routing."""

from __future__ import annotations

from pathlib import Path

from agents.effect_graph.compiler import GraphCompiler
from agents.effect_graph.registry import ShaderRegistry
from agents.effect_graph.topology_variant import (
    PRIVATE_ONLY_SOURCES,
    VALID_SOURCES,
    SourceRoute,
    TopologyVariantGenerator,
)
from agents.effect_graph.types import EffectGraph, NodeInstance

NODES_DIR = Path(__file__).parent.parent.parent / "agents" / "shaders" / "nodes"


def _minimal_graph() -> EffectGraph:
    return EffectGraph(
        name="test_preset",
        nodes={
            "colorgrade": NodeInstance(type="colorgrade", params={"brightness": 0.8}),
            "bloom": NodeInstance(type="bloom", params={"intensity": 0.5}),
            "drift": NodeInstance(type="drift", params={"speed": 0.3}),
            "out": NodeInstance(type="output"),
        },
        edges=[
            ["@live", "colorgrade"],
            ["colorgrade", "bloom"],
            ["bloom", "drift"],
            ["drift", "out"],
        ],
    )


def _make_generator() -> TopologyVariantGenerator:
    registry = ShaderRegistry(NODES_DIR)
    compiler = GraphCompiler(registry)
    return TopologyVariantGenerator(registry, compiler)


class TestVariantGeneration:
    def test_generates_variant_from_preset(self):
        gen = _make_generator()
        result = gen.generate_variant(_minimal_graph(), seed=42)
        assert result.ok
        assert result.variant is not None
        assert result.variant.base_preset == "test_preset"
        assert result.variant.variant_id
        assert result.variant.generation_seed == 42

    def test_variant_has_active_nodes(self):
        gen = _make_generator()
        result = gen.generate_variant(_minimal_graph(), seed=42)
        assert len(result.variant.active_nodes) >= 3

    def test_deterministic_with_same_seed(self):
        gen = _make_generator()
        r1 = gen.generate_variant(_minimal_graph(), seed=123)
        r2 = gen.generate_variant(_minimal_graph(), seed=123)
        assert r1.variant.active_nodes == r2.variant.active_nodes
        assert r1.variant.variant_id == r2.variant.variant_id

    def test_different_seeds_can_differ(self):
        gen = _make_generator()
        results = set()
        for seed in range(20):
            r = gen.generate_variant(_minimal_graph(), seed=seed)
            tuple(sorted(r.variant.graph.nodes.keys()))
            types = tuple(r.variant.graph.nodes[n].type for n in sorted(r.variant.graph.nodes))
            results.add(types)
        assert len(results) > 1

    def test_compile_failure_falls_back(self):
        registry = ShaderRegistry(NODES_DIR)
        compiler = GraphCompiler(registry)
        bad_pool = {"colorgrade": ["nonexistent_shader_xyz"]}
        gen = TopologyVariantGenerator(registry, compiler, substitution_pool=bad_pool)
        result = gen.generate_variant(_minimal_graph(), seed=1)
        assert result.ok


class TestSourceRouting:
    def test_valid_source_routes_accepted(self):
        gen = _make_generator()
        routes = [
            SourceRoute(source_id="@live", posture="public", provenance="camera:brio-operator"),
            SourceRoute(source_id="@reverie", posture="public", provenance="imagination:main"),
        ]
        result = gen.generate_variant(_minimal_graph(), source_routes=routes, seed=42)
        assert result.ok
        assert len(result.variant.source_routes) == 2

    def test_unknown_source_rejected(self):
        gen = _make_generator()
        routes = [SourceRoute(source_id="@invalid", posture="public", provenance="test")]
        result = gen.generate_variant(_minimal_graph(), source_routes=routes, seed=42)
        assert not result.ok
        assert "unknown source" in result.error

    def test_missing_provenance_rejected(self):
        gen = _make_generator()
        routes = [SourceRoute(source_id="@live", posture="public", provenance="")]
        result = gen.generate_variant(_minimal_graph(), source_routes=routes, seed=42)
        assert not result.ok
        assert "provenance" in result.error

    def test_private_source_blocked_from_public(self):
        gen = _make_generator()
        graph = EffectGraph(
            name="test",
            nodes={"n": NodeInstance(type="colorgrade")},
            edges=[["@pool", "n"]],
        )
        routes = [SourceRoute(source_id="@pool", posture="public", provenance="pool:local")]
        result = gen.generate_variant(graph, source_routes=routes, seed=42)
        assert result.ok
        pool_edges = [e for e in result.variant.graph.edges if e[0] == "@pool"]
        assert len(pool_edges) == 0

    def test_valid_sources_constant(self):
        assert "@live" in VALID_SOURCES
        assert "@reverie" in VALID_SOURCES
        assert "@pool" in VALID_SOURCES
        assert "@homage" in VALID_SOURCES

    def test_private_only_sources_constant(self):
        assert "@pool" in PRIVATE_ONLY_SOURCES
        assert "@archive" in PRIVATE_ONLY_SOURCES
        assert "@live" not in PRIVATE_ONLY_SOURCES


class TestLedgerPublication:
    def test_variant_records_metadata(self):
        gen = _make_generator()
        routes = [
            SourceRoute(source_id="@live", posture="public", provenance="camera:brio"),
        ]
        result = gen.generate_variant(_minimal_graph(), source_routes=routes, seed=99)
        v = result.variant
        assert v.generated_at
        assert v.generation_seed == 99
        assert v.base_preset == "test_preset"
        assert len(v.active_nodes) >= 3
        assert len(v.source_routes) == 1
        assert v.source_routes[0].provenance == "camera:brio"
