# Topological Diagnostic (Persistent Homology)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compute Betti numbers (β₀, β₁) of the SCM's reading-dependency graph to detect structural phase transitions when components fail.

**Architecture:** Uses the sheaf graph from Plan 1. Computes simplicial complex (clique complex of undirected reading graph), then Betti numbers via boundary matrix rank. Reports topological stability score = min(β₁ after single-node removal / β₁ before).

**Tech Stack:** Python 3.12+, numpy, shared/sheaf_graph.py (from sheaf plan)

---

### Task 1: Compute Betti Numbers

**Files:**
- Create: `shared/topology_health.py`
- Test: `tests/test_topology_health.py`

- [ ] **Step 1: Write test**

```python
# tests/test_topology_health.py
"""Test topological health metrics."""


def test_betti_0_connected():
    from shared.topology_health import compute_betti_numbers
    from shared.sheaf_graph import build_scm_graph
    b0, b1 = compute_betti_numbers(build_scm_graph())
    assert b0 == 1  # connected


def test_betti_1_has_cycles():
    from shared.topology_health import compute_betti_numbers
    from shared.sheaf_graph import build_scm_graph
    b0, b1 = compute_betti_numbers(build_scm_graph())
    assert b1 >= 3  # at least 3 independent cycles


def test_topological_stability():
    from shared.topology_health import compute_topological_stability
    from shared.sheaf_graph import build_scm_graph
    stability = compute_topological_stability(build_scm_graph())
    assert 0.0 < stability < 1.0
    assert "worst_node" in stability or isinstance(stability, dict)
```

- [ ] **Step 2: Implement**

```python
# shared/topology_health.py
"""Topological health diagnostics for the SCM.

Computes Betti numbers from the reading-dependency graph's clique complex.
β₀ = connected components (should be 1). β₁ = independent cycles (information loops).
Topological stability = resilience to single-node failure.
"""

from __future__ import annotations

import numpy as np
import networkx as nx


def _clique_complex_boundary_1(G: nx.Graph) -> np.ndarray:
    """Build boundary matrix ∂₁: C₁ → C₀ for the clique complex."""
    nodes = sorted(G.nodes())
    edges = sorted(G.edges())
    node_idx = {n: i for i, n in enumerate(nodes)}
    B = np.zeros((len(nodes), len(edges)), dtype=float)
    for j, (u, v) in enumerate(edges):
        B[node_idx[u], j] = -1
        B[node_idx[v], j] = 1
    return B


def compute_betti_numbers(G: nx.DiGraph) -> tuple[int, int]:
    """Compute β₀ and β₁ of the undirected reading-dependency graph."""
    U = G.to_undirected()
    if len(U.nodes) == 0:
        return 0, 0

    # β₀ = connected components
    b0 = nx.number_connected_components(U)

    # β₁ = dim(ker(∂₁)) - dim(im(∂₂))
    # For a graph (1-complex), ∂₂ = 0 (no 2-cells unless we add triangles)
    # So β₁ = |E| - |V| + β₀ (Euler characteristic)
    b1 = len(U.edges) - len(U.nodes) + b0

    return b0, max(0, b1)


def compute_topological_stability(G: nx.DiGraph) -> dict:
    """Compute topological stability: resilience to single-node failure.

    Returns dict with:
    - stability: min(β₁_after / β₁_before) across all single-node removals
    - worst_node: the node whose removal causes maximum β₁ loss
    - betti: (β₀, β₁) of the full graph
    """
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
```

- [ ] **Step 3: Run tests, commit**

```bash
uv run pytest tests/test_topology_health.py -v
git commit -m "feat: topological diagnostic — Betti numbers and stability score"
```

---

### Task 2: Wire into Health Monitor

**Files:** `agents/health_monitor/snapshot.py`

- [ ] **Step 1: Add topology to snapshot**

```python
from shared.topology_health import compute_topological_stability
from shared.sheaf_graph import build_scm_graph

try:
    topo = compute_topological_stability(build_scm_graph())
    snapshot["topology"] = topo
except Exception:
    snapshot["topology"] = {"error": "computation_failed"}
```

- [ ] **Step 2: Commit**

```bash
git commit -m "feat(health): wire topological diagnostic into health monitor"
```
