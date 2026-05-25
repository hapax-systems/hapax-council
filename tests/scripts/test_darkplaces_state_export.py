from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "darkplaces-state-export.py"
BRIDGE = REPO_ROOT / "scripts" / "darkplaces-state-bridge.sh"


def _load_exporter() -> ModuleType:
    spec = importlib.util.spec_from_file_location("darkplaces_state_export", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_darkplaces_state_export_writes_csqc_ward_text_files(tmp_path: Path) -> None:
    exporter = _load_exporter()
    game_dir = tmp_path / "game" / "data"
    shm_dir = tmp_path / "shm"
    shm_dir.mkdir()
    mode_file = tmp_path / "working-mode"
    uniforms_file = tmp_path / "uniforms.json"
    imagination_current_file = tmp_path / "imagination-current.json"
    effect_state_file = tmp_path / "entity-local-effect-state.json"
    stimmung_state_file = tmp_path / "stimmung-state.json"
    visual_chain_state_file = tmp_path / "visual-chain-state.json"
    effect_drift_state_file = tmp_path / "effect-drift-state.json"
    mode_file.write_text("rnd\n", encoding="utf-8")
    (shm_dir / "stimmung-energy.txt").write_text("0.62\n", encoding="utf-8")
    (shm_dir / "voice-active.txt").write_text("1\n", encoding="utf-8")
    _write_json(
        uniforms_file,
        {
            "content.salience": 0.31,
            "fb.trace_strength": 0.22,
            "content.intensity": 0.42,
            "signal.ward_fx_temporal_boost": 0.18,
            "signal.ward_fx_spectral_boost": 0.14,
            "post.vignette_strength": 0.19,
            "signal.color_warmth": 0.16,
            "slot1_3_emboss.strength": 0.12,
            "slot3_1_invert.strength": 0.21,
            "slot3_2_grain_bump.strength": 0.37,
            "slot4_1_colorgrade.sepia": 0.23,
            "signal.homage_custom_4_0": 0.44,
            "signal.homage_custom_4_2": 0.55,
            "signal.homage_custom_4_3": 0.66,
        },
    )
    _write_json(
        imagination_current_file,
        {
            "id": "abc123",
            "timestamp": 100.0,
            "salience": 0.7,
            "continuation": True,
            "material": "fire",
            "narrative": "The scroom intends itself as a warm field.",
            "dimensions": {
                "intensity": 0.8,
                "tension": 0.5,
                "depth": 0.9,
                "coherence": 0.6,
                "degradation": 0.1,
                "diffusion": 0.3,
                "spectral_color": 0.4,
                "temporal_distortion": 0.2,
                "pitch_displacement": 0.7,
            },
        },
    )
    _write_json(
        effect_state_file,
        {
            "schema": "entity-local-effect-state-v1",
            "route": {
                "route_authority": "entity_local_source_plane",
                "fourth_wall_policy": "forbid_foreground_overlay",
                "output_plane_route": False,
            },
            "active_effects": [
                {"effect": "mirror", "mix": 0.42},
                {"effect": "warp", "mix": 0.61},
                {"effect": "mirror", "mix": 0.31},
                {"effect": "slitscan", "mix": 1.0},
            ],
        },
    )

    _write_json(
        shm_dir / "active-segment.json",
        {
            "role": "rant",
            "topic": "Rant on the importance of rigorous governance in AI agent development",
            "current_beat_index": 1,
            "total_beats": 4,
            "beat_progress": 0.5,
            "current_beat_text": "Escalate the argument with concrete evidence and explicit failure predicates.",
            "source_refs": [
                "rag:governance_importance",
                "profile-facts:evidence_based_decision_making",
                "profile-facts:vague_language_risks",
            ],
        },
    )
    _write_json(
        shm_dir / "active_wards.json",
        {"ward_ids": ["programme_banner", "segment_content", "pressure_gauge"]},
    )
    _write_json(
        shm_dir / "ward-properties.json",
        {
            "wards": {
                "album": {
                    "alpha": 0.4,
                    "z_plane": "beyond-scrim",
                    "z_index_float": 0.5,
                    "drift_type": "none",
                    "front_state": "integrated",
                },
                "pressure_gauge": {
                    "alpha": 0.75,
                    "z_plane": "surface-scrim",
                    "z_index_float": 0.8,
                    "glow_radius_px": 32,
                    "scale": 1.07,
                    "scale_bump_pct": 0.05,
                    "drift_amplitude_px": 12,
                    "drift_hz": 0.4,
                    "front_state": "fronting",
                },
            }
        },
    )
    _write_json(shm_dir / "voice-state.json", {"operator_speech_active": True})
    _write_json(
        shm_dir / "album-state.json",
        {"artist": "Radiohead", "title": "Pablo Honey"},
    )
    _write_json(
        shm_dir / "token-ledger.json",
        {"total_tokens": 14056358, "active_viewers": 1},
    )
    _write_json(
        shm_dir / "unified-reactivity.json",
        {"blended": {"rms": 0.12, "onset": 0.34}},
    )
    _write_json(shm_dir / "homage-active.json", {"package": "quake"})
    _write_json(
        shm_dir / "homage-substrate-package.json",
        {"package": "quake", "palette_accent_hue_deg": 180.0, "custom_slot_index": 4},
    )
    _write_json(
        shm_dir / "visual-layer-state.json",
        {
            "display_state": "alert",
            "zone_opacities": {
                "work_tasks": 0.25,
                "health_infra": 0.40,
                "system_state": 0.10,
            },
            "signals": {
                "health_infra": [{"severity": 0.85, "title": "System failed"}],
                "system_state": [{"severity": 1.0, "title": "audience engagement: 100%"}],
            },
            "ambient_params": {
                "speed": 0.25,
                "turbulence": 0.4,
                "color_warmth": 1.0,
                "brightness": 0.25,
                "audio_energy": 0.1,
            },
            "stimmung_stance": "cautious",
            "transition": {"started_at": 0.0, "duration_s": 2.0, "style": "breathe"},
        },
    )
    _write_json(
        stimmung_state_file,
        {
            "health": {"value": 0.2},
            "resource_pressure": {"value": 0.3},
            "error_rate": {"value": 0.4},
            "grounding_quality": {"value": 0.5},
            "exploration_deficit": {"value": 0.6},
            "audience_engagement": {"value": 0.7},
            "operator_energy": {"value": 0.8},
            "physiological_coherence": {"value": 0.9},
            "audio_signal_presence": {"value": 1.0},
            "overall_stance": "seeking",
        },
    )
    _write_json(
        visual_chain_state_file,
        {
            "levels": {
                "visual_chain.intensity": 0.8,
                "visual_chain.diffusion": 0.5,
                "visual_chain.depth": 0.25,
                "visual_chain.pitch_displacement": 0.6,
                "visual_chain.temporal_distortion": 0.4,
                "visual_chain.spectral_color": 0.3,
                "visual_chain.coherence": 0.2,
            },
            "params": {
                "noise.amplitude": 0.5,
                "drift.amplitude": 0.4,
                "color.hue_rotate": 35.0,
                "fb.decay": 0.075,
                "post.vignette_strength": -0.25,
            },
            "timestamp": 100.0,
        },
    )
    _write_json(
        effect_drift_state_file,
        {
            "pass_count": 4,
            "non_neutral_pass_count": 2,
            "passes": [
                {
                    "node_id": "color",
                    "non_neutral": True,
                    "max_delta": 6.0,
                    "parameter_regions": [{"param": "hue_rotate", "region": "high"}],
                },
                {"node_id": "drift", "non_neutral": False, "max_delta": 3.0},
                {"node_id": "fb", "non_neutral": True, "max_delta": 2.0},
                {"node_id": "post", "non_neutral": False, "max_delta": 0.5},
            ],
        },
    )

    exporter.export_state(
        game_dir,
        shm_dir,
        mode_file,
        uniforms_file,
        imagination_current_file=imagination_current_file,
        entity_local_effect_state_file=effect_state_file,
        stimmung_state_file=stimmung_state_file,
        visual_chain_state_file=visual_chain_state_file,
        effect_drift_state_file=effect_drift_state_file,
    )

    assert (game_dir / "working-mode.txt").read_text(encoding="utf-8").strip() == "rnd"
    assert (game_dir / "ward-01.txt").read_text(encoding="utf-8").strip() == "14056K TOK / 1 VIEW"
    assert (game_dir / "ward-02.txt").read_text(
        encoding="utf-8"
    ).strip() == "Radiohead / Pablo Honey"
    assert (game_dir / "ward-03.txt").read_text(encoding="utf-8").strip() == "STREAM 36 WARDS"
    assert (game_dir / "ward-04.txt").read_text(encoding="utf-8").strip() == "AOA RMS 012% ON 034%"
    assert (game_dir / "ward-06.txt").read_text(
        encoding="utf-8"
    ).strip() == "ACT PROGRAMME_BANNER SEGMENT_CONTENT PRESSU>"
    assert (game_dir / "ward-12.txt").read_text(encoding="utf-8").strip() == "VOICE ON / 36 WARDS"
    assert "BEAT 050%" in (game_dir / "ward-13.txt").read_text(encoding="utf-8")
    assert "RANT:" in (game_dir / "ward-21.txt").read_text(encoding="utf-8")
    assert (game_dir / "ward-28.txt").read_text(encoding="utf-8").strip() == "BEAT 2/4 050%"
    assert "Escalate the argument" in (game_dir / "ward-34.txt").read_text(encoding="utf-8")
    assert (game_dir / "ward-36.txt").read_text(encoding="utf-8").strip() == "IRDUAL 012%/034%"
    assert len(list(game_dir.glob("ward-[0-9][0-9].txt"))) == 36
    assert (game_dir / "ward-active-01.txt").read_text(encoding="utf-8").strip() == "0.0000"
    assert (game_dir / "ward-active-13.txt").read_text(encoding="utf-8").strip() == "1.0000"
    assert (game_dir / "ward-active-21.txt").read_text(encoding="utf-8").strip() == "1.0000"
    assert (game_dir / "ward-active-34.txt").read_text(encoding="utf-8").strip() == "1.0000"
    assert len(list(game_dir.glob("ward-active-*.txt"))) == 36
    assert (game_dir / "ward-alpha-02.txt").read_text(encoding="utf-8").strip() == "0.4000"
    assert (game_dir / "ward-depth-02.txt").read_text(encoding="utf-8").strip() == "0.2000"
    assert (game_dir / "ward-presence-02.txt").read_text(encoding="utf-8").strip() == "0.0000"
    assert (game_dir / "ward-glow-13.txt").read_text(encoding="utf-8").strip() == "0.5000"
    assert (game_dir / "ward-scale-13.txt").read_text(encoding="utf-8").strip() == "0.4000"
    assert (game_dir / "ward-front-13.txt").read_text(encoding="utf-8").strip() == "0.7000"
    assert (game_dir / "ward-drift-13.txt").read_text(encoding="utf-8").strip() == "0.7000"
    assert (game_dir / "ward-presence-13.txt").read_text(encoding="utf-8").strip() == "0.7700"
    assert (game_dir / "ward-property-count.txt").read_text(encoding="utf-8").strip() == "2.0000"
    assert (game_dir / "ward-property-route.txt").read_text(
        encoding="utf-8"
    ).strip() == "IN_SCROOM_FISHBOWL_WARD_PROPERTIES"
    assert len(list(game_dir.glob("ward-presence-*.txt"))) == 36
    assert (game_dir / "active-wards-line.txt").read_text(
        encoding="utf-8"
    ).strip() == "36 IN-SCROOM WARDS"
    assert (game_dir / "reverie-salience.txt").read_text(encoding="utf-8").strip() == "0.3100"
    assert (game_dir / "reverie-trace.txt").read_text(encoding="utf-8").strip() == "0.2200"
    assert (game_dir / "reverie-temporal.txt").read_text(encoding="utf-8").strip() == "0.1800"
    assert (game_dir / "reverie-spectral.txt").read_text(encoding="utf-8").strip() == "0.1400"
    assert (game_dir / "reverie-material.txt").read_text(encoding="utf-8").strip() == "0.3700"
    assert (game_dir / "reverie-inversion.txt").read_text(encoding="utf-8").strip() == "0.2100"
    assert (game_dir / "reverie-aperture.txt").read_text(encoding="utf-8").strip() == "0.1900"
    assert (game_dir / "reverie-thermal.txt").read_text(encoding="utf-8").strip() == "0.2300"
    assert (game_dir / "audio-rms.txt").read_text(encoding="utf-8").strip() == "0.1200"
    assert (game_dir / "audio-onset.txt").read_text(encoding="utf-8").strip() == "0.3400"
    assert (game_dir / "homage-package.txt").read_text(encoding="utf-8").strip() == "quake"
    assert (game_dir / "homage-substrate-package.txt").read_text(
        encoding="utf-8"
    ).strip() == "quake"
    assert (game_dir / "homage-quake-active.txt").read_text(encoding="utf-8").strip() == "1.0000"
    assert (game_dir / "homage-transition-energy.txt").read_text(
        encoding="utf-8"
    ).strip() == "0.4400"
    assert (game_dir / "homage-accent-hue.txt").read_text(encoding="utf-8").strip() == "0.5000"
    assert (game_dir / "homage-signature-intensity.txt").read_text(
        encoding="utf-8"
    ).strip() == "0.5500"
    assert (game_dir / "homage-rotation-phase.txt").read_text(encoding="utf-8").strip() == "0.6600"
    assert (game_dir / "aoa-pane-signal-01.txt").read_text(encoding="utf-8").strip() == "0.6200"
    assert (game_dir / "aoa-pane-signal-03.txt").read_text(encoding="utf-8").strip() == "0.0833"
    assert (game_dir / "aoa-pane-signal-04.txt").read_text(encoding="utf-8").strip() == "1.0000"
    assert (game_dir / "aoa-pane-signal-10.txt").read_text(encoding="utf-8").strip() == "1.0000"
    assert len(list(game_dir.glob("aoa-pane-signal-*.txt"))) == 10
    assert (game_dir / "local-effect-01.txt").read_text(encoding="utf-8").strip() == "0.4200"
    assert (game_dir / "local-effect-03.txt").read_text(encoding="utf-8").strip() == "0.6100"
    assert (game_dir / "local-effect-08.txt").read_text(encoding="utf-8").strip() == "0.0000"
    assert (game_dir / "local-effect-count.txt").read_text(encoding="utf-8").strip() == "2.0000"
    assert (game_dir / "local-effect-route.txt").read_text(
        encoding="utf-8"
    ).strip() == "ENTITY_LOCAL_SOURCE_PLANE"
    assert len(list(game_dir.glob("local-effect-[0-9][0-9].txt"))) == 11
    assert (game_dir / "visual-zone-01.txt").read_text(encoding="utf-8").strip() == "0.2500"
    assert (game_dir / "visual-zone-02.txt").read_text(encoding="utf-8").strip() == "0.8500"
    assert (game_dir / "visual-zone-03.txt").read_text(encoding="utf-8").strip() == "1.0000"
    assert (game_dir / "visual-display-state.txt").read_text(encoding="utf-8").strip() == "0.8500"
    assert (game_dir / "visual-stance.txt").read_text(encoding="utf-8").strip() == "0.5500"
    assert (game_dir / "visual-ambient-speed.txt").read_text(encoding="utf-8").strip() == "0.5000"
    assert (game_dir / "visual-ambient-turbulence.txt").read_text(
        encoding="utf-8"
    ).strip() == "0.4000"
    assert (game_dir / "visual-transition-progress.txt").read_text(
        encoding="utf-8"
    ).strip() == "1.0000"
    assert (game_dir / "stimmung-health.txt").read_text(encoding="utf-8").strip() == "0.2000"
    assert (game_dir / "stimmung-audio-presence.txt").read_text(
        encoding="utf-8"
    ).strip() == "1.0000"
    assert (game_dir / "visual-layer-route.txt").read_text(
        encoding="utf-8"
    ).strip() == "IN_SCROOM_VISUAL_LAYER_STATE"
    assert len(list(game_dir.glob("visual-zone-[0-9][0-9].txt"))) == 8
    assert (game_dir / "visual-chain-01.txt").read_text(encoding="utf-8").strip() == "0.8000"
    assert (game_dir / "visual-chain-02.txt").read_text(encoding="utf-8").strip() == "0.0000"
    assert (game_dir / "visual-chain-03.txt").read_text(encoding="utf-8").strip() == "0.5000"
    assert (game_dir / "visual-chain-noise.txt").read_text(encoding="utf-8").strip() == "0.5000"
    assert (game_dir / "visual-chain-drift.txt").read_text(encoding="utf-8").strip() == "0.5000"
    assert (game_dir / "visual-chain-color.txt").read_text(encoding="utf-8").strip() == "0.5000"
    assert (game_dir / "visual-chain-feedback.txt").read_text(encoding="utf-8").strip() == "0.5000"
    assert (game_dir / "visual-chain-param-pressure.txt").read_text(
        encoding="utf-8"
    ).strip() == "0.8000"
    assert (game_dir / "effect-drift-pass-count.txt").read_text(
        encoding="utf-8"
    ).strip() == "0.8000"
    assert (game_dir / "effect-drift-active-ratio.txt").read_text(
        encoding="utf-8"
    ).strip() == "0.5000"
    assert (game_dir / "effect-drift-tonal.txt").read_text(encoding="utf-8").strip() == "0.6000"
    assert (game_dir / "effect-drift-temporal.txt").read_text(encoding="utf-8").strip() == "0.2000"
    assert (game_dir / "effect-drift-route.txt").read_text(
        encoding="utf-8"
    ).strip() == "IN_SCROOM_EFFECT_DRIFT_STATE"
    assert len(list(game_dir.glob("visual-chain-[0-9][0-9].txt"))) == 9
    assert (game_dir / "imagination-salience.txt").read_text(encoding="utf-8").strip() == "0.7000"
    assert (game_dir / "imagination-continuation.txt").read_text(
        encoding="utf-8"
    ).strip() == "1.0000"
    assert (game_dir / "imagination-material.txt").read_text(encoding="utf-8").strip() == "0.2500"
    assert (game_dir / "imagination-dim-01.txt").read_text(encoding="utf-8").strip() == "0.8000"
    assert (game_dir / "imagination-dim-03.txt").read_text(encoding="utf-8").strip() == "0.9000"
    assert (game_dir / "imagination-dim-09.txt").read_text(encoding="utf-8").strip() == "0.7000"
    assert (game_dir / "imagination-route.txt").read_text(
        encoding="utf-8"
    ).strip() == "IN_SCROOM_IMAGINATION_FRAGMENT"
    assert len(list(game_dir.glob("imagination-dim-[0-9][0-9].txt"))) == 9


def test_darkplaces_state_export_builds_entity_local_effect_scalars(tmp_path: Path) -> None:
    exporter = _load_exporter()
    effect_state_file = tmp_path / "entity-local-effect-state.json"
    _write_json(
        effect_state_file,
        {
            "schema": "entity-local-effect-state-v1",
            "active_effects": [
                {"effect": "kaleidoscope", "mix": 0.25},
                {"effect": "droste", "mix": 0.75},
                {"effect": "droste", "mix": 0.55},
                {"effect": "slitscan", "mix": 1.0},
            ],
        },
    )

    lines = exporter.build_entity_local_effect_lines(effect_state_file)

    assert (
        len(
            [
                key
                for key in lines
                if key.startswith("local-effect-")
                and key.endswith(".txt")
                and key[len("local-effect-") : len("local-effect-") + 2].isdigit()
            ]
        )
        == 11
    )
    assert lines["local-effect-02.txt"] == "0.2500"
    assert lines["local-effect-07.txt"] == "0.7500"
    assert lines["local-effect-11.txt"] == "0.0000"
    assert lines["local-effect-count.txt"] == "2.0000"
    assert lines["local-effect-route.txt"] == "ENTITY_LOCAL_SOURCE_PLANE"


def test_darkplaces_state_export_builds_ward_property_fishbowl_scalars(
    tmp_path: Path,
) -> None:
    exporter = _load_exporter()
    shm_dir = tmp_path / "shm"
    shm_dir.mkdir()
    _write_json(
        shm_dir / "ward-properties.json",
        {
            "wards": {
                "album": {
                    "alpha": 0.4,
                    "z_plane": "beyond-scrim",
                    "z_index_float": 0.5,
                    "drift_type": "none",
                },
                "pressure_gauge": {
                    "alpha": 0.75,
                    "z_plane": "surface-scrim",
                    "z_index_float": 0.8,
                    "glow_radius_px": 32,
                    "scale": 1.07,
                    "scale_bump_pct": 0.05,
                    "drift_amplitude_px": 12,
                    "drift_hz": 0.4,
                    "front_state": "fronting",
                },
            }
        },
    )

    lines = exporter.build_ward_property_lines(shm_dir)

    assert len([key for key in lines if key.startswith("ward-presence-")]) == 36
    assert lines["ward-alpha-02.txt"] == "0.4000"
    assert lines["ward-depth-02.txt"] == "0.2000"
    assert lines["ward-drift-02.txt"] == "0.0000"
    assert lines["ward-presence-02.txt"] == "0.0000"
    assert lines["ward-depth-13.txt"] == "1.0000"
    assert lines["ward-glow-13.txt"] == "0.5000"
    assert lines["ward-scale-13.txt"] == "0.4000"
    assert lines["ward-front-13.txt"] == "0.7000"
    assert lines["ward-drift-13.txt"] == "0.7000"
    assert lines["ward-presence-13.txt"] == "0.7700"
    assert lines["ward-property-count.txt"] == "2.0000"
    assert lines["ward-property-route.txt"] == "IN_SCROOM_FISHBOWL_WARD_PROPERTIES"


def test_darkplaces_state_export_builds_visual_layer_state_scalars(tmp_path: Path) -> None:
    exporter = _load_exporter()
    shm_dir = tmp_path / "shm"
    shm_dir.mkdir()
    stimmung_state_file = tmp_path / "stimmung-state.json"
    _write_json(
        shm_dir / "visual-layer-state.json",
        {
            "display_state": "alert",
            "zone_opacities": {"work_tasks": 0.25, "health_infra": 0.4},
            "signals": {
                "health_infra": [{"severity": 0.85}],
                "system_state": [{"severity": 1.0}],
            },
            "ambient_params": {
                "speed": 0.25,
                "turbulence": 0.4,
                "color_warmth": 1.0,
                "brightness": 0.25,
                "audio_energy": 0.1,
            },
            "stimmung_stance": "cautious",
        },
    )
    _write_json(
        stimmung_state_file,
        {
            "health": {"value": 0.2},
            "resource_pressure": {"value": 0.3},
            "error_rate": {"value": 0.4},
            "operator_energy": {"value": 0.8},
            "overall_stance": "seeking",
        },
    )

    lines = exporter.build_visual_layer_lines(shm_dir, stimmung_state_file)

    assert len([key for key in lines if key.startswith("visual-zone-")]) == 8
    assert lines["visual-zone-01.txt"] == "0.2500"
    assert lines["visual-zone-02.txt"] == "0.8500"
    assert lines["visual-zone-03.txt"] == "1.0000"
    assert lines["visual-display-state.txt"] == "0.8500"
    assert lines["visual-stance.txt"] == "0.5500"
    assert lines["visual-ambient-speed.txt"] == "0.5000"
    assert lines["visual-ambient-turbulence.txt"] == "0.4000"
    assert lines["stimmung-health.txt"] == "0.2000"
    assert lines["stimmung-resource.txt"] == "0.3000"
    assert lines["stimmung-error.txt"] == "0.4000"
    assert lines["stimmung-operator-energy.txt"] == "0.8000"
    assert lines["visual-layer-route.txt"] == "IN_SCROOM_VISUAL_LAYER_STATE"


def test_darkplaces_state_export_builds_visual_chain_and_effect_drift_scalars(
    tmp_path: Path,
) -> None:
    exporter = _load_exporter()
    visual_chain_state_file = tmp_path / "visual-chain-state.json"
    effect_drift_state_file = tmp_path / "effect-drift-state.json"
    _write_json(
        visual_chain_state_file,
        {
            "levels": {
                "visual_chain.intensity": 0.8,
                "visual_chain.diffusion": 0.5,
                "visual_chain.depth": 0.25,
                "visual_chain.pitch_displacement": 0.6,
                "visual_chain.temporal_distortion": 0.4,
                "visual_chain.spectral_color": 0.3,
                "visual_chain.coherence": 0.2,
            },
            "params": {
                "noise.octaves": 1.5,
                "drift.amplitude": 0.4,
                "drift.speed": -0.10,
                "color.hue_rotate": 35.0,
                "fb.decay": 0.075,
                "post.vignette_strength": -0.25,
            },
        },
    )
    _write_json(
        effect_drift_state_file,
        {
            "pass_count": 4,
            "non_neutral_pass_count": 2,
            "passes": [
                {
                    "node_id": "color",
                    "non_neutral": True,
                    "max_delta": 6.0,
                    "parameter_regions": [{"param": "hue_rotate", "region": "high"}],
                },
                {"node_id": "drift", "non_neutral": False, "max_delta": 3.0},
                {"node_id": "fb", "non_neutral": True, "max_delta": 2.0},
                {"node_id": "edge_detect", "non_neutral": False, "max_delta": 1.0},
            ],
        },
    )

    lines = exporter.build_visual_chain_lines(visual_chain_state_file, effect_drift_state_file)

    assert (
        len([key for key in lines if key.startswith("visual-chain-") and key[13:15].isdigit()]) == 9
    )
    assert lines["visual-chain-01.txt"] == "0.8000"
    assert lines["visual-chain-02.txt"] == "0.0000"
    assert lines["visual-chain-03.txt"] == "0.5000"
    assert lines["visual-chain-noise.txt"] == "0.5000"
    assert lines["visual-chain-drift.txt"] == "0.5000"
    assert lines["visual-chain-color.txt"] == "0.5000"
    assert lines["visual-chain-feedback.txt"] == "0.5000"
    assert lines["visual-chain-aperture.txt"] == "0.2500"
    assert lines["visual-chain-param-pressure.txt"] == "0.8000"
    assert lines["effect-drift-pass-count.txt"] == "0.8000"
    assert lines["effect-drift-active-ratio.txt"] == "0.5000"
    assert lines["effect-drift-max-delta.txt"] == "0.6000"
    assert lines["effect-drift-region-count.txt"] == "0.0833"
    assert lines["effect-drift-tonal.txt"] == "0.6000"
    assert lines["effect-drift-atmospheric.txt"] == "0.0000"
    assert lines["effect-drift-temporal.txt"] == "0.2000"
    assert lines["effect-drift-edge.txt"] == "0.0000"
    assert lines["effect-drift-route.txt"] == "IN_SCROOM_EFFECT_DRIFT_STATE"


def test_darkplaces_state_export_builds_imagination_intent_scalars(
    tmp_path: Path,
) -> None:
    exporter = _load_exporter()
    imagination_current_file = tmp_path / "current.json"
    _write_json(
        imagination_current_file,
        {
            "id": "abc123",
            "timestamp": 100.0,
            "salience": 0.7,
            "continuation": True,
            "material": "earth",
            "narrative": "The scroom intends itself as embodied structure.",
            "dimensions": {
                "intensity": 0.8,
                "tension": 0.5,
                "depth": 0.9,
                "coherence": 0.6,
                "degradation": 0.1,
                "diffusion": 0.3,
                "spectral_color": 0.4,
                "temporal_distortion": 0.2,
                "pitch_displacement": 0.7,
            },
        },
    )

    lines = exporter.build_imagination_fragment_lines(imagination_current_file)

    assert len([key for key in lines if key.startswith("imagination-dim-")]) == 9
    assert lines["imagination-salience.txt"] == "0.7000"
    assert lines["imagination-continuation.txt"] == "1.0000"
    assert lines["imagination-material.txt"] == "0.5000"
    assert lines["imagination-dim-01.txt"] == "0.8000"
    assert lines["imagination-dim-03.txt"] == "0.9000"
    assert lines["imagination-dim-09.txt"] == "0.7000"
    assert lines["imagination-route.txt"] == "IN_SCROOM_IMAGINATION_FRAGMENT"


def test_darkplaces_state_export_normalizes_all_in_scroom_ward_activity() -> None:
    exporter = _load_exporter()

    assert len(exporter.WARD_EXPORTS) == 36
    assert dict(exporter.WARD_ACTIVITY_EXPORTS) == exporter.WARD_EXPORTS

    lines = exporter.build_ward_activity_lines(
        {
            "ward_ids": [
                "album_overlay",
                "sierpinski",
                "activity_header",
                "coding-session-reveal",
                "programme-banner",
                "m8-display",
                "cbip-dual-ir-displacement",
            ]
        }
    )

    assert len(lines) == 36
    assert lines["ward-active-02.txt"] == "1.0000"
    assert lines["ward-active-04.txt"] == "1.0000"
    assert lines["ward-active-06.txt"] == "1.0000"
    assert lines["ward-active-17.txt"] == "1.0000"
    assert lines["ward-active-18.txt"] == "1.0000"
    assert lines["ward-active-21.txt"] == "1.0000"
    assert lines["ward-active-36.txt"] == "1.0000"
    assert lines["ward-active-01.txt"] == "0.0000"


def test_darkplaces_state_export_writes_camera_source_scalars(tmp_path: Path) -> None:
    exporter = _load_exporter()
    shm_dir = tmp_path / "shm"
    sources_dir = tmp_path / "sources"
    shm_dir.mkdir()

    _write_json(
        shm_dir / "camera-classifications.json",
        {
            "brio-operator": {"ambient_priority": 7},
            "brio-room": {"ambient_priority": 3},
            "brio-synths": {"ambient_priority": 4},
            "c920-desk": {"ambient_priority": 5},
            "c920-room": {"ambient_priority": 8},
            "c920-overhead": {"ambient_priority": 6},
        },
    )
    fresh_dir = sources_dir / "camera-brio-operator"
    stale_dir = sources_dir / "camera-c920-room"
    fresh_dir.mkdir(parents=True)
    stale_dir.mkdir(parents=True)
    _write_json(fresh_dir / "manifest.json", {"ttl_ms": 3000})
    _write_json(stale_dir / "manifest.json", {"ttl_ms": 3000})
    (fresh_dir / "frame.rgba").write_bytes(b"rgba")
    (stale_dir / "frame.rgba").write_bytes(b"rgba")
    os.utime(fresh_dir / "frame.rgba", (99.0, 99.0))
    os.utime(stale_dir / "frame.rgba", (80.0, 80.0))

    lines = exporter.build_source_lines(shm_dir, sources_dir, now=100.0)

    assert lines["source-priority-01.txt"] == "0.7000"
    assert lines["source-priority-05.txt"] == "0.8000"
    assert lines["source-fresh-01.txt"] == "1.0000"
    assert lines["source-fresh-05.txt"] == "0.0000"
    assert lines["source-fresh-06.txt"] == "0.0000"


def test_darkplaces_state_export_builds_aoa_pane_binding_scalars(tmp_path: Path) -> None:
    exporter = _load_exporter()
    shm_dir = tmp_path / "shm"
    sources_dir = tmp_path / "sources"
    shm_dir.mkdir()
    uniforms_file = tmp_path / "uniforms.json"

    (shm_dir / "stimmung-energy.txt").write_text("0.62\n", encoding="utf-8")
    (shm_dir / "voice-active.txt").write_text("0.10\n", encoding="utf-8")
    (shm_dir / "consent-state.txt").write_text("allowed\n", encoding="utf-8")
    _write_json(
        uniforms_file,
        {
            "content.salience": 0.31,
            "fb.trace_strength": 0.44,
            "signal.homage_custom_4_0": 0.12,
            "signal.homage_custom_4_2": 0.34,
        },
    )
    _write_json(shm_dir / "unified-reactivity.json", {"blended": {"onset": 0.34}})
    _write_json(
        shm_dir / "active-segment.json",
        {"beat_progress": 0.5},
    )
    _write_json(
        shm_dir / "active_wards.json",
        {
            "ward_ids": [
                "token_pole",
                "album",
                "stream_overlay",
                "sierpinski",
                "reverie",
                "activity_header",
                "stance_indicator",
                "gem",
                "grounding_provenance_ticker",
                "impingement_cascade",
                "recruitment_candidate_panel",
                "thinking_indicator",
                "pressure_gauge",
                "activity_variety_log",
                "whos_here",
                "durf",
                "coding_session_reveal",
                "m8-display",
            ]
        },
    )
    _write_json(
        shm_dir / "camera-classifications.json",
        {
            "brio-operator": {"ambient_priority": 7},
            "c920-room": {"ambient_priority": 8},
        },
    )
    fresh_dir = sources_dir / "camera-brio-operator"
    fresh_dir.mkdir(parents=True)
    _write_json(fresh_dir / "manifest.json", {"ttl_ms": 3000})
    (fresh_dir / "frame.rgba").write_bytes(b"rgba")
    os.utime(fresh_dir / "frame.rgba", (99.0, 99.0))

    lines = exporter.build_aoa_pane_lines(shm_dir, uniforms_file, sources_dir, now=100.0)

    assert len(lines) == 10
    assert lines["aoa-pane-signal-01.txt"] == "0.6200"
    assert lines["aoa-pane-signal-02.txt"] == "0.4400"
    assert lines["aoa-pane-signal-03.txt"] == "0.5000"
    assert lines["aoa-pane-signal-04.txt"] == "0.3400"
    assert lines["aoa-pane-signal-05.txt"] == "0.8000"
    assert lines["aoa-pane-signal-06.txt"] == "0.1667"
    assert lines["aoa-pane-signal-07.txt"] == "1.0000"
    assert lines["aoa-pane-signal-08.txt"] == "0.4000"
    assert lines["aoa-pane-signal-09.txt"] == "0.5000"
    assert lines["aoa-pane-signal-10.txt"] == "0.3400"


def test_darkplaces_state_export_builds_homage_scalars(tmp_path: Path) -> None:
    exporter = _load_exporter()
    shm_dir = tmp_path / "shm"
    shm_dir.mkdir()
    uniforms_file = tmp_path / "uniforms.json"
    _write_json(shm_dir / "homage-active.json", {"package": "bitchx"})
    _write_json(
        shm_dir / "homage-substrate-package.json",
        {"package": "quake", "palette_accent_hue_deg": 270.0, "custom_slot_index": 4},
    )
    _write_json(
        uniforms_file,
        {
            "signal.homage_custom_4_0": 0.12,
            "signal.homage_custom_4_2": 0.34,
            "signal.homage_custom_4_3": 0.56,
        },
    )

    lines = exporter.build_homage_lines(shm_dir, uniforms_file)

    assert lines["homage-package.txt"] == "bitchx"
    assert lines["homage-substrate-package.txt"] == "quake"
    assert lines["homage-quake-active.txt"] == "1.0000"
    assert lines["homage-transition-energy.txt"] == "0.1200"
    assert lines["homage-accent-hue.txt"] == "0.7500"
    assert lines["homage-signature-intensity.txt"] == "0.3400"
    assert lines["homage-rotation-phase.txt"] == "0.5600"


def test_darkplaces_state_bridge_delegates_to_exporter() -> None:
    body = BRIDGE.read_text(encoding="utf-8")

    assert "darkplaces-state-export.py" in body
    assert "--game-dir" in body
    assert "--uniforms-file" in body
    assert "Keep the original minimal bridge alive" in body


def test_darkplaces_state_export_rejects_bad_arguments_cleanly() -> None:
    result = subprocess.run(
        [str(SCRIPT), "--not-a-real-option"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
