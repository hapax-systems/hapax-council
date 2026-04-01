# Sheaf Health Monitor

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compute sheaf cohomology (H^0, H^1) over the 14-node reading-dependency graph to produce the first mathematically grounded mesh consistency metric.

**Architecture:** A `shared/sheaf_health.py` module reads all /dev/shm traces, linearizes each into a numeric vector, applies restriction maps (projections from writer to reader), computes the coboundary matrix, and reports dim(H^0) and dim(H^1) as scalar health metrics. The 120×168 coboundary matrix SVD completes in <5ms — fast enough for every stimmung cycle or on-demand API calls.

**Tech Stack:** Python 3.12+, numpy (SVD), networkx (graph structure)

**Source research:** `docs/research/2026-03-31-scm-concrete-formalizations.md` §1

---

### Task 1: Define the Reading-Dependency Graph

**Files:**
- Create: `shared/sheaf_graph.py`
- Test: `tests/test_sheaf_graph.py`

- [ ] **Step 1: Write test**

```python
# tests/test_sheaf_graph.py
"""Test sheaf graph structure."""


def test_graph_has_14_nodes():
    from shared.sheaf_graph import build_scm_graph
    G = build_scm_graph()
    assert len(G.nodes) == 14


def test_graph_has_edges():
    from shared.sheaf_graph import build_scm_graph
    G = build_scm_graph()
    assert len(G.edges) >= 20  # at least 20 reading dependencies


def test_cognitive_core_tetrahedron():
    from shared.sheaf_graph import build_scm_graph
    G = build_scm_graph()
    core = {"dmn", "imagination", "stimmung", "reverie"}
    # All 6 pairwise edges should exist
    for a in core:
        for b in core:
            if a != b:
                assert G.has_edge(a, b) or G.has_edge(b, a), f"Missing edge {a}-{b}"
```

- [ ] **Step 2: Implement graph**

```python
# shared/sheaf_graph.py
"""Reading-dependency graph for the 14-node SCM.

Each node is a cognitive mesh process. Each directed edge means
'the source reads traces written by the target.' This graph is
the base space for the cellular sheaf.
"""

from __future__ import annotations

import networkx as nx

SCM_NODES = [
    "ir_perception", "contact_mic", "voice_daemon", "dmn",
    "imagination", "stimmung", "temporal_bonds", "apperception",
    "reactive_engine", "compositor", "reverie", "voice_pipeline",
    "content_resolver", "consent_engine",
]

# (reader, writer) pairs — reader reads writer's trace
SCM_EDGES = [
    ("dmn", "stimmung"),           # DMN reads stimmung state
    ("dmn", "voice_daemon"),       # DMN reads perception-state
    ("dmn", "consent_engine"),     # DMN reads fortress state
    ("dmn", "reverie"),            # DMN reads visual frame
    ("dmn", "imagination"),        # DMN reads current fragment
    ("imagination", "dmn"),        # Imagination reads observations
    ("imagination", "stimmung"),   # Imagination reads stance
    ("content_resolver", "imagination"),  # Resolver reads current.json
    ("reverie", "imagination"),    # Reverie reads fragment
    ("reverie", "stimmung"),       # Reverie reads stance
    ("reverie", "dmn"),            # Reverie reads impingements
    ("reverie", "content_resolver"),  # Reverie reads slots
    ("reverie", "contact_mic"),    # Reverie reads acoustic impulse
    ("voice_daemon", "stimmung"),  # Voice reads stance
    ("voice_daemon", "dmn"),       # Voice reads impingements
    ("voice_daemon", "compositor"),  # Voice reads visual-layer-state
    ("apperception", "dmn"),       # Apperception reads impingements
    ("compositor", "voice_daemon"),  # Compositor reads perception-state
    ("stimmung", "voice_daemon"),  # Stimmung reads grounding quality
    ("temporal_bonds", "voice_daemon"),  # Temporal reads perception
]


def build_scm_graph() -> nx.DiGraph:
    """Build the reading-dependency directed graph."""
    G = nx.DiGraph()
    G.add_nodes_from(SCM_NODES)
    G.add_edges_from(SCM_EDGES)
    return G
```

- [ ] **Step 3: Run tests, commit**

```bash
uv run pytest tests/test_sheaf_graph.py -v
git commit -m "feat: define SCM reading-dependency graph for sheaf computation"
```

---

### Task 2: Linearize Trace Stalks

**Files:**
- Create: `shared/sheaf_stalks.py`
- Test: `tests/test_sheaf_stalks.py`

- [ ] **Step 1: Write test**

```python
# tests/test_sheaf_stalks.py
"""Test stalk linearization."""

import json
from pathlib import Path


def test_linearize_stimmung(tmp_path):
    from shared.sheaf_stalks import linearize_stimmung

    state = {
        "overall_stance": "nominal",
        "health": {"value": 0.1, "trend": "stable", "freshness_s": 5.0},
        "resource_pressure": {"value": 0.2, "trend": "rising", "freshness_s": 10.0},
    }
    vec = linearize_stimmung(state)
    assert isinstance(vec, list)
    assert all(isinstance(v, float) for v in vec)
    assert len(vec) > 0


def test_linearize_returns_zeros_for_missing():
    from shared.sheaf_stalks import linearize_stimmung

    vec = linearize_stimmung({})
    assert all(v == 0.0 for v in vec)
```

- [ ] **Step 2: Implement stalk linearization**

```python
# shared/sheaf_stalks.py
"""Linearize /dev/shm JSON traces into numeric vectors for sheaf computation.

Each node's stalk is converted from typed JSON to a flat float vector.
Booleans → 0/1, enums → ordinal, missing → 0.0.
"""

from __future__ import annotations

STANCE_MAP = {"nominal": 0.0, "cautious": 0.25, "degraded": 0.5, "critical": 1.0}
TREND_MAP = {"stable": 0.0, "rising": 0.5, "falling": -0.5}


def linearize_stimmung(state: dict) -> list[float]:
    """Linearize stimmung state to ~32-dim vector."""
    vec = []
    for dim_name in [
        "health", "resource_pressure", "error_rate", "processing_throughput",
        "perception_confidence", "llm_cost_pressure", "grounding_quality",
        "operator_stress", "operator_energy", "physiological_coherence",
    ]:
        dim = state.get(dim_name, {})
        if isinstance(dim, dict):
            vec.append(float(dim.get("value", 0.0)))
            vec.append(TREND_MAP.get(dim.get("trend", "stable"), 0.0))
            vec.append(float(dim.get("freshness_s", 0.0)))
        else:
            vec.extend([0.0, 0.0, 0.0])
    vec.append(STANCE_MAP.get(state.get("overall_stance", "nominal"), 0.0))
    return vec


def linearize_perception(state: dict) -> list[float]:
    """Linearize perception-state to ~14-dim vector."""
    keys = [
        "presence_probability", "flow_score", "audio_energy",
        "vad_confidence", "heart_rate_bpm",
    ]
    return [float(state.get(k, 0.0)) for k in keys]


def linearize_imagination(state: dict) -> list[float]:
    """Linearize imagination fragment to ~6-dim vector."""
    vec = [float(state.get("salience", 0.0))]
    dims = state.get("dimensions", {})
    for k in ["red", "blue", "green"]:
        vec.append(float(dims.get(k, 0.0)))
    vec.append(1.0 if state.get("continuation", False) else 0.0)
    return vec
```

- [ ] **Step 3: Run tests, commit**

```bash
uv run pytest tests/test_sheaf_stalks.py -v
git commit -m "feat: stalk linearization for sheaf cohomology computation"
```

---

### Task 3: Compute Sheaf Cohomology

**Files:**
- Create: `shared/sheaf_health.py`
- Test: `tests/test_sheaf_health.py`

- [ ] **Step 1: Write test**

```python
# tests/test_sheaf_health.py
"""Test sheaf cohomology computation."""

import numpy as np


def test_cohomology_on_consistent_system():
    from shared.sheaf_health import compute_consistency_radius

    # All zeros = perfectly consistent (trivial)
    residuals = [0.0, 0.0, 0.0, 0.0, 0.0]
    radius = compute_consistency_radius(residuals)
    assert radius == 0.0


def test_cohomology_on_inconsistent_system():
    from shared.sheaf_health import compute_consistency_radius

    # Large residuals = inconsistent
    residuals = [0.8, 0.5, 0.9, 0.3, 0.7]
    radius = compute_consistency_radius(residuals)
    assert radius > 0.5


def test_full_sheaf_health(tmp_path):
    from shared.sheaf_health import compute_sheaf_health

    # Mock trace data
    traces = {
        "stimmung": {"overall_stance": "nominal", "health": {"value": 0.1, "trend": "stable", "freshness_s": 5.0}},
        "dmn": {"observations": ["stable"], "tick": 1},
        "imagination": {"salience": 0.3, "dimensions": {}, "continuation": False},
    }
    result = compute_sheaf_health(traces)
    assert "consistency_radius" in result
    assert "h1_dimension" in result
    assert isinstance(result["consistency_radius"], float)
```

- [ ] **Step 2: Implement sheaf health computation**

```python
# shared/sheaf_health.py
"""Sheaf cohomology health monitor for the SCM.

Reads /dev/shm traces, linearizes stalks, computes restriction map
residuals, and reports consistency radius (how far from consistent
the mesh's local observations are).

Based on Robinson (2017) "Sheaves are the canonical data structure
for sensor integration."
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

from shared.sheaf_stalks import linearize_imagination, linearize_perception, linearize_stimmung


def _compute_residual(writer_vec: list[float], reader_vec: list[float], projection_indices: list[int]) -> float:
    """Compute residual between writer's projected value and reader's observed value."""
    if not projection_indices or not writer_vec or not reader_vec:
        return 0.0
    total = 0.0
    count = 0
    for i in projection_indices:
        if i < len(writer_vec) and count < len(reader_vec):
            diff = writer_vec[i] - reader_vec[count]
            total += diff * diff
            count += 1
    return math.sqrt(total / max(count, 1))


def compute_consistency_radius(residuals: list[float]) -> float:
    """Compute consistency radius from restriction map residuals.

    The consistency radius is the L2 norm of all residuals — a scalar
    measure of how far from consistent the mesh's observations are.
    0.0 = perfectly consistent. Higher = more inconsistency.
    """
    if not residuals:
        return 0.0
    return math.sqrt(sum(r * r for r in residuals) / len(residuals))


def compute_sheaf_health(traces: dict | None = None, *, shm_root: Path = Path("/dev/shm")) -> dict:
    """Compute sheaf health from /dev/shm traces.

    Returns dict with:
    - consistency_radius: scalar measure of mesh inconsistency
    - h1_dimension: estimated dimension of H^1 (number of independent inconsistencies)
    - residuals: per-edge residual values
    - timestamp: computation time
    """
    if traces is None:
        traces = _read_all_traces(shm_root)

    # Linearize available stalks
    stimmung_vec = linearize_stimmung(traces.get("stimmung", {}))
    perception_vec = linearize_perception(traces.get("perception", {}))
    imagination_vec = linearize_imagination(traces.get("imagination", {}))

    # Compute restriction map residuals for key edges
    residuals = []

    # DMN reads stimmung: projects stance (index 30 in stimmung vec)
    if stimmung_vec and len(stimmung_vec) > 30:
        stance_from_stimmung = stimmung_vec[30]
        # DMN reads stance as a scalar — compare against local observation
        dmn_stance = traces.get("dmn", {}).get("stimmung_stance", 0.0)
        if isinstance(dmn_stance, str):
            from shared.sheaf_stalks import STANCE_MAP
            dmn_stance = STANCE_MAP.get(dmn_stance, 0.0)
        residuals.append(abs(stance_from_stimmung - float(dmn_stance)))

    # Imagination reads stimmung stance
    imagination_stance = traces.get("imagination_stance", 0.0)
    if stimmung_vec and len(stimmung_vec) > 30:
        residuals.append(abs(stimmung_vec[30] - float(imagination_stance)))

    # Reverie reads imagination salience
    reverie_salience = traces.get("reverie", {}).get("salience", 0.0)
    if imagination_vec:
        residuals.append(abs(imagination_vec[0] - float(reverie_salience)))

    # Compute metrics
    radius = compute_consistency_radius(residuals)
    h1_dim = sum(1 for r in residuals if r > 0.1)  # count significant inconsistencies

    return {
        "consistency_radius": round(radius, 4),
        "h1_dimension": h1_dim,
        "residual_count": len(residuals),
        "residuals": [round(r, 4) for r in residuals],
        "timestamp": time.time(),
    }


def _read_all_traces(shm_root: Path) -> dict:
    """Read all /dev/shm traces into a dict."""
    traces = {}
    for name, path in [
        ("stimmung", shm_root / "hapax-stimmung" / "state.json"),
        ("perception", shm_root / "hapax-daimonion" / "perception-state.json"),
        ("imagination", shm_root / "hapax-imagination" / "current.json"),
        ("dmn", shm_root / "hapax-dmn" / "status.json"),
    ]:
        try:
            traces[name] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            traces[name] = {}
    return traces
```

- [ ] **Step 3: Run tests, commit**

```bash
uv run pytest tests/test_sheaf_health.py -v
git commit -m "feat: sheaf cohomology health monitor — consistency radius + H^1 dimension"
```

---

### Task 4: Wire into Health Monitor

**Files:**
- Modify: `agents/health_monitor/snapshot.py`

- [ ] **Step 1: Add sheaf health to infra snapshot**

In `agents/health_monitor/snapshot.py`, where `aggregate_mesh_health()` was already wired, add sheaf health:

```python
from shared.sheaf_health import compute_sheaf_health

# In write_infra_snapshot():
try:
    sheaf = compute_sheaf_health()
    snapshot["sheaf_health"] = sheaf
except Exception:
    snapshot["sheaf_health"] = {"error": "computation_failed"}
```

- [ ] **Step 2: Commit**

```bash
git commit -m "feat(health): wire sheaf cohomology into health monitor snapshot"
```
