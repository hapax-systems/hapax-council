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
    # Stimmung says perception is confident, but is the perception state actually fresh?
    stimmung_pc = stimmung_vec[12] if len(stimmung_vec) > 12 else 0.0  # perception_confidence.value
    perception = traces.get("perception", {})
    actual_confidence = float(
        perception.get("confidence", perception.get("perception_confidence", 0.0))
    )
    residuals.append(abs(stimmung_pc - actual_confidence))

    # Imagination-DMN coherence
    # If DMN observations are bland but imagination salience is high, that's inconsistent
    dmn_data = traces.get("dmn", {})
    dmn_obs_count = len(dmn_data.get("observations", []))
    imag_data = traces.get("imagination", {})
    imag_salience = float(imag_data.get("salience", 0.0))
    # Normalize observation count to [0, 1] — 5+ observations = 1.0
    dmn_activity = min(dmn_obs_count / 5.0, 1.0) if dmn_obs_count else 0.0
    residuals.append(abs(imag_salience - dmn_activity))

    # Presence-flow coherence
    # If presence is low (operator away) but flow is high, that's inconsistent
    presence_prob = float(perception.get("presence_probability", 0.0))
    flow_score = float(perception.get("flow_score", 0.0))
    if presence_prob < 0.3 and flow_score > 0.5:
        residuals.append(flow_score - presence_prob)
    else:
        residuals.append(0.0)

    # Stimmung stance vs aggregate mesh health
    # If stimmung says nominal but E_mesh is high, that's inconsistent
    mesh_data = traces.get("mesh", {})
    e_mesh = float(mesh_data.get("E_mesh", mesh_data.get("e_mesh", 0.0)))
    # nominal=0.0, critical=1.0 — E_mesh should correlate with stance severity
    residuals.append(abs(stimmung_stance_val - min(e_mesh, 1.0)))

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
        ("mesh", shm_root / "hapax-mesh" / "health.json"),
    ]:
        try:
            traces[name] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            traces[name] = {}
    return traces
