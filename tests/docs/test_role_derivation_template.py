"""Tests for the role derivation methodology and template artifacts.

These are lightweight file-existence and cross-reference tests, not
integration tests. They verify that:

1. The methodology doc (`docs/research/role-derivation-methodology.md`)
   exists and contains the required sections.
2. The template file (`docs/research/role-derivation-template.md`)
   exists and contains all required sections.
3. The methodology doc references the template.
4. The persona document (`axioms/persona/hapax-description-of-being.md`)
   is cross-referenceable from the methodology.

Reference: docs/superpowers/specs/2026-04-18-role-derivation-research-template-design.md
Task: CVS #156
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
METHODOLOGY_DOC = REPO_ROOT / "docs" / "research" / "role-derivation-methodology.md"
TEMPLATE_DOC = REPO_ROOT / "docs" / "research" / "role-derivation-template.md"
PERSONA_DOC = REPO_ROOT / "axioms" / "persona" / "hapax-description-of-being.md"
ROLE_REGISTRY = REPO_ROOT / "axioms" / "roles" / "registry.yaml"


@pytest.fixture(scope="module")
def methodology_text() -> str:
    return METHODOLOGY_DOC.read_text()


@pytest.fixture(scope="module")
def template_text() -> str:
    return TEMPLATE_DOC.read_text()


# ── Methodology document ────────────────────────────────────────────────────


class TestMethodologyDoc:
    def test_exists(self):
        assert METHODOLOGY_DOC.exists(), f"methodology doc missing at {METHODOLOGY_DOC}"

    def test_has_problem_statement_section(self, methodology_text):
        assert "## 1. Problem statement" in methodology_text

    def test_has_general_case_method_section(self, methodology_text):
        assert "## 2. General-case method" in methodology_text

    def test_has_five_method_steps(self, methodology_text):
        """Steps 1–5 keyed to the ANT-based derivation method."""
        for step_heading in (
            "### Step 1",
            "### Step 2",
            "### Step 3",
            "### Step 4",
            "### Step 5",
        ):
            assert step_heading in methodology_text, (
                f"missing {step_heading!r} — all five derivation steps required"
            )

    def test_has_hapax_application_section(self, methodology_text):
        assert "## 3. Hapax-specific application" in methodology_text

    def test_has_template_section(self, methodology_text):
        assert "## 4. Template (reproducible for other systems)" in methodology_text

    def test_has_governance_relationship_section(self, methodology_text):
        assert "## 5. Relationship to existing governance surfaces" in methodology_text

    def test_has_future_extensions_section(self, methodology_text):
        assert "## 6. Future extensions" in methodology_text


# ── Cross-references ────────────────────────────────────────────────────────


class TestCrossReferences:
    def test_methodology_references_template(self, methodology_text):
        """The methodology doc must point at the template so readers can
        follow from method to reproducible artifact."""
        assert "role-derivation-template.md" in methodology_text, (
            "methodology must reference companion template file"
        )

    def test_methodology_references_phase_7_spec(self, methodology_text):
        assert "2026-04-16-lrr-phase-7-redesign-persona-posture-role.md" in methodology_text, (
            "methodology must cite Phase 7 locked taxonomy authoring spec"
        )

    def test_methodology_references_anti_personification_linter(self, methodology_text):
        assert "2026-04-18-anti-personification-linter-design.md" in methodology_text, (
            "methodology must cite #155 anti-personification linter design "
            "so the is_not: coupling is traceable"
        )

    def test_methodology_references_persona_doc(self, methodology_text):
        assert "hapax-description-of-being.md" in methodology_text, (
            "methodology must cross-reference the persona description-of-being artifact"
        )

    def test_methodology_references_posture_vocabulary(self, methodology_text):
        assert "posture-vocabulary.md" in methodology_text, (
            "methodology must cross-reference the posture vocabulary artifact"
        )

    def test_methodology_references_role_registry(self, methodology_text):
        assert "axioms/roles/registry.yaml" in methodology_text, (
            "methodology must cross-reference the locked role registry"
        )


# ── Template document ───────────────────────────────────────────────────────


class TestTemplateDoc:
    def test_exists(self):
        assert TEMPLATE_DOC.exists(), f"template missing at {TEMPLATE_DOC}"

    def test_has_frontmatter_section(self, template_text):
        assert "## Frontmatter" in template_text

    def test_has_research_question_section(self, template_text):
        assert "## 1. Research question (Step 1)" in template_text

    def test_has_actant_enumeration_section(self, template_text):
        assert "## 2. Actant enumeration (Step 2)" in template_text

    def test_has_candidate_position_section(self, template_text):
        assert "## 3. Candidate position table (Step 3)" in template_text

    def test_has_classification_section(self, template_text):
        assert "## 4. Persona / posture / role classification (Step 4)" in template_text

    def test_has_collapse_test_section(self, template_text):
        assert "## 5. Collapse test (Step 5)" in template_text

    def test_has_final_taxonomy_section(self, template_text):
        assert "## 6. Final taxonomy" in template_text

    def test_has_registry_yaml_section(self, template_text):
        assert "## 7. Registry YAML proposal" in template_text

    def test_has_fill_placeholders(self, template_text):
        """Template must contain `[FILL: ...]` placeholders — that is what
        makes it a template rather than a specific derivation."""
        assert "[FILL:" in template_text, "template must contain [FILL: ...] placeholders"

    def test_has_validation_checklists(self, template_text):
        """Each step block should include a validation checklist."""
        # Step 1 through Step 5 each carry a validation checklist
        validation_count = template_text.count("validation checklist")
        assert validation_count >= 5, (
            f"expected ≥5 validation checklists (one per step), found {validation_count}"
        )

    def test_references_methodology(self, template_text):
        """Template must point back at the methodology so authors can
        consult the full method when filling placeholders."""
        assert "role-derivation-methodology.md" in template_text, (
            "template must reference the methodology document"
        )


# ── Cross-referenceable artifacts ───────────────────────────────────────────


class TestTaxonomyArtifacts:
    """The methodology's claims about the Hapax taxonomy must remain
    grep-able against the actual persona document and role registry.
    These tests confirm the cross-referenced files exist; content-level
    validation lives in `tests/axioms/test_role_registry.py` and
    `tests/axioms/test_persona_description.py`."""

    def test_persona_doc_exists(self):
        assert PERSONA_DOC.exists(), (
            f"persona document missing at {PERSONA_DOC} — "
            "methodology cross-references would be broken"
        )

    def test_role_registry_exists(self):
        assert ROLE_REGISTRY.exists(), (
            f"role registry missing at {ROLE_REGISTRY} — "
            "methodology Hapax application §3.3 cross-references would be broken"
        )
