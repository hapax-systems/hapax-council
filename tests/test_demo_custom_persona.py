"""Tests for custom persona loading."""

from __future__ import annotations

import yaml

from agents.demo_models import load_personas


class TestCustomPersona:
    def test_load_custom_persona_file(self, tmp_path):
        custom = {
            "archetypes": {
                "investor": {
                    "description": "A venture capital partner",
                    "tone": "Results-oriented",
                    "vocabulary": "business",
                    "show": ["ROI", "market fit"],
                    "skip": ["implementation details"],
                    "max_scenes": 5,
                }
            }
        }
        persona_file = tmp_path / "investor.yaml"
        persona_file.write_text(yaml.dump(custom))

        personas = load_personas(extra_path=persona_file)
        assert "investor" in personas
        assert personas["investor"].vocabulary == "business"
        # Built-in personas still present
        assert "family" in personas

    def test_custom_persona_overrides_builtin(self, tmp_path):
        """Custom persona with same name as built-in should override it."""
        custom = {
            "archetypes": {
                "family": {
                    "description": "Overridden family persona",
                    "tone": "Very casual",
                    "vocabulary": "simple",
                    "show": ["cool stuff"],
                    "skip": ["everything else"],
                    "max_scenes": 3,
                }
            }
        }
        persona_file = tmp_path / "override.yaml"
        persona_file.write_text(yaml.dump(custom))

        personas = load_personas(extra_path=persona_file)
        assert personas["family"].description == "Overridden family persona"
        assert personas["family"].max_scenes == 3

    def test_extra_path_none_loads_defaults_only(self):
        """When extra_path is None, only built-in personas are loaded."""
        personas = load_personas(extra_path=None)
        assert "family" in personas
        assert len(personas) >= 1

    def test_extra_path_nonexistent_loads_defaults_only(self, tmp_path):
        """When extra_path doesn't exist, only built-in personas are loaded."""
        personas = load_personas(extra_path=tmp_path / "nonexistent.yaml")
        assert "family" in personas
        assert len(personas) >= 1
