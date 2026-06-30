"""Tests for the CapDLC lifecycle registry dark stub."""

from __future__ import annotations

import pytest

import shared.capdlc_lifecycle as capdlc_lifecycle
from shared.capdlc_lifecycle import (
    CAPDLC_CANONICAL_LABEL,
    CAPDLC_DARK_STUB,
    CAPDLC_LIFECYCLE_REGISTRY,
    CAPDLC_SLUG,
    CapDLCLifecycleEntry,
    CapDLCLifecycleState,
    GateResult,
    GateStatus,
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


def test_gate_status_taxonomy_is_identity_based() -> None:
    assert tuple(GateStatus) == (
        GateStatus.LIT,
        GateStatus.PARTIAL,
        GateStatus.DARK,
    )
    assert GateStatus("lit") is GateStatus.LIT
    assert GateStatus("partial") is GateStatus.PARTIAL
    assert GateStatus("dark") is GateStatus.DARK


@pytest.mark.parametrize("status", tuple(GateStatus))
def test_gate_status_truthiness_is_forbidden(status: GateStatus) -> None:
    with pytest.raises(TypeError, match="GateStatus truthiness is undefined"):
        bool(status)


@pytest.mark.parametrize("verdict", (True, False))
def test_lit_gate_result_requires_explicit_verdict(verdict: bool) -> None:
    result = GateResult(
        status=GateStatus.LIT,
        verdict=verdict,
        evidence_refs=("registry:fixture",),
    )

    assert result.status is GateStatus.LIT
    assert result.verdict is verdict
    assert result.evidence_refs == ("registry:fixture",)


def test_lit_gate_result_without_verdict_is_rejected() -> None:
    with pytest.raises(ValueError, match="LIT GateResult requires a verdict"):
        GateResult(status=GateStatus.LIT)


@pytest.mark.parametrize("status", (GateStatus.PARTIAL, GateStatus.DARK))
@pytest.mark.parametrize("verdict", (True, False))
def test_non_lit_gate_result_with_verdict_is_rejected(status: GateStatus, verdict: bool) -> None:
    with pytest.raises(ValueError, match="Only LIT GateResult may carry a verdict"):
        GateResult(status=status, verdict=verdict)


@pytest.mark.parametrize("status", (GateStatus.PARTIAL, GateStatus.DARK))
def test_non_lit_gate_result_is_verdict_absent(status: GateStatus) -> None:
    result = GateResult(status=status, reason="measurement not available")

    assert result.status is status
    assert result.verdict is None


@pytest.mark.parametrize("status", ("lit", True))
def test_gate_result_rejects_loose_status_values(status: object) -> None:
    with pytest.raises(TypeError, match="GateResult.status must be a GateStatus"):
        GateResult(status=status, verdict=True)  # type: ignore[arg-type]


def test_gate_result_rejects_non_boolean_verdict() -> None:
    with pytest.raises(TypeError, match="GateResult.verdict must be bool or None"):
        GateResult(status=GateStatus.LIT, verdict=1)  # type: ignore[arg-type]


def test_gate_result_truthiness_is_forbidden() -> None:
    result = GateResult(status=GateStatus.LIT, verdict=True)

    with pytest.raises(TypeError, match="GateResult truthiness is undefined"):
        bool(result)


def test_public_exports_are_stable() -> None:
    expected_exports = {
        "CAPDLC_CANONICAL_LABEL",
        "CAPDLC_DARK_STUB",
        "CAPDLC_LEGACY_LABELS",
        "CAPDLC_LIFECYCLE_REGISTRY",
        "CAPDLC_SLUG",
        "CapDLCLifecycleEntry",
        "CapDLCLifecycleState",
        "GateResult",
        "GateStatus",
        "measured_capdlc_entries",
        "resolve_capdlc_lifecycle",
    }

    assert set(capdlc_lifecycle.__all__) == expected_exports
    for name in expected_exports:
        assert getattr(capdlc_lifecycle, name) is capdlc_lifecycle.__dict__[name]
