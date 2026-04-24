"""Tests for WardEnhancementProfile (HOMAGE Ward Umbrella Phase 1)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.ward_enhancement_profile import WardEnhancementProfile


def test_ward_enhancement_profile_required_fields():
    """WardEnhancementProfile rejects instantiation with no fields and
    surfaces the three required fields in the error message."""
    with pytest.raises(ValidationError) as exc_info:
        WardEnhancementProfile()  # type: ignore[call-arg]

    message = str(exc_info.value)
    assert "ward_id" in message
    assert "recognizability_invariant" in message
    assert "use_case_acceptance_test" in message


def test_ward_enhancement_profile_album_round_trip():
    """An album-ward profile instantiates with representative fields and
    survives a model_dump → reconstruct round-trip intact."""
    profile = WardEnhancementProfile(
        ward_id="album",
        recognizability_invariant=(
            "Album title >=80% OCR; dominant contours edge-IoU >=0.65; "
            "palette delta-E <=40; no humanoid bulges"
        ),
        recognizability_tests=["ocr_accuracy", "edge_iou", "palette_delta_e"],
        use_case_acceptance_test=("Operator/audience identify album at glance; title extractable"),
        acceptance_test_harness="tests/studio_compositor/test_album_acceptance.py",
        accepted_enhancement_categories=["posterize", "kuwahara", "halftone"],
        rejected_enhancement_categories=["lens_distortion", "perspective"],
        spatial_dynamism_approved=True,
        oq_02_bound_applicable=True,
        hardm_binding=False,
        cvs_bindings=["CVS #8", "CVS #16"],
    )

    assert profile.ward_id == "album"
    assert "edge_iou" in profile.recognizability_tests

    data = profile.model_dump()
    profile2 = WardEnhancementProfile(**data)
    assert profile2 == profile


EXPECTED_WARDS = frozenset(
    {
        "token_pole",
        "album",
        "stream_overlay",
        "sierpinski",
        "activity_header",
        "stance_indicator",
        "impingement_cascade",
        "recruitment_candidate_panel",
        "thinking_indicator",
        "pressure_gauge",
        "activity_variety_log",
        "whos_here",
        "reverie",
        # Ratified 2026-04-21 (operator decision): GEM (#15, replaces
        # captions in lower-band geometry), chat_keywords (#16, aggregate
        # keyword texture), and four already-shipped wards getting their
        # first profile (captions [deprecating], chat_ambient,
        # grounding_provenance_ticker, research_marker_overlay). See
        # docs/superpowers/specs/2026-04-20-homage-ward-umbrella-design.md
        # §0 ward count reconciliation.
        "gem",
        "chat_keywords",
        "captions",
        "chat_ambient",
        "grounding_provenance_ticker",
        "research_marker_overlay",
    }
)


def test_ward_enhancement_profile_registry_all_wards():
    """Registry loads every expected ward from the YAML config."""
    from shared.ward_enhancement_profile import WardEnhancementProfileRegistry

    registry = WardEnhancementProfileRegistry.load_from_yaml(
        "config/ward_enhancement_profiles.yaml"
    )

    assert set(registry.profiles.keys()) == EXPECTED_WARDS
    for ward_id in EXPECTED_WARDS:
        profile = registry.profiles[ward_id]
        assert profile.recognizability_invariant
        assert profile.use_case_acceptance_test


def test_ward_enhancement_profile_registry_lookup():
    """Registry provides .get() lookup by ward_id and .list_wards() enumeration."""
    from shared.ward_enhancement_profile import WardEnhancementProfileRegistry

    registry = WardEnhancementProfileRegistry.load_from_yaml(
        "config/ward_enhancement_profiles.yaml"
    )

    album = registry.get("album")
    assert album is not None
    assert album.ward_id == "album"
    assert "ocr_accuracy" in album.recognizability_tests

    assert registry.get("nonexistent_ward") is None
    assert set(registry.list_wards()) == EXPECTED_WARDS


def test_ward_enhancement_profile_registry_missing_file():
    """Missing YAML raises FileNotFoundError with a clear message."""
    from shared.ward_enhancement_profile import WardEnhancementProfileRegistry

    with pytest.raises(FileNotFoundError, match="not found"):
        WardEnhancementProfileRegistry.load_from_yaml("config/does_not_exist.yaml")
