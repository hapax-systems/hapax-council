"""Tests for EventRouter — classification, dedup, expiry, interrupt detection."""

from __future__ import annotations

import unittest

from agents.fortress.events import (
    EVENT_CLASSIFICATIONS,
    EventRouter,
    EventUrgency,
    _response_id,
)
from agents.fortress.goal_library import DEFAULT_GOALS
from agents.fortress.goals import GoalPlanner, GoalState
from agents.fortress.schema import (
    CaravanEvent,
    DeathEvent,
    FastFortressState,
    MandateEvent,
    MigrantEvent,
    MoodEvent,
    SiegeEvent,
)


def _state(
    *,
    tick: int = 1000,
    season: int = 0,
    threats: int = 0,
    idle: int = 5,
    population: int = 50,
    events: tuple = (),
) -> FastFortressState:
    return FastFortressState(
        timestamp=0.0,
        game_tick=tick,
        year=1,
        season=season,
        month=0,
        day=0,
        fortress_name="Test",
        paused=False,
        population=population,
        food_count=200,
        drink_count=100,
        active_threats=threats,
        job_queue_length=10,
        idle_dwarf_count=idle,
        most_stressed_value=5000,
        pending_events=events,
    )


class TestEventClassification(unittest.TestCase):
    def test_all_9_event_types_classified(self) -> None:
        expected = {
            "siege",
            "megabeast",
            "death",
            "cave_in",
            "mood",
            "caravan",
            "mandate",
            "migrant",
            "season_change",
        }
        assert set(EVENT_CLASSIFICATIONS.keys()) == expected

    def test_siege_is_interrupt(self) -> None:
        assert EVENT_CLASSIFICATIONS["siege"].urgency == EventUrgency.INTERRUPT

    def test_megabeast_is_interrupt(self) -> None:
        assert EVENT_CLASSIFICATIONS["megabeast"].urgency == EventUrgency.INTERRUPT

    def test_death_is_high(self) -> None:
        assert EVENT_CLASSIFICATIONS["death"].urgency == EventUrgency.HIGH

    def test_migrant_is_low(self) -> None:
        assert EVENT_CLASSIFICATIONS["migrant"].urgency == EventUrgency.LOW


class TestResponseId(unittest.TestCase):
    def test_siege_response_id(self) -> None:
        event = SiegeEvent(attacker_civ="goblins", force_size=50)
        assert _response_id(event) == "siege:goblins"

    def test_death_response_id(self) -> None:
        event = DeathEvent(unit_id=42, unit_name="Urist", cause="combat")
        assert _response_id(event) == "death:42"

    def test_mandate_response_id(self) -> None:
        event = MandateEvent(noble="Baron", item_type="socks", quantity=3)
        assert _response_id(event) == "mandate:Baron:socks"


class TestEventRouterDedup(unittest.TestCase):
    def test_duplicate_events_ignored(self) -> None:
        planner = GoalPlanner(list(DEFAULT_GOALS))
        router = EventRouter(planner)
        state = _state()
        siege = SiegeEvent(attacker_civ="goblins", force_size=50)

        result1 = router.process_events((siege,), state, 1000)
        result2 = router.process_events((siege,), state, 1100)

        assert len(result1) == 1
        assert len(result2) == 0  # deduped
        assert len(router.active_events) == 1

    def test_different_events_not_deduped(self) -> None:
        planner = GoalPlanner(list(DEFAULT_GOALS))
        router = EventRouter(planner)
        state = _state()

        siege1 = SiegeEvent(attacker_civ="goblins", force_size=50)
        siege2 = SiegeEvent(attacker_civ="elves", force_size=30)
        router.process_events((siege1, siege2), state, 1000)

        assert len(router.active_events) == 2


class TestEventRouterInterrupts(unittest.TestCase):
    def test_siege_returns_interrupt(self) -> None:
        planner = GoalPlanner(list(DEFAULT_GOALS))
        router = EventRouter(planner)
        state = _state()
        siege = SiegeEvent(attacker_civ="goblins", force_size=50)

        interrupts = router.process_events((siege,), state, 1000)
        assert len(interrupts) == 1
        assert interrupts[0].classification.urgency == EventUrgency.INTERRUPT

    def test_migrant_does_not_return_interrupt(self) -> None:
        planner = GoalPlanner(list(DEFAULT_GOALS))
        router = EventRouter(planner)
        state = _state()
        migrant = MigrantEvent(count=7)

        interrupts = router.process_events((migrant,), state, 1000)
        assert len(interrupts) == 0
        assert len(router.active_events) == 1


class TestEventRouterGoalActivation(unittest.TestCase):
    def test_siege_activates_respond_to_siege(self) -> None:
        planner = GoalPlanner(list(DEFAULT_GOALS))
        router = EventRouter(planner)
        state = _state()
        siege = SiegeEvent(attacker_civ="goblins", force_size=50)

        router.process_events((siege,), state, 1000)
        assert planner.tracker.goal_state("respond_to_siege") == GoalState.ACTIVE

    def test_mood_activates_handle_strange_mood(self) -> None:
        planner = GoalPlanner(list(DEFAULT_GOALS))
        router = EventRouter(planner)
        state = _state()
        mood = MoodEvent(unit_id=5, mood_type="fey")

        router.process_events((mood,), state, 1000)
        assert planner.tracker.goal_state("handle_strange_mood") == GoalState.ACTIVE

    def test_reactivation_guard(self) -> None:
        """Already-active goal should not reset progress on second event."""
        planner = GoalPlanner(list(DEFAULT_GOALS))
        router = EventRouter(planner)
        state = _state()

        siege1 = SiegeEvent(attacker_civ="goblins", force_size=50)
        router.process_events((siege1,), state, 1000)
        assert planner.tracker.goal_state("respond_to_siege") == GoalState.ACTIVE

        # Record activation tick
        tick1 = planner.tracker._activation_ticks.get("respond_to_siege")

        # Second siege from different civ — goal already active
        siege2 = SiegeEvent(attacker_civ="elves", force_size=30)
        router.process_events((siege2,), state, 2000)

        # Activation tick should NOT have been reset
        tick2 = planner.tracker._activation_ticks.get("respond_to_siege")
        assert tick1 == tick2


class TestEventRouterExpiry(unittest.TestCase):
    def test_threats_zero_expires_siege(self) -> None:
        planner = GoalPlanner(list(DEFAULT_GOALS))
        router = EventRouter(planner)
        state_siege = _state(threats=5)
        siege = SiegeEvent(attacker_civ="goblins", force_size=50)
        router.process_events((siege,), state_siege, 1000)

        # Threats still active — no expiry
        expired = router.expire_events(state_siege)
        assert len(expired) == 0

        # Threats resolved
        state_clear = _state(threats=0)
        expired = router.expire_events(state_clear)
        assert len(expired) == 1
        assert expired[0].response_id == "siege:goblins"
        assert len(router.active_events) == 0

    def test_season_change_expires_on_next_season(self) -> None:
        planner = GoalPlanner(list(DEFAULT_GOALS))
        router = EventRouter(planner)
        state_s0 = _state(season=0)
        death = DeathEvent(unit_id=1, unit_name="Urist", cause="thirst")
        router.process_events((death,), state_s0, 1000)

        # Same season — no expiry
        expired = router.expire_events(state_s0)
        assert len(expired) == 0

        # Next season
        state_s1 = _state(season=1)
        expired = router.expire_events(state_s1)
        assert len(expired) == 1

    def test_idle_below_threshold_expires_migrant(self) -> None:
        planner = GoalPlanner(list(DEFAULT_GOALS))
        router = EventRouter(planner)
        state_idle = _state(idle=10)
        migrant = MigrantEvent(count=7)
        router.process_events((migrant,), state_idle, 1000)

        # Still idle — no expiry
        expired = router.expire_events(state_idle)
        assert len(expired) == 0

        # Idle resolved
        state_busy = _state(idle=2)
        expired = router.expire_events(state_busy)
        assert len(expired) == 1

    def test_mood_resolved_expiry(self) -> None:
        planner = GoalPlanner(list(DEFAULT_GOALS))
        router = EventRouter(planner)
        mood = MoodEvent(unit_id=5, mood_type="fey")
        # State still has pending mood for unit 5
        state_mood = _state(events=(mood,))
        router.process_events((mood,), state_mood, 1000)

        expired = router.expire_events(state_mood)
        assert len(expired) == 0  # mood still pending

        # Mood resolved (no pending mood events)
        state_clear = _state()
        expired = router.expire_events(state_clear)
        assert len(expired) == 1

    def test_expired_events_can_be_reprocessed(self) -> None:
        """After expiry, same response_id can be accepted again."""
        planner = GoalPlanner(list(DEFAULT_GOALS))
        router = EventRouter(planner)
        state_s0 = _state(season=0)
        caravan = CaravanEvent(civ="humans", goods_value=500)
        router.process_events((caravan,), state_s0, 1000)

        # Expire
        state_s1 = _state(season=1)
        router.expire_events(state_s1)

        # Re-process same caravan — should be accepted
        router.process_events((caravan,), state_s1, 2000)
        assert len(router.active_events) == 1


if __name__ == "__main__":
    unittest.main()
