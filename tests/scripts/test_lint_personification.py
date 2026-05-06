"""Tests for the anti-personification prompt-surface sweep."""

from __future__ import annotations

from pathlib import Path

from scripts import lint_personification


def _relative_paths() -> set[str]:
    root = Path(lint_personification.REPO_ROOT)
    return {str(path.relative_to(root)) for path in lint_personification._collect_paths()}


def test_collect_paths_includes_content_prep_prompt_surfaces() -> None:
    paths = _relative_paths()

    assert "agents/programme_manager/prompts/programme_plan.md" in paths
    assert "agents/hapax_daimonion/autonomous_narrative/segment_prompts.py" in paths
    assert "agents/hapax_daimonion/daily_segment_prep.py" in paths


def test_collect_paths_includes_review_rubric_surfaces() -> None:
    paths = _relative_paths()

    assert "shared/segment_quality_actionability.py" in paths
    assert "shared/segment_iteration_review.py" in paths
