"""Tests for projecting audio health into WCS health rows."""

from __future__ import annotations

from typing import Any

from shared.audio_world_surface_fixtures import AudioHealthState
from shared.audio_world_surface_health import (
    AudioSurfaceObservation,
    project_audio_world_surface_health,
)
from shared.broadcast_audio_health import (
    AudioHealthReason,
    BroadcastAudioHealth,
    BroadcastAudioStatus,
)
from shared.world_surface_health import FixtureCase, HealthStatus, WitnessPolicy

CHECKED_AT = "2026-04-30T04:30:00Z"


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
        "voice_output_witness": voice or {"status": "missing", "playback_present": False},
        "runtime_safety": {"status": "clear", "breach_active": False},
        "audio_ducker": {"status": "ok", "fail_open": False},
    }


def _health(
    *,
    safe: bool = True,
    status: BroadcastAudioStatus = BroadcastAudioStatus.SAFE,
    reason_codes: tuple[str, ...] = (),
    evidence: dict[str, Any] | None = None,
    freshness_s: float = 0.0,
) -> BroadcastAudioHealth:
    return BroadcastAudioHealth(
        safe=safe,
        status=status,
        checked_at=CHECKED_AT,
        freshness_s=freshness_s,
        blocking_reasons=[_reason(code) for code in reason_codes],
        warnings=[],
        evidence=evidence or _safe_evidence(),
        owners={"test": "tests/shared/test_audio_world_surface_health.py"},
    )


def _private_ready() -> AudioSurfaceObservation:
    return AudioSurfaceObservation(
        health_state=AudioHealthState.SAFE,
        evidence_refs=("evidence:private-monitor-target",),
        witness_refs=("witness:audio.private_monitor:mpc-live-iii",),
        route_refs=("route:private.mpc_live_iii_monitor",),
        confidence=0.86,
        private_only=True,
    )


def _records(health: BroadcastAudioHealth, **observations: AudioSurfaceObservation):
    normalized = {
        surface_id.replace("__", "."): value for surface_id, value in observations.items()
    }
    envelope = project_audio_world_surface_health(health, observations=normalized)
    return envelope, envelope.records_by_surface_id()


def test_safe_audio_with_public_marker_allows_public_broadcast_ready() -> None:
    voice_marker = {
        "status": "playback_completed",
        "route_present": True,
        "playback_present": True,
        "egress_audible": True,
        "target": "hapax-livestream",
        "media_role": "Broadcast",
        "planned_utterance": {"chars": 21, "words": 3},
    }
    envelope, records = _records(
        _health(evidence=_safe_evidence(voice=voice_marker)),
        audio__private_assistant_monitor=_private_ready(),
    )

    broadcast = records["audio.broadcast_voice.health"]
    assert envelope.public_live_allowed is True
    assert broadcast.status is HealthStatus.HEALTHY
    assert broadcast.public_claim_allowed is True
    assert broadcast.satisfies_claimable_health() is True
    assert broadcast.witness_policy is WitnessPolicy.WITNESSED
    assert records["audio.no_private_leak.health"].status is HealthStatus.HEALTHY
    assert records["audio.l12_capture.health"].status is HealthStatus.HEALTHY
    assert records["audio.broadcast_egress.health"].status is HealthStatus.HEALTHY
    assert records["audio.broadcast_health.health"].status is HealthStatus.HEALTHY


def test_commanded_tts_without_marker_is_not_verified_audio_success() -> None:
    commanded_voice = {
        "status": "destination_decision_recorded",
        "route_present": True,
        "playback_present": False,
        "egress_audible": None,
        "planned_utterance": {"chars": 16, "words": 2},
    }
    envelope, records = _records(_health(evidence=_safe_evidence(voice=commanded_voice)))

    broadcast = records["audio.broadcast_voice.health"]
    assert envelope.public_live_allowed is False
    assert broadcast.status is HealthStatus.UNKNOWN
    assert broadcast.fixture_case is FixtureCase.COMMANDED_ONLY
    assert broadcast.witness_policy is WitnessPolicy.COMMANDED_ONLY
    assert "commanded_tts_without_public_egress_marker" in broadcast.blocking_reasons
    assert envelope.false_grounding_risk_count >= 1


def test_public_marker_requires_broadcast_role_and_public_target() -> None:
    private_role_marker = {
        "status": "playback_completed",
        "route_present": True,
        "playback_present": True,
        "egress_audible": True,
        "target": "hapax-yeti-monitor",
        "media_role": "Assistant",
        "planned_utterance": {"chars": 21, "words": 3},
    }
    envelope, records = _records(_health(evidence=_safe_evidence(voice=private_role_marker)))

    broadcast = records["audio.broadcast_voice.health"]
    assert envelope.public_live_allowed is False
    assert broadcast.public_claim_allowed is False
    assert broadcast.satisfies_claimable_health() is False
    assert broadcast.witness_policy is not WitnessPolicy.WITNESSED
    assert "broadcast_voice_marker_missing" in broadcast.blocking_reasons


def test_unsafe_audio_safe_for_broadcast_blocks_public_mode() -> None:
    evidence = _safe_evidence(
        voice={
            "status": "playback_completed",
            "route_present": True,
            "playback_present": True,
            "egress_audible": True,
        }
    )
    evidence["private_routes"] = {"status": "fail"}
    envelope, records = _records(
        _health(
            safe=False,
            status=BroadcastAudioStatus.UNSAFE,
            reason_codes=("private_route_leak_guard_failed",),
            evidence=evidence,
        ),
        audio__broadcast_voice=AudioSurfaceObservation(
            health_state=AudioHealthState.SAFE,
            evidence_refs=("evidence:marker",),
            witness_refs=("witness:marker",),
        ),
    )

    assert envelope.public_live_allowed is False
    assert envelope.overall_status == "unsafe"
    assert records["audio.broadcast_voice.health"].status is HealthStatus.UNSAFE
    assert records["audio.no_private_leak.health"].status is HealthStatus.UNSAFE
    assert "private_route_leak_guard_failed" in (
        records["audio.no_private_leak.health"].blocking_reasons
    )


def test_stale_audio_safe_for_broadcast_blocks_public_rows() -> None:
    envelope, records = _records(
        _health(
            safe=False,
            status=BroadcastAudioStatus.UNKNOWN,
            reason_codes=("audio_safe_for_broadcast_stale",),
            freshness_s=60.0,
        )
    )

    assert envelope.public_live_allowed is False
    assert records["audio.broadcast_health.health"].status is HealthStatus.STALE
    assert records["audio.broadcast_voice.health"].status is HealthStatus.STALE
    assert records["audio.broadcast_voice.health"].freshness.state.value == "stale"


def test_no_leak_row_can_pass_without_promoting_unsafe_aggregate() -> None:
    evidence = _safe_evidence()
    evidence["loudness"] = {
        "within_target_band": False,
        "true_peak_within_ceiling": True,
    }
    envelope, records = _records(
        _health(
            safe=False,
            status=BroadcastAudioStatus.UNSAFE,
            reason_codes=("loudness_out_of_band",),
            evidence=evidence,
        )
    )

    assert envelope.public_live_allowed is False
    assert records["audio.no_private_leak.health"].status is HealthStatus.HEALTHY
    assert records["audio.no_private_leak.health"].witness_policy is WitnessPolicy.WITNESSED
    assert records["audio.broadcast_health.health"].status is HealthStatus.UNSAFE
    assert records["audio.broadcast_voice.health"].status is HealthStatus.UNSAFE


def test_private_monitor_observation_projects_private_only_not_public() -> None:
    envelope, records = _records(
        _health(),
        audio__private_assistant_monitor=_private_ready(),
    )

    private = records["audio.private_assistant_monitor.health"]
    assert envelope.public_live_allowed is False
    assert private.status is HealthStatus.PRIVATE_ONLY
    assert private.private_only is True
    assert private.public_claim_allowed is False
    assert private.public_private_posture.value == "private_only"
    assert "private_only_not_public" in private.blocking_reasons


def test_private_monitor_blocked_absent_surfaces_without_broadcast_fallback() -> None:
    blocked = AudioSurfaceObservation(
        health_state=AudioHealthState.BLOCKED_ABSENT,
        evidence_refs=("evidence:private-monitor-target",),
        route_refs=("route:private.mpc_live_iii_monitor",),
        blocking_reasons=("mpc_private_monitor_target_absent",),
        confidence=0.8,
    )
    _envelope, records = _records(_health(), audio__private_assistant_monitor=blocked)

    private = records["audio.private_assistant_monitor.health"]
    assert private.status is HealthStatus.BLOCKED
    assert private.public_claim_allowed is False
    assert private.public_private_posture.value == "blocked"
    assert "mpc_private_monitor_target_absent" in private.blocking_reasons
    assert "route:private.assistant_monitor" in private.route_refs
    assert private.fallback.safe_state == "silent_no_fallback"


def test_missing_audio_safe_for_broadcast_remains_unknown() -> None:
    envelope, records = _records(
        _health(
            safe=False,
            status=BroadcastAudioStatus.UNKNOWN,
            reason_codes=("audio_safe_for_broadcast_missing",),
            evidence={"state_file": {"read": "missing"}},
        )
    )

    assert envelope.public_live_allowed is False
    assert records["audio.broadcast_health.health"].status is HealthStatus.UNKNOWN
    assert records["audio.broadcast_voice.health"].status is HealthStatus.UNKNOWN
