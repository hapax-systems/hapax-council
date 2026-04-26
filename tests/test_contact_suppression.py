"""Unit tests for shared.contact_suppression."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from shared.contact_suppression import (
    SuppressionEntry,
    SuppressionList,
    append_entry,
    is_suppressed,
    load,
)


@pytest.fixture
def list_path(tmp_path: Path) -> Path:
    return tmp_path / "contact-suppression-list.yaml"


def test_load_returns_empty_when_file_missing(list_path: Path) -> None:
    result = load(path=list_path)
    assert isinstance(result, SuppressionList)
    assert result.entries == []
    assert result.version == 1


def test_append_creates_file_and_entry(list_path: Path) -> None:
    entry = append_entry(
        orcid="0000-0001-2345-6789",
        reason="operator manual add",
        initiator="operator_manual",
        path=list_path,
    )
    assert isinstance(entry, SuppressionEntry)
    assert list_path.exists()
    reloaded = load(path=list_path)
    assert len(reloaded.entries) == 1
    assert reloaded.entries[0].orcid == "0000-0001-2345-6789"


def test_append_is_idempotent_on_same_orcid_and_initiator(list_path: Path) -> None:
    first = append_entry(
        orcid="0000-0001-2345-6789",
        reason="first",
        initiator="operator_manual",
        path=list_path,
    )
    second = append_entry(
        orcid="0000-0001-2345-6789",
        reason="second",
        initiator="operator_manual",
        path=list_path,
    )
    assert first.reason == second.reason == "first"
    reloaded = load(path=list_path)
    assert len(reloaded.entries) == 1


def test_same_orcid_different_initiator_appends_two_entries(list_path: Path) -> None:
    append_entry(
        orcid="0000-0001-2345-6789",
        reason="hapax sent",
        initiator="hapax_send",
        path=list_path,
    )
    append_entry(
        orcid="0000-0001-2345-6789",
        reason="target opted out",
        initiator="target_optout",
        path=list_path,
    )
    reloaded = load(path=list_path)
    assert len(reloaded.entries) == 2


def test_is_suppressed_matches_any_initiator(list_path: Path) -> None:
    append_entry(
        orcid="0000-0001-2345-6789",
        reason="x",
        initiator="hapax_send",
        path=list_path,
    )
    assert is_suppressed("0000-0001-2345-6789", path=list_path)
    assert not is_suppressed("0000-0009-9999-9999", path=list_path)


def test_invalid_orcid_length_rejected(list_path: Path) -> None:
    with pytest.raises(Exception):
        append_entry(
            orcid="too-short",
            reason="x",
            initiator="operator_manual",
            path=list_path,
        )


def test_atomic_write_does_not_lose_prior_entries(list_path: Path) -> None:
    append_entry(
        orcid="0000-0001-0001-0001",
        reason="a",
        initiator="hapax_send",
        path=list_path,
    )
    append_entry(
        orcid="0000-0002-0002-0002",
        reason="b",
        initiator="operator_manual",
        path=list_path,
    )
    append_entry(
        orcid="0000-0003-0003-0003",
        reason="c",
        initiator="target_optout",
        path=list_path,
    )
    reloaded = load(path=list_path)
    assert {e.orcid for e in reloaded.entries} == {
        "0000-0001-0001-0001",
        "0000-0002-0002-0002",
        "0000-0003-0003-0003",
    }


def test_explicit_date_preserved(list_path: Path) -> None:
    fixed = datetime(2025, 1, 1, 12, tzinfo=UTC)
    entry = append_entry(
        orcid="0000-0001-2345-6789",
        reason="x",
        initiator="operator_manual",
        date=fixed,
        path=list_path,
    )
    assert entry.date == fixed
    reloaded = load(path=list_path)
    assert reloaded.entries[0].date == fixed


def test_yaml_header_present_after_first_write(list_path: Path) -> None:
    append_entry(
        orcid="0000-0001-2345-6789",
        reason="x",
        initiator="operator_manual",
        path=list_path,
    )
    raw = list_path.read_text()
    assert "APPEND-ONLY" in raw
    assert "governance primitive" in raw
