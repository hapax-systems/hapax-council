"""Uniform computation helpers for Reverie mixer.

Extracted to keep mixer.py under the 300-line module limit.
"""

from __future__ import annotations

import json
import logging
import math
import time
from collections.abc import Iterable
from pathlib import Path

from agents.reverie.programme_context import ProgrammeProvider
from agents.reverie.substrate_palette import compute_substrate_saturation

log = logging.getLogger("reverie.uniforms")


def _sanitize_uniform_value(value: float | int | bool) -> float:
    """Clamp NaN/Inf to 0.0; coerce bool to float; clip to safe range.

    Rust ``serde_json`` silently crashes on NaN/Inf in input. The visual
    chain must NEVER write a poison value into ``uniforms.json``: a
    single NaN aggregate from ``compute_param_deltas()`` (e.g. from a
    divide-by-zero in a per-tick mapping) would freeze the GPU bridge
    until the file is hand-edited. This sanitizer is the last line of
    defence — bad input → safe default → log warning, no retry/recovery.

    Audit: 24h independent-auditor batch 2026-05-02 (E #9). The audit
    found ``compute_param_deltas()`` aggregates without clamping, so
    upstream NaN/Inf/bool propagation could land in the JSON dump.
    """
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    f = float(value)
    if math.isnan(f) or math.isinf(f):
        return 0.0
    # Clip to a generous sanity bound. Uniforms are usually [0, 1] or
    # [-π, π]; allow [-1e6, 1e6] to catch the truly pathological without
    # rejecting legitimate large modulation values (e.g. hue degrees,
    # accumulated phase).
    return max(-1e6, min(1e6, f))


UNIFORMS_FILE = Path("/dev/shm/hapax-imagination/uniforms.json")
PLAN_FILE = Path("/dev/shm/hapax-imagination/pipeline/plan.json")
HOMAGE_SUBSTRATE_PACKAGE_FILE = Path("/dev/shm/hapax-compositor/homage-substrate-package.json")
MATERIAL_MAP = {"water": 0, "fire": 1, "earth": 2, "air": 3, "void": 4}

# HOMAGE Phase A6 — substrate invariant (governance doc §3).
# Per the reckoning §3.7 + substrate-invariant doc, when the active
# homage package is BitchX the Reverie ``colorgrade`` pass must damp
# saturation to ~0.40 (range 0.35-0.55) and rotate hue toward the
# package accent (180° cyan) so Reverie reads as a tinted ground, not
# a kaleidoscopic competitor for visual attention. The choreographer
# publishes the palette hint at ``HOMAGE_SUBSTRATE_PACKAGE_FILE``; this
# module honors the hint by overriding the colorgrade node's per-node
# params after plan_defaults + chain deltas are merged, so neither the
# base defaults (saturation=1.0) nor any chain amplification can
# override the damping.
#
# The vocabulary preset's colorgrade node is keyed ``color`` (not
# ``colorgrade``) — so the uniforms.json keys written here are
# ``color.saturation`` / ``color.hue_rotate`` / ``color.brightness``.
_BITCHX_COLOR_SATURATION: float = 0.40
_BITCHX_COLOR_HUE_ROTATE: float = 180.0
_BITCHX_COLOR_BRIGHTNESS: float = 0.85

_plan_defaults_cache: dict[str, float] | None = None
_plan_defaults_mtime: float = 0.0


def _iter_passes(plan: dict) -> Iterable[dict]:
    """Yield pass dicts from either v1 (flat) or v2 (targets.*) plan schemas.

    The Rust DynamicPipeline emits v2 (``plan["targets"][name]["passes"]``).
    Walking ``plan["passes"]`` on a v2 plan returns an empty iterator, which
    silently emptied the defaults cache and starved the visual chain → GPU
    bridge. Handle both schemas so the reader stays robust to either.
    """
    targets = plan.get("targets")
    if isinstance(targets, dict):
        for target in targets.values():
            if isinstance(target, dict):
                yield from target.get("passes", [])
        return
    yield from plan.get("passes", [])


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
        for p in _iter_passes(plan):
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


def _read_homage_substrate_package(path: Path | None = None) -> dict | None:
    """Read the current homage substrate-package broadcast, if any.

    Returns the parsed payload on success, ``None`` on any failure
    (file missing, unreadable bytes, malformed JSON, non-dict payload).
    This path is load-bearing for the Reverie substrate-invariant but
    must never raise — missing / stale / corrupt files fall through to
    plan defaults, which is the documented failure posture.
    """
    p = path or HOMAGE_SUBSTRATE_PACKAGE_FILE
    try:
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _apply_homage_package_damping(
    uniforms: dict[str, float],
    package_payload: dict | None,
) -> None:
    """Apply the active homage package's colorgrade damping in place.

    Per the reverie-substrate-invariant governance doc §3, the reverie
    mixer maps ``palette_accent_hue_deg`` onto the colorgrade node's
    per-node params (hue rotation + saturation damping). When BitchX is
    the active package this writes ``color.saturation`` / ``color.hue_rotate``
    / ``color.brightness`` at the spec-mandated damped values so the
    Reverie frame reads as a tinted-cyan ground rather than a
    kaleidoscopic competitor.

    Called after plan_defaults + chain_params are merged so the damping
    is authoritative — chain deltas cannot re-amplify saturation above
    the substrate-invariant ceiling.
    """
    if not package_payload:
        return
    package_name = package_payload.get("package")
    if package_name == "bitchx":
        uniforms["color.saturation"] = _BITCHX_COLOR_SATURATION
        uniforms["color.hue_rotate"] = _BITCHX_COLOR_HUE_ROTATE
        uniforms["color.brightness"] = _BITCHX_COLOR_BRIGHTNESS


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
    *,
    programme_provider: ProgrammeProvider | None = None,
    transition_energy: float = 0.0,
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

    # Content layer: material / salience / intensity come from imagination,
    # not chain deltas. The Rust side routes these three keys into
    # ``UniformData.custom[0][0..2]`` (F8, dynamic_pipeline.rs render()),
    # which the WGSL reads as ``material_id`` / ``slot salience`` /
    # ``intensity`` via ``uniforms.custom[0]``. Before F8 landed, these
    # writes were silently dropped — ``content_layer.wgsl`` has no
    # ``@group(2) Params`` binding so the per-node params_buffer loop
    # skipped it, and no other code path populated custom[0]. Bachelard
    # Amendment 3 (material quality) was implemented in the shader but
    # unreachable at runtime.
    if imagination:
        uniforms["content.material"] = float(
            MATERIAL_MAP.get(str(imagination.get("material", "water")), 0)
        )
        uniforms["content.salience"] = float(imagination.get("salience", 0.0)) * silence
        uniforms["content.intensity"] = float(imagination.get("salience", 0.0)) * silence

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

    # HOMAGE Phase A6 — substrate invariant. Apply the active package's
    # colorgrade damping AFTER plan_defaults + chain deltas so the damped
    # saturation is authoritative (no chain amplification can override).
    # Missing / malformed broadcast falls through without damping.
    _apply_homage_package_damping(uniforms, _read_homage_substrate_package())

    # Programme-layer Phase 8 — programme-owned saturation centre. When an
    # active programme carries a `reverie_saturation_target`, compose it
    # with stimmung + transition_energy and override `color.saturation`.
    # Programme target overrides BitchX saturation but leaves hue/brightness
    # damping intact (those are package-scoped, not programme-scoped).
    # `programme_provider=None` short-circuits to existing behaviour so
    # pre-Phase-8 callers (and the homage damping tests) stay untouched.
    if programme_provider is not None:
        composed = compute_substrate_saturation(programme_provider(), stimmung, transition_energy)
        if composed is not None:
            uniforms["color.saturation"] = composed

    # Write all scalar overrides to uniforms.json. The Rust pipeline parses this
    # as HashMap<String, f64> — non-scalar values (arrays) must be excluded or
    # the entire parse fails silently. Per-node overrides (node.param) and signal
    # overrides (signal.*) both flow through this file.
    #
    # NaN/Inf/bool sanitisation: Rust ``serde_json`` silently crashes on
    # NaN/Inf input. ``compute_param_deltas()`` aggregates per-dimension
    # mappings without clamping, so upstream propagation (divide-by-zero,
    # bool-to-float coercion, runaway modulation) could land a poison
    # value in this dict. ``_sanitize_uniform_value`` is the last line
    # of defence — every value gets coerced/clamped before serialisation.
    # Per-tick deltas don't need an additional per-key envelope clamp:
    # they're applied to envelope-clipped base values (plan defaults +
    # bounded chain modulation), so reaching ±1e6 indicates upstream
    # corruption rather than legitimate modulation.
    scalar_uniforms = {
        k: _sanitize_uniform_value(v)
        for k, v in uniforms.items()
        if isinstance(v, (int, float, bool))
    }

    try:
        UNIFORMS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = UNIFORMS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(scalar_uniforms))
        tmp.rename(UNIFORMS_FILE)
    except OSError:
        log.warning("Failed to write uniforms", exc_info=True)
