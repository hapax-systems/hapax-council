"""Tests for shared.contact_suppression.

181-LOC append-only contact suppression list — load, append_entry,
is_suppressed, is_suppressed_by_email_domain. Untested before this
commit.

Tests use the ``path=`` parameter so the operator's real
~/hapax-state/contact-suppression-list.yaml is never read or
mutated.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from shared.contact_suppression import (
    SuppressionEntry,
    SuppressionList,
    append_entry,
    is_suppressed,
    is_suppressed_by_email_domain,
    load,
)

VALID_ORCID = "0000-0001-2345-678X"


# ── SuppressionEntry validation ────────────────────────────────────


class TestSuppressionEntry:
    def test_orcid_only_valid(self) -> None:
        e = SuppressionEntry(
            orcid=VALID_ORCID,
            reason="test",
            initiator="operator_manual",
            date=datetime.now(UTC),
        )
        assert e.orcid == VALID_ORCID
        assert e.email_domain is None

    def test_email_domain_only_valid(self) -> None:
        e = SuppressionEntry(
            email_domain="example.com",
            reason="test",
            initiator="target_optout",
            date=datetime.now(UTC),
        )
        assert e.email_domain == "example.com"

    def test_both_orcid_and_email_domain_valid(self) -> None:
        e = SuppressionEntry(
            orcid=VALID_ORCID,
            email_domain="example.com",
            reason="test",
            initiator="hapax_send",
            date=datetime.now(UTC),
        )
        assert e.orcid == VALID_ORCID
        assert e.email_domain == "example.com"

    def test_neither_orcid_nor_email_raises(self) -> None:
        with pytest.raises(ValidationError):
            SuppressionEntry(
                reason="test",
                initiator="operator_manual",
                date=datetime.now(UTC),
            )

    def test_orcid_length_validation(self) -> None:
        """ORCID must be exactly 19 chars (`NNNN-NNNN-NNNN-NNNN`)."""
        with pytest.raises(ValidationError):
            SuppressionEntry(
                orcid="too-short",
                reason="test",
                initiator="operator_manual",
                date=datetime.now(UTC),
            )


# ── load ───────────────────────────────────────────────────────────


class TestLoad:
    def test_missing_file_returns_empty_list(self, tmp_path: Path) -> None:
        result = load(path=tmp_path / "nope.yaml")
        assert isinstance(result, SuppressionList)
        assert result.entries == []
        assert result.version == 1

    def test_loads_existing_yaml(self, tmp_path: Path) -> None:
        path = tmp_path / "list.yaml"
        # Pre-populate via append.
        append_entry(orcid=VALID_ORCID, reason="test entry", path=path)
        result = load(path=path)
        assert len(result.entries) == 1
        assert result.entries[0].orcid == VALID_ORCID


# ── append_entry ──────────────────────────────────────────────────


class TestAppendEntry:
    def test_first_entry_added(self, tmp_path: Path) -> None:
        path = tmp_path / "list.yaml"
        entry = append_entry(
            orcid=VALID_ORCID,
            reason="cold contact sent",
            initiator="hapax_send",
            path=path,
        )
        assert entry.orcid == VALID_ORCID
        result = load(path=path)
        assert len(result.entries) == 1

    def test_idempotent_on_identity_tuple(self, tmp_path: Path) -> None:
        """Same orcid + email_domain + initiator returns the existing
        entry, not a new one."""
        path = tmp_path / "list.yaml"
        first = append_entry(orcid=VALID_ORCID, reason="initial", path=path)
        second = append_entry(orcid=VALID_ORCID, reason="duplicate", path=path)
        # Returns the existing entry, not a fresh one.
        assert second.reason == first.reason
        # And the file still has just one entry.
        result = load(path=path)
        assert len(result.entries) == 1

    def test_different_initiators_are_distinct(self, tmp_path: Path) -> None:
        """Same orcid but different initiators → both entries kept."""
        path = tmp_path / "list.yaml"
        append_entry(
            orcid=VALID_ORCID,
            reason="manual",
            initiator="operator_manual",
            path=path,
        )
        append_entry(
            orcid=VALID_ORCID,
            reason="auto",
            initiator="hapax_send",
            path=path,
        )
        result = load(path=path)
        assert len(result.entries) == 2

    def test_atomic_write_no_partial(self, tmp_path: Path) -> None:
        path = tmp_path / "list.yaml"
        append_entry(orcid=VALID_ORCID, reason="x", path=path)
        # The .tmp suffix should be cleaned up.
        assert not (path.parent / (path.name + ".tmp")).exists()

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        path = tmp_path / "deep" / "nested" / "list.yaml"
        append_entry(orcid=VALID_ORCID, reason="x", path=path)
        assert path.exists()


# ── is_suppressed / is_suppressed_by_email_domain ─────────────────


class TestSuppressionLookup:
    def test_orcid_lookup_match(self, tmp_path: Path) -> None:
        path = tmp_path / "list.yaml"
        append_entry(orcid=VALID_ORCID, reason="x", path=path)
        assert is_suppressed(VALID_ORCID, path=path)

    def test_orcid_lookup_miss(self, tmp_path: Path) -> None:
        path = tmp_path / "list.yaml"
        append_entry(orcid=VALID_ORCID, reason="x", path=path)
        other = "0000-0002-2222-2222"
        assert not is_suppressed(other, path=path)

    def test_orcid_lookup_empty_file(self, tmp_path: Path) -> None:
        assert not is_suppressed(VALID_ORCID, path=tmp_path / "missing.yaml")

    def test_email_domain_lookup_match(self, tmp_path: Path) -> None:
        path = tmp_path / "list.yaml"
        append_entry(
            email_domain="acme.com",
            reason="optout",
            initiator="target_optout",
            path=path,
        )
        assert is_suppressed_by_email_domain("acme.com", path=path)

    def test_email_domain_lookup_miss(self, tmp_path: Path) -> None:
        path = tmp_path / "list.yaml"
        append_entry(
            email_domain="acme.com",
            reason="x",
            initiator="target_optout",
            path=path,
        )
        assert not is_suppressed_by_email_domain("other.com", path=path)

    def test_lookups_are_independent(self, tmp_path: Path) -> None:
        """ORCID-only entry doesn't show up in email-domain lookup, and
        vice versa."""
        path = tmp_path / "list.yaml"
        append_entry(orcid=VALID_ORCID, reason="x", path=path)
        append_entry(
            email_domain="acme.com",
            reason="y",
            initiator="target_optout",
            path=path,
        )
        # ORCID lookup hits ORCID entry but not domain entry
        assert is_suppressed(VALID_ORCID, path=path)
        # Domain lookup hits domain entry but not ORCID entry
        assert is_suppressed_by_email_domain("acme.com", path=path)
        # No cross-contamination
        assert not is_suppressed_by_email_domain("ignored", path=path)
