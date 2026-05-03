"""Tests for the replay demo residency kit."""

from __future__ import annotations

from shared.archive_replay_public_events import ArchiveReplayPublicLinkDecision
from shared.replay_demo_card import (
    PRODUCER,
    PUBLIC_SAFE_PRIVACY,
    PUBLIC_SAFE_RIGHTS,
    TASK_ANCHOR,
    generate_demo_cards,
)
from shared.research_vehicle_public_event import (
    PublicEventChapterRef,
    PublicEventFrameRef,
    PublicEventProvenance,
    PublicEventSource,
    PublicEventSurfacePolicy,
    ResearchVehiclePublicEvent,
)

N1_EXPLANATION = "n=1 epistemic lab — operator narrates own work; replay shows what was visible."
SUGGESTED_AUDIENCE = "researchers studying executive-function externalization"


def _surface_policy() -> PublicEventSurfacePolicy:
    return PublicEventSurfacePolicy(
        allowed_surfaces=["archive", "replay"],
        denied_surfaces=[],
        claim_live=False,
        claim_archive=True,
        claim_monetizable=False,
        requires_egress_public_claim=True,
        requires_audio_safe=True,
        requires_provenance=True,
        requires_human_review=False,
        rate_limit_key="archive.segment",
        redaction_policy="none",
        fallback_action="hold",
        dry_run_reason=None,
    )


def _public_event(
    *,
    rights_class: str = "operator_original",
    privacy_class: str = "public_safe",
    event_id: str = "rvpe:archive_replay:test_001",
    public_url: str | None = "https://hapax.example/replay/001",
    chapter_label: str | None = "Open the day",
    chapter_timecode: str | None = "00:00",
    frame_uri: str | None = "https://hapax.example/frames/001.jpg",
    programme_id: str | None = "prog_001",
    broadcast_id: str | None = "bcast_001",
) -> ResearchVehiclePublicEvent:
    chapter_ref = (
        PublicEventChapterRef(
            kind="chapter",
            label=chapter_label,
            timecode=chapter_timecode,
            source_event_id=event_id,
        )
        if chapter_label and chapter_timecode
        else None
    )
    frame_ref = (
        PublicEventFrameRef(
            kind="frame",
            uri=frame_uri,
            captured_at="2026-04-30T10:00:00Z",
            source_event_id=event_id,
        )
        if frame_uri
        else None
    )
    return ResearchVehiclePublicEvent(
        event_id=event_id,
        event_type="archive.segment",
        occurred_at="2026-04-30T10:00:00Z",
        broadcast_id=broadcast_id,
        programme_id=programme_id,
        condition_id=None,
        source=PublicEventSource(
            producer="shared.archive_replay_public_events",
            substrate_id="archive_replay",
            task_anchor="archive-replay-public-event-link-adapter",
            evidence_ref="sidecar:abc",
            freshness_ref=None,
        ),
        salience=0.6,
        state_kind="archive_artifact",
        rights_class=rights_class,  # type: ignore[arg-type]
        privacy_class=privacy_class,  # type: ignore[arg-type]
        provenance=PublicEventProvenance(
            token="prov_token_001",
            generated_at="2026-04-30T10:01:00Z",
            producer="shared.archive_replay_public_events",
            evidence_refs=["sidecar:abc", "span:span_001"],
            rights_basis="operator generated archive segment",
            citation_refs=[],
        ),
        public_url=public_url,
        frame_ref=frame_ref,
        chapter_ref=chapter_ref,
        attribution_refs=[],
        surface_policy=_surface_policy(),
    )


def _decision(
    *,
    status: str = "emitted",
    public_event: ResearchVehiclePublicEvent | None = None,
    decision_id: str = "archive_replay_decision:rvpe:archive_replay:test_001",
    unavailable: tuple[str, ...] = (),
) -> ArchiveReplayPublicLinkDecision:
    return ArchiveReplayPublicLinkDecision(
        decision_id=decision_id,
        idempotency_key="rvpe:archive_replay:test_001",
        status=status,  # type: ignore[arg-type]
        archive_capture_claim_allowed=True,
        public_replay_link_claim_allowed=(status == "emitted"),
        public_event=public_event if status == "emitted" else None,
        unavailable_reasons=unavailable,
        source_segment_refs=("seg_001",),
        temporal_span_refs=("span_001",),
        gate_refs=("gate_001",),
        evidence_freshness_ref="2026-04-30T10:00:00Z",
        span_gate_status="pass",
        span_gate_reason_codes=(),
    )


# ── Module constants ────────────────────────────────────────────────


class TestModuleConstants:
    def test_task_anchor_pinned(self) -> None:
        assert TASK_ANCHOR == "replay-demo-residency-kit"

    def test_producer_pinned(self) -> None:
        assert PRODUCER == "shared.replay_demo_card"

    def test_rights_set_matches_upstream_adapter(self) -> None:
        assert (
            frozenset({"operator_original", "operator_controlled", "third_party_attributed"})
            == PUBLIC_SAFE_RIGHTS
        )

    def test_privacy_set_matches_upstream_adapter(self) -> None:
        assert frozenset({"public_safe", "aggregate_only"}) == PUBLIC_SAFE_PRIVACY


# ── AC#2 happy path: emitted decision → card ────────────────────────


class TestHappyPath:
    def test_emitted_public_safe_decision_yields_card(self) -> None:
        ev = _public_event()
        decision = _decision(public_event=ev)
        cards, skips = generate_demo_cards(
            [decision],
            n1_explanation=N1_EXPLANATION,
            suggested_audience=SUGGESTED_AUDIENCE,
        )
        assert skips == []
        assert len(cards) == 1
        c = cards[0]
        assert c.event_id == ev.event_id
        assert c.public_url == "https://hapax.example/replay/001"
        assert c.replay_title == "Open the day"
        assert c.chapter_label == "Open the day"
        assert c.chapter_timecode == "00:00"
        assert c.frame_uri == "https://hapax.example/frames/001.jpg"
        assert c.frame_kind == "frame"
        assert c.provenance_token == "prov_token_001"
        assert "sidecar:abc" in c.provenance_evidence_refs
        assert c.rights_class == "operator_original"
        assert c.privacy_class == "public_safe"
        assert c.n1_explanation == N1_EXPLANATION
        assert c.suggested_audience == SUGGESTED_AUDIENCE
        assert c.programme_id == "prog_001"
        assert c.broadcast_id == "bcast_001"

    def test_card_falls_back_to_event_id_when_no_chapter_ref(self) -> None:
        ev = _public_event(chapter_label=None, chapter_timecode=None)
        decision = _decision(public_event=ev)
        cards, _ = generate_demo_cards(
            [decision], n1_explanation=N1_EXPLANATION, suggested_audience=SUGGESTED_AUDIENCE
        )
        assert cards[0].replay_title == ev.event_id
        assert cards[0].chapter_label is None
        assert cards[0].chapter_timecode is None


# ── AC#5 fail-closed gates ──────────────────────────────────────────


class TestFailClosed:
    def test_held_decision_skipped(self) -> None:
        decision = _decision(status="held", unavailable=("public_replay_url_missing",))
        cards, skips = generate_demo_cards(
            [decision], n1_explanation=N1_EXPLANATION, suggested_audience=SUGGESTED_AUDIENCE
        )
        assert cards == []
        assert len(skips) == 1
        assert skips[0].reason == "decision_status_not_emitted"
        assert "status=held" in skips[0].detail
        assert "public_replay_url_missing" in skips[0].detail

    def test_refused_decision_skipped(self) -> None:
        decision = _decision(status="refused", unavailable=("rights_privacy_blocked",))
        cards, skips = generate_demo_cards(
            [decision], n1_explanation=N1_EXPLANATION, suggested_audience=SUGGESTED_AUDIENCE
        )
        assert cards == []
        assert skips[0].reason == "decision_status_not_emitted"

    def test_unsafe_rights_class_skipped(self) -> None:
        ev = _public_event(rights_class="third_party_uncleared")
        decision = _decision(public_event=ev)
        cards, skips = generate_demo_cards(
            [decision], n1_explanation=N1_EXPLANATION, suggested_audience=SUGGESTED_AUDIENCE
        )
        assert cards == []
        assert len(skips) == 1
        assert skips[0].reason == "rights_class_not_public_safe"
        assert "third_party_uncleared" in skips[0].detail

    def test_consent_required_privacy_class_skipped(self) -> None:
        ev = _public_event(privacy_class="consent_required")
        decision = _decision(public_event=ev)
        cards, skips = generate_demo_cards(
            [decision], n1_explanation=N1_EXPLANATION, suggested_audience=SUGGESTED_AUDIENCE
        )
        assert cards == []
        assert len(skips) == 1
        assert skips[0].reason == "privacy_class_not_public_safe"
        assert "consent_required" in skips[0].detail

    def test_aggregate_only_privacy_passes(self) -> None:
        """`aggregate_only` is in the public-safe set; this guards
        against an over-eager refactor that narrows it to only
        `public_safe`."""
        ev = _public_event(privacy_class="aggregate_only")
        decision = _decision(public_event=ev)
        cards, _ = generate_demo_cards(
            [decision], n1_explanation=N1_EXPLANATION, suggested_audience=SUGGESTED_AUDIENCE
        )
        assert len(cards) == 1
        assert cards[0].privacy_class == "aggregate_only"


# ── AC#2 mixed input: every decision accounted for ──────────────────


class TestAccounting:
    def test_every_decision_either_card_or_skip(self) -> None:
        emitted_ev = _public_event(event_id="rvpe:ok")
        emitted = _decision(public_event=emitted_ev, decision_id="dec_ok")
        held = _decision(
            status="held",
            unavailable=("public_replay_url_missing",),
            decision_id="dec_held",
        )
        unsafe_ev = _public_event(rights_class="third_party_uncleared", event_id="rvpe:unsafe")
        unsafe = _decision(public_event=unsafe_ev, decision_id="dec_unsafe")
        cards, skips = generate_demo_cards(
            [emitted, held, unsafe],
            n1_explanation=N1_EXPLANATION,
            suggested_audience=SUGGESTED_AUDIENCE,
        )
        assert len(cards) == 1
        assert len(skips) == 2
        # All inputs accounted for — no silent drops.
        assert len(cards) + len(skips) == 3


# ── Empty input ─────────────────────────────────────────────────────


class TestEmpty:
    def test_no_decisions_returns_empty(self) -> None:
        cards, skips = generate_demo_cards(
            [], n1_explanation=N1_EXPLANATION, suggested_audience=SUGGESTED_AUDIENCE
        )
        assert cards == []
        assert skips == []
