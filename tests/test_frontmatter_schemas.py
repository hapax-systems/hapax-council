"""Tests for shared/frontmatter_schemas.py — frontmatter write-time validation."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from shared.frontmatter_schemas import (
    BridgePromptFrontmatter,
    BriefingFrontmatter,
    DecisionFrontmatter,
    DigestFrontmatter,
    GoalsFrontmatter,
    NudgeFrontmatter,
    RagSourceFrontmatter,
    validate_frontmatter,
)

# ── Valid frontmatter round-trips ────────────────────────────────────────────


class TestBriefingFrontmatter:
    def test_valid(self):
        fm = {
            "type": "briefing",
            "date": "2026-03-23",
            "source": "agents.briefing",
            "tags": ["system"],
        }
        result = validate_frontmatter(fm, BriefingFrontmatter)
        assert result.type == "briefing"
        assert result.date == "2026-03-23"

    def test_missing_date_raises(self):
        fm = {"type": "briefing", "source": "agents.briefing", "tags": ["system"]}
        with pytest.raises(ValueError, match="BriefingFrontmatter"):
            validate_frontmatter(fm, BriefingFrontmatter)

    def test_wrong_type_literal_raises(self):
        fm = {"type": "digest", "date": "2026-03-23", "source": "x", "tags": []}
        with pytest.raises(ValueError):
            validate_frontmatter(fm, BriefingFrontmatter)

    def test_extra_fields_allowed(self):
        fm = {"type": "briefing", "date": "2026-03-23", "source": "x", "tags": [], "custom": True}
        result = validate_frontmatter(fm, BriefingFrontmatter)
        assert result.type == "briefing"


class TestDigestFrontmatter:
    def test_valid(self):
        fm = {"type": "digest", "date": "2026-03-23", "source": "agents.digest", "tags": ["system"]}
        result = validate_frontmatter(fm, DigestFrontmatter)
        assert result.type == "digest"

    def test_missing_source_raises(self):
        fm = {"type": "digest", "date": "2026-03-23", "tags": []}
        with pytest.raises(ValueError, match="DigestFrontmatter"):
            validate_frontmatter(fm, DigestFrontmatter)


class TestNudgeFrontmatter:
    def test_valid(self):
        fm = {
            "type": "nudges",
            "updated": "2026-03-23T12:00:00Z",
            "source": "logos",
            "tags": ["system"],
        }
        result = validate_frontmatter(fm, NudgeFrontmatter)
        assert result.type == "nudges"

    def test_missing_updated_raises(self):
        fm = {"type": "nudges", "source": "logos", "tags": []}
        with pytest.raises(ValueError, match="NudgeFrontmatter"):
            validate_frontmatter(fm, NudgeFrontmatter)


class TestGoalsFrontmatter:
    def test_valid(self):
        fm = {
            "type": "goals",
            "updated": "2026-03-23T12:00:00Z",
            "source": "operator.json",
            "tags": [],
        }
        result = validate_frontmatter(fm, GoalsFrontmatter)
        assert result.type == "goals"


class TestDecisionFrontmatter:
    def test_valid(self):
        fm = {"type": "decision", "status": "decided", "date": "2026-03-23", "tags": ["decision"]}
        result = validate_frontmatter(fm, DecisionFrontmatter)
        assert result.status == "decided"

    def test_missing_status_raises(self):
        fm = {"type": "decision", "date": "2026-03-23", "tags": []}
        with pytest.raises(ValueError, match="DecisionFrontmatter"):
            validate_frontmatter(fm, DecisionFrontmatter)


class TestBridgePromptFrontmatter:
    def test_valid(self):
        fm = {"type": "bridge-prompt", "source": "system", "tags": ["bridge"]}
        result = validate_frontmatter(fm, BridgePromptFrontmatter)
        assert result.type == "bridge-prompt"


class TestRagSourceFrontmatter:
    def test_valid_minimal(self):
        fm = {"content_type": "document", "source_service": "gdrive"}
        result = validate_frontmatter(fm, RagSourceFrontmatter)
        assert result.content_type == "document"
        assert result.date is None

    def test_valid_with_date(self):
        fm = {"content_type": "email_metadata", "source_service": "gmail", "date": "2026-03-23"}
        result = validate_frontmatter(fm, RagSourceFrontmatter)
        assert result.date == "2026-03-23"

    def test_missing_content_type_raises(self):
        fm = {"source_service": "gdrive"}
        with pytest.raises(ValueError, match="RagSourceFrontmatter"):
            validate_frontmatter(fm, RagSourceFrontmatter)


# ── Property-based: any valid model instance round-trips through validate ────


@given(st.builds(BriefingFrontmatter))
@settings(max_examples=20)
def test_briefing_hypothesis_roundtrip(instance):
    data = instance.model_dump()
    result = validate_frontmatter(data, BriefingFrontmatter)
    assert result.type == "briefing"


@given(st.builds(RagSourceFrontmatter))
@settings(max_examples=20)
def test_rag_source_hypothesis_roundtrip(instance):
    data = instance.model_dump()
    result = validate_frontmatter(data, RagSourceFrontmatter)
    assert result.content_type == instance.content_type
