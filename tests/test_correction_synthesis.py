"""Tests for correction synthesis — correction → profile facts pipeline."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from shared.correction_synthesis import (
    MIN_CORRECTIONS,
    SynthesisResult,
    SynthesizedFact,
    synthesize_corrections,
)


def _make_corrections(n: int, dimension: str = "activity") -> list[dict]:
    """Generate n correction dicts."""
    return [
        {
            "dimension": dimension,
            "original_value": "coding",
            "corrected_value": "writing",
            "context": "in Obsidian",
            "hour": 20 + (i % 4),
            "flow_score": 0.3 + (i * 0.05),
        }
        for i in range(n)
    ]


class TestSynthesizeCorrections:
    def test_too_few_corrections(self):
        """Below MIN_CORRECTIONS threshold returns early."""
        result = asyncio.run(synthesize_corrections([{"dimension": "activity"}]))
        assert result.facts == []
        assert "Too few" in result.summary

    def test_exact_threshold(self):
        """Exactly MIN_CORRECTIONS triggers synthesis."""
        corrections = _make_corrections(MIN_CORRECTIONS)
        mock_result = SynthesisResult(
            facts=[
                SynthesizedFact(
                    dimension="work_patterns",
                    key="evening_obsidian",
                    value="Writes in Obsidian in the evening",
                    confidence=0.7,
                    correction_count=3,
                )
            ],
            summary="Found 1 pattern.",
        )

        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value=MagicMock(output=mock_result))

        with patch("pydantic_ai.Agent", return_value=mock_agent):
            result = asyncio.run(synthesize_corrections(corrections))

        assert len(result.facts) == 1
        assert result.facts[0].dimension == "work_patterns"
        assert result.facts[0].key == "evening_obsidian"
        assert result.corrections_analyzed == MIN_CORRECTIONS

    def test_llm_receives_formatted_corrections(self):
        """Verify corrections are formatted correctly for the LLM."""
        corrections = _make_corrections(5)
        mock_result = SynthesisResult(facts=[], summary="No patterns.")
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value=MagicMock(output=mock_result))

        with patch("pydantic_ai.Agent", return_value=mock_agent):
            asyncio.run(synthesize_corrections(corrections))

        # Check the user message passed to the agent
        call_args = mock_agent.run.call_args
        user_msg = call_args[0][0]
        assert "5 accumulated corrections" in user_msg
        assert 'system said "coding"' in user_msg
        assert 'operator said "writing"' in user_msg
        assert "detail: in Obsidian" in user_msg

    def test_multiple_facts_extracted(self):
        """Multiple patterns from diverse corrections."""
        corrections = _make_corrections(10) + _make_corrections(5, dimension="flow")
        mock_result = SynthesisResult(
            facts=[
                SynthesizedFact(
                    dimension="work_patterns",
                    key="evening_obsidian",
                    value="Writes in Obsidian",
                    confidence=0.85,
                    correction_count=10,
                ),
                SynthesizedFact(
                    dimension="energy_and_attention",
                    key="flow_underestimate",
                    value="Flow state often deeper than system estimates",
                    confidence=0.7,
                    correction_count=5,
                ),
            ],
            summary="Found 2 patterns.",
        )
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value=MagicMock(output=mock_result))

        with patch("pydantic_ai.Agent", return_value=mock_agent):
            result = asyncio.run(synthesize_corrections(corrections))

        assert len(result.facts) == 2
        assert result.corrections_analyzed == 15


class TestRunCorrectionSynthesis:
    def test_no_corrections(self):
        """Empty correction store returns early."""
        from shared.correction_synthesis import run_correction_synthesis

        mock_store = MagicMock()
        mock_store.get_all.return_value = []
        mock_store.ensure_collection.return_value = None

        with patch("shared.correction_memory.CorrectionStore", return_value=mock_store):
            result = asyncio.run(run_correction_synthesis())

        assert "No corrections" in result

    def test_full_pipeline(self):
        """End-to-end: corrections → synthesis → apply_corrections."""
        from shared.correction_memory import Correction
        from shared.correction_synthesis import run_correction_synthesis

        corrections = [
            Correction(
                dimension="activity",
                original_value="coding",
                corrected_value="writing",
                context="Obsidian",
                hour=21,
                flow_score=0.4,
            )
            for _ in range(5)
        ]

        mock_store = MagicMock()
        mock_store.get_all.return_value = corrections
        mock_store.ensure_collection.return_value = None

        mock_synthesis_result = SynthesisResult(
            facts=[
                SynthesizedFact(
                    dimension="work_patterns",
                    key="evening_writing",
                    value="Writes in Obsidian evenings",
                    confidence=0.75,
                    correction_count=5,
                )
            ],
            summary="1 pattern.",
        )

        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value=MagicMock(output=mock_synthesis_result))

        with (
            patch("shared.correction_memory.CorrectionStore", return_value=mock_store),
            patch("pydantic_ai.Agent", return_value=mock_agent),
            patch(
                "agents.profiler.apply_corrections",
                return_value="Applied corrections (1 corrected). Profile v5, 42 total facts.",
            ) as mock_apply,
        ):
            result = asyncio.run(run_correction_synthesis())

        # Verify apply_corrections was called with the right structure
        mock_apply.assert_called_once()
        applied = mock_apply.call_args[0][0]
        assert len(applied) == 1
        assert applied[0]["dimension"] == "work_patterns"
        assert applied[0]["key"] == "evening_writing"
        assert applied[0]["value"] == "Writes in Obsidian evenings"

        assert "Synthesized 1 profile facts" in result
        assert "5 corrections" in result
