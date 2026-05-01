"""Layout invariants pinned across the compositor-layouts corpus.

Audit-closeout 3.2 deliverable. The existing 5 layout tests cover
loader/state/persistence/render-stage flows; none have explicit
"invariant" naming or assertions like canvas-fit, no-duplicate-assignment,
role-uniqueness, or kind/backend-pairing. This module pins them.

Each test loads every JSON layout under ``config/compositor-layouts/``
and asserts the invariant holds. A new layout that violates any of
these invariants will fail this test on the first commit.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from shared.compositor_model import Layout

LAYOUTS_DIR = Path(__file__).resolve().parents[2] / "config" / "compositor-layouts"
CANVAS_W = 1920
CANVAS_H = 1080


def _load_layouts() -> list[tuple[str, Layout]]:
    """Return every non-empty named layout in the corpus."""

    out: list[tuple[str, Layout]] = []
    for path in sorted(LAYOUTS_DIR.rglob("*.json")):
        if "examples" in path.parts:
            # Examples are illustrative; not part of the production corpus.
            continue
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        if not raw.get("sources") and not raw.get("surfaces") and not raw.get("assignments"):
            # Empty layouts are not yet finalized (e.g. mobile.json today).
            continue
        out.append((path.relative_to(LAYOUTS_DIR.parents[1]).as_posix(), Layout(**raw)))
    return out


PRODUCTION_LAYOUTS = _load_layouts()


@pytest.fixture(params=PRODUCTION_LAYOUTS, ids=lambda pair: pair[0])
def layout_pair(request: pytest.FixtureRequest) -> tuple[str, Layout]:
    return request.param


# ── Canvas fit (rect surfaces) ──────────────────────────────────────────


class TestRectSurfaceFitsWithinCanvas:
    """Every ``rect`` surface fits within the 1920×1080 canvas."""

    def test_rect_x_y_non_negative(self, layout_pair: tuple[str, Layout]) -> None:
        name, layout = layout_pair
        for surface in layout.surfaces:
            geom = surface.geometry
            if geom.kind != "rect":
                continue
            assert geom.x is not None and geom.x >= 0, (
                f"{name}: surface {surface.id} rect x={geom.x} < 0"
            )
            assert geom.y is not None and geom.y >= 0, (
                f"{name}: surface {surface.id} rect y={geom.y} < 0"
            )

    def test_rect_extent_fits_canvas(self, layout_pair: tuple[str, Layout]) -> None:
        name, layout = layout_pair
        for surface in layout.surfaces:
            geom = surface.geometry
            if geom.kind != "rect":
                continue
            assert geom.w is not None and geom.w > 0, (
                f"{name}: surface {surface.id} rect w must be positive (got {geom.w})"
            )
            assert geom.h is not None and geom.h > 0, (
                f"{name}: surface {surface.id} rect h must be positive (got {geom.h})"
            )
            x_extent = (geom.x or 0) + geom.w
            y_extent = (geom.y or 0) + geom.h
            assert x_extent <= CANVAS_W, (
                f"{name}: surface {surface.id} rect extends past canvas width "
                f"({x_extent} > {CANVAS_W})"
            )
            assert y_extent <= CANVAS_H, (
                f"{name}: surface {surface.id} rect extends past canvas height "
                f"({y_extent} > {CANVAS_H})"
            )


# ── Assignment uniqueness ──────────────────────────────────────────────


class TestAssignmentUniqueness:
    """No two Assignments share the same (source, surface) pair within a layout."""

    def test_no_duplicate_source_surface_pair(self, layout_pair: tuple[str, Layout]) -> None:
        name, layout = layout_pair
        seen: set[tuple[str, str]] = set()
        for a in layout.assignments:
            key = (a.source, a.surface)
            assert key not in seen, (
                f"{name}: duplicate assignment {key!r} — "
                "two assignments target the same (source, surface) pair"
            )
            seen.add(key)


# ── Role / class-name uniqueness within a layout ────────────────────────


class TestCairoClassUniqueness:
    """Each cairo source class is a singleton within a layout.

    Convention: a cairo class (e.g. ``AlbumOverlayCairoSource``) renders a
    semantically singular piece of chrome (one album overlay, one token
    pole, one Sierpinski). Two cairo sources of the same class within the
    same layout would either render the same content twice or fight over
    state — both are bugs.
    """

    def test_cairo_class_names_are_unique_within_layout(
        self, layout_pair: tuple[str, Layout]
    ) -> None:
        name, layout = layout_pair
        seen: dict[str, str] = {}
        for source in layout.sources:
            if source.kind != "cairo":
                continue
            class_name = source.params.get("class_name") if source.params else None
            if class_name is None:
                continue
            existing = seen.get(class_name)
            assert existing is None, (
                f"{name}: cairo class {class_name!r} appears in both "
                f"source {existing!r} and source {source.id!r} — "
                "cairo classes must be singletons within a layout"
            )
            seen[class_name] = source.id


# ── Source kind ↔ backend pairing ───────────────────────────────────────


class TestSourceKindBackendPairing:
    """Each ``SourceKind`` pairs with a stable backend dispatch key.

    The compositor's source registry routes by backend string; if a kind
    drifts to a backend that isn't registered for it, the source silently
    fails to render. Pin the established pairings.
    """

    _EXPECTED_BACKEND_BY_KIND: dict[str, str] = {
        "cairo": "cairo",
        "external_rgba": "shm_rgba",
    }

    def test_known_kinds_use_their_canonical_backend(self, layout_pair: tuple[str, Layout]) -> None:
        name, layout = layout_pair
        for source in layout.sources:
            expected = self._EXPECTED_BACKEND_BY_KIND.get(source.kind)
            if expected is None:
                continue
            assert source.backend == expected, (
                f"{name}: source {source.id!r} has kind {source.kind!r} "
                f"with backend {source.backend!r}; expected {expected!r}"
            )

    def test_cairo_sources_carry_class_name_param(self, layout_pair: tuple[str, Layout]) -> None:
        """Every cairo source must declare which Cairo class to instantiate."""

        name, layout = layout_pair
        for source in layout.sources:
            if source.kind != "cairo":
                continue
            class_name = source.params.get("class_name") if source.params else None
            assert class_name, (
                f"{name}: cairo source {source.id!r} missing 'class_name' param — "
                "the cairo backend cannot route to a renderer without one"
            )

    def test_external_rgba_sources_carry_shm_path_param(
        self, layout_pair: tuple[str, Layout]
    ) -> None:
        """Every external_rgba source must declare its /dev/shm producer path."""

        name, layout = layout_pair
        for source in layout.sources:
            if source.kind != "external_rgba":
                continue
            shm_path = source.params.get("shm_path") if source.params else None
            assert shm_path, (
                f"{name}: external_rgba source {source.id!r} missing 'shm_path' "
                "param — shm_rgba backend has nothing to read"
            )


# ── Reference integrity (regression pin) ───────────────────────────────


class TestReferenceIntegrity:
    """The Layout model already validates source/surface IDs reference existing
    members; pin that pre-existing behaviour as part of the invariant set so
    a refactor that drops the model_validator gets caught here."""

    def test_every_assignment_resolves_to_a_source_and_surface(
        self, layout_pair: tuple[str, Layout]
    ) -> None:
        name, layout = layout_pair
        source_ids = {s.id for s in layout.sources}
        surface_ids = {s.id for s in layout.surfaces}
        for a in layout.assignments:
            assert a.source in source_ids, (
                f"{name}: assignment source {a.source!r} not in source set"
            )
            assert a.surface in surface_ids, (
                f"{name}: assignment surface {a.surface!r} not in surface set"
            )


# ── Coverage smoke ──────────────────────────────────────────────────────


def test_corpus_is_non_empty() -> None:
    """Sanity: at least the three production layouts exist and load."""

    names = [name for name, _ in PRODUCTION_LAYOUTS]
    assert len(names) >= 3, f"expected ≥3 production layouts, got {names!r}"
    for required in ("config/compositor-layouts/default.json",):
        assert required in names, f"missing required layout: {required}"
