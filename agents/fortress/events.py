"""Event router — classification, dedup, goal activation, and expiry.

Processes fortress events into urgency-classified ActiveEvents, deduplicates
via response_id, activates goals in the GoalPlanner, and expires stale events
based on state predicates.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

from agents.fortress.goals import GoalPlanner
from agents.fortress.schema import (
    CaravanEvent,
    CaveInEvent,
    DeathEvent,
    FastFortressState,
    FortressEvent,
    MandateEvent,
    MegabeastEvent,
    MigrantEvent,
    MoodEvent,
    SeasonChangeEvent,
    SiegeEvent,
)

log = logging.getLogger(__name__)


class EventUrgency(StrEnum):
    INTERRUPT = "interrupt"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


@dataclass(frozen=True)
class EventClassification:
    """Static classification of an event type."""

    urgency: EventUrgency
    goal_id: str | None  # goal to activate, if any
    expiry_predicate: str  # key into EXPIRY_PREDICATES


EVENT_CLASSIFICATIONS: dict[str, EventClassification] = {
    "siege": EventClassification(
        urgency=EventUrgency.INTERRUPT,
        goal_id="respond_to_siege",
        expiry_predicate="threats_zero",
    ),
    "megabeast": EventClassification(
        urgency=EventUrgency.INTERRUPT,
        goal_id="respond_to_siege",
        expiry_predicate="threats_zero",
    ),
    "death": EventClassification(
        urgency=EventUrgency.HIGH,
        goal_id=None,
        expiry_predicate="next_season",
    ),
    "cave_in": EventClassification(
        urgency=EventUrgency.HIGH,
        goal_id=None,
        expiry_predicate="next_season",
    ),
    "mood": EventClassification(
        urgency=EventUrgency.NORMAL,
        goal_id="handle_strange_mood",
        expiry_predicate="mood_resolved",
    ),
    "caravan": EventClassification(
        urgency=EventUrgency.NORMAL,
        goal_id="manage_trade",
        expiry_predicate="next_season",
    ),
    "mandate": EventClassification(
        urgency=EventUrgency.NORMAL,
        goal_id="handle_mandate",
        expiry_predicate="next_season",
    ),
    "migrant": EventClassification(
        urgency=EventUrgency.LOW,
        goal_id="process_migrants",
        expiry_predicate="idle_below_threshold",
    ),
    "season_change": EventClassification(
        urgency=EventUrgency.LOW,
        goal_id=None,
        expiry_predicate="next_season",
    ),
}


@dataclass
class ActiveEvent:
    """An event currently being tracked."""

    event: FortressEvent
    classification: EventClassification
    response_id: str
    arrival_tick: int
    arrival_season: int


def _response_id(event: FortressEvent) -> str:
    """Generate a dedup key from event type + distinguishing fields."""
    match event:
        case SiegeEvent():
            return f"siege:{event.attacker_civ}"
        case MegabeastEvent():
            return f"megabeast:{event.creature_type}"
        case DeathEvent():
            return f"death:{event.unit_id}"
        case CaveInEvent():
            return f"cave_in:{event.z_level}"
        case MoodEvent():
            return f"mood:{event.unit_id}"
        case CaravanEvent():
            return f"caravan:{event.civ}"
        case MandateEvent():
            return f"mandate:{event.noble}:{event.item_type}"
        case MigrantEvent():
            return f"migrant:{event.count}"
        case SeasonChangeEvent():
            return f"season_change:{event.new_year}:{event.new_season}"
        case _:  # pragma: no cover
            return f"unknown:{id(event)}"


# ---------------------------------------------------------------------------
# Expiry predicates
# ---------------------------------------------------------------------------

ExpiryPredicate = dict[str, type[None]]  # placeholder for type alias


def _threats_zero(event: ActiveEvent, state: FastFortressState) -> bool:
    return state.active_threats == 0


def _idle_below_threshold(event: ActiveEvent, state: FastFortressState) -> bool:
    return state.idle_dwarf_count < 3


def _mood_resolved(event: ActiveEvent, state: FastFortressState) -> bool:
    # Mood events expire when no pending mood events for same unit
    if not isinstance(event.event, MoodEvent):
        return True
    for pe in state.pending_events:
        if isinstance(pe, MoodEvent) and pe.unit_id == event.event.unit_id:
            return False
    return True


def _next_season(event: ActiveEvent, state: FastFortressState) -> bool:
    return state.season != event.arrival_season


EXPIRY_PREDICATES: dict[str, type[object] | object] = {
    "threats_zero": _threats_zero,
    "idle_below_threshold": _idle_below_threshold,
    "mood_resolved": _mood_resolved,
    "next_season": _next_season,
}


class EventRouter:
    """Classifies, deduplicates, and routes fortress events."""

    def __init__(self, planner: GoalPlanner) -> None:
        self._planner = planner
        self._response_ids: set[str] = set()
        self._active_events: list[ActiveEvent] = []

    @property
    def active_events(self) -> list[ActiveEvent]:
        return list(self._active_events)

    def process_events(
        self,
        events: tuple[FortressEvent, ...],
        state: FastFortressState,
        now: int,
    ) -> list[ActiveEvent]:
        """Process incoming events. Returns list of INTERRUPT-level events."""
        interrupts: list[ActiveEvent] = []

        for event in events:
            classification = EVENT_CLASSIFICATIONS.get(event.type)
            if classification is None:
                log.warning("Unknown event type: %s", event.type)
                continue

            rid = _response_id(event)
            if rid in self._response_ids:
                continue  # dedup

            self._response_ids.add(rid)
            active = ActiveEvent(
                event=event,
                classification=classification,
                response_id=rid,
                arrival_tick=now,
                arrival_season=state.season,
            )
            self._active_events.append(active)
            log.info(
                "Event %s classified as %s (goal=%s)",
                rid,
                classification.urgency,
                classification.goal_id,
            )

            # Activate goal if specified
            if classification.goal_id is not None:
                self._planner.activate_goal(classification.goal_id, now)

            if classification.urgency == EventUrgency.INTERRUPT:
                interrupts.append(active)

        return interrupts

    def expire_events(self, state: FastFortressState) -> list[ActiveEvent]:
        """Remove expired events. Returns list of expired events."""
        expired: list[ActiveEvent] = []
        remaining: list[ActiveEvent] = []

        for active in self._active_events:
            predicate_key = active.classification.expiry_predicate
            predicate_fn = EXPIRY_PREDICATES.get(predicate_key)
            if predicate_fn is not None and predicate_fn(active, state):  # type: ignore[operator]
                expired.append(active)
                self._response_ids.discard(active.response_id)
                log.info("Event expired: %s", active.response_id)
            else:
                remaining.append(active)

        self._active_events = remaining
        return expired
