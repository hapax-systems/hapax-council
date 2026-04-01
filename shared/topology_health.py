"""Topological health diagnostics. β₀=components, β₁=cycles."""

from __future__ import annotations

import networkx as nx


def compute_betti_numbers(G: nx.DiGraph) -> tuple[int, int]:
    U = G.to_undirected()
    if not U.nodes:
        return 0, 0
    b0 = nx.number_connected_components(U)
    b1 = len(U.edges) - len(U.nodes) + b0
    return b0, max(0, b1)


def compute_topological_stability(G: nx.DiGraph) -> dict:
    b0, b1 = compute_betti_numbers(G)
    if b1 == 0:
        return {"stability": 0.0, "worst_node": "none", "betti": (b0, b1)}

    worst_node = "none"
    worst_ratio = 1.0

    for node in G.nodes():
        H = G.copy()
        H.remove_node(node)
        _, b1_after = compute_betti_numbers(H)
        ratio = b1_after / b1
        if ratio < worst_ratio:
            worst_ratio = ratio
            worst_node = node

    return {
        "stability": round(worst_ratio, 3),
        "worst_node": worst_node,
        "betti": (b0, b1),
    }
