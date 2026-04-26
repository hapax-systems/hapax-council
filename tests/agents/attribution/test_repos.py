"""Tests for ``agents.attribution.repos``."""

from __future__ import annotations

from agents.attribution.repos import HAPAX_REPOS, HapaxRepo


class TestHapaxRepoDataclass:
    def test_constructable(self) -> None:
        repo = HapaxRepo(
            slug="x",
            git_url="https://github.com/ryanklee/x",
            description="x",
        )
        assert repo.slug == "x"


class TestHapaxRepos:
    def test_contains_council(self) -> None:
        slugs = {r.slug for r in HAPAX_REPOS}
        assert "hapax-council" in slugs

    def test_contains_constitution(self) -> None:
        slugs = {r.slug for r in HAPAX_REPOS}
        assert "hapax-constitution" in slugs

    def test_all_repos_have_github_urls(self) -> None:
        for repo in HAPAX_REPOS:
            assert repo.git_url.startswith("https://github.com/ryanklee/"), (
                f"{repo.slug} git_url should be ryanklee/<slug> form"
            )

    def test_slugs_are_unique(self) -> None:
        slugs = [r.slug for r in HAPAX_REPOS]
        assert len(slugs) == len(set(slugs))

    def test_descriptions_non_empty(self) -> None:
        for repo in HAPAX_REPOS:
            assert repo.description.strip()

    def test_at_least_seven_repos(self) -> None:
        """V5 weave names 9 repos workspace-wide; first-party Hapax repos
        are at least 7 (council + constitution + officium + watch +
        phone + mcp + assets); upstream clones (tabbyAPI,
        atlas-voice-training) are excluded."""
        assert len(HAPAX_REPOS) >= 7
