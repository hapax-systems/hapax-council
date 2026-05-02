"""Tests for the OMG statuslog public-event adapter."""

from __future__ import annotations

from typing import Any

from shared.omg_statuslog_public_event_adapter import (
    STATUSLOG_ELIGIBLE_EVENT_TYPES,
    select_statuslog_postable_events,
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
        generated_at="2026-05-02T14:00:00Z",
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
    requires_provenance: bool = True,
    fallback_action: FallbackAction = "dry_run",
) -> PublicEventSurfacePolicy:
    return PublicEventSurfacePolicy(
        allowed_surfaces=allowed,
        denied_surfaces=denied or [],
        claim_live=claim_live,
        claim_archive=claim_archive,
        claim_monetizable=False,
        requires_egress_public_claim=False,
        requires_audio_safe=False,
        requires_provenance=requires_provenance,
        requires_human_review=False,
        rate_limit_key=None,
        redaction_policy="none",
        fallback_action=fallback_action,
        dry_run_reason=None,
    )


def _event(
    *,
    event_id: str = "ev-1",
    event_type: EventType = "chronicle.high_salience",
    rights_class: RightsClass = "operator_original",
    privacy_class: PrivacyClass = "public_safe",
    provenance: PublicEventProvenance | None = None,
    surface_policy: PublicEventSurfacePolicy | None = None,
    **overrides: Any,
) -> ResearchVehiclePublicEvent:
    return ResearchVehiclePublicEvent(
        event_id=event_id,
        event_type=event_type,
        occurred_at="2026-05-02T14:00:00Z",
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
        salience=0.7,
        state_kind=overrides.pop("state_kind", "research_observation"),
        rights_class=rights_class,
        privacy_class=privacy_class,
        provenance=provenance or _provenance(),
        public_url=None,
        frame_ref=None,
        chapter_ref=None,
        attribution_refs=[],
        surface_policy=surface_policy or _surface_policy(allowed=["omg_statuslog"]),
        **overrides,
    )


# ── Eligibility filter ────────────────────────────────────────────────


def test_chronicle_high_salience_allowed_event_becomes_candidate() -> None:
    event = _event(event_type="chronicle.high_salience")
    candidates, rejections = select_statuslog_postable_events([event])
    assert len(candidates) == 1
    assert candidates[0].event.event_id == "ev-1"
    assert candidates[0].move.state == "allow"
    assert candidates[0].move.surface == "omg_statuslog"
    assert rejections == []


def test_omg_statuslog_event_type_also_allowed() -> None:
    event = _event(
        event_type="omg.statuslog",
        state_kind="public_post",
        surface_policy=_surface_policy(allowed=["omg_statuslog"]),
    )
    candidates, _ = select_statuslog_postable_events([event])
    assert len(candidates) == 1
    assert candidates[0].event.event_type == "omg.statuslog"


def test_eligible_event_set_is_explicit() -> None:
    """Defensive: pin the eligible event set so silent type drift is caught."""
    assert frozenset({"chronicle.high_salience", "omg.statuslog"}) == STATUSLOG_ELIGIBLE_EVENT_TYPES


def test_non_eligible_event_type_filtered_out() -> None:
    event = _event(
        event_type="cuepoint.candidate",
        state_kind="cuepoint",
        surface_policy=_surface_policy(allowed=["omg_statuslog"]),
    )
    candidates, rejections = select_statuslog_postable_events([event])
    assert candidates == []
    assert rejections == []  # filtered before gate, never considered


def test_event_without_omg_statuslog_in_allowed_surfaces_filtered() -> None:
    event = _event(
        event_type="chronicle.high_salience",
        surface_policy=_surface_policy(allowed=["youtube_cuepoints"]),
    )
    candidates, rejections = select_statuslog_postable_events([event])
    assert candidates == []
    assert rejections == []


# ── Internal-only events (broadcast.boundary, etc.) never reach surface ──


def test_broadcast_boundary_with_omg_statuslog_in_allowed_surfaces_does_not_post() -> None:
    """Even if a boundary event mis-declares omg_statuslog as allowed, the
    upstream director-read-model gate filters internal events out before
    this adapter sees them."""
    event = _event(
        event_type="broadcast.boundary",
        state_kind="live_state",
        surface_policy=_surface_policy(allowed=["omg_statuslog"]),
    )
    candidates, rejections = select_statuslog_postable_events([event])
    assert candidates == []
    # Filtered before gate (event_type not in eligible set).
    assert rejections == []


# ── Gate decisions become rejections ─────────────────────────────────


def test_denied_surface_rejects_with_provenance() -> None:
    event = _event(
        event_type="chronicle.high_salience",
        surface_policy=_surface_policy(
            allowed=["omg_statuslog"],
            denied=["omg_statuslog"],
        ),
    )
    candidates, rejections = select_statuslog_postable_events([event])
    assert candidates == []
    assert len(rejections) == 1
    assert rejections[0].event_id == "ev-1"
    assert rejections[0].state == "deny"
    assert "surface_in_denied_list" in rejections[0].blocker_reasons


def test_third_party_uncleared_rights_rejects() -> None:
    event = _event(
        event_type="chronicle.high_salience",
        rights_class="third_party_uncleared",
        surface_policy=_surface_policy(allowed=["omg_statuslog"], fallback_action="hold"),
    )
    candidates, rejections = select_statuslog_postable_events([event])
    assert candidates == []
    assert len(rejections) == 1
    assert rejections[0].state == "hold"
    assert "rights_class_third_party_uncleared" in rejections[0].blocker_reasons


def test_operator_private_privacy_rejects() -> None:
    event = _event(
        event_type="chronicle.high_salience",
        privacy_class="operator_private",
        surface_policy=_surface_policy(allowed=["omg_statuslog"], fallback_action="dry_run"),
    )
    candidates, rejections = select_statuslog_postable_events([event])
    assert candidates == []
    assert rejections[0].state == "dry_run"
    assert "privacy_class_operator_private" in rejections[0].blocker_reasons


def test_missing_provenance_token_rejects() -> None:
    event = _event(
        event_type="chronicle.high_salience",
        provenance=_provenance(token=None, refs=["evidence://x"]),
        surface_policy=_surface_policy(
            allowed=["omg_statuslog"],
            requires_provenance=True,
            fallback_action="hold",
        ),
    )
    candidates, rejections = select_statuslog_postable_events([event])
    assert candidates == []
    assert "missing_provenance_token" in rejections[0].blocker_reasons


def test_claim_live_false_with_archive_archive_only_rejects() -> None:
    event = _event(
        event_type="chronicle.high_salience",
        surface_policy=_surface_policy(
            allowed=["omg_statuslog"],
            claim_live=False,
            claim_archive=True,
        ),
    )
    candidates, rejections = select_statuslog_postable_events([event])
    assert candidates == []
    assert rejections[0].state == "archive_only"


# ── Multi-event partition ───────────────────────────────────────────


def test_mixed_event_stream_partitions_correctly() -> None:
    events = [
        # 1 candidate (allow)
        _event(
            event_id="ev-allow",
            event_type="chronicle.high_salience",
            surface_policy=_surface_policy(allowed=["omg_statuslog"]),
        ),
        # 1 rejection (denied surface)
        _event(
            event_id="ev-deny",
            event_type="chronicle.high_salience",
            surface_policy=_surface_policy(allowed=["omg_statuslog"], denied=["omg_statuslog"]),
        ),
        # filtered (wrong surface)
        _event(
            event_id="ev-other-surface",
            event_type="chronicle.high_salience",
            surface_policy=_surface_policy(allowed=["youtube_cuepoints"]),
        ),
        # filtered (wrong type)
        _event(
            event_id="ev-cuepoint",
            event_type="cuepoint.candidate",
            state_kind="cuepoint",
            surface_policy=_surface_policy(allowed=["omg_statuslog"]),
        ),
        # filtered (internal-only event_type)
        _event(
            event_id="ev-boundary",
            event_type="broadcast.boundary",
            state_kind="live_state",
            surface_policy=_surface_policy(allowed=["omg_statuslog"]),
        ),
    ]
    candidates, rejections = select_statuslog_postable_events(events)
    assert [c.event.event_id for c in candidates] == ["ev-allow"]
    assert [r.event_id for r in rejections] == ["ev-deny"]


def test_iterator_input_is_consumed_safely() -> None:
    """The adapter accepts any Iterable, including one-shot generators."""
    events = (_event(event_type="chronicle.high_salience"),)
    candidates, rejections = select_statuslog_postable_events(iter(events))
    assert len(candidates) == 1
    assert rejections == []
