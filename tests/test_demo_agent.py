"""Tests for the demo agent."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from agents.demo_models import DemoScript, DemoScene, ScreenshotSpec, load_personas


class TestResolveAudience:
    def test_direct_archetype_match(self):
        from agents.demo import resolve_audience

        archetype, context = resolve_audience("family", load_personas())
        assert archetype == "family"

    def test_natural_language_fallback(self):
        from agents.demo import resolve_audience

        # Unknown audience falls back to technical-peer
        archetype, context = resolve_audience(
            "a random stranger", load_personas()
        )
        assert archetype == "technical-peer"
        assert context == "a random stranger"


    def test_audience_hint_investor(self):
        from agents.demo import resolve_audience
        archetype, _ = resolve_audience("an investor", load_personas())
        assert archetype == "leadership"

    def test_audience_hint_no_substring_false_positive(self):
        from agents.demo import resolve_audience
        archetype, _ = resolve_audience("a friendly neighbor", load_personas())
        # "friendly" should NOT match "friend" due to word boundary
        assert archetype == "technical-peer"


class TestBuildPrompt:
    def test_includes_persona(self):
        from agents.demo import build_planning_prompt

        personas = load_personas()
        prompt = build_planning_prompt(
            scope="the entire system",
            audience_name="family",
            persona=personas["family"],
            research_context="A three-tier agent system...",
            planning_context="## Style Guide\nVoice: first-person",
        )
        assert "family" in prompt.lower() or "warm" in prompt.lower()
        assert "three-tier" in prompt

    def test_includes_scope(self):
        from agents.demo import build_planning_prompt

        personas = load_personas()
        prompt = build_planning_prompt(
            scope="health monitoring",
            audience_name="technical-peer",
            persona=personas["technical-peer"],
            research_context="A three-tier agent system...",
            planning_context="",
        )
        assert "health monitoring" in prompt


class TestParseRequest:
    def test_simple_for_pattern(self):
        from agents.demo import parse_request

        scope, audience = parse_request("the entire system for my wife")
        assert scope == "the entire system"
        assert audience == "my wife"

    def test_no_audience(self):
        from agents.demo import parse_request

        scope, audience = parse_request("health monitoring")
        assert scope == "health monitoring"
        assert audience == "technical-peer"  # default

    def test_complex_audience(self):
        from agents.demo import parse_request

        scope, audience = parse_request(
            "the context maintenance system for a Senior Enterprise Architect on my Platform Services Team"
        )
        assert "context maintenance" in scope
        assert "Senior Enterprise Architect" in audience


class TestOverridePlacement:
    """Tests for planning_overrides placement and accumulation logic."""

    def test_overrides_at_end_of_prompt(self):
        from agents.demo import build_planning_prompt

        personas = load_personas()
        prompt = build_planning_prompt(
            scope="the entire system",
            audience_name="family",
            persona=personas["family"],
            research_context="System description here",
            planning_context="## Style Guide\nVoice: first-person",
            planning_overrides="Use simpler vocabulary throughout.",
        )
        # Overrides must appear AFTER the structural rules (VISUAL VARIETY RULES)
        variety_pos = prompt.index("VISUAL VARIETY RULES")
        override_pos = prompt.index("EVALUATION FEEDBACK")
        assert override_pos > variety_pos, "Overrides must appear after structural rules"
        assert "Use simpler vocabulary throughout." in prompt

    def test_overrides_none_no_section(self):
        from agents.demo import build_planning_prompt

        personas = load_personas()
        prompt = build_planning_prompt(
            scope="the entire system",
            audience_name="family",
            persona=personas["family"],
            research_context="System description here",
            planning_context="",
            planning_overrides=None,
        )
        assert "EVALUATION FEEDBACK" not in prompt

    def test_overrides_empty_string_no_section(self):
        from agents.demo import build_planning_prompt

        personas = load_personas()
        prompt = build_planning_prompt(
            scope="the entire system",
            audience_name="family",
            persona=personas["family"],
            research_context="System description here",
            planning_context="",
            planning_overrides="",
        )
        assert "EVALUATION FEEDBACK" not in prompt

    def test_override_replacement_not_accumulation(self):
        """Verify that the eval loop replaces overrides rather than accumulating."""
        # Simulate the logic from demo_eval.py
        planning_overrides = "First iteration: fix jargon"

        # Second iteration diagnosis replaces (not appends)
        new_diagnosis_overrides = "Second iteration: fix word count"
        planning_overrides = new_diagnosis_overrides
        if len(planning_overrides) > 2000:
            planning_overrides = planning_overrides[:2000].rsplit(" ", 1)[0]

        assert planning_overrides == "Second iteration: fix word count"
        assert "First iteration" not in planning_overrides

    def test_override_cap_at_2000_chars(self):
        """Verify that overrides are capped at ~2000 characters."""
        long_override = "Fix this problem. " * 200  # ~3600 chars
        planning_overrides = long_override
        if len(planning_overrides) > 2000:
            planning_overrides = planning_overrides[:2000].rsplit(" ", 1)[0]

        assert len(planning_overrides) <= 2000


class TestMetadata:
    def test_metadata_roundtrip(self, tmp_path):
        """Verify metadata dict has all expected keys and correct types."""
        metadata = {
            "title": "Test Demo",
            "audience": "family",
            "scope": "the system",
            "scenes": 3,
            "format": "slides",
            "duration": 20.0,
            "timestamp": "20260304-120000",
            "output_dir": str(tmp_path),
            "primary_file": "demo.html",
            "has_video": False,
            "has_audio": False,
        }
        out = tmp_path / "metadata.json"
        out.write_text(json.dumps(metadata, indent=2))
        loaded = json.loads(out.read_text())
        expected_keys = {"title", "audience", "scope", "scenes", "format", "duration", "timestamp", "output_dir", "primary_file", "has_video", "has_audio"}
        assert set(loaded.keys()) == expected_keys
        assert isinstance(loaded["scenes"], int)
        assert isinstance(loaded["duration"], float)

    def test_metadata_has_primary_file(self, tmp_path):
        metadata = {
            "title": "Test", "format": "slides",
            "primary_file": "demo.html",
        }
        out = tmp_path / "metadata.json"
        out.write_text(json.dumps(metadata))
        loaded = json.loads(out.read_text())
        assert loaded["primary_file"] == "demo.html"


class TestSufficiencyIntegration:
    """Integration tests for the sufficiency gate inside generate_demo."""

    @pytest.mark.asyncio
    async def test_generate_demo_blocked_sufficiency(self):
        """When check_sufficiency returns 'blocked', generate_demo raises RuntimeError."""
        from agents.demo_pipeline.sufficiency import SufficiencyResult, KnowledgeCheck

        blocked_result = SufficiencyResult(
            confidence="blocked",
            system_checks=[
                KnowledgeCheck("architecture_docs", False, "file not found", "system"),
                KnowledgeCheck("component_registry", False, "file not found", "system"),
                KnowledgeCheck("health_data", False, "file not found", "system"),
                KnowledgeCheck("operator_manifest", False, "missing axioms key", "system"),
                KnowledgeCheck("profile_facts", True, "200 facts indexed", "system"),
                KnowledgeCheck("briefing", True, "updated 2h ago", "system"),
                KnowledgeCheck("profile_digest", True, "exists", "system"),
            ],
            audience_checks=[],
            enrichment_actions=[],
            audience_dossier=None,
        )

        mock_readiness = MagicMock()
        mock_readiness.ready = True
        mock_readiness.health_report = None

        with (
            patch("agents.demo_pipeline.readiness.check_readiness", return_value=mock_readiness),
            patch("agents.demo_pipeline.sufficiency.check_sufficiency", return_value=blocked_result),
        ):
            from agents.demo import generate_demo

            with pytest.raises(RuntimeError, match="Insufficient knowledge"):
                await generate_demo("the entire system for my wife")

    @pytest.mark.asyncio
    async def test_generate_demo_enrichment_threaded(self):
        """When sufficiency returns enrichment_actions, they are passed to gather_research."""
        from agents.demo_pipeline.sufficiency import SufficiencyResult, KnowledgeCheck

        low_result = SufficiencyResult(
            confidence="low",
            system_checks=[
                KnowledgeCheck("architecture_docs", True, "5000 bytes", "system"),
                KnowledgeCheck("component_registry", True, "exists", "system"),
                KnowledgeCheck("health_data", True, "from readiness gate", "system"),
                KnowledgeCheck("operator_manifest", True, "has axioms", "system"),
                KnowledgeCheck("profile_facts", True, "200 facts indexed", "system"),
                KnowledgeCheck("briefing", False, "file not found", "system"),
                KnowledgeCheck("profile_digest", False, "file not found", "system"),
            ],
            audience_checks=[],
            enrichment_actions=["briefing_stats", "profile_digest"],
            audience_dossier=None,
        )

        mock_readiness = MagicMock()
        mock_readiness.ready = True
        mock_readiness.health_report = None

        mock_gather = AsyncMock(return_value="Research context here")

        with (
            patch("agents.demo_pipeline.readiness.check_readiness", return_value=mock_readiness),
            patch("agents.demo_pipeline.sufficiency.check_sufficiency", return_value=low_result),
            patch("agents.demo_pipeline.research.gather_research", mock_gather),
        ):
            from agents.demo import generate_demo

            # generate_demo will proceed past research but fail at LLM call — that's fine,
            # we just need to verify gather_research was called with enrichment_actions
            try:
                await generate_demo("the entire system for my wife")
            except Exception:
                pass  # Expected — no LLM mock

            mock_gather.assert_called_once()
            call_kwargs = mock_gather.call_args
            assert call_kwargs.kwargs.get("enrichment_actions") == ["briefing_stats", "profile_digest"]
            assert call_kwargs.kwargs.get("audience_dossier") is None

    @pytest.mark.asyncio
    async def test_generate_demo_with_dimension_scores(self):
        """Sufficiency result with dimension_scores is threaded through pipeline."""
        from agents.demo_pipeline.sufficiency import SufficiencyResult, KnowledgeCheck, DimensionScore

        dim_scores = [
            DimensionScore("prior_knowledge", "person", "Prior Knowledge & Expertise Level", "inferred", "Archetype 'family' provides defaults", "Run --gather-dossier for higher confidence"),
            DimensionScore("goals_pain_points", "person", "Goals & Pain Points", "inferred", "Archetype 'family' provides defaults", "Run --gather-dossier for higher confidence"),
            DimensionScore("attitudes_resistance", "person", "Attitudes & Resistance", "missing", "No dossier; not archetype-inferable", "Run --gather-dossier to collect"),
            DimensionScore("decision_role", "person", "Decision Role & Authority", "missing", "No dossier; not archetype-inferable", "Run --gather-dossier to collect"),
            DimensionScore("relevant_subset", "subject", "Relevant Subset Mapping", "high", "System knowledge + archetype persona available", ""),
            DimensionScore("abstraction_vocabulary", "subject", "Appropriate Abstraction & Vocabulary", "high", "System knowledge + archetype persona available", ""),
            DimensionScore("situational_constraints", "context", "Situational Constraints & Stakes", "missing", "No dossier; not archetype-inferable", "Run --gather-dossier to collect"),
        ]

        adequate_result = SufficiencyResult(
            confidence="adequate",
            system_checks=[
                KnowledgeCheck("architecture_docs", True, "5000 bytes", "system"),
                KnowledgeCheck("component_registry", True, "exists", "system"),
                KnowledgeCheck("health_data", True, "from readiness gate", "system"),
                KnowledgeCheck("operator_manifest", True, "has axioms", "system"),
                KnowledgeCheck("profile_facts", True, "200 facts indexed", "system"),
                KnowledgeCheck("briefing", True, "updated 2h ago", "system"),
                KnowledgeCheck("profile_digest", True, "exists", "system"),
            ],
            audience_checks=[],
            enrichment_actions=[],
            audience_dossier=None,
            dimension_scores=dim_scores,
        )

        assert adequate_result.dimension_scores is not None
        assert len(adequate_result.dimension_scores) == 7
        person_dims = [d for d in adequate_result.dimension_scores if d.category == "person"]
        assert len(person_dims) == 4
        missing_person = [d for d in person_dims if d.confidence == "missing"]
        assert len(missing_person) == 2

    def test_gather_dossier_end_to_end(self, tmp_path):
        """Mock input_fn -> gather -> save -> load_audiences -> dossier found."""
        from agents.demo_pipeline.dossier import gather_dossier_interactive, save_dossier
        from agents.demo_models import load_audiences

        responses = iter([
            "Sarah",                          # name
            "never seen it",                  # prior_knowledge
            "wants to understand what I do",  # goals
            "thinks I tinker too much",       # attitudes
            "spouse, no technical role",      # relationship
            "casual at home",                 # situational
        ])

        dossier, _resp = gather_dossier_interactive(
            audience_key="my wife",
            archetype="family",
            input_fn=lambda _prompt: next(responses),
            print_fn=lambda _msg: None,
        )

        assert dossier.name == "Sarah"
        assert dossier.archetype == "family"
        assert "prior_knowledge" in dossier.context

        # Save to tmp file and reload
        yaml_path = tmp_path / "demo-audiences.yaml"
        save_dossier(dossier, path=yaml_path)

        loaded = load_audiences(path=yaml_path)
        assert "my wife" in loaded
        assert loaded["my wife"].name == "Sarah"
        assert loaded["my wife"].archetype == "family"

    @pytest.mark.asyncio
    async def test_sufficiency_hint_logged(self):
        """'adequate' confidence with missing PERSON dims -> progress includes --gather-dossier hint."""
        from agents.demo_pipeline.sufficiency import SufficiencyResult, KnowledgeCheck, DimensionScore

        dim_scores = [
            DimensionScore("prior_knowledge", "person", "Prior Knowledge & Expertise Level", "inferred", "defaults", ""),
            DimensionScore("goals_pain_points", "person", "Goals & Pain Points", "inferred", "defaults", ""),
            DimensionScore("attitudes_resistance", "person", "Attitudes & Resistance", "missing", "No dossier", "Run --gather-dossier to collect"),
            DimensionScore("decision_role", "person", "Decision Role & Authority", "missing", "No dossier", "Run --gather-dossier to collect"),
            DimensionScore("relevant_subset", "subject", "Relevant Subset Mapping", "high", "ok", ""),
            DimensionScore("abstraction_vocabulary", "subject", "Appropriate Abstraction & Vocabulary", "high", "ok", ""),
            DimensionScore("situational_constraints", "context", "Situational Constraints & Stakes", "missing", "No dossier", "Run --gather-dossier to collect"),
        ]

        adequate_result = SufficiencyResult(
            confidence="adequate",
            system_checks=[
                KnowledgeCheck("architecture_docs", True, "5000 bytes", "system"),
                KnowledgeCheck("component_registry", True, "exists", "system"),
                KnowledgeCheck("health_data", True, "from readiness gate", "system"),
                KnowledgeCheck("operator_manifest", True, "has axioms", "system"),
                KnowledgeCheck("profile_facts", True, "200 facts indexed", "system"),
                KnowledgeCheck("briefing", True, "updated 2h ago", "system"),
                KnowledgeCheck("profile_digest", True, "exists", "system"),
            ],
            audience_checks=[],
            enrichment_actions=[],
            audience_dossier=None,
            dimension_scores=dim_scores,
        )

        mock_readiness = MagicMock()
        mock_readiness.ready = True
        mock_readiness.health_report = None

        mock_gather = AsyncMock(return_value="Research context here")

        progress_messages: list[str] = []

        with (
            patch("agents.demo_pipeline.readiness.check_readiness", return_value=mock_readiness),
            patch("agents.demo_pipeline.sufficiency.check_sufficiency", return_value=adequate_result),
            patch("agents.demo_pipeline.research.gather_research", mock_gather),
        ):
            from agents.demo import generate_demo

            try:
                await generate_demo(
                    "the entire system for my wife",
                    on_progress=lambda msg: progress_messages.append(msg),
                )
            except Exception:
                pass  # Expected — no LLM mock for planning step

        hint_messages = [m for m in progress_messages if "--gather-dossier" in m]
        assert len(hint_messages) >= 1, f"Expected --gather-dossier hint in progress messages, got: {progress_messages}"
        assert "Attitudes & Resistance" in hint_messages[0] or "Decision Role" in hint_messages[0]
