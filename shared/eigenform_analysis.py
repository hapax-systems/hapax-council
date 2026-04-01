"""Eigenform convergence detection from logged state vectors.

Reads /dev/shm/hapax-eigenform/state-log.jsonl and computes:
- T(x) - x norm: how much the state changes between consecutive ticks
- Convergence detection: when norm drops below threshold for N ticks
- Orbit detection: when norm oscillates within a bounded range
"""

from __future__ import annotations

import json
import math
from pathlib import Path

EIGENFORM_LOG = Path("/dev/shm/hapax-eigenform/state-log.jsonl")

NUMERIC_FIELDS = [
    "presence",
    "flow_score",
    "audio_energy",
    "imagination_salience",
    "visual_brightness",
    "heart_rate",
    "operator_stress",
    "e_mesh",
    "consistency_radius",
]

STANCE_MAP = {"nominal": 0.0, "cautious": 0.25, "degraded": 0.5, "critical": 1.0}


def _vectorize(entry: dict) -> list[float]:
    """Convert a log entry to a numeric vector."""
    vec = [float(entry.get(f, 0.0)) for f in NUMERIC_FIELDS]
    vec.append(STANCE_MAP.get(entry.get("stimmung_stance", "nominal"), 0.0))
    return vec


def _norm(a: list[float], b: list[float]) -> float:
    """L2 distance between two vectors."""
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b, strict=True)))


def analyze_convergence(
    *, path: Path = EIGENFORM_LOG, window: int = 10, threshold: float = 0.05
) -> dict:
    """Analyze eigenform convergence from logged state vectors.

    Returns:
    - converged: bool — has the system reached an eigenform?
    - mean_delta: float — mean ||T(x) - x|| over the window
    - max_delta: float — max delta in window
    - orbit_amplitude: float — range of deltas (high = orbit, low = fixed point)
    - entries_analyzed: int
    - eigenform_type: "fixed_point" | "stable_orbit" | "divergent" | "insufficient_data"
    """
    try:
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        entries = [json.loads(line) for line in lines if line.strip()]
    except (OSError, json.JSONDecodeError):
        return {
            "converged": False,
            "mean_delta": 1.0,
            "max_delta": 1.0,
            "orbit_amplitude": 0.0,
            "entries_analyzed": 0,
            "eigenform_type": "insufficient_data",
        }

    if len(entries) < window + 1:
        return {
            "converged": False,
            "mean_delta": 1.0,
            "max_delta": 1.0,
            "orbit_amplitude": 0.0,
            "entries_analyzed": len(entries),
            "eigenform_type": "insufficient_data",
        }

    # Compute deltas for the last `window` consecutive pairs
    recent = entries[-(window + 1) :]
    deltas = []
    for i in range(len(recent) - 1):
        v1 = _vectorize(recent[i])
        v2 = _vectorize(recent[i + 1])
        deltas.append(_norm(v1, v2))

    mean_delta = sum(deltas) / len(deltas)
    max_delta = max(deltas)
    min_delta = min(deltas)
    orbit_amplitude = max_delta - min_delta

    # Classification
    if mean_delta < threshold:
        eigenform_type = "fixed_point"
        converged = True
    elif orbit_amplitude < threshold and mean_delta < threshold * 5:
        eigenform_type = "stable_orbit"
        converged = True
    else:
        eigenform_type = "divergent"
        converged = False

    return {
        "converged": converged,
        "mean_delta": round(mean_delta, 4),
        "max_delta": round(max_delta, 4),
        "orbit_amplitude": round(orbit_amplitude, 4),
        "entries_analyzed": len(entries),
        "eigenform_type": eigenform_type,
    }
