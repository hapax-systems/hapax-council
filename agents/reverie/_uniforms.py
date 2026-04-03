"""Uniform computation helpers for Reverie mixer.

Extracted to keep mixer.py under the 300-line module limit.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

log = logging.getLogger("reverie.uniforms")

UNIFORMS_FILE = Path("/dev/shm/hapax-imagination/uniforms.json")
PLAN_FILE = Path("/dev/shm/hapax-imagination/pipeline/plan.json")
MATERIAL_MAP = {"water": 0, "fire": 1, "earth": 2, "air": 3, "void": 4}

_plan_defaults_cache: dict[str, float] | None = None
_plan_defaults_mtime: float = 0.0


def _load_plan_defaults() -> dict[str, float]:
    """Load plan.json defaults as {node_id.param: value} dict. Cached; invalidates on mtime change."""
    global _plan_defaults_cache, _plan_defaults_mtime
    try:
        current_mtime = PLAN_FILE.stat().st_mtime
    except OSError:
        current_mtime = 0.0
    if _plan_defaults_cache is not None and current_mtime == _plan_defaults_mtime:
        return _plan_defaults_cache
    defaults: dict[str, float] = {}
    try:
        plan = json.loads(PLAN_FILE.read_text())
        for p in plan.get("passes", []):
            node_id = p.get("node_id", "")
            for k, v in p.get("uniforms", {}).items():
                if isinstance(v, (int, float)):
                    defaults[f"{node_id}.{k}"] = float(v)
    except (OSError, json.JSONDecodeError):
        log.warning("Failed to load plan defaults", exc_info=True)
    _plan_defaults_cache = defaults
    _plan_defaults_mtime = current_mtime
    return defaults


def build_slot_opacities(imagination: dict | None, fallback_salience: float) -> list[float]:
    """Build slot opacities from fragment salience (uniform, not per-reference)."""
    opacities = [0.0, 0.0, 0.0, 0.0]
    if not imagination:
        return opacities
    salience = float(imagination.get("salience", fallback_salience))
    if salience > 0:
        opacities[0] = salience
    return opacities


SLOT_CENTERS = {0: (0.4, 0.4), 1: (0.6, 0.4), 2: (0.4, 0.6), 3: (0.6, 0.6)}


def update_trace(
    imagination: dict | None,
    last_salience: float,
    trace_strength: float,
    trace_radius: float,
    trace_center: tuple[float, float],
    trace_decay_rate: float,
    dt: float,
) -> tuple[float, float, float, tuple[float, float]]:
    """Update dwelling trace state. Returns (salience, strength, radius, center)."""
    current_salience = float(imagination.get("salience", 0.0)) if imagination else 0.0
    if last_salience > 0.2 and current_salience < last_salience * 0.5:
        trace_strength = min(1.0, last_salience)
        trace_radius = 0.3 + last_salience * 0.2
        trace_center = SLOT_CENTERS.get(0, (0.5, 0.5))
        log.info(
            "Trace: strength=%.2f radius=%.2f center=%s", trace_strength, trace_radius, trace_center
        )
    if trace_strength > 0:
        trace_strength = max(0.0, trace_strength - trace_decay_rate * dt)
    return current_salience, trace_strength, trace_radius, trace_center


def write_uniforms(
    imagination: dict | None,
    stimmung: dict | None,
    visual_chain,
    trace_strength: float,
    trace_center: tuple[float, float],
    trace_radius: float,
    reduction: float = 1.0,
) -> None:
    """Compute and write merged uniforms to uniforms.json."""
    chain_params = visual_chain.compute_param_deltas()

    # Load plan defaults — the Rust pipeline treats uniforms as absolute overrides,
    # so chain deltas must be added to plan defaults before writing.
    plan_defaults = _load_plan_defaults()

    # Silence factor: attenuate vocabulary graph when imagination is absent or stale.
    IMAGINATION_STALE_S = 60.0
    SILENCE_FLOOR = 0.15
    if imagination is None:
        silence = SILENCE_FLOOR
    else:
        frag_age = time.time() - float(imagination.get("timestamp", 0))
        if frag_age > IMAGINATION_STALE_S:
            raw = 1.0 - (frag_age - IMAGINATION_STALE_S) / IMAGINATION_STALE_S
            silence = max(SILENCE_FLOOR, raw)
        else:
            silence = 1.0

    uniforms: dict[str, float] = {}

    # Write EVERY plan-default param every tick: value = base + delta.
    # When delta is zero, value = base (the plan default). This ensures:
    #   - Smooth return to vocabulary defaults as chain levels decay
    #   - No sticky overrides (Rust retains last value when key is absent)
    #   - Subtle modulations below any threshold still reach the GPU
    for key, base in plan_defaults.items():
        delta = chain_params.get(key, 0.0)
        if isinstance(delta, (int, float)):
            uniforms[key] = base + delta * reduction * silence
        else:
            uniforms[key] = base

    # Content layer: material and salience come from imagination, not chain deltas.
    if imagination:
        uniforms["content.material"] = float(
            MATERIAL_MAP.get(str(imagination.get("material", "water")), 0)
        )
        uniforms["content.salience"] = float(imagination.get("salience", 0.0)) * silence

    # Trace params (Amendment 2): always written, zero when inactive.
    uniforms["fb.trace_center_x"] = trace_center[0] if trace_strength > 0 else 0.5
    uniforms["fb.trace_center_y"] = trace_center[1] if trace_strength > 0 else 0.5
    uniforms["fb.trace_radius"] = trace_radius if trace_strength > 0 else 0.0
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

    # Write all scalar overrides to uniforms.json. The Rust pipeline parses this
    # as HashMap<String, f64> — non-scalar values (arrays) must be excluded or
    # the entire parse fails silently. Per-node overrides (node.param) and signal
    # overrides (signal.*) both flow through this file.
    scalar_uniforms = {k: v for k, v in uniforms.items() if isinstance(v, (int, float))}

    try:
        UNIFORMS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = UNIFORMS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(scalar_uniforms))
        tmp.rename(UNIFORMS_FILE)
    except OSError:
        log.warning("Failed to write uniforms", exc_info=True)
