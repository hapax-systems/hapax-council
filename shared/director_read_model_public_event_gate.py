"""Director read-model public-event gate.

Project ResearchVehiclePublicEvent (RVPE) records into director-consumable
public-event moves with explicit gate decisions per surface.

Director public moves cannot outrun public-event truth — a move emitted here
must be backed by a witnessed RVPE record AND must satisfy the event's
surface-policy constraints (rights / privacy / provenance / claim posture).
Internal-only events (`broadcast.boundary`, `programme.boundary`,
`condition.changed`) do NOT imply public publication and are filtered out
fail-closed.

Each emitted `PublicEventMove` carries:
  - `action_kind` — the director-facing category (cuepoint / caption / chapter
    / shorts / social / archive / replay / support / monetization)
  - `surface` — the specific public surface (e.g. youtube_cuepoints, omg_weblog)
  - `state` — allow / deny / hold / dry_run / archive_only / chapter_only
  - `blocker_reasons` — non-empty when the surface_policy gates fail
  - `fallback_action` — directly from the event's surface_policy
  - `source_event_id` — the originating RVPE record's `event_id`

Spec: hapax-research/specs/2026-04-29-director-world-surface-read-model.md §
   `director-read-model-public-event-gate`.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.research_vehicle_public_event import (
    EventType,
    FallbackAction,
    PrivacyClass,
    ResearchVehiclePublicEvent,
    RightsClass,
    Surface,
)

ActionKind = Literal[
    "cuepoint",
    "caption",
    "chapter",
    "shorts",
    "social",
    "archive",
    "replay",
    "support",
    "monetization",
]

MoveState = Literal[
    "allow",
    "deny",
    "hold",
    "dry_run",
    "archive_only",
    "chapter_only",
]

INTERNAL_ONLY_EVENT_TYPES: frozenset[EventType] = frozenset(
    {
        "broadcast.boundary",
        "programme.boundary",
        "condition.changed",
    }
)

_EVENT_TYPE_TO_ACTION_KIND: dict[EventType, ActionKind] = {
    "cuepoint.candidate": "cuepoint",
    "caption.segment": "caption",
    "chapter.marker": "chapter",
    "shorts.candidate": "shorts",
    "shorts.upload": "shorts",
    "metadata.update": "social",
    "channel_section.candidate": "social",
    "arena_block.candidate": "social",
    "omg.statuslog": "social",
    "omg.weblog": "social",
    "publication.artifact": "archive",
    "archive.segment": "archive",
    "monetization.review": "monetization",
    "fanout.decision": "social",
    "chronicle.high_salience": "social",
    "aesthetic.frame_capture": "archive",
}

_INSUFFICIENT_RIGHTS: frozenset[RightsClass] = frozenset({"third_party_uncleared", "unknown"})
_INSUFFICIENT_PRIVACY: frozenset[PrivacyClass] = frozenset(
    {"operator_private", "consent_required", "unknown"}
)
_NON_PUBLIC_FALLBACKS: frozenset[FallbackAction] = frozenset(
    {"hold", "dry_run", "private_only", "operator_review", "deny"}
)


class PublicEventMove(BaseModel):
    """A director-consumable public-event action with gate decision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_event_id: str
    event_type: EventType
    action_kind: ActionKind
    surface: Surface
    state: MoveState
    fallback_action: FallbackAction
    blocker_reasons: list[str] = Field(default_factory=list)


def derive_public_event_moves(
    events: Iterable[ResearchVehiclePublicEvent],
) -> list[PublicEventMove]:
    """Project RVPE records into director-consumable public-event moves.

    Returns one move per (event, allowed_surface) pair, with per-surface gate
    state. Internal-only events are filtered out — they do not imply public
    publication.
    """

    moves: list[PublicEventMove] = []
    for event in events:
        if event.event_type in INTERNAL_ONLY_EVENT_TYPES:
            continue
        action_kind = _EVENT_TYPE_TO_ACTION_KIND.get(event.event_type)
        if action_kind is None:
            continue
        moves.extend(_moves_for_event(event, action_kind))
    return moves


def _moves_for_event(
    event: ResearchVehiclePublicEvent,
    action_kind: ActionKind,
) -> list[PublicEventMove]:
    policy = event.surface_policy
    surfaces = list(policy.allowed_surfaces)
    if not surfaces:
        return [_denied_move(event, action_kind, surface=None)]

    moves: list[PublicEventMove] = []
    for surface in surfaces:
        if surface in policy.denied_surfaces:
            moves.append(
                _move(
                    event,
                    action_kind,
                    surface,
                    state="deny",
                    blocker_reasons=["surface_in_denied_list"],
                )
            )
            continue
        blocker_reasons = _blocker_reasons_for_event(event)
        if blocker_reasons:
            state = _blocked_state(policy.fallback_action)
            moves.append(
                _move(
                    event,
                    action_kind,
                    surface,
                    state=state,
                    blocker_reasons=blocker_reasons,
                )
            )
            continue
        if action_kind == "monetization" and not policy.claim_monetizable:
            moves.append(
                _move(
                    event,
                    action_kind,
                    surface,
                    state="deny",
                    blocker_reasons=["claim_monetizable_false"],
                )
            )
            continue
        if action_kind == "archive":
            state = "allow" if policy.claim_archive else "deny"
        elif policy.claim_live:
            state = "allow"
        elif policy.claim_archive:
            state = "archive_only"
        else:
            state = _blocked_state(policy.fallback_action)
        reasons = ["claim_live_false_archive_only"] if state == "archive_only" else []
        moves.append(
            _move(
                event,
                action_kind,
                surface,
                state=state,
                blocker_reasons=reasons,
            )
        )
    return moves


def _blocker_reasons_for_event(event: ResearchVehiclePublicEvent) -> list[str]:
    reasons: list[str] = []
    if event.rights_class in _INSUFFICIENT_RIGHTS:
        reasons.append(f"rights_class_{event.rights_class}")
    if event.privacy_class in _INSUFFICIENT_PRIVACY:
        reasons.append(f"privacy_class_{event.privacy_class}")
    if not event.provenance.evidence_refs:
        reasons.append("missing_provenance_evidence")
    if event.surface_policy.requires_provenance and not event.provenance.token:
        reasons.append("missing_provenance_token")
    return reasons


def _blocked_state(fallback: FallbackAction) -> MoveState:
    if fallback == "deny":
        return "deny"
    if fallback == "archive_only":
        return "archive_only"
    if fallback == "chapter_only":
        return "chapter_only"
    if fallback == "dry_run":
        return "dry_run"
    return "hold"


def _denied_move(
    event: ResearchVehiclePublicEvent,
    action_kind: ActionKind,
    *,
    surface: Surface | None,
) -> PublicEventMove:
    return _move(
        event,
        action_kind,
        surface or "health",
        state="deny",
        blocker_reasons=["no_allowed_surfaces"],
    )


def _move(
    event: ResearchVehiclePublicEvent,
    action_kind: ActionKind,
    surface: Surface,
    *,
    state: MoveState,
    blocker_reasons: list[str],
) -> PublicEventMove:
    return PublicEventMove(
        source_event_id=event.event_id,
        event_type=event.event_type,
        action_kind=action_kind,
        surface=surface,
        state=state,
        fallback_action=event.surface_policy.fallback_action,
        blocker_reasons=list(blocker_reasons),
    )


__all__ = [
    "ActionKind",
    "INTERNAL_ONLY_EVENT_TYPES",
    "MoveState",
    "PublicEventMove",
    "derive_public_event_moves",
]
