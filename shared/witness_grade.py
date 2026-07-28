"""Canonical ordering and strictest-meet for witness policy grades.

WHY THIS EXISTS
---------------
The estate's doctrine states an ordered provenance ladder:

    witnessed > selected_only > commanded_only > inferred > stale

A 2026-07-28 audit found the ladder was executed as a 1-bit predicate: two
divergent ``WitnessPolicy`` enums exist --
``shared.capability_outcome.WitnessPolicy`` (9 members, has ``STALE`` and
``MISSING``) and ``shared.world_surface_health.WitnessPolicy`` (7 members, has
``ABSENT`` and ``CANDIDATE``) -- neither imports the other, and no comparator
for the ordering exists anywhere in repository history. Callers could therefore
test membership but never ask *which of two grades is weaker*, which is the
only question the ladder is for.

This module supplies that comparator WITHOUT changing either enum's type, so it
is purely additive and cannot break an existing caller. Both enums are
``StrEnum``, so their values are comparable across the split; this ranks on the
string value and spans the union of both vocabularies. When the two enums are
eventually unified, this rank map is the unification point.

FAIL-CLOSED ON UNKNOWN
----------------------
``witness_rank`` maps an unrecognised value to the STRICTEST rank, not the most
permissive. This is deliberate and is the central property: the same audit found
six sites across four primitives encoding *absence as a benign value*, and an
unknown provenance grade silently outranking a known-weak one would be that
defect reproduced here. An unreadable grade is the weakest grade, never the
strongest.

RATIFICATION STATUS
-------------------
Only the five doctrine-named members have a ratified relative order. The other
six (``absent``, ``missing``, ``fixture_only``, ``candidate``,
``legacy_public_event``, ``public_event_adapter``) are placed CONSERVATIVELY --
all strictly below every doctrine-graded member -- so that an ungraded policy can
never outrank a graded one. Those six placements are PROVISIONAL and unratified;
they are safe in the sense that they can only under-credit evidence, never
over-credit it. Do not cite their relative order as doctrine.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

__all__ = [
    "STRICTEST_RANK",
    "WITNESS_RANK",
    "is_doctrine_graded",
    "strictest_witness",
    "witness_rank",
]

# Ascending strength. 0 is the strictest (weakest evidence, most constraining).
#
# Ranks 5-9 are the doctrine ladder and are ratified.
# Ranks 0-3 are provisional; see RATIFICATION STATUS above.
WITNESS_RANK: Final[dict[str, int]] = {
    # --- provisional, all below the doctrine ladder ---
    "absent": 0,  # no evidence exists
    "missing": 0,  # no evidence exists (sibling vocabulary for the same idea)
    "fixture_only": 1,  # synthetic; not evidence about the world at all
    "candidate": 2,  # proposed, not established
    "legacy_public_event": 3,  # legacy adapter path, provenance not reconstructible
    "public_event_adapter": 3,  # adapter-derived, provenance not reconstructible
    # --- the ratified doctrine ladder ---
    "stale": 5,  # was evidence; freshness expired
    "inferred": 6,
    "commanded_only": 7,
    "selected_only": 8,
    "witnessed": 9,
}

#: Rank assigned to any value not present in :data:`WITNESS_RANK`.
STRICTEST_RANK: Final[int] = 0

#: The five members whose relative order is fixed by doctrine.
_DOCTRINE_GRADED: Final[frozenset[str]] = frozenset(
    {"witnessed", "selected_only", "commanded_only", "inferred", "stale"}
)


def _value(policy: object) -> str:
    """Normalise an enum member, bare string, or arbitrary object to its value."""
    if isinstance(policy, StrEnum):
        return str(policy.value)
    if isinstance(policy, str):
        return policy
    # An object that is neither -- e.g. None from an absent field. Deliberately
    # does not raise: the caller is asking "how much do I trust this", and the
    # answer for an unreadable grade is "not at all", not an exception that a
    # caller may swallow into a permissive default.
    return ""


def witness_rank(policy: object) -> int:
    """Return the ordinal strength of ``policy``; higher means stronger evidence.

    Accepts either ``WitnessPolicy`` enum (from either module), a bare string, or
    an unreadable value. Anything unrecognised -- including ``None`` -- returns
    :data:`STRICTEST_RANK`, so an unknown grade can never outrank a known one.
    """
    return WITNESS_RANK.get(_value(policy), STRICTEST_RANK)


def strictest_witness[T](left: T, right: T) -> T:
    """Return whichever of ``left`` / ``right`` carries the WEAKER evidence.

    This is the meet over the provenance lattice, matching the existing
    ``_strictest_authority`` / ``_strictest_freshness`` idiom in
    ``shared/scrim_wcs_claim_posture.py``. Combining two grades yields the more
    constraining one: witnessed + stale = stale, never witnessed.

    Ties resolve to ``left``, matching the sibling helpers.
    """
    return left if witness_rank(left) <= witness_rank(right) else right


def is_doctrine_graded(policy: object) -> bool:
    """True if ``policy`` is one of the five members with a ratified order.

    Callers that need to assert a doctrine-backed comparison should gate on this
    rather than assuming every member's rank is authoritative.
    """
    return _value(policy) in _DOCTRINE_GRADED
