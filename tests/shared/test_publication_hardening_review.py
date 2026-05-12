"""Tests for cross-provider publication review hardening."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from shared.publication_hardening.review import (
    DEFAULT_REVIEW_THRESHOLD,
    ReviewPass,
    attach_review_report_to_frontmatter,
    axiom_review_constraints,
    build_review_messages,
    parse_review_response,
)


def _completion_response(score: float, issues: list[str] | None = None) -> Callable[..., str]:
    def _complete(**kwargs: Any) -> str:
        assert kwargs["model"] == "balanced"
        return json.dumps(
            {
                "claims": [
                    {
                        "text": "The draft makes one test claim.",
                        "confidence": score,
                        "issues": issues or [],
                    }
                ],
                "overall_confidence": score,
                "flagged_issues": issues or [],
            }
        )

    return _complete


class TestReviewPass:
    def test_returns_structured_report(self) -> None:
        review = ReviewPass(completion=_completion_response(0.91))
        report = review.review_text("OpenAI's Codex is correctly attributed.")

        assert report.passes()
        assert report.overall_confidence == 0.91
        assert report.reviewer_model == "balanced"
        assert report.claims[0].confidence == 0.91

    def test_score_below_threshold_holds(self) -> None:
        review = ReviewPass(completion=_completion_response(0.42, ["accuracy unclear"]))
        report = review.review_text("Unsupported draft.")

        assert not report.passes()
        assert report.overall_confidence < DEFAULT_REVIEW_THRESHOLD
        assert "accuracy unclear" in report.flagged_issues

    def test_bad_json_fails_closed(self) -> None:
        report = parse_review_response("not json", reviewer_model="balanced")

        assert not report.passes()
        assert report.overall_confidence == 0.0
        assert report.flagged_issues[0].startswith("review_parse_failed")

    def test_known_entity_misattribution_clamps_score_below_threshold(self) -> None:
        review = ReviewPass(completion=_completion_response(0.95))
        report = review.review_text("Anthropic's Codex wrote the draft.")

        assert not report.passes()
        assert report.overall_confidence < DEFAULT_REVIEW_THRESHOLD
        assert any("known_entity_misattribution" in issue for issue in report.flagged_issues)

    def test_prompt_includes_axiom_summary_and_known_entities(self) -> None:
        messages = build_review_messages(
            "Draft body",
            author_model="claude-code",
            lint_report="none",
            known_entities_summary="codex -> OpenAI",
            deterministic_issues=("none",),
            metadata={"slug": "draft"},
        )

        user = messages[1]["content"]
        assert "single_user" in user
        assert "codex -> OpenAI" in user
        assert "claude-code" in user

    def test_axiom_constraints_include_registry_weights(self) -> None:
        constraints = axiom_review_constraints()

        assert len(constraints) == 5
        assert any("single_user (weight 100)" in constraint for constraint in constraints)

    def test_attach_review_report_to_frontmatter(self, tmp_path: Path) -> None:
        path = tmp_path / "draft.md"
        path.write_text("---\ntitle: Draft\n---\n\nBody\n", encoding="utf-8")

        report = ReviewPass(completion=_completion_response(0.88)).review_text("Body")
        assert attach_review_report_to_frontmatter(path, report) is True

        frontmatter = yaml.safe_load(path.read_text(encoding="utf-8").split("---", 2)[1])
        assert frontmatter["publication_review"]["overall_confidence"] == 0.88
