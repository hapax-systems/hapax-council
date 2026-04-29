"""Broadcast boundary ResearchVehiclePublicEvent producer tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agents.broadcast_boundary_public_event_producer import (
    BroadcastBoundaryPolicyConfig,
    BroadcastBoundaryPublicEventProducer,
    broadcast_boundary_event_id,
    build_broadcast_boundary_public_event,
)
from shared.livestream_egress_state import (
    EgressState,
    EvidenceStatus,
    FloorState,
    LivestreamEgressEvidence,
    LivestreamEgressState,
)

NOW = datetime(2026, 4, 29, 4, 30, tzinfo=UTC).timestamp()
GENERATED_AT = "2026-04-29T04:30:00Z"


def _legacy_event(**overrides: Any) -> dict[str, Any]:
    event = {
        "event_type": "broadcast_rotated",
        "timestamp": "2026-04-29T04:29:00Z",
        "outgoing_broadcast_id": "broadcast-old-111",
        "outgoing_vod_url": "https://www.youtube.com/watch?v=broadcast-old-111",
        "incoming_broadcast_id": "broadcast-new-444",
        "incoming_broadcast_url": "https://www.youtube.com/watch?v=broadcast-new-444",
        "elapsed_s": 40000,
        "seed_title": "Legomena Live - Segment 1",
        "seed_description_digest": "5cf6e1c055b4026d",
    }
    event.update(overrides)
    return event


def _egress(
    *,
    public_claim_allowed: bool = True,
    active_video_id: str | None = "broadcast-new-444",
    audio_floor: FloorState = FloorState.SATISFIED,
    stale: bool = False,
) -> LivestreamEgressState:
    return LivestreamEgressState(
        state=EgressState.PUBLIC_LIVE if public_claim_allowed else EgressState.PUBLIC_BLOCKED,
        confidence=1.0 if public_claim_allowed else 0.4,
        public_claim_allowed=public_claim_allowed,
        public_ready=public_claim_allowed,
        research_capture_ready=True,
        monetization_risk="none",
        privacy_floor=FloorState.SATISFIED,
        audio_floor=audio_floor,
        evidence=[
            LivestreamEgressEvidence(
                source="active_video_id",
                status=EvidenceStatus.PASS if active_video_id else EvidenceStatus.FAIL,
                summary="active id",
                observed={"video_id": active_video_id, "video_id_present": bool(active_video_id)},
                stale=stale,
            )
        ],
        last_transition=GENERATED_AT,
        operator_action="none",
    )


def _write_legacy(path: Path, event: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event) + "\n")


def _read_public_events(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_broadcast_boundary_event_creation_maps_legacy_rotation() -> None:
    event = build_broadcast_boundary_public_event(
        _legacy_event(),
        evidence_ref="/dev/shm/hapax-broadcast/events.jsonl#byte=0",
        egress_state=_egress(),
        quota_remaining=1500,
        generated_at=GENERATED_AT,
        now=NOW,
    )

    assert event.event_type == "broadcast.boundary"
    assert event.broadcast_id == "broadcast-new-444"
    assert event.source.substrate_id == "youtube_metadata"
    assert event.source.task_anchor == "broadcast-boundary-public-event-producer"
    assert event.public_url == "https://www.youtube.com/watch?v=broadcast-new-444"
    assert event.chapter_ref is not None
    assert event.chapter_ref.label == "Legomena Live - Segment 1"
    assert event.surface_policy.claim_live is True
    assert event.surface_policy.claim_archive is True
    assert event.surface_policy.claim_monetizable is False
    assert "youtube_description" in event.surface_policy.allowed_surfaces
    assert "youtube_shorts" in event.surface_policy.denied_surfaces
    assert event.provenance.token == f"broadcast_boundary:{event.event_id}"


def test_event_id_is_stable_and_schema_safe() -> None:
    first = broadcast_boundary_event_id(_legacy_event())
    second = broadcast_boundary_event_id(_legacy_event())

    assert first == second
    assert first.startswith("rvpe:broadcast_boundary:")
    assert "-" not in first


def test_policy_fails_closed_for_egress_quota_audio_and_missing_id() -> None:
    event = build_broadcast_boundary_public_event(
        _legacy_event(incoming_broadcast_id=None),
        evidence_ref="events.jsonl#byte=0",
        egress_state=_egress(
            public_claim_allowed=False,
            active_video_id=None,
            audio_floor=FloorState.BLOCKED,
            stale=True,
        ),
        quota_remaining=0,
        generated_at=GENERATED_AT,
        now=NOW,
    )

    policy = event.surface_policy
    assert policy.claim_live is False
    assert policy.claim_archive is False
    assert policy.allowed_surfaces == []
    assert policy.dry_run_reason is not None
    for blocker in (
        "egress_blocked",
        "stale_egress",
        "missing_active_video_id",
        "quota_exhausted",
        "audio_blocked",
    ):
        assert blocker in policy.dry_run_reason


def test_policy_fails_closed_for_missing_provenance_rights_and_privacy() -> None:
    event = build_broadcast_boundary_public_event(
        _legacy_event(seed_description_digest=None),
        evidence_ref="events.jsonl#byte=0",
        egress_state=_egress(),
        quota_remaining=1500,
        generated_at=GENERATED_AT,
        now=NOW,
        policy=BroadcastBoundaryPolicyConfig(
            rights_class="third_party_uncleared",
            privacy_class="operator_private",
        ),
    )

    assert event.provenance.token is None
    assert event.surface_policy.claim_live is False
    assert event.surface_policy.dry_run_reason is not None
    assert "missing_provenance" in event.surface_policy.dry_run_reason
    assert "rights_blocked" in event.surface_policy.dry_run_reason
    assert "privacy_blocked" in event.surface_policy.dry_run_reason


def test_producer_writes_public_event_and_advances_cursor(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.jsonl"
    public = tmp_path / "public.jsonl"
    cursor = tmp_path / "cursor.txt"
    _write_legacy(legacy, _legacy_event())
    producer = BroadcastBoundaryPublicEventProducer(
        legacy_event_path=legacy,
        public_event_path=public,
        cursor_path=cursor,
        egress_resolver=_egress,
        quota_remaining=lambda _endpoint: 1500,
        time_fn=lambda: NOW,
    )

    assert producer.run_once() == 1
    events = _read_public_events(public)
    assert len(events) == 1
    assert events[0]["event_type"] == "broadcast.boundary"
    assert events[0]["broadcast_id"] == "broadcast-new-444"
    assert int(cursor.read_text(encoding="utf-8")) == legacy.stat().st_size


def test_producer_preserves_legacy_bus_and_skips_duplicate_event_ids(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.jsonl"
    public = tmp_path / "public.jsonl"
    cursor = tmp_path / "cursor.txt"
    rotation = _legacy_event()
    _write_legacy(legacy, rotation)
    producer = BroadcastBoundaryPublicEventProducer(
        legacy_event_path=legacy,
        public_event_path=public,
        cursor_path=cursor,
        egress_resolver=_egress,
        quota_remaining=lambda _endpoint: 1500,
        time_fn=lambda: NOW,
    )

    assert producer.run_once() == 1
    cursor.unlink()
    assert producer.run_once() == 0
    assert len(_read_public_events(public)) == 1
    assert json.loads(legacy.read_text(encoding="utf-8").splitlines()[0]) == rotation


def test_truncation_resets_cursor_and_processes_new_file_from_start(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.jsonl"
    public = tmp_path / "public.jsonl"
    cursor = tmp_path / "cursor.txt"
    producer = BroadcastBoundaryPublicEventProducer(
        legacy_event_path=legacy,
        public_event_path=public,
        cursor_path=cursor,
        egress_resolver=lambda: _egress(active_video_id="broadcast-new-444"),
        quota_remaining=lambda _endpoint: 1500,
        time_fn=lambda: NOW,
    )
    _write_legacy(legacy, _legacy_event())
    assert producer.run_once() == 1

    truncated_event = {
        "event_type": "broadcast_rotated",
        "timestamp": "2026-04-29T04:29:30Z",
        "incoming_broadcast_id": "b555",
        "incoming_broadcast_url": "https://www.youtube.com/watch?v=b555",
        "seed_title": "Segment",
        "seed_description_digest": "abc123",
    }
    legacy.write_text(json.dumps(truncated_event) + "\n", encoding="utf-8")
    producer = BroadcastBoundaryPublicEventProducer(
        legacy_event_path=legacy,
        public_event_path=public,
        cursor_path=cursor,
        egress_resolver=lambda: _egress(active_video_id="b555"),
        quota_remaining=lambda _endpoint: 1500,
        time_fn=lambda: NOW,
    )

    assert producer.run_once() == 1
    events = _read_public_events(public)
    assert [event["broadcast_id"] for event in events] == ["broadcast-new-444", "b555"]
    assert int(cursor.read_text(encoding="utf-8")) == legacy.stat().st_size
