"""Private operator-quality posterior read-model.

Aggregates operator-quality ratings recorded by
``shared.operator_quality_feedback`` into a Bayesian posterior over operator
satisfaction, partitioned by programme / condition / source surface / rating
axis. Output is private-by-default and cannot authorize public, monetized,
or research-validity claims; it feeds the dossier value-braid adapter as
private selection/specification priors only.

cc-task: ``operator-quality-posterior-read-model``.
Spec: ``hapax-research/specs/2026-05-01-operator-predictive-dossier-productization-spine.md``.
Write-side companion: ``shared/operator_quality_feedback.py``.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.operator_quality_feedback import (
    OperatorQualityRatingEvent,
    iter_operator_quality_ratings,
)

log = logging.getLogger(__name__)

DEFAULT_HALF_LIFE_DAYS: float = 14.0
DEFAULT_MIN_SAMPLES: int = 3
DEFAULT_STALE_THRESHOLD_DAYS: float = 30.0
DEFAULT_CONTRADICTION_RATE: float = 0.4

GROUPABLE_FIELDS: tuple[str, ...] = (
    "programme_id",
    "condition_id",
    "source_surface",
    "rating_axis",
)
DEFAULT_GROUP_BY: tuple[str, ...] = GROUPABLE_FIELDS

NEGATIVE_CONSTRAINTS: tuple[str, ...] = (
    "private_by_default",
    "no_public_authorization",
    "no_monetization_authorization",
    "no_research_validity_authorization",
    "no_raw_emission_text",
    "no_raw_note_text",
    "no_raw_evidence_ref_text",
)


class UncertaintyReason(StrEnum):
    NO_OBSERVATIONS = "no_observations"
    LOW_SUPPORT = "low_support"
    STALE_EVIDENCE = "stale_evidence"
    CONFLICTING_EVIDENCE = "conflicting_evidence"


class ConditionKey(BaseModel):
    """Aggregation key for a posterior cell.

    A field set to ``None`` means the dimension was aggregated across (i.e.
    not part of the projection), not that the underlying event lacked the
    field.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    programme_id: str | None = None
    condition_id: str | None = None
    source_surface: str | None = None
    rating_axis: str | None = None


class PosteriorRow(BaseModel):
    """One Bayesian posterior cell over operator-quality ratings.

    ``aggregate_score`` lives on ``[0, 1]``; ``aggregate_score_1_5`` is the
    same posterior mean projected back onto the operator's 1-5 scale.
    ``confidence`` is ``1 - posterior_std / max_std_uniform`` clamped to
    ``[0, 1]`` and is intentionally distinct from ``aggregate_score``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: ConditionKey
    aggregate_score: float = Field(..., ge=0.0, le=1.0)
    aggregate_score_1_5: float = Field(..., ge=1.0, le=5.0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    posterior_alpha: float = Field(..., gt=0.0)
    posterior_beta: float = Field(..., gt=0.0)
    posterior_std: float = Field(..., ge=0.0)
    sample_count: int = Field(..., ge=1)
    effective_sample_size: float = Field(..., ge=0.0)
    correction_count: int = Field(..., ge=0)
    support_count: int = Field(..., ge=0)
    neutral_count: int = Field(..., ge=0)
    contradiction_rate: float = Field(..., ge=0.0, le=1.0)
    last_seen_at: datetime
    oldest_seen_at: datetime
    days_since_last: float = Field(..., ge=0.0)
    decay_half_life_days: float = Field(..., gt=0.0)
    distinct_run_ids: int = Field(..., ge=0)
    distinct_emission_refs: int = Field(..., ge=0)
    evidence_ref_count: int = Field(..., ge=0)
    uncertainty_reason: UncertaintyReason | None = None
    mode_ceiling: Literal["private"] = "private"
    claim_authority: Literal["provisional"] = "provisional"
    privacy_label: Literal["private"] = "private"


class InsufficientEvidenceRow(BaseModel):
    """Explicit insufficient-evidence marker for empty or sparse cells."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: ConditionKey
    sample_count: int = Field(..., ge=0)
    uncertainty_reason: UncertaintyReason
    last_seen_at: datetime | None = None
    notes: str
    mode_ceiling: Literal["private"] = "private"
    privacy_label: Literal["private"] = "private"


class ContradictionRow(BaseModel):
    """Surfaces correction signals without overwriting earlier evidence.

    Generated when the same key has both low (1-2) and high (4-5) ratings.
    The posterior in :class:`PosteriorRow` already incorporates all events
    with naturally widened variance; this row is the auditable record that
    earlier evidence was kept rather than overwritten.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: ConditionKey
    low_count: int = Field(..., ge=1)
    high_count: int = Field(..., ge=1)
    earliest_low_at: datetime
    earliest_high_at: datetime
    latest_low_at: datetime
    latest_high_at: datetime
    later_camp: Literal["low", "high", "tied"]
    mode_ceiling: Literal["private"] = "private"
    privacy_label: Literal["private"] = "private"


class OperatorQualityPosteriorReadModel(BaseModel):
    """Top-level private read-model.

    Cannot authorize public-facing, monetized, or research-validity claims;
    consumers are limited to private selection/specification priors.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    generated_at: datetime
    rows: tuple[PosteriorRow, ...] = Field(default_factory=tuple)
    insufficient_evidence: tuple[InsufficientEvidenceRow, ...] = Field(default_factory=tuple)
    contradictions: tuple[ContradictionRow, ...] = Field(default_factory=tuple)
    total_events: int = Field(..., ge=0)
    decay_half_life_days: float = Field(..., gt=0.0)
    min_samples: int = Field(..., ge=1)
    stale_threshold_days: float = Field(..., gt=0.0)
    contradiction_rate_threshold: float = Field(..., ge=0.0, le=1.0)
    group_by: tuple[str, ...]
    mode_ceiling: Literal["private"] = "private"
    claim_authority: Literal["provisional"] = "provisional"
    privacy_label: Literal["private"] = "private"
    negative_constraints: tuple[str, ...] = NEGATIVE_CONSTRAINTS

    def cells_for_programme(self, programme_id: str) -> tuple[PosteriorRow, ...]:
        return tuple(r for r in self.rows if r.key.programme_id == programme_id)

    def cells_for_axis(self, rating_axis: str) -> tuple[PosteriorRow, ...]:
        return tuple(r for r in self.rows if r.key.rating_axis == rating_axis)

    def private_summary_lines(self, *, max_rows: int = 6) -> tuple[str, ...]:
        """Short prompt-visible private summary lines.

        Excludes raw notes, raw evidence refs, and raw emission refs by
        construction. Each line carries aggregation key + score + confidence
        + sample count + reason.
        """

        if not self.rows:
            if not self.insufficient_evidence:
                return ("operator-quality posterior: no data",)
            head = self.insufficient_evidence[0]
            return (
                "operator-quality posterior: "
                f"{head.uncertainty_reason.value} "
                f"(events={head.sample_count})",
            )

        ranked = sorted(self.rows, key=lambda r: (-r.confidence, -r.sample_count))
        return tuple(_summarize_row(row) for row in ranked[:max_rows])


def aggregate_operator_quality_posterior(
    events: Iterable[OperatorQualityRatingEvent] | None = None,
    *,
    path: Path | None = None,
    now: datetime | None = None,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    stale_threshold_days: float = DEFAULT_STALE_THRESHOLD_DAYS,
    contradiction_rate_threshold: float = DEFAULT_CONTRADICTION_RATE,
    group_by: Sequence[str] = DEFAULT_GROUP_BY,
) -> OperatorQualityPosteriorReadModel:
    """Aggregate operator-quality events into a private posterior read-model.

    With ``events=None``, ratings are read from the JSONL sink at ``path``
    (or :func:`shared.operator_quality_feedback.quality_feedback_path` if
    ``path`` is also ``None``).
    """

    group_by_t = tuple(group_by)
    if not group_by_t:
        raise ValueError("group_by must contain at least one field")
    invalid = [f for f in group_by_t if f not in GROUPABLE_FIELDS]
    if invalid:
        raise ValueError(
            f"group_by contains non-groupable fields: {invalid}; allowed: {list(GROUPABLE_FIELDS)}"
        )

    if half_life_days <= 0:
        raise ValueError("half_life_days must be positive")
    if min_samples < 1:
        raise ValueError("min_samples must be >= 1")
    if stale_threshold_days <= 0:
        raise ValueError("stale_threshold_days must be positive")
    if not 0.0 <= contradiction_rate_threshold <= 1.0:
        raise ValueError("contradiction_rate_threshold must be in [0, 1]")

    if events is None:
        events_iter: Iterable[OperatorQualityRatingEvent] = iter_operator_quality_ratings(path=path)
    else:
        events_iter = events

    materialized = list(events_iter)
    now_utc = now if now is not None else datetime.now(UTC)
    if now_utc.tzinfo is None or now_utc.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    now_utc = now_utc.astimezone(UTC)

    if not materialized:
        return OperatorQualityPosteriorReadModel(
            generated_at=now_utc,
            rows=(),
            insufficient_evidence=(
                InsufficientEvidenceRow(
                    key=ConditionKey(),
                    sample_count=0,
                    uncertainty_reason=UncertaintyReason.NO_OBSERVATIONS,
                    last_seen_at=None,
                    notes="no operator-quality ratings recorded yet",
                ),
            ),
            contradictions=(),
            total_events=0,
            decay_half_life_days=half_life_days,
            min_samples=min_samples,
            stale_threshold_days=stale_threshold_days,
            contradiction_rate_threshold=contradiction_rate_threshold,
            group_by=group_by_t,
        )

    buckets: dict[tuple[str | None, ...], list[OperatorQualityRatingEvent]] = {}
    for event in materialized:
        key_tuple = tuple(_extract_field(event, field) for field in group_by_t)
        buckets.setdefault(key_tuple, []).append(event)

    rows: list[PosteriorRow] = []
    insufficient: list[InsufficientEvidenceRow] = []
    contradictions: list[ContradictionRow] = []

    for key_tuple, key_events in buckets.items():
        condition_key = _build_condition_key(group_by_t, key_tuple)
        sample_count = len(key_events)

        if sample_count < min_samples:
            insufficient.append(
                InsufficientEvidenceRow(
                    key=condition_key,
                    sample_count=sample_count,
                    uncertainty_reason=UncertaintyReason.LOW_SUPPORT,
                    last_seen_at=max(e.occurred_at for e in key_events),
                    notes=(
                        f"sample_count={sample_count} < min_samples={min_samples}; "
                        "treat as candidate evidence only"
                    ),
                )
            )
            contradiction = _maybe_build_contradiction(condition_key, key_events)
            if contradiction is not None:
                contradictions.append(contradiction)
            continue

        rows.append(
            _build_posterior_row(
                condition_key,
                key_events,
                now_utc=now_utc,
                half_life_days=half_life_days,
                stale_threshold_days=stale_threshold_days,
                contradiction_rate_threshold=contradiction_rate_threshold,
            )
        )
        contradiction = _maybe_build_contradiction(condition_key, key_events)
        if contradiction is not None:
            contradictions.append(contradiction)

    rows.sort(key=_row_sort_key)
    insufficient.sort(key=lambda r: _key_sort_key(r.key))
    contradictions.sort(key=lambda r: _key_sort_key(r.key))

    return OperatorQualityPosteriorReadModel(
        generated_at=now_utc,
        rows=tuple(rows),
        insufficient_evidence=tuple(insufficient),
        contradictions=tuple(contradictions),
        total_events=len(materialized),
        decay_half_life_days=half_life_days,
        min_samples=min_samples,
        stale_threshold_days=stale_threshold_days,
        contradiction_rate_threshold=contradiction_rate_threshold,
        group_by=group_by_t,
    )


def _extract_field(event: OperatorQualityRatingEvent, field: str) -> str | None:
    value = getattr(event, field, None)
    if value is None:
        return None
    return str(value)


def _build_condition_key(
    group_by: tuple[str, ...],
    key_tuple: tuple[str | None, ...],
) -> ConditionKey:
    fields: dict[str, str | None] = dict.fromkeys(GROUPABLE_FIELDS)
    for field, value in zip(group_by, key_tuple, strict=True):
        fields[field] = value
    return ConditionKey(**fields)


def _build_posterior_row(
    condition_key: ConditionKey,
    key_events: Sequence[OperatorQualityRatingEvent],
    *,
    now_utc: datetime,
    half_life_days: float,
    stale_threshold_days: float,
    contradiction_rate_threshold: float,
) -> PosteriorRow:
    posterior_alpha = 1.0
    posterior_beta = 1.0
    effective_sample_size = 0.0
    correction_count = 0
    support_count = 0
    neutral_count = 0
    run_ids: set[str] = set()
    emission_refs: set[str] = set()
    evidence_ref_total = 0

    for event in key_events:
        quality = (event.rating - 1) / 4.0
        age_days = max(0.0, (now_utc - event.occurred_at).total_seconds() / 86400.0)
        weight = 0.5 ** (age_days / half_life_days)
        posterior_alpha += weight * quality
        posterior_beta += weight * (1.0 - quality)
        effective_sample_size += weight

        if event.rating <= 2:
            correction_count += 1
        elif event.rating >= 4:
            support_count += 1
        else:
            neutral_count += 1

        if event.run_id is not None:
            run_ids.add(event.run_id)
        if event.emission_ref is not None:
            emission_refs.add(event.emission_ref)
        evidence_ref_total += len(event.evidence_refs)

    a = posterior_alpha
    b = posterior_beta
    mean = a / (a + b)
    variance = (a * b) / ((a + b) ** 2 * (a + b + 1.0))
    std = math.sqrt(variance)
    max_std_uniform = math.sqrt(1.0 / 12.0)
    confidence = max(0.0, min(1.0, 1.0 - std / max_std_uniform))

    last_seen_at = max(e.occurred_at for e in key_events)
    oldest_seen_at = min(e.occurred_at for e in key_events)
    days_since_last = max(0.0, (now_utc - last_seen_at).total_seconds() / 86400.0)
    sample_count = len(key_events)
    contradiction_rate = (
        min(correction_count, support_count) / sample_count if sample_count > 0 else 0.0
    )

    if contradiction_rate >= contradiction_rate_threshold:
        uncertainty_reason: UncertaintyReason | None = UncertaintyReason.CONFLICTING_EVIDENCE
    elif days_since_last > stale_threshold_days:
        uncertainty_reason = UncertaintyReason.STALE_EVIDENCE
    else:
        uncertainty_reason = None

    return PosteriorRow(
        key=condition_key,
        aggregate_score=mean,
        aggregate_score_1_5=1.0 + 4.0 * mean,
        confidence=confidence,
        posterior_alpha=a,
        posterior_beta=b,
        posterior_std=std,
        sample_count=sample_count,
        effective_sample_size=effective_sample_size,
        correction_count=correction_count,
        support_count=support_count,
        neutral_count=neutral_count,
        contradiction_rate=contradiction_rate,
        last_seen_at=last_seen_at,
        oldest_seen_at=oldest_seen_at,
        days_since_last=days_since_last,
        decay_half_life_days=half_life_days,
        distinct_run_ids=len(run_ids),
        distinct_emission_refs=len(emission_refs),
        evidence_ref_count=evidence_ref_total,
        uncertainty_reason=uncertainty_reason,
    )


def _maybe_build_contradiction(
    key: ConditionKey,
    events: Sequence[OperatorQualityRatingEvent],
) -> ContradictionRow | None:
    low = [e for e in events if e.rating <= 2]
    high = [e for e in events if e.rating >= 4]
    if not low or not high:
        return None

    latest_low = max(e.occurred_at for e in low)
    latest_high = max(e.occurred_at for e in high)
    if latest_low > latest_high:
        later_camp: Literal["low", "high", "tied"] = "low"
    elif latest_high > latest_low:
        later_camp = "high"
    else:
        later_camp = "tied"

    return ContradictionRow(
        key=key,
        low_count=len(low),
        high_count=len(high),
        earliest_low_at=min(e.occurred_at for e in low),
        earliest_high_at=min(e.occurred_at for e in high),
        latest_low_at=latest_low,
        latest_high_at=latest_high,
        later_camp=later_camp,
    )


def _key_sort_key(key: ConditionKey) -> tuple[str, str, str, str]:
    return (
        key.programme_id or "",
        key.condition_id or "",
        key.source_surface or "",
        key.rating_axis or "",
    )


def _row_sort_key(row: PosteriorRow) -> tuple[str, str, str, str]:
    return _key_sort_key(row.key)


def _summarize_row(row: PosteriorRow) -> str:
    parts = [
        f"programme={row.key.programme_id or '-'}",
        f"condition={row.key.condition_id or '-'}",
        f"axis={row.key.rating_axis or '-'}",
        f"surface={row.key.source_surface or '-'}",
        f"score_1_5={row.aggregate_score_1_5:.2f}",
        f"confidence={row.confidence:.2f}",
        f"n={row.sample_count}",
    ]
    if row.uncertainty_reason is not None:
        parts.append(f"reason={row.uncertainty_reason.value}")
    return " ".join(parts)
