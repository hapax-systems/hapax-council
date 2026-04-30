"""Tests for the dry-run audio marker probe harness."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from shared.audio_marker_probe_harness import (
    FAIL_CLOSED_POLICY,
    REQUIRED_AUDIO_MARKER_FIXTURE_CASES,
    AudioMarkerProbeAuthorization,
    AudioMarkerProbeHarnessError,
    MarkerFailureClass,
    MarkerProbeState,
    evaluate_marker_fixture_set,
    evaluate_marker_probe,
    load_audio_marker_probe_fixtures,
    result_to_audio_surface_observation,
    results_to_audio_surface_observations,
)
from shared.audio_world_surface_fixtures import AudioHealthState
from shared.audio_world_surface_health import project_audio_world_surface_health
from shared.broadcast_audio_health import (
    AudioHealthReason,
    BroadcastAudioHealth,
    BroadcastAudioStatus,
)
from shared.world_surface_health import HealthStatus, WitnessPolicy

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKED_AT = "2026-04-30T12:05:00Z"


def _reason(code: str) -> AudioHealthReason:
    return AudioHealthReason(
        code=code,
        owner="test",
        message=code,
        evidence_refs=["fixture"],
    )


def _safe_evidence(*, voice: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "topology": {"verification": "pass", "status": "pass"},
        "private_routes": {"status": "pass"},
        "l12_forward_invariant": {"status": "pass"},
        "broadcast_forward": {"status": "pass"},
        "loudness": {
            "within_target_band": True,
            "true_peak_within_ceiling": True,
        },
        "egress_binding": {"bound": True, "observed_source": "hapax-broadcast-normalized"},
        "voice_output_witness": voice
        or {
            "status": "playback_completed",
            "route_present": True,
            "playback_present": True,
            "egress_audible": True,
            "target": "hapax-livestream",
            "media_role": "Broadcast",
        },
        "runtime_safety": {"status": "clear", "breach_active": False},
        "audio_ducker": {"status": "ok", "fail_open": False},
    }


def _health(
    *,
    safe: bool = True,
    status: BroadcastAudioStatus = BroadcastAudioStatus.SAFE,
    reason_codes: tuple[str, ...] = (),
    evidence: dict[str, Any] | None = None,
) -> BroadcastAudioHealth:
    return BroadcastAudioHealth(
        safe=safe,
        status=status,
        checked_at=CHECKED_AT,
        freshness_s=0.0,
        blocking_reasons=[_reason(code) for code in reason_codes],
        warnings=[],
        evidence=evidence or _safe_evidence(),
        owners={"test": "tests/shared/test_audio_marker_probe_harness.py"},
    )


def test_fixture_loader_covers_required_cases_and_fail_closed_policy() -> None:
    fixtures = load_audio_marker_probe_fixtures()

    assert set(fixtures.required_fixture_cases) == REQUIRED_AUDIO_MARKER_FIXTURE_CASES
    assert set(fixtures.probes_by_case()) >= REQUIRED_AUDIO_MARKER_FIXTURE_CASES
    assert fixtures.fail_closed_policy == FAIL_CLOSED_POLICY
    assert {probe.probe_kind.value for probe in fixtures.probes} == {
        "public",
        "private",
        "no_leak",
    }


def test_fixture_expected_results_match_evaluator() -> None:
    fixtures = load_audio_marker_probe_fixtures()

    for probe in fixtures.probes:
        result = evaluate_marker_probe(probe, checked_at=CHECKED_AT)
        assert result.state is probe.expected_state, probe.fixture_case
        assert result.health_state is probe.expected_health_state, probe.fixture_case
        assert result.failure_class is probe.expected_failure_class, probe.fixture_case
        assert result.public_claim_allowed is probe.expected_public_claim_allowed
        assert result.private_only is probe.expected_private_only
        assert result.certifies_marker_observation_only is True


def test_dry_run_plan_is_not_runtime_truth() -> None:
    fixtures = load_audio_marker_probe_fixtures()
    result = evaluate_marker_probe(
        fixtures.require_case("dry_run_public_plan_only"),
        checked_at=CHECKED_AT,
    )

    assert result.state is MarkerProbeState.DRY_RUN_PLANNED
    assert result.health_state is AudioHealthState.UNKNOWN
    assert result.public_claim_allowed is False
    assert result.witness_refs == []
    assert result.failure_class is MarkerFailureClass.DRY_RUN_NOT_RUNTIME_WITNESS
    assert "no_live_audio_action_taken" in result.blocked_reasons
    assert result_to_audio_surface_observation(result).health_state is AudioHealthState.UNKNOWN


def test_public_private_and_no_leak_results_project_into_audio_wcs_health() -> None:
    fixtures = load_audio_marker_probe_fixtures()
    results = evaluate_marker_fixture_set(
        fixtures,
        cases=[
            "public_marker_witnessed",
            "private_marker_witnessed_no_leak",
            "no_leak_clean",
        ],
        checked_at=CHECKED_AT,
    )
    observations = results_to_audio_surface_observations(results)

    envelope = project_audio_world_surface_health(_health(), observations=observations)
    records = envelope.records_by_surface_id()

    assert envelope.public_live_allowed is True
    assert records["audio.broadcast_voice.health"].status is HealthStatus.HEALTHY
    assert records["audio.broadcast_voice.health"].public_claim_allowed is True
    assert records["audio.broadcast_voice.health"].witness_policy is WitnessPolicy.WITNESSED
    assert records["audio.private_assistant_monitor.health"].status is HealthStatus.PRIVATE_ONLY
    assert records["audio.private_assistant_monitor.health"].private_only is True
    assert records["audio.no_private_leak.health"].status is HealthStatus.HEALTHY


def test_private_marker_on_public_path_fails_no_leak_and_blocks_wcs_public_mode() -> None:
    fixtures = load_audio_marker_probe_fixtures()
    result = evaluate_marker_probe(
        fixtures.require_case("private_marker_leaked_public_negative"),
        checked_at=CHECKED_AT,
    )
    observations = results_to_audio_surface_observations([result])
    envelope = project_audio_world_surface_health(_health(), observations=observations)
    no_leak = envelope.records_by_surface_id()["audio.no_private_leak.health"]

    assert result.state is MarkerProbeState.FAILED
    assert result.health_state is AudioHealthState.UNSAFE
    assert result.no_leak_passed is False
    assert result.failure_class is MarkerFailureClass.PRIVATE_MARKER_LEAKED_PUBLIC
    assert "private_marker_leaked_public" in result.blocked_reasons
    assert envelope.public_live_allowed is False
    assert no_leak.status is HealthStatus.UNSAFE
    assert no_leak.public_claim_allowed is False


def test_live_execution_fails_closed_without_all_authorization_gates() -> None:
    fixtures = load_audio_marker_probe_fixtures()
    live_probe = fixtures.require_case("live_execution_blocked_without_authorization")

    result = evaluate_marker_probe(live_probe, checked_at=CHECKED_AT)
    assert result.state is MarkerProbeState.BLOCKED
    assert result.failure_class is MarkerFailureClass.LIVE_EXECUTION_NOT_AUTHORIZED
    assert result.live_execution_permitted is False
    assert result.blocked_reasons == [
        "private_voice_hard_stop_not_deployed",
        "cx_red_or_operator_authorization_missing",
        "live_audio_probe_authorization_missing",
    ]

    partial = evaluate_marker_probe(
        live_probe,
        authorization=AudioMarkerProbeAuthorization(private_voice_hard_stop_deployed=True),
        checked_at=CHECKED_AT,
    )
    assert partial.state is MarkerProbeState.BLOCKED
    assert partial.blocked_reasons == [
        "cx_red_or_operator_authorization_missing",
        "live_audio_probe_authorization_missing",
    ]


def test_missing_required_fixture_case_fails_closed(tmp_path: Path) -> None:
    fixtures = load_audio_marker_probe_fixtures()
    payload = fixtures.model_dump(mode="json")
    payload["probes"] = [
        probe
        for probe in payload["probes"]
        if probe["fixture_case"] != "private_marker_leaked_public_negative"
    ]

    path = tmp_path / "missing-audio-marker-fixtures.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(AudioMarkerProbeHarnessError, match="private_marker_leaked_public_negative"):
        load_audio_marker_probe_fixtures(path)


def test_cli_dry_run_smoke_outputs_fixture_results() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "hapax-audio-marker-probe"),
            "--dry-run",
            "--case",
            "public_marker_witnessed",
        ],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads(completed.stdout)

    assert payload[0]["fixture_case"] == "public_marker_witnessed"
    assert payload[0]["state"] == "witnessed"
    assert payload[0]["public_claim_allowed"] is True
