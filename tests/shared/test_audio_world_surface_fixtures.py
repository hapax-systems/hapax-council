"""Tests for audio World Capability Surface contract fixture loading."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.audio_world_surface_fixtures import (
    REQUIRED_AUDIO_HEALTH_STATES,
    REQUIRED_AUDIO_SURFACE_IDS,
    ROUTE_RESULT_REQUIRED_FIELDS,
    AudioHealthState,
    AudioPrivacyPosture,
    AudioWitnessClassId,
    AudioWorldSurfaceFixturesError,
    load_audio_world_surface_fixtures,
)


def test_audio_fixture_loader_covers_required_surfaces_and_health_states() -> None:
    fixtures = load_audio_world_surface_fixtures()

    assert set(fixtures.rows_by_surface_id()) == REQUIRED_AUDIO_SURFACE_IDS
    assert {state.value for state in fixtures.health_states} == REQUIRED_AUDIO_HEALTH_STATES
    assert {fixture.state.value for fixture in fixtures.health_state_fixtures} == (
        REQUIRED_AUDIO_HEALTH_STATES
    )
    assert set(fixtures.route_result_required_fields) == set(ROUTE_RESULT_REQUIRED_FIELDS)


def test_audio_route_result_shape_is_present_on_every_surface() -> None:
    fixtures = load_audio_world_surface_fixtures()

    for row in fixtures.audio_surface_rows:
        route = row.route_result
        assert route.semantic_destination == row.semantic_destination
        assert route.concrete_target_binding.route_id
        assert route.concrete_target_binding.target_ref
        assert route.concrete_target_binding.substrate_ref == row.surface_id
        assert route.concrete_target_binding.raw_high_level_target_assumption is False
        assert route.fallback_policy.reason_code
        assert route.fallback_policy.operator_visible_reason
        assert route.freshness.state.value
        assert route.failure_reason
        assert row.public_claim_allowed is False
        assert row.blocked_reasons


def test_public_private_and_no_leak_witness_classes_are_distinct() -> None:
    fixtures = load_audio_world_surface_fixtures()
    witnesses = {witness.witness_class: witness for witness in fixtures.witness_classes}

    assert witnesses[AudioWitnessClassId.PUBLIC].privacy_scope == "public"
    assert witnesses[AudioWitnessClassId.PRIVATE].privacy_scope == "private"
    assert witnesses[AudioWitnessClassId.NO_LEAK].privacy_scope == "no_leak"
    assert witnesses[AudioWitnessClassId.PUBLIC] != witnesses[AudioWitnessClassId.PRIVATE]
    assert witnesses[AudioWitnessClassId.PUBLIC] != witnesses[AudioWitnessClassId.NO_LEAK]
    assert witnesses[AudioWitnessClassId.PRIVATE] != witnesses[AudioWitnessClassId.NO_LEAK]

    assert fixtures.rows_for_witness(AudioWitnessClassId.PUBLIC)
    assert fixtures.rows_for_witness(AudioWitnessClassId.PRIVATE)
    assert fixtures.rows_for_witness(AudioWitnessClassId.NO_LEAK) == [
        fixtures.require_surface("audio.no_private_leak")
    ]


def test_route_fixture_families_cover_public_private_no_leak_stale_and_blocked() -> None:
    fixtures = load_audio_world_surface_fixtures()

    public = fixtures.require_surface("audio.broadcast_voice")
    private = fixtures.require_surface("audio.private_assistant_monitor")
    no_leak = fixtures.require_surface("audio.no_private_leak")
    stale = fixtures.require_surface("audio.broadcast_health")
    blocked = fixtures.require_surface("audio.s4_private_monitor")

    assert public.route_result.privacy_posture is AudioPrivacyPosture.PUBLIC_CANDIDATE
    assert public.route_result.witness_class is AudioWitnessClassId.PUBLIC
    assert "route:assistant" in public.route_result.fallback_policy.prohibited_fallback_refs

    assert private.route_result.privacy_posture is AudioPrivacyPosture.PRIVATE_ONLY
    assert private.route_result.witness_class is AudioWitnessClassId.PRIVATE
    assert private.health_state is AudioHealthState.BLOCKED_ABSENT
    assert "route:broadcast" in private.route_result.fallback_policy.prohibited_fallback_refs

    assert no_leak.route_result.privacy_posture is AudioPrivacyPosture.NO_LEAK
    assert no_leak.route_result.witness_class is AudioWitnessClassId.NO_LEAK
    assert no_leak.health_state is AudioHealthState.UNSAFE

    assert stale.health_state is AudioHealthState.STALE
    assert stale.route_result.freshness.state.value == "stale"

    assert blocked.health_state is AudioHealthState.BLOCKED_ABSENT
    assert blocked.route_result.freshness.state.value == "blocked_absent"


def test_audio_fixture_policy_fails_closed_without_runtime_witnesses() -> None:
    fixtures = load_audio_world_surface_fixtures()

    assert fixtures.fail_closed_policy == {
        "fixtures_are_runtime_truth": False,
        "raw_high_level_targets_are_implementation_truth": False,
        "missing_witness_allows_public_claim": False,
        "private_audio_may_fallback_to_public": False,
        "no_leak_can_be_inferred_from_route_name": False,
    }
    for health in fixtures.health_state_fixtures:
        assert health.public_live_allowed is False
        assert health.public_claim_allowed_without_runtime_witness is False
    for row in fixtures.audio_surface_rows:
        assert row.public_claim_allowed is False


def test_raw_high_level_target_assumptions_are_rejected(tmp_path: Path) -> None:
    fixtures = load_audio_world_surface_fixtures()
    payload = fixtures.model_dump(mode="json")
    payload["audio_surface_rows"][0]["route_result"]["concrete_target_binding"][
        "raw_high_level_target_assumption"
    ] = True

    path = tmp_path / "unsafe-audio-world-surface-fixtures.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(AudioWorldSurfaceFixturesError, match="raw_high_level_target_assumption"):
        load_audio_world_surface_fixtures(path)


def test_missing_required_audio_surface_fails_closed(tmp_path: Path) -> None:
    fixtures = load_audio_world_surface_fixtures()
    payload = fixtures.model_dump(mode="json")
    payload["audio_surface_rows"] = [
        row for row in payload["audio_surface_rows"] if row["surface_id"] != "audio.no_private_leak"
    ]

    path = tmp_path / "missing-audio-world-surface-fixtures.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(AudioWorldSurfaceFixturesError, match="audio.no_private_leak"):
        load_audio_world_surface_fixtures(path)
