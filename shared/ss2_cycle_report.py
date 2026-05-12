"""Private SS2 autonomous-speech cycle sampling and scoring.

SS2 is a research loop, not a one-shot feature. This module turns the
cycle protocol into a reproducible private report: select autonomous
narrative emissions from the chronicle, sample them uniformly, join
operator-quality ratings when present, and compute the cycle rubric gates.

The output is a private research artifact. It does not authorize public
claims, monetization claims, or viewer-facing quality claims.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.chronicle import CHRONICLE_FILE, ChronicleEvent, query
from shared.operator_quality_feedback import (
    OperatorQualityRatingEvent,
    iter_operator_quality_ratings,
)

SS2_RUBRIC_AXES: tuple[str, ...] = (
    "substantive",
    "grounded",
    "stimmung_coherence",
    "programme_respecting",
    "listenable",
)
SS2_SCORE_AXES: tuple[str, ...] = ("overall", *SS2_RUBRIC_AXES)

DEFAULT_SAMPLE_SIZE = 20
DEFAULT_QUERY_LIMIT = 100_000
SS2_ACCEPTANCE_SCORE_FLOOR = 4.0
SS2_ITERATE_SCORE_FLOOR = 3.0
SS2_GROUNDING_COVERAGE_FLOOR = 0.7

AUTONOMOUS_NARRATIVE_SOURCE = "self_authored_narrative"
AUTONOMOUS_NARRATIVE_EVENT_TYPE = "narrative.emitted"

NEGATIVE_CONSTRAINTS: tuple[str, ...] = (
    "private_by_default",
    "no_public_authorization",
    "no_monetization_authorization",
    "no_research_validity_authorization",
    "no_raw_operator_note_text",
)


class SS2EmissionSample(BaseModel):
    """One sampled autonomous narrative emission."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str
    occurred_at: datetime
    ts: float
    programme_id: str | None = None
    speech_event_id: str | None = None
    impulse_id: str | None = None
    emission_refs: tuple[str, ...]
    narrative_text: str | None = None
    grounded: bool
    novelty_score: float | None = None
    direct_rating_count: int = Field(default=0, ge=0)
    mean_rating_by_axis: dict[str, float] = Field(default_factory=dict)


class SS2AxisScore(BaseModel):
    """Aggregate score for one SS2 rubric axis."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    axis: str
    rating_count: int = Field(..., ge=0)
    mean_1_5: float | None = Field(default=None, ge=1.0, le=5.0)
    pass_fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    direct_rating_count: int = Field(default=0, ge=0)
    window_rating_count: int = Field(default=0, ge=0)


class SS2CycleReport(BaseModel):
    """Private cycle report for SS2 operator judgment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    cycle_id: str
    generated_at: datetime
    window_start: datetime
    window_end: datetime
    sample_seed: str
    requested_sample_size: int = Field(..., ge=1)
    eligible_event_count: int = Field(..., ge=0)
    sampled_event_count: int = Field(..., ge=0)
    samples: tuple[SS2EmissionSample, ...] = Field(default_factory=tuple)
    axis_scores: tuple[SS2AxisScore, ...] = Field(default_factory=tuple)
    rubric_mean_1_5: float | None = Field(default=None, ge=1.0, le=5.0)
    decision_score_1_5: float | None = Field(default=None, ge=1.0, le=5.0)
    verdict: Literal["hold", "iterate", "revert", "insufficient"]
    verdict_reason: str
    direct_rating_count: int = Field(..., ge=0)
    window_rating_count: int = Field(..., ge=0)
    grounding_coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    grounded_event_count: int = Field(..., ge=0)
    groundable_event_count: int = Field(..., ge=0)
    grounding_gate_passed: bool
    novelty_score_mean: float | None = None
    novelty_score_count: int = Field(..., ge=0)
    mode_ceiling: Literal["private"] = "private"
    privacy_label: Literal["private"] = "private"
    negative_constraints: tuple[str, ...] = NEGATIVE_CONSTRAINTS


def build_ss2_cycle_report(
    *,
    cycle_id: str,
    window_start: datetime,
    window_end: datetime,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
    sample_seed: str | None = None,
    chronicle_path: Path = CHRONICLE_FILE,
    ratings_path: Path | None = None,
    include_text: bool = True,
    programme_id: str | None = None,
    condition_id: str | None = None,
    run_id: str | None = None,
    now: datetime | None = None,
) -> SS2CycleReport:
    """Build a private SS2 cycle report for one observation window."""

    if sample_size < 1:
        raise ValueError("sample_size must be >= 1")
    start = _ensure_utc(window_start)
    end = _ensure_utc(window_end)
    if end <= start:
        raise ValueError("window_end must be after window_start")

    seed = sample_seed or f"{cycle_id}:{start.isoformat()}:{end.isoformat()}:{sample_size}"
    generated_at = _ensure_utc(now) if now is not None else datetime.now(UTC)
    events = load_autonomous_narrative_events(
        since=start.timestamp(),
        until=end.timestamp(),
        path=chronicle_path,
        limit=DEFAULT_QUERY_LIMIT,
        programme_id=programme_id,
    )
    sampled = sample_autonomous_narrative_events(events, sample_size=sample_size, seed=seed)
    ratings = tuple(iter_operator_quality_ratings(path=ratings_path))

    direct_ratings_by_event, window_ratings = _join_ratings(
        sampled,
        ratings,
        window_start=start,
        window_end=end,
        programme_id=programme_id,
        condition_id=condition_id,
        run_id=run_id,
    )
    direct_count = sum(len(items) for items in direct_ratings_by_event.values())
    window_count = len(window_ratings)

    samples = tuple(
        _sample_model(
            event,
            direct_ratings_by_event.get(event.event_id, ()),
            include_text=include_text,
        )
        for event in sampled
    )
    axis_scores = _axis_scores(direct_ratings_by_event.values(), window_ratings)
    rubric_mean = _rubric_mean(axis_scores)
    decision_score = rubric_mean if rubric_mean is not None else _axis_mean(axis_scores, "overall")
    verdict, reason = _verdict(
        decision_score=decision_score,
        rubric_mean=rubric_mean,
        sampled_event_count=len(samples),
        requested_sample_size=sample_size,
        rating_count=direct_count + window_count,
    )

    grounded_count, groundable_count, coverage = _grounding_counts(events)
    novelty_values = [_novelty_score(ev) for ev in events]
    novelty_values_f = [v for v in novelty_values if v is not None]
    novelty_mean = sum(novelty_values_f) / len(novelty_values_f) if novelty_values_f else None

    return SS2CycleReport(
        cycle_id=cycle_id,
        generated_at=generated_at,
        window_start=start,
        window_end=end,
        sample_seed=seed,
        requested_sample_size=sample_size,
        eligible_event_count=len(events),
        sampled_event_count=len(samples),
        samples=samples,
        axis_scores=axis_scores,
        rubric_mean_1_5=rubric_mean,
        decision_score_1_5=decision_score,
        verdict=verdict,
        verdict_reason=reason,
        direct_rating_count=direct_count,
        window_rating_count=window_count,
        grounding_coverage=coverage,
        grounded_event_count=grounded_count,
        groundable_event_count=groundable_count,
        grounding_gate_passed=(coverage is not None and coverage >= SS2_GROUNDING_COVERAGE_FLOOR),
        novelty_score_mean=novelty_mean,
        novelty_score_count=len(novelty_values_f),
    )


def load_autonomous_narrative_events(
    *,
    since: float,
    until: float,
    path: Path = CHRONICLE_FILE,
    limit: int = DEFAULT_QUERY_LIMIT,
    programme_id: str | None = None,
) -> tuple[ChronicleEvent, ...]:
    """Return autonomous-narrative chronicle events in chronological order."""

    raw_events = query(since=since, until=until, limit=limit, path=path)
    events = [
        event
        for event in raw_events
        if _is_autonomous_narrative_event(event)
        and (programme_id is None or _programme_id(event) == programme_id)
    ]
    events.sort(key=lambda event: (event.ts, event.event_id))
    return tuple(events)


def sample_autonomous_narrative_events(
    events: Sequence[ChronicleEvent],
    *,
    sample_size: int,
    seed: str,
) -> tuple[ChronicleEvent, ...]:
    """Uniformly sample events with a deterministic seed, returned chronological."""

    if sample_size < 1:
        raise ValueError("sample_size must be >= 1")
    materialized = list(events)
    if len(materialized) <= sample_size:
        return tuple(materialized)
    rng = random.Random(seed)
    sampled = rng.sample(materialized, sample_size)
    sampled.sort(key=lambda event: (event.ts, event.event_id))
    return tuple(sampled)


def render_ss2_cycle_report_markdown(report: SS2CycleReport) -> str:
    """Render a compact private Markdown report for operator scoring."""

    lines = [
        f"# SS2 Cycle Report: {report.cycle_id}",
        "",
        f"- Window: {report.window_start.isoformat()} to {report.window_end.isoformat()}",
        f"- Verdict: {report.verdict} ({report.verdict_reason})",
        f"- Eligible emissions: {report.eligible_event_count}",
        f"- Sampled emissions: {report.sampled_event_count}/{report.requested_sample_size}",
        f"- Direct ratings: {report.direct_rating_count}",
        f"- Window ratings: {report.window_rating_count}",
        f"- Rubric mean: {_format_float(report.rubric_mean_1_5)}",
        f"- Decision score: {_format_float(report.decision_score_1_5)}",
        (
            "- Grounding coverage: "
            f"{_format_float(report.grounding_coverage)} "
            f"({report.grounded_event_count}/{report.groundable_event_count})"
        ),
        f"- Novelty score mean: {_format_float(report.novelty_score_mean)}",
        "",
        "## Axis Scores",
        "",
        "| Axis | Ratings | Mean | Pass fraction |",
        "|------|---------|------|---------------|",
    ]
    for score in report.axis_scores:
        lines.append(
            "| "
            f"{score.axis} | {score.rating_count} | {_format_float(score.mean_1_5)} | "
            f"{_format_float(score.pass_fraction)} |"
        )

    lines.extend(["", "## Sampled Emissions", ""])
    if not report.samples:
        lines.append("_No autonomous narrative emissions found in the window._")
    for i, sample in enumerate(report.samples, 1):
        refs = ", ".join(sample.emission_refs[:4])
        lines.append(f"### {i}. {sample.occurred_at.isoformat()}")
        lines.append(f"- Refs: {refs}")
        if sample.programme_id:
            lines.append(f"- Programme: {sample.programme_id}")
        lines.append(f"- Grounded: {str(sample.grounded).lower()}")
        if sample.mean_rating_by_axis:
            rendered = ", ".join(
                f"{axis}={value:.2f}" for axis, value in sample.mean_rating_by_axis.items()
            )
            lines.append(f"- Direct rating means: {rendered}")
        if sample.narrative_text:
            lines.append("")
            lines.append(sample.narrative_text)
        lines.append("")

    lines.extend(
        [
            "## Privacy",
            "",
            "Private research signal only. This report cannot authorize public, "
            "monetized, or research-validity claims.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime values must be timezone-aware")
    return value.astimezone(UTC)


def _is_autonomous_narrative_event(event: ChronicleEvent) -> bool:
    if event.source == AUTONOMOUS_NARRATIVE_SOURCE and (
        event.event_type == AUTONOMOUS_NARRATIVE_EVENT_TYPE
    ):
        return True
    payload = event.payload if isinstance(event.payload, dict) else {}
    return payload.get("intent_family") == "narrative.autonomous_speech"


def _programme_id(event: ChronicleEvent) -> str | None:
    payload = event.payload if isinstance(event.payload, dict) else {}
    value = payload.get("programme_id")
    return str(value) if value not in (None, "") else None


def _speech_event_id(event: ChronicleEvent) -> str | None:
    payload = event.payload if isinstance(event.payload, dict) else {}
    value = payload.get("speech_event_id") or payload.get("impingement_id")
    return str(value) if value not in (None, "") else None


def _impulse_id(event: ChronicleEvent) -> str | None:
    payload = event.payload if isinstance(event.payload, dict) else {}
    value = payload.get("impulse_id")
    return str(value) if value not in (None, "") else None


def _narrative_text(event: ChronicleEvent) -> str | None:
    payload = event.payload if isinstance(event.payload, dict) else {}
    value = payload.get("narrative") or payload.get("text")
    if isinstance(value, str) and value.strip():
        return value.strip()
    nested = payload.get("content")
    if isinstance(nested, dict):
        nested_value = nested.get("narrative") or nested.get("text")
        if isinstance(nested_value, str) and nested_value.strip():
            return nested_value.strip()
    return None


def _emission_refs(event: ChronicleEvent) -> tuple[str, ...]:
    refs = [f"chronicle:{event.event_id}", f"event:{event.event_id}", event.event_id]
    speech_id = _speech_event_id(event)
    if speech_id:
        refs.extend(
            [
                f"speech_event:{speech_id}",
                f"speech:{speech_id}",
                f"impingement:{speech_id}",
                f"impingement_id:{speech_id}",
                speech_id,
            ]
        )
    impulse_id = _impulse_id(event)
    if impulse_id:
        refs.extend([f"impulse:{impulse_id}", impulse_id])
    return tuple(dict.fromkeys(refs))


def _is_grounded(event: ChronicleEvent) -> bool:
    if event.evidence_refs:
        return True
    payload = event.payload if isinstance(event.payload, dict) else {}
    provenance = payload.get("grounding_provenance")
    if isinstance(provenance, dict):
        return bool(provenance)
    if isinstance(provenance, str):
        return bool(provenance.strip())
    if isinstance(provenance, (list, tuple)):
        try:
            from shared.director_intent import split_grounding_provenance

            real, _synthetic = split_grounding_provenance([str(item) for item in provenance])
            return bool(real)
        except Exception:  # noqa: BLE001
            return bool(provenance)
    return False


def _novelty_score(event: ChronicleEvent) -> float | None:
    payload = event.payload if isinstance(event.payload, dict) else {}
    for key in (
        "impingement_novelty_score",
        "hapax_impingement_novelty_score",
        "novelty_score",
    ):
        value = payload.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            return float(value)
    quality = payload.get("quality")
    if isinstance(quality, dict):
        value = quality.get("impingement_novelty_score") or quality.get("novelty_score")
        if not isinstance(value, bool) and isinstance(value, (int, float)):
            return float(value)
    return None


def _sample_model(
    event: ChronicleEvent,
    ratings: Sequence[OperatorQualityRatingEvent],
    *,
    include_text: bool,
) -> SS2EmissionSample:
    return SS2EmissionSample(
        event_id=event.event_id,
        occurred_at=datetime.fromtimestamp(event.ts, UTC),
        ts=event.ts,
        programme_id=_programme_id(event),
        speech_event_id=_speech_event_id(event),
        impulse_id=_impulse_id(event),
        emission_refs=_emission_refs(event),
        narrative_text=_narrative_text(event) if include_text else None,
        grounded=_is_grounded(event),
        novelty_score=_novelty_score(event),
        direct_rating_count=len(ratings),
        mean_rating_by_axis=_rating_means_by_axis(ratings),
    )


def _rating_means_by_axis(
    ratings: Sequence[OperatorQualityRatingEvent],
) -> dict[str, float]:
    values: dict[str, list[int]] = defaultdict(list)
    for rating in ratings:
        values[rating.rating_axis].append(rating.rating)
    return {
        axis: sum(axis_values) / len(axis_values)
        for axis, axis_values in sorted(values.items())
        if axis_values
    }


def _join_ratings(
    events: Sequence[ChronicleEvent],
    ratings: Sequence[OperatorQualityRatingEvent],
    *,
    window_start: datetime,
    window_end: datetime,
    programme_id: str | None,
    condition_id: str | None,
    run_id: str | None,
) -> tuple[
    dict[str, tuple[OperatorQualityRatingEvent, ...]], tuple[OperatorQualityRatingEvent, ...]
]:
    ref_index: dict[str, str] = {}
    for event in events:
        for ref in _emission_refs(event):
            ref_index[ref] = event.event_id

    direct: dict[str, list[OperatorQualityRatingEvent]] = defaultdict(list)
    window_level: list[OperatorQualityRatingEvent] = []
    for rating in ratings:
        if rating.emission_ref and rating.emission_ref in ref_index:
            direct[ref_index[rating.emission_ref]].append(rating)
            continue
        if (
            not rating.emission_ref
            and window_start <= rating.occurred_at <= window_end
            and _rating_scope_matches(
                rating,
                programme_id=programme_id,
                condition_id=condition_id,
                run_id=run_id,
            )
        ):
            window_level.append(rating)

    return {key: tuple(value) for key, value in direct.items()}, tuple(window_level)


def _rating_scope_matches(
    rating: OperatorQualityRatingEvent,
    *,
    programme_id: str | None,
    condition_id: str | None,
    run_id: str | None,
) -> bool:
    checks = (
        (programme_id, rating.programme_id),
        (condition_id, rating.condition_id),
        (run_id, rating.run_id),
    )
    for requested, actual in checks:
        if requested is not None and actual is not None and actual != requested:
            return False
    return True


def _axis_scores(
    direct_groups: Iterable[Sequence[OperatorQualityRatingEvent]],
    window_ratings: Sequence[OperatorQualityRatingEvent],
) -> tuple[SS2AxisScore, ...]:
    direct_by_axis: dict[str, list[int]] = defaultdict(list)
    window_by_axis: dict[str, list[int]] = defaultdict(list)
    for group in direct_groups:
        for rating in group:
            direct_by_axis[rating.rating_axis].append(rating.rating)
    for rating in window_ratings:
        window_by_axis[rating.rating_axis].append(rating.rating)

    scores: list[SS2AxisScore] = []
    for axis in SS2_SCORE_AXES:
        values = [*direct_by_axis.get(axis, ()), *window_by_axis.get(axis, ())]
        mean = sum(values) / len(values) if values else None
        pass_fraction = (
            sum(1 for value in values if value >= SS2_ACCEPTANCE_SCORE_FLOOR) / len(values)
            if values
            else None
        )
        scores.append(
            SS2AxisScore(
                axis=axis,
                rating_count=len(values),
                mean_1_5=mean,
                pass_fraction=pass_fraction,
                direct_rating_count=len(direct_by_axis.get(axis, ())),
                window_rating_count=len(window_by_axis.get(axis, ())),
            )
        )
    return tuple(scores)


def _axis_mean(scores: Sequence[SS2AxisScore], axis: str) -> float | None:
    for score in scores:
        if score.axis == axis:
            return score.mean_1_5
    return None


def _rubric_mean(scores: Sequence[SS2AxisScore]) -> float | None:
    values = [_axis_mean(scores, axis) for axis in SS2_RUBRIC_AXES]
    if any(value is None for value in values):
        return None
    concrete = [value for value in values if value is not None]
    return sum(concrete) / len(concrete)


def _verdict(
    *,
    decision_score: float | None,
    rubric_mean: float | None,
    sampled_event_count: int,
    requested_sample_size: int,
    rating_count: int,
) -> tuple[Literal["hold", "iterate", "revert", "insufficient"], str]:
    if sampled_event_count < requested_sample_size:
        return "insufficient", "sample smaller than requested cycle sample"
    if rating_count == 0:
        return "insufficient", "no operator-quality ratings joined"
    if decision_score is None:
        return "insufficient", "no overall rating and incomplete five-axis rubric"
    if rubric_mean is None:
        return "insufficient", "overall rating present but five-axis rubric incomplete"
    if decision_score >= SS2_ACCEPTANCE_SCORE_FLOOR:
        return "hold", "rubric mean clears hold floor"
    if decision_score >= SS2_ITERATE_SCORE_FLOOR:
        return "iterate", "rubric mean falls in iteration band"
    return "revert", "rubric mean falls below revert floor"


def _grounding_counts(events: Sequence[ChronicleEvent]) -> tuple[int, int, float | None]:
    if not events:
        return 0, 0, None
    grounded = sum(1 for event in events if _is_grounded(event))
    return grounded, len(events), grounded / len(events)


def _format_float(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.3f}"
