"""Tests for literature-grounded knowledge dimensions in the sufficiency gate."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agents.demo_models import AudienceDossier, AudiencePersona
from agents.demo_pipeline.sufficiency import (
    KNOWLEDGE_DIMENSIONS,
    DimensionScore,
    _audience_text_references_person,
    score_dimensions,
)

# Note: score_dimensions() now takes has_system_knowledge as a parameter
# instead of calling _system_knowledge_available() internally.


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_persona(**overrides) -> AudiencePersona:
    defaults = {
        "description": "Test persona",
        "tone": "casual",
        "vocabulary": "simple",
        "show": ["dashboard", "health"],
        "skip": ["internals"],
        "forbidden_terms": [],
        "max_scenes": 8,
    }
    defaults.update(overrides)
    return AudiencePersona(**defaults)


def _make_dossier(
    *,
    context: str = "",
    calibration: dict | None = None,
    archetype: str = "family",
    name: str = "Sarah",
    key: str = "my wife",
) -> AudienceDossier:
    return AudienceDossier(
        key=key,
        archetype=archetype,
        name=name,
        context=context,
        calibration=calibration or {},
    )


def _rich_dossier() -> AudienceDossier:
    """Dossier with data covering all PERSON dimensions."""
    return _make_dossier(
        context=(
            "No technical experience — complete beginner. "
            "Goal is to understand what the system does without jargon. "
            "Skeptical attitude toward AI — resistant to hype. "
            "Has no decision authority or budget role. "
            "Time constraint: 5-minute attention span."
        ),
        calibration={
            "emphasize": ["simplicity", "real-world benefit"],
            "skip": ["architecture", "code"],
        },
    )


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestScoreDimensionsWithDossier:
    """test_score_dimensions_with_dossier — all PERSON dims → 'high'."""

    def test_all_person_dims_high(self):
        persona = _make_persona()
        dossier = _rich_dossier()
        scores = score_dimensions("family", dossier, persona)

        person_scores = [s for s in scores if s.category == "person"]
        assert len(person_scores) == 4
        for s in person_scores:
            assert s.confidence == "high", f"{s.key} expected 'high', got '{s.confidence}'"
            assert s.action == ""

    def test_context_dim_high_with_rich_dossier(self):
        persona = _make_persona()
        dossier = _rich_dossier()
        scores = score_dimensions("family", dossier, persona)

        ctx_scores = [s for s in scores if s.category == "context"]
        assert len(ctx_scores) == 1
        assert ctx_scores[0].confidence == "high"


class TestScoreDimensionsArchetypeOnly:
    """test_score_dimensions_archetype_only — archetype_inferable → 'inferred', others → 'missing'."""

    def test_inferable_dims_inferred(self):
        persona = _make_persona()
        scores = score_dimensions("family", dossier=None, persona=persona, has_system_knowledge=False)

        for s in scores:
            dim = next(d for d in KNOWLEDGE_DIMENSIONS if d["key"] == s.key)
            if dim["archetype_inferable"]:
                assert s.confidence == "inferred", (
                    f"{s.key}: expected 'inferred', got '{s.confidence}'"
                )
            else:
                assert s.confidence == "missing", (
                    f"{s.key}: expected 'missing', got '{s.confidence}'"
                )

    def test_missing_dims_have_action(self):
        persona = _make_persona()
        scores = score_dimensions("family", dossier=None, persona=persona, has_system_knowledge=False)

        for s in scores:
            if s.confidence == "missing":
                assert s.action, f"{s.key}: missing dim should have action text"


class TestScoreDimensionsNoPersona:
    """test_score_dimensions_no_persona — all → 'low' or 'missing'."""

    def test_all_low_or_missing(self):
        scores = score_dimensions("family", dossier=None, persona=None)

        for s in scores:
            assert s.confidence in ("low", "missing"), (
                f"{s.key}: expected 'low'/'missing', got '{s.confidence}'"
            )

    def test_inferable_dims_are_low(self):
        scores = score_dimensions("family", dossier=None, persona=None)

        for s in scores:
            dim = next(d for d in KNOWLEDGE_DIMENSIONS if d["key"] == s.key)
            if dim["archetype_inferable"]:
                assert s.confidence == "low", f"{s.key}: expected 'low', got '{s.confidence}'"

    def test_non_inferable_dims_are_missing(self):
        scores = score_dimensions("family", dossier=None, persona=None)

        for s in scores:
            dim = next(d for d in KNOWLEDGE_DIMENSIONS if d["key"] == s.key)
            if not dim["archetype_inferable"]:
                assert s.confidence == "missing", (
                    f"{s.key}: expected 'missing', got '{s.confidence}'"
                )


class TestSubjectDimensionsFromSystemKnowledge:
    """test_subject_dimensions_from_system_knowledge — SUBJECT dims don't need dossier."""

    def test_subject_high_with_system_knowledge_and_persona(self):
        persona = _make_persona()
        scores = score_dimensions("family", dossier=None, persona=persona, has_system_knowledge=True)

        subject_scores = [s for s in scores if s.category == "subject"]
        assert len(subject_scores) == 2
        for s in subject_scores:
            assert s.confidence == "high", f"{s.key}: expected 'high', got '{s.confidence}'"

    def test_subject_inferred_without_system_knowledge(self):
        persona = _make_persona()
        scores = score_dimensions("family", dossier=None, persona=persona, has_system_knowledge=False)

        subject_scores = [s for s in scores if s.category == "subject"]
        for s in subject_scores:
            assert s.confidence == "inferred", (
                f"{s.key}: expected 'inferred', got '{s.confidence}'"
            )

    def test_subject_high_without_dossier(self):
        """SUBJECT dims reach 'high' even with no dossier — only need system knowledge + persona."""
        persona = _make_persona()
        scores = score_dimensions("family", dossier=None, persona=persona, has_system_knowledge=True)

        subject_scores = [s for s in scores if s.category == "subject"]
        for s in subject_scores:
            assert s.confidence == "high"


def _setup_profiles_dir(tmp_path: Path) -> Path:
    """Create a fake PROFILES_DIR with all required files so system checks pass."""
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "component-registry.yaml").write_text("components: []")
    (profiles / "health-history.jsonl").write_text("{}")
    (profiles / "briefing.md").write_text("# Briefing")
    (profiles / "ryan-digest.json").write_text("{}")
    return profiles


class TestSufficiencyWithDimensionScores:
    """test_sufficiency_with_dimension_scores — scores populated on SufficiencyResult."""

    @patch("shared.config.embed", return_value=[0.1] * 768)
    @patch("agents.demo_pipeline.sufficiency.get_qdrant")
    @patch("agents.demo_pipeline.sufficiency.get_operator", return_value={"axioms": {}})
    @patch("agents.demo_pipeline.sufficiency.load_audiences", return_value={})
    @patch("agents.demo_pipeline.sufficiency.load_personas")
    def test_dimension_scores_populated(
        self, mock_personas, mock_audiences, mock_operator, mock_qdrant, mock_embed, tmp_path
    ):
        from agents.demo_pipeline.sufficiency import check_sufficiency
        import agents.demo_pipeline.sufficiency as suf

        # Create real files
        profiles = _setup_profiles_dir(tmp_path)
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("x" * 5000)

        mock_personas.return_value = {"family": _make_persona()}
        mock_qdrant.return_value.get_collection.return_value.points_count = 500
        count_result = MagicMock()
        count_result.count = 500
        mock_qdrant.return_value.count.return_value = count_result

        orig_claude_md = suf._HAPAXROMANA_CLAUDE_MD
        orig_profiles = suf.PROFILES_DIR
        try:
            suf._HAPAXROMANA_CLAUDE_MD = claude_md
            suf.PROFILES_DIR = profiles
            result = check_sufficiency(
                scope="full",
                archetype="family",
                audience_text="my team",
                health_report={"status": "ok"},
            )
        finally:
            suf._HAPAXROMANA_CLAUDE_MD = orig_claude_md
            suf.PROFILES_DIR = orig_profiles

        assert hasattr(result, "dimension_scores")
        assert len(result.dimension_scores) == 7
        for ds in result.dimension_scores:
            assert isinstance(ds, DimensionScore)
            assert ds.key
            assert ds.category in ("person", "subject", "context")


class TestNamedPersonNoDossierCapsConfidence:
    """test_named_person_no_dossier_caps_confidence — 'my wife' + no dossier → max 'adequate'."""

    @patch("shared.config.embed", return_value=[0.1] * 768)
    @patch("agents.demo_pipeline.sufficiency.get_qdrant")
    @patch("agents.demo_pipeline.sufficiency.get_operator", return_value={"axioms": {}})
    @patch("agents.demo_pipeline.sufficiency.load_audiences", return_value={})
    @patch("agents.demo_pipeline.sufficiency.load_personas")
    def test_my_wife_caps_to_adequate(
        self, mock_personas, mock_audiences, mock_operator, mock_qdrant, mock_embed, tmp_path
    ):
        from agents.demo_pipeline.sufficiency import check_sufficiency
        import agents.demo_pipeline.sufficiency as suf

        profiles = _setup_profiles_dir(tmp_path)
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("x" * 5000)

        mock_personas.return_value = {"family": _make_persona()}
        mock_qdrant.return_value.get_collection.return_value.points_count = 500
        count_result = MagicMock()
        count_result.count = 500
        mock_qdrant.return_value.count.return_value = count_result

        orig_claude_md = suf._HAPAXROMANA_CLAUDE_MD
        orig_profiles = suf.PROFILES_DIR
        try:
            suf._HAPAXROMANA_CLAUDE_MD = claude_md
            suf.PROFILES_DIR = profiles
            result = check_sufficiency(
                scope="full",
                archetype="family",
                audience_text="my wife",
                health_report={"status": "ok"},
            )
        finally:
            suf._HAPAXROMANA_CLAUDE_MD = orig_claude_md
            suf.PROFILES_DIR = orig_profiles

        # No dossier matched → confidence capped at "adequate" despite system checks passing
        assert result.confidence == "adequate", (
            f"Expected 'adequate' but got '{result.confidence}'"
        )

    def test_person_reference_detection(self):
        assert _audience_text_references_person("my wife") is True
        assert _audience_text_references_person("my husband") is True
        assert _audience_text_references_person("my mom") is True
        assert _audience_text_references_person("My Friend") is True
        assert _audience_text_references_person("the team") is False
        assert _audience_text_references_person("leadership") is False
        assert _audience_text_references_person("my") is False
