"""Cross-cutting integration tests for the perception type system (matrix 9).

Provenance tracing: verify that the full causal history (watermarks,
trigger sources, denied_by, selected_by) is correctly threaded from
origin to final Schedule. Each test traces data from its source
through 3+ seams.
"""

from __future__ import annotations

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
    presence = MagicMock()
    presence.latest_vad_confidence = vad
    presence.face_detected = face_detected
    presence.face_count = face_count
    presence.guest_count = max(0, face_count - 1)
    presence.operator_visible = face_detected
    return PerceptionEngine(presence, MagicMock())


# ── Class 1: Watermark Provenance ────────────────────────────────────────────


class TestWatermarkProvenance:
    """Trace watermark values from Behavior origin to terminal output."""

    def test_behavior_watermark_traces_through_combinator_to_command(self):
        """S1, S2, S3, S6 + A1, A2, A4: Known watermarks trace to Command."""
        b_op = Behavior(True, watermark=10.0)
        b_vad = Behavior(0.5, watermark=20.0)
        b_mode = Behavior("idle", watermark=30.0)

        trigger: Event[str] = Event()
        fused = with_latest_from(
            trigger,
            {
                "operator_present": b_op,
                "vad_confidence": b_vad,
                "activity_mode": b_mode,
            },
        )
        received: list[FusedContext] = []
        fused.subscribe(lambda ts, ctx: received.append(ctx))

        trigger.emit(35.0, "snap")
        ctx = received[0]

        # min_watermark traces to the least-fresh behavior
        assert ctx.min_watermark == 10.0
        assert ctx.get_sample("operator_present").watermark == 10.0

        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="operator_present", max_staleness_s=30.0),
            ]
        )
        assert guard.check(ctx, 35.0).fresh_enough is True

        cmd = Command(
            action="process",
            params={"source": "traced"},
            min_watermark=ctx.min_watermark,
        )
        assert cmd.min_watermark == 10.0
        assert isinstance(cmd.params, MappingProxyType)
        assert isinstance(ctx.samples, MappingProxyType)

    def test_trigger_time_provenance_through_combinator_to_schedule(self):
        """S1, S2, S6, S7 + A1, A2, A4: trigger_time traces from emit to Schedule."""
        engine = _make_engine(face_detected=True, face_count=1)
        engine.tick()

        trigger: Event[str] = Event()
        fused = with_latest_from(trigger, engine.behaviors)
        received: list[FusedContext] = []
        fused.subscribe(lambda ts, ctx: received.append(ctx))

        trigger.emit(42.5, "wake")
        ctx = received[0]

        assert ctx.trigger_time == 42.5
        assert ctx.trigger_value == "wake"
        assert "operator_present" in ctx.samples

        cmd = Command(
            action="process",
            params={"trigger": "wake"},
            trigger_time=ctx.trigger_time,
            trigger_source="wake_event",
            min_watermark=ctx.min_watermark,
        )
        sched = Schedule(command=cmd, wall_time=1000.0)

        assert sched.command.trigger_time == 42.5
        assert sched.command.trigger_source == "wake_event"
        assert isinstance(sched.command.params, MappingProxyType)
        assert isinstance(ctx.samples, MappingProxyType)

    def test_min_watermark_provenance_with_slow_and_fast_behaviors(self):
        """S7, S1, S2, S3 + A1, A4, A5: Slow behavior is min watermark, not fast tick."""
        engine = _make_engine(face_detected=True, face_count=1)

        # Set slow field BEFORE tick so it has an older watermark
        engine.update_slow_fields(activity_mode="meeting")
        slow_wm = engine.behaviors["activity_mode"].watermark

        engine.tick()
        fast_wm = engine.behaviors["operator_present"].watermark
        assert fast_wm > slow_wm

        trigger: Event[str] = Event()
        fused = with_latest_from(trigger, engine.behaviors)
        received: list[FusedContext] = []
        fused.subscribe(lambda ts, ctx: received.append(ctx))

        trigger.emit(time.monotonic(), "snap")
        ctx = received[0]

        # min_watermark should be from the slow-field batch, not the fast tick
        assert ctx.min_watermark <= slow_wm
        assert ctx.min_watermark < fast_wm
        assert "operator_present" in ctx.samples
        assert isinstance(ctx.samples, MappingProxyType)

        # Missing behavior check
        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="nope", max_staleness_s=1.0),
            ]
        )
        assert "not present" in guard.check(ctx, time.monotonic()).violations[0]

    def test_watermark_provenance_survives_schedule_wrapping(self):
        """S1, S2, S6, S5 + A1, A2, A3: Watermark preserved through 4 levels."""
        b = Behavior("data", watermark=100.0)
        trigger: Event[str] = Event()
        fused = with_latest_from(trigger, {"val": b})
        received: list[FusedContext] = []
        fused.subscribe(lambda ts, ctx: received.append(ctx))

        trigger.emit(105.0, "snap")
        ctx = received[0]

        gov = PipelineGovernor()
        state = _make_state(activity_mode="idle")
        gov.evaluate(state)

        cmd = Command(
            action="process",
            params={"origin_wm": 100.0},
            min_watermark=ctx.min_watermark,
            governance_result=gov.last_veto_result,
        )
        sched = Schedule(command=cmd, wall_time=time.time())

        # Trace: Behavior(wm=100) → Stamped(wm=100) → FusedContext(min=100) → Command(min=100) → Schedule
        assert sched.command.min_watermark == 100.0
        assert ctx.min_watermark == 100.0
        assert isinstance(sched.command.params, MappingProxyType)
        assert isinstance(ctx.samples, MappingProxyType)
        assert gov.last_veto_result.allowed is True


# ── Class 2: Governance Provenance ───────────────────────────────────────────


class TestGovernanceProvenance:
    """Trace governance decisions from veto names to terminal output."""

    def test_denied_by_traces_veto_names_to_command(self):
        """S4, S5, S6 + A2, A3, A5: Each veto name traces to denied_by in Schedule."""
        now = time.monotonic()
        ctx = FusedContext(trigger_time=now, trigger_value="x", samples={}, min_watermark=now)
        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="missing", max_staleness_s=1.0),
            ]
        )

        gov = PipelineGovernor(conversation_debounce_s=0.0)
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
        # Two evals to engage conversation debounce
        gov.evaluate(state)
        gov.evaluate(state)

        denied = set(gov.last_veto_result.denied_by)
        assert denied == {"activity_mode", "conversation_debounce", "freshness_check"}

        cmd = Command(
            action="pause", params={"denied": list(denied)}, governance_result=gov.last_veto_result
        )
        sched = Schedule(command=cmd)
        assert set(sched.command.governance_result.denied_by) == denied
        assert isinstance(sched.command.params, MappingProxyType)
        assert "not present" in guard.check(ctx, now).violations[0]

    def test_selected_by_traces_from_fallback_to_schedule(self):
        """S5, S6, S3 + A2, A3, A4: selected_by traces from Candidate.name to Schedule."""
        gov = PipelineGovernor(operator_absent_withdraw_s=0.0)
        gov._last_operator_seen = time.monotonic() - 10.0

        state = _make_state(activity_mode="idle", operator_present=False, face_count=0)
        r = gov.evaluate(state)
        assert r == "withdraw"
        assert gov.last_selected.selected_by == "operator_absent"

        cmd = Command(
            action=r,
            params={"traced": True},
            governance_result=gov.last_veto_result,
            selected_by=gov.last_selected.selected_by,
        )
        sched = Schedule(command=cmd)

        assert sched.command.selected_by == "operator_absent"
        assert isinstance(sched.command.params, MappingProxyType)
        assert state.operator_present is False

    def test_wake_word_override_provenance_to_schedule(self):
        """S5, S6, S4 + A2, A3, A5: Wake word provenance traces to Schedule."""
        now = time.monotonic()
        ctx = FusedContext(trigger_time=now, trigger_value="x", samples={}, min_watermark=now)
        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="missing", max_staleness_s=1.0),
            ]
        )

        gov = PipelineGovernor()
        gov.veto_chain.add(
            Veto(
                name="custom",
                predicate=lambda _s: guard.check(ctx, now).fresh_enough,
            )
        )

        gov.wake_word_active = True
        state = _make_state(activity_mode="production")
        r = gov.evaluate(state)

        cmd = Command(
            action=r,
            params={"overridden": True},
            governance_result=gov.last_veto_result,
            selected_by=gov.last_selected.selected_by,
        )
        sched = Schedule(command=cmd)

        assert sched.command.selected_by == "wake_word_override"
        assert sched.command.governance_result.allowed is True
        assert isinstance(sched.command.params, MappingProxyType)
        assert "not present" in guard.check(ctx, now).violations[0]

    def test_governance_result_provenance_differentiates_paths(self):
        """S5, S6, S3, S4 + A1, A2, A3: Three eval paths produce different provenance."""
        now = time.monotonic()
        gov = PipelineGovernor()

        # Path 1: idle → process/default
        state_idle = _make_state(activity_mode="idle")
        gov.evaluate(state_idle)
        cmd_idle = Command(
            action="process",
            params={"path": "idle"},
            governance_result=gov.last_veto_result,
            selected_by=gov.last_selected.selected_by,
        )

        # Path 2: production → pause
        state_prod = _make_state(activity_mode="production")
        gov.evaluate(state_prod)
        cmd_prod = Command(
            action="pause",
            params={"path": "production"},
            governance_result=gov.last_veto_result,
        )

        # Path 3: wake word → process/wake_word_override
        gov.wake_word_active = True
        gov.evaluate(state_prod)
        cmd_wake = Command(
            action="process",
            params={"path": "wake"},
            governance_result=gov.last_veto_result,
            selected_by=gov.last_selected.selected_by,
        )

        sched_idle = Schedule(command=cmd_idle)
        sched_prod = Schedule(command=cmd_prod)
        sched_wake = Schedule(command=cmd_wake)

        assert sched_idle.command.selected_by == "default"
        assert sched_prod.command.governance_result.allowed is False
        assert sched_wake.command.selected_by == "wake_word_override"
        assert isinstance(sched_idle.command.params, MappingProxyType)

        ctx = FusedContext(trigger_time=now, trigger_value="x", samples={"a": Stamped(1, now)})
        assert isinstance(ctx.samples, MappingProxyType)


# ── Class 3: End-to-End Provenance ───────────────────────────────────────────


class TestEndToEndProvenance:
    """Trace data from origin through full pipeline to Schedule."""

    def test_full_pipeline_provenance_perception_to_schedule(self):
        """S7, S1, S2, S5, S6 + A1, A2, A4: Every field traces to correct origin."""
        engine = _make_engine(face_detected=True, face_count=1)
        engine.tick()

        trigger: Event[str] = Event()
        fused = with_latest_from(trigger, engine.behaviors)
        received: list[FusedContext] = []
        fused.subscribe(lambda ts, ctx: received.append(ctx))

        t = time.monotonic()
        trigger.emit(t, "full_trace")
        ctx = received[0]

        gov = PipelineGovernor()
        state = engine.latest
        gov.evaluate(state)

        cmd = Command(
            action="process",
            params={"pipeline": "full"},
            trigger_time=ctx.trigger_time,
            min_watermark=ctx.min_watermark,
            governance_result=gov.last_veto_result,
            selected_by=gov.last_selected.selected_by,
        )
        sched = Schedule(command=cmd, wall_time=time.time())

        assert sched.command.trigger_time == ctx.trigger_time
        assert sched.command.min_watermark == ctx.min_watermark
        assert sched.command.governance_result == gov.last_veto_result
        assert "operator_present" in ctx.samples
        assert isinstance(sched.command.params, MappingProxyType)
        assert isinstance(ctx.samples, MappingProxyType)

    def test_freshness_violation_text_traces_through_pipeline(self):
        """S3, S4, S5, S6 + A2, A3, A5: Violation text traces from guard to Schedule."""
        now = time.monotonic()
        ctx = FusedContext(
            trigger_time=now,
            trigger_value="x",
            samples={
                "sensor": Stamped(value="ok", watermark=now - 100.0),
            },
            min_watermark=now - 100.0,
        )

        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="sensor", max_staleness_s=5.0),
                FreshnessRequirement(behavior_name="missing", max_staleness_s=5.0),
            ]
        )
        freshness = guard.check(ctx, now)
        violation_texts = list(freshness.violations)

        chain: VetoChain[FusedContext] = VetoChain(
            [
                Veto(name="freshness", predicate=lambda c: guard.check(c, now).fresh_enough),
            ]
        )
        veto = chain.evaluate(ctx)

        gov = PipelineGovernor()
        state = _make_state(activity_mode="idle")
        gov.evaluate(state)

        cmd = Command(
            action="pause",
            params={"violations": violation_texts},
            governance_result=veto,
        )
        sched = Schedule(command=cmd)

        # Violation text traces from FreshnessGuard output to Schedule params
        assert list(sched.command.params["violations"]) == violation_texts
        assert any("not present" in v for v in sched.command.params["violations"])
        assert isinstance(sched.command.params, MappingProxyType)

    def test_trigger_value_provenance_from_event_to_fused_context(self):
        """S2, S7, S1, S3 + A1, A4, A5: trigger_value traces from emit to FusedContext."""
        engine = _make_engine(face_detected=True, face_count=1)
        engine.tick()

        trigger: Event[str] = Event()
        fused = with_latest_from(trigger, engine.behaviors)
        received: list[FusedContext] = []
        fused.subscribe(lambda ts, ctx: received.append(ctx))

        trigger.emit(time.monotonic(), "wake_detected")
        ctx = received[0]

        assert ctx.trigger_value == "wake_detected"
        assert "operator_present" in ctx.samples
        assert isinstance(ctx.samples, MappingProxyType)

        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="nonexistent", max_staleness_s=1.0),
            ]
        )
        assert "not present" in guard.check(ctx, time.monotonic()).violations[0]

    def test_multi_hop_watermark_provenance_behavior_to_guard_to_command(self):
        """S1, S3, S4, S6 + A1, A2, A5: Watermark 100.0 traces through every hop."""
        ctx = FusedContext(
            trigger_time=105.0,
            trigger_value="trace",
            samples={
                "sensor": Stamped(value="ok", watermark=100.0),
            },
            min_watermark=100.0,
        )

        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="sensor", max_staleness_s=3.0),
            ]
        )
        freshness = guard.check(ctx, 105.0)
        assert freshness.fresh_enough is False
        # staleness = 105 - 100 = 5.0s
        assert any("5.0" in v for v in freshness.violations)

        chain: VetoChain[FusedContext] = VetoChain(
            [
                Veto(
                    name="freshness_check", predicate=lambda c: guard.check(c, 105.0).fresh_enough
                ),
            ]
        )
        veto = chain.evaluate(ctx)
        assert "freshness_check" in veto.denied_by

        cmd = Command(
            action="pause",
            params={"traced_wm": 100.0},
            min_watermark=ctx.min_watermark,
            governance_result=veto,
        )

        assert cmd.min_watermark == 100.0
        assert "freshness_check" in cmd.governance_result.denied_by
        assert isinstance(cmd.params, MappingProxyType)
        assert isinstance(ctx.samples, MappingProxyType)
