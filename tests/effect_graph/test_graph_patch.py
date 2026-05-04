"""Tests for ``EffectGraph.apply_patch`` — chain-composition primitive.

Architectural fix per researcher audit + memory
``feedback_no_presets_use_parametric_modulation``: the GraphPatch type at
``agents/effect_graph/types.py`` had zero callers. ``apply_patch`` is the
new method that lets the graph_patch_consumer mutate the live chain
surgically (add/remove a single shader node) instead of swapping among
30 fixed preset graphs.

These tests exercise the patch primitive in isolation: pure data
transforms, no SHM, no threading, no compiler.
"""

from __future__ import annotations

from agents.effect_graph.types import EffectGraph, GraphPatch, NodeInstance


def _base_graph() -> EffectGraph:
    """A 3-node + output base graph used as the patch target."""
    return EffectGraph(
        name="base",
        nodes={
            "c": NodeInstance(type="colorgrade", params={"saturation": 0.5}),
            "b": NodeInstance(type="bloom"),
            "o": NodeInstance(type="output"),
        },
        edges=[["@live", "c"], ["c", "b"], ["b", "o"]],
    )


# ── add_nodes ──────────────────────────────────────────────────────────────


def test_apply_patch_adds_a_node() -> None:
    g = _base_graph()
    p = GraphPatch(add_nodes={"h": NodeInstance(type="halftone")})
    g2 = g.apply_patch(p)
    assert "h" in g2.nodes
    assert g2.nodes["h"].type == "halftone"
    # Original graph unchanged.
    assert "h" not in g.nodes


def test_apply_patch_adds_multiple_nodes() -> None:
    g = _base_graph()
    p = GraphPatch(
        add_nodes={
            "h": NodeInstance(type="halftone"),
            "k": NodeInstance(type="kaleidoscope"),
        }
    )
    g2 = g.apply_patch(p)
    assert "h" in g2.nodes
    assert "k" in g2.nodes
    assert g2.nodes["h"].type == "halftone"
    assert g2.nodes["k"].type == "kaleidoscope"


def test_apply_patch_add_node_overwrites_on_collision() -> None:
    """Re-adding an existing node id replaces the spec — a clean way to
    swap params without a separate update method."""
    g = _base_graph()
    p = GraphPatch(add_nodes={"c": NodeInstance(type="colorgrade", params={"saturation": 1.0})})
    g2 = g.apply_patch(p)
    assert g2.nodes["c"].params["saturation"] == 1.0
    # Original unchanged.
    assert g.nodes["c"].params["saturation"] == 0.5


# ── remove_nodes ────────────────────────────────────────────────────────────


def test_apply_patch_removes_a_node() -> None:
    g = _base_graph()
    p = GraphPatch(remove_nodes=["b"])
    g2 = g.apply_patch(p)
    assert "b" not in g2.nodes
    assert "c" in g2.nodes
    # Original unchanged.
    assert "b" in g.nodes


def test_apply_patch_removes_drop_touching_edges() -> None:
    """Removing a node also drops edges that reference it — leaving
    dangling edges would fail downstream graph validation."""
    g = _base_graph()
    p = GraphPatch(remove_nodes=["b"])
    g2 = g.apply_patch(p)
    # Edges that mention `b` are gone.
    for edge in g2.edges:
        assert "b" not in edge


def test_apply_patch_remove_unknown_node_is_noop() -> None:
    g = _base_graph()
    p = GraphPatch(remove_nodes=["nonexistent"])
    g2 = g.apply_patch(p)
    # Graph stays the same.
    assert sorted(g2.nodes.keys()) == sorted(g.nodes.keys())


# ── add_edges ──────────────────────────────────────────────────────────────


def test_apply_patch_adds_edges() -> None:
    g = _base_graph()
    p = GraphPatch(
        add_nodes={"h": NodeInstance(type="halftone")},
        add_edges=[["c", "h"], ["h", "b"]],
    )
    g2 = g.apply_patch(p)
    # All four edges present (3 originals minus none removed + 2 new).
    edge_pairs = [(e[0], e[1]) for e in g2.edges]
    assert ("c", "h") in edge_pairs
    assert ("h", "b") in edge_pairs


def test_apply_patch_add_edge_dedup_by_canonical_form() -> None:
    """Adding an edge that already exists in canonical form is a no-op,
    even when the explicit port string differs."""
    g = _base_graph()
    # Re-add ``["c", "b"]`` via the canonical port form.
    p = GraphPatch(add_edges=[["c:out", "b:in"]])
    g2 = g.apply_patch(p)
    # No duplicate "c->b" entry — still 3 edges.
    assert len(g2.edges) == 3


# ── remove_edges ────────────────────────────────────────────────────────────


def test_apply_patch_removes_edge() -> None:
    g = _base_graph()
    p = GraphPatch(remove_edges=[["c", "b"]])
    g2 = g.apply_patch(p)
    edge_pairs = [(e[0], e[1]) for e in g2.edges]
    assert ("c", "b") not in edge_pairs


def test_apply_patch_remove_edge_canonical_form_match() -> None:
    """Remove via ``["c:out", "b:in"]`` matches the same edge added as
    ``["c", "b"]`` because both resolve to the same canonical
    (source_node, source_port, target_node, target_port) tuple."""
    g = _base_graph()
    p = GraphPatch(remove_edges=[["c:out", "b:in"]])
    g2 = g.apply_patch(p)
    edge_pairs = [(e[0], e[1]) for e in g2.edges]
    assert ("c", "b") not in edge_pairs


# ── combined patches ────────────────────────────────────────────────────────


def test_apply_patch_replace_node_via_remove_then_add() -> None:
    """Remove then add a fresh node with the same id — the new instance
    lands, not a no-op."""
    g = _base_graph()
    p = GraphPatch(
        remove_nodes=["c"],
        add_nodes={"c": NodeInstance(type="colorgrade", params={"saturation": 2.0})},
    )
    g2 = g.apply_patch(p)
    assert g2.nodes["c"].params["saturation"] == 2.0


def test_apply_patch_combined_chain_composition() -> None:
    """The realistic recruitment shape: insert a satellite node mid-chain
    by removing one edge and adding three (in via new node, out via new
    node). Same primitive used by the graph_patch_consumer."""
    g = _base_graph()
    p = GraphPatch(
        add_nodes={"h": NodeInstance(type="halftone")},
        remove_edges=[["c", "b"]],
        add_edges=[["c", "h"], ["h", "b"]],
    )
    g2 = g.apply_patch(p)
    edge_pairs = [(e[0], e[1]) for e in g2.edges]
    assert ("c", "b") not in edge_pairs
    assert ("c", "h") in edge_pairs
    assert ("h", "b") in edge_pairs
    assert "h" in g2.nodes


# ── idempotency + immutability ─────────────────────────────────────────────


def test_apply_patch_empty_patch_is_noop() -> None:
    g = _base_graph()
    p = GraphPatch()
    assert p.is_empty
    g2 = g.apply_patch(p)
    assert g2.nodes == g.nodes
    assert g2.edges == g.edges
    # Different instance, same content.
    assert g2 is not g


def test_apply_patch_idempotent() -> None:
    """Applying the same patch twice produces the same graph as applying
    it once — re-application of an already-applied add is a no-op."""
    g = _base_graph()
    p = GraphPatch(
        add_nodes={"h": NodeInstance(type="halftone")},
        add_edges=[["c", "h"]],
    )
    g_once = g.apply_patch(p)
    g_twice = g_once.apply_patch(p)
    # Both runs produce the same node + edge set.
    assert sorted(g_once.nodes.keys()) == sorted(g_twice.nodes.keys())
    once_edges = sorted([tuple(e) for e in g_once.edges])
    twice_edges = sorted([tuple(e) for e in g_twice.edges])
    assert once_edges == twice_edges


def test_apply_patch_does_not_mutate_original() -> None:
    """Pydantic-style value semantics: apply_patch always returns a new
    instance, never mutates the receiver."""
    g = _base_graph()
    pre_nodes = dict(g.nodes)
    pre_edges = list(g.edges)
    pre_modulations = list(g.modulations)
    p = GraphPatch(
        add_nodes={"h": NodeInstance(type="halftone")},
        remove_nodes=["b"],
        add_edges=[["c", "h"]],
        remove_edges=[["c", "b"]],
    )
    g.apply_patch(p)
    # Original is byte-identical to what it was before.
    assert g.nodes == pre_nodes
    assert g.edges == pre_edges
    assert g.modulations == pre_modulations


def test_apply_patch_preserves_modulations() -> None:
    """Modulations are not touched by the patch primitive — modulation
    authority lives outside the patch (visual chain owns it)."""
    from agents.effect_graph.types import ModulationBinding

    g = EffectGraph(
        name="base",
        nodes={
            "c": NodeInstance(type="colorgrade"),
            "o": NodeInstance(type="output"),
        },
        edges=[["@live", "c"], ["c", "o"]],
        modulations=[ModulationBinding(node="c", param="saturation", source="intensity")],
    )
    p = GraphPatch(add_nodes={"h": NodeInstance(type="halftone")})
    g2 = g.apply_patch(p)
    assert len(g2.modulations) == 1
    assert g2.modulations[0].node == "c"
    assert g2.modulations[0].param == "saturation"


def test_apply_patch_preserves_metadata() -> None:
    """Patch keeps name, description, transition_ms — they are graph
    identity, not mutation candidates."""
    g = EffectGraph(
        name="my-graph",
        description="test description",
        transition_ms=750,
        nodes={"o": NodeInstance(type="output")},
        edges=[["@live", "o"]],
    )
    p = GraphPatch(add_nodes={"h": NodeInstance(type="halftone")})
    g2 = g.apply_patch(p)
    assert g2.name == "my-graph"
    assert g2.description == "test description"
    assert g2.transition_ms == 750


# ── GraphPatch.is_empty ─────────────────────────────────────────────────────


def test_graph_patch_is_empty_default() -> None:
    assert GraphPatch().is_empty


def test_graph_patch_is_empty_false_when_add_nodes() -> None:
    p = GraphPatch(add_nodes={"h": NodeInstance(type="halftone")})
    assert not p.is_empty


def test_graph_patch_is_empty_false_when_remove_nodes() -> None:
    p = GraphPatch(remove_nodes=["x"])
    assert not p.is_empty


def test_graph_patch_is_empty_false_when_add_edges() -> None:
    p = GraphPatch(add_edges=[["a", "b"]])
    assert not p.is_empty


def test_graph_patch_is_empty_false_when_remove_edges() -> None:
    p = GraphPatch(remove_edges=[["a", "b"]])
    assert not p.is_empty
