"""Tests for the director read-model public-event gate."""

from __future__ import annotations

from typing import Any

import pytest

from shared.director_read_model_public_event_gate import (
    INTERNAL_ONLY_EVENT_TYPES,
    derive_public_event_moves,
)
from shared.research_vehicle_public_event import (
    EventType,
    FallbackAction,
    PrivacyClass,
    PublicEventProvenance,
    PublicEventSource,
    PublicEventSurfacePolicy,
    ResearchVehiclePublicEvent,
    RightsClass,
    Surface,
)


def _provenance(
    *, token: str | None = "tok-abc", refs: list[str] | None = None
) -> PublicEventProvenance:
    return PublicEventProvenance(
        token=token,
        generated_at="2026-05-02T13:00:00Z",
        producer="test",
        evidence_refs=refs if refs is not None else ["evidence://x"],
        rights_basis="operator-original",
        citation_refs=[],
    )


def _surface_policy(
    *,
    allowed: list[Surface],
    denied: list[Surface] | None = None,
    claim_live: bool = True,
    claim_archive: bool = True,
    claim_monetizable: bool = False,
    requires_provenance: bool = True,
    fallback_action: FallbackAction = "dry_run",
    dry_run_reason: str | None = None,
) -> PublicEventSurfacePolicy:
    return PublicEventSurfacePolicy(
        allowed_surfaces=allowed,
        denied_surfaces=denied or [],
        claim_live=claim_live,
        claim_archive=claim_archive,
        claim_monetizable=claim_monetizable,
        requires_egress_public_claim=False,
        requires_audio_safe=False,
        requires_provenance=requires_provenance,
        requires_human_review=False,
        rate_limit_key=None,
        redaction_policy="none",
        fallback_action=fallback_action,
        dry_run_reason=dry_run_reason,
    )


def _event(
    *,
    event_id: str = "ev-1",
    event_type: EventType = "cuepoint.candidate",
    rights_class: RightsClass = "operator_original",
    privacy_class: PrivacyClass = "public_safe",
    provenance: PublicEventProvenance | None = None,
    surface_policy: PublicEventSurfacePolicy | None = None,
    **overrides: Any,
) -> ResearchVehiclePublicEvent:
    return ResearchVehiclePublicEvent(
        event_id=event_id,
        event_type=event_type,
        occurred_at="2026-05-02T13:00:00Z",
        broadcast_id=None,
        programme_id=None,
        condition_id=None,
        source=PublicEventSource(
            producer="test",
            substrate_id="sub-1",
            task_anchor=None,
            evidence_ref="evidence://src",
            freshness_ref=None,
        ),
        salience=0.5,
        state_kind=overrides.pop("state_kind", "cuepoint"),
        rights_class=rights_class,
        privacy_class=privacy_class,
        provenance=provenance or _provenance(),
        public_url=None,
        frame_ref=None,
        chapter_ref=None,
        attribution_refs=[],
        surface_policy=surface_policy or _surface_policy(allowed=["youtube_cuepoints"]),
        **overrides,
    )


# ── Internal-only events filter ───────────────────────────────────────


@pytest.mark.parametrize("internal_type", sorted(INTERNAL_ONLY_EVENT_TYPES))
def test_internal_only_events_produce_no_moves(internal_type: EventType) -> None:
    """broadcast.boundary, programme.boundary, condition.changed are internal."""
    event = _event(
        event_type=internal_type,
        state_kind="live_state",
        surface_policy=_surface_policy(allowed=["youtube_cuepoints"]),
    )
    moves = derive_public_event_moves([event])
    assert moves == []


# ── Public event types produce moves ──────────────────────────────────


def test_cuepoint_event_produces_cuepoint_move() -> None:
    event = _event(
        event_type="cuepoint.candidate",
        state_kind="cuepoint",
        surface_policy=_surface_policy(allowed=["youtube_cuepoints"]),
    )
    moves = derive_public_event_moves([event])
    assert len(moves) == 1
    move = moves[0]
    assert move.action_kind == "cuepoint"
    assert move.surface == "youtube_cuepoints"
    assert move.state == "allow"
    assert move.blocker_reasons == []
    assert move.source_event_id == "ev-1"


def test_caption_event_produces_caption_move() -> None:
    event = _event(
        event_type="caption.segment",
        state_kind="caption_text",
        surface_policy=_surface_policy(allowed=["youtube_captions"]),
    )
    moves = derive_public_event_moves([event])
    assert moves[0].action_kind == "caption"
    assert moves[0].state == "allow"


def test_chapter_event_produces_chapter_move() -> None:
    event = _event(
        event_type="chapter.marker",
        state_kind="chapter",
        surface_policy=_surface_policy(allowed=["youtube_chapters"]),
    )
    moves = derive_public_event_moves([event])
    assert moves[0].action_kind == "chapter"


def test_shorts_event_produces_shorts_move() -> None:
    event = _event(
        event_type="shorts.candidate",
        state_kind="short_form",
        surface_policy=_surface_policy(allowed=["youtube_shorts"]),
    )
    moves = derive_public_event_moves([event])
    assert moves[0].action_kind == "shorts"


def test_omg_statuslog_event_produces_social_move() -> None:
    event = _event(
        event_type="omg.statuslog",
        state_kind="public_post",
        surface_policy=_surface_policy(allowed=["omg_statuslog"]),
    )
    moves = derive_public_event_moves([event])
    assert moves[0].action_kind == "social"


def test_archive_event_produces_archive_move() -> None:
    event = _event(
        event_type="archive.segment",
        state_kind="archive_artifact",
        surface_policy=_surface_policy(allowed=["archive"], claim_live=False),
    )
    moves = derive_public_event_moves([event])
    assert moves[0].action_kind == "archive"
    assert moves[0].state == "allow"  # archive moves only need claim_archive


def test_monetization_event_blocked_when_claim_monetizable_false() -> None:
    event = _event(
        event_type="monetization.review",
        state_kind="monetization_state",
        surface_policy=_surface_policy(allowed=["monetization"], claim_monetizable=False),
    )
    moves = derive_public_event_moves([event])
    assert moves[0].action_kind == "monetization"
    assert moves[0].state == "deny"
    assert moves[0].blocker_reasons == ["claim_monetizable_false"]


def test_monetization_event_allowed_when_claim_monetizable_true() -> None:
    event = _event(
        event_type="monetization.review",
        state_kind="monetization_state",
        surface_policy=_surface_policy(allowed=["monetization"], claim_monetizable=True),
    )
    moves = derive_public_event_moves([event])
    assert moves[0].state == "allow"


# ── Rights / privacy / provenance gates ──────────────────────────────


def test_third_party_uncleared_rights_blocks() -> None:
    event = _event(
        rights_class="third_party_uncleared",
        surface_policy=_surface_policy(allowed=["youtube_cuepoints"], fallback_action="hold"),
    )
    moves = derive_public_event_moves([event])
    assert "rights_class_third_party_uncleared" in moves[0].blocker_reasons
    assert moves[0].state == "hold"


def test_operator_private_privacy_blocks() -> None:
    event = _event(
        privacy_class="operator_private",
        surface_policy=_surface_policy(allowed=["youtube_cuepoints"], fallback_action="dry_run"),
    )
    moves = derive_public_event_moves([event])
    assert "privacy_class_operator_private" in moves[0].blocker_reasons
    assert moves[0].state == "dry_run"


def test_consent_required_privacy_blocks() -> None:
    event = _event(
        privacy_class="consent_required",
        surface_policy=_surface_policy(
            allowed=["youtube_cuepoints"], fallback_action="operator_review"
        ),
    )
    moves = derive_public_event_moves([event])
    assert "privacy_class_consent_required" in moves[0].blocker_reasons
    assert moves[0].state == "hold"  # operator_review fallback maps to hold


def test_missing_provenance_evidence_blocks() -> None:
    event = _event(
        provenance=_provenance(refs=[]),
        surface_policy=_surface_policy(allowed=["youtube_cuepoints"], fallback_action="hold"),
    )
    moves = derive_public_event_moves([event])
    assert "missing_provenance_evidence" in moves[0].blocker_reasons


def test_missing_provenance_token_blocks_when_required() -> None:
    event = _event(
        provenance=_provenance(token=None, refs=["evidence://x"]),
        surface_policy=_surface_policy(
            allowed=["youtube_cuepoints"],
            requires_provenance=True,
            fallback_action="hold",
        ),
    )
    moves = derive_public_event_moves([event])
    assert "missing_provenance_token" in moves[0].blocker_reasons


# ── Surface policy: allowed/denied + claim_live ──────────────────────


def test_event_with_no_allowed_surfaces_emits_denied_move() -> None:
    event = _event(
        surface_policy=_surface_policy(allowed=[]),
    )
    moves = derive_public_event_moves([event])
    assert len(moves) == 1
    assert moves[0].state == "deny"
    assert "no_allowed_surfaces" in moves[0].blocker_reasons


def test_denied_surface_overrides_allowed() -> None:
    event = _event(
        surface_policy=_surface_policy(
            allowed=["youtube_cuepoints", "omg_statuslog"],
            denied=["youtube_cuepoints"],
        ),
    )
    moves = derive_public_event_moves([event])
    assert len(moves) == 2
    by_surface = {m.surface: m for m in moves}
    assert by_surface["youtube_cuepoints"].state == "deny"
    assert "surface_in_denied_list" in by_surface["youtube_cuepoints"].blocker_reasons
    assert by_surface["omg_statuslog"].state == "allow"


def test_claim_live_false_with_archive_falls_back_to_archive_only() -> None:
    event = _event(
        surface_policy=_surface_policy(
            allowed=["youtube_cuepoints"],
            claim_live=False,
            claim_archive=True,
        ),
    )
    moves = derive_public_event_moves([event])
    assert moves[0].state == "archive_only"
    assert "claim_live_false_archive_only" in moves[0].blocker_reasons


def test_claim_live_false_no_archive_falls_back() -> None:
    event = _event(
        surface_policy=_surface_policy(
            allowed=["youtube_cuepoints"],
            claim_live=False,
            claim_archive=False,
            fallback_action="dry_run",
        ),
    )
    moves = derive_public_event_moves([event])
    assert moves[0].state == "dry_run"


# ── Multi-event pipeline ─────────────────────────────────────────────


def test_multiple_events_produce_per_event_moves() -> None:
    events = [
        _event(
            event_id="ev-cue",
            event_type="cuepoint.candidate",
            state_kind="cuepoint",
            surface_policy=_surface_policy(allowed=["youtube_cuepoints"]),
        ),
        _event(
            event_id="ev-cap",
            event_type="caption.segment",
            state_kind="caption_text",
            surface_policy=_surface_policy(allowed=["youtube_captions"]),
        ),
        _event(
            event_id="ev-internal",
            event_type="broadcast.boundary",
            state_kind="live_state",
            surface_policy=_surface_policy(allowed=["youtube_cuepoints"]),
        ),
        _event(
            event_id="ev-arch",
            event_type="archive.segment",
            state_kind="archive_artifact",
            surface_policy=_surface_policy(allowed=["archive"], claim_live=False),
        ),
    ]
    moves = derive_public_event_moves(events)
    # internal event filtered; 3 public events → 3 moves
    assert len(moves) == 3
    assert {m.source_event_id for m in moves} == {"ev-cue", "ev-cap", "ev-arch"}
    assert all(m.action_kind in {"cuepoint", "caption", "archive"} for m in moves)


def test_event_with_multiple_allowed_surfaces_emits_per_surface_moves() -> None:
    event = _event(
        event_type="omg.weblog",
        state_kind="public_post",
        surface_policy=_surface_policy(allowed=["omg_weblog", "omg_statuslog"]),
    )
    moves = derive_public_event_moves([event])
    assert len(moves) == 2
    surfaces = {m.surface for m in moves}
    assert surfaces == {"omg_weblog", "omg_statuslog"}
    assert all(m.action_kind == "social" for m in moves)
