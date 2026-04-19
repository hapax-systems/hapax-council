"""Tests for shared.persona_prompt_composer (LRR Phase 7 §4.4 prep).

Pure loader + role-declaration appender; these tests pin:
- Fragment loads from the canonical path
- Role declarations append correctly
- Feature flag env var semantics
- Token-budget ceiling (fragment stays prompt-efficient)
- Known-role set synchronized with role registry
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from shared import persona_prompt_composer as composer

REPO_ROOT = Path(__file__).parent.parent.parent


class TestLoading:
    def test_fragment_path_exists(self):
        assert composer.PERSONA_PROMPT_PATH.exists(), (
            "persona prompt fragment missing — composer will fail on load"
        )

    def test_compose_no_role_returns_fragment(self):
        composer.reset_cache_for_testing()
        result = composer.compose_persona_prompt()
        # Sanity: substantive content present
        assert "Hapax" in result
        assert len(result) > 500, "fragment too short — may be truncated"

    def test_fragment_contains_core_claims(self):
        composer.reset_cache_for_testing()
        result = composer.compose_persona_prompt()
        # Per persona document's structural claims, these must be present
        # in the LLM-facing compressed form:
        core_markers = [
            "executive-function substrate",
            "non-human actor",
            "network",
            "curious",  # canonical utility-voice example
        ]
        for marker in core_markers:
            assert marker.lower() in result.lower(), f"missing '{marker}'"


class TestRoleDeclaration:
    def setup_method(self):
        composer.reset_cache_for_testing()

    def test_role_id_suffix_appended(self):
        result = composer.compose_persona_prompt(role_id="executive-function-assistant")
        assert result.endswith("Current role instance: executive-function-assistant")

    def test_no_role_id_no_suffix(self):
        result = composer.compose_persona_prompt()
        assert "Current role instance" not in result

    def test_unknown_role_id_still_appends(self):
        """Composer does NOT validate role_id — that's the caller's job.
        Unknown IDs still get suffixed (caller may have a registry-dynamic
        role in mind that isn't in the hardcoded set)."""
        result = composer.compose_persona_prompt(role_id="some-future-role")
        assert "Current role instance: some-future-role" in result


class TestFeatureFlag:
    def test_default_off(self, monkeypatch):
        monkeypatch.delenv(composer.FEATURE_FLAG_ENV, raising=False)
        assert composer.is_document_driven_enabled() is False

    @pytest.mark.parametrize("value", ["1", "true", "yes", "on", "TRUE", "On"])
    def test_truthy_values(self, monkeypatch, value):
        monkeypatch.setenv(composer.FEATURE_FLAG_ENV, value)
        assert composer.is_document_driven_enabled() is True

    @pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "  ", "random"])
    def test_falsy_values(self, monkeypatch, value):
        monkeypatch.setenv(composer.FEATURE_FLAG_ENV, value)
        assert composer.is_document_driven_enabled() is False


class TestTokenBudget:
    """LLM system prompts share a budget with tool descriptions + context.
    Keep the persona fragment small enough that it doesn't crowd out other
    material. Ceiling raised from 700 → 1200 after PR #1046 added the
    livestream-director role paragraph (operator-directed, load-bearing:
    it declares the three coupled decisions per tick that every narrative
    tick must emit). Any further growth should trade against actual
    compression of the existing content, not silent ceiling creep."""

    def test_fragment_under_soft_ceiling(self):
        composer.reset_cache_for_testing()
        fragment = composer.compose_persona_prompt()
        # Rough token count: 1 token ≈ 4 chars for English (conservative)
        approx_tokens = len(fragment) / 4
        assert approx_tokens < 1200, (
            f"persona fragment approx {approx_tokens:.0f} tokens — "
            f"exceeds 1200-token soft ceiling. Compress the fragment "
            f"(axioms/persona/hapax-description-of-being.prompt.md)."
        )


class TestKnownRolesMatchRegistry:
    def test_known_roles_match_yaml_registry(self):
        """shared.persona_prompt_composer.KNOWN_ROLE_IDS must stay in sync
        with axioms/roles/registry.yaml. This test is the cross-check —
        if roles are added/removed in the registry and the set is not
        updated, this test fails loud.

        Skipped when the registry file is not present on disk (the role
        registry is shipped in a separate PR #970; this test becomes
        active once that lands on main).
        """
        registry_path = REPO_ROOT / "axioms" / "roles" / "registry.yaml"
        if not registry_path.exists():
            pytest.skip(
                "axioms/roles/registry.yaml not on disk (shipped in #970); "
                "sync check activates once that PR merges to main."
            )
        registry_data = yaml.safe_load(registry_path.read_text())
        yaml_ids = {r["id"] for r in registry_data["roles"]}
        assert yaml_ids == composer.KNOWN_ROLE_IDS, (
            f"composer KNOWN_ROLE_IDS drift from registry — "
            f"added {yaml_ids - composer.KNOWN_ROLE_IDS}, "
            f"removed {composer.KNOWN_ROLE_IDS - yaml_ids}. "
            f"Update the composer's KNOWN_ROLE_IDS constant."
        )

    def test_is_known_role_true_for_registered(self):
        for role_id in composer.KNOWN_ROLE_IDS:
            assert composer.is_known_role(role_id)

    def test_is_known_role_false_for_unregistered(self):
        assert composer.is_known_role("not-a-real-role") is False
        assert composer.is_known_role("") is False


class TestCaching:
    def test_cache_hit_after_first_call(self):
        composer.reset_cache_for_testing()
        first = composer.compose_persona_prompt()
        second = composer.compose_persona_prompt()
        assert first == second

    def test_cache_invalidation_via_reset(self):
        """Tests that need to monkey-patch the path can call
        reset_cache_for_testing to force a reload."""
        composer.reset_cache_for_testing()
        first = composer.compose_persona_prompt()
        composer.reset_cache_for_testing()
        # Just ensure no exception; content is the same file so same string
        second = composer.compose_persona_prompt()
        assert first == second


class TestRoleIsNotSurfacing:
    """Anti-personification linter Stage 3: ``role_is_not`` and
    ``role_scope_line`` surface the ``is_not:`` field from the role
    registry to prompt assemblers."""

    def test_role_is_not_returns_tuple_for_institutional_role(self):
        composer.reset_role_registry_cache_for_testing()
        entries = composer.role_is_not("executive-function-assistant")
        assert isinstance(entries, tuple)
        assert len(entries) > 0
        # Spot-check the verbatim entries from the registry.
        assert "therapist" in entries

    def test_role_is_not_returns_tuple_for_relational_role(self):
        composer.reset_role_registry_cache_for_testing()
        entries = composer.role_is_not("partner-in-conversation")
        assert "confidant" in entries

    def test_role_is_not_empty_for_unknown_role(self):
        composer.reset_role_registry_cache_for_testing()
        assert composer.role_is_not("not-a-real-role") == ()

    def test_role_is_not_empty_for_empty_arg(self):
        composer.reset_role_registry_cache_for_testing()
        assert composer.role_is_not("") == ()

    def test_role_is_not_empty_for_structural_role(self):
        """Structural roles may omit ``is_not:`` per design. The current
        registry omits it for both; this test documents the exemption."""
        composer.reset_role_registry_cache_for_testing()
        # Both structural roles omit is_not today.
        assert composer.role_is_not("executive-function-substrate") == ()

    def test_role_scope_line_formats_institutional_role(self):
        composer.reset_role_registry_cache_for_testing()
        line = composer.role_scope_line("livestream-host")
        assert line.startswith("Scope: this role is NOT ")
        assert line.endswith(".")
        assert "personality-entertainer" in line

    def test_role_scope_line_empty_for_unknown_role(self):
        composer.reset_role_registry_cache_for_testing()
        assert composer.role_scope_line("not-a-real-role") == ""

    def test_role_scope_line_empty_for_structural_role(self):
        composer.reset_role_registry_cache_for_testing()
        assert composer.role_scope_line("executive-function-substrate") == ""
