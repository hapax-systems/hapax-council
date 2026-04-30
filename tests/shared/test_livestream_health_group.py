"""Tests for the livestream health-group truth-spine contract."""

from __future__ import annotations

from typing import Any

from shared.archive_replay_public_events import ArchiveReplayPublicLinkDecision
from shared.broadcast_audio_health import (
    AudioHealthReason,
    BroadcastAudioHealth,
    BroadcastAudioStatus,
    ReasonSeverity,
)
from shared.cross_surface_event_contract import decide_cross_surface_fanout
from shared.director_vocabulary import ContentSubstrate
from shared.livestream_egress_state import (
    EgressState,
    EvidenceStatus,
    FloorState,
    LivestreamEgressEvidence,
    LivestreamEgressState,
)
from shared.livestream_health_group import (
    LivestreamHealthGroupId,
    LivestreamHealthStatus,
    SubstrateFreshnessObservation,
    build_livestream_health_envelope,
)
from shared.programme import Programme, ProgrammeRole, ProgrammeStatus
from shared.research_vehicle_public_event import (
    PublicEventChapterRef,
    PublicEventProvenance,
    PublicEventSource,
    PublicEventSurfacePolicy,
    ResearchVehiclePublicEvent,
)

NOW = "2026-04-30T12:00:00Z"


def _evidence(
    source: str, status: EvidenceStatus = EvidenceStatus.PASS
) -> LivestreamEgressEvidence:
    return LivestreamEgressEvidence(
        source=source,
        status=status,
        summary=f"{source} {status.value}",
        observed={},
        age_s=0.0,
        stale=status is not EvidenceStatus.PASS,
        timestamp=NOW,
    )


def _egress(**overrides: Any) -> LivestreamEgressState:
    payload = {
        "state": EgressState.PUBLIC_LIVE,
        "confidence": 0.95,
        "public_claim_allowed": True,
        "public_ready": True,
        "research_capture_ready": True,
        "monetization_risk": "low",
        "privacy_floor": FloorState.SATISFIED,
        "audio_floor": FloorState.SATISFIED,
        "evidence": [
            _evidence("local_preview"),
            _evidence("hls_playlist"),
            _evidence("rtmp_output"),
            _evidence("mediamtx_hls"),
            _evidence("active_video_id"),
            _evidence("youtube_ingest"),
            _evidence("metadata"),
            _evidence("hls_archive"),
            _evidence("privacy_floor"),
        ],
        "public_claim_blockers": [],
        "last_transition": NOW,
        "operator_action": "none",
    }
    payload.update(overrides)
    return LivestreamEgressState(**payload)


def _audio(*, safe: bool = True) -> BroadcastAudioHealth:
    reasons = []
    if not safe:
        reasons.append(
            AudioHealthReason(
                code="private_route_leak_guard_failed",
                severity=ReasonSeverity.BLOCKING,
                owner="scripts/audio-leak-guard.sh",
                message="private route may reach broadcast",
                evidence_refs=["audio-leak-guard"],
            )
        )
    return BroadcastAudioHealth(
        safe=safe,
        status=BroadcastAudioStatus.SAFE if safe else BroadcastAudioStatus.UNSAFE,
        checked_at=NOW,
        freshness_s=0.0,
        blocking_reasons=reasons,
        warnings=[],
        evidence={"loudness": {"status": "pass"}, "private_routes": {"status": "pass"}},
        owners={"health_consumer": "livestream-health-group"},
    )


def _substrate(
    substrate_id: str = "caption_in_band",
    *,
    integration_status: str = "public-live",
    claim_monetizable: bool = True,
    ttl_s: int | None = 30,
) -> ContentSubstrate:
    return ContentSubstrate.model_validate(
        {
            "schema_version": 1,
            "substrate_id": substrate_id,
            "display_name": substrate_id.replace("_", " ").title(),
            "substrate_type": "caption",
            "producer": {"owner": "tests", "state": "state", "evidence": "evidence"},
            "consumer": {"owner": "tests", "state": "event", "evidence": "evidence"},
            "freshness_ttl_s": ttl_s,
            "rights_class": "operator_original",
            "provenance_token": f"{substrate_id}.event",
            "privacy_class": "public_safe",
            "public_private_modes": ["private", "dry_run", "public_live", "archive"],
            "render_target": "test-target",
            "director_vocabulary": [substrate_id],
            "director_affordances": ["hold"],
            "programme_bias_hooks": ["programme_boundary"],
            "objective_links": ["livestream-health-group"],
            "public_claim_permissions": {
                "claim_live": True,
                "claim_archive": True,
                "claim_monetizable": claim_monetizable,
                "requires_egress_public_claim": True,
                "requires_audio_safe": True,
                "requires_provenance": True,
                "requires_operator_action": False,
            },
            "health_signal": {
                "owner": "livestream-health-group",
                "status_ref": f"{substrate_id}.status",
                "freshness_ref": f"{substrate_id}.age_s",
            },
            "fallback": {
                "mode": "dry_run_badge",
                "reason": f"{substrate_id} evidence unavailable",
            },
            "kill_switch_behavior": {
                "trigger": "test trigger",
                "action": "suppress",
                "operator_recovery": "repair evidence",
            },
            "integration_status": integration_status,
        }
    )


def _programme(status: ProgrammeStatus = ProgrammeStatus.ACTIVE) -> Programme:
    return Programme(
        programme_id="programme:health-test",
        role=ProgrammeRole.EXPERIMENT,
        status=status,
        planned_duration_s=300.0,
        actual_started_at=1.0 if status is ProgrammeStatus.ACTIVE else None,
        parent_show_id="show:health-test",
    )


def _public_event(*, claim_monetizable: bool = True) -> ResearchVehiclePublicEvent:
    event_id = "rvpe:broadcast_boundary:health-test"
    return ResearchVehiclePublicEvent(
        event_id=event_id,
        event_type="broadcast.boundary",
        occurred_at=NOW,
        broadcast_id="video-123",
        programme_id="programme:health-test",
        condition_id=None,
        source=PublicEventSource(
            producer="tests",
            substrate_id="caption_in_band",
            task_anchor="livestream-health-group",
            evidence_ref="tests#public-event",
            freshness_ref="tests.public_event.age_s",
        ),
        salience=0.8,
        state_kind="live_state",
        rights_class="operator_original",
        privacy_class="public_safe",
        provenance=PublicEventProvenance(
            token="event-token",
            generated_at=NOW,
            producer="tests",
            evidence_refs=["evidence:public-event"],
            rights_basis="operator original fixture",
            citation_refs=[],
        ),
        public_url="https://example.test/watch/video-123",
        frame_ref=None,
        chapter_ref=PublicEventChapterRef(
            kind="chapter",
            label="Boundary",
            timecode="00:00",
            source_event_id=event_id,
        ),
        attribution_refs=[],
        surface_policy=PublicEventSurfacePolicy(
            allowed_surfaces=["mastodon", "archive", "replay", "health"],
            denied_surfaces=[],
            claim_live=True,
            claim_archive=True,
            claim_monetizable=claim_monetizable,
            requires_egress_public_claim=True,
            requires_audio_safe=True,
            requires_provenance=True,
            requires_human_review=False,
            rate_limit_key="broadcast.boundary:health-test",
            redaction_policy="operator_referent",
            fallback_action="hold",
            dry_run_reason=None,
        ),
    )


def _archive_decision(event: ResearchVehiclePublicEvent) -> ArchiveReplayPublicLinkDecision:
    return ArchiveReplayPublicLinkDecision(
        decision_id="archive_replay_decision:health-test",
        idempotency_key="rvpe:archive_replay:health-test",
        status="emitted",
        archive_capture_claim_allowed=True,
        public_replay_link_claim_allowed=True,
        public_event=event,
        source_segment_refs=("segment:health-test",),
        temporal_span_refs=("span:health-test",),
        gate_refs=("gate:archive:public-event",),
        evidence_freshness_ref="archive_replay_public_link.evidence_fresh_at",
        span_gate_status="pass",
    )


def test_all_truth_surfaces_allow_watch_publish_monetize_and_research_capture() -> None:
    event = _public_event()
    decision = decide_cross_surface_fanout(event, "mastodon", "publish")

    envelope = build_livestream_health_envelope(
        egress=_egress(),
        audio_safe_for_broadcast=_audio(),
        substrates=[_substrate()],
        substrate_observations={
            "caption_in_band": SubstrateFreshnessObservation(
                substrate_id="caption_in_band",
                observed_age_s=1.0,
                evidence_refs=("evidence:caption_in_band:fresh",),
            )
        },
        programme=_programme(),
        archive_decisions=[_archive_decision(event)],
        public_events=[event],
        fanout_decisions=[decision],
        checked_at=NOW,
    )

    assert envelope.safe_to_watch is True
    assert envelope.safe_to_publish is True
    assert envelope.safe_to_monetize is True
    assert envelope.useful_for_research_capture is True
    assert envelope.public_claim_allowed_source == "LivestreamEgressState.public_claim_allowed"
    assert envelope.audio_safe_source == "BroadcastAudioHealth.safe"
    assert envelope.substrate_source == "ContentSubstrate"
    assert set(envelope.groups_by_id()) == {group_id.value for group_id in LivestreamHealthGroupId}


def test_public_aperture_decision_cannot_override_egress_public_claim_blocker() -> None:
    event = _public_event()
    decision = decide_cross_surface_fanout(event, "mastodon", "publish")
    egress = _egress(
        public_claim_allowed=False,
        public_ready=False,
        state=EgressState.PUBLIC_BLOCKED,
        public_claim_blockers=["youtube_ingest:fail"],
        operator_action="restore YouTube ingest proof",
    )

    envelope = build_livestream_health_envelope(
        egress=egress,
        audio_safe_for_broadcast=_audio(),
        substrates=[_substrate()],
        substrate_observations={
            "caption_in_band": SubstrateFreshnessObservation(
                substrate_id="caption_in_band",
                observed_age_s=1.0,
            )
        },
        programme=_programme(),
        archive_decisions=[_archive_decision(event)],
        public_events=[event],
        fanout_decisions=[decision],
        checked_at=NOW,
    )

    public_ingest = envelope.groups_by_id()["public_ingest"]

    assert envelope.safe_to_watch is True
    assert envelope.safe_to_publish is False
    assert envelope.safe_to_monetize is False
    assert public_ingest.status is LivestreamHealthStatus.BLOCKED
    assert "youtube_ingest:fail" in public_ingest.blocked_reasons


def test_unavailable_and_stale_substrates_are_explained_fail_closed() -> None:
    stale = _substrate("caption_in_band", integration_status="public-live", ttl_s=30)
    unavailable = _substrate("re_splay_m8", integration_status="unavailable")

    envelope = build_livestream_health_envelope(
        egress=_egress(),
        audio_safe_for_broadcast=_audio(),
        substrates=[stale, unavailable],
        substrate_observations={
            "caption_in_band": SubstrateFreshnessObservation(
                substrate_id="caption_in_band",
                observed_age_s=90.0,
                evidence_refs=("evidence:caption:old",),
            )
        },
        programme=_programme(),
        checked_at=NOW,
    )

    substrate_group = envelope.groups_by_id()["substrate_freshness"]

    assert envelope.useful_for_research_capture is False
    assert envelope.safe_to_publish is False
    assert substrate_group.status is LivestreamHealthStatus.STALE
    assert any("caption_in_band:stale" in reason for reason in substrate_group.degraded_reasons)
    assert any("re_splay_m8:unavailable" in reason for reason in substrate_group.blocked_reasons)


def test_unsafe_audio_blocks_watch_publish_and_research_capture_claims() -> None:
    event = _public_event()
    decision = decide_cross_surface_fanout(event, "mastodon", "publish")

    envelope = build_livestream_health_envelope(
        egress=_egress(),
        audio_safe_for_broadcast=_audio(safe=False),
        substrates=[_substrate()],
        substrate_observations={
            "caption_in_band": SubstrateFreshnessObservation(
                substrate_id="caption_in_band",
                observed_age_s=1.0,
            )
        },
        programme=_programme(),
        archive_decisions=[_archive_decision(event)],
        public_events=[event],
        fanout_decisions=[decision],
        checked_at=NOW,
    )

    audio = envelope.groups_by_id()["audio"]

    assert envelope.safe_to_watch is False
    assert envelope.safe_to_publish is False
    assert envelope.safe_to_monetize is False
    assert audio.status is LivestreamHealthStatus.BLOCKED
    assert "private_route_leak_guard_failed" in audio.blocked_reasons


def test_static_public_aperture_contract_without_decision_is_not_publish_authority() -> None:
    event = _public_event()

    envelope = build_livestream_health_envelope(
        egress=_egress(),
        audio_safe_for_broadcast=_audio(),
        substrates=[_substrate()],
        substrate_observations={
            "caption_in_band": SubstrateFreshnessObservation(
                substrate_id="caption_in_band",
                observed_age_s=1.0,
            )
        },
        programme=_programme(),
        archive_decisions=[_archive_decision(event)],
        public_events=[event],
        checked_at=NOW,
    )

    public_apertures = envelope.groups_by_id()["public_apertures"]

    assert public_apertures.status is LivestreamHealthStatus.DEGRADED
    assert public_apertures.claim_allowed is False
    assert "public_event_present_but_fanout_decision_missing" in public_apertures.degraded_reasons
    assert envelope.safe_to_publish is False
