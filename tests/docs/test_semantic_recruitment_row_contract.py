"""Schema contract tests for formal semantic recruitment rows."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "schemas" / "semantic-recruitment-row.schema.json"
FIXTURES = REPO_ROOT / "config" / "semantic-recruitment-fixtures.json"


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_semantic_recruitment_schema_validates_projection_fixtures() -> None:
    schema = _json(SCHEMA)
    fixtures = _json(FIXTURES)

    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(fixtures)

    assert schema["title"] == "SemanticRecruitmentFixtureSet"
    assert fixtures["schema_version"] == 1


def test_schema_pins_kind_level_relation_and_projection_fields() -> None:
    schema = _json(SCHEMA)
    row = schema["$defs"]["SemanticRecruitmentRow"]
    required = set(row["required"])

    for field in (
        "row_id",
        "relatum_id",
        "kind",
        "abstraction_level",
        "recruitable",
        "lifecycle",
        "semantic_descriptions",
        "domain_tags",
        "family_tags",
        "relations",
        "authority_ceiling",
        "claim_types_allowed",
        "privacy_label",
        "consent_label",
        "required_clearance",
        "rights_label",
        "content_risk",
        "monetization_risk",
        "witness_contract_id",
        "projection",
        "aliases",
    ):
        assert field in required

    assert set(schema["$defs"]["SemanticKind"]["enum"]) >= {
        "Entity",
        "Process",
        "State",
        "Event",
        "Signal",
        "Capability",
        "Affordance",
        "Substrate",
        "Representation",
        "Constraint",
    }
    assert set(schema["$defs"]["SemanticLevel"]["enum"]) == {"L0", "L1", "L2", "L3", "L4"}
    assert set(schema["$defs"]["RelationPredicate"]["enum"]) >= {
        "realizes",
        "implemented_by",
        "modulates",
        "composes_into",
        "vetoes",
        "biases",
        "witnesses",
        "decommissions",
    }


def test_schema_pins_lattice_enums_and_structured_tags() -> None:
    schema = _json(SCHEMA)

    assert schema["$defs"]["ConsentLabel"]["enum"] == [
        "none",
        "operator_self",
        "person_adjacent",
        "identifiable_person",
        "public_broadcast",
    ]
    assert set(schema["$defs"]["ContentRisk"]["enum"]) >= {
        "unknown",
        "tier_0_owned",
        "tier_4_risky",
    }
    assert schema["$defs"]["MonetizationRisk"]["enum"] == [
        "unknown",
        "none",
        "low",
        "medium",
        "high",
    ]
    assert schema["$defs"]["AuthorityCeiling"]["enum"][-1] == "public_gate_required"

    family_props = schema["$defs"]["FamilyTag"]["properties"]
    domain_props = schema["$defs"]["DomainTag"]["properties"]
    assert {"family", "intent_binding", "dispatch_required"} <= set(family_props)
    assert {"domain", "subdomain"} <= set(domain_props)


def test_fixture_contract_avoids_local_absolute_source_paths() -> None:
    fixture_text = FIXTURES.read_text(encoding="utf-8")

    assert "/home/hapax/" not in fixture_text
    assert "multi_user" not in fixture_text
    assert "auth_provider" not in fixture_text
