"""Regression pins for the trend/current-event constraint gate contract."""

from __future__ import annotations

import json
from pathlib import Path

from shared.trend_current_event_gate import GateAction, GateInfraction, validate_policy

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = (
    REPO_ROOT
    / "docs"
    / "superpowers"
    / "specs"
    / "2026-04-29-trend-current-event-constraint-gate-design.md"
)
SCHEMA = REPO_ROOT / "schemas" / "trend-current-event-constraint-gate.schema.json"
CONFIG = REPO_ROOT / "config" / "trend-current-event-constraint-gate.json"


def _body() -> str:
    return SPEC.read_text(encoding="utf-8")


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_spec_covers_required_contract_sections() -> None:
    body = _body()

    for heading in (
        "## Machine-Readable Contract",
        "## Gate Inputs",
        "## Freshness And Corroboration",
        "## Under-24H Policy",
        "## Sensitive Events",
        "## Uncertainty Copy",
        "## Trend Decay And Source Bias",
        "## Gate Actions",
        "## Downstream Contract",
        "## Verification",
    ):
        assert heading in body


def test_schema_and_config_are_parseable_and_policy_is_conservative() -> None:
    schema = _json(SCHEMA)
    config = _json(CONFIG)

    assert schema["title"] == "TrendCurrentEventConstraintGatePolicy"
    assert config["schema_version"] == 1
    assert validate_policy(config) == []

    policy = schema["properties"]["global_policy"]["properties"]
    assert policy["trend_as_truth_allowed"]["const"] is False
    assert policy["official_or_primary_source_required"]["const"] is True
    assert policy["timestamped_freshness_required"]["const"] is True
    assert policy["uncertainty_language_required"]["const"] is True
    assert policy["under_24h_definitive_ranking_allowed"]["const"] is False
    assert policy["sensitive_event_monetization_allowed"]["const"] is False


def test_config_names_required_actions_and_infractions() -> None:
    config = _json(CONFIG)

    assert {item["action"] for item in config["actions"]} == {action.value for action in GateAction}
    assert set(config["infractions"]) == {infraction.value for infraction in GateInfraction}

    assert config["freshness_policy"]["trend_source_public_ttl_s"] <= 1800
    assert config["freshness_policy"]["current_event_public_ttl_s"] <= 3600
    assert config["event_age_policy"]["under_24h_threshold_s"] == 86400
    assert config["event_age_policy"]["under_24h_default_action"] == "downgrade_to_watch"
    assert "ranking" in config["event_age_policy"]["blocked_under_24h_format_families"]


def test_sensitive_uncertainty_and_scoring_policies_are_pinned() -> None:
    config = _json(CONFIG)

    sensitivity = config["sensitivity_policy"]
    assert sensitivity["edsa_context_required"] is True
    assert sensitivity["monetization_allowed"] is False
    assert sensitivity["default_sensitive_action"] == "force_refusal_format"
    assert "health" in sensitivity["sensitive_categories"]
    assert "identifiable_persons" in sensitivity["sensitive_categories"]

    uncertainty = config["uncertainty_policy"]
    assert uncertainty["title_uncertainty_required"] is True
    assert uncertainty["description_uncertainty_required"] is True
    assert "uncertainty_language" in uncertainty["required_copy_fields"]

    features = {item["feature_name"]: item for item in config["scoring_features"]}
    assert features["trend_decay_score"]["truth_warrant"] is False
    assert features["source_bias_score"]["truth_warrant"] is False
    assert features["trend_decay_score"]["required_for_public_claim"] is True
    assert features["source_bias_score"]["required_for_public_claim"] is True


def test_downstream_contract_blocks_candidate_discovery_and_preserves_fields() -> None:
    config = _json(CONFIG)
    downstream = config["downstream_contract"]

    assert "content-candidate-discovery-daemon" in downstream["blocks"]
    assert "content-opportunity-model" in downstream["feeds"]
    assert "format-grounding-evaluator" in downstream["feeds"]
    assert "grounding-commitment-gate" in downstream["feeds"]

    for field in (
        "action",
        "infractions",
        "blockers",
        "trend_decay_score",
        "source_bias_score",
        "primary_or_official_source_refs",
    ):
        assert field in downstream["must_preserve_fields"]


def test_public_gate_artifacts_do_not_embed_operator_home_paths() -> None:
    for path in (SPEC, SCHEMA, CONFIG):
        text = path.read_text(encoding="utf-8")
        assert "/home/hapax" not in text
        assert "local:/home/" not in text
