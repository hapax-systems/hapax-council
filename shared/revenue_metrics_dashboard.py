"""Revenue metrics dashboard contract for the autonomous grounding train."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

type Horizon = Literal["1_month", "6_months", "1_year", "2_years"]
type Confidence = Literal["unknown", "low", "low_med", "medium", "high"]
type RevenueStream = Literal[
    "platform_native",
    "support_rails",
    "grants_fellowships",
    "research_artifacts_licensing",
    "product_tool_ip",
    "consulting_by_artifact",
    "aesthetic_editions",
    "studio_adjacent",
]
type ContentFormat = Literal[
    "tier_list",
    "bracket",
    "review",
    "comparison",
    "what_is_this",
    "react_commentary",
    "watch_along",
    "explainer_rundown",
    "debate",
    "refusal_breakdown",
    "claim_audit",
    "failure_autopsy",
]
type ReadinessDimension = Literal[
    "safe_to_broadcast",
    "safe_to_archive",
    "safe_to_promote",
    "safe_to_monetize",
    "safe_to_publish_offer",
    "safe_to_publish_artifact",
    "safe_to_accept_payment",
]
type ReadinessStateName = Literal["unknown", "blocked", "ready", "not_applicable"]
type YouTubePartnerState = Literal[
    "unknown",
    "ineligible",
    "eligible",
    "in_review",
    "active",
    "blocked",
]
type TrainStatusName = Literal["unknown", "under_target", "on_track"]

HORIZONS: tuple[Horizon, ...] = ("1_month", "6_months", "1_year", "2_years")
HORIZON_MONTHS: dict[Horizon, float] = {
    "1_month": 1.0,
    "6_months": 6.0,
    "1_year": 12.0,
    "2_years": 24.0,
}
REVENUE_STREAMS: tuple[RevenueStream, ...] = (
    "platform_native",
    "support_rails",
    "grants_fellowships",
    "research_artifacts_licensing",
    "product_tool_ip",
    "consulting_by_artifact",
    "aesthetic_editions",
    "studio_adjacent",
)
CONTENT_FORMATS: tuple[ContentFormat, ...] = (
    "tier_list",
    "bracket",
    "review",
    "comparison",
    "what_is_this",
    "react_commentary",
    "watch_along",
    "explainer_rundown",
    "debate",
    "refusal_breakdown",
    "claim_audit",
    "failure_autopsy",
)
READINESS_DIMENSIONS: tuple[ReadinessDimension, ...] = (
    "safe_to_broadcast",
    "safe_to_archive",
    "safe_to_promote",
    "safe_to_monetize",
    "safe_to_publish_offer",
    "safe_to_publish_artifact",
    "safe_to_accept_payment",
)

STREAM_DISPLAY_NAMES: dict[RevenueStream, str] = {
    "platform_native": "Platform native",
    "support_rails": "Support rails",
    "grants_fellowships": "Grants and fellowships",
    "research_artifacts_licensing": "Research artifacts and licensing",
    "product_tool_ip": "Product, tool, and IP",
    "consulting_by_artifact": "Consulting by artifact",
    "aesthetic_editions": "Aesthetic editions",
    "studio_adjacent": "Studio adjacent",
}
FORMAT_DISPLAY_NAMES: dict[ContentFormat, str] = {
    "tier_list": "Tier list",
    "bracket": "Bracket",
    "review": "Review",
    "comparison": "Comparison",
    "what_is_this": "What is this",
    "react_commentary": "React commentary",
    "watch_along": "Watch along",
    "explainer_rundown": "Explainer rundown",
    "debate": "Debate",
    "refusal_breakdown": "Refusal breakdown",
    "claim_audit": "Claim audit",
    "failure_autopsy": "Failure autopsy",
}
STREAM_BASE_TARGETS: dict[RevenueStream, dict[Horizon, float]] = {
    "platform_native": {
        "1_month": 0.0,
        "6_months": 8_000.0,
        "1_year": 45_000.0,
        "2_years": 190_000.0,
    },
    "support_rails": {
        "1_month": 200.0,
        "6_months": 10_000.0,
        "1_year": 30_000.0,
        "2_years": 95_000.0,
    },
    "grants_fellowships": {
        "1_month": 0.0,
        "6_months": 25_000.0,
        "1_year": 70_000.0,
        "2_years": 160_000.0,
    },
    "research_artifacts_licensing": {
        "1_month": 400.0,
        "6_months": 10_000.0,
        "1_year": 35_000.0,
        "2_years": 110_000.0,
    },
    "product_tool_ip": {
        "1_month": 150.0,
        "6_months": 5_000.0,
        "1_year": 20_000.0,
        "2_years": 70_000.0,
    },
    "consulting_by_artifact": {
        "1_month": 0.0,
        "6_months": 0.0,
        "1_year": 0.0,
        "2_years": 0.0,
    },
    "aesthetic_editions": {
        "1_month": 50.0,
        "6_months": 4_000.0,
        "1_year": 15_000.0,
        "2_years": 65_000.0,
    },
    "studio_adjacent": {
        "1_month": 0.0,
        "6_months": 2_000.0,
        "1_year": 5_000.0,
        "2_years": 25_000.0,
    },
}
BASE_TARGETS: dict[Horizon, float] = {
    horizon: sum(STREAM_BASE_TARGETS[stream][horizon] for stream in REVENUE_STREAMS)
    for horizon in HORIZONS
}
DOUBLED_TARGETS: dict[Horizon, float] = {horizon: BASE_TARGETS[horizon] * 2 for horizon in HORIZONS}
STREAM_DOUBLED_TARGETS: dict[RevenueStream, dict[Horizon, float]] = {
    stream: {horizon: targets[horizon] * 2 for horizon in HORIZONS}
    for stream, targets in STREAM_BASE_TARGETS.items()
}
RUN_RATE_BASE_TARGETS: dict[Horizon, float] = {
    horizon: round(BASE_TARGETS[horizon] / HORIZON_MONTHS[horizon], 2) for horizon in HORIZONS
}
RUN_RATE_DOUBLED_TARGETS: dict[Horizon, float] = {
    horizon: round(DOUBLED_TARGETS[horizon] / HORIZON_MONTHS[horizon], 2) for horizon in HORIZONS
}
NEXT_CORRECTION_PACKET_BY_STREAM: dict[RevenueStream, str] = {
    "platform_native": "content-programming-grounding-runner",
    "support_rails": "public-offer-page-generator-no-perk",
    "grants_fellowships": "grant-opportunity-scout-attestation-queue",
    "research_artifacts_licensing": "artifact-catalog-release-workflow",
    "product_tool_ip": "artifact-catalog-release-workflow",
    "consulting_by_artifact": "license-request-price-class-router",
    "aesthetic_editions": "condition-edition-marketplace-publisher",
    "studio_adjacent": "replay-card-marketplace-publisher",
}


class RevenueModel(BaseModel):
    """Common strict immutable model config."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class RevenueProgress(RevenueModel):
    baseline_usd: float = Field(ge=0)
    doubled_target_usd: float = Field(ge=0)
    actual_usd: float = Field(ge=0)
    delta_from_baseline_usd: float
    delta_from_doubled_target_usd: float
    confidence: Confidence = "unknown"


class MonthlyRunRateMetric(RevenueModel):
    actual_usd: float = Field(default=0.0, ge=0)
    baseline_usd_by_horizon: dict[Horizon, float]
    doubled_usd_by_horizon: dict[Horizon, float]
    confidence: Confidence = "unknown"


class StreamActualInput(RevenueModel):
    cumulative_gross_usd: float = Field(default=0.0, ge=0)
    monthly_run_rate_usd: float = Field(default=0.0, ge=0)
    costs_usd: float = Field(default=0.0, ge=0)
    platform_fees_usd: float = Field(default=0.0, ge=0)
    taxes_withholding_placeholder_usd: float = Field(default=0.0, ge=0)
    processor_leakage_usd: float = Field(default=0.0, ge=0)
    confidence: Confidence = "unknown"


class FinancialActuals(RevenueModel):
    cumulative_gross_usd: float = Field(ge=0)
    monthly_run_rate_usd: float = Field(ge=0)
    costs_usd: float = Field(ge=0)
    platform_fees_usd: float = Field(ge=0)
    taxes_withholding_placeholder_usd: float = Field(ge=0)
    processor_leakage_usd: float = Field(ge=0)
    net_estimate_usd: float


class StreamMetric(RevenueModel):
    stream_id: RevenueStream
    display_name: str
    actuals: FinancialActuals
    horizon_progress: dict[Horizon, RevenueProgress]
    confidence: Confidence = "unknown"


class EngagementObservations(RevenueModel):
    kept_separate: Literal[True] = True
    may_override_grounding: Literal[False] = False
    public_event_count: int = Field(default=0, ge=0)
    views: int = Field(default=0, ge=0)
    watch_time_hours: float = Field(default=0.0, ge=0)
    support_prompt_impressions: int = Field(default=0, ge=0)


class FormatMetric(RevenueModel):
    format_id: ContentFormat
    display_name: str
    run_count: int = Field(default=0, ge=0)
    artifact_conversion_count: int = Field(default=0, ge=0)
    revenue_gross_usd: float = Field(default=0.0, ge=0)
    engagement_observations: EngagementObservations = Field(default_factory=EngagementObservations)
    grounding_quality_refs: list[str] = Field(default_factory=list)


class ReadinessMetric(RevenueModel):
    dimension: ReadinessDimension
    state: ReadinessStateName = "unknown"
    evidence_refs: list[str] = Field(default_factory=list)
    blocked_reasons: list[str] = Field(default_factory=list)
    last_checked_at: datetime | None = None


class PublicEventMetrics(RevenueModel):
    event_count: int = Field(default=0, ge=0)
    safe_to_publish_count: int = Field(default=0, ge=0)
    archive_refs_created: int = Field(default=0, ge=0)


class SupportPromptMetrics(RevenueModel):
    prompt_count: int = Field(default=0, ge=0)
    impressions: int = Field(default=0, ge=0)
    conversion_receipt_count: int = Field(default=0, ge=0)


class AggregateSupportReceiptMetrics(RevenueModel):
    receipt_count: int = Field(default=0, ge=0)
    gross_usd: float = Field(default=0.0, ge=0)
    rail_counts: dict[str, int] = Field(default_factory=dict)
    public_state_aggregate_only: Literal[True] = True
    per_receipt_public_state_allowed: Literal[False] = False


class ArtifactMetrics(RevenueModel):
    page_views: int = Field(default=0, ge=0)
    downloads: int = Field(default=0, ge=0)
    paid_conversions: int = Field(default=0, ge=0)
    refund_count: int = Field(default=0, ge=0)
    support_burden_count: int = Field(default=0, ge=0)


class LicenseMetrics(RevenueModel):
    request_count: int = Field(default=0, ge=0)
    quoted_count: int = Field(default=0, ge=0)
    accepted_count: int = Field(default=0, ge=0)
    paid_exception_count: int = Field(default=0, ge=0)


class GrantMetrics(RevenueModel):
    generated_count: int = Field(default=0, ge=0)
    submitted_count: int = Field(default=0, ge=0)
    refused_count: int = Field(default=0, ge=0)
    won_count: int = Field(default=0, ge=0)
    disbursed_usd: float = Field(default=0.0, ge=0)


class EditionMetrics(RevenueModel):
    candidate_count: int = Field(default=0, ge=0)
    published_count: int = Field(default=0, ge=0)
    gross_usd: float = Field(default=0.0, ge=0)


class YouTubeStateMetrics(RevenueModel):
    subscribers: int = Field(default=0, ge=0)
    public_watch_hours: float = Field(default=0.0, ge=0)
    shorts_views: int = Field(default=0, ge=0)
    rpm_usd: float = Field(default=0.0, ge=0)
    fan_funding_usd: float = Field(default=0.0, ge=0)
    ypp_state: YouTubePartnerState = "unknown"


class CostMetrics(RevenueModel):
    compute_usd: float = Field(default=0.0, ge=0)
    storage_usd: float = Field(default=0.0, ge=0)
    platform_fees_usd: float = Field(default=0.0, ge=0)
    taxes_withholding_placeholder_usd: float = Field(default=0.0, ge=0)
    processor_leakage_usd: float = Field(default=0.0, ge=0)


class SourceMetrics(RevenueModel):
    public_events: PublicEventMetrics = Field(default_factory=PublicEventMetrics)
    support_prompts: SupportPromptMetrics = Field(default_factory=SupportPromptMetrics)
    aggregate_support_receipts: AggregateSupportReceiptMetrics = Field(
        default_factory=AggregateSupportReceiptMetrics
    )
    artifacts: ArtifactMetrics = Field(default_factory=ArtifactMetrics)
    license_requests: LicenseMetrics = Field(default_factory=LicenseMetrics)
    grants: GrantMetrics = Field(default_factory=GrantMetrics)
    editions: EditionMetrics = Field(default_factory=EditionMetrics)
    youtube_state: YouTubeStateMetrics = Field(default_factory=YouTubeStateMetrics)
    costs: CostMetrics = Field(default_factory=CostMetrics)


class SeparationPolicy(RevenueModel):
    engagement_can_override_grounding: Literal[False] = False
    revenue_can_override_grounding: Literal[False] = False
    popularity_is_scientific_warrant: Literal[False] = False
    grounding_quality_metric_refs: list[str] = Field(default_factory=list)
    engagement_metric_refs: list[str] = Field(default_factory=list)
    revenue_metric_refs: list[str] = Field(default_factory=list)


class TrainReadableStatus(RevenueModel):
    status: TrainStatusName = "unknown"
    generated_for_task_id: Literal["revenue-metrics-dashboard"] = "revenue-metrics-dashboard"
    under_target_streams: list[RevenueStream] = Field(default_factory=list)
    under_target_horizons: list[Horizon] = Field(default_factory=list)
    next_correction_stream: RevenueStream | None = None
    next_correction_packet: str = ""
    next_correction_reason: str = ""
    blocked_by: list[str] = Field(default_factory=list)
    metric_contract_ready: Literal[True] = True


class RevenueMetricsDashboard(RevenueModel):
    schema_version: Literal[1] = 1
    generated_at: datetime
    forecast_source: Literal["corrected_content_programming_grounding_train"] = (
        "corrected_content_programming_grounding_train"
    )
    horizon_progress: dict[Horizon, RevenueProgress]
    monthly_run_rate: MonthlyRunRateMetric
    total_actuals: FinancialActuals
    streams: dict[RevenueStream, StreamMetric]
    formats: dict[ContentFormat, FormatMetric]
    readiness: dict[ReadinessDimension, ReadinessMetric]
    source_metrics: SourceMetrics
    separation_policy: SeparationPolicy
    train_status: TrainReadableStatus


def build_revenue_metrics_dashboard(
    *,
    generated_at: datetime | None = None,
    stream_actuals: Mapping[RevenueStream, StreamActualInput] | None = None,
    source_metrics: SourceMetrics | None = None,
) -> RevenueMetricsDashboard:
    """Build the corrected-forecast dashboard from aggregate actuals."""

    actuals = stream_actuals or {}
    streams = {
        stream: _stream_metric(stream, actuals.get(stream, StreamActualInput()))
        for stream in REVENUE_STREAMS
    }
    total_actuals = _total_actuals(streams)
    horizon_progress = {
        horizon: _progress(
            baseline=BASE_TARGETS[horizon],
            doubled=DOUBLED_TARGETS[horizon],
            actual=total_actuals.cumulative_gross_usd,
            confidence="unknown",
        )
        for horizon in HORIZONS
    }
    monthly_run_rate = MonthlyRunRateMetric(
        actual_usd=total_actuals.monthly_run_rate_usd,
        baseline_usd_by_horizon=RUN_RATE_BASE_TARGETS,
        doubled_usd_by_horizon=RUN_RATE_DOUBLED_TARGETS,
        confidence="unknown",
    )
    formats = {
        format_id: FormatMetric(format_id=format_id, display_name=FORMAT_DISPLAY_NAMES[format_id])
        for format_id in CONTENT_FORMATS
    }
    readiness = {
        dimension: ReadinessMetric(dimension=dimension) for dimension in READINESS_DIMENSIONS
    }
    return RevenueMetricsDashboard(
        generated_at=generated_at or datetime.now(UTC),
        horizon_progress=horizon_progress,
        monthly_run_rate=monthly_run_rate,
        total_actuals=total_actuals,
        streams=streams,
        formats=formats,
        readiness=readiness,
        source_metrics=source_metrics or SourceMetrics(),
        separation_policy=SeparationPolicy(),
        train_status=_train_status(streams, horizon_progress),
    )


def _stream_metric(stream: RevenueStream, actual: StreamActualInput) -> StreamMetric:
    financial = _financial_actuals(actual)
    return StreamMetric(
        stream_id=stream,
        display_name=STREAM_DISPLAY_NAMES[stream],
        actuals=financial,
        horizon_progress={
            horizon: _progress(
                baseline=STREAM_BASE_TARGETS[stream][horizon],
                doubled=STREAM_DOUBLED_TARGETS[stream][horizon],
                actual=financial.cumulative_gross_usd,
                confidence=actual.confidence,
            )
            for horizon in HORIZONS
        },
        confidence=actual.confidence,
    )


def _financial_actuals(actual: StreamActualInput) -> FinancialActuals:
    net = (
        actual.cumulative_gross_usd
        - actual.costs_usd
        - actual.platform_fees_usd
        - actual.taxes_withholding_placeholder_usd
        - actual.processor_leakage_usd
    )
    return FinancialActuals(
        cumulative_gross_usd=round(actual.cumulative_gross_usd, 2),
        monthly_run_rate_usd=round(actual.monthly_run_rate_usd, 2),
        costs_usd=round(actual.costs_usd, 2),
        platform_fees_usd=round(actual.platform_fees_usd, 2),
        taxes_withholding_placeholder_usd=round(actual.taxes_withholding_placeholder_usd, 2),
        processor_leakage_usd=round(actual.processor_leakage_usd, 2),
        net_estimate_usd=round(net, 2),
    )


def _total_actuals(streams: Mapping[RevenueStream, StreamMetric]) -> FinancialActuals:
    return FinancialActuals(
        cumulative_gross_usd=round(
            sum(s.actuals.cumulative_gross_usd for s in streams.values()), 2
        ),
        monthly_run_rate_usd=round(
            sum(s.actuals.monthly_run_rate_usd for s in streams.values()), 2
        ),
        costs_usd=round(sum(s.actuals.costs_usd for s in streams.values()), 2),
        platform_fees_usd=round(sum(s.actuals.platform_fees_usd for s in streams.values()), 2),
        taxes_withholding_placeholder_usd=round(
            sum(s.actuals.taxes_withholding_placeholder_usd for s in streams.values()), 2
        ),
        processor_leakage_usd=round(
            sum(s.actuals.processor_leakage_usd for s in streams.values()), 2
        ),
        net_estimate_usd=round(sum(s.actuals.net_estimate_usd for s in streams.values()), 2),
    )


def _progress(
    *,
    baseline: float,
    doubled: float,
    actual: float,
    confidence: Confidence,
) -> RevenueProgress:
    return RevenueProgress(
        baseline_usd=baseline,
        doubled_target_usd=doubled,
        actual_usd=round(actual, 2),
        delta_from_baseline_usd=round(actual - baseline, 2),
        delta_from_doubled_target_usd=round(actual - doubled, 2),
        confidence=confidence,
    )


def _train_status(
    streams: Mapping[RevenueStream, StreamMetric],
    horizon_progress: Mapping[Horizon, RevenueProgress],
) -> TrainReadableStatus:
    under_target_streams = [
        stream
        for stream, metric in streams.items()
        if any(
            progress.delta_from_baseline_usd < 0 for progress in metric.horizon_progress.values()
        )
    ]
    under_target_horizons = [
        horizon
        for horizon, progress in horizon_progress.items()
        if progress.delta_from_baseline_usd < 0
    ]
    next_stream, next_horizon, gap = _next_gap(streams)
    if next_stream is None or next_horizon is None:
        return TrainReadableStatus(
            status="on_track",
            under_target_streams=[],
            under_target_horizons=[],
            next_correction_stream=None,
            next_correction_packet="none",
            next_correction_reason="All baseline revenue targets are currently met.",
        )

    packet = NEXT_CORRECTION_PACKET_BY_STREAM[next_stream]
    return TrainReadableStatus(
        status="under_target",
        under_target_streams=under_target_streams,
        under_target_horizons=under_target_horizons,
        next_correction_stream=next_stream,
        next_correction_packet=packet,
        next_correction_reason=(
            f"{STREAM_DISPLAY_NAMES[next_stream]} is ${gap:.2f} below the "
            f"{next_horizon} baseline; run {packet} before revenue-experiment-controller."
        ),
        blocked_by=[f"{next_stream}:{next_horizon}:baseline_gap_usd={gap:.2f}"],
    )


def _next_gap(
    streams: Mapping[RevenueStream, StreamMetric],
) -> tuple[RevenueStream | None, Horizon | None, float]:
    for horizon in HORIZONS:
        gaps: list[tuple[RevenueStream, float]] = []
        for stream, metric in streams.items():
            gap = max(0.0, -metric.horizon_progress[horizon].delta_from_baseline_usd)
            if gap > 0:
                gaps.append((stream, gap))
        if gaps:
            stream, gap = max(gaps, key=lambda item: item[1])
            return stream, horizon, gap
    return None, None, 0.0


__all__ = [
    "BASE_TARGETS",
    "CONTENT_FORMATS",
    "DOUBLED_TARGETS",
    "HORIZONS",
    "READINESS_DIMENSIONS",
    "REVENUE_STREAMS",
    "STREAM_BASE_TARGETS",
    "AggregateSupportReceiptMetrics",
    "ArtifactMetrics",
    "CostMetrics",
    "EditionMetrics",
    "EngagementObservations",
    "FinancialActuals",
    "FormatMetric",
    "GrantMetrics",
    "LicenseMetrics",
    "MonthlyRunRateMetric",
    "PublicEventMetrics",
    "ReadinessMetric",
    "RevenueMetricsDashboard",
    "RevenueProgress",
    "SeparationPolicy",
    "SourceMetrics",
    "StreamActualInput",
    "StreamMetric",
    "SupportPromptMetrics",
    "TrainReadableStatus",
    "YouTubeStateMetrics",
    "build_revenue_metrics_dashboard",
]
