"""Cross-cutting integration tests for the perception type system (matrix 7).

Convergent pipelines: two independent signal paths merge at a decision
point. Each test verifies properties of the merged output where
independent causal chains converge.
"""

from __future__ import annotations

import time
from types import MappingProxyType
from unittest.mock import MagicMock

from agents.hapax_voice.combinator import with_latest_from
from agents.hapax_voice.commands import Command, Schedule
from agents.hapax_voice.governance import (
    Candidate,
    FallbackChain,
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


# ── Class 1: Dual Context Convergence ────────────────────────────────────────


class TestDualContextConvergence:
    """Two FusedContexts merge at Command construction."""

    def test_two_fused_contexts_merge_at_command_via_worst_watermark(self):
        """S1, S2, S3, S6 + A1, A2, A5: Command takes worst watermark from two contexts."""
        now = time.monotonic()

        # Path A: fresh context
        ctx_a = FusedContext(
            trigger_time=now,
            trigger_value="a",
            samples={"sensor_a": Stamped(value=1, watermark=now)},
            min_watermark=now,
        )
        # Path B: stale context
        ctx_b = FusedContext(
            trigger_time=now,
            trigger_value="b",
            samples={"sensor_b": Stamped(value=2, watermark=now - 50.0)},
            min_watermark=now - 50.0,
        )

        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="missing", max_staleness_s=5.0),
            ]
        )
        violations_a = guard.check(ctx_a, now).violations
        violations_b = guard.check(ctx_b, now).violations

        cmd = Command(
            action="process",
            params={"merged_violations": list(violations_a + violations_b)},
            min_watermark=min(ctx_a.min_watermark, ctx_b.min_watermark),
        )

        assert cmd.min_watermark == ctx_b.min_watermark
        assert isinstance(cmd.params, MappingProxyType)
        assert any("not present" in v for v in cmd.params["merged_violations"])
        assert isinstance(ctx_a.samples, MappingProxyType)
        assert isinstance(ctx_b.samples, MappingProxyType)

    def test_two_fused_contexts_one_fresh_one_stale_at_command(self):
        """S1, S2, S3, S4, S6 + A1, A2, A5: Fresh+stale converge at VetoChain → Command."""
        now = time.monotonic()

        ctx_fresh = FusedContext(
            trigger_time=now,
            trigger_value="fresh",
            samples={"val": Stamped(value="ok", watermark=now)},
            min_watermark=now,
        )
        ctx_stale = FusedContext(
            trigger_time=now,
            trigger_value="stale",
            samples={"val": Stamped(value="old", watermark=now - 100.0)},
            min_watermark=now - 100.0,
        )

        guard_fresh = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="val", max_staleness_s=5.0),
            ]
        )
        guard_stale = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="val", max_staleness_s=5.0),
            ]
        )

        chain: VetoChain[object] = VetoChain(
            [
                Veto(
                    name="path_a",
                    predicate=lambda _: guard_fresh.check(ctx_fresh, now).fresh_enough,
                ),
                Veto(
                    name="path_b",
                    predicate=lambda _: guard_stale.check(ctx_stale, now).fresh_enough,
                ),
            ]
        )
        veto = chain.evaluate(None)

        assert veto.allowed is False
        assert "path_b" in veto.denied_by
        assert "path_a" not in veto.denied_by

        cmd = Command(action="pause", params={"reason": "stale_path"}, governance_result=veto)
        assert isinstance(cmd.params, MappingProxyType)
        assert isinstance(ctx_fresh.samples, MappingProxyType)

    def test_perception_engine_and_manual_context_converge_at_governor(self):
        """S7, S2, S4, S5 + A1, A3, A4: Engine context and manual context converge at governor."""
        engine = _make_engine(face_detected=True, face_count=1)
        engine.tick()

        # Path A: engine behaviors via combinator
        trigger: Event[str] = Event()
        fused = with_latest_from(trigger, engine.behaviors)
        received: list[FusedContext] = []
        fused.subscribe(lambda ts, ctx: received.append(ctx))
        now = time.monotonic()
        trigger.emit(now, "snap")
        ctx_engine = received[0]

        # Path B: manual context with missing behavior
        ctx_manual = FusedContext(
            trigger_time=now,
            trigger_value="manual",
            samples={"custom_signal": Stamped(value=42, watermark=now)},
            min_watermark=now,
        )

        guard_engine = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="operator_present", max_staleness_s=10.0),
            ]
        )
        guard_manual = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="missing_field", max_staleness_s=5.0),
            ]
        )

        gov = PipelineGovernor()
        gov.veto_chain.add(
            Veto(
                name="engine_fresh",
                predicate=lambda _s: guard_engine.check(ctx_engine, now).fresh_enough,
            )
        )
        gov.veto_chain.add(
            Veto(
                name="manual_fresh",
                predicate=lambda _s: guard_manual.check(ctx_manual, now).fresh_enough,
            )
        )

        state = _make_state(activity_mode="idle")
        r = gov.evaluate(state)

        # manual_fresh denies (missing field), engine_fresh allows
        assert r == "pause"
        assert "manual_fresh" in gov.last_veto_result.denied_by
        assert "engine_fresh" not in gov.last_veto_result.denied_by
        assert "operator_present" in ctx_engine.samples
        assert isinstance(ctx_engine.samples, MappingProxyType)

    def test_two_fallback_chains_inform_single_command(self):
        """S3, S4, S5, S6 + A1, A2, A5: Two FallbackChains converge at Command."""
        now = time.monotonic()
        ctx = FusedContext(
            trigger_time=now,
            trigger_value="tick",
            samples={"vad": Stamped(value=0.9, watermark=now)},
            min_watermark=now,
        )

        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="vad", max_staleness_s=10.0),
            ]
        )

        # Chain 1: action selection based on freshness
        action_chain: FallbackChain[FusedContext, str] = FallbackChain(
            candidates=[
                Candidate(
                    name="active",
                    predicate=lambda c: guard.check(c, now).fresh_enough,
                    action="process",
                ),
            ],
            default="pause",
        )

        # Chain 2: mode selection
        mode_chain: FallbackChain[FusedContext, str] = FallbackChain(
            candidates=[
                Candidate(
                    name="high_vad",
                    predicate=lambda c: c.get_sample("vad").value > 0.5,
                    action="interactive",
                ),
            ],
            default="passive",
        )

        action_sel = action_chain.select(ctx)
        mode_sel = mode_chain.select(ctx)

        # Also check missing behavior
        guard_m = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="nope", max_staleness_s=1.0),
            ]
        )

        cmd = Command(
            action=action_sel.action,
            params={"mode": mode_sel.action, "mode_by": mode_sel.selected_by},
        )

        assert cmd.action == "process"
        assert cmd.params["mode"] == "interactive"
        assert cmd.params["mode_by"] == "high_vad"
        assert isinstance(cmd.params, MappingProxyType)
        assert isinstance(ctx.samples, MappingProxyType)
        assert "not present" in guard_m.check(ctx, now).violations[0]


# ── Class 2: Veto Convergence ────────────────────────────────────────────────


class TestVetoConvergence:
    """Multiple VetoChains or FreshnessGuards converge at one decision."""

    def test_two_veto_chains_merged_denials_in_command(self):
        """S3, S4, S5, S6 + A1, A2, A3: Denials from two sources merge in Command."""
        now = time.monotonic()
        ctx = FusedContext(
            trigger_time=now,
            trigger_value="tick",
            samples={"val": Stamped(value=1, watermark=now - 100.0)},
            min_watermark=now - 100.0,
        )

        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="val", max_staleness_s=5.0),
            ]
        )

        gov = PipelineGovernor()
        # Source A: freshness denial
        gov.veto_chain.add(
            Veto(
                name="freshness_deny",
                predicate=lambda _s: guard.check(ctx, now).fresh_enough,
            )
        )

        state = _make_state(activity_mode="production")
        r = gov.evaluate(state)
        assert r == "pause"
        assert "activity_mode" in gov.last_veto_result.denied_by
        assert "freshness_deny" in gov.last_veto_result.denied_by

        cmd = Command(
            action="pause",
            params={"sources": 2},
            governance_result=gov.last_veto_result,
        )
        assert len(cmd.governance_result.denied_by) >= 2
        assert isinstance(cmd.params, MappingProxyType)
        assert isinstance(ctx.samples, MappingProxyType)

    def test_freshness_guard_convergence_stale_plus_missing(self):
        """S2, S3, S4, S6 + A1, A2, A5: Stale and missing converge at VetoChain → Command."""
        now = time.monotonic()
        trigger: Event[str] = Event()
        behaviors = {"vad_confidence": Behavior(0.8, watermark=now - 100.0)}
        fused = with_latest_from(trigger, behaviors)
        received: list[FusedContext] = []
        fused.subscribe(lambda ts, ctx: received.append(ctx))

        trigger.emit(now, "snap")
        ctx = received[0]

        guard_stale = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="vad_confidence", max_staleness_s=5.0),
            ]
        )
        guard_missing = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="gaze_model", max_staleness_s=5.0),
            ]
        )

        chain: VetoChain[FusedContext] = VetoChain(
            [
                Veto(name="stale_vad", predicate=lambda c: guard_stale.check(c, now).fresh_enough),
                Veto(
                    name="missing_gaze",
                    predicate=lambda c: guard_missing.check(c, now).fresh_enough,
                ),
            ]
        )
        veto = chain.evaluate(ctx)

        assert not veto.allowed
        assert "stale_vad" in veto.denied_by
        assert "missing_gaze" in veto.denied_by
        assert "not present" in guard_missing.check(ctx, now).violations[0]

        cmd = Command(
            action="pause", params={"denials": list(veto.denied_by)}, governance_result=veto
        )
        assert isinstance(cmd.params, MappingProxyType)
        assert isinstance(ctx.samples, MappingProxyType)

    def test_governor_builtin_and_custom_veto_convergence(self):
        """S4, S5, S6, S3 + A2, A3, A5: Built-in + custom freshness veto converge."""
        now = time.monotonic()
        ctx = FusedContext(
            trigger_time=now,
            trigger_value="x",
            samples={},
            min_watermark=now,
        )
        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="missing", max_staleness_s=1.0),
            ]
        )

        gov = PipelineGovernor()
        gov.veto_chain.add(
            Veto(
                name="custom_freshness",
                predicate=lambda _s: guard.check(ctx, now).fresh_enough,
            )
        )

        state = _make_state(activity_mode="production")
        r = gov.evaluate(state)
        assert r == "pause"
        assert "activity_mode" in gov.last_veto_result.denied_by
        assert "custom_freshness" in gov.last_veto_result.denied_by

        cmd = Command(
            action="pause",
            params={"converged": True},
            governance_result=gov.last_veto_result,
        )
        assert cmd.governance_result.allowed is False
        assert isinstance(cmd.params, MappingProxyType)
        assert "not present" in guard.check(ctx, now).violations[0]

    def test_engine_fast_and_slow_behaviors_converge_in_fused_context(self):
        """S7, S1, S2, S3 + A1, A4, A5: Fast and slow behaviors converge in one FusedContext."""
        engine = _make_engine(face_detected=True, face_count=1, vad=0.7)
        engine.tick()
        engine.update_slow_fields(activity_mode="meeting")

        trigger: Event[str] = Event()
        fused = with_latest_from(trigger, engine.behaviors)
        received: list[FusedContext] = []
        fused.subscribe(lambda ts, ctx: received.append(ctx))

        now = time.monotonic()
        trigger.emit(now, "snap")
        ctx = received[0]

        # Fast behavior
        assert ctx.get_sample("operator_present").value is True
        # Slow behavior
        assert ctx.get_sample("activity_mode").value == "meeting"

        assert isinstance(ctx.samples, MappingProxyType)
        assert "operator_present" in ctx.samples

        # Missing behavior
        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="nonexistent", max_staleness_s=1.0),
            ]
        )
        assert "not present" in guard.check(ctx, now).violations[0]


# ── Class 3: Merged Pipeline Outputs ────────────────────────────────────────


class TestMergedPipelineOutputs:
    """Two pipeline runs merge at Schedule or Command."""

    def test_two_governor_evaluations_merge_into_schedule_sequence(self):
        """S5, S6, S7 + A2, A3, A4: Two evaluations → two Schedules in sequence."""
        engine = _make_engine(face_detected=True, face_count=1)
        engine.tick()

        gov = PipelineGovernor()

        # Eval 1: idle → process
        state1 = _make_state(activity_mode="idle")
        r1 = gov.evaluate(state1)
        cmd1 = Command(
            action=r1,
            params={"eval": 1},
            governance_result=gov.last_veto_result,
            selected_by=gov.last_selected.selected_by,
        )
        sched1 = Schedule(command=cmd1, target_time=1.0)

        # Eval 2: production → pause
        state2 = _make_state(activity_mode="production")
        r2 = gov.evaluate(state2)
        cmd2 = Command(action=r2, params={"eval": 2}, governance_result=gov.last_veto_result)
        sched2 = Schedule(command=cmd2, target_time=2.0)

        assert sched1.command.action == "process"
        assert sched2.command.action == "pause"
        assert sched1.target_time < sched2.target_time
        assert isinstance(sched1.command.params, MappingProxyType)
        assert isinstance(sched2.command.params, MappingProxyType)
        assert state1.operator_present is True

    def test_combinator_and_governor_paths_converge_at_command(self):
        """S2, S3, S5, S6 + A1, A2, A5: Combinator freshness + governor veto → one Command."""
        now = time.monotonic()

        # Path A: combinator + freshness
        trigger: Event[str] = Event()
        behaviors = {"mode": Behavior("idle", watermark=now)}
        fused = with_latest_from(trigger, behaviors)
        received: list[FusedContext] = []
        fused.subscribe(lambda ts, ctx: received.append(ctx))
        trigger.emit(now, "snap")
        ctx = received[0]

        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="missing_sensor", max_staleness_s=1.0),
            ]
        )
        freshness = guard.check(ctx, now)

        # Path B: governor
        gov = PipelineGovernor()
        state = _make_state(activity_mode="production")
        r = gov.evaluate(state)

        # Converge at Command
        cmd = Command(
            action=r,
            params={"freshness_violations": list(freshness.violations)},
            governance_result=gov.last_veto_result,
        )

        assert cmd.action == "pause"
        assert any("not present" in v for v in cmd.params["freshness_violations"])
        assert isinstance(cmd.params, MappingProxyType)
        assert isinstance(ctx.samples, MappingProxyType)

    def test_wake_word_path_and_freshness_path_converge_at_schedule(self):
        """S5, S6, S3, S4 + A2, A3, A5: Wake word override + freshness warnings → Schedule."""
        now = time.monotonic()

        # Path A: wake word override
        gov = PipelineGovernor()
        gov.wake_word_active = True
        state = _make_state(activity_mode="production")
        r = gov.evaluate(state)
        assert r == "process"
        assert gov.last_selected.selected_by == "wake_word_override"

        # Path B: freshness check with missing behavior
        ctx = FusedContext(trigger_time=now, trigger_value="x", samples={}, min_watermark=now)
        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="missing", max_staleness_s=1.0),
            ]
        )
        freshness = guard.check(ctx, now)

        # Converge at Schedule
        cmd = Command(
            action=r,
            params={"freshness_warnings": list(freshness.violations)},
            governance_result=gov.last_veto_result,
            selected_by=gov.last_selected.selected_by,
        )
        sched = Schedule(command=cmd, domain="beat")

        assert sched.command.action == "process"
        assert sched.command.selected_by == "wake_word_override"
        assert any("not present" in v for v in sched.command.params["freshness_warnings"])
        assert isinstance(sched.command.params, MappingProxyType)

    def test_multiple_perception_engines_behaviors_converge_in_command(self):
        """S7, S1, S2, S6 + A1, A2, A4: Two engines' behaviors converge at Command."""
        engine_a = _make_engine(face_detected=True, face_count=1)
        engine_b = _make_engine(face_detected=False, face_count=0, vad=0.9)
        engine_a.tick()
        engine_b.tick()

        trigger: Event[str] = Event()
        fused_a = with_latest_from(trigger, engine_a.behaviors)
        fused_b = with_latest_from(trigger, engine_b.behaviors)

        recv_a: list[FusedContext] = []
        recv_b: list[FusedContext] = []
        fused_a.subscribe(lambda ts, ctx: recv_a.append(ctx))
        fused_b.subscribe(lambda ts, ctx: recv_b.append(ctx))

        trigger.emit(time.monotonic(), "snap")
        ctx_a = recv_a[0]
        ctx_b = recv_b[0]

        cmd = Command(
            action="process",
            params={"engine_count": 2},
            min_watermark=min(ctx_a.min_watermark, ctx_b.min_watermark),
        )

        assert cmd.min_watermark == min(ctx_a.min_watermark, ctx_b.min_watermark)
        assert "operator_present" in ctx_a.samples
        assert "operator_present" in ctx_b.samples
        assert ctx_a.get_sample("operator_present").value is True
        assert ctx_b.get_sample("operator_present").value is False
        assert isinstance(cmd.params, MappingProxyType)
        assert isinstance(ctx_a.samples, MappingProxyType)
