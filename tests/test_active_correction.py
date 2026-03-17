"""Tests for active correction seeking (WS3 Level 4)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from shared.active_correction import (
    CorrectionQuestion,
    CorrectionSeeker,
    read_pending_question,
)


class TestCorrectionQuestion:
    def test_basic(self):
        q = CorrectionQuestion(
            dimension="activity",
            current_value="coding",
            confidence=0.3,
            question="Is 'coding' right?",
        )
        assert q.dimension == "activity"
        assert not q.answered


class TestCorrectionSeeker:
    def test_high_confidence_no_question(self):
        seeker = CorrectionSeeker()
        result = seeker.evaluate(
            activity="coding", confidence=0.8  # high confidence
        )
        assert result is None

    def test_low_confidence_asks(self):
        seeker = CorrectionSeeker()
        result = seeker.evaluate(
            activity="coding", confidence=0.2  # low confidence
        )
        assert result is not None
        assert result.dimension == "activity"
        assert "coding" in result.question

    def test_daily_budget_exhausted(self):
        seeker = CorrectionSeeker(daily_budget=2, cooldown_s=0)
        # Ask twice
        seeker.evaluate(activity="coding", confidence=0.1)
        seeker.evaluate(activity="writing", confidence=0.1)
        # Third should be blocked
        result = seeker.evaluate(activity="browsing", confidence=0.1)
        assert result is None
        assert seeker.queries_remaining_today == 0

    def test_cooldown_blocks_rapid_queries(self):
        seeker = CorrectionSeeker(cooldown_s=600)
        seeker.evaluate(activity="coding", confidence=0.1)
        # Second query within cooldown
        result = seeker.evaluate(activity="writing", confidence=0.1)
        assert result is None

    def test_no_cooldown_when_zero(self):
        seeker = CorrectionSeeker(cooldown_s=0)
        seeker.evaluate(activity="coding", confidence=0.1)
        result = seeker.evaluate(activity="writing", confidence=0.1)
        assert result is not None

    def test_same_combo_not_asked_twice(self):
        seeker = CorrectionSeeker(cooldown_s=0)
        seeker.evaluate(activity="coding", confidence=0.1)
        # Same activity again — should not re-ask
        result = seeker.evaluate(activity="coding", confidence=0.1)
        assert result is None

    def test_different_activity_asked(self):
        seeker = CorrectionSeeker(cooldown_s=0)
        seeker.evaluate(activity="coding", confidence=0.1)
        result = seeker.evaluate(activity="writing", confidence=0.1)
        assert result is not None
        assert result.current_value == "writing"

    def test_degraded_stimmung_blocks(self):
        seeker = CorrectionSeeker()
        result = seeker.evaluate(
            activity="coding", confidence=0.1, stimmung_stance="degraded"
        )
        assert result is None

    def test_critical_stimmung_blocks(self):
        seeker = CorrectionSeeker()
        result = seeker.evaluate(
            activity="coding", confidence=0.1, stimmung_stance="critical"
        )
        assert result is None

    def test_cautious_stimmung_allows(self):
        seeker = CorrectionSeeker()
        result = seeker.evaluate(
            activity="coding", confidence=0.1, stimmung_stance="cautious"
        )
        assert result is not None

    def test_flow_question_when_activity_already_asked(self):
        seeker = CorrectionSeeker(cooldown_s=0)
        seeker.evaluate(activity="coding", confidence=0.1)
        # Activity already asked, should fall through to flow
        result = seeker.evaluate(
            activity="coding", flow_score=0.5, confidence=0.1
        )
        assert result is not None
        assert result.dimension == "flow"

    def test_record_answer(self):
        seeker = CorrectionSeeker(cooldown_s=0)
        seeker.record_answer("activity", "coding")
        # Should not ask about activity=coding
        result = seeker.evaluate(activity="coding", confidence=0.1)
        assert result is None

    def test_queries_remaining(self):
        seeker = CorrectionSeeker(daily_budget=3, cooldown_s=0)
        assert seeker.queries_remaining_today == 3
        seeker.evaluate(activity="coding", confidence=0.1)
        assert seeker.queries_remaining_today == 2

    def test_budget_resets_on_new_day(self):
        seeker = CorrectionSeeker(daily_budget=1, cooldown_s=0)
        seeker.evaluate(activity="coding", confidence=0.1)
        assert seeker.queries_remaining_today == 0
        # Simulate new day
        seeker._current_day -= 1
        seeker.evaluate(activity="writing", confidence=0.1)
        # Budget should have reset (but writing now used the new budget)
        assert seeker.queries_remaining_today == 0

    def test_correction_store_integration(self):
        """When correction store has prior corrections, question reflects that."""
        seeker = CorrectionSeeker(cooldown_s=0)

        mock_store = MagicMock()
        mock_store.search_for_dimension.return_value = [
            MagicMock(), MagicMock(), MagicMock()  # 3 prior corrections
        ]

        result = seeker.evaluate(
            activity="coding", confidence=0.1, correction_store=mock_store
        )
        assert result is not None
        assert "often" in result.question  # >= 2 corrections → "often uncertain"

    def test_no_correction_store_still_works(self):
        seeker = CorrectionSeeker(cooldown_s=0)
        result = seeker.evaluate(activity="coding", confidence=0.1)
        assert result is not None

    def test_total_asked(self):
        seeker = CorrectionSeeker(cooldown_s=0)
        assert seeker.total_asked == 0
        seeker.evaluate(activity="coding", confidence=0.1)
        assert seeker.total_asked == 1

    def test_empty_activity_no_question(self):
        seeker = CorrectionSeeker()
        result = seeker.evaluate(activity="", confidence=0.1)
        assert result is None  # nothing to ask about


class TestReadPendingQuestion:
    def test_no_file_returns_none(self):
        with patch("shared.active_correction.QUESTION_FILE", Path("/nonexistent")):
            assert read_pending_question() is None

    def test_reads_valid_question(self, tmp_path: Path):
        q = CorrectionQuestion(
            dimension="activity",
            current_value="coding",
            confidence=0.3,
            question="Is coding right?",
            timestamp=time.time(),
        )
        qfile = tmp_path / "question.json"
        qfile.write_text(json.dumps(q.model_dump()))
        with patch("shared.active_correction.QUESTION_FILE", qfile):
            result = read_pending_question()
        assert result is not None
        assert result.current_value == "coding"

    def test_stale_question_returns_none(self, tmp_path: Path):
        q = CorrectionQuestion(
            dimension="activity",
            current_value="coding",
            confidence=0.3,
            question="Is coding right?",
            timestamp=time.time() - 3600,  # 1 hour old
        )
        qfile = tmp_path / "question.json"
        qfile.write_text(json.dumps(q.model_dump()))
        with patch("shared.active_correction.QUESTION_FILE", qfile):
            assert read_pending_question() is None

    def test_answered_question_returns_none(self, tmp_path: Path):
        q = CorrectionQuestion(
            dimension="activity",
            current_value="coding",
            confidence=0.3,
            question="Is coding right?",
            timestamp=time.time(),
            answered=True,
        )
        qfile = tmp_path / "question.json"
        qfile.write_text(json.dumps(q.model_dump()))
        with patch("shared.active_correction.QUESTION_FILE", qfile):
            assert read_pending_question() is None
