"""Acceptance scaffolds for the 6 ward profiles ratified 2026-04-21.

Each profile pinned in ``config/ward_enhancement_profiles.yaml`` references
an ``acceptance_test_harness`` path. Until each ward grows its own deep
golden-image / property-based suite (delta-owned B7 work), this scaffold:

* Verifies the YAML profile loads under the Pydantic schema.
* Pins the load-bearing invariants (HARDM binding, OQ-02 applicable,
  CVS bindings, deprecation marker).
* Asserts the accepted/rejected category lists are non-overlapping.
* Asserts at least one acceptance test name is declared per profile so
  downstream tooling can wire CI gates.

Spec: ``docs/superpowers/specs/2026-04-20-homage-ward-umbrella-design.md`` §4.1bis.
"""

from __future__ import annotations

import pytest

from shared.ward_enhancement_profile import (
    WardEnhancementProfile,
    WardEnhancementProfileRegistry,
)

PROFILE_YAML = "config/ward_enhancement_profiles.yaml"

NEW_WARDS_2026_04_21 = (
    "gem",
    "chat_keywords",
    "captions",
    "chat_ambient",
    "grounding_provenance_ticker",
    "research_marker_overlay",
)


@pytest.fixture(scope="module")
def registry() -> WardEnhancementProfileRegistry:
    return WardEnhancementProfileRegistry.load_from_yaml(PROFILE_YAML)


@pytest.mark.parametrize("ward_id", NEW_WARDS_2026_04_21)
def test_profile_loads(registry: WardEnhancementProfileRegistry, ward_id: str) -> None:
    """Every ratified ward must have a Pydantic-valid YAML entry."""
    profile = registry.get(ward_id)
    assert profile is not None, f"missing YAML profile for {ward_id}"
    assert isinstance(profile, WardEnhancementProfile)
    assert profile.ward_id == ward_id


@pytest.mark.parametrize("ward_id", NEW_WARDS_2026_04_21)
def test_recognizability_invariant_non_empty(
    registry: WardEnhancementProfileRegistry, ward_id: str
) -> None:
    profile = registry.get(ward_id)
    assert profile is not None
    assert profile.recognizability_invariant.strip(), (
        f"{ward_id}: recognizability_invariant must be non-empty prose"
    )


@pytest.mark.parametrize("ward_id", NEW_WARDS_2026_04_21)
def test_use_case_acceptance_test_non_empty(
    registry: WardEnhancementProfileRegistry, ward_id: str
) -> None:
    profile = registry.get(ward_id)
    assert profile is not None
    assert profile.use_case_acceptance_test.strip(), (
        f"{ward_id}: use_case_acceptance_test must be non-empty"
    )


@pytest.mark.parametrize("ward_id", NEW_WARDS_2026_04_21)
def test_acceptance_harness_path_declared(
    registry: WardEnhancementProfileRegistry, ward_id: str
) -> None:
    profile = registry.get(ward_id)
    assert profile is not None
    assert profile.acceptance_test_harness, (
        f"{ward_id}: acceptance_test_harness path must be declared "
        "(per-ward suite scaffolds out from this path)"
    )
    assert profile.acceptance_test_harness.startswith("tests/")


@pytest.mark.parametrize("ward_id", NEW_WARDS_2026_04_21)
def test_recognizability_tests_declared(
    registry: WardEnhancementProfileRegistry, ward_id: str
) -> None:
    profile = registry.get(ward_id)
    assert profile is not None
    assert len(profile.recognizability_tests) >= 1, (
        f"{ward_id}: at least one recognizability_test name required"
    )


@pytest.mark.parametrize("ward_id", NEW_WARDS_2026_04_21)
def test_oq_02_bound_applicable_default(
    registry: WardEnhancementProfileRegistry, ward_id: str
) -> None:
    """All ratified wards opt in to the OQ-02 three-bound governance gate."""
    profile = registry.get(ward_id)
    assert profile is not None
    assert profile.oq_02_bound_applicable is True


@pytest.mark.parametrize("ward_id", NEW_WARDS_2026_04_21)
def test_categories_non_overlapping(registry: WardEnhancementProfileRegistry, ward_id: str) -> None:
    """A category cannot be simultaneously accepted and rejected."""
    profile = registry.get(ward_id)
    assert profile is not None
    overlap = set(profile.accepted_enhancement_categories) & set(
        profile.rejected_enhancement_categories
    )
    assert overlap == set(), f"{ward_id}: overlapping categories {overlap}"


# ── Per-ward invariants ──────────────────────────────────────────────────


def test_gem_hardm_bound(registry: WardEnhancementProfileRegistry) -> None:
    """GEM must enforce HARDM (CP437 raster forbids face emergence)."""
    profile = registry.get("gem")
    assert profile is not None
    assert profile.hardm_binding is True
    # Both anti-anthropomorphization + non-manipulation bindings expected.
    assert any("CVS #16" in b for b in profile.cvs_bindings)
    assert any("CVS #8" in b for b in profile.cvs_bindings)


def test_gem_rejects_kuwahara_and_posterize(
    registry: WardEnhancementProfileRegistry,
) -> None:
    """CP437 raster legibility forbids edge-preserving smoothing or palette collapse."""
    profile = registry.get("gem")
    assert profile is not None
    assert "kuwahara" in profile.rejected_enhancement_categories
    assert "posterize" in profile.rejected_enhancement_categories


def test_chat_keywords_consent_axiom_bound(
    registry: WardEnhancementProfileRegistry,
) -> None:
    """Aggregate-only — interpersonal_transparency T0 must be bound."""
    profile = registry.get("chat_keywords")
    assert profile is not None
    assert any("interpersonal_transparency" in b for b in profile.cvs_bindings)


def test_chat_ambient_consent_axiom_bound(
    registry: WardEnhancementProfileRegistry,
) -> None:
    profile = registry.get("chat_ambient")
    assert profile is not None
    assert any("interpersonal_transparency" in b for b in profile.cvs_bindings)


def test_captions_marked_deprecating(registry: WardEnhancementProfileRegistry) -> None:
    """Captions retires when GEM activates — deprecation marker must be set."""
    profile = registry.get("captions")
    assert profile is not None
    assert profile.deprecation is not None
    assert "GEM" in profile.deprecation


def test_grounding_provenance_ticker_disallows_legibility_breakers(
    registry: WardEnhancementProfileRegistry,
) -> None:
    """Citation text must remain readable — palette/edge transforms rejected."""
    profile = registry.get("grounding_provenance_ticker")
    assert profile is not None
    for category in ("kuwahara", "posterize", "halftone", "glitch"):
        assert category in profile.rejected_enhancement_categories


def test_research_marker_overlay_rejects_all_aesthetics(
    registry: WardEnhancementProfileRegistry,
) -> None:
    """Mode indicator must be unambiguous — no enhancement category accepted."""
    profile = registry.get("research_marker_overlay")
    assert profile is not None
    assert profile.accepted_enhancement_categories == []


# ── Cross-cutting: ratified count ────────────────────────────────────────


def test_total_profile_count_matches_spec(
    registry: WardEnhancementProfileRegistry,
) -> None:
    """Spec §0 reconciliation originally pinned 20 ward profiles (19
    enhanceable + reverie). Dropped to 19 after HARDM retirement
    2026-04-23 (GEAL spec §12).
    """
    assert len(registry.list_wards()) == 19


def test_all_six_new_wards_present(registry: WardEnhancementProfileRegistry) -> None:
    """Spec ratification adds these six profiles atop the original 14."""
    for ward_id in NEW_WARDS_2026_04_21:
        assert registry.get(ward_id) is not None
