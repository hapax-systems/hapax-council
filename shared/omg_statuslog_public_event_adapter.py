"""OMG statuslog public-event adapter.

Project a stream of `ResearchVehiclePublicEvent` records into the subset
that is allowed to post to the omg.lol statuslog surface, with full
gate-decision provenance. The adapter is the canonical input the
OMG statuslog publisher consumes — supplanting the two prior parallel
paths that drifted out of sync:

  - `agents/operator_awareness/omg_lol_fanout.py` posts public-filtered
    awareness state hourly; runs `no_creds` because credentials were not
    wired and never had a public-event contract.
  - `agents/omg_statuslog_poster/poster.py` posts chronicle.high_salience
    events but did not consume the RVPE surface-policy contract.

This module collapses both paths to one rule: a status post is allowed
iff the event has surface `omg_statuslog` in its allowed_surfaces AND
the gate decision per `director_read_model_public_event_gate` resolves
to `state == "allow"`.

Awareness-state posting is intentionally NOT migrated here — that was a
hand-rolled summary loop without a public-event contract. The fanout
module remains as ad-hoc operator-awareness telemetry; this adapter
governs only RVPE-backed public statuses.

Spec: hapax-research/specs/2026-04-28-livestream-research-vehicle-suitcase-parent-spec.md
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.director_read_model_public_event_gate import (
    PublicEventMove,
    derive_public_event_moves,
)
from shared.research_vehicle_public_event import (
    EventType,
    ResearchVehiclePublicEvent,
)

OMG_STATUSLOG_SURFACE: Literal["omg_statuslog"] = "omg_statuslog"

STATUSLOG_ELIGIBLE_EVENT_TYPES: frozenset[EventType] = frozenset(
    {
        "chronicle.high_salience",
        "omg.statuslog",
    }
)


class StatuslogCandidate(BaseModel):
    """One RVPE record cleared to post to omg.lol /statuses.

    Pairs the source event with its omg-statuslog gate move so the
    publisher can record gate provenance alongside post outcomes.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event: ResearchVehiclePublicEvent
    move: PublicEventMove


class StatuslogRejection(BaseModel):
    """An RVPE record that was considered but is NOT cleared to post.

    Kept distinct from candidates so the publisher can emit a
    `result=denied` Prometheus counter row per blocker reason and so
    operator dashboards can show why eligible-looking events did not
    post.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str
    event_type: EventType
    state: str
    blocker_reasons: list[str] = Field(default_factory=list)


def select_statuslog_postable_events(
    events: Iterable[ResearchVehiclePublicEvent],
) -> tuple[list[StatuslogCandidate], list[StatuslogRejection]]:
    """Split an event stream into (postable, rejected) per the omg_statuslog gate.

    Only events whose `event_type` is in
    `STATUSLOG_ELIGIBLE_EVENT_TYPES` AND whose `surface_policy.allowed_surfaces`
    include `omg_statuslog` are considered. Of those, candidates are the
    ones whose gate decision resolves to `state == "allow"`; everything
    else (deny / hold / dry_run / archive_only / chapter_only) is a
    rejection.

    Internal-only event types (`broadcast.boundary`, `programme.boundary`,
    `condition.changed`) are filtered out by the upstream gate and never
    reach this adapter — even if they declared `omg_statuslog` in
    `allowed_surfaces`. That guards against accidental promotion of an
    internal boundary event into a public statuslog post.
    """

    candidates: list[StatuslogCandidate] = []
    rejections: list[StatuslogRejection] = []

    eligible_events = [
        event
        for event in events
        if event.event_type in STATUSLOG_ELIGIBLE_EVENT_TYPES
        and OMG_STATUSLOG_SURFACE in event.surface_policy.allowed_surfaces
    ]

    moves = derive_public_event_moves(eligible_events)
    moves_by_event_id = {
        f"{move.source_event_id}:{move.surface}": move
        for move in moves
        if move.surface == OMG_STATUSLOG_SURFACE
    }

    for event in eligible_events:
        key = f"{event.event_id}:{OMG_STATUSLOG_SURFACE}"
        move = moves_by_event_id.get(key)
        if move is None:
            rejections.append(
                StatuslogRejection(
                    event_id=event.event_id,
                    event_type=event.event_type,
                    state="filtered_no_move",
                    blocker_reasons=["upstream_gate_emitted_no_move_for_surface"],
                )
            )
            continue
        if move.state == "allow":
            candidates.append(StatuslogCandidate(event=event, move=move))
        else:
            rejections.append(
                StatuslogRejection(
                    event_id=event.event_id,
                    event_type=event.event_type,
                    state=move.state,
                    blocker_reasons=list(move.blocker_reasons),
                )
            )

    return candidates, rejections


__all__ = [
    "OMG_STATUSLOG_SURFACE",
    "STATUSLOG_ELIGIBLE_EVENT_TYPES",
    "StatuslogCandidate",
    "StatuslogRejection",
    "select_statuslog_postable_events",
]
