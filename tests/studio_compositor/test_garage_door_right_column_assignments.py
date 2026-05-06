"""Regression pin for garage-door right-column legibility assignments.

The garage-door layout (`config/layouts/garage-door.json`) is the boot/
fallback compositor layout. Three legibility Cairo sources
(``activity_header``, ``stance_indicator``, ``grounding_provenance_ticker``)
were declared in the ``sources`` array but never wired to surfaces, so
they rendered as dead pixels — no on-frame authorship indicator, no
stance flag, no provenance ticker on the boot layout.

This test pins the three assignments that surface them. It also pins
the surface geometry — accidentally relocating these panels into the
top-row hothouse band or under the reverie quadrant would re-occlude
other indicators, so the pin includes the chosen rect.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.compositor_model import Layout

LAYOUT_PATH = Path(__file__).resolve().parents[2] / "config" / "layouts" / "garage-door.json"


@pytest.fixture(scope="module")
def garage_door_layout() -> Layout:
    return Layout(**json.loads(LAYOUT_PATH.read_text(encoding="utf-8")))


# ── Surface presence ───────────────────────────────────────────────────


class TestRightColumnSurfacesPresent:
    """The three legibility surfaces are wired into garage-door."""

    @pytest.mark.parametrize(
        "surface_id,expected_geom",
        [
            ("activity-header-top", {"x": 340, "y": 84, "w": 800, "h": 56}),
            ("stance-indicator-right", {"x": 1800, "y": 400, "w": 100, "h": 40}),
            ("grounding-ticker-right", {"x": 1380, "y": 460, "w": 480, "h": 40}),
        ],
    )
    def test_surface_geometry_pinned(
        self, garage_door_layout: Layout, surface_id: str, expected_geom: dict[str, int]
    ) -> None:
        match = next((s for s in garage_door_layout.surfaces if s.id == surface_id), None)
        assert match is not None, f"surface {surface_id!r} missing from garage-door"
        geom = match.geometry
        assert geom.kind == "rect", f"{surface_id} must be a rect surface"
        for key, value in expected_geom.items():
            actual = getattr(geom, key)
            assert actual == value, (
                f"{surface_id}.{key} = {actual} (expected {value}); "
                "right-column legibility geometry was changed — update spec or revert"
            )


# ── Assignment presence ────────────────────────────────────────────────


class TestRightColumnAssignmentsWired:
    """Each of the three sources is bound to its surface at full opacity."""

    @pytest.mark.parametrize(
        "source_id,surface_id",
        [
            ("activity_header", "activity-header-top"),
            ("stance_indicator", "stance-indicator-right"),
            ("grounding_provenance_ticker", "grounding-ticker-right"),
        ],
    )
    def test_assignment_present_at_full_opacity(
        self, garage_door_layout: Layout, source_id: str, surface_id: str
    ) -> None:
        match = next(
            (
                a
                for a in garage_door_layout.assignments
                if a.source == source_id and a.surface == surface_id
            ),
            None,
        )
        assert match is not None, (
            f"assignment {source_id} -> {surface_id} missing — "
            "legibility source was disconnected from the right column"
        )
        assert match.opacity == 1.0, f"{source_id} expected full opacity; got {match.opacity}"


# ── Orphan-source allowlist ────────────────────────────────────────────


class TestNoUnexpectedOrphanSources:
    """Every declared source has either an assignment or is on the allowlist.

    `chat_keyword_legend` is an intentional Phase-10 backcompat alias kept
    in `legibility_sources.py` for legacy layouts only — default.json
    binds the modern `ChatAmbientWard` instead, so leaving it unwired
    here is correct.

    `halftone-shader` is a wgsl FX-chain shader, not a surface-bound
    Cairo source; it is recruited via the FX chain rather than via a
    layout assignment.
    """

    KNOWN_FX_OR_BACKCOMPAT_ORPHANS = frozenset({"chat_keyword_legend", "halftone-shader"})

    def test_no_unexpected_orphan_declared_sources(self, garage_door_layout: Layout) -> None:
        src_ids = {s.id for s in garage_door_layout.sources}
        assigned = {a.source for a in garage_door_layout.assignments}
        orphans = src_ids - assigned - self.KNOWN_FX_OR_BACKCOMPAT_ORPHANS
        assert not orphans, (
            f"garage-door declares sources without assigning them to surfaces: "
            f"{sorted(orphans)} — either wire each source to a surface or add "
            "a justification to KNOWN_FX_OR_BACKCOMPAT_ORPHANS in this test"
        )
