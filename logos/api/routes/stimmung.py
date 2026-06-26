"""Stimmung state endpoint for the Hapax Obsidian plugin v2."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter

from logos.api.deps.stream_redaction import (
    band_coherence,
    band_energy,
    band_tension,
    is_publicly_visible,
)
from shared.eigenform_analysis import analyze_convergence
from shared.sheaf_graph import build_scm_graph
from shared.sheaf_health import compute_restriction_consistency
from shared.topology_health import compute_topological_stability

router = APIRouter(prefix="/api/stimmung", tags=["stimmung"])

# LRR Phase 6 §4.A — when stream is publicly visible, only these three
# operator-mental-state dimensions survive the redaction (banded into
# categorical labels). Non-banded projected dimensions are full-fidelity
# numeric values that read as biometric/cognitive surveillance on a broadcast.
_BROADCAST_SAFE_BANDED_DIMS: dict[str, callable] = {
    "operator_energy": band_energy,
    "physiological_coherence": band_coherence,
    "operator_stress": band_tension,
}

_SHM_STATE = Path("/dev/shm/hapax-stimmung/state.json")

_DIMENSION_KEYS = [
    "health",
    "resource_pressure",
    "local_capacity_pressure",
    "error_rate",
    "processing_throughput",
    "perception_confidence",
    "llm_cost_pressure",
    "grounding_quality",
    "exploration_deficit",
    "operator_stress",
    "operator_energy",
    "physiological_coherence",
]


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _build_dimensions(raw: dict) -> dict[str, dict]:
    """Build structured dimension objects from nested stimmung state."""
    dimensions: dict[str, dict] = {}
    for key in _DIMENSION_KEYS:
        dim_data = raw.get(key, {})
        if isinstance(dim_data, dict):
            value = dim_data.get("value", 0.0)
            trend = dim_data.get("trend", "stable")
            freshness_s = dim_data.get("freshness_s", 0.0)
        else:
            value = 0.0
            trend = "stable"
            freshness_s = 0.0
        dimensions[key] = {"value": value, "trend": trend, "freshness_s": freshness_s}
    return dimensions


@router.get("")
async def get_stimmung() -> dict:
    """Return structured stimmung state from /dev/shm/hapax-stimmung/state.json.

    LRR Phase 6 §4.A: when stream is publicly visible, replaces projected
    numeric dimension values with categorical bands for energy/coherence/
    tension and omits non-banded dimensions entirely. ``overall_stance``
    is categorical and broadcast-safe as-is.
    """
    raw = _read_json(_SHM_STATE)
    if raw is None:
        return {"overall_stance": "unknown", "dimensions": {}, "timestamp": 0}

    dimensions = _build_dimensions(raw)
    overall_stance = raw.get("overall_stance", "unknown")
    timestamp = raw.get("timestamp", 0)

    if is_publicly_visible():
        banded: dict[str, dict] = {}
        for dim_name, band_fn in _BROADCAST_SAFE_BANDED_DIMS.items():
            dim_data = dimensions.get(dim_name)
            if dim_data is None:
                continue
            label = band_fn(dim_data.get("value"))
            banded[dim_name] = {
                "band": label,
                "trend": dim_data.get("trend", "stable"),
                "freshness_s": dim_data.get("freshness_s", 0.0),
            }
        dimensions = banded

    response: dict = {
        "dimensions": dimensions,
        "overall_stance": overall_stance,
        "timestamp": timestamp,
    }

    if not is_publicly_visible():
        try:
            response["sheaf_health"] = compute_restriction_consistency()
            response["topology"] = compute_topological_stability(build_scm_graph())
        except Exception:
            pass

        try:
            response["eigenform"] = analyze_convergence()
        except Exception:
            response["eigenform"] = {"error": "analysis_failed"}

    return response
