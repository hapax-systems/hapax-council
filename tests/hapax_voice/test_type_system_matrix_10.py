"""Cross-cutting integration tests for the perception type system (matrix 10).

Feedback / re-entry: governor output feeds back into the next perception
evaluation cycle. Each test simulates 3-4 daemon loop cycles where
cycle N's output influences cycle N+1's input.
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
from agents.hapax_voice.primitives import Behavior, Event, Stamped

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_state(**overrides) -> EnvironmentState:
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
    presence = MagicMock()
    presence.latest_vad_confidence = vad
    presence.face_detected = face_detected
    presence.face_count = face_count
    return PerceptionEngine(presence, MagicMock())


# ── Class 1: Daemon Loop Simulation ─────────────────────────────────────────


class TestDaemonLoopSimulation:
    """Multi-cycle daemon loop where each cycle produces perception → governance → command."""

    def test_three_cycle_idle_to_conversation_to_clear(self):
        """S5, S6, S7 + A2, A3, A4: Three cycles: idle → conversation → clear."""
        engine = _make_engine(face_detected=True, face_count=1, vad=0.0)
        gov = PipelineGovernor(conversation_debounce_s=0.0, environment_clear_resume_s=0.0)

        # Cycle 1: idle
        engine.tick()
        r1 = gov.evaluate(engine.latest)
        cmd1 = Command(action=r1, params={"cycle": 1})

        # Cycle 2: conversation
        engine._presence.face_count = 2
        engine._presence.latest_vad_confidence = 0.8
        engine.tick()
        r2 = gov.evaluate(engine.latest)
        cmd2 = Command(action=r2, params={"cycle": 2}, governance_result=gov.last_veto_result)

        # Cycle 3: cleared
        engine._presence.face_count = 1
        engine._presence.latest_vad_confidence = 0.0
        engine.tick()
        r3 = gov.evaluate(engine.latest)
        cmd3 = Command(action=r3, params={"cycle": 3})

        assert cmd1.action == "process"
        assert cmd2.action == "pause"
        assert cmd3.action == "process"
        assert isinstance(cmd1.params, MappingProxyType)
        assert isinstance(cmd2.params, MappingProxyType)
        assert isinstance(cmd3.params, MappingProxyType)
        assert engine.latest.operator_present is True

    def test_three_cycle_production_to_wake_word_to_production(self):
        """S5, S6, S4 + A2, A3, A5: Production → wake word override → back to production."""
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
                name="custom_fresh",
                predicate=lambda _s: guard.check(ctx, now).fresh_enough,
            )
        )

        state = _make_state(activity_mode="production")

        # Cycle 1: production → pause
        r1 = gov.evaluate(state)
        cmd1 = Command(action=r1, params={"cycle": 1}, governance_result=gov.last_veto_result)

        # Cycle 2: wake word → process
        gov.wake_word_active = True
        r2 = gov.evaluate(state)
        cmd2 = Command(
            action=r2,
            params={"cycle": 2},
            governance_result=gov.last_veto_result,
            selected_by=gov.last_selected.selected_by,
        )

        # Exhaust 3-tick grace period
        for _ in range(3):
            gov.evaluate(state)

        # Cycle 3: grace exhausted → pause
        r3 = gov.evaluate(state)
        cmd3 = Command(action=r3, params={"cycle": 3}, governance_result=gov.last_veto_result)

        assert cmd1.action == "pause"
        assert cmd2.action == "process"
        assert cmd2.selected_by == "wake_word_override"
        assert cmd3.action == "pause"
        assert isinstance(cmd1.params, MappingProxyType)
        assert "not present" in guard.check(ctx, now).violations[0]

    def test_four_cycle_presence_tracking_feedback(self):
        """S7, S5, S6 + A2, A3, A4: Presence tracking across 4 cycles."""
        engine = _make_engine(face_detected=True, face_count=1)
        gov = PipelineGovernor(operator_absent_withdraw_s=5.0)

        # Cycle 1: present → process
        engine.tick()
        r1 = gov.evaluate(engine.latest)
        cmd1 = Command(action=r1, params={"cycle": 1})

        # Cycle 2: absent, just disappeared → process (within 5s threshold)
        engine._presence.face_detected = False
        engine._presence.face_count = 0
        engine.tick()
        r2 = gov.evaluate(engine.latest)
        cmd2 = Command(action=r2, params={"cycle": 2})

        # Cycle 3: force absence beyond threshold → withdraw
        gov._last_operator_seen = time.monotonic() - 10.0
        engine.tick()
        r3 = gov.evaluate(engine.latest)
        cmd3 = Command(
            action=r3,
            params={"cycle": 3},
            selected_by=gov.last_selected.selected_by,
        )

        # Cycle 4: operator returns → process
        engine._presence.face_detected = True
        engine._presence.face_count = 1
        engine.tick()
        r4 = gov.evaluate(engine.latest)
        cmd4 = Command(action=r4, params={"cycle": 4})

        assert cmd1.action == "process"
        assert cmd2.action == "process"
        assert cmd3.action == "withdraw"
        assert cmd3.selected_by == "operator_absent"
        assert cmd4.action == "process"
        assert isinstance(cmd1.params, MappingProxyType)
        assert engine.latest.operator_present is True

    def test_combinator_re_entry_fresh_stale_fresh_cycle(self):
        """S1, S2, S3, S4 + A1, A4, A5: Behavior ages across cycles: fresh → stale → fresh."""
        now = time.monotonic()
        b = Behavior(True, watermark=now)
        trigger: Event[str] = Event()
        fused = with_latest_from(trigger, {"operator_present": b})
        received: list[FusedContext] = []
        fused.subscribe(lambda ts, ctx: received.append(ctx))

        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="operator_present", max_staleness_s=5.0),
            ]
        )
        chain: VetoChain[FusedContext] = VetoChain(
            [
                Veto(name="fresh", predicate=lambda c: guard.check(c, chain_now[0]).fresh_enough),
            ]
        )

        # Cycle 1: fresh (check at now+1)
        chain_now = [now + 1.0]
        trigger.emit(now + 1.0, "c1")
        r1 = chain.evaluate(received[-1])
        assert r1.allowed is True

        # Cycle 2: stale (check at now+7, behavior not updated)
        chain_now[0] = now + 7.0
        trigger.emit(now + 7.0, "c2")
        r2 = chain.evaluate(received[-1])
        assert r2.allowed is False

        # Cycle 3: update behavior, fresh again
        b.update(True, now + 8.0)
        chain_now[0] = now + 9.0
        trigger.emit(now + 9.0, "c3")
        r3 = chain.evaluate(received[-1])
        assert r3.allowed is True

        assert "operator_present" in received[0].samples
        assert isinstance(received[0].samples, MappingProxyType)

        # Missing behavior
        gm = FreshnessGuard([FreshnessRequirement("nope", 1.0)])
        assert "not present" in gm.check(received[0], now).violations[0]


# ── Class 2: Feedback State Accumulation ─────────────────────────────────────


class TestFeedbackStateAccumulation:
    """State accumulates across cycles, affecting subsequent evaluations."""

    def test_conversation_debounce_state_accumulates_across_cycles(self):
        """S5, S6, S7 + A2, A3, A4: Debounce timer accumulates across cycles."""
        engine = _make_engine(face_detected=True, face_count=2, vad=0.8)
        gov = PipelineGovernor(conversation_debounce_s=100.0)  # Long debounce

        # Cycle 1: conversation starts, under debounce → process
        engine.tick()
        r1 = gov.evaluate(engine.latest)
        assert r1 == "process"

        # Cycle 2: conversation continues, still under debounce → process
        engine.tick()
        r2 = gov.evaluate(engine.latest)
        assert r2 == "process"

        # Cycle 3: force past debounce
        gov._conversation_first_seen = time.monotonic() - 200.0
        engine.tick()
        r3 = gov.evaluate(engine.latest)
        assert r3 == "pause"
        assert gov._paused_by_conversation is True

        cmd = Command(action=r3, params={"debounced": True}, governance_result=gov.last_veto_result)
        assert isinstance(cmd.params, MappingProxyType)
        assert engine.latest.operator_present is True

    def test_veto_addition_feedback_across_cycles(self):
        """S4, S5, S6 + A1, A2, A3: Veto chain grows across cycles."""
        now = time.monotonic()
        gov = PipelineGovernor()
        state = _make_state(activity_mode="idle")

        # Cycle 1: no custom vetoes → process
        r1 = gov.evaluate(state)
        cmd1 = Command(action=r1, params={"cycle": 1}, governance_result=gov.last_veto_result)

        # Between cycles: add veto
        gov.veto_chain.add(Veto(name="veto_a", predicate=lambda _s: False))

        # Cycle 2: 1 custom denial → pause
        r2 = gov.evaluate(state)
        cmd2 = Command(action=r2, params={"cycle": 2}, governance_result=gov.last_veto_result)

        # Between cycles: add another
        gov.veto_chain.add(Veto(name="veto_b", predicate=lambda _s: False))

        # Cycle 3: 2 custom denials → pause
        r3 = gov.evaluate(state)
        cmd3 = Command(action=r3, params={"cycle": 3}, governance_result=gov.last_veto_result)

        assert cmd1.action == "process"
        assert cmd2.action == "pause"
        assert len(cmd2.governance_result.denied_by) == 1
        assert cmd3.action == "pause"
        assert len(cmd3.governance_result.denied_by) == 2
        assert isinstance(cmd1.params, MappingProxyType)

        ctx = FusedContext(trigger_time=now, trigger_value="x", samples={"a": Stamped(1, now)})
        assert isinstance(ctx.samples, MappingProxyType)

    def test_freshness_aging_across_combinator_cycles(self):
        """S1, S2, S3, S6 + A1, A2, A5: Behavior ages across cycles without update."""
        b = Behavior("data", watermark=100.0)
        trigger: Event[str] = Event()
        fused = with_latest_from(trigger, {"val": b})
        received: list[FusedContext] = []
        fused.subscribe(lambda ts, ctx: received.append(ctx))

        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="val", max_staleness_s=5.0),
                FreshnessRequirement(behavior_name="missing", max_staleness_s=5.0),
            ]
        )

        # Cycle 1: check at 101 → val fresh (1s < 5s), but missing fails
        trigger.emit(101.0, "c1")
        f1 = guard.check(received[-1], 101.0)
        cmd1 = Command(action="pause" if not f1.fresh_enough else "process", params={"cycle": 1})

        # Cycle 2: check at 106 → val stale (6s > 5s)
        trigger.emit(106.0, "c2")
        f2 = guard.check(received[-1], 106.0)
        cmd2 = Command(action="pause" if not f2.fresh_enough else "process", params={"cycle": 2})

        # Cycle 3: update behavior, check at 108 → val fresh again
        b.update("fresh_data", 107.0)
        trigger.emit(108.0, "c3")
        f3 = guard.check(received[-1], 108.0)
        cmd3 = Command(action="pause" if not f3.fresh_enough else "process", params={"cycle": 3})

        # All pause because missing behavior always fails
        assert cmd1.action == "pause"
        assert cmd2.action == "pause"
        assert cmd3.action == "pause"
        # But violation count varies
        assert any("not present" in v for v in f1.violations)
        assert isinstance(cmd1.params, MappingProxyType)
        assert isinstance(received[0].samples, MappingProxyType)

    def test_governor_observability_state_feedback(self):
        """S5, S6, S3 + A2, A3, A5: Observability fields update each cycle."""
        now = time.monotonic()
        gov = PipelineGovernor()

        # Cycle 1: idle → process
        state1 = _make_state(activity_mode="idle")
        gov.evaluate(state1)
        assert gov.last_veto_result.allowed is True
        assert gov.last_selected.selected_by == "default"
        cmd1 = Command(action="process", params={"cycle": 1})

        # Cycle 2: production → pause
        state2 = _make_state(activity_mode="production")
        gov.evaluate(state2)
        assert gov.last_veto_result.allowed is False
        cmd2 = Command(action="pause", params={"cycle": 2}, governance_result=gov.last_veto_result)

        # Cycle 3: wake word → process
        gov.wake_word_active = True
        gov.evaluate(state2)
        assert gov.last_veto_result.allowed is True
        assert gov.last_selected.selected_by == "wake_word_override"
        cmd3 = Command(action="process", params={"cycle": 3})

        assert isinstance(cmd1.params, MappingProxyType)
        assert isinstance(cmd2.params, MappingProxyType)
        assert isinstance(cmd3.params, MappingProxyType)

        guard = FreshnessGuard([FreshnessRequirement("missing", 1.0)])
        ctx = FusedContext(trigger_time=now, trigger_value="x", samples={})
        assert "not present" in guard.check(ctx, now).violations[0]


# ── Class 3: Cyclic Pipeline Integrity ───────────────────────────────────────


class TestCyclicPipelineIntegrity:
    """Pipeline produces coherent outputs across multiple daemon cycles."""

    def test_schedule_sequence_integrity_across_cycles(self):
        """S5, S6, S7 + A2, A3, A4: Schedules form coherent timeline across cycles."""
        engine = _make_engine(face_detected=True, face_count=1)
        gov = PipelineGovernor()

        schedules: list[Schedule] = []
        for i in range(3):
            engine.tick()
            state = engine.latest
            r = gov.evaluate(state)
            cmd = Command(
                action=r,
                params={"cycle": i},
                governance_result=gov.last_veto_result,
                min_watermark=engine.min_watermark,
            )
            sched = Schedule(command=cmd, target_time=float(i), wall_time=time.time())
            schedules.append(sched)

        assert schedules[0].target_time < schedules[1].target_time < schedules[2].target_time
        # Watermarks non-decreasing
        wms = [s.command.min_watermark for s in schedules]
        assert wms[0] <= wms[1] <= wms[2]
        assert isinstance(schedules[0].command.params, MappingProxyType)
        assert engine.latest.operator_present is True

    def test_combinator_subscriber_stability_across_cycles(self):
        """S2, S7, S1, S3 + A1, A4, A5: Subscriber wiring survives multiple cycles."""
        engine = _make_engine(face_detected=True, face_count=1)

        trigger: Event[str] = Event()
        fused = with_latest_from(trigger, engine.behaviors)
        received: list[FusedContext] = []
        fused.subscribe(lambda ts, ctx: received.append(ctx))

        for _ in range(3):
            engine.tick()
            trigger.emit(time.monotonic(), "tick")

        assert len(received) == 3

        # Watermarks non-decreasing
        wms = [ctx.min_watermark for ctx in received]
        assert wms[0] <= wms[1] <= wms[2]

        for ctx in received:
            assert "operator_present" in ctx.samples
            assert isinstance(ctx.samples, MappingProxyType)

        guard = FreshnessGuard([FreshnessRequirement("nonexistent", 1.0)])
        assert "not present" in guard.check(received[0], time.monotonic()).violations[0]

    def test_wake_word_single_use_does_not_leak_across_cycles(self):
        """S5, S6, S4 + A2, A3, A5: Wake word consumed in one cycle, not available in next."""
        now = time.monotonic()
        ctx = FusedContext(trigger_time=now, trigger_value="x", samples={}, min_watermark=now)
        guard = FreshnessGuard([FreshnessRequirement("missing", 1.0)])

        gov = PipelineGovernor()
        gov.veto_chain.add(
            Veto(
                name="fresh_check",
                predicate=lambda _s: guard.check(ctx, now).fresh_enough,
            )
        )

        state = _make_state(activity_mode="production")

        # Cycle 1: wake word → process
        gov.wake_word_active = True
        r1 = gov.evaluate(state)
        assert r1 == "process"
        assert gov.wake_word_active is False

        # Grace period: 3 ticks return "process" with wake_word_grace
        for _ in range(3):
            rg = gov.evaluate(state)
            assert rg == "process"
            assert gov.last_selected.selected_by == "wake_word_grace"

        # Cycle 2: grace exhausted → pause
        r2 = gov.evaluate(state)
        assert r2 == "pause"

        # Cycle 3: still paused → pause
        r3 = gov.evaluate(state)
        assert r3 == "pause"

        # Cycle 4: re-set → process
        gov.wake_word_active = True
        r4 = gov.evaluate(state)
        assert r4 == "process"
        assert gov.wake_word_active is False

        cmds = [Command(action=r, params={"cycle": i}) for i, r in enumerate([r1, r2, r3, r4], 1)]
        assert [c.action for c in cmds] == ["process", "pause", "pause", "process"]
        assert all(isinstance(c.params, MappingProxyType) for c in cmds)
        assert "not present" in guard.check(ctx, now).violations[0]

    def test_full_daemon_loop_perception_to_governance_three_cycles(self):
        """S7, S1, S2, S5, S6 + A1, A2, A4: Full daemon loop with presence flip."""
        engine = _make_engine(face_detected=True, face_count=1)
        gov = PipelineGovernor()

        trigger: Event[str] = Event()
        fused = with_latest_from(trigger, engine.behaviors)
        contexts: list[FusedContext] = []
        fused.subscribe(lambda ts, ctx: contexts.append(ctx))

        schedules: list[Schedule] = []

        # Cycle 1: present
        engine.tick()
        trigger.emit(time.monotonic(), "c1")
        state1 = engine.latest
        r1 = gov.evaluate(state1)
        cmd1 = Command(
            action=r1,
            params={"cycle": 1},
            min_watermark=contexts[-1].min_watermark,
        )
        schedules.append(Schedule(command=cmd1, target_time=1.0))

        # Cycle 2: absent
        engine._presence.face_detected = False
        engine._presence.face_count = 0
        engine.tick()
        trigger.emit(time.monotonic(), "c2")
        state2 = engine.latest
        r2 = gov.evaluate(state2)
        cmd2 = Command(
            action=r2,
            params={"cycle": 2},
            min_watermark=contexts[-1].min_watermark,
        )
        schedules.append(Schedule(command=cmd2, target_time=2.0))

        # Cycle 3: present again
        engine._presence.face_detected = True
        engine._presence.face_count = 1
        engine.tick()
        trigger.emit(time.monotonic(), "c3")
        state3 = engine.latest
        r3 = gov.evaluate(state3)
        cmd3 = Command(
            action=r3,
            params={"cycle": 3},
            min_watermark=contexts[-1].min_watermark,
        )
        schedules.append(Schedule(command=cmd3, target_time=3.0))

        # operator_present flips
        assert contexts[0].get_sample("operator_present").value is True
        assert contexts[1].get_sample("operator_present").value is False
        assert contexts[2].get_sample("operator_present").value is True

        # All immutable
        assert all(isinstance(s.command.params, MappingProxyType) for s in schedules)
        assert all(isinstance(c.samples, MappingProxyType) for c in contexts)

        # Watermarks advance
        wms = [c.min_watermark for c in contexts]
        assert wms[0] <= wms[1] <= wms[2]
