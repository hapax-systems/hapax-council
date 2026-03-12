"""Cross-cutting integration tests for the perception type system.

Exercises composition seams where types feed into each other, verifying
that the 5 thoroughness additions (MappingProxyType immutability on
FusedContext.samples and Command.params, wake word observability,
operator_present rename, FreshnessGuard missing-behavior handling)
compose correctly through realistic paths.
"""

from __future__ import annotations

import time
from types import MappingProxyType
from unittest.mock import MagicMock

from agents.hapax_voice.combinator import with_latest_from
from agents.hapax_voice.commands import Command
from agents.hapax_voice.governance import (
    FreshnessGuard,
    FreshnessRequirement,
    FusedContext,
    Veto,
    VetoChain,
    VetoResult,
)
from agents.hapax_voice.governor import PipelineGovernor
from agents.hapax_voice.perception import EnvironmentState, PerceptionEngine
from agents.hapax_voice.primitives import Behavior, Event, Stamped

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_state(**overrides) -> EnvironmentState:
    """Create an EnvironmentState with sensible defaults."""
    defaults = dict(
        timestamp=time.monotonic(),
        speech_detected=False,
        vad_confidence=0.0,
        face_count=1,
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

    workspace_monitor = MagicMock()
    return PerceptionEngine(presence, workspace_monitor)


# ── Class 1: Immutability Barriers (A1, A2) ──────────────────────────────────


class TestImmutabilityBarriers:
    """Verify MappingProxyType immutability flows through combinators and commands."""

    def test_fused_context_samples_immutable_through_combinator(self):
        """S1, S2, A1: with_latest_from output has immutable samples."""
        trigger: Event[str] = Event()
        behaviors = {"alpha": Behavior(42, watermark=1.0)}

        fused_event = with_latest_from(trigger, behaviors)
        received: list[FusedContext] = []
        fused_event.subscribe(lambda ts, ctx: received.append(ctx))

        trigger.emit(2.0, "go")
        assert len(received) == 1

        ctx = received[0]
        # Reads work
        assert ctx.get_sample("alpha").value == 42
        assert isinstance(ctx.samples, MappingProxyType)

        # Mutation blocked
        with_error = False
        try:
            ctx.samples["new"] = Stamped(value=99, watermark=2.0)  # type: ignore[index]
        except TypeError:
            with_error = True
        assert with_error, "MappingProxyType should reject item assignment"

    def test_combinator_output_samples_are_snapshots(self):
        """S1, S2, A1: updating Behavior after fusion doesn't change old context."""
        trigger: Event[str] = Event()
        b = Behavior(10, watermark=1.0)
        behaviors = {"val": b}

        fused_event = with_latest_from(trigger, behaviors)
        received: list[FusedContext] = []
        fused_event.subscribe(lambda ts, ctx: received.append(ctx))

        # First fusion
        trigger.emit(2.0, "first")
        assert len(received) == 1
        old_ctx = received[0]

        # Update behavior, second fusion
        b.update(20, 3.0)
        trigger.emit(4.0, "second")
        assert len(received) == 2
        new_ctx = received[1]

        # Old snapshot preserved, new snapshot reflects update
        assert old_ctx.get_sample("val").value == 10
        assert new_ctx.get_sample("val").value == 20

        # Both immutable
        assert isinstance(old_ctx.samples, MappingProxyType)
        assert isinstance(new_ctx.samples, MappingProxyType)

    def test_command_params_immutable_with_full_provenance(self):
        """S5, S6, A2: Governor pause → Command with immutable params."""
        gov = PipelineGovernor()

        # activity_mode="production" triggers veto
        state = _make_state(activity_mode="production")
        result = gov.evaluate(state)
        assert result == "pause"
        assert gov.last_veto_result is not None
        assert not gov.last_veto_result.allowed
        assert "activity_mode" in gov.last_veto_result.denied_by

        cmd = Command(
            action="pause",
            params={"reason": "governance_denied"},
            governance_result=gov.last_veto_result,
        )
        assert isinstance(cmd.params, MappingProxyType)
        assert cmd.params["reason"] == "governance_denied"

        mutated = False
        try:
            cmd.params["x"] = 1  # type: ignore[index]
        except TypeError:
            mutated = True
        assert mutated

    def test_wake_word_command_params_immutable(self):
        """S5, S6, A2, A3: Wake word → Command with immutable params + observability."""
        gov = PipelineGovernor()
        gov.wake_word_active = True

        state = _make_state(activity_mode="production")
        result = gov.evaluate(state)
        assert result == "process"

        assert gov.last_veto_result is not None
        assert gov.last_veto_result.allowed
        assert gov.last_selected is not None
        assert gov.last_selected.selected_by == "wake_word_override"

        cmd = Command(
            action="process",
            params={"source": "wake_word"},
            governance_result=gov.last_veto_result,
            selected_by=gov.last_selected.selected_by,
        )
        assert isinstance(cmd.params, MappingProxyType)

        mutated = False
        try:
            cmd.params["y"] = 2  # type: ignore[index]
        except TypeError:
            mutated = True
        assert mutated


# ── Class 2: Governor Observability (A3, A4) ─────────────────────────────────


class TestGovernorObservability:
    """Verify wake word fields and operator_present key alignment."""

    def test_wake_word_overrides_production_mode_with_observability(self):
        """S5, A3: Wake word overrides production veto, observability fields set."""
        gov = PipelineGovernor()
        gov.wake_word_active = True

        # production mode would normally pause
        state = _make_state(activity_mode="production")
        result = gov.evaluate(state)

        assert result == "process"
        assert gov.last_veto_result is not None
        assert gov.last_veto_result.allowed is True
        assert gov.last_selected is not None
        assert gov.last_selected.action == "process"
        assert gov.last_selected.selected_by == "wake_word_override"

    def test_wake_word_clears_conversation_debounce(self):
        """S5, A3: Wake word clears conversation-paused state."""
        gov = PipelineGovernor(conversation_debounce_s=0.0)

        # Drive into conversation-paused state
        conv_state = _make_state(
            activity_mode="idle",
            face_count=2,
            speech_detected=True,
        )
        result = gov.evaluate(conv_state)
        assert result == "pause"
        assert gov._paused_by_conversation is True

        # Fire wake word
        gov.wake_word_active = True
        result2 = gov.evaluate(conv_state)
        assert result2 == "process"
        assert gov._paused_by_conversation is False
        assert gov.last_selected is not None
        assert gov.last_selected.selected_by == "wake_word_override"

        # Next normal eval proceeds without conversation debounce blocking
        # (conversation_detected is still true but _paused_by_conversation was cleared)
        idle_state = _make_state(activity_mode="idle", face_count=0, speech_detected=False)
        result3 = gov.evaluate(idle_state)
        assert result3 == "process"

    def test_operator_present_key_aligns_engine_to_state(self):
        """S5, S7, A4: PerceptionEngine exposes 'operator_present' behavior, not 'face_detected'."""
        engine = _make_engine(face_detected=True, face_count=1, vad=0.0)

        assert "operator_present" in engine.behaviors
        assert "face_detected" not in engine.behaviors

        # Tick to update behaviors
        state = engine.tick()
        assert state.operator_present is True

        # Fuse behaviors via with_latest_from
        trigger: Event[str] = Event()
        fused_event = with_latest_from(trigger, engine.behaviors)
        received: list[FusedContext] = []
        fused_event.subscribe(lambda ts, ctx: received.append(ctx))

        trigger.emit(time.monotonic(), "tick")
        assert len(received) == 1
        ctx = received[0]

        sample = ctx.get_sample("operator_present")
        assert sample.value is True
        assert sample.value == state.operator_present

    def test_operator_present_flows_through_governor_absence_tracking(self):
        """S5, A4: Governor tracks operator_present for withdraw detection."""
        gov = PipelineGovernor(operator_absent_withdraw_s=0.0)

        # Operator present → process
        state_present = _make_state(activity_mode="idle", operator_present=True, face_count=1)
        result1 = gov.evaluate(state_present)
        assert result1 == "process"

        # Operator absent → withdraw (with 0s threshold)
        gov._last_operator_seen = time.monotonic() - 1.0
        state_absent = _make_state(activity_mode="idle", operator_present=False, face_count=0)
        result2 = gov.evaluate(state_absent)
        assert result2 == "withdraw"
        assert gov.last_selected is not None
        assert gov.last_selected.selected_by == "operator_absent"


# ── Class 3: Freshness Composition (A5, A1) ──────────────────────────────────


class TestFreshnessComposition:
    """Verify FreshnessGuard missing-behavior handling composes with immutability."""

    def test_freshness_guard_missing_behavior_in_combinator_output(self):
        """S3, S7, A5: FreshnessGuard handles missing behavior gracefully."""
        engine = _make_engine(face_detected=True, face_count=1)
        engine.tick()

        # Fuse engine behaviors
        trigger: Event[str] = Event()
        fused_event = with_latest_from(trigger, engine.behaviors)
        received: list[FusedContext] = []
        fused_event.subscribe(lambda ts, ctx: received.append(ctx))

        now = time.monotonic()
        trigger.emit(now, "check")
        ctx = received[0]

        # Guard requires a behavior not in engine
        guard = FreshnessGuard([
            FreshnessRequirement(behavior_name="gaze_confidence", max_staleness_s=5.0),
        ])
        result = guard.check(ctx, now)

        assert result.fresh_enough is False
        assert len(result.violations) == 1
        assert "not present" in result.violations[0]

    def test_freshness_guard_mixed_stale_and_missing(self):
        """S3, S4, A1, A5: Stale + missing → VetoChain denies; context immutable."""
        now = time.monotonic()
        ctx = FusedContext(
            trigger_time=now,
            trigger_value="test",
            samples={
                "activity_mode": Stamped(value="idle", watermark=now - 100.0),
            },
            min_watermark=now - 100.0,
        )

        guard = FreshnessGuard([
            FreshnessRequirement(behavior_name="activity_mode", max_staleness_s=5.0),
            FreshnessRequirement(behavior_name="missing_sensor", max_staleness_s=5.0),
        ])
        freshness = guard.check(ctx, now)

        assert freshness.fresh_enough is False
        assert len(freshness.violations) == 2

        # Wrap as VetoChain predicate
        chain: VetoChain[FusedContext] = VetoChain([
            Veto(name="freshness", predicate=lambda c: guard.check(c, now).fresh_enough),
        ])
        veto_result = chain.evaluate(ctx)
        assert not veto_result.allowed
        assert "freshness" in veto_result.denied_by

        # Context still immutable
        assert isinstance(ctx.samples, MappingProxyType)

    def test_freshness_on_operator_present_after_perception_tick(self):
        """S2, S3, S7, A4: Fresh 'operator_present' passes freshness check."""
        engine = _make_engine(face_detected=True, face_count=1)
        engine.tick()

        trigger: Event[str] = Event()
        fused_event = with_latest_from(trigger, engine.behaviors)
        received: list[FusedContext] = []
        fused_event.subscribe(lambda ts, ctx: received.append(ctx))

        now = time.monotonic()
        trigger.emit(now, "check")
        ctx = received[0]

        guard = FreshnessGuard([
            FreshnessRequirement(behavior_name="operator_present", max_staleness_s=10.0),
        ])
        result = guard.check(ctx, now)

        assert result.fresh_enough is True
        assert len(result.violations) == 0
        assert ctx.get_sample("operator_present").value is True

    def test_full_pipeline_stale_behavior_vetoes_command(self):
        """S2, S3, S4, S5, S6, S7, A1, A2, A4, A5: End-to-end pipeline with stale veto."""
        engine = _make_engine(face_detected=True, face_count=1)
        engine.tick()

        # Fuse behaviors
        trigger: Event[str] = Event()
        fused_event = with_latest_from(trigger, engine.behaviors)
        received: list[FusedContext] = []
        fused_event.subscribe(lambda ts, ctx: received.append(ctx))

        # Wait a bit, then trigger so activity_mode is stale
        now = time.monotonic()
        trigger.emit(now, "evaluate")
        ctx = received[0]

        # FreshnessGuard: activity_mode must be within 0.0001s (will be stale)
        guard = FreshnessGuard([
            FreshnessRequirement(behavior_name="activity_mode", max_staleness_s=0.0001),
        ])
        freshness = guard.check(ctx, now + 1.0)
        assert freshness.fresh_enough is False

        # Wrap as VetoChain predicate
        chain: VetoChain[FusedContext] = VetoChain([
            Veto(
                name="freshness_veto",
                predicate=lambda c: guard.check(c, now + 1.0).fresh_enough,
            ),
        ])
        veto_result = chain.evaluate(ctx)
        assert not veto_result.allowed

        # Governor also evaluates
        gov = PipelineGovernor()
        state = _make_state(activity_mode="production")
        gov_result = gov.evaluate(state)
        assert gov_result == "pause"

        # Construct Command from vetoed result
        cmd = Command(
            action="pause",
            params={"freshness_violations": list(freshness.violations)},
            governance_result=VetoResult(
                allowed=False,
                denied_by=veto_result.denied_by + gov.last_veto_result.denied_by,
            ),
            min_watermark=ctx.min_watermark,
        )

        # All immutability assertions
        assert isinstance(cmd.params, MappingProxyType)
        assert isinstance(ctx.samples, MappingProxyType)
        assert cmd.action == "pause"

        # operator_present key present in fused context
        assert "operator_present" in ctx.samples
        assert ctx.get_sample("operator_present").value is True

        # Params immutable
        mutated = False
        try:
            cmd.params["x"] = 1  # type: ignore[index]
        except TypeError:
            mutated = True
        assert mutated
