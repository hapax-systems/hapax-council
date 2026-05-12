"""Tests for production governance hooks."""

from __future__ import annotations

from agentgov.hooks import (
    scan_attribution_entities,
    scan_management_boundary,
    scan_pii,
    scan_provenance_references,
    scan_single_user_violations,
    validate_all,
)


class TestPIIGuard:
    def test_detects_ssn(self) -> None:
        result = scan_pii("SSN is 123-45-6789")
        assert not result.ok
        assert result.hook == "pii_guard"

    def test_detects_email(self) -> None:
        result = scan_pii("Contact: test@example.com for details")
        assert not result.ok

    def test_detects_phone(self) -> None:
        result = scan_pii("Call 555-123-4567")
        assert not result.ok

    def test_clean_text_passes(self) -> None:
        result = scan_pii("The governance algebra is verified by Hypothesis.")
        assert result.ok


class TestSingleOperatorAxiom:
    def test_detects_multiop_scaffolding(self) -> None:
        result = scan_single_user_violations("class " + "Au" + "thManager:")
        assert not result.ok
        assert result.hook == "single_user_axiom"

    def test_clean_code_passes(self) -> None:
        result = scan_single_user_violations("class ConfigManager:\n    pass")
        assert result.ok


class TestAttributionEntities:
    def test_detects_wrong_company(self) -> None:
        result = scan_attribution_entities("Anthropic's Codex is great")
        assert not result.ok
        assert "OpenAI" in result.reason

    def test_correct_attribution_passes(self) -> None:
        result = scan_attribution_entities("OpenAI's Codex is a coding tool")
        assert result.ok


class TestProvenanceReferences:
    def test_ungrounded_claim_fails(self) -> None:
        result = scan_provenance_references("This proves the system is safe.")
        assert not result.ok

    def test_grounded_claim_passes(self) -> None:
        result = scan_provenance_references(
            "According to the audit, this confirms the system is safe."
        )
        assert result.ok


class TestManagementBoundary:
    def test_detects_mgmt_gen(self) -> None:
        result = scan_management_boundary("def generate_feed" + "back(emp):")
        assert not result.ok

    def test_clean_code_passes(self) -> None:
        result = scan_management_boundary("def generate_report(data):")
        assert result.ok


class TestValidateAll:
    def test_runs_all_hooks(self) -> None:
        results = validate_all("clean text with no issues")
        assert len(results) == 5
        assert all(r.ok for r in results)

    def test_selective_checks(self) -> None:
        results = validate_all("test@example.com", checks=["pii"])
        assert len(results) == 1
        assert not results[0].ok
