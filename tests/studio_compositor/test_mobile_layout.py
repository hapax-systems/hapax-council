"""Mobile substream layout and Cairo routing contracts."""

from __future__ import annotations

import json
import time
from pathlib import Path

from agents.studio_compositor.cairo_sources import get_cairo_source_class
from agents.studio_compositor.mobile_cairo_sources import (
    MOBILE_HEIGHT,
    MOBILE_OVERLAY_PATH,
    MOBILE_SOURCE_SPECS,
    MOBILE_WIDTH,
    MobileCairoRunner,
)
from agents.studio_compositor.mobile_layout import (
    DEFAULT_MOBILE_LAYOUT_PATH,
    MIN_MOBILE_FONT_SIZE_PT,
    load_mobile_layout,
    select_mobile_sources,
)


def test_mobile_json_matches_portrait_schema() -> None:
    layout = load_mobile_layout(DEFAULT_MOBILE_LAYOUT_PATH)

    assert layout.version == 1
    assert layout.target_width == 1080
    assert layout.target_height == 1920
    assert layout.hero_cam.source_crop.width == 608
    assert layout.hero_cam.dest.height == 1152
    assert layout.ward_zone.max_wards == 3
    assert layout.ward_zone.fallback_density == "minimum_density"
    assert layout.metadata_footer.font_size_pt >= 18
    assert layout.metadata_footer.claim_posture == "neutral_hold"
    assert layout.ward_candidates == (
        "activity_header",
        "stance_indicator",
        "impingement_cascade",
        "token_pole",
        "captions",
    )


def test_select_mobile_sources_clamps_to_candidates_and_fails_closed() -> None:
    layout = load_mobile_layout(DEFAULT_MOBILE_LAYOUT_PATH)
    fresh = {
        "selected_wards": [
            "captions",
            "unknown",
            "activity_header",
            "token_pole",
            "stance_indicator",
        ],
        "ts": 1000.0,
    }

    selection = select_mobile_sources(layout, fresh, now=1001.0)

    assert selection.selected_wards == ("captions", "activity_header", "token_pole")
    assert selection.density_mode == "normal_density"
    assert selection.claim_posture == "neutral_hold"
    assert not selection.stale

    stale = select_mobile_sources(layout, {"selected_wards": ["captions"], "ts": 900.0}, now=1000.0)
    assert stale.selected_wards == ()
    assert stale.density_mode == "minimum_density"
    assert stale.claim_posture == "neutral_hold"
    assert stale.stale

    missing = select_mobile_sources(layout, None, now=1000.0)
    assert missing.selected_wards == ()
    assert missing.density_mode == "minimum_density"
    assert missing.claim_posture == "neutral_hold"
    assert missing.stale


def test_mobile_cairo_sources_are_registered_and_readable() -> None:
    for spec in MOBILE_SOURCE_SPECS:
        assert spec.font_size_pt >= MIN_MOBILE_FONT_SIZE_PT
        assert spec.source_id.startswith(("activity", "stance", "impingement", "token", "captions"))
        cls = get_cairo_source_class(spec.class_name)
        assert cls.__name__ == spec.class_name


def test_mobile_cairo_runner_writes_exact_rgba_size(tmp_path: Path) -> None:
    salience = tmp_path / "mobile-salience.json"
    output = tmp_path / MOBILE_OVERLAY_PATH.name
    salience.write_text(
        json.dumps(
            {
                "selected_wards": ["activity_header", "stance_indicator", "captions"],
                "viewer_count": 2,
                "scores": {"activity_header": 1.0, "stance_indicator": 0.5, "captions": 0.4},
                "ts": time.time(),
            }
        )
    )

    runner = MobileCairoRunner(salience_path=salience, output_path=output)
    written = runner.render_once()

    assert written == output
    assert output.stat().st_size == MOBILE_WIDTH * MOBILE_HEIGHT * 4
