"""Cross-cutting integration tests for the perception type system (matrix 14).

Degradation & recovery (Q4): composes perturbation cascades (T2), convergent
pipelines (T3), and reconfiguration invariants (T4). Each test exercises a
system where one convergent path fails, the system degrades gracefully, the
path recovers, and the system restores correct behavior.
"""

from __future__ import annotations

import time
from types import MappingProxyType
from unittest.mock import MagicMock

from agents.hapax_daimonion.combinator import with_latest_from
from agents.hapax_daimonion.commands import Command, Schedule
from agents.hapax_daimonion.governance import (
    FallbackChain,
    FreshnessGuard,
    FreshnessRequirement,
    FusedContext,
    Veto,
    VetoChain,
    VetoResult,
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


# ── Q4: Degradation & Recovery ───────────────────────────────────────────────


class TestSinglePathDegradation:
    """One convergent path fails, system degrades gracefully."""

    def test_freshness_path_fails_veto_path_still_governs(self):
        """T2+T3+T4: Freshness path has missing behavior, veto path still evaluates."""
        now = time.monotonic()
        ctx = FusedContext(
            trigger_time=now,
            trigger_value="eval",
            samples={
                "activity_mode": Stamped(value="idle", watermark=now),
            },
            min_watermark=now,
        )

        # Path A: freshness — missing sensor behavior
        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="sensor", max_staleness_s=5.0),
            ]
        )
        freshness = guard.check(ctx, now)
        assert not freshness.fresh_enough
        assert any("not present" in v for v in freshness.violations)

        # Path B: veto — activity_mode check succeeds
        chain: VetoChain[FusedContext] = VetoChain(
            [
                Veto(
                    name="mode", predicate=lambda c: c.samples["activity_mode"].value != "meeting"
                ),
            ]
        )
        veto = chain.evaluate(ctx)
        assert veto.allowed

        # Degradation: merge — freshness failure + veto success → cautious pause
        cmd = Command(
            action="pause" if not freshness.fresh_enough else "process",
            params={"freshness_ok": freshness.fresh_enough, "veto_ok": veto.allowed},
            governance_result=veto,
        )
        assert cmd.action == "pause"
        assert cmd.params["veto_ok"] is True

    def test_stale_behavior_degrades_convergent_combinator(self):
        """T2+T3+T4: One behavior stale in convergent combinator, min_watermark drops."""
        now = time.monotonic()
        b_fresh = Behavior("ok", watermark=now)
        b_stale = Behavior("old", watermark=now - 100.0)

        trigger: Event[str] = Event()
        fused = with_latest_from(trigger, {"fresh": b_fresh, "stale": b_stale})
        received: list[FusedContext] = []
        fused.subscribe(lambda ts, ctx: received.append(ctx))
        trigger.emit(now, "check")

        ctx = received[0]
        assert ctx.min_watermark == now - 100.0

        # Degradation: freshness guard catches the stale path
        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="stale", max_staleness_s=5.0),
            ]
        )
        result = guard.check(ctx, now)
        assert not result.fresh_enough
        assert isinstance(ctx.samples, MappingProxyType)

    def test_governor_veto_degrades_while_fallback_would_process(self):
        """T2+T3+T4: Veto chain denies, fallback chain would have selected process."""
        state = _make_state(activity_mode="meeting")

        # Path A: VetoChain denies
        chain: VetoChain[EnvironmentState] = VetoChain(
            [
                Veto(
                    name="mode",
                    predicate=lambda s: s.activity_mode not in ("production", "meeting"),
                ),
            ]
        )
        veto = chain.evaluate(state)
        assert not veto.allowed

        # Path B: FallbackChain would select process
        fallback: FallbackChain[EnvironmentState, str] = FallbackChain(
            candidates=[],
            default="process",
        )
        selected = fallback.select(state)
        assert selected.action == "process"

        # Degradation: veto takes precedence over fallback
        cmd = Command(
            action="pause" if not veto.allowed else selected.action,
            governance_result=veto,
            selected_by=selected.selected_by if veto.allowed else "veto_override",
        )
        assert cmd.action == "pause"
        assert cmd.selected_by == "veto_override"

    def test_dual_veto_chains_partial_degradation(self):
        """T2+T3+T4: Two veto chains, one fails, combined result reflects partial failure."""
        now = time.monotonic()
        ctx = FusedContext(
            trigger_time=now,
            trigger_value="x",
            samples={
                "mode": Stamped(value="idle", watermark=now),
                "sensor": Stamped(value="ok", watermark=now - 50.0),
            },
            min_watermark=now - 50.0,
        )

        # Chain A: passes
        chain_a: VetoChain[FusedContext] = VetoChain(
            [
                Veto(name="mode_ok", predicate=lambda c: c.samples["mode"].value != "meeting"),
            ]
        )
        veto_a = chain_a.evaluate(ctx)
        assert veto_a.allowed

        # Chain B: fails (staleness)
        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="sensor", max_staleness_s=5.0),
            ]
        )
        chain_b: VetoChain[FusedContext] = VetoChain(
            [
                Veto(
                    name="freshness",
                    predicate=lambda c: guard.check(c, time.monotonic()).fresh_enough,
                ),
            ]
        )
        veto_b = chain_b.evaluate(ctx)
        assert not veto_b.allowed

        # Partial degradation: combine
        combined = VetoResult(
            allowed=veto_a.allowed and veto_b.allowed,
            denied_by=veto_a.denied_by + veto_b.denied_by,
        )
        assert not combined.allowed
        assert combined.denied_by == ("freshness",)


class TestRecoveryFromDegradation:
    """Degraded path recovers, system restores correct behavior."""

    def test_stale_behavior_recovers_freshness_restores(self):
        """T2+T3+T4: Behavior stale → guard denies → behavior updates → guard allows."""
        now = time.monotonic()
        b = Behavior("data", watermark=now - 100.0)

        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="sig", max_staleness_s=5.0),
            ]
        )

        # Degraded: stale
        trigger: Event[str] = Event()
        fused = with_latest_from(trigger, {"sig": b})
        ctx_stale: list[FusedContext] = []
        fused.subscribe(lambda ts, ctx: ctx_stale.append(ctx))
        trigger.emit(now, "stale")
        assert not guard.check(ctx_stale[0], now).fresh_enough

        # Recovery: update behavior
        b.update("fresh_data", time.monotonic())
        fused2 = with_latest_from(trigger, {"sig": b})
        ctx_fresh: list[FusedContext] = []
        fused2.subscribe(lambda ts, ctx: ctx_fresh.append(ctx))
        trigger.emit(time.monotonic(), "fresh")
        assert guard.check(ctx_fresh[0], time.monotonic()).fresh_enough

    def test_missing_behavior_added_recovers_freshness(self):
        """T2+T3+T4: Missing behavior → guard fails → behavior added → guard passes."""
        now = time.monotonic()
        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="sensor", max_staleness_s=5.0),
            ]
        )

        # Degraded: missing behavior
        ctx_missing = FusedContext(
            trigger_time=now,
            trigger_value="x",
            samples={},
            min_watermark=now,
        )
        r1 = guard.check(ctx_missing, now)
        assert not r1.fresh_enough
        assert any("not present" in v for v in r1.violations)

        # Recovery: behavior now present
        ctx_present = FusedContext(
            trigger_time=now,
            trigger_value="x",
            samples={"sensor": Stamped(value="ok", watermark=now)},
            min_watermark=now,
        )
        r2 = guard.check(ctx_present, now)
        assert r2.fresh_enough

    def test_meeting_mode_clears_governor_recovers(self):
        """T2+T3+T4: Meeting → pause → meeting ends → process restored."""
        engine = _make_engine(face_detected=True, face_count=1)
        gov = PipelineGovernor()

        # Degraded: meeting mode
        engine.update_slow_fields(activity_mode="meeting")
        engine.tick()
        r1 = gov.evaluate(engine.latest)
        assert r1 == "pause"

        # Recovery: meeting ends
        engine.update_slow_fields(activity_mode="idle")
        engine.tick()
        r2 = gov.evaluate(engine.latest)
        assert r2 == "process"

        # Verify governor state is clean
        assert gov.last_veto_result.allowed

    def test_convergent_paths_both_degrade_then_both_recover(self):
        """T2+T3+T4: Both convergent paths fail → both recover → system restored."""
        engine = _make_engine(face_detected=True, face_count=1)

        # Both degrade: meeting mode (veto) + operator absent (fallback)
        engine.update_slow_fields(activity_mode="meeting")
        engine.tick()

        gov = PipelineGovernor(operator_absent_withdraw_s=5.0)
        r1 = gov.evaluate(engine.latest)
        assert r1 == "pause"  # veto fires first

        # Make operator absent too
        engine._presence.face_detected = False
        engine._presence.face_count = 0
        gov._last_operator_seen = time.monotonic() - 10.0
        engine.tick()
        r2 = gov.evaluate(engine.latest)
        assert r2 == "pause"  # veto still fires (takes precedence over withdraw)

        # Recover path 1: meeting ends
        engine.update_slow_fields(activity_mode="idle")
        engine.tick()
        r3 = gov.evaluate(engine.latest)
        assert r3 == "withdraw"  # veto clear, but still absent

        # Recover path 2: operator returns
        engine._presence.face_detected = True
        engine._presence.face_count = 1
        engine.tick()
        r4 = gov.evaluate(engine.latest)
        assert r4 == "process"  # fully recovered


class TestGracefulDegradationInFullPipeline:
    """Full pipeline degradation and recovery scenarios."""

    def test_full_pipeline_degrade_at_freshness_recover_at_update(self):
        """T2+T3+T4: Engine → combinator → freshness fails → update → freshness passes."""
        engine = _make_engine(face_detected=True, face_count=1)
        engine.update_slow_fields(activity_mode="idle")
        engine.tick()

        trigger: Event[str] = Event()
        fused = with_latest_from(trigger, engine.behaviors)
        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="operator_present", max_staleness_s=5.0),
            ]
        )

        received: list[FusedContext] = []
        fused.subscribe(lambda ts, ctx: received.append(ctx))

        # Phase 1: fresh → process
        trigger.emit(time.monotonic(), "tick1")
        f1 = guard.check(received[-1], time.monotonic())
        assert f1.fresh_enough

        # Degradation: don't tick engine, wait
        # Simulate by creating stale context directly
        stale_ctx = FusedContext(
            trigger_time=time.monotonic(),
            trigger_value="tick2",
            samples={"operator_present": Stamped(value=True, watermark=time.monotonic() - 100.0)},
            min_watermark=time.monotonic() - 100.0,
        )
        f2 = guard.check(stale_ctx, time.monotonic())
        assert not f2.fresh_enough

        # Recovery: tick engine again
        engine.tick()
        trigger.emit(time.monotonic(), "tick3")
        f3 = guard.check(received[-1], time.monotonic())
        assert f3.fresh_enough

    def test_schedule_sequence_shows_degradation_and_recovery(self):
        """T2+T3+T4: Schedule sequence: process → pause (degraded) → process (recovered)."""
        engine = _make_engine(face_detected=True, face_count=1)
        gov = PipelineGovernor()
        schedules: list[Schedule] = []

        # Normal
        engine.tick()
        r1 = gov.evaluate(engine.latest)
        schedules.append(
            Schedule(
                command=Command(action=r1, params={"phase": "normal"}),
            )
        )

        # Degraded: production mode
        engine.update_slow_fields(activity_mode="production")
        engine.tick()
        r2 = gov.evaluate(engine.latest)
        schedules.append(
            Schedule(
                command=Command(action=r2, params={"phase": "degraded"}),
            )
        )

        # Recovered
        engine.update_slow_fields(activity_mode="idle")
        engine.tick()
        r3 = gov.evaluate(engine.latest)
        schedules.append(
            Schedule(
                command=Command(action=r3, params={"phase": "recovered"}),
            )
        )

        assert schedules[0].command.action == "process"
        assert schedules[1].command.action == "pause"
        assert schedules[2].command.action == "process"
        for s in schedules:
            assert isinstance(s.command.params, MappingProxyType)

    def test_wake_word_as_recovery_mechanism(self):
        """T2+T3+T4: Degraded by veto → wake word recovers → stable after."""
        gov = PipelineGovernor()

        # Degraded: production mode
        s1 = _make_state(activity_mode="production")
        r1 = gov.evaluate(s1)
        assert r1 == "pause"

        # Recovery: wake word
        gov.wake_word_active = True
        s2 = _make_state(activity_mode="production")
        r2 = gov.evaluate(s2)
        assert r2 == "process"
        assert gov.last_selected.selected_by == "engagement_override"

        # Exhaust 8-tick grace period
        for _ in range(8):
            gov.evaluate(_make_state(activity_mode="production"))

        # Post-recovery: grace exhausted, production still active → degrades again
        s3 = _make_state(activity_mode="production")
        r3 = gov.evaluate(s3)
        assert r3 == "pause"

        # Full recovery: production clears
        s4 = _make_state(activity_mode="idle")
        r4 = gov.evaluate(s4)
        assert r4 == "process"

    def test_convergent_degradation_with_command_provenance(self):
        """T2+T3+T4: Two convergent paths degrade, Command carries provenance of both."""
        now = time.monotonic()

        # Path A: veto denies (meeting)
        state = _make_state(activity_mode="meeting")
        chain: VetoChain[EnvironmentState] = VetoChain(
            [
                Veto(
                    name="mode",
                    predicate=lambda s: s.activity_mode not in ("production", "meeting"),
                ),
            ]
        )
        veto = chain.evaluate(state)

        # Path B: freshness denies (stale context)
        ctx = FusedContext(
            trigger_time=now,
            trigger_value="x",
            samples={"sensor": Stamped(value="ok", watermark=now - 100.0)},
            min_watermark=now - 100.0,
        )
        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="sensor", max_staleness_s=5.0),
            ]
        )
        freshness = guard.check(ctx, now)

        # Both degraded → Command with full provenance
        all_denials = list(veto.denied_by) + [f"freshness:{v}" for v in freshness.violations]
        cmd = Command(
            action="pause",
            params={"denials": all_denials},
            governance_result=VetoResult(allowed=False, denied_by=tuple(all_denials)),
        )

        assert cmd.action == "pause"
        assert "mode" in cmd.governance_result.denied_by
        assert any("freshness:" in d for d in cmd.governance_result.denied_by)
        assert isinstance(cmd.params, MappingProxyType)
