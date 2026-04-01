"""Linearize /dev/shm JSON traces into numeric vectors for sheaf computation."""

from __future__ import annotations

STANCE_MAP = {"nominal": 0.0, "cautious": 0.25, "degraded": 0.5, "critical": 1.0}
TREND_MAP = {"stable": 0.0, "rising": 0.5, "falling": -0.5}


def linearize_stimmung(state: dict) -> list[float]:
    vec = []
    for dim_name in [
        "health",
        "resource_pressure",
        "error_rate",
        "processing_throughput",
        "perception_confidence",
        "llm_cost_pressure",
        "grounding_quality",
        "operator_stress",
        "operator_energy",
        "physiological_coherence",
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
    keys = [
        "presence_probability",
        "flow_score",
        "audio_energy",
        "vad_confidence",
        "heart_rate_bpm",
    ]
    return [float(state.get(k, 0.0)) for k in keys]


def linearize_imagination(state: dict) -> list[float]:
    vec = [float(state.get("salience", 0.0))]
    dims = state.get("dimensions", {})
    for k in ["red", "blue", "green"]:
        vec.append(float(dims.get(k, 0.0)))
    vec.append(1.0 if state.get("continuation", False) else 0.0)
    return vec
