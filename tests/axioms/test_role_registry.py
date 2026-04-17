"""Tests for axioms/roles/registry.yaml (LRR Phase 7 §4.3).

Validates the shape of the thick-position role registry so that adding
or removing a role without updating dependent tests becomes a loud
failure. Registry is pure data — tests enforce the schema invariants
instead of a Pydantic model, which would over-specify too early.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REGISTRY_PATH = Path(__file__).parent.parent.parent / "axioms" / "roles" / "registry.yaml"

VALID_LAYERS = {"structural", "institutional", "relational"}

EXPECTED_ROLE_IDS = {
    # structural (2)
    "executive-function-substrate",
    "research-subject-and-instrument",
    # institutional (4)
    "executive-function-assistant",
    "livestream-host",
    "research-participant",
    "household-inhabitant",
    # relational (2)
    "partner-in-conversation",
    "addressee-facing",
}

# Axioms referenced in the registry must exist in axioms/registry.yaml
AXIOM_REGISTRY_PATH = Path(__file__).parent.parent.parent / "axioms" / "registry.yaml"


@pytest.fixture(scope="module")
def registry() -> dict:
    return yaml.safe_load(REGISTRY_PATH.read_text())


@pytest.fixture(scope="module")
def known_axiom_ids() -> set[str]:
    data = yaml.safe_load(AXIOM_REGISTRY_PATH.read_text())
    return {a["id"] for a in data["axioms"]}


class TestRegistryStructure:
    def test_version_is_int(self, registry):
        assert isinstance(registry["version"], int)
        assert registry["version"] >= 1

    def test_has_eight_roles(self, registry):
        assert len(registry["roles"]) == 8

    def test_role_ids_match_expected(self, registry):
        actual = {r["id"] for r in registry["roles"]}
        assert actual == EXPECTED_ROLE_IDS, (
            f"Role IDs drift — added {actual - EXPECTED_ROLE_IDS}, "
            f"removed {EXPECTED_ROLE_IDS - actual}. If intentional, "
            f"update EXPECTED_ROLE_IDS in this test; adding or removing "
            f"a thick position is a Phase 7 amendment moment."
        )

    def test_no_duplicate_ids(self, registry):
        ids = [r["id"] for r in registry["roles"]]
        assert len(ids) == len(set(ids))


class TestLayerDistribution:
    def test_structural_has_two(self, registry):
        structural = [r for r in registry["roles"] if r["layer"] == "structural"]
        assert len(structural) == 2

    def test_institutional_has_four(self, registry):
        inst = [r for r in registry["roles"] if r["layer"] == "institutional"]
        assert len(inst) == 4

    def test_relational_has_two(self, registry):
        rel = [r for r in registry["roles"] if r["layer"] == "relational"]
        assert len(rel) == 2

    def test_no_functional_layer(self, registry):
        """Phase 7 reframe dissolved the functional layer. Regression test
        to catch accidental re-introduction."""
        layers = {r["layer"] for r in registry["roles"]}
        assert "functional" not in layers

    def test_all_layers_recognized(self, registry):
        for role in registry["roles"]:
            assert role["layer"] in VALID_LAYERS


class TestRoleFields:
    def test_required_fields_present(self, registry):
        required = {"id", "layer", "axiom_anchors", "whom_to", "answers_for", "description"}
        for role in registry["roles"]:
            missing = required - set(role.keys())
            assert not missing, f"role {role['id']} missing {missing}"

    def test_answers_for_non_empty(self, registry):
        for role in registry["roles"]:
            assert isinstance(role["answers_for"], list)
            assert len(role["answers_for"]) > 0, f"role {role['id']} has empty answers_for"

    def test_description_non_empty(self, registry):
        for role in registry["roles"]:
            assert role["description"].strip(), f"role {role['id']} has empty description"

    def test_axiom_anchors_is_list(self, registry):
        for role in registry["roles"]:
            assert isinstance(role["axiom_anchors"], list)


class TestAxiomAnchors:
    def test_referenced_axioms_exist(self, registry, known_axiom_ids):
        """Every axiom_anchor must be a real axiom in axioms/registry.yaml.
        Catches typos or stale references after an axiom rename/retire."""
        for role in registry["roles"]:
            for anchor in role["axiom_anchors"]:
                assert anchor in known_axiom_ids, (
                    f"role {role['id']} references unknown axiom '{anchor}' — "
                    f"known axioms: {sorted(known_axiom_ids)}"
                )

    def test_structural_roles_that_need_anchoring_are_anchored(self, registry):
        """executive-function-substrate must anchor to both executive_function
        and single_user. These are the load-bearing amendments for that role."""
        ef_sub = next(r for r in registry["roles"] if r["id"] == "executive-function-substrate")
        assert set(ef_sub["axiom_anchors"]) == {"executive_function", "single_user"}


class TestAmendmentGating:
    def test_structural_roles_are_amendment_gated(self, registry):
        """Structural roles cannot be removed or redefined without an
        axiom amendment. Regression pin on amendment_gated flag."""
        for role in registry["roles"]:
            if role["layer"] == "structural":
                assert role["amendment_gated"] is True, (
                    f"structural role {role['id']} must have amendment_gated=True"
                )

    def test_institutional_roles_are_not_amendment_gated(self, registry):
        """Institutional roles are editable via normal review — cycle 3
        research participation, platform changes, household changes all
        happen without touching the axiom registry."""
        for role in registry["roles"]:
            if role["layer"] == "institutional":
                assert role["amendment_gated"] is False


class TestRelationalInstances:
    def test_relational_roles_declare_runtime_inference(self, registry):
        """Relational roles don't carry runtime instance state; they name
        signals from which the instance is inferred. Schema check: each
        relational role has a non-empty instances_inferred_from list."""
        for role in registry["roles"]:
            if role["layer"] == "relational":
                assert "instances_inferred_from" in role
                assert isinstance(role["instances_inferred_from"], list)
                assert len(role["instances_inferred_from"]) > 0


class TestPosturesVocabulary:
    """Light structural checks on the posture vocabulary document."""

    def test_posture_vocabulary_exists(self):
        vocab = Path(__file__).parent.parent.parent / "axioms" / "persona" / "posture-vocabulary.md"
        assert vocab.exists()

    def test_posture_vocabulary_declares_glossary_not_policy(self):
        vocab = Path(__file__).parent.parent.parent / "axioms" / "persona" / "posture-vocabulary.md"
        text = vocab.read_text().lower()
        # The document must be explicit about its shape
        assert "glossary, not a policy" in text
        assert "recognized" in text and "mandated" in text

    def test_posture_vocabulary_forbids_llm_prompt_injection(self):
        """Posture names must NOT be in LLM system prompts. The vocabulary
        document is explicit about this to prevent reification."""
        vocab = Path(__file__).parent.parent.parent / "axioms" / "persona" / "posture-vocabulary.md"
        text = vocab.read_text()
        # Document uses "**not** expected to appear in" (markdown bold) —
        # normalize by stripping markdown asterisks for the phrase check
        normalized = text.lower().replace("*", "")
        assert "not expected to appear in" in normalized
        assert "llm system prompt" in text.lower()
