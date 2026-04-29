"""Tests for WCS witness probe runtime evaluation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from shared.wcs_witness_probe_runtime import (
    REQUIRED_PROBE_STATES,
    REQUIRED_WITNESS_CLASSES,
    LearningUpdatePolicy,
    ProbeState,
    WCSWitnessProbeRuntimeError,
    WitnessClass,
    evaluate_probe,
    load_wcs_witness_probe_fixtures,
)

FRESH_NOW = datetime(2026, 4, 29, 18, 11, 0, tzinfo=UTC)
STALE_NOW = datetime(2026, 4, 29, 18, 20, 0, tzinfo=UTC)


def test_fixture_loader_covers_probe_classes_and_states() -> None:
    fixtures = load_wcs_witness_probe_fixtures()

    assert {interface.witness_class.value for interface in fixtures.witness_class_interfaces} == (
        REQUIRED_WITNESS_CLASSES
    )
    assert {state.value for state in fixtures.states} == REQUIRED_PROBE_STATES
    assert {probe.state.value for probe in fixtures.probes} == REQUIRED_PROBE_STATES
    assert fixtures.fail_closed_policy == {
        "selected_or_commanded_is_public_truth": False,
        "missing_witness_allows_public_claim": False,
        "stale_witness_allows_public_claim": False,
        "probes_are_expert_truth_oracle": False,
    }


def test_command_success_without_witness_blocks_public_claims() -> None:
    fixtures = load_wcs_witness_probe_fixtures()
    probe = fixtures.require_probe("audio.broadcast_voice.commanded_no_egress_witness")

    assert probe.command_result_success is True
    assert probe.state is ProbeState.COMMANDED

    evaluation = evaluate_probe(probe, now=FRESH_NOW)

    assert evaluation.public_claim_allowed is False
    assert evaluation.learning_update_policy is LearningUpdatePolicy.DEFER
    assert evaluation.blocked_reasons == [
        "commanded_without_required_witness",
        "missing_witness:public_egress",
        "missing_witness:audio_video_state",
    ]


def test_fresh_public_egress_witness_allows_reference_audio_claim() -> None:
    fixtures = load_wcs_witness_probe_fixtures()
    probe = fixtures.require_probe("audio.broadcast_voice.public_egress_witnessed")

    evaluation = evaluate_probe(probe, now=FRESH_NOW)

    assert evaluation.state is ProbeState.WITNESSED
    assert evaluation.witness_class is WitnessClass.PUBLIC_EGRESS
    assert evaluation.public_claim_allowed is True
    assert evaluation.learning_update_policy is LearningUpdatePolicy.SUCCESS
    assert evaluation.blocked_reasons == []
    assert "shm:hapax-daimonion/voice-output-witness.json" in evaluation.source_refs


def test_stale_witness_fails_closed_even_if_witnessed_before() -> None:
    fixtures = load_wcs_witness_probe_fixtures()
    probe = fixtures.require_probe("audio.broadcast_voice.public_egress_witnessed")

    evaluation = evaluate_probe(probe, now=STALE_NOW)

    assert evaluation.state is ProbeState.STALE
    assert evaluation.public_claim_allowed is False
    assert evaluation.learning_update_policy is LearningUpdatePolicy.FAILURE
    assert evaluation.failure_reason == "witness_stale"
    assert evaluation.blocked_reasons == ["stale_witness_blocks_public_claim"]


def test_selected_observed_blocked_stale_and_failed_emit_blocked_reasons() -> None:
    fixtures = load_wcs_witness_probe_fixtures()

    selected = evaluate_probe(fixtures.require_probe("archive.replay_sidecar.selected_only"))
    observed = evaluate_probe(
        fixtures.require_probe("camera.studio_compositor_frame.observed_without_witness")
    )
    blocked = evaluate_probe(
        fixtures.require_probe("public.research_vehicle_apertures.policy_blocked")
    )
    stale = evaluate_probe(fixtures.require_probe("audio.broadcast_voice.stale_public_egress"))
    failed = evaluate_probe(
        fixtures.require_probe("browser.mcp_tool_read.failed_source_acquisition")
    )

    assert selected.blocked_reasons == ["selected_without_command_or_witness"]
    assert observed.blocked_reasons == ["observed_without_required_witness"]
    assert blocked.blocked_reasons == ["public_event_policy_missing"]
    assert stale.blocked_reasons == ["stale_public_egress_witness"]
    assert failed.blocked_reasons == ["source_acquisition_failed"]
    for evaluation in (selected, observed, blocked, stale, failed):
        assert evaluation.public_claim_allowed is False


def test_probe_records_certify_obligations_not_expert_truth() -> None:
    fixtures = load_wcs_witness_probe_fixtures()

    for interface in fixtures.witness_class_interfaces:
        assert interface.is_truth_oracle is False
    for probe in fixtures.probes:
        assert probe.certifies_declared_obligation_only is True


def test_missing_witness_timestamp_rejected(tmp_path: Path) -> None:
    fixtures = load_wcs_witness_probe_fixtures()
    payload = fixtures.model_dump(mode="json")
    for probe in payload["probes"]:
        if probe["probe_id"] == "audio.broadcast_voice.public_egress_witnessed":
            probe["witnessed_at"] = None

    path = tmp_path / "bad-wcs-witness-probes.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(WCSWitnessProbeRuntimeError, match="witnessed probes require witnessed_at"):
        load_wcs_witness_probe_fixtures(path)


def test_truth_oracle_interface_rejected(tmp_path: Path) -> None:
    fixtures = load_wcs_witness_probe_fixtures()
    payload = fixtures.model_dump(mode="json")
    payload["witness_class_interfaces"][0]["is_truth_oracle"] = True

    path = tmp_path / "bad-wcs-witness-interfaces.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(WCSWitnessProbeRuntimeError, match="Input should be False"):
        load_wcs_witness_probe_fixtures(path)
