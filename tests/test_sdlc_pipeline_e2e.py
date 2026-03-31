"""End-to-end dry-run test for the SDLC pipeline.

Runs triage -> plan -> review -> axiom-gate in sequence using --dry-run
to verify output formats and state transitions without LLM calls.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.sdlc_axiom_judge import AxiomGateResult, run_axiom_gate
from scripts.sdlc_plan import PlanResult, run_plan
from scripts.sdlc_review import ReviewResult, run_review
from scripts.sdlc_triage import TriageResult, run_triage


class TestDryRunOutputFormats:
    """Verify dry-run produces valid structured output."""

    @patch("scripts.sdlc_triage.fetch_issue")
    def test_triage_output_format(self, mock_fetch):
        from sdlc.github import Issue

        mock_fetch.return_value = Issue(
            number=1,
            title="Fix typo",
            body="There is a typo in README",
        )
        result = run_triage(1, dry_run=True)
        assert isinstance(result, TriageResult)
        assert result.type in ("bug", "feature", "chore")
        assert result.complexity in ("S", "M", "L")
        # Should serialize to valid JSON.
        json.loads(result.model_dump_json())

    @patch("scripts.sdlc_plan.fetch_issue")
    @patch("scripts.sdlc_plan.post_issue_comment")
    def test_plan_output_format(self, mock_comment, mock_fetch):
        from sdlc.github import Issue

        mock_fetch.return_value = Issue(
            number=1,
            title="Fix typo",
            body="There is a typo",
        )
        result = run_plan(1, dry_run=True, post_comment=False)
        assert isinstance(result, PlanResult)
        assert isinstance(result.acceptance_criteria, list)
        assert isinstance(result.estimated_diff_lines, int)
        json.loads(result.model_dump_json())

    def test_review_output_format(self):
        result = run_review(1, dry_run=True)
        assert isinstance(result, ReviewResult)
        assert result.verdict in ("approve", "request_changes")
        json.loads(result.model_dump_json())

    def test_axiom_gate_output_format(self):
        result = run_axiom_gate(1, dry_run=True)
        assert isinstance(result, AxiomGateResult)
        assert result.overall in ("pass", "block", "advisory")
        assert isinstance(result.structural.passed, bool)
        json.loads(result.model_dump_json())


class TestSimilarClosedIssues:
    def test_skip_github_returns_empty(self):
        from scripts.sdlc_triage import find_similar_closed

        result = find_similar_closed("Fix typo", "There is a typo", skip_github=True)
        assert result == []

    def test_extract_keywords(self):
        from scripts.sdlc_triage import _extract_search_keywords

        kw = _extract_search_keywords("Fix broken webhook handler", "The webhook times out")
        assert "webhook" in kw
        assert "the" not in kw
        assert len(kw) <= 5

    @patch("scripts.sdlc_triage.fetch_issue")
    def test_triage_with_skip_similar(self, mock_fetch):
        from sdlc.github import Issue

        mock_fetch.return_value = Issue(number=1, title="Fix typo", body="Typo in README")
        result = run_triage(1, dry_run=True, skip_similar=True)
        assert isinstance(result, TriageResult)


class TestDryRunPipelineSequence:
    """Verify the pipeline stages produce compatible outputs."""

    @patch("scripts.sdlc_triage.fetch_issue")
    @patch("scripts.sdlc_plan.fetch_issue")
    @patch("scripts.sdlc_plan.post_issue_comment")
    def test_triage_then_plan(self, mock_comment, mock_plan_fetch, mock_triage_fetch):
        from sdlc.github import Issue

        issue = Issue(number=1, title="Fix typo", body="Fix the typo in scout.py")
        mock_triage_fetch.return_value = issue
        mock_plan_fetch.return_value = issue

        triage = run_triage(1, dry_run=True)
        assert triage.reject_reason is None
        assert triage.complexity != "L"

        plan = run_plan(1, dry_run=True, post_comment=False)
        assert isinstance(plan.files_to_modify, list)

    def test_review_then_axiom_gate(self):
        review = run_review(1, dry_run=True)
        assert review.verdict == "approve"

        gate = run_axiom_gate(1, dry_run=True)
        assert gate.overall in ("pass", "advisory")
