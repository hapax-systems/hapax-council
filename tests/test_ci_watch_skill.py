"""Regression pins for the CI-watch skill's GitHub API surface."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL = REPO_ROOT / "skills" / "ci-watch" / "SKILL.md"


def test_ci_watch_skill_uses_rest_core_for_pr_status() -> None:
    text = SKILL.read_text(encoding="utf-8")
    forbidden = [
        "gh pr checks",
        "statusCheckRollup",
        "--watch --fail-fast",
    ]
    for needle in forbidden:
        assert needle not in text
    assert "gh api --method GET" in text
    assert "gh api --paginate --method GET" in text
    assert "/check-runs" in text
    assert "check-runs?per_page=100" in text
    assert "/status" in text
