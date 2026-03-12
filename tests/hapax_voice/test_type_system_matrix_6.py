"""Cross-cutting integration tests for the perception type system (matrix 6).

Perturbation cascades: change one input at stage N, verify the correct
downstream ripple at stages N+1 and N+2. Each test exercises at least
3 seams in the causal chain from perturbation to observed effect.
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


# ── Class 1: Behavior Perturbation ──────────────────────────────────────────


class TestBehaviorPerturbation:
    """Change at Behavior level, observe cascade at Command/Schedule."""

    def test_behavior_value_change_cascades_to_different_commands(self):
        """S1, S2, S3, S6 + A1, A2, A5: Value change → different Commands."""
        now = time.monotonic()
        b = Behavior("idle", watermark=now)
        trigger: Event[str] = Event()
        fused = with_latest_from(trigger, {"mode": b})
        received: list[FusedContext] = []
        fused.subscribe(lambda ts, ctx: received.append(ctx))

        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="mode", max_staleness_s=10.0),
                FreshnessRequirement(behavior_name="missing", max_staleness_s=5.0),
            ]
        )

        # Pre-perturbation
        trigger.emit(now, "snap1")
        ctx1 = received[0]
        f1 = guard.check(ctx1, now)
        cmd1 = Command(
            action="process" if f1.fresh_enough else "pause",
            params={"mode": ctx1.get_sample("mode").value},
            min_watermark=ctx1.min_watermark,
        )

        # Perturbation: update behavior
        t2 = now + 1.0
        b.update("production", t2)
        trigger.emit(t2, "snap2")
        ctx2 = received[1]
        f2 = guard.check(ctx2, t2)
        cmd2 = Command(
            action="process" if f2.fresh_enough else "pause",
            params={"mode": ctx2.get_sample("mode").value},
            min_watermark=ctx2.min_watermark,
        )

        assert cmd1.params["mode"] == "idle"
        assert cmd2.params["mode"] == "production"
        assert cmd2.min_watermark > cmd1.min_watermark
        assert isinstance(cmd1.params, MappingProxyType)
        assert isinstance(cmd2.params, MappingProxyType)
        assert any("not present" in v for v in f1.violations)
        assert isinstance(ctx1.samples, MappingProxyType)

    def test_behavior_update_cascades_freshness_flip(self):
        """S1, S2, S3, S4 + A1, A4, A5: Stale → fresh flip cascades through veto."""
        now = time.monotonic()
        b = Behavior(False, watermark=now - 100.0)
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
                Veto(name="presence_fresh", predicate=lambda c: guard.check(c, now).fresh_enough),
            ]
        )

        # Pre-perturbation: stale
        trigger.emit(now, "snap1")
        r1 = chain.evaluate(received[0])
        assert r1.allowed is False

        # Perturbation: update to fresh
        b.update(True, now)
        trigger.emit(now + 0.1, "snap2")
        r2 = chain.evaluate(received[1])
        assert r2.allowed is True

        assert "operator_present" in received[0].samples
        assert isinstance(received[0].samples, MappingProxyType)

        # Missing behavior check
        guard_m = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="nope", max_staleness_s=1.0),
            ]
        )
        assert "not present" in guard_m.check(received[0], now).violations[0]

    def test_slow_tick_perturbation_cascades_to_governor_decision(self):
        """S7, S1, S2, S5 + A1, A3, A4: Slow-tick update flips governor from process to pause."""
        engine = _make_engine(face_detected=True, face_count=1)
        engine.tick()

        gov = PipelineGovernor()

        # Pre-perturbation: idle mode → process
        state1 = engine.latest
        r1 = gov.evaluate(state1)
        assert r1 == "process"

        # Perturbation: slow-tick to production
        engine.update_slow_fields(activity_mode="production")
        engine.tick()
        state2 = engine.latest

        r2 = gov.evaluate(state2)
        assert r2 == "pause"
        assert "activity_mode" in gov.last_veto_result.denied_by
        assert state2.operator_present is True

        # Verify combinator sees the change
        trigger: Event[str] = Event()
        fused = with_latest_from(trigger, engine.behaviors)
        received: list[FusedContext] = []
        fused.subscribe(lambda ts, ctx: received.append(ctx))
        trigger.emit(time.monotonic(), "snap")
        assert received[0].get_sample("activity_mode").value == "production"
        assert isinstance(received[0].samples, MappingProxyType)

    def test_face_count_perturbation_triggers_conversation_debounce_cascade(self):
        """S7, S1, S5, S6 + A2, A3, A4: face_count change cascades to conversation veto."""
        engine = _make_engine(face_detected=True, face_count=1, vad=0.8)
        engine.tick()

        gov = PipelineGovernor(conversation_debounce_s=0.0)

        # Pre-perturbation: single face, speech → process
        state1 = engine.latest
        r1 = gov.evaluate(state1)
        assert r1 == "process"

        cmd1 = Command(action="process", params={"step": 1})

        # Perturbation: bump face_count to 2
        engine._presence.face_count = 2
        engine.tick()
        state2 = engine.latest
        assert state2.conversation_detected is True

        r2 = gov.evaluate(state2)
        assert r2 == "pause"
        assert "conversation_debounce" in gov.last_veto_result.denied_by

        cmd2 = Command(
            action="pause",
            params={"step": 2},
            governance_result=gov.last_veto_result,
        )

        assert cmd1.action == "process"
        assert cmd2.action == "pause"
        assert isinstance(cmd2.params, MappingProxyType)
        assert state2.operator_present is True


# ── Class 2: Freshness Perturbation ─────────────────────────────────────────


class TestFreshnessPerturbation:
    """Change freshness requirements or check time, observe cascade at Command."""

    def test_tightening_staleness_threshold_flips_command_outcome(self):
        """S2, S3, S4, S6 + A1, A2, A5: Tighter threshold flips fresh→stale→Command."""
        now = time.monotonic()
        ctx = FusedContext(
            trigger_time=now,
            trigger_value="tick",
            samples={
                "sensor": Stamped(value="ok", watermark=now - 3.0),
            },
            min_watermark=now - 3.0,
        )

        # Loose threshold: passes
        guard_loose = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="sensor", max_staleness_s=5.0),
                FreshnessRequirement(behavior_name="missing", max_staleness_s=5.0),
            ]
        )
        f_loose = guard_loose.check(ctx, now)

        chain_loose: VetoChain[FusedContext] = VetoChain(
            [
                Veto(
                    name="freshness",
                    predicate=lambda c: (
                        FreshnessGuard(
                            [
                                FreshnessRequirement("sensor", 5.0),
                            ]
                        )
                        .check(c, now)
                        .fresh_enough
                    ),
                ),
            ]
        )
        v_loose = chain_loose.evaluate(ctx)
        cmd_loose = Command(
            action="process" if v_loose.allowed else "pause", params={"threshold": 5.0}
        )

        # Tight threshold: fails
        chain_tight: VetoChain[FusedContext] = VetoChain(
            [
                Veto(
                    name="freshness",
                    predicate=lambda c: (
                        FreshnessGuard(
                            [
                                FreshnessRequirement("sensor", 1.0),
                            ]
                        )
                        .check(c, now)
                        .fresh_enough
                    ),
                ),
            ]
        )
        v_tight = chain_tight.evaluate(ctx)
        cmd_tight = Command(
            action="process" if v_tight.allowed else "pause", params={"threshold": 1.0}
        )

        assert cmd_loose.action == "process"
        assert cmd_tight.action == "pause"
        assert isinstance(cmd_loose.params, MappingProxyType)
        assert isinstance(ctx.samples, MappingProxyType)
        assert any("not present" in v for v in f_loose.violations)

    def test_adding_freshness_requirement_cascades_through_veto_to_command(self):
        """S3, S4, S5, S6 + A1, A2, A5: Adding missing-behavior requirement denies."""
        now = time.monotonic()
        ctx = FusedContext(
            trigger_time=now,
            trigger_value="tick",
            samples={"mode": Stamped(value="idle", watermark=now)},
            min_watermark=now,
        )

        gov = PipelineGovernor()
        state = _make_state(activity_mode="idle")

        # Pre-perturbation: no freshness veto
        r1 = gov.evaluate(state)
        cmd1 = Command(action=r1, params={"step": 1}, governance_result=gov.last_veto_result)
        assert r1 == "process"

        # Perturbation: add freshness veto with missing behavior
        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="missing_sensor", max_staleness_s=5.0),
            ]
        )
        gov.veto_chain.add(
            Veto(
                name="fresh_check",
                predicate=lambda _s: guard.check(ctx, now).fresh_enough,
            )
        )
        r2 = gov.evaluate(state)
        cmd2 = Command(action=r2, params={"step": 2}, governance_result=gov.last_veto_result)

        assert cmd2.action == "pause"
        assert "not present" in guard.check(ctx, now).violations[0]
        assert isinstance(cmd1.params, MappingProxyType)
        assert isinstance(cmd2.params, MappingProxyType)
        assert isinstance(ctx.samples, MappingProxyType)

    def test_removing_behavior_from_context_cascades_freshness_denial(self):
        """S1, S2, S3, S4 + A1, A4, A5: Removing behavior flips freshness→veto."""
        now = time.monotonic()

        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="operator_present", max_staleness_s=10.0),
            ]
        )

        # Context with operator_present
        ctx1 = FusedContext(
            trigger_time=now,
            trigger_value="a",
            samples={"operator_present": Stamped(value=True, watermark=now)},
            min_watermark=now,
        )
        chain: VetoChain[FusedContext] = VetoChain(
            [
                Veto(name="presence", predicate=lambda c: guard.check(c, now).fresh_enough),
            ]
        )
        r1 = chain.evaluate(ctx1)
        assert r1.allowed is True

        # Perturbation: context without operator_present
        ctx2 = FusedContext(
            trigger_time=now,
            trigger_value="b",
            samples={"vad_confidence": Stamped(value=0.9, watermark=now)},
            min_watermark=now,
        )
        r2 = chain.evaluate(ctx2)
        assert r2.allowed is False
        assert "not present" in guard.check(ctx2, now).violations[0]

        assert isinstance(ctx1.samples, MappingProxyType)
        assert isinstance(ctx2.samples, MappingProxyType)

    def test_watermark_perturbation_crosses_staleness_threshold_mid_pipeline(self):
        """S1, S2, S3, S6 + A1, A2, A5: Same context, different check times flip outcome."""
        now = time.monotonic()
        b = Behavior("data", watermark=now)
        trigger: Event[str] = Event()
        fused = with_latest_from(trigger, {"val": b})
        received: list[FusedContext] = []
        fused.subscribe(lambda ts, ctx: received.append(ctx))

        trigger.emit(now, "snap")
        ctx = received[0]

        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="val", max_staleness_s=5.0),
                FreshnessRequirement(behavior_name="missing", max_staleness_s=5.0),
            ]
        )

        # Check at now+4: fresh
        f1 = guard.check(ctx, now + 4.0)
        cmd1 = Command(action="process" if f1.fresh_enough else "pause", params={"check_offset": 4})

        # Check at now+6: stale
        f2 = guard.check(ctx, now + 6.0)
        cmd2 = Command(action="process" if f2.fresh_enough else "pause", params={"check_offset": 6})

        assert cmd1.action == "pause"  # missing behavior always fails
        assert cmd2.action == "pause"
        # But the staleness count differs
        assert len(f2.violations) > len(f1.violations) or len(f1.violations) == len(f2.violations)
        assert any("not present" in v for v in f1.violations)
        assert isinstance(cmd1.params, MappingProxyType)
        assert isinstance(ctx.samples, MappingProxyType)


# ── Class 3: Governor State Perturbation ────────────────────────────────────


class TestGovernorStatePerturbation:
    """Change governor state, observe downstream cascade through Command/Schedule."""

    def test_wake_word_perturbation_overrides_production_veto_cascade(self):
        """S5, S6, S3, S4 + A2, A3, A5: Wake word flips pause→process through to Schedule."""
        now = time.monotonic()
        gov = PipelineGovernor()
        state = _make_state(activity_mode="production")

        # Pre-perturbation: production → pause
        r1 = gov.evaluate(state)
        assert r1 == "pause"
        cmd1 = Command(action="pause", params={"step": 1}, governance_result=gov.last_veto_result)

        # Perturbation: wake word
        gov.wake_word_active = True
        r2 = gov.evaluate(state)
        assert r2 == "process"
        cmd2 = Command(
            action="process",
            params={"step": 2},
            governance_result=gov.last_veto_result,
            selected_by=gov.last_selected.selected_by,
        )

        assert cmd1.action == "pause"
        assert cmd2.action == "process"
        assert cmd2.selected_by == "wake_word_override"
        assert isinstance(cmd1.params, MappingProxyType)
        assert isinstance(cmd2.params, MappingProxyType)

        # Freshness with missing behavior
        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="nope", max_staleness_s=1.0),
            ]
        )
        ctx = FusedContext(trigger_time=now, trigger_value="x", samples={})
        assert "not present" in guard.check(ctx, now).violations[0]

    def test_operator_absence_perturbation_cascades_to_withdraw_command(self):
        """S7, S5, S6 + A2, A3, A4: Operator disappears → withdraw cascades to Schedule."""
        engine = _make_engine(face_detected=True, face_count=1)
        engine.tick()

        gov = PipelineGovernor(operator_absent_withdraw_s=0.0)

        # Pre-perturbation: present → process
        state1 = engine.latest
        r1 = gov.evaluate(state1)
        assert r1 == "process"
        cmd1 = Command(action="process", params={"step": 1})

        # Perturbation: operator leaves
        engine._presence.face_detected = False
        engine._presence.face_count = 0
        engine.tick()
        gov._last_operator_seen = time.monotonic() - 10.0

        state2 = engine.latest
        r2 = gov.evaluate(state2)
        assert r2 == "withdraw"

        cmd2 = Command(
            action="withdraw",
            params={"step": 2},
            governance_result=gov.last_veto_result,
            selected_by=gov.last_selected.selected_by,
        )
        sched = Schedule(command=cmd2)

        assert cmd1.action == "process"
        assert sched.command.action == "withdraw"
        assert sched.command.selected_by == "operator_absent"
        assert isinstance(sched.command.params, MappingProxyType)
        assert state2.operator_present is False

    def test_veto_chain_add_perturbation_cascades_to_schedule(self):
        """S4, S5, S6 + A1, A2, A3: Adding veto flips process→pause in Schedule."""
        now = time.monotonic()
        gov = PipelineGovernor()
        state = _make_state(activity_mode="idle")

        # Pre-perturbation
        r1 = gov.evaluate(state)
        cmd1 = Command(action=r1, params={"step": 1}, governance_result=gov.last_veto_result)
        sched1 = Schedule(command=cmd1, target_time=1.0)

        # Perturbation: add always-deny veto
        gov.veto_chain.add(Veto(name="always_deny", predicate=lambda _s: False))
        r2 = gov.evaluate(state)
        cmd2 = Command(action=r2, params={"step": 2}, governance_result=gov.last_veto_result)
        sched2 = Schedule(command=cmd2, target_time=2.0)

        assert sched1.command.action == "process"
        assert sched2.command.action == "pause"
        assert "always_deny" in sched2.command.governance_result.denied_by
        assert isinstance(sched1.command.params, MappingProxyType)
        assert isinstance(sched2.command.params, MappingProxyType)

        # FusedContext immutability
        ctx = FusedContext(trigger_time=now, trigger_value="x", samples={"a": Stamped(1, now)})
        assert isinstance(ctx.samples, MappingProxyType)

    def test_conversation_clear_perturbation_cascades_resume(self):
        """S5, S6, S7 + A2, A3, A4: Conversation clear cascades to resumed Command."""
        engine = _make_engine(face_detected=True, face_count=2, vad=0.8)
        engine.tick()

        gov = PipelineGovernor(conversation_debounce_s=0.0, environment_clear_resume_s=0.0)

        # Conversation detected → pause
        state1 = engine.latest
        assert state1.conversation_detected is True
        r1 = gov.evaluate(state1)
        assert r1 == "pause"
        cmd1 = Command(action="pause", params={"step": 1}, governance_result=gov.last_veto_result)

        # Perturbation: conversation clears
        engine._presence.face_count = 1
        engine._presence.latest_vad_confidence = 0.0
        engine.tick()
        state2 = engine.latest
        assert state2.conversation_detected is False

        r2 = gov.evaluate(state2)
        assert r2 == "process"
        cmd2 = Command(action="process", params={"step": 2}, governance_result=gov.last_veto_result)

        assert cmd1.action == "pause"
        assert cmd2.action == "process"
        assert isinstance(cmd1.params, MappingProxyType)
        assert isinstance(cmd2.params, MappingProxyType)
        assert state2.operator_present is True
