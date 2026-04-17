"""Tests for LRR Phase 7 §4.4 persona document-driven integration.

Default path: system_prompt() + director_loop._build_unified_prompt() consume
the persona-document composer. Legacy path: HAPAX_PERSONA_LEGACY=1 reverts
to pre-Phase-7 hard-coded personification strings.
"""

from __future__ import annotations

import pytest

# ── Persona path selection + composition ────────────────────────────────────


class TestSystemPrompt:
    def test_default_uses_document_driven_path(self, monkeypatch):
        """Default (no HAPAX_PERSONA_LEGACY): prompt comes from composer."""
        monkeypatch.delenv("HAPAX_PERSONA_LEGACY", raising=False)
        monkeypatch.setattr("agents.hapax_daimonion.persona.operator_name", lambda: "ryan")

        from agents.hapax_daimonion import persona

        result = persona.system_prompt()
        # Signature of the composer's description-of-being fragment:
        assert "non-human actor" in result.lower()
        assert "network" in result.lower()
        # Voice-mode instructions present
        assert "## Voice mode" in result
        # Partner block present (operator)
        assert "ryan" in result
        assert "partner-in-conversation" in result.lower()
        # Tools present (default path)
        assert "## Tools" in result
        # No personification-coded prologue
        assert "warm but concise" not in result.lower()

    def test_legacy_opt_out_env(self, monkeypatch):
        """HAPAX_PERSONA_LEGACY=1 reverts to pre-Phase-7 prompt."""
        monkeypatch.setenv("HAPAX_PERSONA_LEGACY", "1")
        monkeypatch.setattr("agents.hapax_daimonion.persona.operator_name", lambda: "ryan")

        from agents.hapax_daimonion import persona

        result = persona.system_prompt()
        # Legacy personification strings present
        assert "warm but concise" in result
        assert "friendly without being chatty" in result
        # Document-driven signatures absent
        assert "## Voice mode" not in result
        assert "non-human actor" not in result.lower()

    def test_guest_mode_uses_guest_partner_block(self, monkeypatch):
        monkeypatch.delenv("HAPAX_PERSONA_LEGACY", raising=False)
        monkeypatch.setattr("agents.hapax_daimonion.persona.operator_name", lambda: "ryan")

        from agents.hapax_daimonion import persona

        result = persona.system_prompt(guest_mode=True)
        assert "partner in conversation is a guest" in result
        # Operator-private tools should NOT appear
        assert "## Tools" not in result
        # Guest still uses partner-in-conversation role (same relational role,
        # different instance)
        assert "partner-in-conversation" in result.lower() or "partner in conversation" in result

    def test_experiment_mode_skips_tools(self, monkeypatch):
        """Benchmark / experiment mode omits tool descriptions but keeps persona."""
        monkeypatch.delenv("HAPAX_PERSONA_LEGACY", raising=False)
        monkeypatch.setattr("agents.hapax_daimonion.persona.operator_name", lambda: "ryan")

        from agents.hapax_daimonion import persona

        result = persona.system_prompt(experiment_mode=True)
        assert "## Tools" not in result
        # Persona + voice mode + partner still there
        assert "## Voice mode" in result
        assert "ryan" in result

    def test_tool_recruitment_skips_inline_tools(self, monkeypatch):
        """Tool recruitment injects tools via schemas; prompt should omit them."""
        monkeypatch.delenv("HAPAX_PERSONA_LEGACY", raising=False)
        monkeypatch.setattr("agents.hapax_daimonion.persona.operator_name", lambda: "ryan")

        from agents.hapax_daimonion import persona

        result = persona.system_prompt(tool_recruitment_active=True)
        assert "## Tools" not in result
        assert "## Voice mode" in result

    def test_policy_block_appended(self, monkeypatch):
        monkeypatch.delenv("HAPAX_PERSONA_LEGACY", raising=False)
        monkeypatch.setattr("agents.hapax_daimonion.persona.operator_name", lambda: "ryan")

        from agents.hapax_daimonion import persona

        policy = "## Conversational policy\nTEST_POLICY_MARKER"
        result = persona.system_prompt(policy_block=policy)
        assert "TEST_POLICY_MARKER" in result

    @pytest.mark.parametrize("falsy_val", ["", "0", "false", "no", "off", "  ", "random"])
    def test_legacy_env_is_falsy_for_non_truthy(self, monkeypatch, falsy_val):
        """Only 1/true/yes/on activate legacy mode."""
        monkeypatch.setenv("HAPAX_PERSONA_LEGACY", falsy_val)
        monkeypatch.setattr("agents.hapax_daimonion.persona.operator_name", lambda: "ryan")

        from agents.hapax_daimonion import persona

        result = persona.system_prompt()
        # Document-driven markers should be present (legacy not triggered)
        assert "## Voice mode" in result


class TestNoPersonification:
    """The Phase 7 reframe forbids pre-Phase-7 personification-coded phrases
    in the default (document-driven) prompt. Regression pin against the
    legacy strings leaking back in.

    NOTE: the persona document itself discusses inner-life claims
    ("curious", "I feel wonder") AS EXAMPLES of what Hapax should not do —
    the document's content is not a regression. This test targets only the
    pre-Phase-7 personality-coded strings that the Phase 7 reframe retired.
    """

    FORBIDDEN_PHRASES = [
        "warm but concise",
        "friendly without being chatty",
        "skip formalities",  # operator-voice framing language from legacy prompt
    ]

    @pytest.mark.parametrize("phrase", FORBIDDEN_PHRASES)
    def test_default_path_rejects(self, monkeypatch, phrase):
        monkeypatch.delenv("HAPAX_PERSONA_LEGACY", raising=False)
        monkeypatch.setattr("agents.hapax_daimonion.persona.operator_name", lambda: "ryan")

        from agents.hapax_daimonion import persona

        for mode in (
            {},
            {"guest_mode": True},
            {"experiment_mode": True},
            {"tool_recruitment_active": True},
        ):
            result = persona.system_prompt(**mode).lower()
            assert phrase.lower() not in result, (
                f"personification-coded phrase '{phrase}' leaked into prompt under mode={mode}"
            )


# ── Director loop identity block uses composer ──────────────────────────────


class TestDirectorLegacyOptOut:
    """The director loop's _build_unified_prompt() should consult
    HAPAX_PERSONA_LEGACY to choose between composer-driven and hard-coded
    identity. Full _build_unified_prompt requires a director instance +
    compositor state; this is a narrower unit test on the module-level
    helper."""

    def test_legacy_helper_default_false(self, monkeypatch):
        monkeypatch.delenv("HAPAX_PERSONA_LEGACY", raising=False)
        from agents.studio_compositor import director_loop

        assert director_loop._persona_legacy_mode() is False

    @pytest.mark.parametrize("truthy", ["1", "true", "yes", "on", "TRUE"])
    def test_legacy_helper_truthy_env(self, monkeypatch, truthy):
        monkeypatch.setenv("HAPAX_PERSONA_LEGACY", truthy)
        from agents.studio_compositor import director_loop

        assert director_loop._persona_legacy_mode() is True
