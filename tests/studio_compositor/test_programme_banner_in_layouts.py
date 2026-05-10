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
            "u6-periodic-tick-driver requires the banner across live default/safety layouts"
        )

    def test_has_programme_banner_surface(self, layout_path: Path) -> None:
        layout = self._load(layout_path)
        names = {sfc.id for sfc in layout.surfaces}
        # Garage-door layout uses programme-banner-bottom; consent-safe may
        # still use programme-banner-top.
        has_banner = "programme-banner-bottom" in names or "programme-banner-top" in names
        assert has_banner, f"layout {layout_path.name} missing programme-banner surface"

    def test_has_programme_banner_assignment(self, layout_path: Path) -> None:
        layout = self._load(layout_path)
        wired = [a for a in layout.assignments if a.source == "programme_banner"]
        assert len(wired) == 1, (
            f"layout {layout_path.name} missing exactly one assignment "
            f"binding programme_banner to a programme-banner surface"
        )
        assert wired[0].surface in ("programme-banner-bottom", "programme-banner-top")

    def test_banner_placement_within_canvas(self, layout_path: Path) -> None:
        """Banner must be within the 1920x1080 canvas bounds."""
        layout = self._load(layout_path)
        surface = next(
            (sfc for sfc in layout.surfaces if sfc.id.startswith("programme-banner-")),
            None,
        )
        assert surface is not None
        geom = surface.geometry
        assert geom.kind == "rect"
        assert geom.y is not None and geom.x is not None
        assert geom.w is not None and geom.h is not None
        assert (geom.x or 0) + (geom.w or 0) <= 1920
        assert (geom.y or 0) + (geom.h or 0) <= 1080

    def test_banner_z_order_above_camera_below_overlays(self, layout_path: Path) -> None:
        """Banner must render above base layers but below modal overlays."""
        layout = self._load(layout_path)
        surface = next(
            (sfc for sfc in layout.surfaces if sfc.id.startswith("programme-banner-")),
            None,
        )
        assert surface is not None
        assert surface.z_order is not None
        assert 20 <= surface.z_order <= 55


def test_garage_door_layout_unchanged() -> None:
    """garage-door is the boot/fallback layout used by LayoutStore default;
    banner placement is NOT required there because the u6 driver cycles
    OUT of garage-door once switching is wired. Pinning this absence
    catches accidental drift."""
    layout = Layout.model_validate_json((REPO_ROOT / "config/layouts/garage-door.json").read_text())
    names = {src.id for src in layout.sources}
    # Affirmative absence — garage-door is a different concept (full-camera
    # layout for live-stream debug); banner placement is intentionally
    # scoped to the live default/safety layouts the switcher routes between.
    assert "programme_banner" not in names
