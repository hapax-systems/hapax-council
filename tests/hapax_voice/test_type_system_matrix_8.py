"""Cross-cutting integration tests for the perception type system (matrix 8).

Pipeline invariants under reconfiguration: add/remove vetoes, change
freshness requirements, toggle wake word across multiple evaluations.
Invariants must hold across reconfiguration events.
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


# ── Class 1: Veto Reconfiguration Invariants ────────────────────────────────


class TestVetoReconfigurationInvariants:
    """Adding vetoes never relaxes; wake word always overrides; deny-wins always holds."""

    def test_adding_veto_never_relaxes_across_three_evaluations(self):
        """S4, S5, S6 + A1, A2, A3: Successive veto additions only restrict."""
        now = time.monotonic()
        gov = PipelineGovernor()
        state = _make_state(activity_mode="idle")

        # Eval 1: no custom vetoes → process
        r1 = gov.evaluate(state)
        assert r1 == "process"
        cmd1 = Command(action=r1, params={"step": 1}, governance_result=gov.last_veto_result)

        # Eval 2: add veto X → pause
        gov.veto_chain.add(Veto(name="veto_x", predicate=lambda _s: False))
        r2 = gov.evaluate(state)
        assert r2 == "pause"
        cmd2 = Command(action=r2, params={"step": 2}, governance_result=gov.last_veto_result)

        # Eval 3: add veto Y → still pause, more denials
        gov.veto_chain.add(Veto(name="veto_y", predicate=lambda _s: False))
        r3 = gov.evaluate(state)
        assert r3 == "pause"
        cmd3 = Command(action=r3, params={"step": 3}, governance_result=gov.last_veto_result)

        assert len(cmd3.governance_result.denied_by) >= len(cmd2.governance_result.denied_by)
        assert isinstance(cmd1.params, MappingProxyType)
        assert isinstance(cmd3.params, MappingProxyType)

        ctx = FusedContext(trigger_time=now, trigger_value="x", samples={"a": Stamped(1, now)})
        assert isinstance(ctx.samples, MappingProxyType)

    def test_wake_word_override_invariant_holds_despite_veto_additions(self):
        """S4, S5, S3 + A1, A3, A5: Wake word overrides regardless of veto count."""
        now = time.monotonic()
        ctx = FusedContext(trigger_time=now, trigger_value="x", samples={}, min_watermark=now)
        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="missing", max_staleness_s=1.0),
            ]
        )

        gov = PipelineGovernor()
        # Add 3 denying vetoes
        for i in range(3):
            gov.veto_chain.add(Veto(name=f"deny_{i}", predicate=lambda _s: False))
        gov.veto_chain.add(
            Veto(
                name="freshness",
                predicate=lambda _s: guard.check(ctx, now).fresh_enough,
            )
        )

        state = _make_state(activity_mode="idle")

        # First wake word override
        gov.wake_word_active = True
        r1 = gov.evaluate(state)
        assert r1 == "process"
        assert gov.last_selected.selected_by == "wake_word_override"

        # Add a 5th veto, wake word again
        gov.veto_chain.add(Veto(name="deny_4", predicate=lambda _s: False))
        gov.wake_word_active = True
        r2 = gov.evaluate(state)
        assert r2 == "process"
        assert gov.last_selected.selected_by == "wake_word_override"

        assert "not present" in guard.check(ctx, now).violations[0]
        assert isinstance(ctx.samples, MappingProxyType)

    def test_deny_wins_invariant_survives_reconfiguration(self):
        """S3, S4, S5, S6 + A2, A3, A5: Adding allow vetoes doesn't override denial."""
        now = time.monotonic()
        gov = PipelineGovernor()
        ctx = FusedContext(trigger_time=now, trigger_value="x", samples={}, min_watermark=now)
        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="missing", max_staleness_s=1.0),
            ]
        )

        # One denier
        gov.veto_chain.add(
            Veto(
                name="freshness_deny",
                predicate=lambda _s: guard.check(ctx, now).fresh_enough,
            )
        )

        state = _make_state(activity_mode="idle")
        r1 = gov.evaluate(state)
        assert r1 == "pause"

        # Add two more allows — still denied
        gov.veto_chain.add(Veto(name="allow_1", predicate=lambda _s: True))
        gov.veto_chain.add(Veto(name="allow_2", predicate=lambda _s: True))
        r2 = gov.evaluate(state)
        assert r2 == "pause"
        assert "freshness_deny" in gov.last_veto_result.denied_by

        cmd = Command(action=r2, params={"allows_added": 2}, governance_result=gov.last_veto_result)
        assert isinstance(cmd.params, MappingProxyType)
        assert "not present" in guard.check(ctx, now).violations[0]

    def test_exhaustive_evaluation_invariant_after_reconfiguration(self):
        """S4, S5, S6, S7 + A2, A3, A4: All vetoes evaluated after reconfig."""
        engine = _make_engine(face_detected=True, face_count=1)
        engine.tick()
        assert "operator_present" in engine.behaviors

        gov = PipelineGovernor(conversation_debounce_s=0.0)
        gov.veto_chain.add(Veto(name="custom_1", predicate=lambda _s: False))
        gov.veto_chain.add(Veto(name="custom_2", predicate=lambda _s: False))

        state = _make_state(
            activity_mode="production",
            face_count=2,
            guest_count=1,
            speech_detected=True,
        )
        # First eval to set conversation state
        gov.evaluate(state)
        gov.evaluate(state)
        assert len(gov.last_veto_result.denied_by) == 4

        # Add 5th veto
        gov.veto_chain.add(Veto(name="custom_3", predicate=lambda _s: False))
        gov.evaluate(state)
        assert len(gov.last_veto_result.denied_by) == 5

        cmd = Command(
            action="pause", params={"total_vetoes": 5}, governance_result=gov.last_veto_result
        )
        assert isinstance(cmd.params, MappingProxyType)


# ── Class 2: Freshness Reconfiguration Invariants ───────────────────────────


class TestFreshnessReconfigurationInvariants:
    """Tightening freshness only restricts; time monotonicity holds."""

    def test_tightening_freshness_never_accepts_previously_rejected(self):
        """S2, S3, S4, S6 + A1, A2, A5: Tighter threshold only restricts."""
        now = time.monotonic()
        trigger: Event[str] = Event()
        behaviors = {"sensor": Behavior("ok", watermark=now - 8.0)}
        fused = with_latest_from(trigger, behaviors)
        received: list[FusedContext] = []
        fused.subscribe(lambda ts, ctx: received.append(ctx))
        trigger.emit(now, "snap")
        ctx = received[0]

        # 10s threshold: passes
        g10 = FreshnessGuard([FreshnessRequirement("sensor", 10.0)])
        assert g10.check(ctx, now).fresh_enough is True

        # 5s threshold: fails
        g5 = FreshnessGuard([FreshnessRequirement("sensor", 5.0)])
        assert g5.check(ctx, now).fresh_enough is False

        # 1s threshold: still fails
        g1 = FreshnessGuard([FreshnessRequirement("sensor", 1.0)])
        assert g1.check(ctx, now).fresh_enough is False

        # Missing behavior
        gm = FreshnessGuard([FreshnessRequirement("nope", 10.0)])
        assert "not present" in gm.check(ctx, now).violations[0]

        cmd = Command(action="pause", params={"threshold": "tightened"})
        assert isinstance(cmd.params, MappingProxyType)
        assert isinstance(ctx.samples, MappingProxyType)

    def test_adding_freshness_requirement_only_restricts(self):
        """S1, S3, S4, S5 + A1, A4, A5: Adding requirements only restricts governor."""
        now = time.monotonic()
        ctx = FusedContext(
            trigger_time=now,
            trigger_value="x",
            samples={
                "operator_present": Stamped(value=True, watermark=now),
            },
            min_watermark=now,
        )

        gov = PipelineGovernor()
        state = _make_state(activity_mode="idle")

        # No freshness veto → process
        r1 = gov.evaluate(state)
        assert r1 == "process"

        # Add present+fresh requirement → still process
        g1 = FreshnessGuard([FreshnessRequirement("operator_present", 10.0)])
        gov.veto_chain.add(
            Veto(
                name="presence_fresh",
                predicate=lambda _s: g1.check(ctx, now).fresh_enough,
            )
        )
        r2 = gov.evaluate(state)
        assert r2 == "process"

        # Add missing requirement → pause
        g2 = FreshnessGuard([FreshnessRequirement("missing_sensor", 5.0)])
        gov.veto_chain.add(
            Veto(
                name="missing_fresh",
                predicate=lambda _s: g2.check(ctx, now).fresh_enough,
            )
        )
        r3 = gov.evaluate(state)
        assert r3 == "pause"

        assert "not present" in g2.check(ctx, now).violations[0]
        assert "operator_present" in ctx.samples
        assert isinstance(ctx.samples, MappingProxyType)

    def test_freshness_check_time_monotonicity_invariant(self):
        """S1, S2, S3, S6 + A1, A2, A5: If fresh at T2, must be fresh at T1<T2."""
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

        t1 = now + 2.0
        t2 = now + 4.0
        t3 = now + 6.0

        f1 = guard.check(ctx, t1)
        f2 = guard.check(ctx, t2)
        f3 = guard.check(ctx, t3)

        # All fail due to missing, but val staleness monotonically increases
        # At t3, val is also stale (6s > 5s threshold)
        assert len(f3.violations) >= len(f2.violations) >= len(f1.violations)
        assert any("not present" in v for v in f1.violations)

        cmd = Command(action="pause", params={"check_count": 3})
        assert isinstance(cmd.params, MappingProxyType)
        assert isinstance(ctx.samples, MappingProxyType)

    def test_reconfigured_guard_and_reconfigured_veto_compound(self):
        """S3, S4, S5, S6 + A2, A3, A5: Guard replacement + wake word override."""
        now = time.monotonic()

        ctx_fresh = FusedContext(
            trigger_time=now,
            trigger_value="x",
            samples={"ambient": Stamped(value="quiet", watermark=now)},
            min_watermark=now,
        )
        ctx_missing = FusedContext(
            trigger_time=now,
            trigger_value="x",
            samples={},
            min_watermark=now,
        )

        guard_state = {"ctx": ctx_fresh}
        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="ambient", max_staleness_s=10.0),
            ]
        )

        gov = PipelineGovernor()
        gov.veto_chain.add(
            Veto(
                name="ambient_fresh",
                predicate=lambda _s: guard.check(guard_state["ctx"], now).fresh_enough,
            )
        )

        state = _make_state(activity_mode="idle")

        # Fresh context → process
        r1 = gov.evaluate(state)
        assert r1 == "process"
        cmd1 = Command(action=r1, params={"step": 1}, governance_result=gov.last_veto_result)

        # Swap to missing-behavior context → pause
        guard_state["ctx"] = ctx_missing
        r2 = gov.evaluate(state)
        assert r2 == "pause"
        cmd2 = Command(action=r2, params={"step": 2}, governance_result=gov.last_veto_result)

        # Wake word override
        gov.wake_word_active = True
        r3 = gov.evaluate(state)
        assert r3 == "process"
        cmd3 = Command(
            action=r3,
            params={"step": 3},
            governance_result=gov.last_veto_result,
            selected_by=gov.last_selected.selected_by,
        )

        assert cmd1.action == "process"
        assert cmd2.action == "pause"
        assert cmd3.action == "process"
        assert cmd3.selected_by == "wake_word_override"
        assert isinstance(cmd2.params, MappingProxyType)
        assert (
            "not present"
            in FreshnessGuard(
                [
                    FreshnessRequirement("ambient", 10.0),
                ]
            )
            .check(ctx_missing, now)
            .violations[0]
        )


# ── Class 3: Wake Word Reconfiguration Invariants ───────────────────────────


class TestWakeWordReconfigurationInvariants:
    """Wake word toggle behavior is consistent across reconfigurations."""

    def test_wake_word_toggle_invariant_across_evaluations(self):
        """S5, S6, S7 + A2, A3, A4: Wake word toggle pattern: pause/process/pause/process."""
        engine = _make_engine(face_detected=True, face_count=1)
        engine.tick()
        assert "operator_present" in engine.behaviors

        gov = PipelineGovernor()
        state = _make_state(activity_mode="production")

        results = []

        # Eval 1: production → pause
        results.append(gov.evaluate(state))

        # Eval 2: wake word → process
        gov.wake_word_active = True
        results.append(gov.evaluate(state))

        # Exhaust 3-tick grace period
        for _ in range(3):
            gov.evaluate(state)

        # Eval 3: grace exhausted → pause
        results.append(gov.evaluate(state))

        # Eval 4: wake word again → process
        gov.wake_word_active = True
        results.append(gov.evaluate(state))

        assert results == ["pause", "process", "pause", "process"]

        cmd = Command(action="process", params={"toggles": 4})
        assert isinstance(cmd.params, MappingProxyType)

    def test_wake_word_clears_conversation_invariant_across_reconfiguration(self):
        """S5, S6, S3, S4 + A2, A3, A5: Wake word clears conversation; custom veto survives."""
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
                name="custom_freshness",
                predicate=lambda _s: guard.check(ctx, now).fresh_enough,
            )
        )

        # Drive into conversation pause
        conv_state = _make_state(
            activity_mode="idle", face_count=2, guest_count=1, speech_detected=True
        )
        gov.evaluate(conv_state)
        assert gov._paused_by_conversation is True

        # Wake word clears conversation
        gov.wake_word_active = True
        r = gov.evaluate(conv_state)
        assert r == "process"
        assert gov._paused_by_conversation is False

        # Exhaust 3-tick grace period
        for _ in range(3):
            gov.evaluate(_make_state(activity_mode="idle", face_count=1, speech_detected=False))

        # After grace exhausted, custom freshness veto still active
        idle_state = _make_state(activity_mode="idle", face_count=1, speech_detected=False)
        r2 = gov.evaluate(idle_state)
        assert r2 == "pause"
        assert "custom_freshness" in gov.last_veto_result.denied_by
        assert "conversation_debounce" not in gov.last_veto_result.denied_by

        cmd = Command(
            action=r2, params={"step": "after_wake"}, governance_result=gov.last_veto_result
        )
        assert isinstance(cmd.params, MappingProxyType)
        assert "not present" in guard.check(ctx, now).violations[0]

    def test_governor_reconfiguration_preserves_observability_invariant(self):
        """S4, S5, S6 + A1, A2, A3: Observability fields always updated after each eval."""
        now = time.monotonic()
        gov = PipelineGovernor()
        state = _make_state(activity_mode="idle")

        # Eval 1: process
        gov.evaluate(state)
        assert gov.last_veto_result is not None
        assert gov.last_veto_result.allowed is True
        assert gov.last_selected is not None

        # Add custom veto
        gov.veto_chain.add(Veto(name="custom", predicate=lambda _s: False))
        gov.evaluate(state)
        assert gov.last_veto_result.allowed is False
        assert "custom" in gov.last_veto_result.denied_by

        # Wake word
        gov.wake_word_active = True
        gov.evaluate(state)
        assert gov.last_veto_result.allowed is True
        assert gov.last_selected.selected_by == "wake_word_override"

        cmd = Command(
            action="process", params={"obs": True}, governance_result=gov.last_veto_result
        )
        assert isinstance(cmd.params, MappingProxyType)

        ctx = FusedContext(trigger_time=now, trigger_value="x", samples={"a": Stamped(1, now)})
        assert isinstance(ctx.samples, MappingProxyType)

    def test_schedule_domain_invariant_survives_governance_reconfiguration(self):
        """S5, S6, S3 + A2, A3, A5: Schedule.domain preserved across governance changes."""
        now = time.monotonic()
        gov = PipelineGovernor()
        state = _make_state(activity_mode="idle")

        # Schedule 1: process
        r1 = gov.evaluate(state)
        sched1 = Schedule(
            command=Command(action=r1, params={"step": 1}, governance_result=gov.last_veto_result),
            domain="beat",
        )

        # Reconfigure: add veto → pause
        gov.veto_chain.add(Veto(name="deny", predicate=lambda _s: False))
        r2 = gov.evaluate(state)
        sched2 = Schedule(
            command=Command(action=r2, params={"step": 2}, governance_result=gov.last_veto_result),
            domain="beat",
        )

        # Wake word → process
        gov.wake_word_active = True
        r3 = gov.evaluate(state)
        sched3 = Schedule(
            command=Command(action=r3, params={"step": 3}, governance_result=gov.last_veto_result),
            domain="beat",
        )

        assert sched1.domain == sched2.domain == sched3.domain == "beat"
        assert sched1.command.action == "process"
        assert sched2.command.action == "pause"
        assert sched3.command.action == "process"
        assert isinstance(sched1.command.params, MappingProxyType)

        # Freshness check
        guard = FreshnessGuard([FreshnessRequirement("missing", 1.0)])
        ctx = FusedContext(trigger_time=now, trigger_value="x", samples={})
        assert "not present" in guard.check(ctx, now).violations[0]
