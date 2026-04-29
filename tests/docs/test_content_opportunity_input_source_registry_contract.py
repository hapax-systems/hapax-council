"""Regression pins for the content-opportunity input-source registry."""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = (
    REPO_ROOT
    / "docs"
    / "superpowers"
    / "specs"
    / "2026-04-29-content-opportunity-input-source-registry-design.md"
)
SCHEMA = REPO_ROOT / "schemas" / "content-opportunity-input-source-registry.schema.json"

REQUIRED_SOURCE_CLASSES = {
    "local_state",
    "owned_media",
    "platform_native_state",
    "trend_sources",
    "curated_watchlists",
    "public_web_references",
    "ambient_aggregate_audience",
    "internal_anomalies",
}


def _body() -> str:
    return SPEC.read_text(encoding="utf-8")


def _schema() -> dict[str, object]:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def _example_registry() -> dict[str, object]:
    body = _body()
    match = re.search(r"```json\n(?P<payload>.*?)\n```", body, re.DOTALL)
    assert match, "example ContentOpportunityInputSourceRegistry JSON block missing"
    return json.loads(match.group("payload"))


def _records_by_class() -> dict[str, dict[str, object]]:
    registry = _example_registry()
    records = registry["source_classes"]
    return {record["source_class"]: record for record in records}


def test_spec_covers_required_contract_sections() -> None:
    body = _body()

    for heading in (
        "## Machine-Readable Registry",
        "## Source Class Registry",
        "## Source Freshness And Provenance",
        "## Rights Privacy And Dry-Run Defaults",
        "## No Request Queues Or Supporter Control",
        "## Trend And Current Event Policy",
        "## Source Priors",
        "## Candidate Output Contract",
    ):
        assert heading in body


def test_schema_has_required_registry_fields_and_global_policy() -> None:
    schema = _schema()
    required = set(schema["required"])
    properties = schema["properties"]

    for field in (
        "schema_version",
        "registry_id",
        "declared_at",
        "producer",
        "global_policy",
        "source_classes",
    ):
        assert field in required
        assert field in properties

    policy = properties["global_policy"]["properties"]
    assert policy["single_operator_only"]["const"] is True
    assert policy["supporter_controlled_programming_allowed"]["const"] is False
    assert policy["per_person_request_queues_allowed"]["const"] is False
    assert policy["aggregate_audience_only"]["const"] is True
    assert policy["trend_as_truth_allowed"]["const"] is False
    assert policy["official_current_source_required_for_current_event"]["const"] is True
    assert policy["missing_freshness_blocks_public_claim"]["const"] is True


def test_schema_names_all_required_source_classes_and_controls() -> None:
    schema = _schema()
    source_classes = set(schema["$defs"]["source_class"]["enum"])
    record_required = set(schema["$defs"]["source_class_record"]["required"])

    assert source_classes == REQUIRED_SOURCE_CLASSES

    for field in (
        "source_class",
        "freshness",
        "provenance_requirements",
        "quota_rate_limits",
        "rights_assumptions",
        "privacy_posture",
        "source_prior_fields",
        "allowed_public_private_modes",
        "private_dry_run_only",
        "public_claim_requirements",
        "official_current_source_policy",
    ):
        assert field in record_required


def test_example_registry_is_parseable_complete_and_conservative() -> None:
    registry = _example_registry()
    records = _records_by_class()

    assert registry["schema_version"] == 1
    assert re.match(r"^[a-z][a-z0-9_:-]*$", registry["registry_id"])
    assert set(records) == REQUIRED_SOURCE_CLASSES

    global_policy = registry["global_policy"]
    assert global_policy["single_operator_only"] is True
    assert global_policy["supporter_controlled_programming_allowed"] is False
    assert global_policy["per_person_request_queues_allowed"] is False
    assert global_policy["aggregate_audience_only"] is True
    assert global_policy["trend_as_truth_allowed"] is False

    for forbidden_use in (
        "per_person_request_queue",
        "supporter_controlled_programming",
        "supporter_priority_queue",
        "personalized_supporter_perk_content",
        "identifiable_person_audience_targeting",
    ):
        assert forbidden_use in global_policy["forbidden_uses"]
        assert f"`{forbidden_use}`" in _body()


def test_each_source_class_declares_freshness_provenance_quotas_and_priors() -> None:
    records = _records_by_class()

    for source_class, record in records.items():
        freshness = record["freshness"]
        quota = record["quota_rate_limits"]

        assert freshness["default_ttl_s"] > 0, source_class
        assert freshness["public_claim_ttl_s"] > 0, source_class
        assert freshness["watermark_required"] is True, source_class
        assert freshness["stale_behavior"] in {
            "block_public_claim",
            "downgrade_to_dry_run",
            "private_only",
            "refresh_required",
        }

        assert record["provenance_requirements"], source_class
        assert quota["quota_owner"], source_class
        assert quota["rate_limit_ref"], source_class
        assert quota["failure_mode"], source_class
        assert record["rights_assumptions"], source_class
        assert record["privacy_posture"], source_class
        assert record["source_prior_fields"], source_class
        assert record["public_claim_requirements"], source_class

        for prior in record["source_prior_fields"]:
            assert prior["field_name"], source_class
            assert prior["meaning"], source_class
            assert 0 <= prior["initial_value"] <= 1, source_class
            assert prior["update_signal"], source_class


def test_private_dry_run_only_sources_cannot_directly_emit_public_opportunities() -> None:
    records = _records_by_class()

    for source_class in ("ambient_aggregate_audience", "internal_anomalies"):
        record = records[source_class]
        assert record["private_dry_run_only"] is True
        assert set(record["allowed_public_private_modes"]) == {"private", "dry_run"}

    body = _body()
    for phrase in (
        "private/dry-run-only",
        "cannot directly create public-live",
        "cannot directly create public-live, public-archive, or",
    ):
        assert phrase in body


def test_trend_and_current_event_sources_require_official_current_sources() -> None:
    records = _records_by_class()

    trend_policy = records["trend_sources"]["official_current_source_policy"]
    assert trend_policy["required"] is True
    assert trend_policy["primary_source_required"] is True
    assert trend_policy["recency_label_required"] is True
    assert trend_policy["sensitivity_gate_required"] is True
    assert trend_policy["max_source_age_s"] <= 86400
    assert "trend_candidate" in trend_policy["applies_to"]
    assert "current_event_claim" in trend_policy["applies_to"]

    web_policy = records["public_web_references"]["official_current_source_policy"]
    assert web_policy["required"] is True
    assert web_policy["primary_source_required"] is True
    assert "current_event_claim" in web_policy["applies_to"]

    body = _body()
    for phrase in (
        "recency label required",
        "primary or official source required",
        "trend/currentness may route attention but may not become a truth warrant",
    ):
        assert phrase in body


def test_candidate_output_contract_preserves_source_fields_downstream() -> None:
    body = _body()

    for phrase in (
        "source class",
        "source ref",
        "freshness status and TTL",
        "provenance refs",
        "rights assumption",
        "privacy posture",
        "source prior fields",
        "public/private mode ceiling",
        "official/current-source evidence",
        "forbidden-use check results",
        "may not silently drop",
    ):
        assert phrase in body
