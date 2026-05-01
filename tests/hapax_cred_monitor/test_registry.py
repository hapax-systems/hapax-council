"""Tests for the credential → service registry.

The registry is pure data; tests verify shape, uniqueness, and the
helper-function contracts (``lookup``, ``services_unblocked_by``,
``categorize``).
"""

from __future__ import annotations

from agents.hapax_cred_monitor.registry import (
    EXPECTED_ENTRIES,
    ExpectedEntry,
    categorize,
    expected_entry_names,
    lookup,
    services_unblocked_by,
)


class TestRegistryShape:
    def test_entry_names_are_unique(self) -> None:
        names = [e.name for e in EXPECTED_ENTRIES]
        assert len(names) == len(set(names))

    def test_every_entry_has_remediation(self) -> None:
        for entry in EXPECTED_ENTRIES:
            assert entry.remediation, f"entry {entry.name} has empty remediation"
            assert "pass insert" in entry.remediation, (
                f"entry {entry.name} remediation must use 'pass insert' form"
            )

    def test_remediation_is_exactly_pass_insert_with_entry_name(self) -> None:
        """Remediation must be exactly ``pass insert <entry_name>`` — no
        sample values, partial fingerprints, example tokens, or any other
        material that could leak credential shape. The contract is
        verified by string equality against the entry name, which
        forbids any extra payload by construction.
        """
        for entry in EXPECTED_ENTRIES:
            expected = f"pass insert {entry.name}"
            assert entry.remediation == expected, (
                f"entry {entry.name} remediation {entry.remediation!r} != {expected!r}"
            )

    def test_every_entry_has_at_least_one_unblock(self) -> None:
        for entry in EXPECTED_ENTRIES:
            assert entry.unblocks, f"entry {entry.name} unblocks no services"

    def test_categories_are_known(self) -> None:
        known = {"publication", "attribution", "archival", "infra", "other"}
        for entry in EXPECTED_ENTRIES:
            assert entry.category in known, (
                f"entry {entry.name} has unknown category {entry.category}"
            )


class TestLookup:
    def test_known_entry(self) -> None:
        result = lookup("api/anthropic")
        assert isinstance(result, ExpectedEntry)
        assert result.name == "api/anthropic"

    def test_unknown_entry_returns_none(self) -> None:
        assert lookup("nonexistent/entry") is None


class TestServicesUnblockedBy:
    def test_empty_input_yields_empty_set(self) -> None:
        assert services_unblocked_by(frozenset()) == frozenset()

    def test_known_entry_yields_its_unblocks(self) -> None:
        services = services_unblocked_by(frozenset({"orcid/orcid"}))
        assert "hapax-orcid-verifier.timer" in services
        assert "hapax-datacite-mirror.timer" in services

    def test_unknown_entry_is_skipped_silently(self) -> None:
        services = services_unblocked_by(frozenset({"nonexistent/entry", "orcid/orcid"}))
        assert "hapax-orcid-verifier.timer" in services

    def test_multiple_entries_compose_unblock_sets(self) -> None:
        services = services_unblocked_by(
            frozenset({"orcid/orcid", "ia/access-key", "ia/secret-key"})
        )
        assert "hapax-orcid-verifier.timer" in services
        assert "internet-archive-ias3-publisher" in services


class TestCategorize:
    def test_categorize_returns_present_and_missing_per_category(self) -> None:
        present = frozenset({"api/anthropic"})
        missing = frozenset({"orcid/orcid", "zenodo/api-token"})
        views = categorize(present, missing)
        by_cat = {v.category: v for v in views}
        assert "infra" in by_cat
        assert "api/anthropic" in by_cat["infra"].present
        assert "publication" in by_cat
        assert "zenodo/api-token" in by_cat["publication"].missing


class TestExpectedEntryNames:
    def test_returns_frozenset(self) -> None:
        result = expected_entry_names()
        assert isinstance(result, frozenset)
        assert "api/anthropic" in result
