"""Cross-cutting integration tests for the perception type system (matrix 4).

Algebraic properties and edge cases: commutativity (VetoChain
order-independent), idempotency (re-evaluation stable), and boundary
conditions (empty chains, zero behaviors, threshold exactness).
"""

from __future__ import annotations

import time
from types import MappingProxyType
from unittest.mock import MagicMock

from agents.hapax_voice.combinator import with_latest_from
from agents.hapax_voice.commands import Command
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
    """Create an EnvironmentState with sensible defaults."""
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
    """PerceptionEngine with mocked presence/workspace_monitor."""
    presence = MagicMock()
    presence.latest_vad_confidence = vad
    presence.face_detected = face_detected
    presence.face_count = face_count

    workspace_monitor = MagicMock()
    return PerceptionEngine(presence, workspace_monitor)


# ── Class 1: Commutativity ───────────────────────────────────────────────────


class TestCommutativity:
    """Order-independent evaluation where promised."""

    def test_veto_chain_order_independent_through_fused_context(self):
        """S3, S4, A1: VetoChain produces same result regardless of veto order."""
        now = time.monotonic()
        ctx = FusedContext(
            trigger_time=now,
            trigger_value="test",
            samples={
                "x": Stamped(value=1, watermark=now),
                "y": Stamped(value=2, watermark=now - 100.0),
            },
            min_watermark=now - 100.0,
        )

        guard_x = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="x", max_staleness_s=5.0),
            ]
        )
        guard_y = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="y", max_staleness_s=5.0),
            ]
        )

        veto_a = Veto(name="x_fresh", predicate=lambda c: guard_x.check(c, now).fresh_enough)
        veto_b = Veto(name="y_fresh", predicate=lambda c: guard_y.check(c, now).fresh_enough)
        veto_c = Veto(name="always_ok", predicate=lambda _c: True)

        chain_abc: VetoChain[FusedContext] = VetoChain([veto_a, veto_b, veto_c])
        chain_cba: VetoChain[FusedContext] = VetoChain([veto_c, veto_b, veto_a])

        r_abc = chain_abc.evaluate(ctx)
        r_cba = chain_cba.evaluate(ctx)

        assert r_abc.allowed == r_cba.allowed
        assert set(r_abc.denied_by) == set(r_cba.denied_by)
        assert isinstance(ctx.samples, MappingProxyType)

    def test_freshness_guard_requirement_order_irrelevant(self):
        """S3, S7, A4, A5: FreshnessGuard produces same violations regardless of requirement order."""
        engine = _make_engine(face_detected=True, face_count=1)
        engine.tick()

        trigger: Event[str] = Event()
        fused_event = with_latest_from(trigger, engine.behaviors)
        received: list[FusedContext] = []
        fused_event.subscribe(lambda ts, ctx: received.append(ctx))

        now = time.monotonic()
        trigger.emit(now, "snap")
        ctx = received[0]

        reqs = [
            FreshnessRequirement(behavior_name="operator_present", max_staleness_s=10.0),
            FreshnessRequirement(behavior_name="missing_a", max_staleness_s=5.0),
            FreshnessRequirement(behavior_name="missing_b", max_staleness_s=5.0),
        ]

        guard_fwd = FreshnessGuard(reqs)
        guard_rev = FreshnessGuard(list(reversed(reqs)))

        r_fwd = guard_fwd.check(ctx, now)
        r_rev = guard_rev.check(ctx, now)

        assert r_fwd.fresh_enough == r_rev.fresh_enough
        assert set(r_fwd.violations) == set(r_rev.violations)
        assert any("not present" in v for v in r_fwd.violations)
        assert "operator_present" in ctx.samples

    def test_fallback_chain_priority_order_matters(self):
        """S3, S4, A1: FallbackChain is NOT commutative — first eligible wins."""
        now = time.monotonic()
        ctx = FusedContext(
            trigger_time=now,
            trigger_value="test",
            samples={"x": Stamped(value=1, watermark=now)},
            min_watermark=now,
        )

        cand_a = Candidate(name="alpha", predicate=lambda _c: True, action="do_alpha")
        cand_b = Candidate(name="beta", predicate=lambda _c: True, action="do_beta")

        chain_ab: FallbackChain[FusedContext, str] = FallbackChain([cand_a, cand_b], default="nop")
        chain_ba: FallbackChain[FusedContext, str] = FallbackChain([cand_b, cand_a], default="nop")

        r_ab = chain_ab.select(ctx)
        r_ba = chain_ba.select(ctx)

        assert r_ab.selected_by == "alpha"
        assert r_ba.selected_by == "beta"
        assert r_ab.action != r_ba.action
        assert isinstance(ctx.samples, MappingProxyType)

    def test_veto_commutativity_with_governor_custom_vetoes(self):
        """S4, S5, A3: Two governors with custom vetoes in opposite order produce same result."""
        gov_xy = PipelineGovernor()
        gov_yx = PipelineGovernor()

        veto_x = Veto(name="custom_x", predicate=lambda _s: False)
        veto_y = Veto(name="custom_y", predicate=lambda _s: True)

        gov_xy.veto_chain.add(veto_x)
        gov_xy.veto_chain.add(veto_y)

        gov_yx.veto_chain.add(veto_y)
        gov_yx.veto_chain.add(veto_x)

        state = _make_state(activity_mode="idle")

        r_xy = gov_xy.evaluate(state)
        r_yx = gov_yx.evaluate(state)

        assert r_xy == r_yx == "pause"
        assert set(gov_xy.last_veto_result.denied_by) == set(gov_yx.last_veto_result.denied_by)
        assert "custom_x" in gov_xy.last_veto_result.denied_by


# ── Class 2: Idempotency ────────────────────────────────────────────────────


class TestIdempotency:
    """Re-evaluation with same inputs produces same results."""

    def test_veto_chain_idempotent_on_same_context(self):
        """S3, S4, A1: Same context through same chain 3 times gives identical results."""
        now = time.monotonic()
        ctx = FusedContext(
            trigger_time=now,
            trigger_value="tick",
            samples={
                "val": Stamped(value="ok", watermark=now - 10.0),
            },
            min_watermark=now - 10.0,
        )

        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="val", max_staleness_s=5.0),
            ]
        )
        chain: VetoChain[FusedContext] = VetoChain(
            [
                Veto(name="staleness", predicate=lambda c: guard.check(c, now).fresh_enough),
            ]
        )

        results = [chain.evaluate(ctx) for _ in range(3)]
        assert all(r.allowed == results[0].allowed for r in results)
        assert all(r.denied_by == results[0].denied_by for r in results)
        assert isinstance(ctx.samples, MappingProxyType)

    def test_governor_idempotent_on_stateless_evaluation(self):
        """S5, S6, A2, A3: Governor returns same result for repeated stateless evaluations."""
        gov = PipelineGovernor()
        state = _make_state(activity_mode="idle")

        results = []
        for _ in range(3):
            r = gov.evaluate(state)
            results.append(
                (
                    r,
                    gov.last_veto_result.allowed,
                    gov.last_selected.selected_by,
                )
            )

        assert all(r == results[0] for r in results)

        cmd = Command(
            action="process",
            params={"repeat": 3},
            governance_result=gov.last_veto_result,
        )
        assert isinstance(cmd.params, MappingProxyType)

    def test_freshness_guard_pure_function(self):
        """S3, S7, A4, A5: FreshnessGuard.check is pure — same inputs, same output."""
        engine = _make_engine(face_detected=True, face_count=1)
        engine.tick()

        trigger: Event[str] = Event()
        fused_event = with_latest_from(trigger, engine.behaviors)
        received: list[FusedContext] = []
        fused_event.subscribe(lambda ts, ctx: received.append(ctx))

        now = time.monotonic()
        trigger.emit(now, "snap")
        ctx = received[0]

        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="operator_present", max_staleness_s=10.0),
                FreshnessRequirement(behavior_name="missing_key", max_staleness_s=5.0),
            ]
        )

        results = [guard.check(ctx, now) for _ in range(3)]
        assert all(r.fresh_enough == results[0].fresh_enough for r in results)
        assert all(r.violations == results[0].violations for r in results)
        assert any("not present" in v for v in results[0].violations)
        assert "operator_present" in ctx.samples

    def test_combinator_deterministic_on_stable_behaviors(self):
        """S1, S2, A1: Same behaviors, multiple triggers, same sample values."""
        b = Behavior(42, watermark=10.0)
        trigger: Event[str] = Event()
        fused_event = with_latest_from(trigger, {"val": b})
        received: list[FusedContext] = []
        fused_event.subscribe(lambda ts, ctx: received.append(ctx))

        for t in (11.0, 12.0, 13.0):
            trigger.emit(t, "tick")

        assert len(received) == 3
        for ctx in received:
            assert ctx.get_sample("val").value == 42
            assert ctx.get_sample("val").watermark == 10.0
            assert isinstance(ctx.samples, MappingProxyType)

        # Only trigger_time differs
        assert received[0].trigger_time == 11.0
        assert received[1].trigger_time == 12.0
        assert received[2].trigger_time == 13.0


# ── Class 3: Boundary Conditions ────────────────────────────────────────────


class TestBoundaryConditions:
    """Degenerate and edge-case inputs produce well-defined results."""

    def test_empty_behaviors_produce_valid_fused_context(self):
        """S1, S2, A1: with_latest_from with zero behaviors produces valid context."""
        trigger: Event[str] = Event()
        fused_event = with_latest_from(trigger, {})
        received: list[FusedContext] = []
        fused_event.subscribe(lambda ts, ctx: received.append(ctx))

        trigger.emit(42.0, "empty")

        assert len(received) == 1
        ctx = received[0]
        assert len(ctx.samples) == 0
        assert isinstance(ctx.samples, MappingProxyType)
        assert ctx.trigger_time == 42.0
        # min() with default=timestamp when no behaviors
        assert ctx.min_watermark == 42.0

    def test_empty_veto_chain_always_allows(self):
        """S4, S5, S6, A2: Empty VetoChain allows everything."""
        chain: VetoChain[FusedContext] = VetoChain()
        now = time.monotonic()
        ctx = FusedContext(
            trigger_time=now,
            trigger_value="test",
            samples={},
            min_watermark=now,
        )
        result = chain.evaluate(ctx)
        assert result.allowed is True
        assert result.denied_by == ()

        gov = PipelineGovernor()
        state = _make_state(activity_mode="idle")
        r = gov.evaluate(state)
        assert r == "process"

        cmd = Command(action="process", params={})
        assert isinstance(cmd.params, MappingProxyType)
        assert len(cmd.params) == 0

    def test_freshness_guard_no_requirements_always_fresh(self):
        """S3, S7, A4, A5: FreshnessGuard with no requirements always passes."""
        engine = _make_engine(face_detected=True, face_count=1)
        engine.tick()

        trigger: Event[str] = Event()
        fused_event = with_latest_from(trigger, engine.behaviors)
        received: list[FusedContext] = []
        fused_event.subscribe(lambda ts, ctx: received.append(ctx))

        now = time.monotonic()
        trigger.emit(now, "snap")
        ctx = received[0]

        empty_guard = FreshnessGuard()
        result = empty_guard.check(ctx, now)
        assert result.fresh_enough is True
        assert result.violations == ()

        assert "operator_present" in ctx.samples

        # Adding one missing requirement changes outcome
        guard_with_req = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="nonexistent", max_staleness_s=1.0),
            ]
        )
        result2 = guard_with_req.check(ctx, now)
        assert result2.fresh_enough is False
        assert "not present" in result2.violations[0]

    def test_freshness_at_exact_staleness_threshold(self):
        """S3, S6, A1, A2: Staleness exactly at threshold passes; epsilon beyond fails."""
        now = time.monotonic()
        threshold = 5.0

        # Exactly at threshold: staleness == max_staleness_s
        ctx_exact = FusedContext(
            trigger_time=now,
            trigger_value="test",
            samples={
                "signal": Stamped(value="ok", watermark=now - threshold),
            },
            min_watermark=now - threshold,
        )

        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="signal", max_staleness_s=threshold),
            ]
        )

        # staleness == threshold, guard uses > (not >=), so exactly at threshold passes
        result_exact = guard.check(ctx_exact, now)
        assert result_exact.fresh_enough is True

        # Epsilon beyond threshold
        epsilon = 0.001
        ctx_stale = FusedContext(
            trigger_time=now,
            trigger_value="test",
            samples={
                "signal": Stamped(value="ok", watermark=now - threshold - epsilon),
            },
            min_watermark=now - threshold - epsilon,
        )
        result_stale = guard.check(ctx_stale, now)
        assert result_stale.fresh_enough is False

        # Build Commands from each path
        cmd_ok = Command(action="process", params={"fresh": True})
        cmd_stale = Command(action="pause", params={"fresh": False})
        assert isinstance(cmd_ok.params, MappingProxyType)
        assert isinstance(cmd_stale.params, MappingProxyType)
        assert isinstance(ctx_exact.samples, MappingProxyType)
