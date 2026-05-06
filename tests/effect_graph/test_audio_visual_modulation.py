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


# ── No global flash/dim/pulse ban (operator directive 2026-05-06) ──────────
#
# `~/.claude/projects/-home-hapax-projects/memory/feedback_no_global_flash_dim_pulse.md`
#
# Audio modulations may NOT target params that produce a global frame-luma
# effect. ALLOW list: vibration (slice/displacement), color modulation
# (hue/sat/chroma), cycling (posterize/dither/palette), luminescences on
# specific geometries, warping of non-global areas, specific geometries.
# BAN list (any audio→ binding to these on any preset is a CI-blocking error):

BANNED_GLOBAL_LUMA_PARAMS: frozenset[str] = frozenset(
    {
        # global frame-luma multipliers
        "brightness",
        "intensity",
        # global opacity / alpha
        "opacity",
        "alpha",
        "master_opacity",
        # global vignette luma multiply (radius is allowed — that's spatial)
        "strength",
        # generic catchalls operators have used as flash channels
        "flash",
        "dim",
        "pulse",
    }
)

# Audio-source prefixes that count as audio reactivity (not perception or
# stimmung — those have their own governance paths).
AUDIO_SOURCE_PREFIXES: tuple[str, ...] = (
    "audio_",
    "music.",
    "audio.",
)


def _is_audio_source(source: str) -> bool:
    return any(source.startswith(p) for p in AUDIO_SOURCE_PREFIXES)


# Grandfathered violations from before the directive existed. Each entry
# has a known retargeting path that requires shader-level work (adding
# allow-list params to the corresponding WGSL shader). Tracked in cc-task
# `extend-banned-luma-shaders-with-allow-list-params`. NEW violations
# beyond this set must fail the gate.
KNOWN_BANNED_VIOLATIONS: frozenset[tuple[str, str, str]] = frozenset(
    {
        # (source, node, param)
        # ── from _default_modulations.json ──
        ("music.hat_onset", "noise_overlay", "intensity"),
        ("music.kick_onset", "glitch_block", "intensity"),
        ("music.rms", "scanlines", "opacity"),
        ("music.kick_onset", "fisheye", "strength"),
        ("music.rms", "thermal", "intensity"),
        ("broadcast.rms", "trail", "opacity"),
        # ── from per-preset modulations (audio_* sources) ──
        ("audio_energy", "noise", "intensity"),
        ("audio_energy", "grain_grit", "intensity"),
        ("audio_energy", "noise_static", "intensity"),
        ("audio_beat", "emboss_brushed", "strength"),
        ("audio_energy", "noise_dense", "intensity"),
        ("audio_energy", "noise_drone", "intensity"),
        ("audio_beat", "bloom", "alpha"),
        ("audio_beat", "fisheye", "strength"),
        ("audio_energy", "grain_print", "intensity"),
        ("audio_energy", "grain_paper", "intensity"),
        ("audio_energy", "grain_tape", "intensity"),
        ("audio_rms", "trail", "opacity"),
        ("audio_energy", "noise_dust", "intensity"),
        ("audio_energy", "grain_xerox", "intensity"),
    }
)


def test_no_preset_modulation_targets_banned_global_luma_param() -> None:
    """Per operator directive 2026-05-06: zero global flash/dim/pulse from
    audio reactivity. Scans every `presets/*.json` modulations array and
    fails CI if any audio-driven binding targets a banned param outside
    the grandfathered `KNOWN_BANNED_VIOLATIONS` set.

    Build path (per never-remove): when this test fails on a NEW binding,
    the fix is to re-target the modulation to an ALLOW-list axis
    (vibration, color, cycling, luminescence-on-specific-geom,
    warp-non-global). Do NOT delete — replace with a non-banned target.
    For grandfathered violations, the retargeting path requires shader
    extension (adding allow-list params to the corresponding WGSL).
    """
    presets_dir = REPO_ROOT / "presets"
    violations: list[str] = []
    for preset_path in sorted(presets_dir.glob("*.json")):
        try:
            payload = json.loads(preset_path.read_text())
        except json.JSONDecodeError as e:
            violations.append(f"{preset_path.name}: invalid JSON ({e})")
            continue
        for row in payload.get("modulations", []) or []:
            if not isinstance(row, dict):
                continue
            source = row.get("source", "")
            param = row.get("param", "")
            node = row.get("node", "")
            if not isinstance(source, str) or not isinstance(param, str):
                continue
            if not _is_audio_source(source) and not source.startswith("broadcast."):
                continue
            if param in BANNED_GLOBAL_LUMA_PARAMS:
                if (source, node, param) in KNOWN_BANNED_VIOLATIONS:
                    continue  # grandfathered — followup PR will retarget
                violations.append(
                    f"{preset_path.name}: {source} → {node}.{param} "
                    f"(banned: produces global flash/dim/pulse)"
                )
    assert not violations, (
        "Banned global-luma audio modulations detected. "
        "Re-target to ALLOW-list axis (vibration/color/cycling/luminescence/warp), "
        "do NOT delete:\n  " + "\n  ".join(violations)
    )


def test_default_modulations_template_obeys_global_luma_ban() -> None:
    """The `_default_modulations.json` template carries the operator's
    no-global-flash directive verbatim — its own bindings must obey it
    outside the grandfathered set.
    """
    payload = json.loads((REPO_ROOT / "presets" / "_default_modulations.json").read_text())
    violations: list[str] = []
    for row in payload.get("default_modulations", []) or []:
        if not isinstance(row, dict):
            continue
        source = row.get("source", "")
        param = row.get("param", "")
        node = row.get("node", "")
        if not isinstance(source, str) or not isinstance(param, str):
            continue
        if not _is_audio_source(source) and not source.startswith("broadcast."):
            continue
        if param in BANNED_GLOBAL_LUMA_PARAMS:
            if (source, node, param) in KNOWN_BANNED_VIOLATIONS:
                continue
            violations.append(f"{source} → {node}.{param}")
    assert not violations, (
        "_default_modulations.json contains banned global-luma audio bindings:\n  "
        + "\n  ".join(violations)
    )


def test_known_banned_violations_set_does_not_regrow() -> None:
    """The grandfathered violations set is a transitional exemption.
    Adding a new entry without operator approval is a regression — every
    new banned binding should be retargeted, not exempted. This pin
    catches accidental growth of the set."""
    # Caps the set size at the original count from 2026-05-06 audit. New
    # exemptions require an explicit operator-approved cap bump.
    assert len(KNOWN_BANNED_VIOLATIONS) <= 20, (
        f"KNOWN_BANNED_VIOLATIONS grew to {len(KNOWN_BANNED_VIOLATIONS)} — "
        "retarget the new violation to an ALLOW-list param instead of exempting."
    )


