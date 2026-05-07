"""Programme banner ward placement in compositor layouts.

cc-task: programme-banner-ward-layout-placement (follow-on to PR #2409
which only registered the ward in the cairo_sources registry without
placing it in any layout).

Per ``feedback_show_dont_tell_director``: the banner must SHOW programme
state, which requires it to actually render. These tests pin the banner
into every still-live LayoutSwitcher KNOWN_LAYOUTS entry at the
top-strip placement chosen for u6-periodic-tick-driver visibility.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.compositor_model import Layout

REPO_ROOT = Path(__file__).resolve().parents[2]

# LayoutSwitcher (u6) layouts that must carry the banner so it renders
# regardless of the active layout. Distinct from garage-door which is
# the boot/fallback.
#
# ``default-legacy.json`` and ``examples/vinyl-focus.json`` were purged
# in the layout cleanup (PR #2770); their entries are dropped here to
# keep the pin honest. If either layout is reintroduced, re-add it to
# the parametrize set so the banner pin re-extends.
KNOWN_LAYOUT_PATHS = (
    REPO_ROOT / "config/compositor-layouts/default.json",
    REPO_ROOT / "config/compositor-layouts/consent-safe.json",
)


@pytest.mark.parametrize("layout_path", KNOWN_LAYOUT_PATHS, ids=lambda p: p.name)
class TestProgrammeBannerInLayout:
    def _load(self, layout_path: Path) -> Layout:
        return Layout.model_validate_json(layout_path.read_text())

    def test_layout_validates(self, layout_path: Path) -> None:
        """The patched layout still passes Pydantic validation."""
        self._load(layout_path)

    def test_has_programme_banner_source(self, layout_path: Path) -> None:
        layout = self._load(layout_path)
        names = {src.id for src in layout.sources}
        assert "programme_banner" in names, (
            f"layout {layout_path.name} missing programme_banner source; "
            "u6-periodic-tick-driver requires the banner across ALL 4 known layouts"
        )

    def test_has_programme_banner_surface(self, layout_path: Path) -> None:
        layout = self._load(layout_path)
        names = {sfc.id for sfc in layout.surfaces}
        assert "programme-banner-top" in names, (
            f"layout {layout_path.name} missing programme-banner-top surface"
        )

    def test_has_programme_banner_assignment(self, layout_path: Path) -> None:
        layout = self._load(layout_path)
        wired = [a for a in layout.assignments if a.source == "programme_banner"]
        assert len(wired) == 1, (
            f"layout {layout_path.name} missing exactly one assignment "
            f"binding programme_banner → programme-banner-top"
        )
        assert wired[0].surface == "programme-banner-top"

    def test_banner_uses_top_strip_anchor(self, layout_path: Path) -> None:
        """Top-strip placement avoids album/sierpinski collision and
        feedback_show_dont_tell_director (banner must SHOW state legibly)."""
        layout = self._load(layout_path)
        surface = next(
            (sfc for sfc in layout.surfaces if sfc.id == "programme-banner-top"),
            None,
        )
        assert surface is not None
        geom = surface.geometry
        # 1920x1080 canvas; top half = y < 540. Banner sits high enough
        # that bottom-zone wards (album, sierpinski, gem) do not overlap.
        assert geom.kind == "rect"
        assert geom.y is not None
        assert geom.y < 220, f"banner y={geom.y} drops into the camera zone; must stay in top strip"
        # Width covers the central legibility band — narrow enough to
        # not collide with token_pole upper-left or pip-ur upper-right.
        assert geom.w is not None
        assert 600 <= geom.w <= 1000, f"banner width {geom.w} outside top-strip range"

    def test_banner_z_order_above_camera_below_overlays(self, layout_path: Path) -> None:
        """Banner must render above camera tiles (z<=20 typical) but
        below modal overlays like recruitment-candidate-top (z>=24)."""
        layout = self._load(layout_path)
        surface = next(
            (sfc for sfc in layout.surfaces if sfc.id == "programme-banner-top"),
            None,
        )
        assert surface is not None
        assert surface.z_order is not None
        assert 20 <= surface.z_order <= 40


def test_garage_door_layout_unchanged() -> None:
    """garage-door is the boot/fallback layout used by LayoutStore default;
    banner placement is NOT required there because the u6 driver cycles
    OUT of garage-door once switching is wired. Pinning this absence
    catches accidental drift."""
    layout = Layout.model_validate_json((REPO_ROOT / "config/layouts/garage-door.json").read_text())
    names = {src.id for src in layout.sources}
    # Affirmative absence — garage-door is a different concept (full-camera
    # layout for live-stream debug); banner placement is intentionally
    # scoped to the 4 KNOWN_LAYOUTS the switcher routes between.
    assert "programme_banner" not in names
