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
