"""Tests for the seg-prep changing-criterion phase controller (G3 / LANE-DATA-SPINE #12).

The controller is pure logic over the DV reader's per-phase summaries; it applies the
ratified §5.1 advance rule (min 8 hosted; advance when the last 3 pre-gate means are within
20%; force-advance at 15) and emits hold / advance / complete + the next C_k.
"""

from __future__ import annotations

import pytest

from shared.segment_prep_dv_reader import PhaseSummary, ProducerObservation
from shared.segment_prep_phase_controller import (
    PhaseDecision,
    PhasePlan,
    decide,
    is_stable,
    phase_complete,
)


def _phase_obs(
    criterion: float,
    scores: list[float],
    *,
    released: list[bool] | None = None,
    start: int = 0,
) -> list[ProducerObservation]:
    """Producer observations at one C_k, with deterministic chronological order."""
    out: list[ProducerObservation] = []
    for i, score in enumerate(scores):
        seq = start + i
        out.append(
            ProducerObservation(
                programme_id=f"p{seq}",
                ledgered_at=f"2026-06-16T00:{seq:02d}:00Z",
                mean_score=score,
                criterion=criterion,
                released=True if released is None else released[i],
                source="test",
            )
        )
    return out


def _summary(
    scores: list[float], *, criterion: float = 3.0, released: int | None = None
) -> PhaseSummary:
    """Build a real PhaseSummary; `released` (hosted count) defaults to all-hosted (A0 floor case)."""
    n = len(scores)
    released = n if released is None else released
    return PhaseSummary(
        criterion=criterion,
        pre_gate_scores=list(scores),
        n=n,
        released=released,
        released_fraction=(released / n) if n else 0.0,
        mean_pre_gate=(sum(scores) / n) if n else None,
    )


class TestIsStable:
    """§5.1 stability: the producer DV is stable when the last `window` pre-gate means are
    within `tolerance` of each other (relative range about their mean)."""

    def test_true_when_last_three_within_tolerance(self):
        # range 0.2 / mean 4.0 = 5% <= 20%
        assert is_stable([4.0, 4.1, 3.9]) is True

    def test_false_when_last_three_exceed_tolerance(self):
        # range 2.0 / mean 4.0 = 50% > 20%
        assert is_stable([4.0, 5.0, 3.0]) is False

    def test_uses_only_the_last_window(self):
        # early volatility is ignored; only the trailing window is judged
        assert is_stable([1.0, 5.0, 4.0, 4.1, 3.9]) is True

    def test_false_with_fewer_than_window_scores(self):
        # not enough trailing data to declare stability
        assert is_stable([4.0, 4.1]) is False

    def test_false_for_nonpositive_window(self):
        # window <= 0 is nonsensical; never "stable" (and must not silently judge the whole series)
        assert is_stable([4.0, 4.0, 4.0], window=0) is False
        assert is_stable([4.0, 4.0, 4.0], window=-1) is False

    def test_false_for_nonpositive_mean(self):
        # the relative-range formula assumes a positive mean; a zero/negative window mean is not stable
        assert is_stable([0.0, 0.0, 0.0]) is False
        assert is_stable([-1.0, -1.0, -1.0]) is False


class TestPhaseComplete:
    """§5.1 per-phase stop rule: complete when hosted >= min_hosted AND the DV is stable, OR when
    hosted reaches the max-segments cap (force-advance regardless of stability)."""

    PLAN = PhasePlan(criteria=(3.0,))  # defaults: min_hosted=8, max_segments=15, window=3, tol=0.20

    def test_incomplete_below_min_hosted(self):
        # 5 hosted < 8, even though the DV is perfectly stable
        done, reason = phase_complete(_summary([4.0] * 5, released=5), self.PLAN)
        assert done is False
        assert "hosted" in reason

    def test_incomplete_when_min_hosted_but_unstable(self):
        # 10 hosted >= 8, but the trailing window swings (3.0, 5.0, 4.0)
        scores = [4.0] * 7 + [3.0, 5.0, 4.0]
        done, reason = phase_complete(_summary(scores, released=10), self.PLAN)
        assert done is False
        assert "stab" in reason.lower()

    def test_complete_when_min_hosted_and_stable(self):
        done, _ = phase_complete(_summary([4.0] * 10, released=10), self.PLAN)
        assert done is True

    def test_complete_at_cap_on_total_observations_even_if_unstable(self):
        # 15 PRODUCED segments hits the cap even though only 4 were released (a yield-collapse /
        # ceiling phase): the cap bounds TOTAL produced segments, not the hosted count, so a
        # non-converging phase still terminates (spec §6 ceiling-reached). A hosted-unit cap would
        # hold forever here because released never reaches 15.
        scores = [4.0] * 12 + [3.0, 5.0, 4.0]  # 15 produced, volatile tail
        done, reason = phase_complete(_summary(scores, released=4), self.PLAN)
        assert done is True
        assert any(word in reason.lower() for word in ("cap", "ceiling", "max"))

    def test_hosted_counts_released_not_total_observations(self):
        # 12 producer observations but only the released count gates phase length:
        # 8 released -> complete; 7 released (sieve dropped one more) -> not complete.
        scores = [4.0] * 12
        assert phase_complete(_summary(scores, released=8), self.PLAN)[0] is True
        assert phase_complete(_summary(scores, released=7), self.PLAN)[0] is False


class TestDecide:
    """End-to-end control decision over DV observations: hold / advance / complete + next C_k."""

    A0 = PhasePlan(criteria=(3.0,))
    LADDER = PhasePlan(criteria=(3.0, 3.5, 4.0))
    REVERSAL = PhasePlan(criteria=(3.0, 3.5, 4.0, 3.2))  # last step LOWERS the criterion

    def test_holds_when_no_observations_yet(self):
        d = decide(self.A0, [])
        assert isinstance(d, PhaseDecision)
        assert d.action == "hold"
        assert d.current_criterion == 3.0
        assert d.next_criterion == 3.0  # keep collecting at the same C_k
        assert d.hosted == 0

    def test_holds_while_below_min_hosted(self):
        d = decide(self.A0, _phase_obs(3.0, [4.0] * 5))
        assert d.action == "hold"
        assert d.hosted == 5
        assert d.is_reversal is False

    def test_a0_completes_with_baseline_complete_when_stable(self):
        # A single-criterion (A0) plan that meets its stop rule is "baseline_complete" — distinct
        # from a fully-exhausted multi-step ladder — so a runner never misreads A0-done as run-done.
        d = decide(self.A0, _phase_obs(3.0, [4.0] * 10))
        assert d.action == "baseline_complete"
        assert d.current_criterion == 3.0
        assert d.next_criterion is None
        assert d.stable is True

    def test_a0_completes_at_cap_even_if_unstable(self):
        scores = [4.0] * 12 + [3.0, 5.0, 4.0]  # 15 produced, volatile tail
        d = decide(self.A0, _phase_obs(3.0, scores))
        assert d.action == "baseline_complete"
        assert d.hosted == 15

    def test_exhausted_multi_phase_ladder_is_complete(self):
        # the active phase is the last ladder criterion and it completes -> "complete" (run done)
        obs = _phase_obs(3.0, [4.0] * 10, start=0) + _phase_obs(3.5, [4.2] * 10, start=10)
        d = decide(PhasePlan(criteria=(3.0, 3.5)), obs)
        assert d.action == "complete"
        assert d.current_criterion == 3.5
        assert d.next_criterion is None

    def test_off_plan_observations_are_surfaced_not_silently_stalled(self):
        # 15 aired segments at an off-plan C_k must NOT read as "no observations yet" (silent stall);
        # the off-plan criterion is surfaced so an env/plan drift is visible.
        d = decide(self.A0, _phase_obs(3.5, [4.0] * 15))
        assert d.action == "hold"
        assert d.hosted == 0
        assert "3.5" in d.reason or "off-plan" in d.reason.lower()

    def test_advances_to_next_criterion_when_phase_complete(self):
        d = decide(self.LADDER, _phase_obs(3.0, [4.0] * 10))
        assert d.action == "advance"
        assert d.current_criterion == 3.0
        assert d.next_criterion == 3.5
        assert d.is_reversal is False

    def test_active_phase_is_the_highest_reached_criterion(self):
        # observations exist at both 3.0 and 3.5; the active phase is 3.5 (still collecting there)
        obs = _phase_obs(3.0, [4.0] * 10, start=0) + _phase_obs(3.5, [4.2] * 4, start=10)
        d = decide(self.LADDER, obs)
        assert d.current_criterion == 3.5
        assert d.action == "hold"  # only 4 hosted at 3.5 (< min)
        assert d.hosted == 4

    def test_criterion_key_precision_matches_reader(self):
        # The controller keys plan C_k values into the reader's rounded per-phase summaries; the two
        # precisions MUST stay equal or active-phase lookup silently misses (drift guard).
        from shared import segment_prep_dv_reader, segment_prep_phase_controller

        assert (
            segment_prep_phase_controller._CRITERION_KEY_PRECISION
            == segment_prep_dv_reader._CRITERION_KEY_PRECISION
        )

    def test_reversal_step_is_flagged(self):
        # fully through the ascending ladder; the active phase is 4.0 and it completes
        obs = (
            _phase_obs(3.0, [4.0] * 10, start=0)
            + _phase_obs(3.5, [4.2] * 10, start=10)
            + _phase_obs(4.0, [4.4] * 10, start=20)
        )
        d = decide(self.REVERSAL, obs)
        assert d.action == "advance"
        assert d.current_criterion == 4.0
        assert d.next_criterion == 3.2
        assert d.is_reversal is True


class TestPhasePlanValidation:
    """Phases are identified in the captured DV by C_k VALUE, so the plan must use distinct values
    (otherwise a reversal that reuses an earlier value silently merges with that phase and reports
    a false complete). Cross-parameter coupling is validated up-front so a misconfigured plan fails
    LOUD rather than silently changing the stop behavior."""

    def test_rejects_duplicate_criteria(self):
        with pytest.raises(ValueError, match="distinct"):
            PhasePlan(criteria=(3.0, 3.5, 3.0))

    def test_rejects_empty_criteria(self):
        with pytest.raises(ValueError):
            PhasePlan(criteria=())

    def test_rejects_stability_window_below_one(self):
        with pytest.raises(ValueError):
            PhasePlan(criteria=(3.0,), stability_window=0)

    def test_rejects_min_hosted_below_stability_window(self):
        # min_hosted < window would let the floor pass before stability can ever be computed
        with pytest.raises(ValueError):
            PhasePlan(criteria=(3.0,), min_hosted=2, stability_window=3)

    def test_rejects_max_segments_below_min_hosted(self):
        with pytest.raises(ValueError):
            PhasePlan(criteria=(3.0,), min_hosted=8, max_segments=5)

    def test_rejects_nonpositive_tolerance(self):
        with pytest.raises(ValueError):
            PhasePlan(criteria=(3.0,), stability_tolerance=0.0)

    def test_accepts_a_well_formed_ascending_plus_reversal_ladder(self):
        plan = PhasePlan(criteria=(3.0, 3.5, 4.0, 3.2))
        assert plan.criteria == (3.0, 3.5, 4.0, 3.2)

    def test_rejects_criterion_outside_operative_range(self):
        # C_k must lie on the gate-operative (1.0, 5.0] coherence rubric — prep refuses otherwise,
        # so an out-of-range plan would crash the first prep pass instead of failing at build time.
        with pytest.raises(ValueError):
            PhasePlan(criteria=(0.5,))
        with pytest.raises(ValueError):
            PhasePlan(criteria=(1.0,))  # exclusive lower bound
        with pytest.raises(ValueError):
            PhasePlan(criteria=(5.5,))

    def test_accepts_upper_bound_criterion(self):
        assert PhasePlan(criteria=(5.0,)).criteria == (5.0,)
