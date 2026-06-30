"""Tests for the CapDLC lifecycle registry dark stub."""

from __future__ import annotations

from shared.capdlc_lifecycle import (
    CAPDLC_CANONICAL_LABEL,
    CAPDLC_DARK_STUB,
    CAPDLC_LIFECYCLE_REGISTRY,
    CAPDLC_SLUG,
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
    assert resolve_capdlc_lifecycle("capdlc") is CAPDLC_DARK_STUB
    assert resolve_capdlc_lifecycle("MDLC") is CAPDLC_DARK_STUB


def test_dark_specified_stub_is_falsy_and_unmeasured() -> None:
    assert CAPDLC_DARK_STUB.lifecycle_state is CapDLCLifecycleState.DARK_SPECIFIED
    assert CAPDLC_DARK_STUB.measured_value is None
    assert CAPDLC_DARK_STUB.is_measured is False
    assert bool(CAPDLC_DARK_STUB) is False


def test_dark_stub_is_not_counted_as_measured_value() -> None:
    assert measured_capdlc_entries() == ()
