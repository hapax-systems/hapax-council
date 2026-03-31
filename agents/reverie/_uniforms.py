"""Uniform computation helpers for Reverie mixer.

Extracted to keep mixer.py under the 300-line module limit.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("reverie.uniforms")

UNIFORMS_FILE = Path("/dev/shm/hapax-imagination/pipeline/uniforms.json")
MATERIAL_MAP = {"water": 0, "fire": 1, "earth": 2, "air": 3, "void": 4}


def build_slot_opacities(imagination: dict | None, fallback_salience: float) -> list[float]:
    """Build slot opacities from content references or fallback to single-slot."""
    opacities = [0.0, 0.0, 0.0, 0.0]
    if not imagination:
        return opacities
    refs = imagination.get("content_references", [])
    if isinstance(refs, list) and refs:
        for i, ref in enumerate(refs[:4]):
            if isinstance(ref, dict):
                opacities[i] = float(ref.get("salience", fallback_salience))
            else:
                opacities[i] = fallback_salience
    elif fallback_salience > 0:
        opacities[0] = fallback_salience
    return opacities


def write_uniforms(
    imagination: dict | None,
    stimmung: dict | None,
    visual_chain,
    trace_strength: float,
    trace_center: tuple[float, float],
    trace_radius: float,
    reduction: float = 1.0,
) -> None:
    """Compute and write merged uniforms to pipeline/uniforms.json."""
    material = "water"
    salience = 0.0
    if imagination:
        material = str(imagination.get("material", "water"))
        salience = float(imagination.get("salience", 0.0))

    material_val = float(MATERIAL_MAP.get(material, 0))
    chain_params = visual_chain.compute_param_deltas()

    uniforms: dict[str, object] = {
        "custom": [material_val],
        "slot_opacities": build_slot_opacities(imagination, salience),
    }

    for key, value in chain_params.items():
        uniforms[key] = value * reduction if isinstance(value, (int, float)) else value

    if trace_strength > 0:
        uniforms["fb.trace_center_x"] = trace_center[0]
        uniforms["fb.trace_center_y"] = trace_center[1]
        uniforms["fb.trace_radius"] = trace_radius
        uniforms["fb.trace_strength"] = trace_strength

    if stimmung:
        stance = stimmung.get("overall_stance", "nominal")
        stance_map = {"nominal": 0.0, "cautious": 0.25, "degraded": 0.5, "critical": 1.0}
        uniforms["signal.stance"] = stance_map.get(stance, 0.0)
        worst_infra = 0.0
        for dim_key in (
            "health",
            "resource_pressure",
            "error_rate",
            "processing_throughput",
            "perception_confidence",
            "llm_cost_pressure",
        ):
            dim_data = stimmung.get(dim_key, {})
            if isinstance(dim_data, dict):
                worst_infra = max(worst_infra, dim_data.get("value", 0.0))
        uniforms["signal.color_warmth"] = worst_infra

    try:
        UNIFORMS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = UNIFORMS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(uniforms))
        tmp.rename(UNIFORMS_FILE)
    except OSError:
        log.debug("Failed to write uniforms", exc_info=True)
