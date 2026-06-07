from __future__ import annotations

import statistics
from dataclasses import dataclass

from .models import ConvergenceStatus, PhaseOneResult


def compute_iqr(values: list[int | float]) -> float:
    if len(values) <= 1:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    return float(sorted_vals[(3 * n) // 4] - sorted_vals[n // 4])


def should_shortcircuit(results: list[PhaseOneResult], threshold: float = 1.0) -> bool:
    axes: set[str] = set()
    for r in results:
        axes.update(r.scores.keys())
    return all(
        compute_iqr([r.scores[a] for r in results if a in r.scores]) <= threshold for a in axes
    )


def compute_confidence_band(values: list[int]) -> tuple[int, int]:
    if not values:
        return (0, 0)
    return (min(values), max(values))


@dataclass(frozen=True)
class AxisAggregate:
    axis: str
    score: int | None
    status: ConvergenceStatus
    iqr: float
    values: tuple[int, ...]
    confidence_band: tuple[int, int]


def aggregate_scores(
    results: list[PhaseOneResult],
    contested_threshold: float = 2.0,
    weights: dict[str, float] | None = None,
    min_values: int = 2,
) -> dict[str, AxisAggregate]:
    """Aggregate per-axis scores into convergence verdicts.

    ``min_values`` is the per-axis coverage floor: an axis scored by FEWER than
    ``min_values`` independent members cannot certify convergence. ``compute_iqr``
    of a single value is 0.0, which previously read as CONVERGED — a lone
    survivor masquerading as consensus. Such an under-covered axis is REFUSED,
    never CONVERGED (cc-task cctv-council-perfect-health-faillloud-convergence).
    """
    axes: set[str] = set()
    for r in results:
        axes.update(r.scores.keys())

    output: dict[str, AxisAggregate] = {}
    for axis in sorted(axes):
        values = [r.scores[axis] for r in results if axis in r.scores]
        iqr = compute_iqr(values)
        band = compute_confidence_band(values)

        if len(values) < min_values:
            # Insufficient independent coverage — a lone (or too-thin) survivor
            # is NOT consensus. Refuse the axis loudly rather than certify it.
            status = ConvergenceStatus.REFUSED
            score = None
        elif iqr <= 1.0:
            status = ConvergenceStatus.CONVERGED
            score = round(statistics.median(values))
        elif iqr <= contested_threshold:
            status = ConvergenceStatus.CONTESTED
            score = round(statistics.median(values))
        else:
            status = ConvergenceStatus.HUNG
            score = None

        output[axis] = AxisAggregate(
            axis=axis,
            score=score,
            status=status,
            iqr=iqr,
            values=tuple(values),
            confidence_band=band,
        )
    return output
