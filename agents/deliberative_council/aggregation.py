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


def family_correlation_penalty(results, families, threshold=0.90):
    import logging

    _log = logging.getLogger(__name__)
    weights = {r.model_alias: 1.0 for r in results}
    family_groups = {}
    for alias, family in families.items():
        family_groups.setdefault(family, []).append(alias)
    for members in family_groups.values():
        if len(members) < 2:
            continue
        participating = [r for r in results if r.model_alias in members]
        if len(participating) < 2:
            continue
        r1, r2 = participating[0], participating[1]
        shared = set(r1.scores.keys()) & set(r2.scores.keys())
        if not shared:
            continue
        diffs = [abs(r1.scores[a] - r2.scores[a]) for a in shared]
        similarity = 1.0 - (sum(diffs) / len(diffs) / 4.0)
        if similarity >= threshold:
            _log.info(
                "Family penalty: %s/%s sim=%.2f, halving",
                r1.model_alias,
                r2.model_alias,
                similarity,
            )
            weights[r1.model_alias] *= 0.5
            weights[r2.model_alias] *= 0.5
    return weights


def aggregate_scores(
    results: list[PhaseOneResult],
    contested_threshold: float = 2.0,
    weights: dict[str, float] | None = None,
) -> dict[str, AxisAggregate]:
    axes: set[str] = set()
    for r in results:
        axes.update(r.scores.keys())

    output: dict[str, AxisAggregate] = {}
    for axis in sorted(axes):
        values = [r.scores[axis] for r in results if axis in r.scores]
        iqr = compute_iqr(values)
        band = compute_confidence_band(values)

        if iqr <= 1.0:
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
