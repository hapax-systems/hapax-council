"""Tests for OQ-02 scrim health fixture contracts."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, cast

import jsonschema
import pytest

from shared.scrim_health_fixtures import (
    FORBIDDEN_AUDIO_MODULATION_REGISTERS,
    REQUIRED_SCRIM_HEALTH_FIXTURE_FAMILIES,
    ScrimHealthFixtureError,
    load_scrim_health_fixtures,
)
from shared.scrim_wcs_claim_posture import ScrimStateEnvelopeRef
from shared.world_surface_health import (
    AuthorityCeiling,
    FreshnessState,
    HealthStatus,
    PrivacyState,
    WorldSurfaceHealthRecord,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "schemas" / "scrim-health-fixtures.schema.json"
FIXTURES = REPO_ROOT / "config" / "scrim-health-fixtures.json"


def _payload() -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(FIXTURES.read_text(encoding="utf-8")))


def _fixtures():
    return load_scrim_health_fixtures()


def _by_family():
    return _fixtures().by_family()


def test_schema_validates_scrim_health_fixture_file() -> None:
    schema = cast("dict[str, Any]", json.loads(SCHEMA.read_text(encoding="utf-8")))
    payload = _payload()

    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(payload)
    assert set(schema["x-required_fixture_families"]) == REQUIRED_SCRIM_HEALTH_FIXTURE_FAMILIES
    assert set(schema["x-forbidden_audio_modulation_registers"]) == (
        FORBIDDEN_AUDIO_MODULATION_REGISTERS
    )
    assert schema["x-no_authority_policy"] == payload["no_authority_policy"]


def test_loader_covers_required_fixture_families() -> None:
    fixtures = _fixtures()

    assert set(fixtures.families) == REQUIRED_SCRIM_HEALTH_FIXTURE_FAMILIES
    assert {fixture.family for fixture in fixtures.fixtures} == (
        REQUIRED_SCRIM_HEALTH_FIXTURE_FAMILIES
    )


def test_health_refs_are_consumable_by_scrim_envelope_and_world_surface_health() -> None:
    fixtures = _fixtures()
    scrim_refs = fixtures.scrim_state_refs()
    health_records = fixtures.world_surface_records()

    assert len(scrim_refs) == len(fixtures.fixtures)
    assert len(health_records) == len(fixtures.fixtures)

    for fixture in fixtures.fixtures:
        assert isinstance(fixture.scrim_state, ScrimStateEnvelopeRef)
        record = fixture.world_surface_record()
        assert isinstance(record, WorldSurfaceHealthRecord)
        assert fixture.scrim_state.health_ref == record.surface_id
        assert record.public_claim_allowed is False
        assert record.monetization_allowed is False
        assert record.authority_ceiling is AuthorityCeiling.NO_CLAIM
        assert record.claimability.public_live is False
        assert record.claimability.grounded is False


def test_anti_recognition_keeps_face_obscure_upstream_not_scrim_privacy() -> None:
    fixture = _by_family()["anti_recognition_upstream_obscure"]
    record = fixture.world_surface_record()

    assert fixture.expected.scrim_counts_as_privacy_protection is False
    assert fixture.expected.face_obscure_upstream_required is True
    assert fixture.invariants.face_obscure_upstream_ref is not None
    assert fixture.invariants.face_obscure_upstream_ref in record.source_refs
    assert record.privacy_state is PrivacyState.PUBLIC_SAFE
    assert record.authority_ceiling is AuthorityCeiling.NO_CLAIM
    assert record.public_claim_allowed is False


def test_scrim_translucency_fixture_clears_structural_content_floor() -> None:
    fixture = _by_family()["scrim_translucency_nominal"]

    assert fixture.invariants.translucency_score >= fixture.invariants.translucency_minimum
    assert fixture.invariants.clears_primary_bounds() is True
    assert fixture.expected.minimum_density_fallback_required is False
    assert fixture.scrim_state.fallback_mode == "none"


def test_anti_visualizer_and_music_reactive_states_stay_structural() -> None:
    fixtures = _by_family()
    for family in ("anti_visualizer_structural_motion", "music_reactive_structural"):
        fixture = fixtures[family]
        assert fixture.invariants.audio_reactive is True
        assert fixture.invariants.structural_texture_motion is True
        assert fixture.invariants.audio_modulation_register not in (
            FORBIDDEN_AUDIO_MODULATION_REGISTERS
        )
        assert fixture.invariants.anti_visualizer_score <= (
            fixture.invariants.anti_visualizer_maximum
        )
        assert fixture.expected.scrim_health_passed is True


def test_forbidden_visualizer_registers_fail_fixture_load(tmp_path: Path) -> None:
    payload = copy.deepcopy(_payload())
    for fixture in payload["fixtures"]:
        if fixture["family"] == "music_reactive_structural":
            fixture["invariants"]["audio_modulation_register"] = "fft"
            break
    path = tmp_path / "bad-scrim-health-fixtures.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ScrimHealthFixtureError, match="forbidden visualizer register"):
        load_scrim_health_fixtures(path)


def test_pixel_sort_dominance_blocks_and_forces_minimum_density() -> None:
    fixture = _by_family()["pixel_sort_dominance_blocked"]
    record = fixture.world_surface_record()

    assert fixture.invariants.pixel_sort_dominance > (
        fixture.invariants.pixel_sort_dominance_maximum
    )
    assert fixture.expected.scrim_health_passed is False
    assert fixture.expected.minimum_density_fallback_required is True
    assert fixture.scrim_state.fallback_mode == "minimum_density"
    assert fixture.invariants.density == fixture.invariants.minimum_density
    assert record.status is HealthStatus.BLOCKED
    assert record.public_claim_allowed is False


def test_stale_state_fails_closed_without_public_confidence_cues() -> None:
    fixture = _by_family()["stale_state"]
    record = fixture.world_surface_record()

    assert record.status is HealthStatus.STALE
    assert record.freshness.state is FreshnessState.STALE
    assert fixture.scrim_state.fallback_mode == "neutral_hold"
    assert fixture.expected.public_confidence_cue_allowed is False
    assert fixture.expected.foreground_gestures_required is True
    assert record.public_claim_allowed is False


def test_minimum_density_fallback_strips_public_cues_and_foregrounds_health() -> None:
    fixture = _by_family()["minimum_density_fallback"]
    record = fixture.world_surface_record()

    assert fixture.expected.minimum_density_fallback_required is True
    assert fixture.invariants.density == fixture.invariants.minimum_density
    assert fixture.scrim_state.fallback_mode == "minimum_density"
    assert fixture.expected.public_confidence_cue_allowed is False
    assert fixture.expected.foreground_gestures_required is True
    assert record.status is HealthStatus.DEGRADED
    assert record.public_claim_allowed is False


def test_failed_health_strips_confidence_cues_and_names_foreground_gestures() -> None:
    for fixture in _fixtures().fixtures:
        if fixture.expected.scrim_health_passed:
            continue
        record = fixture.world_surface_record()
        assert fixture.expected.public_confidence_cue_allowed is False
        assert fixture.expected.foreground_gestures_required is True
        assert fixture.expected.foreground_gesture_refs
        assert record.status is not HealthStatus.HEALTHY
        assert record.public_claim_allowed is False


def test_hothouse_high_texture_profile_stays_under_caps() -> None:
    fixture = _by_family()["hothouse_high_texture"]

    assert fixture.profile_id == "moire_crackle"
    assert "high_texture" in fixture.texture_family
    assert fixture.invariants.translucency_score >= fixture.invariants.translucency_minimum
    assert fixture.invariants.pixel_sort_dominance <= (
        fixture.invariants.pixel_sort_dominance_maximum
    )
    assert fixture.invariants.motion_rate <= fixture.invariants.max_motion_rate
    assert fixture.invariants.anti_visualizer_score <= (fixture.invariants.anti_visualizer_maximum)


def test_listening_quiet_is_valid_without_music_visualizer_register() -> None:
    fixture = _by_family()["listening_quiet"]

    assert fixture.profile_id == "gauzy_quiet"
    assert fixture.invariants.audio_reactive is False
    assert fixture.invariants.audio_modulation_register == "none"
    assert fixture.invariants.anti_visualizer_score <= (fixture.invariants.anti_visualizer_maximum)
    assert fixture.expected.scrim_health_passed is True
