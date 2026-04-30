"""Tests for chronicle high-salience ResearchVehiclePublicEvent projection."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema

from shared.livestream_egress_state import (
    EgressState,
    EvidenceStatus,
    FloorState,
    LivestreamEgressEvidence,
    LivestreamEgressState,
)
from shared.research_vehicle_public_event_chronicle import (
    build_chronicle_public_event,
    is_chronicle_public_event_candidate,
)

NOW = datetime(2026, 4, 30, 11, 10, tzinfo=UTC).timestamp()
GENERATED_AT = "2026-04-30T11:10:00Z"


def _gate(
    *,
    mode: str = "public_live",
    may_publish_live: bool = True,
    may_publish_archive: bool = True,
    gate_state: str = "pass",
    infractions: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "gate_id": "grounding_gate_chronicle_001",
        "public_private_mode": mode,
        "gate_state": gate_state,
        "infractions": list(infractions),
        "claim": {
            "claim_text": "Chronicle observed a high-salience programme moment.",
            "evidence_refs": ["chronicle:source-window", "source:research-note"],
            "provenance": {
                "producer": "tests",
                "source_refs": ["source:research-note"],
                "model_id": None,
                "tool_id": "fixture",
                "retrieved_at": GENERATED_AT,
            },
            "confidence": {"kind": "posterior", "value": 0.82, "label": "medium_high"},
            "uncertainty": "Chronicle salience is an observation, not an expert verdict.",
            "freshness": {"status": "fresh", "checked_at": GENERATED_AT, "age_s": 60, "ttl_s": 300},
            "rights_state": "operator_original",
            "privacy_state": "public_safe",
            "public_private_mode": mode,
            "refusal_correction_path": {
                "refusal_reason": None,
                "correction_event_ref": None,
                "artifact_ref": "grounding_gate_chronicle_001",
            },
        },
        "gate_result": {
            "may_emit_claim": True,
            "may_publish_live": may_publish_live,
            "may_publish_archive": may_publish_archive,
            "may_monetize": False,
            "must_emit_refusal_artifact": False,
            "must_emit_correction_artifact": False,
            "blockers": [],
            "unavailable_reasons": [],
        },
        "no_expert_system_policy": {
            "rules_may_gate_and_structure_attempts": True,
            "authoritative_verdict_allowed": False,
            "verdict_requires_evidence_bound_claim": True,
            "latest_intelligence_default": True,
            "older_model_exception_requires_grounding_evidence": True,
        },
    }


def _chronicle_event(**payload_overrides: Any) -> dict[str, Any]:
    payload = {
        "salience": 0.91,
        "rights_class": "operator_original",
        "privacy_class": "public_safe",
        "provenance_token": "chronicle-token-001",
        "attribution_refs": ["operator:chronicle"],
        "chapter_label": "High-salience observation",
        "timecode": "00:42",
        "grounding_gate_result": _gate(),
        "condition_id": "condition-public-aperture",
    }
    payload.update(payload_overrides)
    return {
        "ts": NOW - 60,
        "trace_id": "a" * 32,
        "span_id": "b" * 16,
        "parent_span_id": None,
        "source": "stimmung",
        "event_type": "snapshot.salience",
        "payload": payload,
    }


def _egress(*, public_claim_allowed: bool = True, stale: bool = False) -> LivestreamEgressState:
    return LivestreamEgressState(
        state=EgressState.PUBLIC_LIVE if public_claim_allowed else EgressState.PUBLIC_BLOCKED,
        confidence=1.0 if public_claim_allowed else 0.4,
        public_claim_allowed=public_claim_allowed,
        public_ready=public_claim_allowed,
        research_capture_ready=True,
        monetization_risk="none",
        privacy_floor=FloorState.SATISFIED,
        audio_floor=FloorState.SATISFIED,
        evidence=[
            LivestreamEgressEvidence(
                source="fixture",
                status=EvidenceStatus.PASS if public_claim_allowed else EvidenceStatus.FAIL,
                summary="fixture egress",
                observed={},
                stale=stale,
            )
        ],
        last_transition=GENERATED_AT,
        operator_action="none",
    )


def _build(event: dict[str, Any], egress: LivestreamEgressState | None = None):
    return build_chronicle_public_event(
        event,
        evidence_ref="/dev/shm/hapax-chronicle/events.jsonl#byte=0",
        egress_state=egress or _egress(),
        generated_at=GENERATED_AT,
        now=NOW,
    )


def test_clean_chronicle_high_salience_maps_to_schema_safe_public_live_event() -> None:
    decision = _build(_chronicle_event())

    assert decision.status == "emitted"
    assert decision.grounding_gate_ref == "grounding_gate_chronicle_001"
    assert decision.confidence_label == "medium_high"
    assert decision.uncertainty == "Chronicle salience is an observation, not an expert verdict."

    event = decision.public_event
    assert event is not None
    assert event.event_type == "chronicle.high_salience"
    assert event.state_kind == "research_observation"
    assert event.source.producer == "agents.chronicle_high_salience_public_event_producer"
    assert event.source.task_anchor == "chronicle-high-salience-public-event-producer"
    assert event.source.freshness_ref == "chronicle_event.age_s"
    assert event.surface_policy.claim_live is True
    assert event.surface_policy.claim_archive is True
    assert event.surface_policy.claim_monetizable is False
    assert "omg_statuslog" in event.surface_policy.allowed_surfaces
    assert "mastodon" in event.surface_policy.allowed_surfaces
    assert "youtube_shorts" in event.surface_policy.denied_surfaces
    assert "GroundingCommitmentGate:grounding_gate_chronicle_001" in (
        event.provenance.evidence_refs
    )
    assert "source:research-note" in event.attribution_refs

    schema = json.loads(Path("schemas/research-vehicle-public-event.schema.json").read_text())
    jsonschema.validate(event.model_dump(mode="json"), schema)


def test_aesthetic_frame_capture_requires_frame_ref_and_allows_visual_surfaces() -> None:
    decision = _build(
        _chronicle_event(
            public_event_type="aesthetic.frame_capture",
            frame_uri="/dev/shm/hapax-visual/frame.jpg",
            captured_at=GENERATED_AT,
        )
    )

    event = decision.public_event
    assert event is not None
    assert event.event_type == "aesthetic.frame_capture"
    assert event.state_kind == "aesthetic_frame"
    assert event.frame_ref is not None
    assert event.frame_ref.uri == "/dev/shm/hapax-visual/frame.jpg"
    assert "arena" in event.surface_policy.allowed_surfaces
    assert "replay" in event.surface_policy.allowed_surfaces


def test_missing_gate_provenance_refs_and_private_posture_hold_without_claims() -> None:
    decision = _build(
        _chronicle_event(
            grounding_gate_result=None,
            provenance_token=None,
            attribution_refs=[],
            chapter_label=None,
            timecode=None,
            rights_class="unknown",
            privacy_class="operator_private",
        )
    )

    event = decision.public_event
    assert event is not None
    assert event.surface_policy.allowed_surfaces == []
    assert event.surface_policy.claim_live is False
    assert event.surface_policy.claim_archive is False
    assert event.surface_policy.fallback_action == "private_only"
    assert event.surface_policy.dry_run_reason is not None
    for reason in (
        "missing_grounding_gate",
        "missing_provenance",
        "missing_surface_reference",
        "missing_attribution_ref",
        "rights_blocked",
        "privacy_blocked",
    ):
        assert reason in event.surface_policy.dry_run_reason
        assert reason in decision.unavailable_reasons


def test_egress_blocked_clean_archive_evidence_degrades_to_archive_only() -> None:
    decision = _build(
        _chronicle_event(
            grounding_gate_result=_gate(
                mode="public_archive",
                may_publish_live=False,
                may_publish_archive=True,
            ),
        ),
        egress=_egress(public_claim_allowed=False),
    )

    event = decision.public_event
    assert event is not None
    assert event.surface_policy.claim_live is False
    assert event.surface_policy.claim_archive is True
    assert event.surface_policy.allowed_surfaces == ["archive", "health"]
    assert event.surface_policy.fallback_action == "archive_only"
    assert event.surface_policy.dry_run_reason is None
    assert "egress_blocked" in decision.unavailable_reasons
    assert "blocker:egress_blocked" in event.provenance.evidence_refs


def test_below_threshold_and_explicit_internal_only_do_not_emit_public_event() -> None:
    below_threshold = _build(_chronicle_event(salience=0.2))
    internal_only = _build(_chronicle_event(public_event_type="internal_only"))

    assert is_chronicle_public_event_candidate(_chronicle_event()) is True
    assert is_chronicle_public_event_candidate(_chronicle_event(salience=0.2)) is False
    assert (
        is_chronicle_public_event_candidate(_chronicle_event(public_event_type="internal_only"))
        is False
    )
    assert below_threshold.status == "refused"
    assert below_threshold.public_event is None
    assert below_threshold.unavailable_reasons == ("below_salience_threshold",)
    assert internal_only.status == "refused"
    assert internal_only.public_event is None
    assert internal_only.unavailable_reasons == ("internal_only",)
