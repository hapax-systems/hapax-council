"""Tests for the semantic FX expression surface."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from shared.audio_expression_surface import (
    AudioExpressionIntent,
    AudioExpressionRegister,
    AudioPublicPosture,
    FxDeviceWitness,
    FxFallback,
    FxOutcomeWitness,
    FxPlanState,
    FxRiskClamps,
    FxSelectedRoute,
    FxTimingPolicy,
    resolve_fx_plan,
)

NOW = datetime(2026, 4, 30, 1, 55, tzinfo=UTC)


def _intent(
    *,
    posture: AudioPublicPosture = AudioPublicPosture.PUBLIC_LIVE,
    register: AudioExpressionRegister = AudioExpressionRegister.CLEAR_WET,
    clamps: FxRiskClamps | None = None,
) -> AudioExpressionIntent:
    return AudioExpressionIntent(
        intent_id="intent:test",
        created_at=NOW,
        source_impingement_ref="impingement:test",
        programme_ref="programme:test",
        speech_act_ref="speech:test",
        semantic_basis=("semantic:voice-expression",),
        expression_register=register,
        intended_outcome="voice remains legible while marked as Hapax expression",
        clarity_budget=0.85,
        public_posture=posture,
        risk_clamps=clamps or FxRiskClamps(),
        world_surface_refs=("world:audio",),
        evidence_refs=("intent:evidence",),
    )


def _fresh_witness(**overrides: object) -> FxDeviceWitness:
    data: dict[str, object] = {
        "observed_at": NOW,
        "max_age_s": 300.0,
        "evil_pet_midi": True,
        "evil_pet_sd_pack": True,
        "evil_pet_firmware_verified": True,
        "s4_midi": True,
        "s4_audio": True,
        "l12_route": True,
        "evidence_refs": ("device:witness",),
    }
    data.update(overrides)
    return FxDeviceWitness.model_validate(data)


def _write_private_status(path: Path) -> None:
    payload = {
        "bridge": {
            "installed": True,
            "matches_repo": True,
            "repaired": False,
            "requires_pipewire_reload": False,
        },
        "bridge_nodes_present": True,
        "checked_at": "2026-04-30T01:55:00Z",
        "exact_target_present": True,
        "fallback_policy": "no_default_fallback",
        "operator_visible_reason": "Exact private monitor target is present.",
        "reason_code": "exact_private_monitor_bound",
        "route_id": "route:private.s4_track_fenced",
        "sanitized": True,
        "state": "ready",
        "surface_id": "audio.s4_private_monitor",
        "target_ref": "audio.s4_private_monitor",
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_public_voice_with_missing_fx_witness_is_held_not_dry() -> None:
    plan = resolve_fx_plan(
        _intent(),
        device_witness=_fresh_witness(
            evil_pet_midi=False,
            evil_pet_sd_pack=False,
            evil_pet_firmware_verified=False,
            s4_midi=False,
            s4_audio=False,
            l12_route=False,
            evidence_refs=(),
        ),
        now=NOW,
    )

    assert plan.state is FxPlanState.HELD
    assert plan.selected_route is FxSelectedRoute.HELD
    assert plan.no_dry_invariant is True
    assert plan.fallback is FxFallback.NO_PUBLIC_SPEECH
    assert plan.playback_target is None
    assert "evil_pet_sd_pack_missing" in plan.operator_visible_reason


def test_public_voice_with_stale_device_witness_is_held() -> None:
    plan = resolve_fx_plan(
        _intent(),
        device_witness=_fresh_witness(observed_at=NOW - timedelta(seconds=301)),
        now=NOW,
    )

    assert plan.state is FxPlanState.HELD
    assert plan.selected_route is FxSelectedRoute.HELD
    assert plan.playback_target is None
    assert "fx_device_witness_stale" in plan.operator_visible_reason


def test_private_diagnostic_voice_may_use_exact_private_monitor_without_fx(
    tmp_path: Path,
) -> None:
    status_path = tmp_path / "private-monitor-target.json"
    _write_private_status(status_path)

    plan = resolve_fx_plan(
        _intent(posture=AudioPublicPosture.PRIVATE),
        device_witness=_fresh_witness(
            evil_pet_midi=False,
            evil_pet_sd_pack=False,
            evil_pet_firmware_verified=False,
            s4_midi=False,
            s4_audio=False,
            l12_route=False,
        ),
        private_monitor_status_path=status_path,
        now=NOW,
    )

    assert plan.state is FxPlanState.PLANNED
    assert plan.selected_route is FxSelectedRoute.PRIVATE_MONITOR
    assert plan.no_dry_invariant is False
    assert plan.fallback is FxFallback.PRIVATE_ONLY
    assert plan.playback_target == "hapax-private"


def test_dry_run_posture_records_intent_without_playback() -> None:
    plan = resolve_fx_plan(
        _intent(posture=AudioPublicPosture.DRY_RUN),
        device_witness=_fresh_witness(),
        now=NOW,
    )

    assert plan.state is FxPlanState.PLANNED
    assert plan.selected_route is FxSelectedRoute.DRY_RUN_PROBE
    assert plan.playback_target is None
    assert plan.timing_policy is FxTimingPolicy.EMERGENCY_HOLD


def test_successful_public_dual_fx_plan_uses_router_target_and_wet_devices() -> None:
    plan = resolve_fx_plan(
        _intent(register=AudioExpressionRegister.MEMORY),
        device_witness=_fresh_witness(),
        now=NOW,
    )

    assert plan.state is FxPlanState.PLANNED
    assert plan.selected_route is FxSelectedRoute.DUAL_FX
    assert plan.no_dry_invariant is True
    assert plan.evil_pet_baseline == "hapax-memory"
    assert plan.evil_pet_baseline_hash is not None
    assert plan.evil_pet_cc_overlay
    assert plan.s4_scene == "MEMORY-COMPANION"
    assert plan.s4_scene_hash is not None
    assert plan.s4_params
    assert plan.route_plan.accepted is True
    assert plan.playback_target == "hapax-voice-fx-capture"
    assert "wet_fx_route_present" in plan.expected_observables


def test_public_plan_can_use_s4_only_but_never_dry() -> None:
    plan = resolve_fx_plan(
        _intent(register=AudioExpressionRegister.RADIO),
        device_witness=_fresh_witness(
            evil_pet_midi=False,
            evil_pet_sd_pack=False,
            evil_pet_firmware_verified=False,
        ),
        now=NOW,
    )

    assert plan.state is FxPlanState.PLANNED
    assert plan.selected_route is FxSelectedRoute.S4
    assert plan.evil_pet_baseline is None
    assert plan.s4_scene == "VOCAL-COMPANION"
    assert plan.playback_target == "hapax-voice-fx-capture"


def test_unsafe_cc_values_are_clamped_before_plan_execution() -> None:
    plan = resolve_fx_plan(
        _intent(
            register=AudioExpressionRegister.OBLITERATED,
            clamps=FxRiskClamps(shimmer=0.0, resonance=0.2, saturation=0.25, wetness=0.7),
        ),
        device_witness=_fresh_witness(s4_midi=False, s4_audio=False, l12_route=False),
        now=NOW,
    )

    assert plan.state is FxPlanState.PLANNED
    assert plan.selected_route is FxSelectedRoute.EVIL_PET
    cc_values = {command.cc: command.value for command in plan.evil_pet_cc_overlay}
    assert cc_values[94] == 0
    assert cc_values[71] <= round(127 * 0.2)
    assert cc_values[39] <= round(127 * 0.25)
    assert cc_values[40] <= round(127 * 0.7)


def test_outcome_witness_blocks_posterior_without_grounded_audio_probe() -> None:
    plan = resolve_fx_plan(
        _intent(register=AudioExpressionRegister.MEMORY),
        device_witness=_fresh_witness(),
        now=NOW,
    )

    witness = FxOutcomeWitness.grounded(
        witness_id="fx-witness:test",
        plan=plan,
        device_reachability=_fresh_witness(),
        route_evidence=("route:public.broadcast_voice",),
        audio_probe=(),
        egress_evidence=("egress:broadcast",),
        observed_register=AudioExpressionRegister.MEMORY,
    )

    assert witness.posterior_update_allowed is False
    assert witness.mismatch_reasons == ("missing_grounded_witness_component",)
