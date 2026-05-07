"""Projected hero contract tests."""

from __future__ import annotations

from agents.studio_compositor.models import TileRect
from agents.studio_compositor.projected_hero import (
    PROJECTED_HERO_ALPHA,
    PROJECTED_HERO_MIN_DWELL_S,
    ProjectedHeroProfile,
    build_projected_hero_profile,
    validate_projected_hero_profile,
)


def test_build_projected_hero_profile_is_virtual_and_non_authoritative() -> None:
    profile = build_projected_hero_profile("brio-operator", TileRect(x=1200, y=700, w=320, h=180))

    assert validate_projected_hero_profile(profile) == []
    assert profile.alpha == PROJECTED_HERO_ALPHA
    assert profile.min_dwell_s == PROJECTED_HERO_MIN_DWELL_S
    assert profile.grants_layout_success is False
    assert profile.grants_face_obscuring is False
    assert profile.authority == "derived_virtual_overlay_only"


def test_projected_hero_profile_rejects_blink_or_authority_regressions() -> None:
    profile = ProjectedHeroProfile(
        role="brio-operator",
        rect=TileRect(x=0, y=0, w=320, h=180),
        alpha=0.95,
        min_dwell_s=0.1,
        authority="layout_success",
        grants_layout_success=True,
        grants_face_obscuring=True,
    )

    violations = validate_projected_hero_profile(profile)

    assert "alpha_must_be_constant_and_subdominant" in violations
    assert "min_dwell_below_no_blink_floor" in violations
    assert "projected_hero_cannot_grant_layout_authority" in violations
    assert "projected_hero_cannot_grant_layout_success" in violations
    assert "projected_hero_cannot_grant_face_obscuring" in violations
