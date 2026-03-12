"""Cross-cutting integration tests for the perception type system (matrix 16).

Holistic steady-state (Q6): composes ALL trinary themes — forward pipeline
flow (T1), perturbation cascades (T2), convergent pipelines (T3),
reconfiguration invariants (T4), provenance tracing (T5), and feedback/
re-entry (T6). Each test exercises the full system under combined pressures,
verifying convergence to correct steady state.
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
from agents.hapax_voice.primitives import Event

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


# ── Q6: Holistic Steady-State ────────────────────────────────────────────────


class TestFullSystemConvergence:
    """All themes active — system converges to correct steady state."""

    def test_six_cycle_full_system_convergence(self):
        """T1-T6: Full daemon lifecycle with every theme exercised.

        Cycle 1: forward pipeline (T1)
        Cycle 2: perturbation — meeting mode (T2)
        Cycle 3: convergent — combinator + governor agree (T3)
        Cycle 4: reconfiguration — wake word (T4)
        Cycle 5: provenance — traceable through schedule (T5)
        Cycle 6: feedback — stable steady state (T6)
        """
        engine = _make_engine(face_detected=True, face_count=1)
        gov = PipelineGovernor()
        trigger: Event[str] = Event()
        fused = with_latest_from(trigger, engine.behaviors)
        ctx_log: list[FusedContext] = []
        fused.subscribe(lambda ts, ctx: ctx_log.append(ctx))

        guard = FreshnessGuard([
            FreshnessRequirement(behavior_name="operator_present", max_staleness_s=30.0),
        ])

        schedules: list[Schedule] = []

        for cycle in range(6):
            # T2: perturbation at cycle 2
            if cycle == 2:
                engine.update_slow_fields(activity_mode="meeting")
            # T4: reconfiguration at cycle 4
            if cycle == 4:
                gov.wake_word_active = True
            # T2: perturbation clears at cycle 5
            if cycle == 5:
                engine.update_slow_fields(activity_mode="idle")

            # T1: forward pipeline
            engine.tick()
            action = gov.evaluate(engine.latest)

            # T3: convergent — combinator path
            trigger.emit(time.monotonic(), f"cycle_{cycle}")
            ctx = ctx_log[-1]
            freshness = guard.check(ctx, time.monotonic())

            # T5: provenance in command
            cmd = Command(
                action=action,
                params={
                    "cycle": cycle,
                    "fresh": freshness.fresh_enough,
                    "op_present": engine.latest.operator_present,
                },
                min_watermark=ctx.min_watermark,
                governance_result=gov.last_veto_result,
                selected_by=(gov.last_selected.selected_by if gov.last_selected else "vetoed"),
            )
            # T6: schedule feeds forward
            schedules.append(Schedule(command=cmd, target_time=engine.latest.timestamp))

        actions = [s.command.action for s in schedules]
        assert actions[0] == "process"  # idle
        assert actions[1] == "process"  # still idle
        assert actions[2] == "pause"    # meeting perturbation
        assert actions[3] == "pause"    # meeting persists
        assert actions[4] == "process"  # wake word override
        assert actions[5] == "process"  # steady state restored

        # Provenance traceable
        assert schedules[4].command.selected_by == "wake_word_override"
        assert all(s.command.params["fresh"] for s in schedules)

    def test_convergent_perturbation_with_provenance_feedback(self):
        """T1-T6: Two convergent paths perturbed, provenance feeds back across cycles."""
        engine = _make_engine(face_detected=True, face_count=1)
        gov = PipelineGovernor()

        # External freshness chain
        guard = FreshnessGuard([
            FreshnessRequirement(behavior_name="operator_present", max_staleness_s=30.0),
        ])
        chain: VetoChain[FusedContext] = VetoChain([
            Veto(name="freshness", predicate=lambda c: guard.check(c, time.monotonic()).fresh_enough),
        ])

        trigger: Event[str] = Event()
        fused = with_latest_from(trigger, engine.behaviors)
        ctx_log: list[FusedContext] = []
        fused.subscribe(lambda ts, ctx: ctx_log.append(ctx))

        commands: list[Command] = []
        for cycle in range(3):
            if cycle == 1:
                engine.update_slow_fields(activity_mode="production")

            engine.tick()

            # Path A: governor
            gov_action = gov.evaluate(engine.latest)

            # Path B: combinator → veto chain
            trigger.emit(time.monotonic(), f"c{cycle}")
            veto = chain.evaluate(ctx_log[-1])

            # Merge convergent results
            final_action = "pause" if (gov_action == "pause" or not veto.allowed) else gov_action
            cmd = Command(
                action=final_action,
                params={"gov": gov_action, "veto_ok": veto.allowed},
                governance_result=gov.last_veto_result,
            )
            commands.append(cmd)

        assert commands[0].action == "process"
        assert commands[1].action == "pause"  # production mode
        assert commands[1].params["gov"] == "pause"

    def test_reconfigured_pipeline_with_dual_path_provenance(self):
        """T1-T6: Pipeline reconfigured, dual paths carry provenance through."""
        engine = _make_engine(face_detected=True, face_count=1)
        schedules: list[Schedule] = []

        gov_configs = [
            PipelineGovernor(),
            PipelineGovernor(conversation_debounce_s=0.0),
        ]

        for i, gov in enumerate(gov_configs):
            # T2: perturbation at config 1
            if i == 1:
                engine.update_slow_fields(activity_mode="meeting")

            engine.tick()

            # T1: forward path A
            action = gov.evaluate(engine.latest)

            # T3: convergent path B
            trigger: Event[str] = Event()
            fused = with_latest_from(trigger, engine.behaviors)
            ctxs: list[FusedContext] = []
            fused.subscribe(lambda ts, ctx: ctxs.append(ctx))
            trigger.emit(time.monotonic(), f"config_{i}")

            # T5: provenance
            cmd = Command(
                action=action,
                params={
                    "config": i,
                    "combinator_wm": ctxs[0].min_watermark,
                    "op_present": ctxs[0].samples["operator_present"].value,
                },
                min_watermark=engine.min_watermark,
                governance_result=gov.last_veto_result,
            )
            # T6: schedule carries forward
            schedules.append(Schedule(command=cmd))

        assert schedules[0].command.action == "process"
        assert schedules[1].command.action == "pause"
        assert schedules[1].command.params["config"] == 1
        assert isinstance(schedules[0].command.params, MappingProxyType)

    def test_five_cycle_all_governor_paths_with_provenance(self):
        """T1-T6: 5 cycles hitting every governor path, full provenance chain."""
        engine = _make_engine(face_detected=True, face_count=1)
        gov = PipelineGovernor(
            operator_absent_withdraw_s=5.0,
            conversation_debounce_s=0.0,
        )

        # Cycle 1: idle → process
        engine.tick()
        r1 = gov.evaluate(engine.latest)
        cmd1 = Command(
            action=r1, params={"desc": "idle"},
            governance_result=gov.last_veto_result,
            selected_by=(gov.last_selected.selected_by if gov.last_selected else "vetoed"),
        )

        # Cycle 2: meeting → pause
        engine.update_slow_fields(activity_mode="meeting")
        engine.tick()
        r2 = gov.evaluate(engine.latest)
        cmd2 = Command(
            action=r2, params={"desc": "meeting"},
            governance_result=gov.last_veto_result,
            selected_by=(gov.last_selected.selected_by if gov.last_selected else "vetoed"),
        )

        # Cycle 3: wake word → process
        gov.wake_word_active = True
        engine.tick()
        r3 = gov.evaluate(engine.latest)
        cmd3 = Command(
            action=r3, params={"desc": "wake_word"},
            governance_result=gov.last_veto_result,
            selected_by=(gov.last_selected.selected_by if gov.last_selected else "vetoed"),
        )

        # Exhaust 3-tick grace period
        for _ in range(3):
            engine.tick()
            gov.evaluate(engine.latest)

        # Cycle 4: absent → withdraw
        engine._presence.face_detected = False
        engine._presence.face_count = 0
        engine.update_slow_fields(activity_mode="idle")
        gov._last_operator_seen = time.monotonic() - 10.0
        engine.tick()
        r4 = gov.evaluate(engine.latest)
        cmd4 = Command(
            action=r4, params={"desc": "absent"},
            governance_result=gov.last_veto_result,
            selected_by=(gov.last_selected.selected_by if gov.last_selected else "vetoed"),
        )

        # Cycle 5: return → process
        engine._presence.face_detected = True
        engine._presence.face_count = 1
        engine.tick()
        r5 = gov.evaluate(engine.latest)
        cmd5 = Command(
            action=r5, params={"desc": "return"},
            governance_result=gov.last_veto_result,
            selected_by=(gov.last_selected.selected_by if gov.last_selected else "vetoed"),
        )

        commands = [cmd1, cmd2, cmd3, cmd4, cmd5]
        actions = [c.action for c in commands]
        assert actions == ["process", "pause", "process", "withdraw", "process"]
        assert commands[2].selected_by == "wake_word_override"
        assert commands[3].selected_by == "operator_absent"


class TestSteadyStateUnderStress:
    """System reaches steady state despite combined pressures."""

    def test_perturbation_storm_converges_to_steady_state(self):
        """T1-T6: Rapid perturbations → system eventually stabilizes."""
        engine = _make_engine(face_detected=True, face_count=1)
        gov = PipelineGovernor()

        perturbations = [
            "idle", "meeting", "idle", "production", "idle", "idle", "idle",
        ]
        results = []
        for mode in perturbations:
            engine.update_slow_fields(activity_mode=mode)
            engine.tick()
            results.append(gov.evaluate(engine.latest))

        # Last 3 should be steady state
        assert results[-1] == results[-2] == results[-3] == "process"
        # Storm caused some pauses
        assert "pause" in results

    def test_convergent_paths_agree_under_steady_state(self):
        """T1-T6: After perturbation clears, dual paths converge to agreement."""
        engine = _make_engine(face_detected=True, face_count=1)

        # Perturbation
        engine.update_slow_fields(activity_mode="meeting")
        engine.tick()
        gov = PipelineGovernor()
        r1 = gov.evaluate(engine.latest)
        assert r1 == "pause"

        # Clear → steady state
        engine.update_slow_fields(activity_mode="idle")
        engine.tick()
        r2 = gov.evaluate(engine.latest)

        # Path B: combinator
        trigger: Event[str] = Event()
        fused = with_latest_from(trigger, engine.behaviors)
        ctx: list[FusedContext] = []
        fused.subscribe(lambda ts, c: ctx.append(c))
        trigger.emit(time.monotonic(), "ss")

        chain: VetoChain[FusedContext] = VetoChain([
            Veto(
                name="mode",
                predicate=lambda c: c.samples["activity_mode"].value
                not in ("production", "meeting"),
            ),
        ])
        veto = chain.evaluate(ctx[0])

        # Convergence at steady state
        assert r2 == "process"
        assert veto.allowed

    def test_reconfigured_system_reaches_same_steady_state(self):
        """T1-T6: Different configs converge to same steady state on same input."""
        engine = _make_engine(face_detected=True, face_count=1)
        engine.tick()

        configs = [
            PipelineGovernor(),
            PipelineGovernor(conversation_debounce_s=0.0),
            PipelineGovernor(operator_absent_withdraw_s=0.0),
            PipelineGovernor(conversation_debounce_s=0.0, operator_absent_withdraw_s=0.0),
        ]

        results = []
        for gov in configs:
            results.append(gov.evaluate(engine.latest))

        # All reach same steady state on idle+present input
        assert all(r == "process" for r in results)

    def test_wake_word_does_not_create_persistent_state_leak(self):
        """T1-T6: Wake word override doesn't leak into subsequent steady state."""
        engine = _make_engine(face_detected=True, face_count=1)
        gov = PipelineGovernor()

        # Drive to pause
        engine.update_slow_fields(activity_mode="production")
        engine.tick()
        r1 = gov.evaluate(engine.latest)
        assert r1 == "pause"

        # Wake word override
        gov.wake_word_active = True
        engine.tick()
        r2 = gov.evaluate(engine.latest)
        assert r2 == "process"

        # Exhaust 3-tick grace period
        for _ in range(3):
            engine.tick()
            gov.evaluate(engine.latest)

        # Next cycle: grace exhausted, no leak — production still blocks
        engine.tick()
        r3 = gov.evaluate(engine.latest)
        assert r3 == "pause"

        # Clear production → steady state
        engine.update_slow_fields(activity_mode="idle")
        engine.tick()
        r4 = gov.evaluate(engine.latest)
        assert r4 == "process"

        # Verify no residual wake word state
        assert gov.wake_word_active is False
        assert gov._paused_by_conversation is False


class TestHolisticProvenance:
    """Every output traceable through all system layers."""

    def test_end_to_end_provenance_under_all_pressures(self):
        """T1-T6: Full pipeline, every field traceable from origin."""
        engine = _make_engine(face_detected=True, face_count=1)
        gov = PipelineGovernor()

        engine.tick()
        action = gov.evaluate(engine.latest)

        trigger: Event[str] = Event()
        fused = with_latest_from(trigger, engine.behaviors)
        ctx: list[FusedContext] = []
        fused.subscribe(lambda ts, c: ctx.append(c))
        trigger.emit(time.monotonic(), "final")

        guard = FreshnessGuard([
            FreshnessRequirement(behavior_name="operator_present", max_staleness_s=30.0),
        ])
        freshness = guard.check(ctx[0], time.monotonic())

        cmd = Command(
            action=action,
            params={
                "op_present": engine.latest.operator_present,
                "fresh": freshness.fresh_enough,
                "ctx_trigger": ctx[0].trigger_value,
            },
            trigger_time=ctx[0].trigger_time,
            trigger_source="holistic_test",
            min_watermark=ctx[0].min_watermark,
            governance_result=gov.last_veto_result,
            selected_by=gov.last_selected.selected_by,
        )
        sched = Schedule(command=cmd, target_time=engine.latest.timestamp)

        # Every field traceable
        assert sched.command.action == "process"
        assert sched.command.trigger_source == "holistic_test"
        assert sched.command.params["op_present"] is True
        assert sched.command.params["fresh"] is True
        assert sched.command.params["ctx_trigger"] == "final"
        assert sched.command.governance_result.allowed
        assert sched.command.selected_by == "default"
        assert sched.command.min_watermark > 0
        assert isinstance(sched.command.params, MappingProxyType)

    def test_degraded_provenance_under_all_pressures(self):
        """T1-T6: Full pipeline in degraded state, every denial traceable."""
        engine = _make_engine(face_detected=True, face_count=1)
        engine.update_slow_fields(activity_mode="meeting")
        gov = PipelineGovernor()

        engine.tick()
        action = gov.evaluate(engine.latest)

        # Combinator path with missing behavior
        trigger: Event[str] = Event()
        fused = with_latest_from(trigger, engine.behaviors)
        ctx: list[FusedContext] = []
        fused.subscribe(lambda ts, c: ctx.append(c))
        trigger.emit(time.monotonic(), "degraded")

        guard = FreshnessGuard([
            FreshnessRequirement(behavior_name="phantom", max_staleness_s=5.0),
        ])
        freshness = guard.check(ctx[0], time.monotonic())

        cmd = Command(
            action=action,
            params={
                "gov_denied": list(gov.last_veto_result.denied_by),
                "fresh_violations": list(freshness.violations),
            },
            governance_result=gov.last_veto_result,
        )
        sched = Schedule(command=cmd)

        assert sched.command.action == "pause"
        assert "activity_mode" in sched.command.governance_result.denied_by
        assert any("not present" in v for v in sched.command.params["fresh_violations"])

    def test_recovered_provenance_under_all_pressures(self):
        """T1-T6: System degrades then recovers, provenance reflects recovery."""
        engine = _make_engine(face_detected=True, face_count=1)
        gov = PipelineGovernor()

        # Degrade
        engine.update_slow_fields(activity_mode="production")
        engine.tick()
        r1 = gov.evaluate(engine.latest)
        veto1 = gov.last_veto_result

        # Recover
        engine.update_slow_fields(activity_mode="idle")
        engine.tick()
        r2 = gov.evaluate(engine.latest)
        veto2 = gov.last_veto_result

        cmd1 = Command(action=r1, governance_result=veto1, params={"phase": "degraded"})
        cmd2 = Command(action=r2, governance_result=veto2, params={"phase": "recovered"})

        assert cmd1.action == "pause"
        assert not cmd1.governance_result.allowed
        assert cmd2.action == "process"
        assert cmd2.governance_result.allowed
        assert isinstance(cmd1.params, MappingProxyType)
        assert isinstance(cmd2.params, MappingProxyType)

    def test_steady_state_provenance_is_deterministic(self):
        """T1-T6: Same inputs → identical provenance every time."""
        engine = _make_engine(face_detected=True, face_count=1)

        results = []
        for _ in range(3):
            gov = PipelineGovernor()
            engine.tick()
            action = gov.evaluate(engine.latest)
            results.append({
                "action": action,
                "allowed": gov.last_veto_result.allowed,
                "selected_by": gov.last_selected.selected_by if gov.last_selected else None,
                "denied_by": gov.last_veto_result.denied_by,
            })

        # All three identical
        assert results[0] == results[1] == results[2]
        assert results[0]["action"] == "process"
        assert results[0]["allowed"] is True
        assert results[0]["selected_by"] == "default"
