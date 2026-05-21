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


# ── Synthetic brief parsing ────────────────────────────────────────────────

VALID_BRIEF = """\
# Test Refusal Brief

**Slug:** `test-slug`
**Axiom tag:** `single_user`
**Status:** REFUSED
**Refusal classification:** test-class
**Date:** 2026-05-21
**CI guard:** tests/test_example.py
"""

LIFTED_BRIEF = """\
# Lifted Brief

**Slug:** `lifted-slug`
**Axiom tag:** `executive_function`
**Status:** LIFTED
**Refusal classification:** lifted-class
**Date:** 2026-05-01
"""

REGRESSED_BRIEF = """\
# Regressed Brief

**Slug:** `regressed-slug`
**Axiom tag:** `corporate_boundary`
**Status:** REGRESSED
**Refusal classification:** regressed-class
**Date:** 2026-05-10
"""


class TestParseBrief:
    def test_parse_valid_brief(self, tmp_path):
        from shared.refusal_registry import _parse_brief

        brief = tmp_path / "test-brief.md"
        brief.write_text(VALID_BRIEF)
        entry = _parse_brief(brief)
        assert entry is not None
        assert entry.slug == "test-slug"
        assert entry.title == "Test Refusal Brief"
        assert entry.status == RefusalStatus.REFUSED
        assert entry.axiom_tags == ["single_user"]
        assert entry.classification == "test-class"
        assert entry.date == "2026-05-21"
        assert entry.ci_guard == "tests/test_example.py"

    def test_parse_lifted_status(self, tmp_path):
        from shared.refusal_registry import _parse_brief

        brief = tmp_path / "lifted.md"
        brief.write_text(LIFTED_BRIEF)
        entry = _parse_brief(brief)
        assert entry is not None
        assert entry.status == RefusalStatus.LIFTED

    def test_parse_regressed_status(self, tmp_path):
        from shared.refusal_registry import _parse_brief

        brief = tmp_path / "regressed.md"
        brief.write_text(REGRESSED_BRIEF)
        entry = _parse_brief(brief)
        assert entry is not None
        assert entry.status == RefusalStatus.REGRESSED

    def test_parse_unreadable_file_returns_none(self, tmp_path):
        from shared.refusal_registry import _parse_brief

        missing = tmp_path / "does-not-exist.md"
        assert _parse_brief(missing) is None

    def test_parse_brief_with_receive_only_exception(self, tmp_path):
        from shared.refusal_registry import _parse_brief

        content = VALID_BRIEF + "\n## Receive-Only Exception\nAllowed for inbound.\n"
        brief = tmp_path / "receive-only.md"
        brief.write_text(content)
        entry = _parse_brief(brief)
        assert entry is not None
        assert entry.receive_only_exception == "test-slug"

    def test_parse_brief_with_permanent_lift(self, tmp_path):
        from shared.refusal_registry import _parse_brief

        content = VALID_BRIEF + "\n## Lift conditions\nThis is a permanent refusal.\n"
        brief = tmp_path / "permanent.md"
        brief.write_text(content)
        entry = _parse_brief(brief)
        assert entry is not None
        assert entry.lift_condition_type == "permanent"

    def test_parse_brief_with_conditional_lift(self, tmp_path):
        from shared.refusal_registry import _parse_brief

        content = VALID_BRIEF + "\n## Lift conditions\nLifted when approval granted.\n"
        brief = tmp_path / "conditional.md"
        brief.write_text(content)
        entry = _parse_brief(brief)
        assert entry is not None
        assert entry.lift_condition_type == "conditional"

    def test_parse_brief_with_lifecycle_probe_lift(self, tmp_path):
        from shared.refusal_registry import _parse_brief

        content = VALID_BRIEF + "\n## Lift conditions\nRecheck in 90 days.\n"
        brief = tmp_path / "lifecycle.md"
        brief.write_text(content)
        entry = _parse_brief(brief)
        assert entry is not None
        assert entry.lift_condition_type == "lifecycle_probe"


class TestLoadRegistrySynthetic:
    def test_skips_underscore_prefixed_files(self, tmp_path):
        load_registry.cache_clear()
        (tmp_path / "valid.md").write_text(VALID_BRIEF)
        (tmp_path / "_template.md").write_text(VALID_BRIEF)
        entries = load_registry(briefs_dir=tmp_path)
        assert len(entries) == 1
        assert entries[0].slug == "test-slug"
        load_registry.cache_clear()

    def test_empty_directory(self, tmp_path):
        load_registry.cache_clear()
        entries = load_registry(briefs_dir=tmp_path)
        assert entries == []
        load_registry.cache_clear()

    def test_duplicate_slugs_both_loaded(self, tmp_path):
        load_registry.cache_clear()
        (tmp_path / "a.md").write_text(VALID_BRIEF)
        (tmp_path / "b.md").write_text(VALID_BRIEF)
        entries = load_registry(briefs_dir=tmp_path)
        assert len(entries) == 2
        assert entries[0].slug == entries[1].slug == "test-slug"
        load_registry.cache_clear()


class TestSerializationRoundTrip:
    def test_refusal_entry_roundtrip(self, tmp_path):
        from shared.refusal_registry import RefusalEntry, _parse_brief

        brief = tmp_path / "roundtrip.md"
        brief.write_text(VALID_BRIEF)
        entry = _parse_brief(brief)
        assert entry is not None
        dumped = entry.model_dump()
        restored = RefusalEntry.model_validate(dumped)
        assert restored == entry

    def test_refusal_entry_json_roundtrip(self, tmp_path):
        from shared.refusal_registry import RefusalEntry, _parse_brief

        brief = tmp_path / "json-rt.md"
        brief.write_text(VALID_BRIEF)
        entry = _parse_brief(brief)
        assert entry is not None
        json_str = entry.model_dump_json()
        restored = RefusalEntry.model_validate_json(json_str)
        assert restored == entry
