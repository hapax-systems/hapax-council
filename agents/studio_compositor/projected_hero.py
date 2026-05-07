"""Projected-hero contract for the compositor hero inset.

The projected hero is a bounded monitor projection, not a second camera layout
and not evidence that face-obscuring or layout responsibility succeeded. It
uses constant alpha and a minimum snapshot dwell so it cannot create a blink
cadence while the source JPEG refreshes.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import TileRect

PROJECTED_HERO_VERSION = 1
PROJECTED_HERO_ALPHA = 0.68
PROJECTED_HERO_BACKDROP_ALPHA = 0.42
PROJECTED_HERO_BORDER_ALPHA = 0.72
PROJECTED_HERO_MIN_DWELL_S = 0.5


@dataclass(frozen=True)
class ProjectedHeroProfile:
    """Runtime-safe projection profile for one hero inset."""

    role: str
    rect: TileRect
    alpha: float = PROJECTED_HERO_ALPHA
    backdrop_alpha: float = PROJECTED_HERO_BACKDROP_ALPHA
    border_alpha: float = PROJECTED_HERO_BORDER_ALPHA
    min_dwell_s: float = PROJECTED_HERO_MIN_DWELL_S
    authority: str = "derived_virtual_overlay_only"
    obscuring_posture: str = "projected_monitor_not_raw_layout_success"
    grants_layout_success: bool = False
    grants_face_obscuring: bool = False


def build_projected_hero_profile(role: str, rect: TileRect) -> ProjectedHeroProfile:
    """Build the bounded projection profile for a virtual hero tile."""
    if not role:
        raise ValueError("projected hero requires a camera role")
    if rect.w <= 1 or rect.h <= 1:
        raise ValueError("projected hero requires a visible virtual tile")
    return ProjectedHeroProfile(role=role, rect=rect)


def validate_projected_hero_profile(profile: ProjectedHeroProfile) -> list[str]:
    """Return contract violations for a projected hero profile."""
    violations: list[str] = []
    if profile.alpha <= 0.0 or profile.alpha > 0.75:
        violations.append("alpha_must_be_constant_and_subdominant")
    if profile.backdrop_alpha < 0.0 or profile.backdrop_alpha > profile.alpha:
        violations.append("backdrop_alpha_must_not_exceed_projection_alpha")
    if profile.border_alpha < profile.alpha or profile.border_alpha > 0.85:
        violations.append("border_alpha_must_be_legible_but_bounded")
    if profile.min_dwell_s < PROJECTED_HERO_MIN_DWELL_S:
        violations.append("min_dwell_below_no_blink_floor")
    if profile.authority != "derived_virtual_overlay_only":
        violations.append("projected_hero_cannot_grant_layout_authority")
    if profile.grants_layout_success:
        violations.append("projected_hero_cannot_grant_layout_success")
    if profile.grants_face_obscuring:
        violations.append("projected_hero_cannot_grant_face_obscuring")
    if profile.rect.w <= 1 or profile.rect.h <= 1:
        violations.append("projected_hero_rect_must_be_visible")
    return violations


__all__ = [
    "PROJECTED_HERO_ALPHA",
    "PROJECTED_HERO_BORDER_ALPHA",
    "PROJECTED_HERO_MIN_DWELL_S",
    "PROJECTED_HERO_VERSION",
    "ProjectedHeroProfile",
    "build_projected_hero_profile",
    "validate_projected_hero_profile",
]
