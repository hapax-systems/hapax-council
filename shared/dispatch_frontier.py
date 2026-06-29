"""Dispatch frontier — real Pareto dominance over the CCEF cell vector (STEP 2).

Replaces the scalar-argmax selectors (the forbidden scalar-collapse): priority is the
Pareto-non-dominated (task x capability) CELL over the measured economic vector, not a number.

Two pure functions, no weights, no aggregate:
  - ``dominates(a, b)``: Pareto dominance over the shared PRESENT dimensions.
  - ``non_dominated_set(cells)``: the frontier — cells dominated by no other.

value_status-HONESTY (the core invariant): a dimension ABSENT on either cell (missing key or a
None value) is EXCLUDED from the comparison — never imputed 0 — so an absent term can neither
create nor block a domination. A pair with no shared present dimension is INCOMPARABLE (neither
dominates), and both survive on the frontier (no scalar tie-break, no fabricated rank).

Additive + inert: nothing calls this yet. Shadow-wiring is STEP 9, per-class cutover STEP 10.
Design: agentic-native dispatch CCEF/H STEP 2.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

Direction = Literal["max", "min"]

#: The CCEF cell-vector axes and their optimization direction. "max" = higher is better
#: (value posterior, capability fit, DAG unlock); "min" = lower is better (cost, congestion).
FRONTIER_AXES: Mapping[str, Direction] = {
    "v_hat": "max",
    "fit": "max",
    "u": "max",
    "c_hat": "min",
    "mu": "min",
}

Cell = Mapping[str, Any]


def _present(cell: Cell, dim: str) -> bool:
    """A dimension is present iff the key exists with a non-None value (else: absent)."""
    return dim in cell and cell[dim] is not None


def dominates(a: Cell, b: Cell, *, axes: Mapping[str, Direction] = FRONTIER_AXES) -> bool:
    """True iff ``a`` Pareto-dominates ``b`` over the shared PRESENT axes.

    Restricting to axes present (non-None) on BOTH cells, ``a`` dominates ``b`` when it is
    better-or-equal on every such axis and strictly better on at least one (direction per
    ``axes``). With no shared present axis the pair is INCOMPARABLE — not a domination. Absent
    dimensions are never imputed; they drop out of the comparison entirely.
    """
    shared = [d for d in axes if _present(a, d) and _present(b, d)]
    if not shared:
        return False
    strictly_better = False
    for d in shared:
        av, bv = a[d], b[d]
        direction = axes[d]
        if direction == "max":
            if av < bv:
                return False
            if av > bv:
                strictly_better = True
        elif direction == "min":  # lower is better
            if av > bv:
                return False
            if av < bv:
                strictly_better = True
        else:  # fail closed: an unknown direction must not silently default to min
            raise ValueError(f"unknown axis direction {direction!r} for axis {d!r}")
    return strictly_better


def non_dominated_set(
    cells: Sequence[Cell], *, axes: Mapping[str, Direction] = FRONTIER_AXES
) -> list[Cell]:
    """The Pareto frontier: the cells dominated by no OTHER cell (input order preserved)."""
    return [
        cell
        for i, cell in enumerate(cells)
        if not any(dominates(other, cell, axes=axes) for j, other in enumerate(cells) if i != j)
    ]
