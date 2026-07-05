"""Self-contained tests for the intake fit-scorer shadow slice.

The scorer is the first half of the (1)<->(2) loop: it ranks offered tasks by their
demand-shape (the 8-dim requirement_vector) alongside WSJF, behind a default-off blend
flag. ``fit_score`` shadows the engine's ``requirement_fit`` concept (mean of scored
non-quality_floor dims, scale 0..5) at the task level.

The three load-bearing invariants (the "verify corrections"):
  * blend == 0.0 => composite is byte-identical to wsjf_effective (the golden guarantee);
  * fit_score never raises / never returns NaN on None/partial/non-int/bool (honest-DARK);
  * quality_floor is excluded (matches the engine's _scored_requirement_dimensions).
"""

from __future__ import annotations

import math

from shared.intake_fit_scorer import composite_rank_key, fit_score

# ---------------------------------------------------------------------- fit_score


def test_fit_score_full_valid_vector() -> None:
    # All 8 dims; quality_floor excluded -> mean of the other 7.
    rv = {
        "quality_floor": 5,
        "information_scope": 4,
        "context_length": 4,
        "mutation_risk": 5,
        "verification_demand": 3,
        "ambiguity_novelty": 2,
        "composition_coupling": 1,
        "governance_sensitivity": 2,
    }
    # (4+4+5+3+2+1+2)/7 = 21/7 = 3.0
    assert fit_score(rv) == 3.0


def test_fit_score_partial_vector() -> None:
    # A partial vector (only some dims present) scores over the dims that ARE present.
    rv = {"context_length": 4, "mutation_risk": 5}
    assert fit_score(rv) == 4.5  # (4+5)/2


def test_fit_score_none_is_dark_zero() -> None:
    # None = absent/unparsed -> honest-DARK, the neutral score (no fit influence).
    assert fit_score(None) == 0.0


def test_fit_score_empty_is_dark_zero() -> None:
    assert fit_score({}) == 0.0


def test_fit_score_rejects_bool_dim() -> None:
    # bool is a subclass of int but must be rejected (strict-int scores); the dim is
    # excluded, not counted as 1.
    rv = {"context_length": 4, "mutation_risk": True}
    assert fit_score(rv) == 4.0  # only context_length counts


def test_fit_score_rejects_non_int_dim() -> None:
    rv = {"context_length": 4, "mutation_risk": "5", "verification_demand": 4.0}
    # "5" (str) and 4.0 (float) are excluded; only the strict-int 4 counts.
    assert fit_score(rv) == 4.0


def test_fit_score_all_zero_is_neutral_zero() -> None:
    # All-zero is a VALID low-complexity vector (neutral), not absent. It scores 0.0.
    rv = {
        dim: 0
        for dim in (
            "quality_floor",
            "information_scope",
            "context_length",
            "mutation_risk",
            "verification_demand",
            "ambiguity_novelty",
            "composition_coupling",
            "governance_sensitivity",
        )
    }
    assert fit_score(rv) == 0.0


def test_fit_score_excludes_quality_floor() -> None:
    # quality_floor is a hard floor (enforced as a veto in the engine), not a soft score;
    # a saturated quality_floor must NOT inflate the intake fit_score.
    low_qf = {"quality_floor": 0, "context_length": 4}
    high_qf = {"quality_floor": 5, "context_length": 4}
    assert fit_score(low_qf) == fit_score(high_qf) == 4.0


def test_fit_score_bounded_in_unit_range() -> None:
    # saturated non-quality dims all 5 -> 5.0 (the engine requirement_fit ceiling).
    rv = {"quality_floor": 5, "context_length": 5, "mutation_risk": 5}
    assert fit_score(rv) == 5.0
    # out-of-range values are excluded, never push the score above 5.
    assert fit_score({"context_length": 9}) == 0.0
    assert fit_score({"context_length": -1}) == 0.0


# ---------------------------------------------------------------- composite_rank_key


def test_composite_blend_zero_is_byte_identical_to_wsjf() -> None:
    # The golden guarantee: blend=0 short-circuits to wsjf_effective EXACTLY — not
    # wsjf + 0.0*fit (float wobble), and immune even to a NaN/inf fit_score.
    wsjf = 7.5
    assert composite_rank_key(wsjf, 3.0, blend=0.0) == wsjf
    # bit-identity, not just equality:
    assert composite_rank_key(wsjf, 3.0, blend=0.0).hex() == wsjf.hex()
    # NaN-safety: even a poisoned fit_score cannot perturb the blend=0 path.
    assert composite_rank_key(wsjf, float("nan"), blend=0.0) == wsjf
    assert math.isfinite(composite_rank_key(wsjf, float("nan"), blend=0.0))


def test_composite_blend_positive_adds_term() -> None:
    wsjf = 5.0
    # blend=1.0, fit=3.0 -> 5.0 + 3.0
    assert composite_rank_key(wsjf, 3.0, blend=1.0) == 8.0
    # a higher-fit task outranks a lower-fit task at equal wsjf.
    hi = composite_rank_key(wsjf, 4.0, blend=0.5)
    lo = composite_rank_key(wsjf, 1.0, blend=0.5)
    assert hi > lo


def test_composite_negative_blend_inverts() -> None:
    # a negative blend is a valid operator knob (prefer simpler tasks first); it must
    # flow through as plain arithmetic, not be clamped (the flag is the operator's dial).
    wsjf = 5.0
    assert composite_rank_key(wsjf, 3.0, blend=-1.0) == 2.0


# -------------------------------------------------- active-dim filter + honesty guard


def test_fit_score_focused_hot_outranks_diffuse_medium() -> None:
    # The >0 active-dim filter (mirror of the engine's _scored_requirement_dimensions): a
    # focused-hot task (one dim at 5, rest 0) must score HIGHER than a diffuse-medium task
    # (every dim at 3). Averaging the zero dims into the mean would invert this — the
    # adversarial review's demand-magnitude-inversion finding (0.71 vs 3.0) this fixes.
    non_qf = (
        "mutation_risk",
        "context_length",
        "verification_demand",
        "information_scope",
        "ambiguity_novelty",
        "composition_coupling",
        "governance_sensitivity",
    )
    focused = {"mutation_risk": 5, **{d: 0 for d in non_qf if d != "mutation_risk"}}
    diffuse = {d: 3 for d in non_qf}
    assert fit_score(focused) == 5.0  # one active dim at 5
    assert fit_score(diffuse) == 3.0  # seven active dims at 3
    assert fit_score(focused) > fit_score(diffuse)


def test_fit_score_zero_dim_is_inactive_not_averaged() -> None:
    # A dim scored 0 is inactive demand (the engine's >0 filter): excluded from BOTH the
    # numerator and the denominator — {context_length:4, mutation_risk:0} -> 4.0, not 2.0.
    assert fit_score({"context_length": 4, "mutation_risk": 0}) == 4.0


def test_fit_score_never_raises_on_hostile_mapping() -> None:
    # A hostile Mapping whose iteration raises must not propagate — fit_score is evaluated
    # inside the dispatch rank-key; a crash there breaks the scheduler (the docstring's
    # "NEVER raises" promise, made true by the try/except guard).
    from collections.abc import Mapping as _Mapping

    class _HostileMapping(_Mapping):
        def __getitem__(self, key):  # type: ignore[override]
            raise KeyError(key)

        def __iter__(self):  # type: ignore[override]
            raise RuntimeError("hostile iteration")

        def __len__(self) -> int:
            return 0

    assert fit_score(_HostileMapping()) == 0.0  # caught -> DARK, never raised
