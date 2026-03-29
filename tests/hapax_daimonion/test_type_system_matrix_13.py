"""Cross-cutting integration tests for the perception type system (matrix 13).

Adaptive resilience (Q3): composes perturbation cascades (T2), reconfiguration
invariants (T4), and feedback/re-entry (T6). Each test exercises a system that
is perturbed, reconfigured in response, and feeds state back across cycles.
System-level property: the system adapts correctly to changes across cycles
and re-stabilizes after reconfiguration.
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


# ── Q3: Adaptive Resilience ──────────────────────────────────────────────────


class TestPerturbationTriggersReconfiguration:
    """Perturbations cause pipeline reconfiguration that feeds back."""

    def test_stale_sensor_triggers_veto_addition_across_cycles(self):
        """T2+T4+T6: Stale sensor detected → veto added → next cycle denied."""
        now = time.monotonic()
        chain: VetoChain[FusedContext] = VetoChain()
        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="sensor", max_staleness_s=5.0),
            ]
        )

        # Cycle 1: fresh → allowed
        ctx1 = FusedContext(
            trigger_time=now,
            trigger_value="c1",
            samples={"sensor": Stamped(value="ok", watermark=now)},
            min_watermark=now,
        )
        result1 = chain.evaluate(ctx1)
        assert result1.allowed

        # Perturbation: sensor goes stale
        ctx_stale = FusedContext(
            trigger_time=now,
            trigger_value="c2",
            samples={"sensor": Stamped(value="ok", watermark=now - 100.0)},
            min_watermark=now - 100.0,
        )
        freshness = guard.check(ctx_stale, now)
        assert not freshness.fresh_enough

        # Reconfiguration: add freshness veto to chain
        chain.add(
            Veto(
                name="freshness",
                predicate=lambda c: guard.check(c, time.monotonic()).fresh_enough,
            )
        )

        # Cycle 2 feedback: stale context now denied by reconfigured chain
        result2 = chain.evaluate(ctx_stale)
        assert not result2.allowed
        assert "freshness" in result2.denied_by

    def test_meeting_mode_reconfigures_governor_debounce_across_cycles(self):
        """T2+T4+T6: Meeting detected → adjust debounce → feeds back to next eval."""
        engine = _make_engine(face_detected=True, face_count=1)
        gov = PipelineGovernor(conversation_debounce_s=5.0)

        # Cycle 1: idle → process
        engine.tick()
        r1 = gov.evaluate(engine.latest)
        assert r1 == "process"

        # Perturbation: meeting mode
        engine.update_slow_fields(activity_mode="meeting")
        engine.tick()
        r2 = gov.evaluate(engine.latest)
        assert r2 == "pause"

        # Reconfiguration: create new governor with tighter params
        gov2 = PipelineGovernor(conversation_debounce_s=0.0)
        # Carry forward: meeting mode still active
        engine.tick()
        r3 = gov2.evaluate(engine.latest)
        assert r3 == "pause"  # meeting veto still fires

        # Perturbation clears: idle again
        engine.update_slow_fields(activity_mode="idle")
        engine.tick()
        r4 = gov2.evaluate(engine.latest)
        assert r4 == "process"

    def test_wake_word_perturbation_survives_reconfiguration(self):
        """T2+T4+T6: Wake word set → governor reconfigured → wake word state transfers."""
        engine = _make_engine(face_detected=True, face_count=1)
        engine.update_slow_fields(activity_mode="production")

        gov = PipelineGovernor()
        engine.tick()
        r1 = gov.evaluate(engine.latest)
        assert r1 == "pause"

        # Perturbation: wake word
        gov.wake_word_active = True

        # Cycle 2: wake word overrides
        engine.tick()
        r2 = gov.evaluate(engine.latest)
        assert r2 == "process"
        assert gov.wake_word_active is False

        # Reconfiguration: new governor
        gov2 = PipelineGovernor()
        # No wake word on new governor → production pauses again
        engine.tick()
        r3 = gov2.evaluate(engine.latest)
        assert r3 == "pause"

        # Wake word on new governor
        gov2.wake_word_active = True
        engine.tick()
        r4 = gov2.evaluate(engine.latest)
        assert r4 == "process"

    def test_absence_perturbation_with_threshold_reconfiguration(self):
        """T2+T4+T6: Operator absent → reconfigure threshold → affects withdraw timing."""
        engine = _make_engine(face_detected=True, face_count=1)
        gov = PipelineGovernor(operator_absent_withdraw_s=60.0)

        # Cycle 1: present
        engine.tick()
        gov.evaluate(engine.latest)

        # Perturbation: operator leaves
        engine._presence.face_detected = False
        engine._presence.face_count = 0
        gov._last_operator_seen = time.monotonic() - 30.0
        engine.tick()
        r2 = gov.evaluate(engine.latest)
        assert r2 == "process"  # within 60s threshold

        # Reconfiguration: tighten threshold to 10s
        gov.operator_absent_withdraw_s = 10.0

        # Feedback: same absence, now exceeds new threshold
        engine.tick()
        r3 = gov.evaluate(engine.latest)
        assert r3 == "withdraw"


class TestReconfigurationStability:
    """System re-stabilizes after reconfiguration perturbation."""

    def test_veto_chain_grows_monotonically_across_cycles(self):
        """T2+T4+T6: Each cycle adds a veto, system only gets more restrictive."""
        chain: VetoChain[FusedContext] = VetoChain()
        now = time.monotonic()

        results = []
        for i in range(4):
            ctx = FusedContext(
                trigger_time=now,
                trigger_value=f"c{i}",
                samples={
                    "a": Stamped(value="meeting" if i >= 1 else "idle", watermark=now),
                    "b": Stamped(value="old", watermark=now - 100.0 if i >= 2 else now),
                },
                min_watermark=now,
            )
            results.append(chain.evaluate(ctx))

            # Reconfigure: add increasingly restrictive vetoes
            if i == 0:
                chain.add(
                    Veto(
                        name="mode",
                        predicate=lambda c: c.samples["a"].value != "meeting",
                    )
                )
            elif i == 1:
                guard = FreshnessGuard(
                    [
                        FreshnessRequirement(behavior_name="b", max_staleness_s=5.0),
                    ]
                )
                chain.add(
                    Veto(
                        name="fresh",
                        predicate=lambda c: guard.check(c, time.monotonic()).fresh_enough,
                    )
                )

        assert results[0].allowed  # no vetoes yet
        assert not results[1].allowed  # mode veto
        assert not results[2].allowed  # mode + freshness veto
        assert not results[3].allowed  # both still active

    def test_fallback_chain_stable_after_perturbation_clears(self):
        """T2+T4+T6: Perturbation → governor changes → perturbation clears → stable."""
        engine = _make_engine(face_detected=True, face_count=1)
        gov = PipelineGovernor()

        # Stable state
        engine.tick()
        r1 = gov.evaluate(engine.latest)
        assert r1 == "process"

        # Perturbation → meeting
        engine.update_slow_fields(activity_mode="meeting")
        engine.tick()
        r2 = gov.evaluate(engine.latest)
        assert r2 == "pause"

        # Clear perturbation
        engine.update_slow_fields(activity_mode="idle")
        engine.tick()
        r3 = gov.evaluate(engine.latest)

        # Stability: same as initial state
        assert r3 == r1 == "process"

    def test_combinator_stable_after_behavior_replacement(self):
        """T2+T4+T6: Behavior replaced mid-lifecycle, combinator stable with new source."""
        b_v1 = Behavior("version1", watermark=time.monotonic())
        trigger: Event[str] = Event()
        fused1 = with_latest_from(trigger, {"data": b_v1})
        ctx1: list[FusedContext] = []
        fused1.subscribe(lambda ts, ctx: ctx1.append(ctx))

        trigger.emit(time.monotonic(), "c1")
        assert ctx1[0].samples["data"].value == "version1"

        # Reconfiguration: replace behavior
        b_v2 = Behavior("version2", watermark=time.monotonic())
        fused2 = with_latest_from(trigger, {"data": b_v2})
        ctx2: list[FusedContext] = []
        fused2.subscribe(lambda ts, ctx: ctx2.append(ctx))

        trigger.emit(time.monotonic(), "c2")
        # Old combinator gets old value, new gets new
        assert ctx2[0].samples["data"].value == "version2"
        # Both contexts immutable
        assert isinstance(ctx1[0].samples, MappingProxyType)
        assert isinstance(ctx2[0].samples, MappingProxyType)

    def test_freshness_guard_reconfigured_mid_lifecycle(self):
        """T2+T4+T6: Freshness thresholds tightened mid-lifecycle, system adapts."""
        now = time.monotonic()
        ctx = FusedContext(
            trigger_time=now,
            trigger_value="x",
            samples={"sensor": Stamped(value="ok", watermark=now - 3.0)},
            min_watermark=now - 3.0,
        )

        # Cycle 1: lenient guard → fresh
        guard1 = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="sensor", max_staleness_s=10.0),
            ]
        )
        assert guard1.check(ctx, now).fresh_enough

        # Reconfiguration: tighter guard
        guard2 = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="sensor", max_staleness_s=1.0),
            ]
        )
        assert not guard2.check(ctx, now).fresh_enough

        # Same context, different outcomes based on configuration
        cmd1 = Command(action="process", params={"guard": "lenient"})
        cmd2 = Command(action="pause", params={"guard": "strict"})
        assert cmd1.action != cmd2.action
        assert isinstance(cmd1.params, MappingProxyType)


class TestAdaptiveResilience:
    """Full adaptive resilience: perturbation + reconfiguration + feedback."""

    def test_multi_perturbation_recovery_across_five_cycles(self):
        """T2+T4+T6: 5-cycle adaptive scenario with multiple perturbations."""
        engine = _make_engine(face_detected=True, face_count=1)
        gov = PipelineGovernor(operator_absent_withdraw_s=5.0)
        directives = []

        # Cycle 1: normal
        engine.tick()
        directives.append(gov.evaluate(engine.latest))

        # Cycle 2: perturbation → production mode
        engine.update_slow_fields(activity_mode="production")
        engine.tick()
        directives.append(gov.evaluate(engine.latest))

        # Cycle 3: reconfiguration → wake word to adapt
        gov.wake_word_active = True
        engine.tick()
        directives.append(gov.evaluate(engine.latest))

        # Cycle 4: perturbation clears
        engine.update_slow_fields(activity_mode="idle")
        engine.tick()
        directives.append(gov.evaluate(engine.latest))

        # Cycle 5: stable
        engine.tick()
        directives.append(gov.evaluate(engine.latest))

        assert directives == ["process", "pause", "process", "process", "process"]

    def test_cascading_perturbation_with_progressive_reconfiguration(self):
        """T2+T4+T6: Each perturbation triggers a reconfiguration response."""
        now = time.monotonic()
        chain: VetoChain[FusedContext] = VetoChain()

        # Initial: no vetoes, everything passes
        ctx = FusedContext(
            trigger_time=now,
            trigger_value="init",
            samples={
                "mode": Stamped(value="idle", watermark=now),
                "sensor": Stamped(value="ok", watermark=now),
            },
            min_watermark=now,
        )
        assert chain.evaluate(ctx).allowed

        # Perturbation 1: bad mode → add mode veto
        ctx_bad_mode = FusedContext(
            trigger_time=now,
            trigger_value="p1",
            samples={
                "mode": Stamped(value="meeting", watermark=now),
                "sensor": Stamped(value="ok", watermark=now),
            },
            min_watermark=now,
        )
        chain.add(Veto(name="mode", predicate=lambda c: c.samples["mode"].value != "meeting"))
        r1 = chain.evaluate(ctx_bad_mode)
        assert not r1.allowed

        # Perturbation 2: sensor stale → add freshness veto
        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="sensor", max_staleness_s=5.0),
            ]
        )
        chain.add(
            Veto(name="fresh", predicate=lambda c: guard.check(c, time.monotonic()).fresh_enough)
        )

        ctx_both_bad = FusedContext(
            trigger_time=now,
            trigger_value="p2",
            samples={
                "mode": Stamped(value="meeting", watermark=now),
                "sensor": Stamped(value="ok", watermark=now - 100.0),
            },
            min_watermark=now - 100.0,
        )
        r2 = chain.evaluate(ctx_both_bad)
        assert not r2.allowed
        assert len(r2.denied_by) == 2  # both vetoes fire

        # Recovery: both clear
        ctx_clear = FusedContext(
            trigger_time=now,
            trigger_value="clear",
            samples={
                "mode": Stamped(value="idle", watermark=now),
                "sensor": Stamped(value="ok", watermark=time.monotonic()),
            },
            min_watermark=now,
        )
        r3 = chain.evaluate(ctx_clear)
        assert r3.allowed

    def test_engine_governor_command_adaptive_pipeline(self):
        """T2+T4+T6: Full pipeline adapts: engine perturbed → governor reconfigured → commands shift."""
        engine = _make_engine(face_detected=True, face_count=1)
        commands: list[Command] = []

        # Governor 1: lenient
        gov1 = PipelineGovernor(operator_absent_withdraw_s=60.0)
        engine.tick()
        action = gov1.evaluate(engine.latest)
        commands.append(Command(action=action, params={"config": "lenient"}))

        # Perturbation: production mode
        engine.update_slow_fields(activity_mode="production")
        engine.tick()
        action = gov1.evaluate(engine.latest)
        commands.append(Command(action=action, params={"config": "lenient"}))

        # Reconfiguration: new governor
        gov2 = PipelineGovernor(operator_absent_withdraw_s=0.0)
        gov2.wake_word_active = True  # adapt by enabling wake word
        engine.tick()
        action = gov2.evaluate(engine.latest)
        commands.append(Command(action=action, params={"config": "adapted"}))

        assert commands[0].action == "process"
        assert commands[1].action == "pause"
        assert commands[2].action == "process"  # wake word overrides
        for cmd in commands:
            assert isinstance(cmd.params, MappingProxyType)

    def test_schedule_resilience_through_perturbation_and_recovery(self):
        """T2+T4+T6: Schedule sequence shows perturbation impact and recovery."""
        engine = _make_engine(face_detected=True, face_count=1)
        gov = PipelineGovernor()
        schedules: list[Schedule] = []

        phases = ["idle", "meeting", "idle"]
        for phase in phases:
            engine.update_slow_fields(activity_mode=phase)
            engine.tick()
            action = gov.evaluate(engine.latest)
            cmd = Command(
                action=action,
                params={"phase": phase},
                min_watermark=engine.min_watermark,
            )
            schedules.append(Schedule(command=cmd, target_time=engine.latest.timestamp))

        assert schedules[0].command.action == "process"
        assert schedules[1].command.action == "pause"
        assert schedules[2].command.action == "process"
        # Watermarks advance monotonically
        for i in range(1, len(schedules)):
            assert schedules[i].command.min_watermark >= schedules[i - 1].command.min_watermark
