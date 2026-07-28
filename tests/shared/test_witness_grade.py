"""Tests for the canonical witness-grade ordering.

The regression that matters most here is ``test_every_member_of_both_enums_is_ranked``:
if a new ``WitnessPolicy`` member is added to either enum and not given a rank, it
silently becomes STRICTEST. That is the correct fail-closed direction, but it is a
silent behaviour change and must be caught at test time rather than discovered when
a grade stops outranking anything.
"""

from __future__ import annotations

import pytest

from shared.capability_outcome import WitnessPolicy as CapabilityWitnessPolicy
from shared.witness_grade import (
    STRICTEST_RANK,
    WITNESS_RANK,
    is_doctrine_graded,
    strictest_witness,
    witness_rank,
)
from shared.world_surface_health import WitnessPolicy as WorldSurfaceWitnessPolicy

DOCTRINE_LADDER_STRONGEST_FIRST = [
    "witnessed",
    "selected_only",
    "commanded_only",
    "inferred",
    "stale",
]


def test_doctrine_ladder_is_strictly_descending() -> None:
    ranks = [witness_rank(name) for name in DOCTRINE_LADDER_STRONGEST_FIRST]
    assert ranks == sorted(ranks, reverse=True)
    assert len(set(ranks)) == len(ranks), "doctrine members must not share a rank"


def test_every_member_of_both_enums_is_ranked() -> None:
    """No enum member may fall through to the unknown/strictest default."""
    unranked = [
        f"{enum.__module__}.{member.name}"
        for enum in (CapabilityWitnessPolicy, WorldSurfaceWitnessPolicy)
        for member in enum
        if member.value not in WITNESS_RANK
    ]
    assert not unranked, f"WitnessPolicy members missing from WITNESS_RANK: {unranked}"


def test_ranks_agree_across_the_two_divergent_enums() -> None:
    """The whole point: a grade means the same thing whichever enum produced it."""
    shared_values = {m.value for m in CapabilityWitnessPolicy} & {
        m.value for m in WorldSurfaceWitnessPolicy
    }
    assert shared_values, "expected the two enums to overlap"
    for value in shared_values:
        left = CapabilityWitnessPolicy(value)
        right = WorldSurfaceWitnessPolicy(value)
        assert witness_rank(left) == witness_rank(right) == witness_rank(value)


@pytest.mark.parametrize(
    "unknown",
    [None, "", "not_a_policy", 0, object()],
)
def test_unknown_grades_rank_strictest(unknown: object) -> None:
    """An unreadable grade is the weakest grade, never the strongest."""
    assert witness_rank(unknown) == STRICTEST_RANK


def test_unknown_never_outranks_a_known_grade() -> None:
    for value in WITNESS_RANK:
        if WITNESS_RANK[value] > STRICTEST_RANK:
            assert witness_rank("garbage") < witness_rank(value)


def test_ungraded_members_never_outrank_doctrine_members() -> None:
    graded = [v for v in WITNESS_RANK if is_doctrine_graded(v)]
    ungraded = [v for v in WITNESS_RANK if not is_doctrine_graded(v)]
    assert graded and ungraded
    assert max(WITNESS_RANK[v] for v in ungraded) < min(WITNESS_RANK[v] for v in graded)


def test_strictest_witness_returns_the_weaker_grade() -> None:
    assert strictest_witness("witnessed", "stale") == "stale"
    assert strictest_witness("stale", "witnessed") == "stale"
    assert strictest_witness("inferred", "commanded_only") == "inferred"
    assert strictest_witness("witnessed", "unknown_thing") == "unknown_thing"


def test_strictest_witness_is_commutative_in_rank() -> None:
    values = list(WITNESS_RANK) + ["garbage"]
    for left in values:
        for right in values:
            assert witness_rank(strictest_witness(left, right)) == witness_rank(
                strictest_witness(right, left)
            )


def test_strictest_witness_ties_resolve_left() -> None:
    """Matches the _strictest_authority / _strictest_freshness sibling idiom."""
    assert strictest_witness("absent", "missing") == "absent"


def test_strictest_witness_preserves_enum_identity() -> None:
    weaker = strictest_witness(CapabilityWitnessPolicy.WITNESSED, CapabilityWitnessPolicy.STALE)
    assert weaker is CapabilityWitnessPolicy.STALE


def test_is_doctrine_graded_marks_only_the_ratified_five() -> None:
    assert {v for v in WITNESS_RANK if is_doctrine_graded(v)} == set(
        DOCTRINE_LADDER_STRONGEST_FIRST
    )
    assert not is_doctrine_graded("fixture_only")
    assert not is_doctrine_graded(None)
