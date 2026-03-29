"""Cross-cutting integration tests for the perception type system (matrix 3).

Error boundaries and safety invariants: exception isolation through
combinators, watermark regression rejection, one-shot consumption
guarantees, and deny-wins exhaustive evaluation.
"""

from __future__ import annotations

import dataclasses
import time
from types import MappingProxyType
from unittest.mock import MagicMock

from agents.hapax_daimonion.combinator import with_latest_from
from agents.hapax_daimonion.commands import Command, Schedule
from agents.hapax_daimonion.governance import (
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


# ── Class 1: Exception Isolation ─────────────────────────────────────────────


class TestExceptionIsolation:
    """Exceptions in subscribers don't propagate or corrupt state."""

    def test_fused_event_subscriber_exception_does_not_block_others(self):
        """S2, S7, A1: Throwing subscriber doesn't prevent other subscribers from receiving."""
        engine = _make_engine(face_detected=True, face_count=1)
        engine.tick()

        trigger: Event[str] = Event()
        fused_event = with_latest_from(trigger, engine.behaviors)

        received_b: list[FusedContext] = []
        received_c: list[FusedContext] = []

        def _thrower(_ts, _ctx):
            raise RuntimeError("subscriber exploded")

        fused_event.subscribe(_thrower)
        fused_event.subscribe(lambda ts, ctx: received_b.append(ctx))
        fused_event.subscribe(lambda ts, ctx: received_c.append(ctx))

        trigger.emit(time.monotonic(), "go")

        assert len(received_b) == 1
        assert len(received_c) == 1
        assert isinstance(received_b[0].samples, MappingProxyType)

    def test_perception_tick_subscriber_exception_does_not_prevent_behavior_update(self):
        """S1, S7, A4: Throwing perception subscriber doesn't block behavior updates."""
        engine = _make_engine(face_detected=True, face_count=1, vad=0.8)

        def _thrower(_state):
            raise RuntimeError("subscriber exploded")

        engine.subscribe(_thrower)

        state = engine.tick()

        assert engine.latest is not None
        assert engine.latest.operator_present is True
        assert engine.behaviors["operator_present"].value is True
        assert engine.behaviors["operator_present"].watermark == state.timestamp

    def test_exception_in_first_fused_subscriber_still_delivers_to_second(self):
        """S2, S3, A5: FreshnessGuard check still runs despite prior subscriber exception."""
        trigger: Event[str] = Event()
        behaviors = {"activity_mode": Behavior("idle", watermark=time.monotonic())}
        fused_event = with_latest_from(trigger, behaviors)

        freshness_results: list[bool] = []

        def _thrower(_ts, _ctx):
            raise RuntimeError("boom")

        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="nonexistent", max_staleness_s=5.0),
            ]
        )

        def _checker(_ts, ctx):
            result = guard.check(ctx, time.monotonic())
            freshness_results.append(result.fresh_enough)

        fused_event.subscribe(_thrower)
        fused_event.subscribe(_checker)

        trigger.emit(time.monotonic(), "check")

        assert len(freshness_results) == 1
        assert freshness_results[0] is False

    def test_perception_subscriber_exception_preserves_fused_context_immutability(self):
        """S1, S2, S7, A1, A4: Exception in tick subscriber doesn't affect combinator output."""
        engine = _make_engine(face_detected=True, face_count=1)
        engine.subscribe(lambda _s: (_ for _ in ()).throw(RuntimeError("boom")))

        engine.tick()

        trigger: Event[str] = Event()
        fused_event = with_latest_from(trigger, engine.behaviors)
        received: list[FusedContext] = []
        fused_event.subscribe(lambda ts, ctx: received.append(ctx))

        trigger.emit(time.monotonic(), "snap")

        assert len(received) == 1
        ctx = received[0]
        assert isinstance(ctx.samples, MappingProxyType)
        assert "operator_present" in ctx.samples
        assert ctx.get_sample("operator_present").value is True


# ── Class 2: Monotonic Safety ────────────────────────────────────────────────


class TestMonotonicSafety:
    """Properties that can only move in one direction."""

    def test_watermark_regression_rejected_after_fusion(self):
        """S1, S2, A1: Behavior rejects timestamp regression; prior fusion unaffected."""
        b = Behavior(42, watermark=10.0)
        trigger: Event[str] = Event()
        fused_event = with_latest_from(trigger, {"val": b})
        received: list[FusedContext] = []
        fused_event.subscribe(lambda ts, ctx: received.append(ctx))

        trigger.emit(11.0, "snap")
        assert len(received) == 1

        raised = False
        try:
            b.update(99, 5.0)
        except ValueError:
            raised = True
        assert raised

        # Behavior unchanged
        assert b.value == 42
        assert b.watermark == 10.0

        # Prior fusion unchanged and immutable
        assert received[0].get_sample("val").value == 42
        assert isinstance(received[0].samples, MappingProxyType)

    def test_veto_chain_add_never_relaxes_through_governor(self):
        """S4, S5, A3: Adding a veto to governor can only restrict."""
        gov = PipelineGovernor()

        state = _make_state(activity_mode="idle")
        r1 = gov.evaluate(state)
        assert r1 == "process"

        gov.veto_chain.add(
            Veto(
                name="always_deny",
                predicate=lambda _s: False,
            )
        )

        r2 = gov.evaluate(state)
        assert r2 == "pause"
        assert gov.last_veto_result is not None
        assert "always_deny" in gov.last_veto_result.denied_by

    def test_wake_word_consumed_on_single_evaluation(self):
        """S5, S6, A2, A3: wake_word_active is one-shot — consumed after first eval."""
        gov = PipelineGovernor()
        gov.wake_word_active = True

        state = _make_state(activity_mode="production")

        # First eval: override
        r1 = gov.evaluate(state)
        assert r1 == "process"
        assert gov.wake_word_active is False
        assert gov.last_selected.selected_by == "wake_word_override"

        cmd1 = Command(
            action="process",
            params={"eval": 1},
            governance_result=gov.last_veto_result,
            selected_by=gov.last_selected.selected_by,
        )

        # Grace period: 8 ticks return "process" via wake_word_grace
        for _ in range(8):
            rg = gov.evaluate(state)
            assert rg == "process"
            assert gov.last_selected.selected_by == "wake_word_grace"

        # After grace: normal governance (production mode vetoes)
        r2 = gov.evaluate(state)
        assert r2 == "pause"

        cmd2 = Command(
            action="pause",
            params={"eval": 2},
            governance_result=gov.last_veto_result,
        )

        assert isinstance(cmd1.params, MappingProxyType)
        assert isinstance(cmd2.params, MappingProxyType)
        assert cmd1.governance_result.allowed is True
        assert cmd2.governance_result.allowed is False

    def test_fused_context_frozen_fields_reject_mutation(self):
        """S1, S2, A1: FusedContext frozen dataclass rejects field assignment."""
        b = Behavior("hello", watermark=1.0)
        trigger: Event[str] = Event()
        fused_event = with_latest_from(trigger, {"msg": b})
        received: list[FusedContext] = []
        fused_event.subscribe(lambda ts, ctx: received.append(ctx))

        trigger.emit(2.0, "snap")
        ctx = received[0]

        # Frozen field mutation rejected
        frozen_rejected = False
        try:
            ctx.trigger_time = 999.0  # type: ignore[misc]
        except dataclasses.FrozenInstanceError:
            frozen_rejected = True
        assert frozen_rejected

        # MappingProxyType mutation rejected
        proxy_rejected = False
        try:
            ctx.samples["x"] = Stamped(value=1, watermark=1.0)  # type: ignore[index]
        except TypeError:
            proxy_rejected = True
        assert proxy_rejected

        # Original values intact
        assert ctx.trigger_time == 2.0
        assert isinstance(ctx.samples, MappingProxyType)


# ── Class 3: Deny-Wins Exhaustive Evaluation ────────────────────────────────


class TestDenyWinsExhaustive:
    """VetoChain always evaluates all vetoes — no short-circuit."""

    def test_all_vetoes_evaluated_despite_early_denial(self):
        """S4, S5, A3: All veto names appear in denied_by, not just the first."""
        gov = PipelineGovernor(conversation_debounce_s=0.0)

        # Add a custom veto
        gov.veto_chain.add(
            Veto(
                name="custom_deny",
                predicate=lambda _s: False,
            )
        )

        # State that triggers conversation debounce (built-in veto)
        # AND has production activity_mode (built-in veto)
        state = _make_state(
            activity_mode="production",
            face_count=2,
            guest_count=1,
            speech_detected=True,
        )
        # First eval to set _paused_by_conversation
        gov.evaluate(state)
        # Second eval with all three denying
        gov.evaluate(state)

        assert gov.last_veto_result is not None
        assert len(gov.last_veto_result.denied_by) == 3
        assert "activity_mode" in gov.last_veto_result.denied_by
        assert "conversation_debounce" in gov.last_veto_result.denied_by
        assert "custom_deny" in gov.last_veto_result.denied_by

    def test_multiple_freshness_violations_all_reported(self):
        """S3, S4, A1, A5: All freshness violations collected, not just first."""
        now = time.monotonic()
        ctx = FusedContext(
            trigger_time=now,
            trigger_value="tick",
            samples={
                "a": Stamped(value=1, watermark=now - 100.0),
                "b": Stamped(value=2, watermark=now - 200.0),
                "c": Stamped(value=3, watermark=now - 300.0),
            },
            min_watermark=now - 300.0,
        )

        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="a", max_staleness_s=5.0),
                FreshnessRequirement(behavior_name="b", max_staleness_s=5.0),
                FreshnessRequirement(behavior_name="c", max_staleness_s=5.0),
                FreshnessRequirement(behavior_name="missing", max_staleness_s=5.0),
            ]
        )
        result = guard.check(ctx, now)

        assert result.fresh_enough is False
        assert len(result.violations) == 4
        assert any("not present" in v for v in result.violations)

        chain: VetoChain[FusedContext] = VetoChain(
            [
                Veto(name="freshness", predicate=lambda c: guard.check(c, now).fresh_enough),
            ]
        )
        veto_result = chain.evaluate(ctx)
        assert not veto_result.allowed
        assert "freshness" in veto_result.denied_by
        assert isinstance(ctx.samples, MappingProxyType)

    def test_governor_reports_all_built_in_denials(self):
        """S5, S6, A2, A4: Both built-in vetoes appear in denied_by simultaneously."""
        gov = PipelineGovernor(conversation_debounce_s=0.0)

        state = _make_state(
            activity_mode="production",
            face_count=2,
            guest_count=1,
            speech_detected=True,
            operator_present=True,
        )

        # First eval sets _paused_by_conversation
        gov.evaluate(state)
        # Second eval: both vetoes deny
        result = gov.evaluate(state)
        assert result == "pause"

        assert gov.last_veto_result is not None
        assert "activity_mode" in gov.last_veto_result.denied_by
        assert "conversation_debounce" in gov.last_veto_result.denied_by
        assert len(gov.last_veto_result.denied_by) == 2

        cmd = Command(
            action="pause",
            params={"denials": list(gov.last_veto_result.denied_by)},
            governance_result=gov.last_veto_result,
        )
        assert isinstance(cmd.params, MappingProxyType)
        assert state.operator_present is True

    def test_exhaustive_denial_flows_through_command_to_schedule(self):
        """S4, S5, S6, A2, A3, A5: All denials flow into Command and Schedule."""
        now = time.monotonic()
        gov = PipelineGovernor(conversation_debounce_s=0.0)

        # Add custom freshness veto
        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="missing_sensor", max_staleness_s=1.0),
            ]
        )
        ctx = FusedContext(
            trigger_time=now,
            trigger_value="tick",
            samples={},
            min_watermark=now,
        )
        gov.veto_chain.add(
            Veto(
                name="freshness_check",
                predicate=lambda _s: guard.check(ctx, now).fresh_enough,
            )
        )

        state = _make_state(
            activity_mode="production",
            face_count=2,
            guest_count=1,
            speech_detected=True,
        )
        # First eval to set conversation state
        gov.evaluate(state)
        # Second eval: all 3 vetoes deny
        result = gov.evaluate(state)
        assert result == "pause"

        assert gov.last_veto_result is not None
        assert len(gov.last_veto_result.denied_by) == 3

        cmd = Command(
            action="pause",
            params={"violations": list(guard.check(ctx, now).violations)},
            governance_result=gov.last_veto_result,
        )
        sched = Schedule(command=cmd, domain="wall")

        assert isinstance(sched.command.params, MappingProxyType)
        assert len(sched.command.governance_result.denied_by) == 3

        # Freshness violation says "not present"
        freshness_result = guard.check(ctx, now)
        assert "not present" in freshness_result.violations[0]
