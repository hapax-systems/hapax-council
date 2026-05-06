"""Tests for source-role-aware audio visual modulation governance."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.effect_graph.audio_visual_modulation import (
    AntiVisualizerObservation,
    AudioVisualModulationGovernor,
    AudioVisualSourceRole,
    PublicClaimPolicy,
    VisualModulationAxis,
    infer_source_role,
)
from agents.effect_graph.modulator import UniformModulator
from agents.effect_graph.types import ModulationBinding

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_default_modulations_use_namespaced_audio_sources() -> None:
    payload = json.loads((REPO_ROOT / "presets" / "_default_modulations.json").read_text())

    # Skip _comment-only rows (header markers in the JSON for human
    # readability); only real binding rows have a `source` field.
    sources = {row["source"] for row in payload["default_modulations"] if "source" in row}

    assert "music.rms" in sources
    assert "broadcast.rms" in sources
    assert all("." in source for source in sources)


def test_source_roles_classify_required_namespaces() -> None:
    assert infer_source_role("music.rms") is AudioVisualSourceRole.PROGRAMME_MUSIC
    assert infer_source_role("operator_voice.rms") is AudioVisualSourceRole.OPERATOR_VOICE
    assert infer_source_role("tts.onset") is AudioVisualSourceRole.HAPAX_TTS
    assert infer_source_role("broadcast.rms") is AudioVisualSourceRole.BROADCAST
    assert infer_source_role("desk.onset_rate") is AudioVisualSourceRole.DESK
    assert infer_source_role("time") is AudioVisualSourceRole.NON_AUDIO


def test_legacy_alias_keeps_namespaced_music_binding_live() -> None:
    modulator = UniformModulator()
    modulator.add_binding(
        ModulationBinding(
            node="drift",
            param="amplitude",
            source="music.rms",
            scale=2.0,
            smoothing=0.0,
        )
    )

    updates = modulator.tick({"mixer_energy": 0.4})
    decision = modulator.last_modulation_decisions[0]

    assert updates[("drift", "amplitude")] == pytest.approx(0.8)
    assert decision.fallback_used is True
    assert decision.resolved_source == "mixer_energy"
    assert decision.source_role is AudioVisualSourceRole.PROGRAMME_MUSIC
    assert decision.visual_axis is VisualModulationAxis.GEOMETRY
    assert decision.public_claim_policy is PublicClaimPolicy.NO_CLAIM_AUTHORITY
    assert "source:audio-reactivity:programme_music" in decision.source_refs
    assert "health:scrim:anti_visualizer" in decision.health_refs


def test_sustained_visualizer_score_dampens_audio_geometry_only() -> None:
    governor = AudioVisualModulationGovernor(dampen_rate=0.5, hysteresis_windows=2)
    governor.observe(AntiVisualizerObservation(score=0.9, audio_rms=0.7, fresh=True))
    state = governor.observe(AntiVisualizerObservation(score=0.9, audio_rms=0.7, fresh=True))
    assert state.coupling_gain == pytest.approx(0.5)

    modulator = UniformModulator(audio_visual_governor=governor)
    modulator.add_binding(
        ModulationBinding(
            node="drift",
            param="amplitude",
            source="music.rms",
            scale=10.0,
            smoothing=0.0,
        )
    )
    modulator.add_binding(
        ModulationBinding(
            node="colorgrade",
            param="brightness",
            source="time",
            scale=10.0,
            smoothing=0.0,
        )
    )

    updates = modulator.tick({"music.rms": 0.8, "time": 0.8})

    assert updates[("drift", "amplitude")] == pytest.approx(4.0)
    assert updates[("colorgrade", "brightness")] == pytest.approx(8.0)
    assert {
        decision.binding_key: decision.coupling_gain
        for decision in modulator.last_modulation_decisions
    } == {("drift", "amplitude"): 0.5, ("colorgrade", "brightness"): 1.0}


def test_legitimate_broadband_modulation_preserves_expressive_gain() -> None:
    governor = AudioVisualModulationGovernor(dampen_rate=0.5, hysteresis_windows=2)
    state = governor.observe(AntiVisualizerObservation(score=0.18, audio_rms=0.8, fresh=True))

    modulator = UniformModulator(audio_visual_governor=governor)
    modulator.add_binding(
        ModulationBinding(
            node="drift",
            param="speed",
            source="music.rms",
            scale=2.0,
            smoothing=0.0,
        )
    )

    updates = modulator.tick({"music.rms": 0.5})

    assert state.coupling_gain == pytest.approx(1.0)
    assert updates[("drift", "speed")] == pytest.approx(1.0)


def test_recovery_window_raises_gain_after_visualizer_dampening() -> None:
    governor = AudioVisualModulationGovernor(
        dampen_rate=0.5,
        recovery_rate=1.5,
        hysteresis_windows=2,
        recovery_windows=1,
    )
    governor.observe(AntiVisualizerObservation(score=0.9, audio_rms=0.7, fresh=True))
    dampened = governor.observe(AntiVisualizerObservation(score=0.9, audio_rms=0.7, fresh=True))
    recovered = governor.observe(AntiVisualizerObservation(score=0.1, audio_rms=0.7, fresh=True))

    assert dampened.coupling_gain == pytest.approx(0.5)
    assert recovered.coupling_gain == pytest.approx(0.75)
    assert "anti_visualizer_score_recovering" in recovered.reason_codes


def test_default_recovery_rate_restores_variance_after_clean_windows() -> None:
    governor = AudioVisualModulationGovernor()
    for _ in range(3):
        dampened = governor.observe(AntiVisualizerObservation(score=0.9, audio_rms=0.7, fresh=True))

    first_clean = governor.observe(AntiVisualizerObservation(score=0.1, audio_rms=0.7, fresh=True))
    second_clean = governor.observe(AntiVisualizerObservation(score=0.1, audio_rms=0.7, fresh=True))

    assert dampened.coupling_gain == pytest.approx(0.85)
    assert first_clean.coupling_gain == pytest.approx(0.9775)
    assert second_clean.coupling_gain == pytest.approx(1.0)


def test_silence_guard_does_not_dampen_audio_geometry() -> None:
    governor = AudioVisualModulationGovernor(dampen_rate=0.5, hysteresis_windows=1)
    state = governor.observe(AntiVisualizerObservation(score=0.99, audio_rms=0.0, fresh=True))

    assert state.coupling_gain == pytest.approx(1.0)
    assert "silence_guard" in state.reason_codes


def test_stale_anti_visualizer_state_fails_closed_to_minimum_gain() -> None:
    governor = AudioVisualModulationGovernor(minimum_coupling_gain=0.3)
    state = governor.observe(AntiVisualizerObservation(score=0.1, audio_rms=0.5, fresh=False))

    modulator = UniformModulator(audio_visual_governor=governor)
    modulator.add_binding(
        ModulationBinding(
            node="drift",
            param="amplitude",
            source="music.rms",
            scale=10.0,
            smoothing=0.0,
        )
    )
    updates = modulator.tick({"music.rms": 1.0})

    assert state.coupling_gain == pytest.approx(0.3)
    assert updates[("drift", "amplitude")] == pytest.approx(3.0)
    assert "audio_geometry_gain_dampened" in modulator.last_modulation_decisions[0].reason_codes


def test_forbidden_waveform_binding_neutralizes_without_claim_authority() -> None:
    governor = AudioVisualModulationGovernor()
    modulator = UniformModulator(audio_visual_governor=governor)
    modulator.add_binding(
        ModulationBinding(
            node="waveform_ward",
            param="amplitude",
            source="music.rms",
            scale=10.0,
            offset=0.2,
            smoothing=0.0,
        )
    )

    updates = modulator.tick({"music.rms": 0.9})
    decision = modulator.last_modulation_decisions[0]

    assert updates[("waveform_ward", "amplitude")] == pytest.approx(0.2)
    assert decision.allowed is False
    assert "forbidden_visualizer_register" in decision.reason_codes
    assert decision.public_claim_policy is PublicClaimPolicy.NO_CLAIM_AUTHORITY
