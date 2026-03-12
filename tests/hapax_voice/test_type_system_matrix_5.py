"""Cross-cutting integration tests for the perception type system (matrix 5).

Forward pipeline flow: signal enters at perception, traverses 3+ stages,
property verified at the terminal output. Each test exercises a complete
causal chain, not individual junctions.
"""

from __future__ import annotations

import time
from types import MappingProxyType
from unittest.mock import MagicMock

from agents.hapax_voice.combinator import with_latest_from
from agents.hapax_voice.commands import Command, Schedule
from agents.hapax_voice.governance import (
    FreshnessGuard,
    FreshnessRequirement,
    FusedContext,
    Veto,
    VetoChain,
)
from agents.hapax_voice.governor import PipelineGovernor
from agents.hapax_voice.perception import EnvironmentState, PerceptionEngine
from agents.hapax_voice.primitives import Behavior, Event

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_state(**overrides) -> EnvironmentState:
    defaults = dict(
        timestamp=time.monotonic(),
        speech_detected=False,
        speech_volume_db=-40.0,
        ambient_class="quiet",
        vad_confidence=0.0,
        face_count=1,
        operator_present=True,
        gaze_at_camera=False,
        activity_mode="idle",
        workspace_context="",
        ambient_detailed="",
        active_window=None,
        window_count=0,
        active_workspace_id=0,
    )
    defaults.update(overrides)
    return EnvironmentState(**defaults)


def _make_engine(face_detected: bool = False, face_count: int = 0, vad: float = 0.0):
    presence = MagicMock()
    presence.latest_vad_confidence = vad
    presence.face_detected = face_detected
    presence.face_count = face_count
    return PerceptionEngine(presence, MagicMock())


# ── Class 1: Full Forward Chain (perception → combinator → freshness → command) ─


class TestFullForwardChain:
    """Signal flows from PerceptionEngine through combinator and freshness to Command."""

    def test_perception_to_freshness_to_command_fresh_path(self):
        """S7, S1, S2, S3, S6 + A1, A2, A4: Fresh pipeline produces process Command."""
        engine = _make_engine(face_detected=True, face_count=1)
        engine.tick()

        trigger: Event[str] = Event()
        fused = with_latest_from(trigger, engine.behaviors)
        received: list[FusedContext] = []
        fused.subscribe(lambda ts, ctx: received.append(ctx))

        now = time.monotonic()
        trigger.emit(now, "tick")
        ctx = received[0]

        guard = FreshnessGuard([
            FreshnessRequirement(behavior_name="operator_present", max_staleness_s=10.0),
        ])
        result = guard.check(ctx, now)
        assert result.fresh_enough is True

        cmd = Command(
            action="process",
            params={"fresh": True},
            min_watermark=ctx.min_watermark,
        )
        assert cmd.action == "process"
        assert isinstance(cmd.params, MappingProxyType)
        assert cmd.min_watermark == ctx.min_watermark
        assert "operator_present" in ctx.samples
        assert isinstance(ctx.samples, MappingProxyType)

    def test_perception_to_freshness_to_command_stale_path(self):
        """S7, S1, S2, S3, S4, S6 + A1, A2, A5: Stale pipeline produces denied Command."""
        engine = _make_engine(face_detected=True, face_count=1)
        engine.tick()

        trigger: Event[str] = Event()
        fused = with_latest_from(trigger, engine.behaviors)
        received: list[FusedContext] = []
        fused.subscribe(lambda ts, ctx: received.append(ctx))

        now = time.monotonic()
        trigger.emit(now, "tick")
        ctx = received[0]

        guard = FreshnessGuard([
            FreshnessRequirement(behavior_name="activity_mode", max_staleness_s=0.0001),
        ])
        # Check far in the future to guarantee staleness
        freshness = guard.check(ctx, now + 10.0)
        assert freshness.fresh_enough is False

        chain: VetoChain[FusedContext] = VetoChain([
            Veto(name="freshness", predicate=lambda c: guard.check(c, now + 10.0).fresh_enough),
        ])
        veto = chain.evaluate(ctx)
        assert not veto.allowed

        cmd = Command(
            action="pause",
            params={"stale": True},
            governance_result=veto,
        )
        assert cmd.governance_result.allowed is False
        assert "freshness" in cmd.governance_result.denied_by
        assert isinstance(cmd.params, MappingProxyType)
        assert isinstance(ctx.samples, MappingProxyType)

    def test_perception_to_schedule_with_watermark_integrity(self):
        """S7, S1, S2, S6 + A1, A2, A4: min_watermark flows from engine to Schedule."""
        engine = _make_engine(face_detected=True, face_count=1)
        engine.tick()

        trigger: Event[str] = Event()
        fused = with_latest_from(trigger, engine.behaviors)
        received: list[FusedContext] = []
        fused.subscribe(lambda ts, ctx: received.append(ctx))

        trigger.emit(time.monotonic(), "snap")
        ctx = received[0]

        expected_min = min(s.watermark for s in ctx.samples.values())
        assert ctx.min_watermark == expected_min

        cmd = Command(
            action="process",
            params={"behaviors": len(ctx.samples)},
            min_watermark=ctx.min_watermark,
        )
        sched = Schedule(command=cmd, wall_time=time.time())

        assert sched.command.min_watermark == ctx.min_watermark
        assert sched.command.min_watermark == expected_min
        assert isinstance(sched.command.params, MappingProxyType)
        assert "operator_present" in ctx.samples

    def test_perception_to_missing_behavior_to_schedule_denial(self):
        """S7, S1, S2, S3, S4, S6 + A2, A4, A5: Missing behavior denies through to Schedule."""
        engine = _make_engine(face_detected=True, face_count=1)
        engine.tick()

        trigger: Event[str] = Event()
        fused = with_latest_from(trigger, engine.behaviors)
        received: list[FusedContext] = []
        fused.subscribe(lambda ts, ctx: received.append(ctx))

        now = time.monotonic()
        trigger.emit(now, "snap")
        ctx = received[0]

        guard = FreshnessGuard([
            FreshnessRequirement(behavior_name="gaze_confidence", max_staleness_s=5.0),
        ])
        freshness = guard.check(ctx, now)
        assert "not present" in freshness.violations[0]

        chain: VetoChain[FusedContext] = VetoChain([
            Veto(name="gaze_fresh", predicate=lambda c: guard.check(c, now).fresh_enough),
        ])
        veto = chain.evaluate(ctx)

        cmd = Command(
            action="pause",
            params={"missing": "gaze_confidence"},
            governance_result=veto,
        )
        sched = Schedule(command=cmd)

        assert sched.command.governance_result.allowed is False
        assert isinstance(sched.command.params, MappingProxyType)
        assert "operator_present" in ctx.samples


# ── Class 2: Governor Forward Chain (governor → command → schedule) ──────────


class TestGovernorForwardChain:
    """EnvironmentState flows through governor to Command to Schedule."""

    def test_governor_idle_to_command_to_schedule(self):
        """S5, S6, S3 + A2, A3, A5: Idle → process → Command → Schedule."""
        gov = PipelineGovernor()
        state = _make_state(activity_mode="idle")
        r = gov.evaluate(state)
        assert r == "process"

        cmd = Command(
            action="process",
            params={"mode": "idle"},
            governance_result=gov.last_veto_result,
            selected_by=gov.last_selected.selected_by,
        )
        sched = Schedule(command=cmd, domain="wall")

        assert sched.command.action == "process"
        assert sched.command.selected_by == "default"
        assert isinstance(sched.command.params, MappingProxyType)

        # Separate freshness check for A5
        guard = FreshnessGuard([
            FreshnessRequirement(behavior_name="missing", max_staleness_s=1.0),
        ])
        ctx = FusedContext(trigger_time=time.monotonic(), trigger_value="x", samples={})
        assert "not present" in guard.check(ctx, time.monotonic()).violations[0]

    def test_governor_production_to_vetoed_schedule(self):
        """S5, S6, S4 + A2, A3, A5: Production + custom freshness veto → denied Schedule."""
        now = time.monotonic()
        gov = PipelineGovernor()

        guard = FreshnessGuard([
            FreshnessRequirement(behavior_name="missing_sensor", max_staleness_s=1.0),
        ])
        ctx = FusedContext(trigger_time=now, trigger_value="x", samples={})
        gov.veto_chain.add(Veto(
            name="custom_freshness",
            predicate=lambda _s: guard.check(ctx, now).fresh_enough,
        ))

        state = _make_state(activity_mode="production")
        r = gov.evaluate(state)
        assert r == "pause"

        cmd = Command(
            action="pause",
            params={"denials": list(gov.last_veto_result.denied_by)},
            governance_result=gov.last_veto_result,
        )
        sched = Schedule(command=cmd)

        assert sched.command.governance_result.allowed is False
        assert "activity_mode" in sched.command.governance_result.denied_by
        assert "custom_freshness" in sched.command.governance_result.denied_by
        assert isinstance(sched.command.params, MappingProxyType)

    def test_governor_wake_word_to_command_to_schedule(self):
        """S5, S6, S3 + A2, A3, A4: Wake word → process → Schedule with observability."""
        gov = PipelineGovernor()
        gov.wake_word_active = True

        state = _make_state(activity_mode="production")
        r = gov.evaluate(state)
        assert r == "process"

        cmd = Command(
            action="process",
            params={"override": "wake_word"},
            governance_result=gov.last_veto_result,
            selected_by=gov.last_selected.selected_by,
        )
        sched = Schedule(command=cmd, domain="beat")

        assert sched.command.selected_by == "wake_word_override"
        assert sched.command.governance_result.allowed is True
        assert isinstance(sched.command.params, MappingProxyType)

        # Verify operator_present field on state
        assert state.operator_present is True

    def test_governor_withdraw_to_command_to_schedule(self):
        """S5, S6, S7 + A2, A3, A4: Operator absent → withdraw → Schedule."""
        engine = _make_engine(face_detected=False, face_count=0)
        engine.tick()

        gov = PipelineGovernor(operator_absent_withdraw_s=0.0)
        gov._last_operator_seen = time.monotonic() - 10.0

        state = engine.latest
        r = gov.evaluate(state)
        assert r == "withdraw"

        cmd = Command(
            action="withdraw",
            params={"reason": "operator_absent"},
            governance_result=gov.last_veto_result,
            selected_by=gov.last_selected.selected_by,
        )
        sched = Schedule(command=cmd)

        assert sched.command.action == "withdraw"
        assert sched.command.selected_by == "operator_absent"
        assert isinstance(sched.command.params, MappingProxyType)
        assert state.operator_present is False


# ── Class 3: Combinator to Governance Pipeline ──────────────────────────────


class TestCombinatorToGovernancePipeline:
    """Combinator output feeds freshness/veto chain which extends governor."""

    def test_combinator_freshness_veto_extends_governor(self):
        """S2, S3, S4, S5 + A1, A3, A5: Missing behavior via combinator denies governor."""
        now = time.monotonic()
        trigger: Event[str] = Event()
        behaviors = {"activity_mode": Behavior("idle", watermark=now)}
        fused = with_latest_from(trigger, behaviors)
        received: list[FusedContext] = []
        fused.subscribe(lambda ts, ctx: received.append(ctx))

        trigger.emit(now, "check")
        ctx = received[0]

        guard = FreshnessGuard([
            FreshnessRequirement(behavior_name="missing_sensor", max_staleness_s=5.0),
        ])
        freshness = guard.check(ctx, now)
        assert "not present" in freshness.violations[0]

        gov = PipelineGovernor()
        gov.veto_chain.add(Veto(
            name="custom_freshness",
            predicate=lambda _s: guard.check(ctx, now).fresh_enough,
        ))

        state = _make_state(activity_mode="idle")
        r = gov.evaluate(state)
        assert r == "pause"
        assert "custom_freshness" in gov.last_veto_result.denied_by
        assert isinstance(ctx.samples, MappingProxyType)

    def test_combinator_fresh_context_passes_governor_extended_veto(self):
        """S2, S3, S4, S5 + A1, A4, A5: Fresh combinator output lets governor process."""
        engine = _make_engine(face_detected=True, face_count=1)
        engine.tick()

        trigger: Event[str] = Event()
        fused = with_latest_from(trigger, engine.behaviors)
        received: list[FusedContext] = []
        fused.subscribe(lambda ts, ctx: received.append(ctx))

        now = time.monotonic()
        trigger.emit(now, "check")
        ctx = received[0]

        guard = FreshnessGuard([
            FreshnessRequirement(behavior_name="operator_present", max_staleness_s=10.0),
        ])

        gov = PipelineGovernor()
        gov.veto_chain.add(Veto(
            name="presence_fresh",
            predicate=lambda _s: guard.check(ctx, now).fresh_enough,
        ))

        state = _make_state(activity_mode="idle")
        r = gov.evaluate(state)
        assert r == "process"
        assert "operator_present" in ctx.samples
        assert isinstance(ctx.samples, MappingProxyType)

        # Separate missing-behavior check
        guard_m = FreshnessGuard([
            FreshnessRequirement(behavior_name="nope", max_staleness_s=1.0),
        ])
        assert "not present" in guard_m.check(ctx, now).violations[0]

    def test_combinator_stale_cascades_through_veto_to_governor_pause(self):
        """S1, S2, S3, S4, S5 + A1, A2, A5: Stale behavior cascades to governor pause + Command."""
        now = time.monotonic()
        b = Behavior("idle", watermark=now - 100.0)
        trigger: Event[str] = Event()
        fused = with_latest_from(trigger, {"activity_mode": b})
        received: list[FusedContext] = []
        fused.subscribe(lambda ts, ctx: received.append(ctx))

        trigger.emit(now, "check")
        ctx = received[0]

        guard = FreshnessGuard([
            FreshnessRequirement(behavior_name="activity_mode", max_staleness_s=5.0),
        ])
        freshness = guard.check(ctx, now)
        assert freshness.fresh_enough is False

        gov = PipelineGovernor()
        gov.veto_chain.add(Veto(
            name="staleness",
            predicate=lambda _s: guard.check(ctx, now).fresh_enough,
        ))

        state = _make_state(activity_mode="idle")
        r = gov.evaluate(state)
        assert r == "pause"

        cmd = Command(
            action="pause",
            params={"staleness": True},
            governance_result=gov.last_veto_result,
            min_watermark=ctx.min_watermark,
        )
        assert cmd.governance_result.allowed is False
        assert cmd.min_watermark < now - 50
        assert isinstance(cmd.params, MappingProxyType)
        assert isinstance(ctx.samples, MappingProxyType)

    def test_dual_freshness_guards_both_feed_governor(self):
        """S2, S3, S4, S5 + A1, A3, A5: Present behavior allows, missing denies — governor pauses."""
        now = time.monotonic()
        trigger: Event[str] = Event()
        behaviors = {"activity_mode": Behavior("idle", watermark=now)}
        fused = with_latest_from(trigger, behaviors)
        received: list[FusedContext] = []
        fused.subscribe(lambda ts, ctx: received.append(ctx))

        trigger.emit(now, "check")
        ctx = received[0]

        guard_ok = FreshnessGuard([
            FreshnessRequirement(behavior_name="activity_mode", max_staleness_s=10.0),
        ])
        guard_missing = FreshnessGuard([
            FreshnessRequirement(behavior_name="gaze_confidence", max_staleness_s=5.0),
        ])

        gov = PipelineGovernor()
        gov.veto_chain.add(Veto(
            name="activity_freshness",
            predicate=lambda _s: guard_ok.check(ctx, now).fresh_enough,
        ))
        gov.veto_chain.add(Veto(
            name="gaze_freshness",
            predicate=lambda _s: guard_missing.check(ctx, now).fresh_enough,
        ))

        state = _make_state(activity_mode="idle")
        r = gov.evaluate(state)
        assert r == "pause"
        assert "gaze_freshness" in gov.last_veto_result.denied_by
        assert "activity_freshness" not in gov.last_veto_result.denied_by
        assert "not present" in guard_missing.check(ctx, now).violations[0]
        assert isinstance(ctx.samples, MappingProxyType)
