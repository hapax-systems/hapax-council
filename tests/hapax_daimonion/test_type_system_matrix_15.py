"""Cross-cutting integration tests for the perception type system (matrix 15).

Accountable evolution (Q5): composes reconfiguration invariants (T4),
provenance tracing (T5), and feedback/re-entry (T6). Each test exercises a
pipeline that is reconfigured across cycles while provenance remains coherent
through each configuration — every decision remains traceable to its origin.
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


# ── Q5: Accountable Evolution ────────────────────────────────────────────────


class TestProvenanceThroughReconfiguration:
    """Provenance remains traceable as pipeline is reconfigured."""

    def test_veto_chain_reconfigured_provenance_tracks_new_denials(self):
        """T4+T5+T6: VetoChain reconfigured, denied_by tracks new veto names."""
        chain: VetoChain[FusedContext] = VetoChain()
        now = time.monotonic()
        ctx = FusedContext(
            trigger_time=now,
            trigger_value="x",
            samples={"mode": Stamped(value="meeting", watermark=now)},
            min_watermark=now,
        )

        # Config 1: no vetoes → allowed
        r1 = chain.evaluate(ctx)
        assert r1.allowed

        # Reconfig: add veto
        chain.add(Veto(name="mode_v1", predicate=lambda c: c.samples["mode"].value != "meeting"))

        # Config 2: denied by mode_v1
        r2 = chain.evaluate(ctx)
        assert not r2.allowed
        cmd2 = Command(action="pause", governance_result=r2)
        assert "mode_v1" in cmd2.governance_result.denied_by

        # Reconfig: add another veto
        chain.add(Veto(name="always_deny", predicate=lambda _: False))

        # Config 3: denied by both — provenance shows evolution
        r3 = chain.evaluate(ctx)
        cmd3 = Command(action="pause", governance_result=r3)
        assert "mode_v1" in cmd3.governance_result.denied_by
        assert "always_deny" in cmd3.governance_result.denied_by
        assert len(cmd3.governance_result.denied_by) == 2

    def test_governor_replacement_preserves_observability_contract(self):
        """T4+T5+T6: Governor replaced across cycles, observability fields still set."""
        engine = _make_engine(face_detected=True, face_count=1)

        governors = [
            PipelineGovernor(),
            PipelineGovernor(conversation_debounce_s=0.0),
            PipelineGovernor(operator_absent_withdraw_s=0.0),
        ]

        for gov in governors:
            engine.tick()
            gov.evaluate(engine.latest)
            # Observability contract: last_veto_result always set after evaluate
            assert gov.last_veto_result is not None
            assert isinstance(gov.last_veto_result.allowed, bool)
            # For allowed path, last_selected is set
            if gov.last_veto_result.allowed:
                assert gov.last_selected is not None
                assert gov.last_selected.selected_by != ""

    def test_freshness_guard_reconfigured_violations_trace_correctly(self):
        """T4+T5+T6: FreshnessGuard reconfigured, violation messages trace new config."""
        now = time.monotonic()
        ctx = FusedContext(
            trigger_time=now,
            trigger_value="x",
            samples={
                "sensor": Stamped(value="ok", watermark=now - 3.0),
            },
            min_watermark=now - 3.0,
        )

        # Config 1: lenient → passes
        guard1 = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="sensor", max_staleness_s=10.0),
            ]
        )
        r1 = guard1.check(ctx, now)
        assert r1.fresh_enough
        assert len(r1.violations) == 0

        # Reconfig: strict → fails
        guard2 = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="sensor", max_staleness_s=1.0),
            ]
        )
        r2 = guard2.check(ctx, now)
        assert not r2.fresh_enough
        assert "sensor:" in r2.violations[0]

        # Reconfig: require missing behavior
        guard3 = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="phantom", max_staleness_s=1.0),
            ]
        )
        r3 = guard3.check(ctx, now)
        assert "not present" in r3.violations[0]

    def test_combinator_rewired_watermark_provenance_shifts(self):
        """T4+T5+T6: Combinator rewired to different behaviors, watermarks shift."""
        now = time.monotonic()
        b_fast = Behavior("fast", watermark=now)
        b_slow = Behavior("slow", watermark=now - 50.0)
        trigger: Event[str] = Event()

        # Config 1: fast behavior → high watermark
        fused1 = with_latest_from(trigger, {"sig": b_fast})
        ctx1: list[FusedContext] = []
        fused1.subscribe(lambda ts, ctx: ctx1.append(ctx))
        trigger.emit(now, "c1")
        wm1 = ctx1[0].min_watermark

        # Reconfig: slow behavior → low watermark
        fused2 = with_latest_from(trigger, {"sig": b_slow})
        ctx2: list[FusedContext] = []
        fused2.subscribe(lambda ts, ctx: ctx2.append(ctx))
        trigger.emit(now, "c2")
        wm2 = ctx2[0].min_watermark

        assert wm1 > wm2
        assert wm2 == now - 50.0


class TestEvolutionAcrossCycles:
    """Pipeline evolves across cycles with full accountability."""

    def test_three_cycle_progressive_veto_evolution(self):
        """T4+T5+T6: Each cycle adds a veto, Commands trace the growing denial set."""
        chain: VetoChain[FusedContext] = VetoChain()
        now = time.monotonic()
        commands: list[Command] = []

        for i in range(3):
            ctx = FusedContext(
                trigger_time=now,
                trigger_value=f"cycle_{i}",
                samples={"x": Stamped(value="bad", watermark=now)},
                min_watermark=now,
            )
            result = chain.evaluate(ctx)
            commands.append(
                Command(
                    action="pause" if not result.allowed else "process",
                    params={"cycle": i},
                    governance_result=result,
                )
            )
            # Evolve: add veto after each cycle
            chain.add(Veto(name=f"veto_{i}", predicate=lambda _: False))

        assert commands[0].action == "process"  # no vetoes yet
        assert commands[1].action == "pause"  # veto_0
        assert commands[2].action == "pause"  # veto_0 + veto_1
        assert len(commands[1].governance_result.denied_by) == 1
        assert len(commands[2].governance_result.denied_by) == 2

    def test_governor_state_feedback_with_schedule_provenance(self):
        """T4+T5+T6: Governor state feeds back, Schedule carries provenance of each config."""
        engine = _make_engine(face_detected=True, face_count=1)
        gov = PipelineGovernor()
        schedules: list[Schedule] = []

        configs = [
            {"activity_mode": "idle"},
            {"activity_mode": "production"},
            {"activity_mode": "idle"},
        ]

        for i, cfg in enumerate(configs):
            engine.update_slow_fields(**cfg)
            engine.tick()
            action = gov.evaluate(engine.latest)
            cmd = Command(
                action=action,
                params={"config_idx": i, **cfg},
                min_watermark=engine.min_watermark,
                governance_result=gov.last_veto_result,
            )
            schedules.append(Schedule(command=cmd, target_time=engine.latest.timestamp))

        assert schedules[0].command.action == "process"
        assert schedules[1].command.action == "pause"
        assert schedules[2].command.action == "process"
        # Provenance: each schedule traces its config
        assert schedules[1].command.params["activity_mode"] == "production"
        assert not schedules[1].command.governance_result.allowed

    def test_combinator_behavior_evolution_across_cycles(self):
        """T4+T5+T6: Behavior updated across cycles, combinator snapshots evolve."""
        b = Behavior("v1", watermark=time.monotonic())
        trigger: Event[str] = Event()
        fused = with_latest_from(trigger, {"data": b})
        snapshots: list[FusedContext] = []
        fused.subscribe(lambda ts, ctx: snapshots.append(ctx))

        # Cycle 1
        trigger.emit(time.monotonic(), "c1")

        # Evolve
        b.update("v2", time.monotonic())
        trigger.emit(time.monotonic(), "c2")

        # Evolve again
        b.update("v3", time.monotonic())
        trigger.emit(time.monotonic(), "c3")

        values = [s.samples["data"].value for s in snapshots]
        assert values == ["v1", "v2", "v3"]
        # Watermarks advance monotonically
        watermarks = [s.samples["data"].watermark for s in snapshots]
        for i in range(1, len(watermarks)):
            assert watermarks[i] > watermarks[i - 1]

    def test_wake_word_evolution_with_observability_provenance(self):
        """T4+T5+T6: Wake word used across cycles, observability traces each use."""
        engine = _make_engine(face_detected=True, face_count=1)
        engine.update_slow_fields(activity_mode="production")
        gov = PipelineGovernor()

        # Cycle 0: production → pause
        engine.tick()
        r0 = gov.evaluate(engine.latest)
        result0 = (r0, gov.last_veto_result.allowed)

        # Cycle 1: wake word → process
        gov.wake_word_active = True
        engine.tick()
        r1 = gov.evaluate(engine.latest)
        result1 = (r1, gov.last_veto_result.allowed)

        # Exhaust 3-tick grace period
        for _ in range(3):
            engine.tick()
            gov.evaluate(engine.latest)

        # Cycle 2: grace exhausted, production → pause
        engine.tick()
        r2 = gov.evaluate(engine.latest)
        result2 = (r2, gov.last_veto_result.allowed)

        # Cycle 3: wake word again → process
        gov.wake_word_active = True
        engine.tick()
        r3 = gov.evaluate(engine.latest)
        result3 = (r3, gov.last_veto_result.allowed)

        assert result0 == ("pause", False)  # production → veto
        assert result1 == ("process", True)  # wake word override
        assert result2 == ("pause", False)  # production → veto again
        assert result3 == ("process", True)  # wake word override again


class TestAccountableEndToEnd:
    """End-to-end accountability: every output traceable through evolution."""

    def test_full_pipeline_evolution_perception_to_schedule(self):
        """T4+T5+T6: Full pipeline reconfigured across 3 cycles, schedules traceable."""
        engine = _make_engine(face_detected=True, face_count=1)
        schedules: list[Schedule] = []

        gov_configs = [
            PipelineGovernor(),
            PipelineGovernor(conversation_debounce_s=0.0),
            PipelineGovernor(operator_absent_withdraw_s=0.0),
        ]

        for i, gov in enumerate(gov_configs):
            engine.tick()
            action = gov.evaluate(engine.latest)
            cmd = Command(
                action=action,
                params={"gov_config": i},
                trigger_time=engine.latest.timestamp,
                min_watermark=engine.min_watermark,
                governance_result=gov.last_veto_result,
                selected_by=gov.last_selected.selected_by if gov.last_selected else "vetoed",
            )
            schedules.append(Schedule(command=cmd))

        # All process (idle mode, operator present)
        for s in schedules:
            assert s.command.action == "process"
            assert s.command.governance_result.allowed
        # Provenance: each traces its governor config
        assert schedules[0].command.params["gov_config"] == 0
        assert schedules[2].command.params["gov_config"] == 2

    def test_freshness_evolution_traced_through_commands(self):
        """T4+T5+T6: FreshnessGuard reconfigured, violation provenance in Commands."""
        now = time.monotonic()
        ctx = FusedContext(
            trigger_time=now,
            trigger_value="x",
            samples={"sensor": Stamped(value="ok", watermark=now - 3.0)},
            min_watermark=now - 3.0,
        )

        configs = [
            FreshnessGuard([FreshnessRequirement("sensor", 10.0)]),  # lenient
            FreshnessGuard([FreshnessRequirement("sensor", 1.0)]),  # strict
            FreshnessGuard([FreshnessRequirement("phantom", 1.0)]),  # missing
        ]

        commands: list[Command] = []
        for i, guard in enumerate(configs):
            result = guard.check(ctx, now)
            commands.append(
                Command(
                    action="process" if result.fresh_enough else "pause",
                    params={
                        "config": i,
                        "violations": list(result.violations),
                    },
                )
            )

        assert commands[0].action == "process"
        assert commands[1].action == "pause"
        assert commands[2].action == "pause"
        assert len(commands[0].params["violations"]) == 0
        assert "sensor:" in commands[1].params["violations"][0]
        assert "not present" in commands[2].params["violations"][0]

    def test_veto_chain_evolution_with_immutable_command_history(self):
        """T4+T5+T6: VetoChain evolves, all Command params remain immutable."""
        chain: VetoChain[FusedContext] = VetoChain()
        now = time.monotonic()
        commands: list[Command] = []

        for i in range(4):
            ctx = FusedContext(
                trigger_time=now,
                trigger_value=f"c{i}",
                samples={"x": Stamped(value=i, watermark=now)},
                min_watermark=now,
            )
            result = chain.evaluate(ctx)
            commands.append(
                Command(
                    action="process" if result.allowed else "pause",
                    params={"cycle": i, "denied_count": len(result.denied_by)},
                    governance_result=result,
                )
            )
            if i < 3:
                chain.add(Veto(name=f"v{i}", predicate=lambda _: False))

        # All commands immutable regardless of evolution
        for cmd in commands:
            assert isinstance(cmd.params, MappingProxyType)
        # Denial count traces evolution
        assert commands[0].params["denied_count"] == 0
        assert commands[1].params["denied_count"] == 1
        assert commands[3].params["denied_count"] == 3

    def test_engine_evolution_with_watermark_provenance_chain(self):
        """T4+T5+T6: Engine behaviors evolve, watermark provenance advances."""
        engine = _make_engine(face_detected=True, face_count=1)
        trigger: Event[str] = Event()
        fused = with_latest_from(trigger, engine.behaviors)
        snapshots: list[FusedContext] = []
        fused.subscribe(lambda ts, ctx: snapshots.append(ctx))

        watermarks: list[float] = []
        for i in range(3):
            engine.tick()
            trigger.emit(time.monotonic(), f"c{i}")
            watermarks.append(snapshots[-1].min_watermark)
            if i == 1:
                engine.update_slow_fields(activity_mode="coding")

        # Watermarks advance across engine evolution
        for i in range(1, len(watermarks)):
            assert watermarks[i] >= watermarks[i - 1]
        # Samples reflect evolution
        assert snapshots[2].samples["activity_mode"].value == "coding"
