"""Regression pins for the revenue metrics dashboard contract."""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = (
    REPO_ROOT / "docs" / "superpowers" / "specs" / "2026-04-29-revenue-metrics-dashboard-design.md"
)
SCHEMA = REPO_ROOT / "schemas" / "revenue-metrics-dashboard.schema.json"


def _body() -> str:
    return SPEC.read_text(encoding="utf-8")


def _schema() -> dict[str, object]:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def test_spec_covers_required_contract_sections() -> None:
    body = _body()

    for heading in (
        "## Forecast Source",
        "## Dashboard Payload",
        "## Stream Dimensions",
        "## Format Dimensions",
        "## Readiness Dimensions",
        "## Source Metrics",
        "## Grounding Separation Policy",
        "## Train-Readable Status",
        "## Downstream Unblockers",
    ):
        assert heading in body


def test_schema_top_level_fields_are_train_readable() -> None:
    schema = _schema()
    required = set(schema["required"])
    properties = schema["properties"]

    for field in (
        "horizon_progress",
        "monthly_run_rate",
        "total_actuals",
        "streams",
        "formats",
        "readiness",
        "source_metrics",
        "separation_policy",
        "train_status",
    ):
        assert field in required
        assert field in properties


def test_corrected_forecast_values_are_pinned_in_schema_and_spec() -> None:
    schema = _schema()
    forecast = schema["x-corrected_content_programming_forecast"]

    assert forecast["baseline"] == {
        "1_month": 800,
        "6_months": 64_000,
        "1_year": 220_000,
        "2_years": 715_000,
    }
    assert forecast["doubled"] == {
        "1_month": 1_600,
        "6_months": 128_000,
        "1_year": 440_000,
        "2_years": 1_430_000,
    }

    body = _body()
    for text in ("$800", "$64,000", "$220,000", "$715,000", "$1,430,000"):
        assert text in body


def test_schema_names_required_stream_format_and_readiness_dimensions() -> None:
    schema = _schema()

    streams = set(schema["$defs"]["revenue_stream"]["enum"])
    formats = set(schema["$defs"]["content_format"]["enum"])
    readiness = set(schema["$defs"]["readiness_dimension"]["enum"])

    assert streams == {
        "platform_native",
        "support_rails",
        "grants_fellowships",
        "research_artifacts_licensing",
        "product_tool_ip",
        "consulting_by_artifact",
        "aesthetic_editions",
        "studio_adjacent",
    }
    assert formats == {
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
    }
    assert readiness == {
        "safe_to_broadcast",
        "safe_to_archive",
        "safe_to_promote",
        "safe_to_monetize",
        "safe_to_publish_offer",
        "safe_to_publish_artifact",
        "safe_to_accept_payment",
    }


def test_source_metrics_and_support_privacy_are_structural() -> None:
    schema = _schema()
    source_required = set(schema["$defs"]["source_metrics"]["required"])
    support = schema["$defs"]["aggregate_support_receipts"]["properties"]

    assert source_required == {
        "public_events",
        "support_prompts",
        "aggregate_support_receipts",
        "artifacts",
        "license_requests",
        "grants",
        "editions",
        "youtube_state",
        "costs",
    }
    assert support["public_state_aggregate_only"]["const"] is True
    assert support["per_receipt_public_state_allowed"]["const"] is False

    text = json.dumps(schema).lower()
    for forbidden in ("payer", "per_payer", "sender_excerpt", "message_text", "handle"):
        assert forbidden not in text

    body = _body()
    assert "aggregate-only" in body
    assert "payer identity, names, handles, message text, or per-payer history" in body


def test_engagement_revenue_and_grounding_are_pinned_separate() -> None:
    schema = _schema()
    separation = schema["$defs"]["separation_policy"]["properties"]
    engagement = schema["$defs"]["engagement_observations"]["properties"]

    assert separation["engagement_can_override_grounding"]["const"] is False
    assert separation["revenue_can_override_grounding"]["const"] is False
    assert separation["popularity_is_scientific_warrant"]["const"] is False
    assert engagement["kept_separate"]["const"] is True
    assert engagement["may_override_grounding"]["const"] is False

    body = _body()
    for phrase in (
        "They are never scientific warrant",
        "`popularity_is_scientific_warrant` is always `false`",
        "not view counts, receipt counts, or platform revenue",
    ):
        assert phrase in body


def test_example_payload_is_parseable_and_train_status_ready() -> None:
    body = _body()
    match = re.search(r"```json\n(?P<payload>.*?)\n```", body, re.DOTALL)
    assert match, "example RevenueMetricsDashboard JSON block missing"

    payload = json.loads(match.group("payload"))

    assert payload["schema_version"] == 1
    assert payload["forecast_source"] == "corrected_content_programming_grounding_train"
    assert payload["horizon_progress"]["1_month"]["baseline_usd"] == 800
    assert payload["horizon_progress"]["2_years"]["doubled_target_usd"] == 1_430_000
    assert (
        payload["source_metrics"]["aggregate_support_receipts"]["public_state_aggregate_only"]
        is True
    )
    assert payload["separation_policy"]["engagement_can_override_grounding"] is False
    assert payload["train_status"]["next_correction_packet"] == "artifact-catalog-release-workflow"
