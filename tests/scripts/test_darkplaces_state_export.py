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
    shader_plan_file = tmp_path / "shader-plan.json"
    gem_recruitment_file = tmp_path / "gem-recruitment.json"
    gem_frames_file = tmp_path / "gem-frames.json"
    legacy_gem_frames_file = tmp_path / "legacy-gem-frames.json"
    recent_impingements_file = tmp_path / "recent-impingements.json"
    recent_recruitment_file = tmp_path / "recent-recruitment.json"
    daimonion_consent_file = tmp_path / "daimonion-consent.json"
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
        shader_plan_file,
        {
            "version": 2,
            "targets": {
                "main": {
                    "passes": [
                        {
                            "node_id": "color",
                            "shader": "colorgrade.wgsl",
                            "type": "render",
                            "uniforms": {"brightness": 1.05, "saturation": 1.1},
                            "param_order": ["brightness", "saturation"],
                        },
                        {
                            "node_id": "drift",
                            "shader": "drift.wgsl",
                            "type": "render",
                            "uniforms": {"amplitude": 0.4, "speed": 0.2, "width": 1280.0},
                            "param_order": ["amplitude", "speed"],
                        },
                        {
                            "node_id": "fb",
                            "shader": "feedback.wgsl",
                            "type": "render",
                            "temporal": True,
                            "uniforms": {"decay": 0.8},
                            "param_order": ["decay"],
                        },
                        {
                            "node_id": "post",
                            "shader": "postprocess.wgsl",
                            "type": "render",
                            "uniforms": {"vignette_strength": 0.3},
                            "param_order": ["vignette_strength"],
                        },
                    ]
                }
            },
        },
    )
    _write_json(
        gem_recruitment_file,
        {
            "capability": "gem.composition",
            "narrative": "Narrative: density-gradient glyph rooms recruit a mural.",
            "score": 0.7,
            "ttl_s": 40.0,
            "updated_at": 100.0,
            "frames_path": str(gem_frames_file),
        },
    )
    _write_json(
        gem_frames_file,
        {
            "frames": [
                {
                    "text": "density-gradient glyph rooms",
                    "hold_ms": 2000,
                    "layers": [
                        {"text": "layer one", "opacity": 0.3},
                        {"text": "layer two", "opacity": 0.9},
                        {"text": "layer three", "opacity": 0.6},
                    ],
                },
                {
                    "text": "recursive mural",
                    "hold_ms": 6000,
                    "layers": [
                        {"text": "layer four", "opacity": 1.0},
                        {"text": "layer five", "opacity": 0.8},
                        {"text": "layer six", "opacity": 0.4},
                    ],
                },
            ],
            "written_ts": 80.0,
        },
    )
    _write_json(legacy_gem_frames_file, {"frames": []})
    _write_json(
        recent_impingements_file,
        {
            "generated_at": 120.0,
            "entries": [
                {
                    "path": "trigger_novelty",
                    "value": 0.6,
                    "family": "attention.winner",
                    "source": "exploration.apperception",
                    "ts": 90.0,
                },
                {
                    "path": "reverie_prediction",
                    "value": 1.0,
                    "family": "prediction.alert",
                    "source": "reverie_prediction",
                    "ts": 119.0,
                },
            ],
        },
    )
    _write_json(
        recent_recruitment_file,
        {
            "families": {
                "transition.cut.hard": {"last_recruited_ts": 110.0, "ttl_s": 20.0},
                "gem.composition": {
                    "last_recruited_ts": 100.0,
                    "ttl_s": 40.0,
                    "score": 0.7,
                },
            },
            "updated_at": 120.0,
        },
    )
    (shm_dir / "consent-state.txt").write_text("allowed\n", encoding="utf-8")
    _write_json(
        daimonion_consent_file,
        {"phase": "no_guest", "persistence_allowed": True, "timestamp": 118.0},
    )
    _write_json(
        shm_dir / "health.json",
        {"reference": 0.8, "perception": 0.6, "error": 0.1, "timestamp": 90.0},
    )
    _write_json(
        shm_dir / "follow-mode-recommendation.json",
        {"active": True, "confidence": 0.7, "ts": 116.0, "ttl_s": 8.0},
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
        shm_dir / "segment-cue-hold.json",
        {"set_at": 118.0, "ttl_s": 4.0, "programme": "rant-governance"},
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
        {
            "artist": "Radiohead",
            "title": "Pablo Honey",
            "confidence": 0.6,
            "playing": True,
            "content_risk": "tier_4_risky",
            "timestamp": 100.0,
        },
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
        shader_plan_file=shader_plan_file,
        gem_recruitment_file=gem_recruitment_file,
        gem_frames_file=gem_frames_file,
        legacy_gem_frames_file=legacy_gem_frames_file,
        recent_impingements_file=recent_impingements_file,
        recent_recruitment_file=recent_recruitment_file,
        daimonion_consent_file=daimonion_consent_file,
        entity_local_effect_state_file=effect_state_file,
        stimmung_state_file=stimmung_state_file,
        visual_chain_state_file=visual_chain_state_file,
        effect_drift_state_file=effect_drift_state_file,
        visual_chain_fallback_state_file=tmp_path / "missing-visual-chain-fallback.json",
        effect_drift_fallback_state_file=tmp_path / "missing-effect-drift-fallback.json",
        now=120.0,
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
    assert (game_dir / "shader-plan-pass-count.txt").read_text(encoding="utf-8").strip() == "0.5000"
    assert (game_dir / "shader-plan-render-ratio.txt").read_text(
        encoding="utf-8"
    ).strip() == "1.0000"
    assert (game_dir / "shader-plan-temporal-ratio.txt").read_text(
        encoding="utf-8"
    ).strip() == "0.2500"
    assert (game_dir / "shader-plan-color.txt").read_text(encoding="utf-8").strip() == "0.5500"
    assert (game_dir / "shader-plan-motion.txt").read_text(encoding="utf-8").strip() == "0.2000"
    assert (game_dir / "shader-plan-feedback.txt").read_text(encoding="utf-8").strip() == "0.4000"
    assert (game_dir / "shader-plan-post.txt").read_text(encoding="utf-8").strip() == "0.2000"
    assert (game_dir / "shader-plan-route.txt").read_text(
        encoding="utf-8"
    ).strip() == "IN_SCROOM_SHADER_PASS_PLAN"
    assert (game_dir / "gem-recruitment-score.txt").read_text(encoding="utf-8").strip() == "0.7000"
    assert (game_dir / "gem-recruitment-fresh.txt").read_text(encoding="utf-8").strip() == "0.5000"
    assert (game_dir / "gem-frame-fresh.txt").read_text(encoding="utf-8").strip() == "0.7500"
    assert (game_dir / "gem-frame-count.txt").read_text(encoding="utf-8").strip() == "0.1667"
    assert (game_dir / "gem-layer-density.txt").read_text(encoding="utf-8").strip() == "0.5000"
    assert (game_dir / "gem-layer-opacity.txt").read_text(encoding="utf-8").strip() == "0.6667"
    assert (game_dir / "gem-hold-pressure.txt").read_text(encoding="utf-8").strip() == "1.0000"
    assert (game_dir / "gem-narrative-pressure.txt").read_text(encoding="utf-8").strip() == "0.2333"
    assert (game_dir / "gem-route.txt").read_text(
        encoding="utf-8"
    ).strip() == "IN_SCROOM_GEM_RECRUITMENT_MURAL"
    assert (game_dir / "impingement-count.txt").read_text(encoding="utf-8").strip() == "0.1333"
    assert (game_dir / "impingement-strength.txt").read_text(encoding="utf-8").strip() == "1.0000"
    assert (game_dir / "impingement-fresh.txt").read_text(encoding="utf-8").strip() == "0.9833"
    assert (game_dir / "impingement-curiosity.txt").read_text(encoding="utf-8").strip() == "0.6000"
    assert (game_dir / "impingement-reverie-alert.txt").read_text(
        encoding="utf-8"
    ).strip() == "1.0000"
    assert (game_dir / "recruitment-family-count.txt").read_text(
        encoding="utf-8"
    ).strip() == "0.1667"
    assert (game_dir / "recruitment-fresh-ratio.txt").read_text(
        encoding="utf-8"
    ).strip() == "1.0000"
    assert (game_dir / "recruitment-score.txt").read_text(encoding="utf-8").strip() == "0.7000"
    assert (game_dir / "recruitment-transition-pressure.txt").read_text(
        encoding="utf-8"
    ).strip() == "0.5000"
    assert (game_dir / "recruitment-studio-pressure.txt").read_text(
        encoding="utf-8"
    ).strip() == "0.7000"
    assert (game_dir / "impingement-recruitment-route.txt").read_text(
        encoding="utf-8"
    ).strip() == "IN_SCROOM_IMPINGEMENT_RECRUITMENT_FIELD"
    assert (game_dir / "programme-role.txt").read_text(encoding="utf-8").strip() == "0.2800"
    assert (game_dir / "programme-beat-progress.txt").read_text(
        encoding="utf-8"
    ).strip() == "0.5000"
    assert (game_dir / "programme-beat-index.txt").read_text(encoding="utf-8").strip() == "0.5000"
    assert (game_dir / "programme-duration-pressure.txt").read_text(
        encoding="utf-8"
    ).strip() == "0.0000"
    assert (game_dir / "programme-source-pressure.txt").read_text(
        encoding="utf-8"
    ).strip() == "0.5000"
    assert (game_dir / "programme-asset-pressure.txt").read_text(
        encoding="utf-8"
    ).strip() == "0.0000"
    assert (game_dir / "programme-affordance-pressure.txt").read_text(
        encoding="utf-8"
    ).strip() == "0.0000"
    assert (game_dir / "programme-cue-hold.txt").read_text(encoding="utf-8").strip() == "0.5000"
    assert (game_dir / "programme-segment-route.txt").read_text(
        encoding="utf-8"
    ).strip() == "IN_SCROOM_PROGRAMME_SEGMENT_FIELD"
    assert (game_dir / "live-token-pressure.txt").read_text(encoding="utf-8").strip() == "1.0000"
    assert (game_dir / "live-viewer-pressure.txt").read_text(encoding="utf-8").strip() == "0.1000"
    assert (game_dir / "live-token-burst.txt").read_text(encoding="utf-8").strip() == "0.0000"
    assert (game_dir / "live-album-confidence.txt").read_text(encoding="utf-8").strip() == "0.6000"
    assert (game_dir / "live-album-fresh.txt").read_text(encoding="utf-8").strip() == "0.9944"
    assert (game_dir / "live-album-playing.txt").read_text(encoding="utf-8").strip() == "1.0000"
    assert (game_dir / "live-album-risk.txt").read_text(encoding="utf-8").strip() == "0.9200"
    assert (game_dir / "live-voice-active.txt").read_text(encoding="utf-8").strip() == "1.0000"
    assert (game_dir / "live-context-route.txt").read_text(
        encoding="utf-8"
    ).strip() == "IN_SCROOM_LIVE_CONTEXT_FIELD"
    assert (game_dir / "governance-consent-allowed.txt").read_text(
        encoding="utf-8"
    ).strip() == "1.0000"
    assert (game_dir / "governance-persistence-allowed.txt").read_text(
        encoding="utf-8"
    ).strip() == "1.0000"
    assert (game_dir / "governance-health-reference.txt").read_text(
        encoding="utf-8"
    ).strip() == "0.8000"
    assert (game_dir / "governance-health-perception.txt").read_text(
        encoding="utf-8"
    ).strip() == "0.6000"
    assert (game_dir / "governance-health-error.txt").read_text(
        encoding="utf-8"
    ).strip() == "0.1000"
    assert (game_dir / "governance-health-fresh.txt").read_text(
        encoding="utf-8"
    ).strip() == "0.9000"
    assert (game_dir / "governance-follow-active.txt").read_text(
        encoding="utf-8"
    ).strip() == "1.0000"
    assert (game_dir / "governance-follow-confidence.txt").read_text(
        encoding="utf-8"
    ).strip() == "0.7000"
    assert (game_dir / "governance-follow-fresh.txt").read_text(
        encoding="utf-8"
    ).strip() == "0.5000"
    assert (game_dir / "governance-health-route.txt").read_text(
        encoding="utf-8"
    ).strip() == "IN_SCROOM_GOVERNANCE_HEALTH_FIELD"
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
    assert (game_dir / "effect-drift-source.txt").read_text(
        encoding="utf-8"
    ).strip() == "primary-stale-or-noncanonical"
    assert (game_dir / "effect-drift-real-source.txt").read_text(
        encoding="utf-8"
    ).strip() == "0.0000"
    assert (game_dir / "visual-chain-source.txt").read_text(encoding="utf-8").strip() == "canonical"
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
    assert lines["ward-property-active-ratio.txt"] == "0.0556"
    assert lines["ward-property-depth-pressure.txt"] == "1.0000"
    assert lines["ward-property-glow-pressure.txt"] == "0.5000"
    assert lines["ward-property-front-pressure.txt"] == "0.7000"
    assert lines["ward-property-drift-pressure.txt"] == "0.7000"
    assert lines["ward-property-presence-pressure.txt"] == "0.7700"
    assert lines["ward-property-fishbowl-pressure.txt"] == "1.0000"
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

    lines = exporter.build_visual_chain_lines(
        visual_chain_state_file,
        effect_drift_state_file,
        visual_chain_fallback_state_file=tmp_path / "missing-visual-chain-fallback.json",
        effect_drift_fallback_state_file=tmp_path / "missing-effect-drift-fallback.json",
    )

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
    assert lines["effect-drift-mode-tonal.txt"] == "0.1000"
    assert lines["effect-drift-mode-temporal.txt"] == "0.9800"
    assert lines["effect-drift-route.txt"] == "IN_SCROOM_EFFECT_DRIFT_STATE"
    assert lines["effect-drift-source.txt"] == "primary-stale-or-noncanonical"
    assert lines["effect-drift-real-source.txt"] == "0.0000"
    assert lines["visual-chain-source.txt"] == "canonical"


def test_darkplaces_state_export_prefers_expressive_visual_chain_fallback(
    tmp_path: Path,
) -> None:
    exporter = _load_exporter()
    visual_chain_state_file = tmp_path / "visual-chain-state.json"
    visual_chain_fallback_state_file = tmp_path / "screwm-visual-chain-state.json"
    effect_drift_state_file = tmp_path / "effect-drift-state.json"
    _write_json(
        visual_chain_state_file,
        {
            "levels": {
                "visual_chain.intensity": 0.9,
                "visual_chain.coherence": 0.3,
            },
            "params": {
                "noise.amplitude": 0.25,
                "drift.amplitude": 0.0,
                "drift.speed": 0.0,
                "color.hue_rotate": 0.0,
                "color.saturation": 0.0,
                "color.brightness": 0.0,
            },
        },
    )
    _write_json(
        visual_chain_fallback_state_file,
        {
            "levels": {
                "visual_chain.intensity": 0.7,
                "visual_chain.temporal_distortion": 0.6,
                "visual_chain.spectral_color": 0.5,
            },
            "params": {
                "drift.amplitude": 0.4,
                "drift.speed": 0.25,
                "color.hue_rotate": 35.0,
                "color.saturation": 0.3,
                "fb.decay": 0.075,
            },
        },
    )
    _write_json(
        effect_drift_state_file,
        {
            "pass_count": 0,
            "non_neutral_pass_count": 0,
            "passes": [],
        },
    )

    lines = exporter.build_visual_chain_lines(
        visual_chain_state_file,
        effect_drift_state_file,
        visual_chain_fallback_state_file=visual_chain_fallback_state_file,
        effect_drift_fallback_state_file=tmp_path / "missing-effect-drift-fallback.json",
    )

    assert lines["visual-chain-source.txt"] == "fallback-expressive"
    assert lines["visual-chain-01.txt"] == "0.7000"
    assert lines["visual-chain-drift.txt"] == "0.5000"
    assert lines["visual-chain-color.txt"] == "0.5000"
    assert lines["visual-chain-feedback.txt"] == "0.5000"


def test_darkplaces_state_export_covers_all_effect_drift_families(tmp_path: Path) -> None:
    exporter = _load_exporter()
    visual_chain_state_file = tmp_path / "visual-chain-state.json"
    effect_drift_state_file = tmp_path / "effect-drift-state.json"
    _write_json(visual_chain_state_file, {"levels": {}, "params": {}})
    _write_json(
        effect_drift_state_file,
        {
            "passes": [
                {"node_id": "colorgrade", "non_neutral": True, "max_delta": 7.0},
                {"node_id": "fisheye", "non_neutral": True, "max_delta": 6.0},
                {"node_id": "trail", "non_neutral": True, "max_delta": 5.0},
                {"node_id": "scanlines", "non_neutral": True, "max_delta": 4.0},
                {"node_id": "edge_detect", "non_neutral": True, "max_delta": 3.0},
                {"node_id": "blend", "non_neutral": True, "max_delta": 2.0},
            ],
            "pass_count": 6,
            "non_neutral_pass_count": 6,
        },
    )

    lines = exporter.build_visual_chain_lines(
        visual_chain_state_file,
        effect_drift_state_file,
        visual_chain_fallback_state_file=tmp_path / "missing-visual-chain-fallback.json",
        effect_drift_fallback_state_file=tmp_path / "missing-effect-drift-fallback.json",
    )

    assert lines["effect-drift-tonal.txt"] == "0.7000"
    assert lines["effect-drift-atmospheric.txt"] == "0.6000"
    assert lines["effect-drift-temporal.txt"] == "0.5000"
    assert lines["effect-drift-texture.txt"] == "0.4000"
    assert lines["effect-drift-edge.txt"] == "0.3000"
    assert lines["effect-drift-compositing.txt"] == "0.2000"
    assert lines["effect-drift-mode-tonal.txt"] == "0.1000"
    assert lines["effect-drift-mode-atmospheric.txt"] == "0.4800"
    assert lines["effect-drift-mode-temporal.txt"] == "0.1500"
    assert lines["effect-drift-mode-texture.txt"] == "0.4400"
    assert lines["effect-drift-mode-edge.txt"] == "0.2000"
    assert lines["effect-drift-mode-compositing.txt"] == "0.2000"


def test_darkplaces_state_export_routes_real_slotdrift_through_full_family_vector(
    tmp_path: Path,
) -> None:
    exporter = _load_exporter()
    visual_chain_state_file = tmp_path / "visual-chain-state.json"
    effect_drift_state_file = tmp_path / "effect-drift-state.json"
    _write_json(visual_chain_state_file, {"levels": {}, "params": {}})
    _write_json(
        effect_drift_state_file,
        {
            "source_presence": {"main": True},
            "slotdrift_coverage": {"covered": 1.0},
            "passes": [
                {"node_id": "colorgrade", "non_neutral": True, "max_delta": 7.0},
                {"node_id": "fisheye", "non_neutral": True, "max_delta": 6.0},
                {"node_id": "trail", "non_neutral": True, "max_delta": 5.0},
                {"node_id": "scanlines", "non_neutral": True, "max_delta": 4.0},
                {"node_id": "edge_detect", "non_neutral": True, "max_delta": 3.0},
                {"node_id": "blend", "non_neutral": True, "max_delta": 2.0},
            ],
            "pass_count": 6,
            "non_neutral_pass_count": 6,
        },
    )

    lines = exporter.build_visual_chain_lines(
        visual_chain_state_file,
        effect_drift_state_file,
        visual_chain_fallback_state_file=tmp_path / "missing-visual-chain-fallback.json",
        effect_drift_fallback_state_file=tmp_path / "missing-effect-drift-fallback.json",
        now=15.0,
    )

    assert lines["effect-drift-source.txt"] == "slotdrift"
    assert lines["effect-drift-active-ratio.txt"] == "0.6480"
    assert lines["effect-drift-texture.txt"] == "0.4000"
    assert lines["effect-drift-edge.txt"] == "0.3000"
    assert lines["effect-drift-compositing.txt"] == "0.2000"
    assert lines["effect-drift-tonal.txt"] == "0.7000"
    assert lines["effect-drift-atmospheric.txt"] == "0.6000"
    assert lines["effect-drift-temporal.txt"] == "0.5000"


def test_darkplaces_state_export_density_grounds_drift_currency(tmp_path: Path) -> None:
    """W3: aggregate_density grounds drift currency, is_live-gated + fail-safe."""
    exporter = _load_exporter()
    visual_chain_state_file = tmp_path / "visual-chain-state.json"
    slot_drift_file = tmp_path / "effect-drift-state.json"
    nonslot_drift_file = tmp_path / "nonslot-drift-state.json"
    density_file = tmp_path / "density-field.json"
    missing_density = tmp_path / "missing-density.json"
    _write_json(visual_chain_state_file, {"levels": {}, "params": {}})
    # live slotdrift source present -> is_live True (B3 real-source gate)
    _write_json(
        slot_drift_file,
        {
            "source_presence": {"main": True},
            "slotdrift_coverage": {"covered": 1.0},
            "passes": [
                {"node_id": "colorgrade", "non_neutral": True, "max_delta": 7.0},
                {"node_id": "fisheye", "non_neutral": True, "max_delta": 6.0},
                {"node_id": "trail", "non_neutral": True, "max_delta": 5.0},
            ],
            "pass_count": 6,
            "non_neutral_pass_count": 3,
        },
    )
    # non-canonical primary -> effect_source != slotdrift -> is_live False
    _write_json(
        nonslot_drift_file,
        {
            "pass_count": 4,
            "non_neutral_pass_count": 2,
            "passes": [
                {"node_id": "color", "non_neutral": True, "max_delta": 6.0},
                {"node_id": "fb", "non_neutral": True, "max_delta": 2.0},
            ],
        },
    )
    _write_json(density_file, {"aggregate_density": 0.20, "dominant_zone": "audio"})

    def _run(density_path: Path, drift_file: Path = slot_drift_file) -> dict[str, str]:
        return exporter.build_visual_chain_lines(
            visual_chain_state_file,
            drift_file,
            visual_chain_fallback_state_file=tmp_path / "missing-visual-chain-fallback.json",
            effect_drift_fallback_state_file=tmp_path / "missing-fallback.json",
            density_field_file=density_path,
            now=15.0,
        )

    # (a) absent density -> fail-safe 0.0, no currency, no boost
    base = _run(missing_density)
    assert base["effect-drift-density.txt"] == "0.0000"
    assert base["effect-drift-density-currency.txt"] == "0.0000"

    # (b) density present + live slotdrift -> raw aggregate emitted, currency > 0,
    #     zone->family affinity, and kind_variance/active_effect_ratio raised.
    grounded = _run(density_file)
    assert grounded["effect-drift-density.txt"] == "0.2000"
    assert float(grounded["effect-drift-density-currency.txt"]) > 0.0
    assert grounded["effect-drift-density-zone.txt"] == "atmospheric"  # audio -> atmospheric
    assert float(grounded["effect-drift-kind-variance.txt"]) > float(
        base["effect-drift-kind-variance.txt"]
    )
    assert float(grounded["effect-drift-active-effect-ratio.txt"]) > float(
        base["effect-drift-active-effect-ratio.txt"]
    )

    # (c) density present + NO slotdrift -> density still emitted, but currency
    #     gated to 0 (is_live False) so the quiet-baseline invariant holds.
    nonslot = _run(density_file, drift_file=nonslot_drift_file)
    assert nonslot["effect-drift-source.txt"] != "slotdrift"
    assert nonslot["effect-drift-density.txt"] == "0.2000"
    assert nonslot["effect-drift-density-currency.txt"] == "0.0000"


def test_darkplaces_state_export_rejects_fail_closed_slotdrift(
    tmp_path: Path,
) -> None:
    exporter = _load_exporter()
    visual_chain_state_file = tmp_path / "visual-chain-state.json"
    effect_drift_state_file = tmp_path / "effect-drift-state.json"
    fallback_effect_drift_state_file = tmp_path / "screwm-effect-drift-fallback-state.json"
    _write_json(visual_chain_state_file, {"levels": {}, "params": {}})
    _write_json(
        effect_drift_state_file,
        {
            "source_presence": {
                "visible_source_count": 0,
                "minimum_effect_source_count": 4,
                "fail_closed": True,
            },
            "slotdrift_coverage": {"covered": 1.0},
            "pass_count": 1,
            "non_neutral_pass_count": 1,
            "passes": [{"node_id": "blend", "non_neutral": True, "max_delta": 9.0}],
        },
    )
    _write_json(
        fallback_effect_drift_state_file,
        {
            "source_presence": "synthetic-fallback-live-state-only",
            "fallback_state": True,
            "slotdrift_coverage": "six-family-baseline-fast-slow-eviction",
            "pass_count": 1,
            "non_neutral_pass_count": 1,
            "passes": [{"node_id": "particle_system", "non_neutral": True, "max_delta": 5.0}],
        },
    )

    lines = exporter.build_visual_chain_lines(
        visual_chain_state_file,
        effect_drift_state_file,
        visual_chain_fallback_state_file=tmp_path / "missing-visual-chain-fallback.json",
        effect_drift_fallback_state_file=fallback_effect_drift_state_file,
    )

    assert lines["effect-drift-source.txt"] == "synthetic-fallback"
    assert lines["effect-drift-real-source.txt"] == "0.0000"
    assert lines["effect-drift-compositing.txt"] == "0.0000"
    assert lines["effect-drift-texture.txt"] == "0.5000"
    assert lines["effect-drift-mode-texture.txt"] == "0.9600"


def test_darkplaces_state_export_prefers_fresh_real_slotdrift_over_fallback(
    tmp_path: Path,
) -> None:
    exporter = _load_exporter()
    visual_chain_state_file = tmp_path / "visual-chain-state.json"
    effect_drift_state_file = tmp_path / "effect-drift-state.json"
    fallback_effect_drift_state_file = tmp_path / "screwm-effect-drift-fallback-state.json"
    _write_json(
        visual_chain_state_file,
        {"levels": {"visual_chain.intensity": 0.4}, "params": {"drift.amplitude": 0.3}},
    )
    _write_json(
        effect_drift_state_file,
        {
            "source_presence": {"main": True},
            "slotdrift_coverage": {"covered": 1.0},
            "pass_count": 1,
            "non_neutral_pass_count": 1,
            "passes": [
                {"node_id": "blend", "non_neutral": True, "max_delta": 7.0},
            ],
        },
    )
    _write_json(
        fallback_effect_drift_state_file,
        {
            "source_presence": "synthetic-fallback-live-state-only",
            "slotdrift_coverage": "six-family-baseline-fast-slow-eviction",
            "pass_count": 1,
            "non_neutral_pass_count": 1,
            "passes": [
                {"node_id": "scanlines", "non_neutral": True, "max_delta": 1.0},
            ],
        },
    )

    lines = exporter.build_visual_chain_lines(
        visual_chain_state_file,
        effect_drift_state_file,
        visual_chain_fallback_state_file=tmp_path / "missing-visual-chain-fallback.json",
        effect_drift_fallback_state_file=fallback_effect_drift_state_file,
    )

    assert lines["effect-drift-source.txt"] == "slotdrift"
    assert lines["effect-drift-real-source.txt"] == "1.0000"
    assert lines["effect-drift-compositing.txt"] == "0.7000"
    assert lines["effect-drift-mode-compositing.txt"] == "0.2000"
    assert lines["effect-drift-texture.txt"] == "0.0000"


def test_darkplaces_state_export_does_not_replace_recent_slotdrift_with_synthetic_fallback(
    tmp_path: Path,
) -> None:
    exporter = _load_exporter()
    visual_chain_state_file = tmp_path / "visual-chain-state.json"
    effect_drift_state_file = tmp_path / "effect-drift-state.json"
    fallback_effect_drift_state_file = tmp_path / "screwm-effect-drift-fallback-state.json"
    _write_json(visual_chain_state_file, {"levels": {}, "params": {}})
    _write_json(
        effect_drift_state_file,
        {
            "source_presence": {"main": True},
            "slotdrift_coverage": {"covered": 1.0},
            "pass_count": 1,
            "non_neutral_pass_count": 1,
            "passes": [{"node_id": "blend", "non_neutral": True, "max_delta": 6.0}],
        },
    )
    _write_json(
        fallback_effect_drift_state_file,
        {
            "source_presence": "synthetic-fallback-live-state-only",
            "fallback_state": True,
            "slotdrift_coverage": "six-family-baseline-fast-slow-eviction",
            "pass_count": 1,
            "non_neutral_pass_count": 1,
            "passes": [{"node_id": "scanlines", "non_neutral": True, "max_delta": 2.0}],
        },
    )
    os.utime(effect_drift_state_file, (180.0, 180.0))
    os.utime(fallback_effect_drift_state_file, (200.0, 200.0))

    lines = exporter.build_visual_chain_lines(
        visual_chain_state_file,
        effect_drift_state_file,
        visual_chain_fallback_state_file=tmp_path / "missing-visual-chain-fallback.json",
        effect_drift_fallback_state_file=fallback_effect_drift_state_file,
        now=220.0,
    )

    assert lines["effect-drift-source.txt"] == "slotdrift"
    assert lines["effect-drift-real-source.txt"] == "1.0000"
    assert lines["effect-drift-compositing.txt"] == "0.6000"
    assert lines["effect-drift-mode-compositing.txt"] == "0.2000"
    assert lines["effect-drift-texture.txt"] == "0.0000"


def test_darkplaces_state_export_uses_named_synthetic_fallback_when_primary_is_not_slotdrift(
    tmp_path: Path,
) -> None:
    exporter = _load_exporter()
    visual_chain_state_file = tmp_path / "visual-chain-state.json"
    effect_drift_state_file = tmp_path / "effect-drift-state.json"
    fallback_effect_drift_state_file = tmp_path / "screwm-effect-drift-fallback-state.json"
    _write_json(visual_chain_state_file, {"levels": {}, "params": {}})
    _write_json(
        effect_drift_state_file,
        {
            "source_presence": "legacy-live-state-only",
            "slotdrift_coverage": "not-canonical",
            "passes": [{"node_id": "blend", "non_neutral": True, "max_delta": 7.0}],
            "pass_count": 1,
            "non_neutral_pass_count": 1,
        },
    )
    _write_json(
        fallback_effect_drift_state_file,
        {
            "source_presence": "synthetic-fallback-live-state-only",
            "fallback_state": True,
            "slotdrift_coverage": "six-family-baseline-fast-slow-eviction",
            "passes": [{"node_id": "scanlines", "non_neutral": True, "max_delta": 5.0}],
            "pass_count": 1,
            "non_neutral_pass_count": 1,
        },
    )

    lines = exporter.build_visual_chain_lines(
        visual_chain_state_file,
        effect_drift_state_file,
        visual_chain_fallback_state_file=tmp_path / "missing-visual-chain-fallback.json",
        effect_drift_fallback_state_file=fallback_effect_drift_state_file,
    )

    assert lines["effect-drift-source.txt"] == "synthetic-fallback"
    assert lines["effect-drift-real-source.txt"] == "0.0000"
    assert lines["effect-drift-texture.txt"] == "0.5000"
    assert lines["effect-drift-mode-texture.txt"] == "0.4400"
    assert lines["effect-drift-compositing.txt"] == "0.0000"


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
                "aoa_oarb_state",
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

    layout_lines = exporter.build_ward_activity_lines(
        {"active_ward_ids": ["programme_banner", "cbip-dual-ir-displacement"]}
    )

    assert layout_lines["ward-active-21.txt"] == "1.0000"
    assert layout_lines["ward-active-36.txt"] == "1.0000"
    assert layout_lines["ward-active-01.txt"] == "0.0000"


def test_darkplaces_state_export_falls_back_to_current_layout_active_wards(
    tmp_path: Path,
) -> None:
    exporter = _load_exporter()
    shm_dir = tmp_path / "shm"
    shm_dir.mkdir()

    _write_json(
        shm_dir / "current-layout-state.json",
        {"active_ward_ids": ["programme_banner", "segment_content"]},
    )

    active_wards = exporter._active_wards_with_layout_fallback(shm_dir)
    lines = exporter.build_ward_activity_lines(active_wards)
    ward_lines = exporter.build_ward_lines(shm_dir)

    assert active_wards["ward_ids"] == ["programme_banner", "segment_content"]
    assert lines["ward-active-21.txt"] == "1.0000"
    assert lines["ward-active-34.txt"] == "1.0000"
    assert lines["ward-active-01.txt"] == "0.0000"
    assert "PROGRAMME_BANNER SEGMENT_CONTENT" in ward_lines["06"]


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


def test_darkplaces_state_export_reads_quake_live_camera_freshness(tmp_path: Path) -> None:
    exporter = _load_exporter()
    shm_dir = tmp_path / "shm"
    sources_dir = tmp_path / "sources"
    shm_dir.mkdir()
    sources_dir.mkdir()
    _write_json(
        shm_dir / "camera-classifications.json",
        {
            "brio-operator": {"ambient_priority": 7},
            "brio-room": {"ambient_priority": 3},
        },
    )
    _write_json(
        shm_dir / "quake-live-cam-brio-room.json",
        {"updated_at": 98.0, "fps": 10, "drift_changed": True},
    )

    lines = exporter.build_source_lines(shm_dir, sources_dir, now=100.0)

    assert lines["source-fresh-01.txt"] == "0.0000"
    assert lines["source-fresh-02.txt"] == "1.0000"


def test_darkplaces_state_export_builds_content_source_manifest_scalars(
    tmp_path: Path,
) -> None:
    exporter = _load_exporter()
    sources_dir = tmp_path / "sources"
    pool_dir = sources_dir / "visual-pool-slot-0"
    overlay_dir = sources_dir / "overlay-zones"
    stale_dir = sources_dir / "stale"
    pool_dir.mkdir(parents=True)
    overlay_dir.mkdir(parents=True)
    stale_dir.mkdir(parents=True)
    _write_json(
        pool_dir / "manifest.json",
        {
            "source_id": "visual-pool-slot-0",
            "width": 640,
            "height": 360,
            "opacity": 0.9,
            "layer": 1,
            "z_order": 5,
            "ttl_ms": 0,
        },
    )
    _write_json(
        overlay_dir / "manifest.json",
        {
            "source_id": "overlay-zones",
            "width": 1280,
            "height": 720,
            "opacity": 0.5,
            "layer": 1,
            "z_order": 2,
            "ttl_ms": 3000,
        },
    )
    _write_json(
        stale_dir / "manifest.json",
        {
            "source_id": "stale",
            "width": 320,
            "height": 180,
            "opacity": 1.0,
            "layer": 1,
            "z_order": 9,
            "ttl_ms": 1000,
        },
    )
    for frame in (pool_dir / "frame.rgba", overlay_dir / "frame.rgba", stale_dir / "frame.rgba"):
        frame.write_bytes(b"rgba")
    os.utime(pool_dir / "frame.rgba", (100.0, 100.0))
    os.utime(overlay_dir / "frame.rgba", (99.0, 99.0))
    os.utime(stale_dir / "frame.rgba", (80.0, 80.0))

    lines = exporter.build_content_source_lines(sources_dir, now=100.0)

    assert lines["content-source-count.txt"] == "0.5000"
    assert lines["content-source-fresh-01.txt"] == "1.0000"
    assert lines["content-source-opacity-01.txt"] == "0.9000"
    assert lines["content-source-area-01.txt"] == "0.1111"
    assert lines["content-source-fresh-02.txt"] == "1.0000"
    assert lines["content-source-opacity-02.txt"] == "0.5000"
    assert lines["content-source-area-02.txt"] == "0.4444"
    assert lines["content-source-fresh-03.txt"] == "0.0000"
    assert lines["content-source-route.txt"] == "IN_SCROOM_CONTENT_SOURCE_MANIFESTS"


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
                "aoa_oarb_state",
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
