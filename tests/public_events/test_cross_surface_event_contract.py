"""Tests for the shared cross-surface public-event contract."""

from __future__ import annotations

import json
from typing import Any

import jsonschema

from shared.cross_surface_event_contract import (
    ALL_FANOUT_ACTIONS,
    CROSS_SURFACE_APERTURES,
    cross_surface_contract_payload,
    cross_surface_decision_id,
    decide_cross_surface_fanout,
    get_aperture_contract,
)
from shared.research_vehicle_public_event import (
    PublicEventChapterRef,
    PublicEventProvenance,
    PublicEventSource,
    PublicEventSurfacePolicy,
    ResearchVehiclePublicEvent,
)


def _event(**overrides: Any) -> ResearchVehiclePublicEvent:
    payload = {
        "schema_version": 1,
        "event_id": "rvpe:broadcast_boundary:20260429t043000z:b444",
        "event_type": "broadcast.boundary",
        "occurred_at": "2026-04-29T04:30:00Z",
        "broadcast_id": "b444",
        "programme_id": None,
        "condition_id": None,
        "source": PublicEventSource(
            producer="tests",
            substrate_id="youtube_metadata",
            task_anchor="cross-surface-event-contract",
            evidence_ref="tests#event",
            freshness_ref="tests.age_s",
        ),
        "salience": 0.7,
        "state_kind": "live_state",
        "rights_class": "operator_original",
        "privacy_class": "public_safe",
        "provenance": PublicEventProvenance(
            token="event-token",
            generated_at="2026-04-29T04:30:01Z",
            producer="tests",
            evidence_refs=["test.evidence"],
            rights_basis="operator generated test fixture",
            citation_refs=[],
        ),
        "public_url": "https://www.youtube.com/watch?v=b444",
        "frame_ref": None,
        "chapter_ref": PublicEventChapterRef(
            kind="chapter",
            label="Boundary",
            timecode="00:00",
            source_event_id="rvpe:broadcast_boundary:20260429t043000z:b444",
        ),
        "attribution_refs": [],
        "surface_policy": PublicEventSurfacePolicy(
            allowed_surfaces=[
                "youtube_description",
                "youtube_chapters",
                "omg_statuslog",
                "mastodon",
                "bluesky",
                "discord",
                "archive",
                "replay",
                "health",
            ],
            denied_surfaces=["youtube_shorts", "arena", "omg_weblog"],
            claim_live=True,
            claim_archive=True,
            claim_monetizable=False,
            requires_egress_public_claim=True,
            requires_audio_safe=True,
            requires_provenance=True,
            requires_human_review=False,
            rate_limit_key="broadcast.boundary:live_state",
            redaction_policy="operator_referent",
            fallback_action="hold",
            dry_run_reason=None,
        ),
    }
    payload.update(overrides)
    return ResearchVehiclePublicEvent(**payload)


def test_contract_payload_is_schema_valid_and_covers_required_apertures() -> None:
    payload = cross_surface_contract_payload()
    schema = json.loads(
        open("schemas/cross-surface-event-contract.schema.json", encoding="utf-8").read()
    )

    jsonschema.validate(payload, schema)

    assert set(payload["actions"]) == set(ALL_FANOUT_ACTIONS)
    assert {aperture.aperture_id for aperture in CROSS_SURFACE_APERTURES} == {
        "youtube",
        "youtube_channel_trailer",
        "omg_statuslog",
        "omg_weblog",
        "arena",
        "mastodon",
        "bluesky",
        "discord",
        "shorts",
        "archive",
        "replay",
    }
    realities = {
        aperture.aperture_id: aperture.current_reality for aperture in CROSS_SURFACE_APERTURES
    }
    assert realities["mastodon"] == "active_canonical"
    assert realities["bluesky"] == "active_canonical"
    assert realities["youtube_channel_trailer"] == "credential_blocked"


def test_publish_decision_allows_policy_matching_mastodon_event() -> None:
    event = _event()
    decision = decide_cross_surface_fanout(event, "mastodon", "publish")

    assert decision.decision == "allow"
    assert decision.resolved_action == "publish"
    assert decision.health_status == "ok"
    assert decision.target_surfaces == ["mastodon"]
    assert decision.reasons == ["policy_allowed"]
    assert decision.failure_event_type is None
    assert decision.decision_id == cross_surface_decision_id(
        event.event_id,
        target_aperture="mastodon",
        requested_action="publish",
    )


def test_denied_surface_becomes_failure_event_and_health_blocker() -> None:
    decision = decide_cross_surface_fanout(_event(), "shorts", "publish")

    assert decision.decision == "deny"
    assert decision.resolved_action == "hold"
    assert decision.health_status == "blocked"
    assert decision.failure_event_type == "fanout.decision"
    assert decision.failure_event_id is not None
    assert "event_type_not_allowed" in decision.reasons
    assert "surface_denied" in decision.reasons
    assert decision.child_task == "shorts-public-event-adapter"


def test_operator_review_surface_holds_autonomous_publish() -> None:
    event = _event(
        event_id="rvpe:omg_weblog:20260429",
        event_type="omg.weblog",
        state_kind="public_post",
        surface_policy=PublicEventSurfacePolicy(
            allowed_surfaces=["omg_weblog", "archive"],
            denied_surfaces=[],
            claim_live=True,
            claim_archive=True,
            claim_monetizable=False,
            requires_egress_public_claim=False,
            requires_audio_safe=False,
            requires_provenance=True,
            requires_human_review=False,
            rate_limit_key="omg.weblog:public_post",
            redaction_policy="human_review",
            fallback_action="operator_review",
            dry_run_reason=None,
        ),
    )

    decision = decide_cross_surface_fanout(event, "omg_weblog", "publish")

    assert decision.decision == "hold"
    assert decision.resolved_action == "hold"
    assert decision.health_status == "degraded"
    assert decision.failure_event_type == "fanout.decision"
    assert decision.reasons == ["human_review_required"]


def test_weblog_event_allows_social_and_arena_fanout() -> None:
    event = _event(
        event_id="rvpe:omg_weblog:visibility_engine",
        event_type="omg.weblog",
        state_kind="public_post",
        public_url="https://hapax.weblog.lol/visibility-engine",
        surface_policy=PublicEventSurfacePolicy(
            allowed_surfaces=["mastodon", "bluesky", "arena", "archive"],
            denied_surfaces=[],
            claim_live=False,
            claim_archive=True,
            claim_monetizable=False,
            requires_egress_public_claim=False,
            requires_audio_safe=False,
            requires_provenance=True,
            requires_human_review=False,
            rate_limit_key="omg.weblog:public_post",
            redaction_policy="none",
            fallback_action="hold",
            dry_run_reason=None,
        ),
    )

    for aperture in ("mastodon", "bluesky", "arena"):
        decision = decide_cross_surface_fanout(event, aperture, "publish")
        assert decision.decision == "allow", (aperture, decision.reasons)
        assert decision.target_surfaces == [aperture]


def test_non_broadcast_social_events_are_in_fanout_contract() -> None:
    expected = {"governance.enforcement", "omg.weblog", "velocity.digest"}

    for aperture in ("mastodon", "bluesky", "arena"):
        contract = get_aperture_contract(aperture)
        assert expected <= set(contract.allowed_event_types)


def test_non_broadcast_social_events_bypass_stale_egress_gate() -> None:
    cases = (
        ("omg.weblog", "public_post"),
        ("velocity.digest", "research_observation"),
        ("governance.enforcement", "governance_state"),
    )

    for event_type, state_kind in cases:
        event = _event(
            event_id=f"rvpe:{event_type.replace('.', '_')}:egress_bypass",
            event_type=event_type,
            state_kind=state_kind,
            broadcast_id=None,
            public_url="https://hapax.weblog.lol/visibility-engine",
            surface_policy=PublicEventSurfacePolicy(
                allowed_surfaces=["mastodon", "bluesky", "arena", "archive"],
                denied_surfaces=[],
                claim_live=False,
                claim_archive=True,
                claim_monetizable=False,
                requires_egress_public_claim=True,
                requires_audio_safe=True,
                requires_provenance=True,
                requires_human_review=False,
                rate_limit_key=f"{event_type}:{state_kind}",
                redaction_policy="none",
                fallback_action="hold",
                dry_run_reason=None,
            ),
        )

        for aperture in ("mastodon", "bluesky", "arena"):
            decision = decide_cross_surface_fanout(event, aperture, "publish")
            assert decision.decision == "allow", (event_type, aperture, decision.reasons)
            assert "egress_blocked" not in decision.reasons


def test_broadcast_boundary_still_requires_live_egress_claim() -> None:
    event = _event(
        surface_policy=PublicEventSurfacePolicy(
            allowed_surfaces=["mastodon", "archive"],
            denied_surfaces=[],
            claim_live=False,
            claim_archive=True,
            claim_monetizable=False,
            requires_egress_public_claim=True,
            requires_audio_safe=True,
            requires_provenance=True,
            requires_human_review=False,
            rate_limit_key="broadcast.boundary:live_state",
            redaction_policy="operator_referent",
            fallback_action="hold",
            dry_run_reason=None,
        )
    )

    decision = decide_cross_surface_fanout(event, "mastodon", "publish")

    assert decision.decision == "hold"
    assert decision.health_status == "degraded"
    assert "egress_blocked" in decision.reasons


def test_archive_and_replay_actions_use_archive_claim_and_refs() -> None:
    event = _event()

    archive_decision = decide_cross_surface_fanout(event, "archive", "archive")
    assert archive_decision.decision == "allow"
    assert archive_decision.resolved_action == "archive"

    blocked_replay = decide_cross_surface_fanout(
        _event(
            surface_policy=PublicEventSurfacePolicy(
                allowed_surfaces=["replay"],
                denied_surfaces=[],
                claim_live=True,
                claim_archive=False,
                claim_monetizable=False,
                requires_egress_public_claim=True,
                requires_audio_safe=True,
                requires_provenance=True,
                requires_human_review=False,
                rate_limit_key="replay:test",
                redaction_policy="none",
                fallback_action="hold",
                dry_run_reason=None,
            )
        ),
        "replay",
        "replay",
    )
    assert blocked_replay.decision == "hold"
    assert blocked_replay.health_status == "degraded"
    assert "replay_claim_blocked" in blocked_replay.reasons


def test_rights_privacy_and_provenance_fail_closed() -> None:
    event = _event(
        rights_class="unknown",
        privacy_class="operator_private",
        provenance=PublicEventProvenance(
            token=None,
            generated_at="2026-04-29T04:30:01Z",
            producer="tests",
            evidence_refs=["test.evidence"],
            rights_basis="unknown",
            citation_refs=[],
        ),
    )

    decision = decide_cross_surface_fanout(event, "mastodon", "publish")

    assert decision.decision == "deny"
    assert decision.health_status == "blocked"
    assert "rights_blocked" in decision.reasons
    assert "privacy_blocked" in decision.reasons
    assert "missing_provenance" in decision.reasons
