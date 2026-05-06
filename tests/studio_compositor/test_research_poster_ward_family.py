"""Regression pins for the research-poster Cairo ward family."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import cairo

from agents.studio_compositor.ascii_schematic_ward import (
    FEATURE_FLAG_ENV as ASCII_FLAG_ENV,
)
from agents.studio_compositor.ascii_schematic_ward import (
    SOURCE_ID as ASCII_SOURCE_ID,
)
from agents.studio_compositor.ascii_schematic_ward import (
    ASCIISchematicWard,
    ascii_schematic_lines,
)
from agents.studio_compositor.cairo_source import CairoSource
from agents.studio_compositor.cairo_sources import get_cairo_source_class
from agents.studio_compositor.constructivist_research_poster_ward import (
    FEATURE_FLAG_ENV as CONSTRUCTIVIST_FLAG_ENV,
)
from agents.studio_compositor.constructivist_research_poster_ward import (
    SOURCE_ID as CONSTRUCTIVIST_SOURCE_ID,
)
from agents.studio_compositor.constructivist_research_poster_ward import (
    ConstructivistResearchPosterWard,
)
from agents.studio_compositor.research_instrument_dashboard_ward import ClaimRow
from agents.studio_compositor.research_poster_data import (
    ResearchPosterState,
    research_poster_feature_enabled,
)
from agents.studio_compositor.tufte_density_ward import (
    FEATURE_FLAG_ENV as TUFTE_FLAG_ENV,
)
from agents.studio_compositor.tufte_density_ward import (
    SOURCE_ID as TUFTE_SOURCE_ID,
)
from agents.studio_compositor.tufte_density_ward import TufteDensityWard
from shared.compositor_model import Layout

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest

REPO_ROOT = Path(__file__).parents[2]
DEFAULT_JSON = REPO_ROOT / "config" / "compositor-layouts" / "default.json"
EXAMPLE_JSON = (
    REPO_ROOT / "config" / "compositor-layouts" / "examples" / ("research-poster-family.json")
)

FEATURE_FLAGS = (
    CONSTRUCTIVIST_FLAG_ENV,
    TUFTE_FLAG_ENV,
    ASCII_FLAG_ENV,
)
CLASS_BY_ID = {
    CONSTRUCTIVIST_SOURCE_ID: ConstructivistResearchPosterWard,
    TUFTE_SOURCE_ID: TufteDensityWard,
    ASCII_SOURCE_ID: ASCIISchematicWard,
}
SURFACE_BY_ID = {
    CONSTRUCTIVIST_SOURCE_ID: "research-poster-constructivist",
    TUFTE_SOURCE_ID: "research-poster-tufte",
    ASCII_SOURCE_ID: "research-poster-ascii",
}


def _snapshot() -> ResearchPosterState:
    return ResearchPosterState(
        condition_id="poster-condition-alpha",
        epoch=7,
        claim_rows=(
            ClaimRow("poster-condition-alpha", "claim-a", "passing"),
            ClaimRow("poster-condition-alpha", "claim-b", "passing"),
            ClaimRow("poster-condition-alpha", "claim-c", "failing"),
            ClaimRow("poster-condition-alpha", "claim-d", "unverified"),
        ),
    )


def _render_bytes(
    ward_factory: Callable[[Callable[[], ResearchPosterState]], CairoSource],
    reader: Callable[[], ResearchPosterState],
) -> bytes:
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 520, 180)
    cr = cairo.Context(surface)
    ward = ward_factory(reader)
    ward.render(cr, 520, 180, 0.0, {})
    surface.flush()
    return bytes(surface.get_data())


def test_research_poster_feature_flags_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    for env_name in FEATURE_FLAGS:
        monkeypatch.delenv(env_name, raising=False)
        assert not research_poster_feature_enabled(env_name)
        monkeypatch.setenv(env_name, "0")
        assert not research_poster_feature_enabled(env_name)
        monkeypatch.setenv(env_name, "true")
        assert research_poster_feature_enabled(env_name)


def test_research_poster_classes_registered() -> None:
    for source_id, expected_cls in CLASS_BY_ID.items():
        cls = get_cairo_source_class(expected_cls.__name__)
        assert cls is expected_cls, source_id
        assert issubclass(cls, CairoSource)


def test_research_poster_source_ids_are_stable() -> None:
    assert ConstructivistResearchPosterWard.source_id == CONSTRUCTIVIST_SOURCE_ID
    assert TufteDensityWard.source_id == TUFTE_SOURCE_ID
    assert ASCIISchematicWard.source_id == ASCII_SOURCE_ID


def test_disabled_wards_do_not_render_or_read_state(monkeypatch: pytest.MonkeyPatch) -> None:
    def unreadable_state() -> ResearchPosterState:
        raise AssertionError("disabled ward should not read state")

    for env_name, ward_cls in (
        (CONSTRUCTIVIST_FLAG_ENV, ConstructivistResearchPosterWard),
        (TUFTE_FLAG_ENV, TufteDensityWard),
        (ASCII_FLAG_ENV, ASCIISchematicWard),
    ):
        monkeypatch.delenv(env_name, raising=False)
        assert set(_render_bytes(ward_cls, unreadable_state)) == {0}


def test_enabled_wards_draw_nonempty_surfaces(monkeypatch: pytest.MonkeyPatch) -> None:
    for env_name, ward_cls in (
        (CONSTRUCTIVIST_FLAG_ENV, ConstructivistResearchPosterWard),
        (TUFTE_FLAG_ENV, TufteDensityWard),
        (ASCII_FLAG_ENV, ASCIISchematicWard),
    ):
        monkeypatch.setenv(env_name, "1")
        assert any(_render_bytes(ward_cls, _snapshot))


def test_ascii_schematic_rows_are_ascii_and_fixed_width() -> None:
    rows = ascii_schematic_lines(_snapshot())
    assert rows
    widths = {len(row) for row in rows}
    assert widths == {46}
    for row in rows:
        row.encode("ascii")


def test_research_poster_example_layout_is_declarable() -> None:
    layout = Layout.model_validate(json.loads(EXAMPLE_JSON.read_text()))

    assert layout.name == "research-poster-family"
    assert {s.id for s in layout.sources} == set(CLASS_BY_ID)
    assert {s.id for s in layout.surfaces} == set(SURFACE_BY_ID.values())

    by_source = {source.id: source for source in layout.sources}
    for source_id, cls in CLASS_BY_ID.items():
        source = by_source[source_id]
        assert source.backend == "cairo"
        assert source.params["class_name"] == cls.__name__
        assert source.update_cadence == "rate"
        assert source.rate_hz == 0.5
        assert "research-poster" in source.tags
        assert get_cairo_source_class(source.params["class_name"]) is cls

    by_surface = {surface.id: surface for surface in layout.surfaces}
    rects = []
    for surface_id in SURFACE_BY_ID.values():
        surface = by_surface[surface_id]
        geom = surface.geometry
        assert surface.z_order == 22
        assert geom.kind == "rect"
        assert geom.x is not None and geom.y is not None
        assert geom.w == 520 and geom.h == 180
        assert geom.x >= 0 and geom.x + geom.w <= 1920
        assert geom.y >= 0 and geom.y + geom.h <= 1080
        rects.append((surface_id, geom.x, geom.y, geom.w, geom.h))

    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            id_a, ax, ay, aw, ah = rects[i]
            id_b, bx, by, bw, bh = rects[j]
            overlap_x = ax < bx + bw and bx < ax + aw
            overlap_y = ay < by + bh and by < ay + ah
            assert not (overlap_x and overlap_y), f"{id_a} overlaps {id_b}"

    pairs = {(assignment.source, assignment.surface) for assignment in layout.assignments}
    assert pairs == set(SURFACE_BY_ID.items())
    for assignment in layout.assignments:
        assert assignment.render_stage == "pre_fx"
        assert assignment.non_destructive
        assert assignment.opacity == 0.92


def test_research_poster_sources_are_not_auto_active_in_default_layout() -> None:
    layout = Layout.model_validate(json.loads(DEFAULT_JSON.read_text()))
    default_source_ids = {source.id for source in layout.sources}
    assert default_source_ids.isdisjoint(CLASS_BY_ID)
