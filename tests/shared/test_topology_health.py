"""Tests for shared.topology_health.

38-LOC topological health diagnostics for graphs (Betti numbers +
node-removal stability). Untested before this commit.
"""

from __future__ import annotations

import networkx as nx

from shared.topology_health import compute_betti_numbers, compute_topological_stability

# ── compute_betti_numbers ──────────────────────────────────────────


class TestBettiNumbers:
    def test_empty_graph(self) -> None:
        G = nx.DiGraph()
        assert compute_betti_numbers(G) == (0, 0)

    def test_single_node_no_edges(self) -> None:
        G = nx.DiGraph()
        G.add_node("a")
        # 1 component, 0 cycles
        assert compute_betti_numbers(G) == (1, 0)

    def test_tree_has_no_cycles(self) -> None:
        """A tree on 4 nodes has β₀=1 (connected), β₁=0 (no cycle)."""
        G = nx.DiGraph()
        G.add_edges_from([("a", "b"), ("a", "c"), ("c", "d")])
        b0, b1 = compute_betti_numbers(G)
        assert b0 == 1
        assert b1 == 0

    def test_triangle_has_one_cycle(self) -> None:
        G = nx.DiGraph()
        G.add_edges_from([("a", "b"), ("b", "c"), ("c", "a")])
        b0, b1 = compute_betti_numbers(G)
        assert b0 == 1
        assert b1 == 1

    def test_two_disconnected_components(self) -> None:
        G = nx.DiGraph()
        G.add_edges_from([("a", "b"), ("c", "d")])
        b0, b1 = compute_betti_numbers(G)
        assert b0 == 2
        assert b1 == 0

    def test_b1_clamped_to_non_negative(self) -> None:
        """A graph with edges than nodes-1 (e.g. an isolated node + a tree)
        could in principle compute negative b1; the impl clamps to ≥0."""
        G = nx.DiGraph()
        G.add_node("isolated")
        b0, b1 = compute_betti_numbers(G)
        assert b1 == 0


# ── compute_topological_stability ──────────────────────────────────


class TestTopologicalStability:
    def test_acyclic_graph_returns_zero_stability(self) -> None:
        """When β₁ = 0 (no cycles), stability is 0.0 and worst_node is
        the 'none' sentinel — no node removal can reduce a cycle count
        that's already zero."""
        G = nx.DiGraph()
        G.add_edges_from([("a", "b"), ("b", "c")])
        result = compute_topological_stability(G)
        assert result["stability"] == 0.0
        assert result["worst_node"] == "none"
        assert result["betti"] == (1, 0)

    def test_triangle_finds_critical_node(self) -> None:
        """In a triangle, removing any node breaks the cycle — stability
        should be 0.0 (worst-case ratio after removal is 0/1)."""
        G = nx.DiGraph()
        G.add_edges_from([("a", "b"), ("b", "c"), ("c", "a")])
        result = compute_topological_stability(G)
        assert result["stability"] == 0.0
        assert result["worst_node"] in {"a", "b", "c"}
        assert result["betti"] == (1, 1)

    def test_two_disjoint_triangles(self) -> None:
        """Two disjoint triangles → β₀=2, β₁=2. Removing one node from
        either triangle drops β₁ to 1 → ratio 0.5 (the worst case
        across all nodes — none can drop it lower)."""
        G = nx.DiGraph()
        G.add_edges_from(
            [
                ("a", "b"),
                ("b", "c"),
                ("c", "a"),
                ("d", "e"),
                ("e", "f"),
                ("f", "d"),
            ]
        )
        result = compute_topological_stability(G)
        assert result["betti"] == (2, 2)
        assert result["stability"] == 0.5

    def test_returns_dict_with_required_keys(self) -> None:
        G = nx.DiGraph()
        G.add_edges_from([("a", "b"), ("b", "a")])
        result = compute_topological_stability(G)
        assert set(result.keys()) == {"stability", "worst_node", "betti"}
