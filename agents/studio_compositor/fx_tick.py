"""Per-frame tick subroutines for the FX chain."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ── Stimmung stance reader ────────────────────────────────────────────────────
#
# Halftone-monoculture root cause (researcher audit, 2026-05-03): the
# governance tick previously hardcoded ``stance="nominal"``, so
# ``_STATE_MATRIX[("nominal","low")]`` always picked its first member —
# halftone_preset — whenever recruitment fell silent for more than a
# cooldown. Reading the live stimmung overall_stance (with a 30s cache so
# the 30 fps governance tick doesn't re-stat the SHM file every frame)
# lets the matrix actually exercise its other rows. Missing/parse-error
# falls back to "nominal" — same default as before, so behaviour with no
# stimmung writer matches the old hardcoded path.
_STIMMUNG_STATE_PATH = Path("/dev/shm/hapax-stimmung/state.json")
_STANCE_CACHE_TTL_S = 30.0
_VALID_MATRIX_STANCES: frozenset[str] = frozenset({"nominal", "cautious", "degraded", "critical"})
_stance_cache: tuple[float, str] = (0.0, "nominal")


def _read_stimmung_stance() -> str:
    """Return a ``_STATE_MATRIX``-keyable stance from stimmung.

    Cached for ``_STANCE_CACHE_TTL_S`` so the 30 fps governance tick
    doesn't re-stat / re-parse the SHM file on every frame. Stimmung
    publishes ``overall_stance`` with values ``nominal``, ``seeking``,
    ``cautious``, ``degraded``, ``critical`` (see ``shared.stimmung.Stance``).
    The atmospheric ``_STATE_MATRIX`` only carries entries for
    ``nominal``/``cautious``/``degraded``/``critical``; ``seeking`` is
    folded back to ``nominal`` so the matrix lookup still hits.
    """
    global _stance_cache
    now = time.monotonic()
    cached_t, cached_stance = _stance_cache
    if now - cached_t < _STANCE_CACHE_TTL_S:
        return cached_stance
    stance = "nominal"
    try:
        raw = json.loads(_STIMMUNG_STATE_PATH.read_text(encoding="utf-8"))
        candidate = raw.get("overall_stance") or raw.get("stance") or "nominal"
        if isinstance(candidate, str):
            candidate = candidate.lower()
            if candidate in _VALID_MATRIX_STANCES:
                stance = candidate
            elif candidate == "seeking":
                # No matrix entry for SEEKING — fall back to nominal so the
                # lookup hits a non-degenerate row.
                stance = "nominal"
            else:
                stance = "nominal"
    except (OSError, json.JSONDecodeError, ValueError):
        log.debug("stimmung stance read failed; falling back to nominal", exc_info=True)
    _stance_cache = (now, stance)
    return stance


def _degraded_active() -> bool:
    """Return True while DEGRADED mode is active (task #122).

    Isolated helper so the import stays lazy — unit-test environments
    without prometheus/compositor metrics can still exercise fx tick
    paths without pulling in the metrics registry.
    """
    try:
        from agents.studio_compositor.degraded_mode import get_controller

        return get_controller().is_active()
    except Exception:
        log.debug("degraded-mode check failed", exc_info=True)
        return False


def _autonomous_fx_mutations_enabled() -> bool:
    from .preset_policy import autonomous_fx_mutations_enabled

    return autonomous_fx_mutations_enabled()


def _pin_slots_to_passthrough(compositor: Any) -> None:
    """Force every non-passthrough slot to passthrough (task #122).

    Called from :func:`tick_slot_pipeline` while DEGRADED mode is
    active. Uses the same property-set path as
    :meth:`SlotPipeline.activate_plan` so it honors the recompile
    diff-check (byte-identical passthrough sets no-op on the Rust
    side). Clearing the slot_assignments list ensures that the normal
    tick path does not resume mid-degraded by re-applying preset
    params from ``_slot_preset_params``.
    """
    slot_pipeline = getattr(compositor, "_slot_pipeline", None)
    if slot_pipeline is None:
        return
    try:
        from agents.effect_graph.pipeline import PASSTHROUGH_SHADER
    except Exception:
        log.debug("PASSTHROUGH_SHADER import failed; degraded pin noop", exc_info=True)
        return

    slots = getattr(slot_pipeline, "_slots", [])
    assignments = getattr(slot_pipeline, "_slot_assignments", [])
    last_frag = getattr(slot_pipeline, "_slot_last_frag", [])
    changed = False
    for i, slot in enumerate(slots):
        if i < len(last_frag) and last_frag[i] == PASSTHROUGH_SHADER:
            continue
        try:
            slot.set_property("fragment", PASSTHROUGH_SHADER)
            if i < len(last_frag):
                last_frag[i] = PASSTHROUGH_SHADER
            if i < len(assignments):
                assignments[i] = None
            changed = True
        except Exception:
            log.debug("degraded pin: set_property failed on slot %d", i, exc_info=True)
    if changed:
        log.info("DEGRADED mode: pinned %d fx slots to passthrough", len(slots))
        try:
            from agents.studio_compositor.degraded_mode import get_controller

            get_controller().record_hold("fx_chain")
        except Exception:
            log.debug("degraded hold record failed", exc_info=True)


def tick_governance(compositor: Any, t: float) -> None:
    """Perception-visual governance tick."""
    if compositor._graph_runtime is None or not hasattr(compositor, "_atmospheric_selector"):
        return

    # Task #122: skip preset-family rotation while degraded. Governance
    # would otherwise keep swapping presets during a service restart
    # and the fresh shaders could surface compile errors or partial
    # plans mid-degraded — exactly the raw failure state we want to
    # suppress. The slot pinner (tick_slot_pipeline) is the defense
    # in depth; suppressing the selector here avoids the wasted work.
    if _degraded_active():
        return

    if not _autonomous_fx_mutations_enabled():
        return

    # User override hold: when the user explicitly selects a preset via API,
    # governance is suppressed for a hold period to prevent instant override.
    hold_until = getattr(compositor, "_user_preset_hold_until", 0.0)
    if time.monotonic() < hold_until:
        return

    from agents.effect_graph.visual_governance import (
        compute_gestural_offsets,
        energy_level_from_activity,
    )

    from .effects import get_available_preset_names, try_graph_preset

    gov_data = compositor._overlay_state._data
    energy_level = energy_level_from_activity(gov_data.desk_activity)
    stance = _read_stimmung_stance()
    available = get_available_preset_names()
    target = compositor._atmospheric_selector.evaluate(
        stance=stance,
        energy_level=energy_level,
        available_presets=available,
        genre=gov_data.music_genre,
    )
    if target and target != getattr(compositor, "_current_preset_name", None):
        if try_graph_preset(compositor, target):
            compositor._current_preset_name = target

    offsets = compute_gestural_offsets(
        desk_activity=gov_data.desk_activity,
        gaze_direction="",
        person_count=0,
    )
    for (node_id, param), offset in offsets.items():
        if offset != 0 and compositor._graph_runtime.current_graph:
            if node_id in compositor._graph_runtime.current_graph.nodes:
                compositor._on_graph_params_changed(node_id, {param: offset})

    if gov_data.desk_activity in ("idle", ""):
        if compositor._idle_start is None:
            compositor._idle_start = time.monotonic()
    else:
        compositor._idle_start = None


def tick_modulator(compositor: Any, t: float, energy: float, b: float) -> None:
    """Node graph modulator tick."""
    if compositor._graph_runtime is None:
        return

    modulator = compositor._graph_runtime.modulator
    if not modulator.bindings:
        return

    signals = {"audio_rms": energy, "audio_beat": b, "time": t}
    data = compositor._overlay_state._data
    if data.flow_score > 0:
        signals["flow_score"] = data.flow_score
    if data.emotion_valence != 0:
        signals["stimmung_valence"] = data.emotion_valence
    if data.emotion_arousal != 0:
        signals["stimmung_arousal"] = data.emotion_arousal
    # Audio signals — use cached signals from fx_tick_callback (already called get_signals once)
    audio = getattr(compositor, "_cached_audio", None)
    if audio:
        signals["mixer_energy"] = audio.get("mixer_energy", 0.0)
        signals["mixer_beat"] = audio.get("mixer_beat", 0.0)
        signals["mixer_bass"] = audio.get("mixer_bass", 0.0)
        signals["mixer_mid"] = audio.get("mixer_mid", 0.0)
        signals["mixer_high"] = audio.get("mixer_high", 0.0)
        signals["beat_pulse"] = audio.get("beat_pulse", 0.0)
        # Onset classification (kick/snare/hat)
        signals["onset_kick"] = audio.get("onset_kick", 0.0)
        signals["onset_snare"] = audio.get("onset_snare", 0.0)
        signals["onset_hat"] = audio.get("onset_hat", 0.0)
        signals["sidechain_kick"] = audio.get("sidechain_kick", 0.0)
        # Timbral features
        signals["spectral_centroid"] = audio.get("spectral_centroid", 0.0)
        signals["spectral_flatness"] = audio.get("spectral_flatness", 0.0)
        signals["spectral_rolloff"] = audio.get("spectral_rolloff", 0.0)
        signals["zero_crossing_rate"] = audio.get("zero_crossing_rate", 0.0)
        # 8 mel bands (per-band AGC normalized)
        for band in (
            "sub_bass",
            "bass",
            "low_mid",
            "mid",
            "upper_mid",
            "presence",
            "brilliance",
            "air",
        ):
            signals[f"mel_{band}"] = audio.get(f"mel_{band}", 0.0)
    else:
        signals["mixer_energy"] = data.mixer_energy
        signals["mixer_beat"] = data.mixer_beat
        signals["mixer_bass"] = data.mixer_bass
        signals["mixer_mid"] = data.mixer_mid
        signals["mixer_high"] = data.mixer_high
    signals["desk_energy"] = data.desk_energy
    signals["desk_onset_rate"] = data.desk_onset_rate
    signals["desk_centroid"] = (
        min(1.0, data.desk_spectral_centroid / 4000.0)
        if hasattr(data, "desk_spectral_centroid")
        else 0.0
    )

    if data.beat_position > 0:
        signals["beat_phase"] = data.beat_position % 1.0
        signals["bar_phase"] = (data.beat_position % 4) / 4.0

    if not hasattr(compositor, "_beat_pulse"):
        compositor._beat_pulse = 0.0
        compositor._prev_beat_phase = 0.0
    cur_phase = data.beat_position % 1.0
    if cur_phase < compositor._prev_beat_phase and data.beat_position > 0:
        compositor._beat_pulse = 1.0
    compositor._beat_pulse *= 0.85
    compositor._prev_beat_phase = cur_phase
    # Only use beat-phase-derived pulse when direct audio capture is unavailable
    if not hasattr(compositor, "_audio_capture"):
        signals["beat_pulse"] = compositor._beat_pulse

    if data.heart_rate_bpm > 0:
        signals["heart_rate"] = min(1.0, max(0.0, (data.heart_rate_bpm - 40) / 140.0))
    signals["stress"] = 1.0 if data.stress_elevated else 0.0

    from agents.effect_graph.visual_governance import compute_perlin_drift

    signals["perlin_drift"] = compute_perlin_drift(t, data.desk_energy)

    updates = modulator.tick(signals)
    for (node_id, param), value in updates.items():
        compositor._on_graph_params_changed(node_id, {param: value})


def tick_slot_pipeline(compositor: Any, t: float) -> None:
    """Push time/resolution to active slots."""
    if not compositor._slot_pipeline:
        return

    # Task #122 DEGRADED mode: pin every slot to passthrough so any
    # shader-compile errors that would otherwise surface during a
    # live-change stay invisible. The pin is idempotent — the byte-
    # identical diff check in the slot-pipeline path avoids Rust-side
    # recompiles once the slots are already pinned.
    if _degraded_active():
        _pin_slots_to_passthrough(compositor)
        return

    # A+ Stage 2 audit B3 fix (2026-04-17): width/height pulled from
    # config module constants rather than hardcoded 1920/1080.
    # Shaders that use width/height uniforms for UV normalization or
    # aspect-ratio-dependent math compute correctly at whichever canvas
    # size the compositor is currently using (1280x720 default).
    from .config import OUTPUT_HEIGHT, OUTPUT_WIDTH

    time_uniforms = {
        "time": t % 600.0,
        "width": float(OUTPUT_WIDTH),
        "height": float(OUTPUT_HEIGHT),
    }
    for i, node_type in enumerate(compositor._slot_pipeline.slot_assignments):
        if node_type is None:
            continue
        defn = (
            compositor._slot_pipeline._registry.get(node_type)
            if compositor._slot_pipeline._registry
            else None
        )
        if defn and defn.glsl_source:
            # Drop #43 FXT-1: cache the set of implicit time-uniform
            # keys this shader references on defn itself. Without the
            # cache, every tick does 3 string-contains scans × 24 slots
            # × 30 fps = 2160 scans/sec. The result is deterministic in
            # defn.glsl_source, so a single attribute on defn suffices.
            implicit_keys: tuple[str, ...] | None = getattr(
                defn, "_hapax_implicit_uniform_keys", None
            )
            if implicit_keys is None:
                implicit_keys = tuple(k for k in time_uniforms if f"u_{k}" in defn.glsl_source)
                defn._hapax_implicit_uniform_keys = implicit_keys
            if implicit_keys:
                implicit = {k: time_uniforms[k] for k in implicit_keys}
                compositor._slot_pipeline._slot_base_params[i].update(implicit)
                if compositor._slot_pipeline._slot_is_temporal[i]:
                    compositor._slot_pipeline._apply_glfeedback_uniforms(i)
                else:
                    compositor._slot_pipeline._set_uniforms(
                        i, compositor._slot_pipeline._slot_base_params[i]
                    )
