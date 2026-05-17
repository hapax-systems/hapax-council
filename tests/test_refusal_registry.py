"""Tests for the typed refusal registry — CI validation of brief consistency."""

from __future__ import annotations

import pytest

from shared.refusal_registry import (
    BRIEFS_DIR,
    RefusalStatus,
    load_registry,
    query_by_axiom,
    query_by_status,
    query_by_surface,
)


@pytest.fixture
def registry():
    load_registry.cache_clear()
    return load_registry()


class TestRegistryCompleteness:
    def test_indexes_all_briefs(self, registry):
        brief_count = len([p for p in BRIEFS_DIR.glob("*.md") if not p.name.startswith("_")])
        assert len(registry) == brief_count

    def test_every_entry_has_slug(self, registry):
        for entry in registry:
            assert entry.slug, f"Missing slug in {entry.file}"

    def test_every_entry_has_title(self, registry):
        for entry in registry:
            assert entry.title, f"Missing title in {entry.file}"

    def test_every_entry_has_status(self, registry):
        for entry in registry:
            assert entry.status in RefusalStatus


class TestQueryFunctions:
    def test_query_by_axiom_returns_results(self, registry):
        results = query_by_axiom("single_user", registry=registry)
        assert len(results) > 0

    def test_query_by_axiom_no_match(self, registry):
        results = query_by_axiom("nonexistent_axiom_xyz", registry=registry)
        assert len(results) == 0

    def test_query_by_status_refused(self, registry):
        results = query_by_status(RefusalStatus.REFUSED, registry=registry)
        assert len(results) > 0
        assert all(e.status == RefusalStatus.REFUSED for e in results)

    def test_query_by_surface(self, registry):
        results = query_by_surface("patreon", registry=registry)
        assert len(results) > 0


class TestFrontmatterConsistency:
    def test_slug_uniqueness_or_known_supersession(self, registry):
        from collections import Counter

        slugs = [e.slug for e in registry]
        dupes = {s for s, c in Counter(slugs).items() if c > 1}
        known_supersessions = {
            "leverage-REFUSED-github-discussions-enabled",
            "leverage-REFUSED-twitter-linkedin-substack-accounts",
            "leverage-REFUSED-wikipedia-auto-edit",
        }
        unexpected = dupes - known_supersessions
        assert not unexpected, f"Unexpected duplicate slugs: {unexpected}"

    def test_axiom_tags_are_non_empty(self, registry):
        for entry in registry:
            for tag in entry.axiom_tags:
                assert tag.strip(), f"Empty axiom tag in {entry.file}"

    def test_known_axioms_appear(self, registry):
        all_tags = set()
        for entry in registry:
            all_tags.update(entry.axiom_tags)
        for required in ("single_user", "feedback_full_automation_or_no_engagement"):
            assert any(required in t for t in all_tags), f"Expected axiom '{required}' not found"
