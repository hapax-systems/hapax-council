"""Verify the Steam Deck source / surface / assignment land in the
default compositor layout + the affordance is registered."""

from __future__ import annotations

from agents.studio_compositor.compositor import _FALLBACK_LAYOUT
from shared.affordance_registry import ALL_AFFORDANCES


def _source_by_id(source_id: str):
    matches = [s for s in _FALLBACK_LAYOUT.sources if s.id == source_id]
    return matches[0] if matches else None


def _surface_by_id(surface_id: str):
    matches = [s for s in _FALLBACK_LAYOUT.surfaces if s.id == surface_id]
    return matches[0] if matches else None


def _assignments_for_source(source_id: str):
    return [a for a in _FALLBACK_LAYOUT.assignments if a.source == source_id]


def test_steamdeck_display_source_registered() -> None:
    source = _source_by_id("steamdeck-display")
    assert source is not None
    assert source.kind == "external_rgba"
    assert source.backend == "shm_rgba"
    assert source.params["natural_w"] == 1920
    assert source.params["natural_h"] == 1080
    assert source.params["shm_path"] == "/dev/shm/hapax-sources/steamdeck-display.rgba"


def test_steamdeck_pip_surface_present() -> None:
    surface = _surface_by_id("steamdeck-display-pip")
    assert surface is not None
    assert surface.geometry.kind == "rect"
    # Upper-right large quadrant per cc-task spec.
    assert surface.geometry.x == 960
    assert surface.geometry.y == 60
    assert surface.geometry.w == 920
    assert surface.geometry.h == 580


def test_steamdeck_fullscreen_surface_present() -> None:
    surface = _surface_by_id("steamdeck-display-fullscreen")
    assert surface is not None
    assert surface.geometry.x == 0
    assert surface.geometry.y == 0
    assert surface.geometry.w == 1920
    assert surface.geometry.h == 1080


def test_assignments_default_opacity() -> None:
    """PiP starts visible (opacity 1.0); fullscreen stays hidden (0.0)
    until the affordance pipeline recruits it."""
    assignments = _assignments_for_source("steamdeck-display")
    assert len(assignments) == 2
    by_surface = {a.surface: a for a in assignments}
    assert by_surface["steamdeck-display-pip"].opacity == 1.0
    assert by_surface["steamdeck-display-fullscreen"].opacity == 0.0


def test_steamdeck_reveal_affordance_registered() -> None:
    names = {r.name for r in ALL_AFFORDANCES}
    assert "ward.reveal.steamdeck-display" in names


def test_steamdeck_reveal_affordance_carries_visual_medium() -> None:
    record = next(r for r in ALL_AFFORDANCES if r.name == "ward.reveal.steamdeck-display")
    assert record.daemon == "compositor"
    assert record.operational.medium == "visual"
    assert record.operational.consent_required is False


def test_steamdeck_reveal_affordance_description_long_enough() -> None:
    record = next(r for r in ALL_AFFORDANCES if r.name == "ward.reveal.steamdeck-display")
    # Embedding-quality cosine match needs a meaningful Gibson-verb
    # description — same threshold as chat affordances.
    assert len(record.description.split()) >= 12
