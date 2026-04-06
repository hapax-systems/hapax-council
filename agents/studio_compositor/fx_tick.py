"""Per-frame tick subroutines for the FX chain."""

from __future__ import annotations

import time
from typing import Any


def tick_governance(compositor: Any, t: float) -> None:
    """Perception-visual governance tick."""
    if compositor._graph_runtime is None or not hasattr(compositor, "_atmospheric_selector"):
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
    stance = "nominal"
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

    time_uniforms = {"time": t % 600.0, "width": 1920.0, "height": 1080.0}
    for i, node_type in enumerate(compositor._slot_pipeline.slot_assignments):
        if node_type is None:
            continue
        defn = (
            compositor._slot_pipeline._registry.get(node_type)
            if compositor._slot_pipeline._registry
            else None
        )
        if defn and defn.glsl_source:
            implicit = {k: v for k, v in time_uniforms.items() if f"u_{k}" in defn.glsl_source}
            if implicit:
                compositor._slot_pipeline._slot_base_params[i].update(implicit)
                if compositor._slot_pipeline._slot_is_temporal[i]:
                    compositor._slot_pipeline._apply_glfeedback_uniforms(i)
                else:
                    compositor._slot_pipeline._set_uniforms(
                        i, compositor._slot_pipeline._slot_base_params[i]
                    )
