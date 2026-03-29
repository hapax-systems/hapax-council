"""Cross-cutting integration tests for the perception type system (matrix 2).

Exercises lifecycle, temporal ordering, multi-subscriber fan-out,
FallbackChain + FreshnessGuard composition, Schedule wrapping,
VetoChain.add() dynamic restriction, and governor multi-step state
machine transitions.
"""

from __future__ import annotations

import time
from types import MappingProxyType
from unittest.mock import MagicMock

from agents.hapax_daimonion.combinator import with_latest_from
from agents.hapax_daimonion.commands import Command, Schedule
from agents.hapax_daimonion.governance import (
    Candidate,
    FallbackChain,
    FreshnessGuard,
    FreshnessRequirement,
    FusedContext,
    Veto,
    VetoChain,
)
from agents.hapax_daimonion.governor import PipelineGovernor
from agents.hapax_daimonion.perception import EnvironmentState, PerceptionEngine
from agents.hapax_daimonion.primitives import Behavior, Event, Stamped

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_state(**overrides) -> EnvironmentState:
    """Create an EnvironmentState with sensible defaults."""
    defaults = dict(
        timestamp=time.monotonic(),
        speech_detected=False,
        vad_confidence=0.0,
        face_count=1,
        guest_count=0,
        operator_present=True,
        activity_mode="idle",
        workspace_context="",
        active_window=None,
        window_count=0,
        active_workspace_id=0,
    )
    defaults.update(overrides)
    return EnvironmentState(**defaults)


def _make_engine(face_detected: bool = False, face_count: int = 0, vad: float = 0.0):
    """PerceptionEngine with mocked presence/workspace_monitor."""
    presence = MagicMock()
    presence.latest_vad_confidence = vad
    presence.face_detected = face_detected
    presence.face_count = face_count
    presence.guest_count = max(0, face_count - 1)
    presence.operator_visible = face_detected

    workspace_monitor = MagicMock()
    return PerceptionEngine(presence, workspace_monitor)


# ── Class 1: Event Lifecycle and Fan-Out ─────────────────────────────────────


class TestEventLifecycleAndFanOut:
    """Event unsubscribe, multiple subscribers, temporal ordering through combinators."""

    def test_unsubscribe_stops_fused_context_delivery(self):
        """S2, S7, A1: Unsubscribing from fused output stops delivery to that listener."""
        engine = _make_engine(face_detected=True, face_count=1)
        engine.tick()

        trigger: Event[str] = Event()
        fused_event = with_latest_from(trigger, engine.behaviors)

        received_a: list[FusedContext] = []
        received_b: list[FusedContext] = []
        unsub_a = fused_event.subscribe(lambda ts, ctx: received_a.append(ctx))
        fused_event.subscribe(lambda ts, ctx: received_b.append(ctx))

        trigger.emit(time.monotonic(), "first")
        assert len(received_a) == 1
        assert len(received_b) == 1

        unsub_a()

        trigger.emit(time.monotonic(), "second")
        assert len(received_a) == 1  # no new delivery
        assert len(received_b) == 2

        # Both received contexts have immutable samples
        assert isinstance(received_a[0].samples, MappingProxyType)
        assert isinstance(received_b[1].samples, MappingProxyType)

    def test_behavior_update_after_fusion_does_not_mutate_prior_context(self):
        """S1, S2, A1, A4: Updating a Behavior after fusion doesn't retroactively change old context."""
        b_present = Behavior(False, watermark=1.0)
        b_vad = Behavior(0.3, watermark=1.0)
        behaviors = {"operator_present": b_present, "vad_confidence": b_vad}

        trigger: Event[str] = Event()
        fused_event = with_latest_from(trigger, behaviors)
        received: list[FusedContext] = []
        fused_event.subscribe(lambda ts, ctx: received.append(ctx))

        # First fusion at t=5
        trigger.emit(5.0, "first")
        assert len(received) == 1

        # Update operator_present after fusion
        b_present.update(True, 6.0)

        # Second fusion at t=7
        trigger.emit(7.0, "second")
        assert len(received) == 2

        # Old context unchanged
        assert received[0].get_sample("operator_present").value is False
        assert received[0].get_sample("operator_present").watermark == 1.0

        # New context reflects update
        assert received[1].get_sample("operator_present").value is True
        assert received[1].get_sample("operator_present").watermark == 6.0

        # Both immutable, key is operator_present not face_detected
        assert isinstance(received[0].samples, MappingProxyType)
        assert isinstance(received[1].samples, MappingProxyType)
        assert "operator_present" in received[0].samples
        assert "face_detected" not in received[0].samples

    def test_multiple_subscribers_receive_identical_fused_context(self):
        """S2, S7, A4, A5: All subscribers receive the same FusedContext object."""
        engine = _make_engine(face_detected=True, face_count=1)
        engine.tick()

        trigger: Event[str] = Event()
        fused_event = with_latest_from(trigger, engine.behaviors)

        received: list[list[FusedContext]] = [[], [], []]
        for i in range(3):
            slot = received[i]
            fused_event.subscribe(lambda ts, ctx, s=slot: s.append(ctx))

        trigger.emit(time.monotonic(), "tick")

        # All three got the same object
        assert received[0][0] is received[1][0] is received[2][0]

        ctx = received[0][0]
        assert "operator_present" in ctx.samples

        # FreshnessGuard on nonexistent sensor
        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="nonexistent_sensor", max_staleness_s=5.0),
            ]
        )
        result = guard.check(ctx, time.monotonic())
        assert result.fresh_enough is False
        assert "not present" in result.violations[0]

    def test_slow_tick_update_flows_through_combinator_on_next_trigger(self):
        """S1, S2, S7, A1, A5: Slow-tick update is visible in the next combinator fusion."""
        engine = _make_engine(face_detected=False, face_count=0)
        engine.tick()
        initial_wm = engine.behaviors["activity_mode"].watermark

        # Slow-tick update
        engine.update_slow_fields(activity_mode="meeting")
        updated_wm = engine.behaviors["activity_mode"].watermark
        assert updated_wm >= initial_wm

        trigger: Event[str] = Event()
        fused_event = with_latest_from(trigger, engine.behaviors)
        received: list[FusedContext] = []
        fused_event.subscribe(lambda ts, ctx: received.append(ctx))

        trigger.emit(time.monotonic(), "check")
        ctx = received[0]

        assert ctx.get_sample("activity_mode").value == "meeting"
        assert ctx.get_sample("activity_mode").watermark == updated_wm
        assert isinstance(ctx.samples, MappingProxyType)

        # Missing behavior
        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="gaze_model", max_staleness_s=5.0),
            ]
        )
        result = guard.check(ctx, time.monotonic())
        assert result.fresh_enough is False
        assert "not present" in result.violations[0]


# ── Class 2: FallbackChain + Freshness Composition ──────────────────────────


class TestFallbackChainFreshnessComposition:
    """FallbackChain with FreshnessGuard predicates, Schedule wrapping, VetoChain.add."""

    def test_fallback_chain_selects_action_based_on_freshness_result(self):
        """S3, S4, A1, A5: FallbackChain candidates delegate to FreshnessGuard checks."""
        now = time.monotonic()

        hi_guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="vad_confidence", max_staleness_s=1.0),
            ]
        )
        lo_guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="operator_present", max_staleness_s=10.0),
            ]
        )

        chain: FallbackChain[FusedContext, str] = FallbackChain(
            candidates=[
                Candidate(
                    name="high_confidence",
                    predicate=lambda c: hi_guard.check(c, now).fresh_enough,
                    action="full_processing",
                ),
                Candidate(
                    name="degraded",
                    predicate=lambda c: lo_guard.check(c, now).fresh_enough,
                    action="degraded_processing",
                ),
            ],
            default="offline",
        )

        # Both fresh
        ctx_fresh = FusedContext(
            trigger_time=now,
            trigger_value="tick",
            samples={
                "vad_confidence": Stamped(value=0.9, watermark=now),
                "operator_present": Stamped(value=True, watermark=now),
            },
            min_watermark=now,
        )
        assert chain.select(ctx_fresh).action == "full_processing"
        assert chain.select(ctx_fresh).selected_by == "high_confidence"
        assert isinstance(ctx_fresh.samples, MappingProxyType)

        # vad stale, presence fresh
        ctx_degraded = FusedContext(
            trigger_time=now,
            trigger_value="tick",
            samples={
                "vad_confidence": Stamped(value=0.9, watermark=now - 100.0),
                "operator_present": Stamped(value=True, watermark=now),
            },
            min_watermark=now - 100.0,
        )
        assert chain.select(ctx_degraded).action == "degraded_processing"
        assert chain.select(ctx_degraded).selected_by == "degraded"

        # Both missing
        ctx_empty = FusedContext(
            trigger_time=now,
            trigger_value="tick",
            samples={},
            min_watermark=now,
        )
        assert chain.select(ctx_empty).action == "offline"
        assert chain.select(ctx_empty).selected_by == "default"

        # Verify missing-behavior violations
        combined_guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="vad_confidence", max_staleness_s=1.0),
                FreshnessRequirement(behavior_name="operator_present", max_staleness_s=10.0),
            ]
        )
        result = combined_guard.check(ctx_empty, now)
        assert result.fresh_enough is False
        assert len(result.violations) == 2
        assert all("not present" in v for v in result.violations)

    def test_schedule_wraps_vetoed_command_with_watermark_provenance(self):
        """S5, S6, A2, A3: Schedule wraps Command through veto and wake word paths."""
        gov = PipelineGovernor()

        # Meeting mode → vetoed
        state = _make_state(activity_mode="meeting")
        result = gov.evaluate(state)
        assert result == "pause"

        cmd_vetoed = Command(
            action="pause",
            params={"mode": "meeting"},
            governance_result=gov.last_veto_result,
        )
        sched_vetoed = Schedule(
            command=cmd_vetoed,
            domain="beat",
            target_time=4.0,
            wall_time=1000.5,
            tolerance_ms=25.0,
        )
        assert isinstance(sched_vetoed.command.params, MappingProxyType)
        assert sched_vetoed.command.governance_result.allowed is False
        try:
            sched_vetoed.command.params["x"] = 1  # type: ignore[index]
        except TypeError:
            pass
        else:
            raise AssertionError("Should have raised TypeError")

        # Wake word override
        gov.wake_word_active = True
        result2 = gov.evaluate(state)
        assert result2 == "process"

        cmd_override = Command(
            action="process",
            params={"mode": "meeting", "override": "wake_word"},
            governance_result=gov.last_veto_result,
            selected_by=gov.last_selected.selected_by,
        )
        sched_override = Schedule(command=cmd_override, domain="beat")
        assert sched_override.command.governance_result.allowed is True
        assert sched_override.command.selected_by == "wake_word_override"
        assert isinstance(sched_override.command.params, MappingProxyType)

    def test_veto_chain_add_dynamically_restricts_fused_context(self):
        """S2, S3, S4, A1, A5: VetoChain.add() makes system more restrictive."""
        now = time.monotonic()

        guard_activity = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="activity_mode", max_staleness_s=5.0),
            ]
        )
        guard_gaze = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="gaze_confidence", max_staleness_s=5.0),
            ]
        )

        chain: VetoChain[FusedContext] = VetoChain(
            [
                Veto(
                    name="activity_freshness",
                    predicate=lambda c: guard_activity.check(c, now).fresh_enough,
                ),
            ]
        )

        # Build context with fresh activity_mode but no gaze_confidence
        trigger: Event[str] = Event()
        behaviors = {"activity_mode": Behavior("idle", watermark=now)}
        fused_event = with_latest_from(trigger, behaviors)
        received: list[FusedContext] = []
        fused_event.subscribe(lambda ts, ctx: received.append(ctx))

        trigger.emit(now, "eval")
        ctx = received[0]

        # Initially allowed
        result1 = chain.evaluate(ctx)
        assert result1.allowed is True

        # Dynamically add gaze freshness veto
        chain.add(
            Veto(
                name="gaze_freshness",
                predicate=lambda c: guard_gaze.check(c, now).fresh_enough,
            )
        )

        # Now denied — gaze_confidence missing
        result2 = chain.evaluate(ctx)
        assert result2.allowed is False
        assert "gaze_freshness" in result2.denied_by

        assert isinstance(ctx.samples, MappingProxyType)

        # Verify "not present" violation
        gaze_result = guard_gaze.check(ctx, now)
        assert "not present" in gaze_result.violations[0]

    def test_schedule_carries_min_watermark_through_full_pipeline(self):
        """S1, S2, S6, S7, A2, A4: min_watermark flows from engine through combinator to Schedule."""
        engine = _make_engine(face_detected=True, face_count=1)
        engine.tick()

        trigger: Event[str] = Event()
        fused_event = with_latest_from(trigger, engine.behaviors)
        received: list[FusedContext] = []
        fused_event.subscribe(lambda ts, ctx: received.append(ctx))

        trigger_time = time.monotonic()
        trigger.emit(trigger_time, "snap")
        ctx = received[0]

        cmd = Command(
            action="process",
            params={"behavior_count": len(ctx.samples)},
            min_watermark=ctx.min_watermark,
        )
        sched = Schedule(command=cmd, wall_time=time.time())

        assert sched.command.min_watermark == ctx.min_watermark
        assert isinstance(sched.command.params, MappingProxyType)
        assert "operator_present" in ctx.samples
        assert ctx.min_watermark > 0
        assert ctx.min_watermark <= trigger_time


# ── Class 3: Governor State Transitions ──────────────────────────────────────


class TestGovernorStateTransitions:
    """Multi-step state machine transitions and governor chain extension."""

    def test_governor_process_to_pause_to_resume_transition_sequence(self):
        """S5, S6, A2, A3: Governor transitions through process → pause → resume."""
        gov = PipelineGovernor(conversation_debounce_s=0.0, environment_clear_resume_s=0.0)

        # Step 1: idle → process
        state_idle = _make_state(activity_mode="idle")
        r1 = gov.evaluate(state_idle)
        assert r1 == "process"

        # Step 2: conversation → pause
        state_conv = _make_state(
            activity_mode="idle",
            face_count=2,
            guest_count=1,
            speech_detected=True,
        )
        r2 = gov.evaluate(state_conv)
        assert r2 == "pause"
        assert gov.last_veto_result is not None
        assert "conversation_debounce" in gov.last_veto_result.denied_by

        cmd_paused = Command(
            action="pause",
            params={"reason": "conversation"},
            governance_result=gov.last_veto_result,
        )
        assert isinstance(cmd_paused.params, MappingProxyType)

        # Step 3: cleared → process
        state_clear = _make_state(activity_mode="idle", face_count=1, speech_detected=False)
        r3 = gov.evaluate(state_clear)
        assert r3 == "process"
        assert gov.last_selected is not None
        assert gov.last_selected.selected_by == "default"

        cmd_resumed = Command(
            action="process",
            params={"reason": "cleared"},
            governance_result=gov.last_veto_result,
        )

        # Two commands have different governance results
        assert cmd_paused.governance_result.allowed is False
        assert cmd_resumed.governance_result.allowed is True

    def test_governor_veto_chain_extension_with_freshness_predicate(self):
        """S3, S4, S5, A1, A5: Extend governor's veto chain with a freshness-based custom veto."""
        now = time.monotonic()
        gov = PipelineGovernor()

        # Build a FusedContext with fresh operator_present
        ctx_fresh = FusedContext(
            trigger_time=now,
            trigger_value="tick",
            samples={
                "operator_present": Stamped(value=True, watermark=now),
            },
            min_watermark=now,
        )

        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="operator_present", max_staleness_s=5.0),
            ]
        )

        # Closure over the context for the veto predicate
        freshness_ctx = {"current": ctx_fresh}

        gov.veto_chain.add(
            Veto(
                name="ambient_freshness",
                predicate=lambda _state: guard.check(freshness_ctx["current"], now).fresh_enough,
            )
        )

        # With fresh context → governor allows (idle mode passes built-in vetoes)
        state = _make_state(activity_mode="idle")
        r1 = gov.evaluate(state)
        assert r1 == "process"

        # Swap to stale context → governor denies via extended veto
        ctx_stale = FusedContext(
            trigger_time=now,
            trigger_value="tick",
            samples={
                "operator_present": Stamped(value=True, watermark=now - 100.0),
            },
            min_watermark=now - 100.0,
        )
        freshness_ctx["current"] = ctx_stale
        r2 = gov.evaluate(state)
        assert r2 == "pause"
        assert gov.last_veto_result is not None
        assert "ambient_freshness" in gov.last_veto_result.denied_by

        assert isinstance(ctx_fresh.samples, MappingProxyType)
        assert isinstance(ctx_stale.samples, MappingProxyType)

        # Missing-key check
        guard_missing = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="nonexistent", max_staleness_s=1.0),
            ]
        )
        missing_result = guard_missing.check(ctx_stale, now)
        assert "not present" in missing_result.violations[0]

    def test_governor_withdraw_to_wake_word_override_transition(self):
        """S5, S6, A3, A4: Governor transitions from withdraw to wake word override."""
        gov = PipelineGovernor(operator_absent_withdraw_s=0.0)
        gov._last_operator_seen = time.monotonic() - 10.0

        state_absent = _make_state(
            activity_mode="idle",
            operator_present=False,
            face_count=0,
            guest_count=0,
        )

        # Step 1: absent → withdraw
        r1 = gov.evaluate(state_absent)
        assert r1 == "withdraw"
        assert gov.last_selected is not None
        assert gov.last_selected.selected_by == "operator_absent"
        assert gov.last_selected.action == "withdraw"

        cmd_withdraw = Command(
            action="withdraw",
            params={"reason": "absent"},
            governance_result=gov.last_veto_result,
            selected_by=gov.last_selected.selected_by,
        )

        # Step 2: wake word overrides
        gov.wake_word_active = True
        r2 = gov.evaluate(state_absent)
        assert r2 == "process"
        assert gov.last_selected.selected_by == "wake_word_override"
        assert gov.last_veto_result.allowed is True

        cmd_override = Command(
            action="process",
            params={"reason": "wake_word"},
            governance_result=gov.last_veto_result,
            selected_by=gov.last_selected.selected_by,
        )

        # Two commands have different results
        assert cmd_withdraw.selected_by == "operator_absent"
        assert cmd_override.selected_by == "wake_word_override"
        assert cmd_withdraw.governance_result is not cmd_override.governance_result

        # EnvironmentState uses operator_present field
        assert hasattr(state_absent, "operator_present")
        assert state_absent.operator_present is False

    def test_perception_tick_watermark_monotonicity_through_governor_and_schedule(self):
        """S1, S5, S6, S7, A2, A4: Watermarks increase monotonically through ticks into Schedule."""
        engine = _make_engine(face_detected=True, face_count=1)

        watermarks: list[float] = []
        for _ in range(3):
            engine.tick()
            watermarks.append(engine.min_watermark)

        # Monotonically non-decreasing
        assert watermarks[0] <= watermarks[1] <= watermarks[2]

        state = engine.latest
        assert state is not None
        assert state.operator_present is True

        gov = PipelineGovernor()
        result = gov.evaluate(state)
        assert result == "process"

        cmd = Command(
            action="process",
            params={"tick_count": 3},
            min_watermark=engine.min_watermark,
            governance_result=gov.last_veto_result,
        )
        sched = Schedule(command=cmd, wall_time=time.time())

        assert isinstance(sched.command.params, MappingProxyType)
        assert sched.command.min_watermark >= watermarks[0]
        assert sched.command.min_watermark == watermarks[2]
