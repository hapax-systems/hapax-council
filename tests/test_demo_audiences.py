"""Tests for audience dossier loading."""
from __future__ import annotations

from pathlib import Path

import yaml
import pytest

from agents.demo_models import AudienceDossier, AudiencePersona, load_audiences, load_personas


class TestLoadAudiences:
    def test_load_audiences_missing_file(self, tmp_path: Path) -> None:
        """Missing file returns empty dict."""
        result = load_audiences(tmp_path / "nonexistent.yaml")
        assert result == {}

    def test_load_audiences_valid(self) -> None:
        """Built-in audiences file loads known dossiers."""
        audiences = load_audiences()
        assert len(audiences) >= 2
        assert "my wife" in audiences
        assert "chris beron" in audiences

    def test_load_audiences_from_fixture(self, tmp_path: Path) -> None:
        """A populated audiences file parses correctly with all fields."""
        data = {
            "audiences": {
                "my colleague": {
                    "archetype": "technical-peer",
                    "name": "Alex",
                    "context": "Works on the platform team. Familiar with Docker and Kubernetes.",
                    "calibration": {
                        "emphasize": ["Agent orchestration patterns"],
                        "skip": ["Personal automations"],
                    },
                }
            }
        }
        f = tmp_path / "audiences.yaml"
        f.write_text(yaml.dump(data))
        audiences = load_audiences(f)
        assert len(audiences) == 1
        dossier = audiences["my colleague"]
        assert isinstance(dossier, AudienceDossier)
        assert dossier.archetype == "technical-peer"
        assert dossier.name == "Alex"
        assert "Docker" in dossier.context
        assert "emphasize" in dossier.calibration
        assert "skip" in dossier.calibration

    def test_load_audiences_case_insensitive(self, tmp_path: Path) -> None:
        """Keys are lowercased for case-insensitive lookup."""
        data = {
            "audiences": {
                "My Wife": {
                    "archetype": "family",
                    "name": "Jane",
                    "context": "test context",
                }
            }
        }
        f = tmp_path / "audiences.yaml"
        f.write_text(yaml.dump(data))
        audiences = load_audiences(f)
        assert "my wife" in audiences
        assert "My Wife" not in audiences

    def test_load_audiences_empty_calibration(self, tmp_path: Path) -> None:
        """Missing calibration defaults to empty dict."""
        data = {
            "audiences": {
                "colleague": {
                    "archetype": "technical-peer",
                    "name": "Alex",
                    "context": "Works on the same team",
                }
            }
        }
        f = tmp_path / "audiences.yaml"
        f.write_text(yaml.dump(data))
        audiences = load_audiences(f)
        assert audiences["colleague"].calibration == {}

    def test_load_audiences_malformed_yaml(self, tmp_path: Path) -> None:
        """Malformed YAML returns empty dict."""
        f = tmp_path / "audiences.yaml"
        f.write_text("[ invalid yaml {{{")
        result = load_audiences(f)
        assert result == {}


class TestForbiddenTerms:
    def test_persona_loads_forbidden_terms(self) -> None:
        """Family persona includes forbidden_terms from YAML."""
        personas = load_personas()
        family = personas["family"]
        assert isinstance(family.forbidden_terms, list)
        assert len(family.forbidden_terms) > 0
        assert "API" in family.forbidden_terms
        assert "Docker" in family.forbidden_terms
        assert "Qdrant" in family.forbidden_terms

    def test_persona_without_forbidden_terms(self) -> None:
        """Personas without forbidden_terms default to empty list."""
        personas = load_personas()
        tech = personas["technical-peer"]
        assert tech.forbidden_terms == []

    def test_forbidden_terms_in_planning_prompt(self) -> None:
        """Forbidden terms appear in the planning prompt for family persona."""
        from agents.demo import build_planning_prompt

        personas = load_personas()
        prompt = build_planning_prompt(
            scope="the entire system",
            audience_name="family",
            persona=personas["family"],
            research_context="A three-tier agent system...",
            planning_context="",
        )
        assert "FORBIDDEN TERMS" in prompt
        assert "API" in prompt
        assert "FAIL evaluation" in prompt

    def test_no_forbidden_terms_section_for_technical(self) -> None:
        """Technical persona should not have a FORBIDDEN TERMS section."""
        from agents.demo import build_planning_prompt

        personas = load_personas()
        prompt = build_planning_prompt(
            scope="the entire system",
            audience_name="technical-peer",
            persona=personas["technical-peer"],
            research_context="A three-tier agent system...",
            planning_context="",
        )
        assert "FORBIDDEN TERMS" not in prompt
