"""Tests for shared.sheaf_graph.

56-LOC SCM reading-dependency graph (14 nodes, 24 edges). Untested
before this commit. Tests pin the topology so any change to
SCM_NODES or SCM_EDGES is a deliberate, test-flipping decision.
"""

from __future__ import annotations

import networkx as nx

from shared.sheaf_graph import SCM_EDGES, SCM_NODES, build_scm_graph

# ── Topology pinning ──────────────────────────────────────────────


class TestNodes:
    def test_node_count_pinned(self) -> None:
        """The 14-node SCM is documented in the module docstring; pin
        the count so additions are deliberate."""
        assert len(SCM_NODES) == 14

    def test_canonical_nodes_present(self) -> None:
        """Pin every documented node name."""
        expected = {
            "ir_perception",
            "contact_mic",
            "voice_daemon",
            "dmn",
            "imagination",
            "stimmung",
            "temporal_bonds",
            "apperception",
            "reactive_engine",
            "compositor",
            "reverie",
            "voice_pipeline",
            "content_resolver",
            "consent_engine",
        }
        assert set(SCM_NODES) == expected

    def test_no_duplicate_nodes(self) -> None:
        assert len(SCM_NODES) == len(set(SCM_NODES))


class TestEdges:
    def test_edge_count_pinned(self) -> None:
        assert len(SCM_EDGES) == 24

    def test_no_duplicate_edges(self) -> None:
        assert len(SCM_EDGES) == len(set(SCM_EDGES))

    def test_all_edge_endpoints_in_node_set(self) -> None:
        """Every edge endpoint must be a declared node — catches typos
        + drift between SCM_NODES and SCM_EDGES."""
        nodes = set(SCM_NODES)
        for src, dst in SCM_EDGES:
            assert src in nodes, f"edge source {src!r} missing from SCM_NODES"
            assert dst in nodes, f"edge dest {dst!r} missing from SCM_NODES"

    def test_dmn_imagination_bidirectional(self) -> None:
        """dmn ↔ imagination bidirectional pin (both edges canonical)."""
        edges = set(SCM_EDGES)
        assert ("dmn", "imagination") in edges
        assert ("imagination", "dmn") in edges

    def test_dmn_outgoing_pin(self) -> None:
        """DMN broadcasts to stimmung, voice_daemon, consent_engine,
        reverie, imagination."""
        outgoing = {dst for src, dst in SCM_EDGES if src == "dmn"}
        assert outgoing == {
            "stimmung",
            "voice_daemon",
            "consent_engine",
            "reverie",
            "imagination",
        }


# ── build_scm_graph ────────────────────────────────────────────────


class TestBuildScmGraph:
    def test_returns_directed_graph(self) -> None:
        G = build_scm_graph()
        assert isinstance(G, nx.DiGraph)

    def test_node_set_matches(self) -> None:
        G = build_scm_graph()
        assert set(G.nodes) == set(SCM_NODES)

    def test_edge_set_matches(self) -> None:
        G = build_scm_graph()
        assert set(G.edges) == set(SCM_EDGES)

    def test_graph_is_directed(self) -> None:
        """A graph with bidirectional dmn/imagination edges must
        retain direction (so the two edges aren't merged)."""
        G = build_scm_graph()
        assert G.has_edge("dmn", "imagination")
        assert G.has_edge("imagination", "dmn")

    def test_returns_fresh_graph_each_call(self) -> None:
        """Mutating one returned graph must not affect a subsequent call."""
        G1 = build_scm_graph()
        G1.add_node("rogue")
        G2 = build_scm_graph()
        assert "rogue" not in G2.nodes
