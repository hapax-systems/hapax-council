"""Contract tests for the n=1 methodology dossier."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC = REPO_ROOT / "docs" / "research" / "2026-04-30-n1-methodology-dossier.md"
SCHEMA = REPO_ROOT / "schemas" / "n1-methodology-dossier.schema.json"
DOSSIER = REPO_ROOT / "config" / "n1-methodology-dossier.json"
CONVERSION_MATRIX = REPO_ROOT / "config" / "conversion-target-readiness-threshold-matrix.json"


def _json(path: Path) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def _validator() -> jsonschema.Draft202012Validator:
    schema = _json(SCHEMA)
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def _dossier() -> dict[str, Any]:
    return _json(DOSSIER)


def test_schema_validates_dossier_payload() -> None:
    payload = _dossier()

    _validator().validate(payload)

    assert payload["schema_version"] == 1
    assert payload["schema_ref"] == "schemas/n1-methodology-dossier.schema.json"
    assert payload["mode_ceiling"] == "private"
    assert payload["max_public_claim"] == "provisional"


def test_category_statements_pin_public_language_and_private_ceiling() -> None:
    statements = _dossier()["category_statements"]

    assert statements["primary_category"] == "single-operator autonomous grounding lab"
    assert statements["alternate_category"] == "single-operator live epistemic lab"
    assert "real life" in statements["public_short"]
    assert "does not authorize" in statements["private_construction_note"]


def test_near_neighbor_table_covers_generic_category_failures() -> None:
    payload = _dossier()
    schema = _json(SCHEMA)
    neighbors = {row["category"]: row for row in payload["near_neighbor_comparisons"]}

    assert set(neighbors) == set(schema["x-required_near_neighbors"])
    for row in neighbors.values():
        assert row["what_it_shares"]
        assert row["why_generic_category_fails"]
        assert row["retained_signal"]


def test_scientific_posture_is_n1_sced_best_not_population_claims() -> None:
    posture = _dossier()["scientific_posture"]

    assert posture["n_size"] == 1
    assert {"SCED", "BEST"} <= set(posture["methods"])
    assert posture["broad_population_claims_allowed"] is False
    assert "broad-population generalization" in posture["forbidden_claims"]
    assert posture["sced_best_framing"]["uncertainty_language_required"] is True
    assert "one operator" in posture["sced_best_framing"]["case_scope"]


def test_automation_doctrine_bans_hidden_recurring_operator_labor() -> None:
    doctrine = _dossier()["automation_doctrine"]

    assert doctrine["recurring_manual_labor_allowed"] is False
    assert doctrine["support_perks_allowed"] is False
    assert doctrine["hidden_operator_service_allowed"] is False
    assert doctrine["manual_community_moderation_allowed"] is False
    assert set(doctrine["classes"]) == {
        "AUTO",
        "BOOTSTRAP",
        "LEGAL_ATTEST",
        "GUARDED",
        "REFUSAL_ARTIFACT",
    }
    assert "consulting as recurring service" in doctrine["refusal_conversions"]


def test_structured_diagrams_cover_required_system_shapes() -> None:
    payload = _dossier()
    schema = _json(SCHEMA)
    diagrams = {diagram["diagram_id"]: diagram for diagram in payload["structured_diagrams"]}

    assert set(diagrams) == set(schema["x-required_diagrams"])
    for diagram in diagrams.values():
        assert len(diagram["nodes"]) >= 3
        assert len(diagram["edges"]) >= 2
        assert "grant" in diagram["claim_limit"] or "cannot" in diagram["claim_limit"]

    truth_spine = diagrams["truth_spine"]
    assert "provenance" in truth_spine["nodes"]
    assert "egress" in truth_spine["nodes"]
    assert "public claim gate" in truth_spine["nodes"]


def test_reuse_profiles_match_conversion_matrix_and_fail_closed_for_public_use() -> None:
    payload = _dossier()
    schema = _json(SCHEMA)
    matrix = _json(CONVERSION_MATRIX)
    profile_by_id = {profile["profile_id"]: profile for profile in payload["reuse_profiles"]}
    target_families = {family["target_family_id"]: family for family in matrix["target_families"]}

    assert set(profile_by_id) == set(schema["x-required_reuse_profiles"])

    required_for_public_or_money = {
        "conversion-target-readiness-threshold-matrix",
        "provenance/egress",
        "public-claim gate",
        "privacy/rights gate",
        "no-hidden-operator-labor gate",
    }

    for profile in profile_by_id.values():
        target_family = target_families[profile["target_family_ref"]]
        assert set(profile["allowed_states"]) <= set(target_family["allowed_states"])
        assert set(profile["required_gate_refs"]) >= {
            "conversion-target-readiness-threshold-matrix",
            "provenance/egress",
            "public-claim gate",
        }
        if profile["public_release_allowed"] or profile["monetization_allowed"]:
            assert set(profile["required_gate_refs"]) >= required_for_public_or_money

    grants = profile_by_id["grants_fellowships"]
    assert grants["public_release_allowed"] is False
    assert grants["monetization_allowed"] is False
    assert grants["operator_attestation_required"] is True
    assert "private-evidence" in grants["allowed_states"]


def test_anti_overclaim_and_public_private_boundary_are_explicit() -> None:
    payload = _dossier()
    policy = payload["anti_overclaim_policy"]
    boundary = payload["public_private_boundary"]

    for key, value in policy.items():
        if key != "notes":
            assert value is False

    assert boundary["private_dossier_can_prepare"] is True
    assert boundary["public_positioning_requires_gates"] is True
    assert boundary["public_or_money_use_requires_conversion_matrix"] is True
    assert {
        "public release authority",
        "monetization readiness",
        "truth authority",
        "broad-population claim",
    } <= set(boundary["forbidden_without_gates"])


def test_markdown_dossier_references_machine_contract_and_public_private_boundary() -> None:
    body = DOC.read_text(encoding="utf-8")

    assert "config/n1-methodology-dossier.json" in body
    assert "schemas/n1-methodology-dossier.schema.json" in body
    assert "single-operator autonomous grounding lab" in body
    assert "single-operator live epistemic lab" in body
    assert "Private Construction Boundary" in body
    assert "conversion-target-readiness-threshold-matrix" in body
    assert "provenance/egress" in body
    assert "public-claim gates" in body
