"""Tests for the revenue metrics dashboard model."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from pydantic import ValidationError

from shared.revenue_metrics_dashboard import (
    BASE_TARGETS,
    CONTENT_FORMATS,
    DOUBLED_TARGETS,
    FORMAT_LEARNING_OUTCOMES,
    PUBLIC_PRIVATE_MODES,
    READINESS_DIMENSIONS,
    REVENUE_STREAMS,
    RIGHTS_CLASSES,
    SOURCE_CLASSES,
    AggregateSupportReceiptMetrics,
    SourceMetrics,
    StreamActualInput,
    build_revenue_metrics_dashboard,
)


def test_corrected_content_programming_targets_are_seeded() -> None:
    dashboard = build_revenue_metrics_dashboard(generated_at=datetime(2026, 4, 29, tzinfo=UTC))

    assert BASE_TARGETS == {
        "1_month": 800.0,
        "6_months": 64_000.0,
        "1_year": 220_000.0,
        "2_years": 715_000.0,
    }
    assert DOUBLED_TARGETS == {
        "1_month": 1_600.0,
        "6_months": 128_000.0,
        "1_year": 440_000.0,
        "2_years": 1_430_000.0,
    }
    assert dashboard.horizon_progress["1_month"].baseline_usd == 800.0
    assert dashboard.horizon_progress["1_month"].doubled_target_usd == 1_600.0
    assert dashboard.monthly_run_rate.baseline_usd_by_horizon["6_months"] == 10_666.67


def test_all_required_dimensions_are_present() -> None:
    dashboard = build_revenue_metrics_dashboard()

    assert set(dashboard.streams) == set(REVENUE_STREAMS)
    assert set(dashboard.formats) == set(CONTENT_FORMATS)
    assert set(dashboard.readiness) == set(READINESS_DIMENSIONS)
    tier_list = dashboard.formats["tier_list"]
    assert tier_list.format_family == "ranking_ordering"
    assert set(tier_list.source_class_counts) == set(SOURCE_CLASSES)
    assert set(tier_list.rights_class_counts) == set(RIGHTS_CLASSES)
    assert set(tier_list.public_private_mode_counts) == set(PUBLIC_PRIVATE_MODES)
    assert set(tier_list.learning_by_outcome) == set(FORMAT_LEARNING_OUTCOMES)
    assert dashboard.source_metrics.public_events.event_count == 0
    assert dashboard.source_metrics.support_prompts.impressions == 0
    assert dashboard.source_metrics.aggregate_support_receipts.public_state_aggregate_only is True
    assert (
        dashboard.source_metrics.aggregate_support_receipts.per_receipt_public_state_allowed
        is False
    )


def test_stream_actuals_compute_net_estimate_and_deltas() -> None:
    dashboard = build_revenue_metrics_dashboard(
        stream_actuals={
            "support_rails": StreamActualInput(
                cumulative_gross_usd=250.0,
                monthly_run_rate_usd=250.0,
                costs_usd=10.0,
                platform_fees_usd=5.0,
                taxes_withholding_placeholder_usd=50.0,
                processor_leakage_usd=2.5,
                confidence="low",
            )
        }
    )

    support = dashboard.streams["support_rails"]
    assert support.actuals.net_estimate_usd == 182.5
    assert support.horizon_progress["1_month"].delta_from_baseline_usd == 50.0
    assert support.horizon_progress["1_month"].delta_from_doubled_target_usd == -150.0
    assert dashboard.total_actuals.cumulative_gross_usd == 250.0
    assert dashboard.total_actuals.net_estimate_usd == 182.5


def test_train_status_names_under_target_stream_and_packet() -> None:
    dashboard = build_revenue_metrics_dashboard(
        stream_actuals={
            "research_artifacts_licensing": StreamActualInput(cumulative_gross_usd=400.0),
            "product_tool_ip": StreamActualInput(cumulative_gross_usd=150.0),
            "aesthetic_editions": StreamActualInput(cumulative_gross_usd=50.0),
        }
    )

    assert dashboard.train_status.status == "under_target"
    assert "support_rails" in dashboard.train_status.under_target_streams
    assert dashboard.train_status.next_correction_stream == "support_rails"
    assert dashboard.train_status.next_correction_packet == "public-offer-page-generator-no-perk"
    assert "before revenue-experiment-controller" in dashboard.train_status.next_correction_reason


def test_revenue_and_engagement_cannot_override_grounding() -> None:
    dashboard = build_revenue_metrics_dashboard()

    assert dashboard.separation_policy.engagement_can_override_grounding is False
    assert dashboard.separation_policy.revenue_can_override_grounding is False
    assert dashboard.separation_policy.popularity_is_scientific_warrant is False
    for metric in dashboard.formats.values():
        assert 0 <= metric.grounding_score <= 1
        assert 0 <= metric.refusal_rate <= 1
        assert 0 <= metric.correction_rate <= 1
        assert 0 <= metric.artifact_conversion_rate <= 1
        assert metric.youtube_content_revenue_usd == 0.0
        assert metric.engagement_observations.kept_separate is True
        assert metric.engagement_observations.may_override_grounding is False
        assert metric.engagement_observations.public_state_aggregate_only is True
        assert metric.engagement_observations.per_audience_member_public_state_allowed is False
        assert metric.n1_weirdness_value_stream.audience_response_is_scientific_warrant is False
        for bucket in metric.learning_by_outcome.values():
            assert bucket.engagement_can_override_grounding is False
            assert bucket.revenue_can_override_grounding is False


def test_format_learning_buckets_track_outcomes_separately() -> None:
    dashboard = build_revenue_metrics_dashboard()
    format_metric = dashboard.formats["react_commentary"]

    assert format_metric.format_family == "attention_commentary"
    assert format_metric.learning_by_outcome["refused"].outcome == "refused"
    assert format_metric.learning_by_outcome["corrected"].outcome == "corrected"
    assert format_metric.learning_by_outcome["private"].outcome == "private"
    assert format_metric.learning_by_outcome["dry_run"].outcome == "dry_run"
    assert format_metric.learning_by_outcome["public_archive"].outcome == "public_archive"
    assert format_metric.learning_by_outcome["public_live"].outcome == "public_live"
    assert format_metric.learning_by_outcome["monetized"].outcome == "monetized"
    assert format_metric.n1_weirdness_value_stream.dimension_id == "n1_weirdness"
    assert format_metric.n1_weirdness_value_stream.tracked is True


def test_support_receipts_are_aggregate_only() -> None:
    metrics = SourceMetrics(
        aggregate_support_receipts=AggregateSupportReceiptMetrics(
            receipt_count=3,
            gross_usd=42.0,
            rail_counts={"lightning": 2, "liberapay": 1},
        )
    )
    dashboard = build_revenue_metrics_dashboard(source_metrics=metrics)

    support = dashboard.source_metrics.aggregate_support_receipts
    assert support.receipt_count == 3
    assert support.gross_usd == 42.0
    assert support.rail_counts == {"lightning": 2, "liberapay": 1}
    assert support.public_state_aggregate_only is True
    assert support.per_receipt_public_state_allowed is False

    schema_text = json.dumps(AggregateSupportReceiptMetrics.model_json_schema()).lower()
    for forbidden in (
        "payer",
        "per_payer",
        "sender_excerpt",
        "message_text",
        "handle",
        "name",
    ):
        assert forbidden not in schema_text


def test_extra_public_receipt_fields_are_rejected() -> None:
    try:
        AggregateSupportReceiptMetrics.model_validate(
            {
                "receipt_count": 1,
                "gross_usd": 5.0,
                "rail_counts": {"lightning": 1},
                "public_state_aggregate_only": True,
                "per_receipt_public_state_allowed": False,
                "sender_excerpt": "not allowed",
            }
        )
    except ValidationError as exc:
        assert "sender_excerpt" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("extra receipt detail field should be rejected")
