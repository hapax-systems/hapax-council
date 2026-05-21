"""Tests for gap validation protocol tooling."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "gap_validate", REPO_ROOT / "scripts" / "gap-validate.py"
)
gap_validate = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
sys.modules["gap_validate"] = gap_validate
_spec.loader.exec_module(gap_validate)  # type: ignore[union-attr]


@pytest.fixture
def sample_gap() -> dict:
    return {
        "gap_id": "GAP-TEST",
        "title": "Test gap for validation",
        "request_ref": "REQ-TEST",
        "disposition": "execute",
        "validation_status": "in_progress",
        "uniqueness_score": 0.85,
        "composability_score": 0.90,
        "decay_rate_halflife_days": 180,
        "unique_apparatus_required": True,
        "apparatus_justification": "Requires stigmergic_coordination + temporal_grounding",
        "last_reviewed": "2026-05-20",
    }


@pytest.fixture
def sample_registry(sample_gap: dict) -> dict:
    return {
        "schema_version": 1,
        "registry_id": "test",
        "gaps": [sample_gap],
    }


class TestBuildSearchTerms:
    def test_includes_title(self, sample_gap: dict) -> None:
        terms = gap_validate.build_search_terms(sample_gap)
        assert sample_gap["title"] in terms

    def test_expands_domain_keywords(self, sample_gap: dict) -> None:
        terms = gap_validate.build_search_terms(sample_gap)
        assert any("stigmergy" in t for t in terms)


class TestComputeDecision:
    def test_high_confidence_with_4_novel(self) -> None:
        signals = [
            gap_validate.SignalResult(signal=f"s{i}", vote="novel", confidence=0.7)
            for i in range(4)
        ]
        signals.append(gap_validate.SignalResult(signal="s4", vote="inconclusive", confidence=0.0))
        signals.append(gap_validate.SignalResult(signal="s5", vote="inconclusive", confidence=0.0))
        decision, novel, total = gap_validate.compute_decision(signals)
        assert decision == "high_confidence_novel"
        assert novel == 4

    def test_medium_confidence_with_3_novel(self) -> None:
        signals = [
            gap_validate.SignalResult(signal=f"s{i}", vote="novel", confidence=0.6)
            for i in range(3)
        ]
        signals.append(
            gap_validate.SignalResult(signal="s3", vote="prior_art_exists", confidence=0.8)
        )
        signals.append(gap_validate.SignalResult(signal="s4", vote="inconclusive", confidence=0.0))
        signals.append(gap_validate.SignalResult(signal="s5", vote="inconclusive", confidence=0.0))
        decision, novel, total = gap_validate.compute_decision(signals)
        assert decision == "medium_confidence_novel"
        assert novel == 3

    def test_likely_not_novel_with_3_prior_art(self) -> None:
        signals = [
            gap_validate.SignalResult(signal=f"s{i}", vote="prior_art_exists", confidence=0.8)
            for i in range(3)
        ]
        signals.append(gap_validate.SignalResult(signal="s3", vote="novel", confidence=0.5))
        signals.append(gap_validate.SignalResult(signal="s4", vote="inconclusive", confidence=0.0))
        signals.append(gap_validate.SignalResult(signal="s5", vote="inconclusive", confidence=0.0))
        decision, novel, total = gap_validate.compute_decision(signals)
        assert decision == "likely_not_novel"
        assert novel == 1

    def test_low_confidence_when_mixed(self) -> None:
        signals = [
            gap_validate.SignalResult(signal="s0", vote="novel", confidence=0.5),
            gap_validate.SignalResult(signal="s1", vote="prior_art_exists", confidence=0.5),
            gap_validate.SignalResult(signal="s2", vote="inconclusive", confidence=0.0),
            gap_validate.SignalResult(signal="s3", vote="inconclusive", confidence=0.0),
            gap_validate.SignalResult(signal="s4", vote="inconclusive", confidence=0.0),
            gap_validate.SignalResult(signal="s5", vote="inconclusive", confidence=0.0),
        ]
        decision, novel, total = gap_validate.compute_decision(signals)
        assert decision == "low_confidence_needs_phase2"


class TestFindGap:
    def test_finds_existing_gap(self, sample_registry: dict) -> None:
        gap = gap_validate.find_gap(sample_registry, "GAP-TEST")
        assert gap is not None
        assert gap["title"] == "Test gap for validation"

    def test_returns_none_for_missing(self, sample_registry: dict) -> None:
        gap = gap_validate.find_gap(sample_registry, "GAP-NONEXISTENT")
        assert gap is None


class TestSignalResult:
    def test_dataclass_defaults(self) -> None:
        sr = gap_validate.SignalResult(signal="test", vote="novel", confidence=0.5)
        assert sr.evidence == []
        assert sr.source_urls == []
        assert sr.error is None


class TestPhase2Scaffolding:
    def test_forum_post_contains_gap_id(self, sample_gap: dict) -> None:
        post = gap_validate.generate_forum_post(sample_gap)
        assert "GAP-TEST" in post
        assert "Test gap for validation" in post

    def test_cold_email_contains_gap_metadata(self, sample_gap: dict) -> None:
        email = gap_validate.generate_cold_email(sample_gap)
        assert "GAP-TEST" in email
        assert "stigmergic_coordination" in email


class TestObservationGuide:
    def test_guide_content_has_7_questions(self) -> None:
        content = gap_validate.OBSERVATION_GUIDE_CONTENT
        question_count = content.count("**")
        assert question_count >= 7

    def test_guide_has_scoring_section(self) -> None:
        assert "## Scoring" in gap_validate.OBSERVATION_GUIDE_CONTENT

    def test_guide_has_ethics_section(self) -> None:
        assert "## Ethics" in gap_validate.OBSERVATION_GUIDE_CONTENT


class TestRegistryIntegration:
    def test_registry_loads(self) -> None:
        registry = gap_validate.load_registry()
        assert "gaps" in registry
        assert len(registry["gaps"]) >= 18

    def test_registry_has_validated_gaps(self) -> None:
        registry = gap_validate.load_registry()
        validated = [g for g in registry["gaps"] if g["validation_status"] == "validated_novel"]
        assert len(validated) >= 3
