"""Mobile substream Cairo routing contracts.

The three ``mobile.json``-bound tests
(``test_mobile_json_matches_portrait_schema``,
``test_select_mobile_sources_clamps_to_candidates_and_fails_closed``,
and ``test_mobile_cairo_runner_writes_exact_rgba_size``) were removed
when PR #2770 purged ``config/compositor-layouts/mobile.json`` ("broken
schema" — operator directive). The runner test depended transitively
because ``MobileCairoRunner.__init__`` calls
``load_mobile_layout(DEFAULT_MOBILE_LAYOUT_PATH)``, which now
``FileNotFoundError``s.

The static-spec pin below remains: it exercises the
``MOBILE_SOURCE_SPECS`` tuple and the cairo class registry, neither of
which depends on the purged JSON. If a fresh mobile layout is
reintroduced, restore the runner / load-layout pins alongside it.
"""

from __future__ import annotations

from agents.studio_compositor.cairo_sources import get_cairo_source_class
from agents.studio_compositor.mobile_cairo_sources import MOBILE_SOURCE_SPECS
from agents.studio_compositor.mobile_layout import MIN_MOBILE_FONT_SIZE_PT


def test_mobile_cairo_sources_are_registered_and_readable() -> None:
    for spec in MOBILE_SOURCE_SPECS:
        assert spec.font_size_pt >= MIN_MOBILE_FONT_SIZE_PT
        assert spec.source_id.startswith(("activity", "stance", "impingement", "token", "captions"))
        cls = get_cairo_source_class(spec.class_name)
        assert cls.__name__ == spec.class_name
