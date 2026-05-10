"""Tests for shared.publication_hardening.entity_checker.

Covers the known-entities YAML registry loader, attribution pattern
extraction, and misattribution detection. The triggering incident:
a blog post attributed OpenAI's Codex to Anthropic (2026-05-09).
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from shared.publication_hardening.entity_checker import (
    AttributionFinding,
    EntityRegistry,
    check_attributions,
    load_registry,
)

REGISTRY_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "config"
    / "publication-hardening"
    / "known-entities.yaml"
)


@pytest.fixture()
def registry() -> EntityRegistry:
    return load_registry(REGISTRY_PATH)


class TestLoadRegistry:
    def test_loads_without_error(self, registry: EntityRegistry) -> None:
        assert registry is not None

    def test_codex_belongs_to_openai(self, registry: EntityRegistry) -> None:
        assert registry.lookup("codex") == "OpenAI"

    def test_claude_belongs_to_anthropic(self, registry: EntityRegistry) -> None:
        assert registry.lookup("claude") == "Anthropic"

    def test_gemini_belongs_to_google(self, registry: EntityRegistry) -> None:
        assert registry.lookup("gemini") == "Google"

    def test_llama_belongs_to_meta(self, registry: EntityRegistry) -> None:
        assert registry.lookup("llama") == "Meta"

    def test_command_r_belongs_to_cohere(self, registry: EntityRegistry) -> None:
        assert registry.lookup("command r") == "Cohere"
        assert registry.lookup("command-r") == "Cohere"

    def test_unknown_product_returns_none(self, registry: EntityRegistry) -> None:
        assert registry.lookup("nonexistent-product") is None

    def test_case_insensitive_lookup(self, registry: EntityRegistry) -> None:
        assert registry.lookup("CLAUDE") == "Anthropic"
        assert registry.lookup("Claude") == "Anthropic"

    def test_company_names_populated(self, registry: EntityRegistry) -> None:
        assert "Anthropic" in registry.company_names
        assert "OpenAI" in registry.company_names
        assert "Google" in registry.company_names

    def test_is_company(self, registry: EntityRegistry) -> None:
        assert registry.is_company("Anthropic")
        assert registry.is_company("OpenAI")
        assert not registry.is_company("SomeRandomCorp")


class TestCheckAttributionsTriggeringIncident:
    """The exact bug class that triggered this feature: Codex attributed to Anthropic."""

    def test_anthropic_codex_possessive(self, registry: EntityRegistry) -> None:
        text = "We use Anthropic's Codex for code generation."
        findings = check_attributions(text, registry)
        assert len(findings) >= 1
        f = findings[0]
        assert f.product.lower() == "codex"
        assert f.claimed_company == "Anthropic"
        assert f.actual_company == "OpenAI"

    def test_codex_by_anthropic(self, registry: EntityRegistry) -> None:
        text = "Codex by Anthropic is a powerful tool."
        findings = check_attributions(text, registry)
        assert len(findings) >= 1
        f = findings[0]
        assert f.claimed_company == "Anthropic"
        assert f.actual_company == "OpenAI"

    def test_codex_from_anthropic(self, registry: EntityRegistry) -> None:
        text = "We integrated Codex from Anthropic into our pipeline."
        findings = check_attributions(text, registry)
        assert len(findings) >= 1
        assert findings[0].actual_company == "OpenAI"


class TestCheckAttributionsCorrectAttributions:
    """Correct attributions must NOT produce findings."""

    def test_anthropic_claude_no_finding(self, registry: EntityRegistry) -> None:
        text = "We use Anthropic's Claude for reasoning tasks."
        findings = check_attributions(text, registry)
        assert len(findings) == 0

    def test_openai_codex_no_finding(self, registry: EntityRegistry) -> None:
        text = "OpenAI's Codex powers our code completion."
        findings = check_attributions(text, registry)
        assert len(findings) == 0

    def test_claude_by_anthropic_no_finding(self, registry: EntityRegistry) -> None:
        text = "Claude by Anthropic excels at long-context work."
        findings = check_attributions(text, registry)
        assert len(findings) == 0

    def test_gemini_by_google_no_finding(self, registry: EntityRegistry) -> None:
        text = "Gemini by Google handles multimodal inputs."
        findings = check_attributions(text, registry)
        assert len(findings) == 0


class TestCheckAttributionsVariousPatterns:
    """Cross-company misattributions beyond the triggering incident."""

    def test_google_claude_misattribution(self, registry: EntityRegistry) -> None:
        text = "Google's Claude model is impressive."
        findings = check_attributions(text, registry)
        assert len(findings) >= 1
        assert findings[0].actual_company == "Anthropic"

    def test_openai_gemini_misattribution(self, registry: EntityRegistry) -> None:
        text = "OpenAI's Gemini surpasses expectations."
        findings = check_attributions(text, registry)
        assert len(findings) >= 1
        assert findings[0].actual_company == "Google"

    def test_anthropic_gpt4_misattribution(self, registry: EntityRegistry) -> None:
        text = "Anthropic's GPT-4 sets a new benchmark."
        findings = check_attributions(text, registry)
        assert len(findings) >= 1
        assert findings[0].actual_company == "OpenAI"

    def test_meta_mistral_misattribution(self, registry: EntityRegistry) -> None:
        text = "Meta's Mistral model is open-weight."
        findings = check_attributions(text, registry)
        assert len(findings) >= 1
        assert findings[0].actual_company == "Mistral AI"

    def test_reverse_possessive_misattribution(self, registry: EntityRegistry) -> None:
        text = "Google's Codex is revolutionary."
        findings = check_attributions(text, registry)
        assert len(findings) >= 1
        assert findings[0].actual_company == "OpenAI"


class TestCheckAttributionsNoFalsePositives:
    """Text that mentions products without attribution claims."""

    def test_plain_product_mention(self, registry: EntityRegistry) -> None:
        text = "Codex is a powerful code generation tool."
        findings = check_attributions(text, registry)
        assert len(findings) == 0

    def test_unrelated_text(self, registry: EntityRegistry) -> None:
        text = "The weather is nice today."
        findings = check_attributions(text, registry)
        assert len(findings) == 0

    def test_empty_text(self, registry: EntityRegistry) -> None:
        findings = check_attributions("", registry)
        assert len(findings) == 0


class TestCheckAttributionsMultiline:
    """Multi-line documents with mixed correct and incorrect attributions."""

    def test_mixed_document(self, registry: EntityRegistry) -> None:
        text = dedent("""\
            # AI Tool Comparison

            We evaluated several AI tools:

            - Anthropic's Claude for reasoning (correct)
            - Anthropic's Codex for code generation (WRONG)
            - Google's Gemini for multimodal (correct)
        """)
        findings = check_attributions(text, registry)
        assert len(findings) >= 1
        wrong = [f for f in findings if f.product.lower() == "codex"]
        assert len(wrong) >= 1
        assert wrong[0].claimed_company == "Anthropic"
        assert wrong[0].actual_company == "OpenAI"


class TestAttributionFindingStr:
    def test_str_representation(self) -> None:
        f = AttributionFinding(
            line=5,
            col=10,
            product="Codex",
            claimed_company="Anthropic",
            actual_company="OpenAI",
            matched_text="Anthropic's Codex",
        )
        s = str(f)
        assert "Codex" in s
        assert "Anthropic" in s
        assert "OpenAI" in s


class TestLoadRegistryFromCustomPath:
    def test_custom_yaml(self, tmp_path: Path) -> None:
        yaml_content = dedent("""\
            companies:
              TestCorp:
                products:
                  - name: TestProduct
                    aliases: [testproduct, tp]
              OtherCorp:
                products:
                  - name: OtherThing
                    aliases: [otherthing]
        """)
        yaml_path = tmp_path / "test-entities.yaml"
        yaml_path.write_text(yaml_content)
        reg = load_registry(yaml_path)
        assert reg.lookup("testproduct") == "TestCorp"
        assert reg.lookup("otherthing") == "OtherCorp"
        assert reg.is_company("TestCorp")

    def test_custom_registry_misattribution(self, tmp_path: Path) -> None:
        yaml_content = dedent("""\
            companies:
              AlphaCo:
                products:
                  - name: WidgetX
                    aliases: [widgetx]
              BetaCo:
                products:
                  - name: GadgetY
                    aliases: [gadgety]
        """)
        yaml_path = tmp_path / "test-entities.yaml"
        yaml_path.write_text(yaml_content)
        reg = load_registry(yaml_path)

        text = "BetaCo's WidgetX is great."
        findings = check_attributions(text, reg)
        assert len(findings) >= 1
        assert findings[0].actual_company == "AlphaCo"
        assert findings[0].claimed_company == "BetaCo"
