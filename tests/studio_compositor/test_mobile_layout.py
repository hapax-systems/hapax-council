"""Mobile substream Cairo routing contracts."""

from __future__ import annotations

from agents.studio_compositor.cairo_sources import get_cairo_source_class
from agents.studio_compositor.mobile_cairo_sources import (
    MOBILE_HEIGHT,
    MOBILE_SOURCE_SPECS,
    MOBILE_WIDTH,
    MobileCairoRunner,
)
from agents.studio_compositor.mobile_layout import (
    DEFAULT_MOBILE_LAYOUT_PATH,
    MIN_MOBILE_FONT_SIZE_PT,
    load_mobile_layout,
)


def test_mobile_json_matches_portrait_schema() -> None:
    layout = load_mobile_layout(DEFAULT_MOBILE_LAYOUT_PATH)

    assert layout.target_width == 1080
    assert layout.target_height == 1920
    assert layout.metadata_footer.claim_posture == "neutral_hold"
    assert layout.ward_zone.max_wards == 3


def test_mobile_cairo_sources_are_registered_and_readable() -> None:
    for spec in MOBILE_SOURCE_SPECS:
        assert spec.font_size_pt >= MIN_MOBILE_FONT_SIZE_PT
        assert spec.source_id.startswith(("activity", "stance", "impingement", "token", "captions"))
        cls = get_cairo_source_class(spec.class_name)
        assert cls.__name__ == spec.class_name


def test_mobile_runner_reuses_portrait_surface(tmp_path) -> None:
    runner = MobileCairoRunner(output_path=tmp_path / "mobile-overlay.rgba")

    first = runner._render_surface()
    second = runner._render_surface()

    assert first is second
    runner._write_surface_atomic(first)
    assert runner.output_path.stat().st_size == MOBILE_WIDTH * MOBILE_HEIGHT * 4
