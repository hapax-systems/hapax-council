"""Completeness and no-hidden-default tests for the Constitutional BOM."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

import shared.constitutional_bom as bom


def test_committed_bom_is_complete() -> None:
    artifact = json.loads(bom.ARTIFACT_PATH.read_text(encoding="utf-8"))
    bom.validate_completeness(artifact)
    assert artifact["unknown_count"] == 1


def test_mutation_verification_red_then_green() -> None:
    artifact = json.loads(bom.ARTIFACT_PATH.read_text(encoding="utf-8"))
    added = replace(bom.COMMITMENTS[0], id="mutation-only-commitment")
    original = list(bom.COMMITMENTS)
    bom.COMMITMENTS.append(added)
    try:
        with pytest.raises(AssertionError, match="mutation-only-commitment"):
            bom.validate_completeness(artifact)
    finally:
        bom.COMMITMENTS[:] = original
    bom.validate_completeness(artifact)


def test_unknowns_are_counted_and_not_silenced() -> None:
    artifact = bom.generate_bom(generated_on="2026-08-22")
    unknowns = [row for row in artifact["commitments"] if row["disposition"] == "unknown"]
    assert artifact["unknown_count"] == len(unknowns) == 1
    assert artifact["unknown_disposition"]


def test_reference_profile_never_loads_by_default() -> None:
    assert bom.load_values_profile() is None
    profile = bom.load_values_profile("hapax-estate-reference")
    assert profile is not None
    assert profile["is_default"] is False
    assert "Explicit reference profile" in profile["label"]
