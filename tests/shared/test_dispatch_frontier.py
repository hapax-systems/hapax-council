"""Tests for the dispatch frontier — real Pareto dominance over the CCEF cell vector.

CCEF/H STEP 2: priority is the Pareto-non-dominated (task x capability) cell, not a scalar.
These cover real dominance (replacing the scalar argmax), mixed max/min axes, and the
value_status-honesty invariant: an ABSENT dimension is excluded from the comparison, never
imputed 0 — so it can neither create nor block domination.
"""

from __future__ import annotations

from shared.dispatch_frontier import dominates, non_dominated_set


def test_dominates_all_max_axes() -> None:
    a = {"v_hat": 0.9, "fit": 4, "u": 3}
    b = {"v_hat": 0.5, "fit": 4, "u": 2}
    assert dominates(a, b)  # >= on all shared, strictly > on v_hat and u
    assert not dominates(b, a)


def test_equal_is_not_domination() -> None:
    a = {"v_hat": 0.5, "fit": 3}
    b = {"v_hat": 0.5, "fit": 3}
    assert not dominates(a, b)
    assert not dominates(b, a)


def test_lower_is_better_axes() -> None:
    # c_hat (cost) and mu (congestion) are minimized
    a = {"c_hat": 1.0, "mu": 0.2}
    b = {"c_hat": 2.0, "mu": 0.2}
    assert dominates(a, b)  # cheaper, equal congestion
    assert not dominates(b, a)


def test_mixed_tradeoff_is_incomparable() -> None:
    a = {"v_hat": 0.9, "c_hat": 2.0}  # more value, more cost
    b = {"v_hat": 0.5, "c_hat": 1.0}  # less value, less cost
    assert not dominates(a, b)
    assert not dominates(b, a)


def test_absent_dimension_excluded_not_imputed() -> None:
    # b lacks c_hat; only the shared present dim (v_hat) is compared.
    a = {"v_hat": 0.9, "c_hat": 5.0}
    b = {"v_hat": 0.5}
    # a wins on v_hat; a's bad (high) c_hat is NOT counted against it (absent on b -> excluded)
    assert dominates(a, b)
    assert not dominates(b, a)


def test_absent_value_does_not_block_or_forge_domination() -> None:
    # None is treated as absent, identically to a missing key
    a = {"v_hat": 0.9, "c_hat": None}
    b = {"v_hat": 0.5, "c_hat": 1.0}
    assert dominates(a, b)  # only v_hat shared+present


def test_no_shared_dimension_is_incomparable() -> None:
    a = {"v_hat": 0.9}
    b = {"c_hat": 1.0}
    assert not dominates(a, b)
    assert not dominates(b, a)


def test_non_dominated_set_keeps_frontier_and_incomparable() -> None:
    dominant = {"id": "A", "v_hat": 0.9, "c_hat": 1.0}
    dominated = {"id": "B", "v_hat": 0.5, "c_hat": 2.0}  # worse on both -> dropped
    tradeoff = {"id": "C", "v_hat": 0.3, "c_hat": 0.5}  # incomparable with A
    front = non_dominated_set([dominant, dominated, tradeoff])
    assert {c["id"] for c in front} == {"A", "C"}


def test_non_dominated_set_empty_and_singleton() -> None:
    assert non_dominated_set([]) == []
    one = {"v_hat": 0.5}
    assert non_dominated_set([one]) == [one]
