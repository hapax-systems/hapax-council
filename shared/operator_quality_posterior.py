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

import hashlib
import json
import logging
import math
import os
from collections.abc import Iterable, Mapping, Sequence
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


# ---------------------------------------------------------------------------
# Derived quality bars — wire this posterior to the segment-prep gate bars,
# replacing the magic constants (cc-task
# ``segment-prep-calibration-posterior-wiring-20260607``).
#
# Honesty contract:
#   * Uncertainty-aware and loud + advisory: below ``min_samples`` quorum, or on
#     conflicting ("hung") evidence, the operator-derived value is NEVER silently
#     enforced. The seed default holds and the bar is loudly marked advisory.
#   * One-way ratchet: an operative value can only *tighten* a bar above its seed
#     default, never relax it. Wiring removes magic constants; it does not lower
#     any bar.
#   * The exact posterior -> cutoff calibration is intentionally conservative
#     (project the posterior mean onto the bar scale, ratchet against the seed).
#     A richer calibration belongs to the parent spec; this scaffold is safe
#     under an empty corpus (today) because it cannot relax or spuriously fire.
# ---------------------------------------------------------------------------

DERIVED_QUALITY_BARS_VERSION = 1
DERIVED_QUALITY_BARS_PATH_ENV = "HAPAX_DERIVED_QUALITY_BARS_PATH"
HAPAX_STATE_ENV = "HAPAX_STATE"

# Decay reference for an empty corpus: a fixed instant so derivation stays
# deterministic (no wall-clock) when there is nothing to date it against.
_EMPTY_CORPUS_REFERENCE = datetime(2026, 1, 1, tzinfo=UTC)
_UNIFORM_STD = math.sqrt(1.0 / 12.0)
# An axis "passes" when the posterior mean sits above the neutral midpoint of
# the 1-5 scale (rating 3 -> 0.5 on the [0, 1] quality scale).
_AXIS_PASS_THRESHOLD = 0.5

QualityBarScale = Literal["score_1_5", "rubric_0_100"]
DerivationStatus = Literal[
    "advisory_insufficient_evidence",
    "advisory_conflicting_evidence",
    "advisory_stale_evidence",
    "advisory_seed_band",
    "derived_enforced",
    "derived_floored_at_seed",
]
AxisVerdict = Literal["pass", "fail", "unresolved"]
_ADVISORY_STATUSES: frozenset[str] = frozenset(
    {
        "advisory_insufficient_evidence",
        "advisory_conflicting_evidence",
        "advisory_stale_evidence",
        "advisory_seed_band",
    }
)


class QualityBarSpec(BaseModel):
    """A governed segment-prep gate bar and the posterior axis it reads from.

    ``seed_default`` is the legacy magic constant the bar falls back to (loud +
    advisory) until the posterior reaches quorum on ``rating_axis``.
    ``posterior_governed`` bars derive a ratcheted operative value; non-governed
    band subdivisions stay at the seed but are still emitted to / read from the
    file so the decision sites no longer hardcode the literal.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    rating_axis: str
    scale: QualityBarScale
    seed_default: float
    governs: str
    posterior_governed: bool = True


GOVERNED_QUALITY_BARS: tuple[QualityBarSpec, ...] = (
    QualityBarSpec(
        name="automated_script_overall",
        rating_axis="overall",
        scale="score_1_5",
        seed_default=3.5,
        governs="shared.segment_iteration_review.MIN_AUTOMATED_SCRIPT_SCORE",
    ),
    QualityBarSpec(
        name="live_event_good_floor",
        rating_axis="substantive",
        scale="rubric_0_100",
        seed_default=82.0,
        governs="shared.segment_live_event_quality.LIVE_EVENT_GOOD_FLOOR",
    ),
    QualityBarSpec(
        name="live_event_band_excellent",
        rating_axis="substantive",
        scale="rubric_0_100",
        seed_default=93.0,
        governs="shared.segment_live_event_quality._band(excellent)",
        posterior_governed=False,
    ),
    QualityBarSpec(
        name="live_event_band_review_only",
        rating_axis="substantive",
        scale="rubric_0_100",
        seed_default=75.0,
        governs="shared.segment_live_event_quality._band(review_only)",
        posterior_governed=False,
    ),
    QualityBarSpec(
        name="live_event_band_thin",
        rating_axis="substantive",
        scale="rubric_0_100",
        seed_default=50.0,
        governs="shared.segment_live_event_quality._band(thin)",
        posterior_governed=False,
    ),
)
_BARS_BY_NAME: dict[str, QualityBarSpec] = {spec.name: spec for spec in GOVERNED_QUALITY_BARS}
GOVERNED_RATING_AXES: tuple[str, ...] = tuple(
    dict.fromkeys(spec.rating_axis for spec in GOVERNED_QUALITY_BARS)
)


class DerivedQualityBar(BaseModel):
    """A single gate bar resolved against the operator-quality posterior."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    rating_axis: str
    scale: QualityBarScale
    seed_default: float
    value: float
    derived_value: float | None
    posterior_alpha: float = Field(..., gt=0.0)
    posterior_beta: float = Field(..., gt=0.0)
    std: float = Field(..., ge=0.0)
    sample_count: int = Field(..., ge=0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    derived_at: datetime
    corpus_sha256: str
    uncertainty_reason: str | None
    derivation_status: DerivationStatus
    advisory: bool
    mode_ceiling: Literal["private"] = "private"
    privacy_label: Literal["private"] = "private"


class DerivedQualityBars(BaseModel):
    """Versioned, emittable set of derived segment-prep gate bars."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    derived_at: datetime
    corpus_sha256: str
    min_samples: int = Field(..., ge=1)
    bars: tuple[DerivedQualityBar, ...]
    axis_verdict: dict[str, AxisVerdict]
    quorum_met: bool
    bar_derivation_sha256: str
    mode_ceiling: Literal["private"] = "private"
    privacy_label: Literal["private"] = "private"
    negative_constraints: tuple[str, ...] = NEGATIVE_CONSTRAINTS

    def bar(self, name: str) -> DerivedQualityBar | None:
        for entry in self.bars:
            if entry.name == name:
                return entry
        return None


def _corpus_sha256(events: Sequence[OperatorQualityRatingEvent]) -> str:
    payload = [
        json.loads(event.model_dump_json())
        for event in sorted(events, key=lambda e: (e.occurred_at, e.event_id))
    ]
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


_EMPTY_CORPUS_SHA256 = _corpus_sha256([])


def _reference_time(events: Sequence[OperatorQualityRatingEvent]) -> datetime:
    if not events:
        return _EMPTY_CORPUS_REFERENCE
    return max(event.occurred_at for event in events)


def _project(scale: QualityBarScale, row: PosteriorRow) -> float:
    if scale == "score_1_5":
        return row.aggregate_score_1_5
    return float(round(row.aggregate_score * 100.0))


def _derive_one_bar(
    spec: QualityBarSpec,
    *,
    row: PosteriorRow | None,
    insufficient: InsufficientEvidenceRow | None,
    reference_time: datetime,
    corpus_sha: str,
) -> DerivedQualityBar:
    derived_value: float | None = None
    value = spec.seed_default

    if row is not None:
        alpha = row.posterior_alpha
        beta = row.posterior_beta
        std = row.posterior_std
        sample_count = row.sample_count
        confidence = row.confidence
        reason = row.uncertainty_reason.value if row.uncertainty_reason is not None else None

        if not spec.posterior_governed:
            status: DerivationStatus = "advisory_seed_band"
        elif row.uncertainty_reason == UncertaintyReason.CONFLICTING_EVIDENCE:
            status = "advisory_conflicting_evidence"
        elif row.uncertainty_reason == UncertaintyReason.STALE_EVIDENCE:
            status = "advisory_stale_evidence"
        else:
            projected = _project(spec.scale, row)
            derived_value = projected
            if projected >= spec.seed_default:
                status = "derived_enforced"
                value = projected
            else:
                status = "derived_floored_at_seed"
    else:
        alpha = 1.0
        beta = 1.0
        std = _UNIFORM_STD
        confidence = 0.0
        if insufficient is not None:
            sample_count = insufficient.sample_count
            reason = insufficient.uncertainty_reason.value
        else:
            sample_count = 0
            reason = UncertaintyReason.NO_OBSERVATIONS.value
        status = (
            "advisory_seed_band"
            if not spec.posterior_governed
            else "advisory_insufficient_evidence"
        )

    return DerivedQualityBar(
        name=spec.name,
        rating_axis=spec.rating_axis,
        scale=spec.scale,
        seed_default=spec.seed_default,
        value=value,
        derived_value=derived_value,
        posterior_alpha=alpha,
        posterior_beta=beta,
        std=std,
        sample_count=sample_count,
        confidence=confidence,
        derived_at=reference_time,
        corpus_sha256=corpus_sha,
        uncertainty_reason=reason,
        derivation_status=status,
        advisory=status in _ADVISORY_STATUSES,
    )


def _axis_verdict(rows_by_axis: Mapping[str, PosteriorRow]) -> dict[str, AxisVerdict]:
    """Per-axis advisory verdict.

    Every governed axis stays in the denominator: an axis with no resolved
    posterior, or with conflicting ("hung") evidence, is ``unresolved`` (cannot
    pass) rather than silently dropped.
    """

    axes = set(GOVERNED_RATING_AXES) | set(rows_by_axis)
    verdict: dict[str, AxisVerdict] = {}
    for axis in sorted(axes):
        row = rows_by_axis.get(axis)
        if row is None or row.uncertainty_reason == UncertaintyReason.CONFLICTING_EVIDENCE:
            verdict[axis] = "unresolved"
        elif row.aggregate_score >= _AXIS_PASS_THRESHOLD:
            verdict[axis] = "pass"
        else:
            verdict[axis] = "fail"
    return verdict


def _derivation_payload(
    *,
    derived_at: datetime,
    corpus_sha: str,
    min_samples: int,
    bars: tuple[DerivedQualityBar, ...],
    axis_verdict: Mapping[str, str],
    quorum_met: bool,
) -> dict[str, object]:
    return {
        "schema_version": DERIVED_QUALITY_BARS_VERSION,
        "derived_at": derived_at.isoformat(),
        "corpus_sha256": corpus_sha,
        "min_samples": min_samples,
        "bars": [bar.model_dump(mode="json") for bar in bars],
        "axis_verdict": dict(axis_verdict),
        "quorum_met": quorum_met,
    }


def derive_quality_bars(
    events: Iterable[OperatorQualityRatingEvent] | None = None,
    *,
    path: Path | None = None,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    reference_time: datetime | None = None,
) -> DerivedQualityBars:
    """Derive the governed gate bars from the operator-quality posterior.

    With ``events=None`` the corpus is read from the JSONL sink. The derivation
    is deterministic given the corpus: decay is referenced to the most recent
    rating (``reference_time``), never wall-clock.
    """

    if min_samples < 1:
        raise ValueError("min_samples must be >= 1")
    materialized = (
        list(iter_operator_quality_ratings(path=path)) if events is None else list(events)
    )

    ref = reference_time if reference_time is not None else _reference_time(materialized)
    if ref.tzinfo is None or ref.utcoffset() is None:
        raise ValueError("reference_time must be timezone-aware")
    ref = ref.astimezone(UTC)
    corpus_sha = _corpus_sha256(materialized)

    model = aggregate_operator_quality_posterior(
        materialized,
        now=ref,
        min_samples=min_samples,
        group_by=("rating_axis",),
    )
    rows_by_axis = {row.key.rating_axis: row for row in model.rows if row.key.rating_axis}
    insufficient_by_axis = {
        row.key.rating_axis: row for row in model.insufficient_evidence if row.key.rating_axis
    }

    bars = tuple(
        _derive_one_bar(
            spec,
            row=rows_by_axis.get(spec.rating_axis),
            insufficient=insufficient_by_axis.get(spec.rating_axis),
            reference_time=ref,
            corpus_sha=corpus_sha,
        )
        for spec in GOVERNED_QUALITY_BARS
    )
    axis_verdict = _axis_verdict(rows_by_axis)
    quorum_met = bool(axis_verdict) and all(v == "pass" for v in axis_verdict.values())

    payload = _derivation_payload(
        derived_at=ref,
        corpus_sha=corpus_sha,
        min_samples=min_samples,
        bars=bars,
        axis_verdict=axis_verdict,
        quorum_met=quorum_met,
    )
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    return DerivedQualityBars(
        derived_at=ref,
        corpus_sha256=corpus_sha,
        min_samples=min_samples,
        bars=bars,
        axis_verdict=axis_verdict,
        quorum_met=quorum_met,
        bar_derivation_sha256=digest,
    )


def _seed_default_bar(spec: QualityBarSpec) -> DerivedQualityBar:
    return DerivedQualityBar(
        name=spec.name,
        rating_axis=spec.rating_axis,
        scale=spec.scale,
        seed_default=spec.seed_default,
        value=spec.seed_default,
        derived_value=None,
        posterior_alpha=1.0,
        posterior_beta=1.0,
        std=_UNIFORM_STD,
        sample_count=0,
        confidence=0.0,
        derived_at=_EMPTY_CORPUS_REFERENCE,
        corpus_sha256=_EMPTY_CORPUS_SHA256,
        uncertainty_reason=UncertaintyReason.NO_OBSERVATIONS.value,
        derivation_status=(
            "advisory_seed_band"
            if not spec.posterior_governed
            else "advisory_insufficient_evidence"
        ),
        advisory=True,
    )


def resolve_quality_bar(name: str, *, bars: DerivedQualityBars | None = None) -> DerivedQualityBar:
    """Return the operative bar; the seed default (advisory) when none derived."""

    spec = _BARS_BY_NAME.get(name)
    if spec is None:
        raise KeyError(f"unknown quality bar: {name!r}")
    if bars is not None:
        found = bars.bar(name)
        if found is not None:
            return found
    return _seed_default_bar(spec)


def derived_quality_bars_path(env: Mapping[str, str] | None = None) -> Path:
    """Resolve the derived-quality-bars artifact path (env override honored)."""

    env_map = os.environ if env is None else env
    if explicit := env_map.get(DERIVED_QUALITY_BARS_PATH_ENV):
        return Path(explicit).expanduser()
    state_root = Path(env_map.get(HAPAX_STATE_ENV, str(Path.home() / "hapax-state"))).expanduser()
    return state_root / "operator-quality-feedback" / "derived-quality-bars.json"


def write_derived_quality_bars(bars: DerivedQualityBars, *, path: Path | None = None) -> Path:
    """Emit the derived-quality-bars artifact as JSON."""

    target = path if path is not None else derived_quality_bars_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(bars.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return target


def load_derived_quality_bars(*, path: Path | None = None) -> DerivedQualityBars | None:
    """Load the emitted derived-quality-bars artifact, or ``None`` if absent."""

    target = path if path is not None else derived_quality_bars_path()
    if not target.exists():
        return None
    try:
        return DerivedQualityBars.model_validate_json(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("ignoring malformed derived-quality-bars artifact: %s", target, exc_info=True)
        return None


def generate_derived_quality_bars_main() -> int:
    """CLI entrypoint: derive bars from the corpus and emit the artifact."""

    bars = derive_quality_bars()
    target = write_derived_quality_bars(bars)
    log.info(
        "wrote %d derived quality bars to %s (quorum_met=%s, corpus=%s)",
        len(bars.bars),
        target,
        bars.quorum_met,
        bars.corpus_sha256[:12],
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(generate_derived_quality_bars_main())
