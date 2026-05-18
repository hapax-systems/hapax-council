"""Tests for the visual variance state vector and novelty ledger."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, cast

import jsonschema

from shared.visual_variance_ledger import (
    ClaimStatus,
    RenderedWitnessStatus,
    VisualSelectedMove,
    VisualStateVector,
    VisualVarianceRuntimePaths,
    build_visual_state_vector_from_runtime,
    build_visual_variance_ledger,
    rendered_witness_from_path,
    score_visual_novelty,
)

NOW = 1_779_000_000.0
SCHEMA = Path(__file__).resolve().parents[2] / "schemas" / "visual-variance-ledger.schema.json"


def _vector(**overrides: object) -> VisualStateVector:
    data: dict[str, object] = {
        "programme_role": "lecture",
        "programme_format": "source_walkthrough",
        "active_source_set": ("camera:desk", "ward:gem", "homage:album"),
        "source_provenance_posture": ("homage:private-runtime", "stream:private"),
        "camera_hero": "c920-desk",
        "camera_layout": "3d:balanced",
        "camera_roles": ("c920-desk:operator-hands", "pi-noir-desk:ir-desk"),
        "graph_family": "texture:2+spatial:2",
        "graph_topology_variant": "slotdrift:warp>halftone>trail",
        "active_node_set": ("warp", "halftone", "trail"),
        "unused_node_exploration": ("droste", "fluid_sim"),
        "parameter_regions": ("warp:strength:mid", "halftone:scale:low"),
        "homage_package": "bitchx-authentic-v1",
        "homage_artefact": "bitchx-authentic-v1:kick-reason:by Hapax/bitchx",
        "video_emissive_pair_role": "homage_video_emissive_pair",
        "scrim_profile": "layout=default:mode=3d:stream=private",
        "scrim_permeability": "visible=8:avg_alpha=mid",
        "depth_parallax_profile": "3d:on-scrim:6,beyond-scrim:2:low/mid",
        "ward_set": ("gem", "album", "precedent_ticker"),
        "ward_motion_state": ("gem:z=on-scrim:hz=mid:amp=mid",),
        "audio_role": ("instrument",),
        "audio_source_attribution": ("mixer",),
        "transition_type": "drift",
        "color_palette_role": "homage:bitchx-authentic-v1:hue=low",
        "archive_replay_public_event_status": "private-research",
        "camera_salience_refs": ("shared.camera_salience_singleton:visual_variance",),
        "cross_camera_time_evidence": ("shm:person-detection",),
        "ir_evidence_refs": ("pi-noir-desk",),
        "livestream_self_classification_refs": ("shm:scene-classification",),
    }
    data.update(overrides)
    return VisualStateVector(**data)


def _selected(vector: VisualStateVector | None = None) -> VisualSelectedMove:
    vector = vector or _vector()
    return VisualSelectedMove(
        selected_at="2026-05-17T12:00:00Z",
        move_id="visual-move:test",
        selected_by="test",
        selected_effect_nodes=vector.active_node_set,
        selected_graph_family=vector.graph_family,
        selected_source_refs=vector.active_source_set,
        selected_camera_refs=(vector.camera_hero,),
        evidence_refs=("test:selected-move",),
    )


def test_repeat_heavy_state_is_novelty_starved() -> None:
    current = _vector()
    assessment = score_visual_novelty(current, [current])

    assert assessment.score < 0.05
    assert "active_source_set" in assessment.novelty_pressure_axes
    assert "camera_hero" in assessment.novelty_pressure_axes
    assert "graph_topology_variant" in assessment.novelty_pressure_axes


def test_multi_axis_novel_state_scores_higher_than_repeat() -> None:
    prior = _vector()
    current = _vector(
        programme_role="interview",
        programme_format="operator-questioning",
        active_source_set=("camera:room", "ward:research_dashboard", "reverie"),
        camera_hero="brio-room",
        camera_layout="3d:aperture-left-arc",
        graph_family="tonal:1+spatial:3+temporal:1",
        graph_topology_variant="slotdrift:kaleidoscope>slitscan>color_map>feedback",
        active_node_set=("kaleidoscope", "slitscan", "color_map", "feedback"),
        source_provenance_posture=("homage:archive-runtime", "stream:private"),
        parameter_regions=("kaleidoscope:segments:high", "slitscan:speed:mid"),
        homage_package="cybernetic-studio-v1",
        homage_artefact="cybernetic-studio-v1:screen-test:by Hapax",
        video_emissive_pair_role="single_substrate",
        scrim_profile="layout=aperture:mode=3d:stream=private",
        scrim_permeability="visible=12:avg_alpha=high",
        depth_parallax_profile="3d:on-scrim:3,beyond-scrim:8:mid/high",
        ward_set=("programme_history", "activity_header"),
        ward_motion_state=("programme_history:z=beyond-scrim:hz=high:amp=low",),
        audio_role=("tts",),
        audio_source_attribution=("broadcast-tts",),
        transition_type="transform",
        color_palette_role="homage:other:hue=high",
        archive_replay_public_event_status="private-archive-reference",
    )

    repeat = score_visual_novelty(prior, [prior])
    assessment = score_visual_novelty(current, [prior])

    assert assessment.score > 0.55
    assert assessment.score > repeat.score
    assert "graph_topology_variant" not in assessment.novelty_pressure_axes


def test_missing_witness_blocks_success_but_not_selection() -> None:
    vector = _vector()
    ledger = build_visual_variance_ledger(
        state_vector=vector,
        selected_move=_selected(vector),
        rendered_witnesses=(),
        prior_vectors=[vector],
        now=NOW,
    )

    assert ledger.selected_move.selection_allowed is True
    assert ledger.claim_gate.success_claim_allowed is False
    assert ledger.claim_gate.claim_status is ClaimStatus.SELECTED_NOT_WITNESSED
    assert "rendered_witness_missing" in ledger.claim_gate.blockers


def test_stale_rendered_witness_blocks_success_claim(tmp_path: Path) -> None:
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"not-really-jpeg-but-nonempty")
    os.utime(frame, (NOW - 30.0, NOW - 30.0))
    witness = rendered_witness_from_path("frame", frame, now=NOW, ttl_s=5.0)

    ledger = build_visual_variance_ledger(
        state_vector=_vector(),
        selected_move=_selected(),
        rendered_witnesses=(witness,),
        now=NOW,
    )

    assert witness.status is RenderedWitnessStatus.STALE
    assert ledger.claim_gate.success_claim_allowed is False
    assert ledger.claim_gate.claim_status is ClaimStatus.STALE_WITNESS_BLOCKED


def test_public_claim_requires_explicit_public_aperture_refs(tmp_path: Path) -> None:
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"nonempty")
    os.utime(frame, (NOW, NOW))
    witness = rendered_witness_from_path("frame", frame, now=NOW, ttl_s=5.0)

    ledger = build_visual_variance_ledger(
        state_vector=_vector(),
        selected_move=_selected(),
        rendered_witnesses=(witness,),
        public_claim_requested=True,
        public_aperture_refs=(),
        now=NOW,
    )

    assert ledger.claim_gate.success_claim_allowed is True
    assert ledger.claim_gate.public_claim_allowed is False
    assert ledger.claim_gate.claim_status is ClaimStatus.PUBLIC_CLAIM_BLOCKED
    assert "public_aperture_refs_missing" in ledger.claim_gate.blockers


def test_schema_validates_emitted_ledger(tmp_path: Path) -> None:
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"nonempty")
    os.utime(frame, (NOW, NOW))
    witness = rendered_witness_from_path("frame", frame, now=NOW, ttl_s=5.0)
    ledger = build_visual_variance_ledger(
        state_vector=_vector(),
        selected_move=_selected(),
        rendered_witnesses=(witness,),
        now=NOW,
    )
    schema = cast("dict[str, Any]", json.loads(SCHEMA.read_text(encoding="utf-8")))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(ledger.model_dump(mode="json"))


def test_runtime_vector_uses_effect_layout_camera_and_witness_surfaces(tmp_path: Path) -> None:
    paths = _runtime_paths(tmp_path)
    _write_json(
        paths.effect_drift_state,
        {
            "passes": [
                {
                    "node_id": "warp",
                    "effect_family": "spatial",
                    "non_neutral": True,
                    "source_bound": True,
                    "full_surface": True,
                    "inputs": ["@live"],
                    "parameter_regions": [{"param": "strength", "region": "mid"}],
                },
                {
                    "node_id": "halftone",
                    "effect_family": "texture",
                    "non_neutral": True,
                    "source_bound": True,
                    "full_surface": True,
                    "inputs": ["main:layer_0"],
                    "parameter_regions": [{"param": "scale", "region": "low"}],
                },
            ],
            "slotdrift_coverage": {
                "effect_counts": [
                    {"name": "warp", "coverage_window_count": 1},
                    {"name": "droste", "coverage_window_count": 0},
                ]
            },
        },
    )
    _write_json(
        paths.current_layout_state,
        {
            "layout_name": "default",
            "layout_mode": "3d",
            "active_ward_ids": ["gem", "album"],
            "assignments": [
                {"source": "gem"},
                {"source": "album"},
            ],
        },
    )
    _write_json(paths.active_wards, {"ward_ids": ["gem", "album"]})
    _write_json(
        paths.ward_properties,
        {
            "wards": {
                "gem": {
                    "visible": True,
                    "z_plane": "on-scrim",
                    "front_state": "integrated",
                    "alpha": 0.8,
                    "drift_hz": 0.5,
                    "drift_amplitude_px": 5.0,
                    "parallax_scalar_video": 1.0,
                    "parallax_scalar_emissive": 1.0,
                }
            }
        },
    )
    _write_json(
        paths.camera_classifications,
        {
            "c920-desk": {
                "semantic_role": "operator-hands",
                "angle": "top-down",
                "operator_visible": False,
            },
            "pi-noir-desk": {
                "semantic_role": "ir-desk",
                "angle": "top-down",
                "operator_visible": False,
            },
        },
    )
    _write_json(
        paths.follow_mode_recommendation,
        {"camera_role": "c920-desk", "ts": NOW, "ttl_s": 30.0},
    )
    _write_json(
        paths.homage_substrate_package,
        {
            "package": "bitchx-authentic-v1",
            "palette_accent_hue_deg": 0.0,
            "substrate_source_ids": ["album", "reverie"],
        },
    )

    vector = build_visual_state_vector_from_runtime(paths=paths, now=NOW)

    assert vector.camera_hero == "c920-desk"
    assert vector.camera_layout == "3d:default"
    assert vector.graph_topology_variant.startswith("slotdrift:warp>halftone")
    assert "droste" in vector.unused_node_exploration
    assert "gem" in vector.ward_set
    assert "pi-noir-desk" in vector.ir_evidence_refs


def _runtime_paths(root: Path) -> VisualVarianceRuntimePaths:
    return VisualVarianceRuntimePaths(
        effect_drift_state=root / "effect-drift-state.json",
        effect_plan=root / "plan.json",
        visual_frame=root / "frame.jpg",
        compositor_snapshot=root / "snapshot.jpg",
        compositor_fx_snapshot=root / "fx-snapshot.jpg",
        current_layout_state=root / "current-layout-state.json",
        active_wards=root / "active_wards.json",
        ward_properties=root / "ward-properties.json",
        camera_classifications=root / "camera-classifications.json",
        hero_camera_override=root / "hero-camera-override.json",
        follow_mode_recommendation=root / "follow-mode-recommendation.json",
        person_detection=root / "person-detection.json",
        scene_classification=root / "scene-classification.json",
        segment_layout_receipt=root / "segment-layout-receipt.json",
        composition_state=root / "composition-state.json",
        homage_substrate_package=root / "homage-substrate-package.json",
        homage_active_artefact=root / "homage-active-artefact.json",
        color_resonance=root / "color-resonance.json",
        audio_source_ledger=root / "audio-source-ledger.json",
        unified_reactivity=root / "unified-reactivity.json",
        stream_mode_intent=root / "stream-mode-intent.json",
        dmn_visual_salience=root / "visual-salience.json",
        conversation_visual_signal=root / "visual-signal.json",
    )


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")
