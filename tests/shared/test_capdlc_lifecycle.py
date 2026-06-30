"""Tests for the CapDLC lifecycle registry dark stub."""

from __future__ import annotations

import shared.capdlc_lifecycle as capdlc_lifecycle
from shared.capdlc_lifecycle import (
    CAPDLC_CANONICAL_LABEL,
    CAPDLC_DARK_STUB,
    CAPDLC_LIFECYCLE_REGISTRY,
    CAPDLC_SLUG,
    CapDLCLifecycleEntry,
    CapDLCLifecycleState,
    measured_capdlc_entries,
    resolve_capdlc_lifecycle,
)


def test_registry_uses_capdlc_as_future_facing_label() -> None:
    entry = CAPDLC_LIFECYCLE_REGISTRY[CAPDLC_SLUG]

    assert entry.canonical_label == CAPDLC_CANONICAL_LABEL == "CapDLC"
    assert "MDLC" in entry.legacy_labels
    assert entry.slug == "capdlc"


def test_legacy_mdlc_resolves_only_as_provenance_alias() -> None:
    assert resolve_capdlc_lifecycle("CapDLC") is CAPDLC_DARK_STUB
    assert resolve_capdlc_lifecycle("  CapDLC  ") is CAPDLC_DARK_STUB
    assert resolve_capdlc_lifecycle("capdlc") is CAPDLC_DARK_STUB
    assert resolve_capdlc_lifecycle("MDLC") is CAPDLC_DARK_STUB
    assert resolve_capdlc_lifecycle("  mdlc  ") is CAPDLC_DARK_STUB
    assert resolve_capdlc_lifecycle("MonDLC") is None
    assert resolve_capdlc_lifecycle("") is None


def test_dark_specified_stub_is_falsy_and_unmeasured() -> None:
    assert CAPDLC_DARK_STUB.lifecycle_state is CapDLCLifecycleState.DARK_SPECIFIED
    assert CAPDLC_DARK_STUB.measured_value is None
    assert CAPDLC_DARK_STUB.is_measured is False
    assert bool(CAPDLC_DARK_STUB) is False


def test_dark_stub_is_not_counted_as_measured_value() -> None:
    assert measured_capdlc_entries() == ()


def test_measured_entry_is_truthy() -> None:
    entry = CapDLCLifecycleEntry(
        slug="capdlc-measured-fixture",
        canonical_label="CapDLC",
        lifecycle_state=CapDLCLifecycleState.MEASURED,
        measured_value=1.0,
    )

    assert entry.is_measured is True
    assert bool(entry) is True


def test_measured_state_without_value_is_falsy() -> None:
    entry = CapDLCLifecycleEntry(
        slug="capdlc-empty-measured-fixture",
        canonical_label="CapDLC",
        lifecycle_state=CapDLCLifecycleState.MEASURED,
        measured_value=None,
    )

    assert entry.is_measured is False
    assert bool(entry) is False


def test_measured_registry_entries_are_returned(monkeypatch) -> None:
    entry = CapDLCLifecycleEntry(
        slug="capdlc-measured-fixture",
        canonical_label="CapDLC",
        lifecycle_state=CapDLCLifecycleState.MEASURED,
        measured_value=1.0,
    )

    monkeypatch.setitem(CAPDLC_LIFECYCLE_REGISTRY, entry.slug, entry)

    result = measured_capdlc_entries()

    assert result == (entry,)
    assert entry in result
    assert CAPDLC_DARK_STUB not in result


def test_public_exports_are_stable() -> None:
    expected_exports = {
        "CAPDLC_CANONICAL_LABEL",
        "CAPDLC_DARK_STUB",
        "CAPDLC_LEGACY_LABELS",
        "CAPDLC_LIFECYCLE_REGISTRY",
        "CAPDLC_SLUG",
        "CapDLCLifecycleEntry",
        "CapDLCLifecycleState",
        "measured_capdlc_entries",
        "resolve_capdlc_lifecycle",
    }

    assert set(capdlc_lifecycle.__all__) == expected_exports
    for name in expected_exports:
        assert getattr(capdlc_lifecycle, name) is capdlc_lifecycle.__dict__[name]
