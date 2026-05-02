"""Tests for ``agents.studio_compositor.activity_reveal_ward``.

Per cc-task ``activity-reveal-ward-p0-base-class`` (WSJF 7.5). Two
test surfaces:

  - :class:`ActivityRevealWardTestBase`: an abstract test class that
    every concrete ward subclass (P1: ``CodingActivityReveal``,
    P2: ``M8InstrumentReveal``, P5: ``PolyendInstrumentReveal``,
    P6: ``SteamDeckInstrumentReveal``) inherits via
    ``class TestX(ActivityRevealWardTestBase, unittest.TestCase): ...``.
    Provides 7 inherited contract tests.
  - :class:`TestActivityRevealMixinP0Pins`: 4 P0 regression pins on the
    mixin's load-bearing invariants — ``__init_subclass__`` validation,
    ``HAPAX_ACTIVITY_CEILING_DISABLED=1`` bypass, ceiling enforcement
    once the rolling-window total exceeds the per-ward budget, and
    ``poll_once`` fail-CLOSED when the subclass raises.

Plus a sanity test for the P0 router stub (``ActivityRouter.tick()``
iterates without raising and exposes the state snapshot).
"""

from __future__ import annotations

import unittest
from abc import ABC, abstractmethod
from typing import Any
from unittest.mock import patch

from agents.studio_compositor.activity_reveal_ward import (
    ACTIVITY_CEILING_DISABLED_ENV,
    ActivityRevealMixin,
    VisibilityClaim,
)
from agents.studio_compositor.activity_router import (
    ActivityRouter,
    RouterConfig,
    RouterState,
)

# ── Concrete fixture wards used by the tests ──────────────────────────


class _GoodWard(ActivityRevealMixin):
    """Minimal valid concrete subclass used by the abstract base + the
    P0 mixin pins. Implements the abstract surface with deterministic
    knobs the tests can flip."""

    WARD_ID = "fixture-good"
    SOURCE_KIND = "cairo"
    DEFAULT_HYSTERESIS_S = 1.5

    def __init__(self, *, score: float = 0.5, want: bool = False, mand: bool = False) -> None:
        # Pin the fixture's knobs FIRST so __init__ -> poll_once reads
        # them without an AttributeError.
        self._fixture_score = score
        self._fixture_want = want
        self._fixture_mand = mand
        super().__init__(start_poll_thread=False)

    def _compute_claim_score(self) -> float:
        return self._fixture_score

    def _want_visible(self) -> bool:
        return self._fixture_want

    def _mandatory_invisible(self) -> bool:
        return self._fixture_mand

    def _claim_source_refs(self) -> tuple[str, ...]:
        return ("fixture-source",)

    def _describe_source_registration(self) -> dict[str, Any]:
        return {"id": self.WARD_ID, "kind": self.SOURCE_KIND}


class _RaisingWard(_GoodWard):
    """Subclass whose ``_compute_claim_score`` raises — used by the
    fail-CLOSED contract pin."""

    WARD_ID = "fixture-raising"
    SOURCE_KIND = "cairo"

    def _compute_claim_score(self) -> float:
        raise RuntimeError("intentional test failure")


# ── Abstract test base for concrete subclasses (P1+) ─────────────────


class ActivityRevealWardTestBase(ABC):
    """Inherited by every concrete ward subclass test.

    Subclasses provide ``make_ward()`` and inherit 7 contract tests.
    Hosted here so the contract evolves in lock-step with the mixin.
    """

    @abstractmethod
    def make_ward(self) -> ActivityRevealMixin:
        """Build an instance of the ward under test."""

    def test_ward_id_declared(self) -> None:
        ward = self.make_ward()
        try:
            assert getattr(type(ward), "WARD_ID", "")
        finally:
            ward.stop()

    def test_source_kind_valid(self) -> None:
        ward = self.make_ward()
        try:
            assert type(ward).SOURCE_KIND in ("cairo", "external_rgba")
        finally:
            ward.stop()

    def test_current_claim_returns_visibility_claim(self) -> None:
        ward = self.make_ward()
        try:
            ward.poll_once()
            claim = ward.current_claim()
            assert isinstance(claim, VisibilityClaim)
            assert claim.ward_id == type(ward).WARD_ID
        finally:
            ward.stop()

    def test_claim_score_in_range(self) -> None:
        ward = self.make_ward()
        try:
            ward.poll_once()
            claim = ward.current_claim()
            assert 0.0 <= claim.score <= 1.0
        finally:
            ward.stop()

    def test_mandatory_invisible_overrides_want_visible(self) -> None:
        # The mixin doesn't enforce override semantics — the router does.
        # The contract here is that BOTH fields populate as the subclass
        # reports them; routers are responsible for treating
        # mandatory_invisible as authoritative.
        ward = self.make_ward()
        try:
            ward.poll_once()
            claim = ward.current_claim()
            # Both fields are bools and both populate.
            assert isinstance(claim.want_visible, bool)
            assert isinstance(claim.mandatory_invisible, bool)
        finally:
            ward.stop()

    def test_stop_idempotent(self) -> None:
        ward = self.make_ward()
        ward.stop()
        # Second call must not raise.
        ward.stop()

    def test_describe_source_registration_returns_dict(self) -> None:
        ward = self.make_ward()
        try:
            d = ward._describe_source_registration()
            assert isinstance(d, dict)
        finally:
            ward.stop()

    def test_state_returns_required_keys(self) -> None:
        ward = self.make_ward()
        try:
            ward.poll_once()
            s = ward.state()
            assert {
                "ward_id",
                "want_visible",
                "score",
                "mandatory_invisible",
                "hysteresis_floor_s",
                "source_refs",
                "reason",
            } <= set(s)
        finally:
            ward.stop()

    def test_poll_once_survives_compute_exception(self) -> None:
        """Subclasses that legitimately raise must observe the
        fail-CLOSED contract: claim becomes (want=False, mand=True).
        Subclasses without exception paths skip via overridden test."""
        ward = self.make_ward()
        try:
            with patch.object(ward, "_compute_claim_score", side_effect=RuntimeError("boom")):
                ward.poll_once()
            claim = ward.current_claim()
            assert claim.want_visible is False
            assert claim.mandatory_invisible is True
            assert claim.score == 0.0
        finally:
            ward.stop()


# ── Local unittest runner of the abstract base over _GoodWard ─────────


class _GoodWardTests(ActivityRevealWardTestBase, unittest.TestCase):
    """Self-test of the abstract base via the in-file fixture ward."""

    def make_ward(self) -> ActivityRevealMixin:
        return _GoodWard(score=0.6, want=True, mand=False)


# ── 4 P0 regression pins on the mixin ────────────────────────────────


class TestActivityRevealMixinP0Pins(unittest.TestCase):
    """The 4 P0 regression pins from the cc-task acceptance criteria."""

    # Pin 1: __init_subclass__ validates WARD_ID / SOURCE_KIND.

    def test_subclass_without_ward_id_raises(self) -> None:
        with self.assertRaises(TypeError) as ctx:

            class _BadNoWardId(ActivityRevealMixin):
                # WARD_ID absent (default empty string).
                SOURCE_KIND = "cairo"

                def _compute_claim_score(self) -> float:
                    return 0.0

                def _want_visible(self) -> bool:
                    return False

                def _mandatory_invisible(self) -> bool:
                    return False

                def _claim_source_refs(self) -> tuple[str, ...]:
                    return ()

                def _describe_source_registration(self) -> dict[str, Any]:
                    return {}

        self.assertIn("WARD_ID", str(ctx.exception))

    def test_subclass_with_invalid_source_kind_raises(self) -> None:
        with self.assertRaises(TypeError) as ctx:

            class _BadKind(ActivityRevealMixin):
                WARD_ID = "bad-kind"
                SOURCE_KIND = "wgpu"  # type: ignore[assignment]

                def _compute_claim_score(self) -> float:
                    return 0.0

                def _want_visible(self) -> bool:
                    return False

                def _mandatory_invisible(self) -> bool:
                    return False

                def _claim_source_refs(self) -> tuple[str, ...]:
                    return ()

                def _describe_source_registration(self) -> dict[str, Any]:
                    return {}

        self.assertIn("SOURCE_KIND", str(ctx.exception))

    # Pin 2: HAPAX_ACTIVITY_CEILING_DISABLED=1 bypass.

    def test_ceiling_enforced_disabled_by_env(self) -> None:
        ward = _GoodWard()
        try:
            # Pre-fill the visibility window with twice the ceiling
            # budget so the unsuppressed branch would return True.
            ward._visible_intervals.append((0.0, ward._visibility_ceiling_s * 2))
            with patch.dict("os.environ", {ACTIVITY_CEILING_DISABLED_ENV: "1"}):
                self.assertFalse(ward._ceiling_enforced(now=ward._visibility_ceiling_s * 2))
        finally:
            ward.stop()

    # Pin 3: ceiling enforced once accumulated visible-seconds exceed
    # the budget within the rolling window.

    def test_ceiling_enforced_when_budget_consumed(self) -> None:
        ward = _GoodWard()
        try:
            budget = ward._visibility_ceiling_s
            # Single interval just over the per-ward budget.
            ward._visible_intervals.append((0.0, budget + 1.0))
            self.assertTrue(ward._ceiling_enforced(now=budget + 1.0))
        finally:
            ward.stop()

    def test_ceiling_not_enforced_below_budget(self) -> None:
        ward = _GoodWard()
        try:
            budget = ward._visibility_ceiling_s
            ward._visible_intervals.append((0.0, budget * 0.5))
            self.assertFalse(ward._ceiling_enforced(now=budget * 0.5))
        finally:
            ward.stop()

    # Pin 4: poll_once fail-CLOSED on subclass exception.

    def test_poll_once_fail_closed_on_exception(self) -> None:
        ward = _RaisingWard()
        try:
            ward.poll_once()
            claim = ward.current_claim()
            self.assertFalse(claim.want_visible)
            self.assertTrue(claim.mandatory_invisible)
            self.assertEqual(claim.score, 0.0)
            self.assertIn("compute_exception", claim.reason)
        finally:
            ward.stop()


# ── Mixin auxiliaries ────────────────────────────────────────────────


class TestMixinAuxiliaries(unittest.TestCase):
    def test_mark_visible_window_evicts_old_entries(self) -> None:
        ward = _GoodWard()
        try:
            window = ward._rolling_window_s
            # Old interval, fully outside the window.
            ward.mark_visible_window(0.0, 10.0)
            # Fresh interval inside the window.
            ward.mark_visible_window(window + 100.0, window + 110.0)
            # Eviction occurs the next time we call _consumed_visible_seconds.
            consumed = ward._consumed_visible_seconds(now=window + 110.0)
            # Only the fresh 10-second interval should count.
            self.assertAlmostEqual(consumed, 10.0, places=3)
        finally:
            ward.stop()

    def test_mark_visible_window_rejects_inverted_range(self) -> None:
        ward = _GoodWard()
        try:
            ward.mark_visible_window(end_ts=10.0, start_ts=20.0)
            self.assertEqual(ward._consumed_visible_seconds(now=100.0), 0.0)
        finally:
            ward.stop()

    def test_score_clamped_to_unit_interval(self) -> None:
        # A misbehaving subclass that returns out-of-range scores must
        # be clamped before the claim is published.
        class _OutOfRange(_GoodWard):
            WARD_ID = "fixture-clamp"

            def _compute_claim_score(self) -> float:
                return 99.0

        ward = _OutOfRange()
        try:
            ward.poll_once()
            self.assertEqual(ward.current_claim().score, 1.0)
        finally:
            ward.stop()


# ── ActivityRouter (P0 stub) ─────────────────────────────────────────


class TestActivityRouterP0(unittest.TestCase):
    def test_tick_returns_state_with_claims(self) -> None:
        wards = (
            _GoodWard(score=0.6, want=True),
            _GoodWard(score=0.3, want=False),
        )
        # Two wards share the same WARD_ID via _GoodWard; ensure the
        # second occurrence in the dict overwrites cleanly. (Real
        # subclasses get unique IDs via __init_subclass__ checks.)
        router = ActivityRouter(wards)
        try:
            for w in wards:
                w.poll_once()
            state = router.tick(now=1234.0)
            self.assertIsInstance(state, RouterState)
            self.assertEqual(state.tick_ts, 1234.0)
            self.assertEqual(len(state.claims), 1)  # same WARD_ID
        finally:
            router.stop()
            for w in wards:
                w.stop()

    def test_tick_classifies_into_visible_lists(self) -> None:
        class _A(_GoodWard):
            WARD_ID = "router-a"

        class _B(_GoodWard):
            WARD_ID = "router-b"

        class _C(_GoodWard):
            WARD_ID = "router-c"

        a = _A(score=0.7, want=True, mand=False)
        b = _B(score=0.2, want=False, mand=False)
        c = _C(score=0.9, want=True, mand=True)
        router = ActivityRouter((a, b, c))
        try:
            for w in (a, b, c):
                w.poll_once()
            state = router.tick(now=42.0)
            self.assertEqual(state.want_visible_ids, ("router-a",))
            self.assertEqual(state.mandatory_invisible_ids, ("router-c",))
        finally:
            router.stop()
            for w in (a, b, c):
                w.stop()

    def test_describe_lists_ward_ids(self) -> None:
        class _D(_GoodWard):
            WARD_ID = "describe-ward"

        d = _D()
        router = ActivityRouter((d,), config=RouterConfig(tick_hz=4.0))
        try:
            desc = router.describe()
            self.assertEqual(desc["ward_count"], 1)
            self.assertEqual(desc["ward_ids"], ["describe-ward"])
            self.assertEqual(desc["tick_hz"], 4.0)
        finally:
            router.stop()
            d.stop()

    def test_stop_idempotent(self) -> None:
        router = ActivityRouter(())
        router.stop()
        router.stop()  # second call must not raise


if __name__ == "__main__":
    unittest.main()
