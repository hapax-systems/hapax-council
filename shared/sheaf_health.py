"""Sheaf cohomology health monitor for the SCM.

Reports consistency_radius (how far from consistent) and h1_dimension
(number of independent inconsistencies). Based on Robinson (2017).
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

from shared.sheaf_stalks import STANCE_MAP, linearize_stimmung


def compute_consistency_radius(residuals: list[float]) -> float:
    if not residuals:
        return 0.0
    return math.sqrt(sum(r * r for r in residuals) / len(residuals))


def compute_sheaf_health(traces: dict | None = None, *, shm_root: Path = Path("/dev/shm")) -> dict:
    if traces is None:
        traces = _read_all_traces(shm_root)

    stimmung_vec = linearize_stimmung(traces.get("stimmung", {}))
    residuals = []

    # Restriction map residuals for key edges
    stimmung_stance_val = stimmung_vec[30] if len(stimmung_vec) > 30 else 0.0

    # DMN reads stimmung stance
    dmn_stance = traces.get("dmn", {}).get(
        "stance", traces.get("dmn", {}).get("overall_stance", "nominal")
    )
    if isinstance(dmn_stance, str):
        dmn_stance = STANCE_MAP.get(dmn_stance, 0.0)
    residuals.append(abs(stimmung_stance_val - float(dmn_stance)))

    # Imagination reads stimmung stance
    imag_stance = traces.get("imagination_stance", 0.0)
    if isinstance(imag_stance, str):
        imag_stance = STANCE_MAP.get(imag_stance, 0.0)
    residuals.append(abs(stimmung_stance_val - float(imag_stance)))

    # Perception confidence consistency
    stimmung_pc = stimmung_vec[12] if len(stimmung_vec) > 12 else 0.0  # perception_confidence.value
    perception = traces.get("perception", {})
    actual_confidence = float(
        perception.get("confidence", perception.get("perception_confidence", 0.0))
    )
    residuals.append(abs(stimmung_pc - actual_confidence))

    radius = compute_consistency_radius(residuals)
    h1_dim = sum(1 for r in residuals if r > 0.1)

    return {
        "consistency_radius": round(radius, 4),
        "h1_dimension": h1_dim,
        "residual_count": len(residuals),
        "residuals": [round(r, 4) for r in residuals],
        "timestamp": time.time(),
    }


def _read_all_traces(shm_root: Path) -> dict:
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
