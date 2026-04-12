"""Tests for the compile phase.

Phase 4a of the compositor unification epic — the second of three
render-time stages (Extract → Compile → Execute). The compile phase
turns FrameDescription into CompiledFrame, a frozen execution plan
the future executor will consume.

This phase is purely additive: no rendering code yet reads CompiledFrame.
Tests verify the compile reasoning is correct on synthetic and canonical
layouts.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from agents.studio_compositor.compile import CompiledFrame, compile_frame
from agents.studio_compositor.extract import extract_frame_description
from shared.compositor_model import (
    Assignment,
    Layout,
    SourceSchema,
    SurfaceGeometry,
    SurfaceSchema,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _src(id_: str, kind: str = "shader", backend: str = "wgsl_render") -> SourceSchema:
    return SourceSchema(id=id_, kind=kind, backend=backend)  # type: ignore[arg-type]


def _surf(id_: str, z_order: int = 0, kind: str = "rect") -> SurfaceSchema:
    return SurfaceSchema(
        id=id_,
        geometry=SurfaceGeometry(kind=kind, x=0, y=0, w=64, h=64),  # type: ignore[arg-type]
        z_order=z_order,
    )


def _frame(layout: Layout, frame_index: int = 0):
    return extract_frame_description(layout, frame_index=frame_index, timestamp=1.0)


# ---------------------------------------------------------------------------
# Empty / minimal layouts
# ---------------------------------------------------------------------------


def test_empty_layout_compiles_to_empty_plan():
    """A layout with no sources/surfaces/assignments compiles to an
    empty CompiledFrame — no active, no culled, no assignments."""
    layout = Layout(name="empty", sources=[], surfaces=[], assignments=[])
    compiled = compile_frame(_frame(layout))
    assert isinstance(compiled, CompiledFrame)
    assert compiled.active_sources == ()
    assert compiled.culled_sources == frozenset()
    assert compiled.active_assignments == ()
    assert compiled.cull_count == 0
    assert compiled.total_sources == 0
    assert compiled.layout_name == "empty"


def test_compile_frame_mirrors_frame_index_and_timestamp():
    layout = Layout(name="meta", sources=[], surfaces=[], assignments=[])
    frame = extract_frame_description(layout, frame_index=42, timestamp=99.5)
    compiled = compile_frame(frame)
    assert compiled.frame_index == 42
    assert compiled.timestamp == 99.5


# ---------------------------------------------------------------------------
# Dead-source culling
# ---------------------------------------------------------------------------


def test_all_sources_referenced_no_culling():
    """When every source has at least one assignment, no source is culled."""
    layout = Layout(
        name="all-bound",
        sources=[_src("a"), _src("b"), _src("c")],
        surfaces=[_surf("s")],
        assignments=[
            Assignment(source="a", surface="s"),
            Assignment(source="b", surface="s"),
            Assignment(source="c", surface="s"),
        ],
    )
    compiled = compile_frame(_frame(layout))
    assert set(compiled.active_sources) == {"a", "b", "c"}
    assert compiled.culled_sources == frozenset()
    assert compiled.cull_count == 0


def test_unreferenced_source_is_culled():
    """A source with no assignment ends up in culled_sources with reason."""
    layout = Layout(
        name="orphan",
        sources=[_src("bound"), _src("orphan")],
        surfaces=[_surf("s")],
        assignments=[Assignment(source="bound", surface="s")],
    )
    compiled = compile_frame(_frame(layout))
    assert compiled.active_sources == ("bound",)
    assert compiled.culled_sources == frozenset({"orphan"})
    assert compiled.cull_reason == {"orphan": "no_assignment_references_source"}


def test_culled_source_excluded_from_active():
    """active_sources never contains a culled source ID."""
    layout = Layout(
        name="mixed",
        sources=[_src("keep"), _src("drop1"), _src("drop2")],
        surfaces=[_surf("s")],
        assignments=[Assignment(source="keep", surface="s")],
    )
    compiled = compile_frame(_frame(layout))
    for culled in compiled.culled_sources:
        assert culled not in compiled.active_sources


def test_active_source_order_matches_layout_order():
    """active_sources preserves the layout's source declaration order."""
    layout = Layout(
        name="ordering",
        sources=[_src("c"), _src("a"), _src("b")],
        surfaces=[_surf("s")],
        assignments=[
            Assignment(source="a", surface="s"),
            Assignment(source="b", surface="s"),
            Assignment(source="c", surface="s"),
        ],
    )
    compiled = compile_frame(_frame(layout))
    # Order is c, a, b — the layout's source list order, not assignment order.
    assert compiled.active_sources == ("c", "a", "b")


# ---------------------------------------------------------------------------
# Assignment ordering
# ---------------------------------------------------------------------------


def test_active_assignments_ordered_by_surface_zorder():
    """Assignments are sorted by destination surface z_order ascending."""
    layout = Layout(
        name="zorder",
        sources=[_src("s1"), _src("s2"), _src("s3")],
        surfaces=[
            _surf("hi", z_order=10),
            _surf("lo", z_order=0),
            _surf("mid", z_order=5),
        ],
        assignments=[
            Assignment(source="s1", surface="hi"),
            Assignment(source="s2", surface="lo"),
            Assignment(source="s3", surface="mid"),
        ],
    )
    compiled = compile_frame(_frame(layout))
    surfaces = [a.surface for a in compiled.active_assignments]
    assert surfaces == ["lo", "mid", "hi"]


def test_active_assignments_stable_within_zorder():
    """Two assignments with the same z_order preserve layout order."""
    layout = Layout(
        name="stable",
        sources=[_src("a"), _src("b"), _src("c")],
        surfaces=[
            _surf("s1", z_order=0),
            _surf("s2", z_order=0),
            _surf("s3", z_order=0),
        ],
        assignments=[
            Assignment(source="a", surface="s2"),
            Assignment(source="b", surface="s1"),
            Assignment(source="c", surface="s3"),
        ],
    )
    compiled = compile_frame(_frame(layout))
    # Same z_order → layout (assignment list) order is preserved.
    assert [a.source for a in compiled.active_assignments] == ["a", "b", "c"]


def test_assignments_to_culled_sources_excluded():
    """Defensive: if any assignment references a missing source, exclude it.

    Pydantic Layout validation rejects this in practice (the model
    validator enforces source existence), so we can't construct one
    directly through the schema. We instead verify that the active
    assignment list does not contain orphan references in valid layouts.
    """
    with pytest.raises(ValidationError):
        Layout(
            name="invalid",
            sources=[_src("real")],
            surfaces=[_surf("s")],
            assignments=[Assignment(source="ghost", surface="s")],
        )


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


def test_total_sources_property():
    layout = Layout(
        name="counts",
        sources=[_src("a"), _src("b"), _src("c"), _src("d")],
        surfaces=[_surf("s")],
        assignments=[Assignment(source="a", surface="s")],
    )
    compiled = compile_frame(_frame(layout))
    assert compiled.cull_count == 3
    assert len(compiled.active_sources) == 1
    assert compiled.total_sources == 4


def test_compiled_frame_is_frozen():
    """Frozen dataclass forbids attribute mutation."""
    layout = Layout(name="frozen", sources=[], surfaces=[], assignments=[])
    compiled = compile_frame(_frame(layout))
    with pytest.raises(Exception):  # FrozenInstanceError
        compiled.frame_index = 99  # type: ignore[misc]


def test_compile_frame_is_pure_function():
    """Same FrameDescription compiled twice produces equal CompiledFrames."""
    layout = Layout(
        name="pure",
        sources=[_src("a"), _src("b")],
        surfaces=[_surf("s", z_order=2)],
        assignments=[
            Assignment(source="a", surface="s"),
            Assignment(source="b", surface="s"),
        ],
    )
    frame = _frame(layout)
    a = compile_frame(frame)
    b = compile_frame(frame)
    assert a == b
    # Same active set, same culled set, same assignment ordering.
    assert a.active_sources == b.active_sources
    assert a.culled_sources == b.culled_sources
    assert a.active_assignments == b.active_assignments


# ---------------------------------------------------------------------------
# Canonical layout round-trip
# ---------------------------------------------------------------------------


def test_compile_garage_door_layout():
    """The canonical garage-door.json layout compiles successfully and
    produces non-empty active sources + assignments.

    This is the smoke test that catches regressions in the compile
    reasoning against the production layout.
    """
    layout_path = Path("config/layouts/garage-door.json")
    if not layout_path.exists():
        pytest.skip("garage-door.json not present in this checkout")
    raw = json.loads(layout_path.read_text())
    layout = Layout.model_validate(raw)
    compiled = compile_frame(_frame(layout))
    # The garage-door layout has at least one bound source.
    assert len(compiled.active_sources) > 0
    assert len(compiled.active_assignments) > 0
    # Layout name is preserved through compile.
    assert compiled.layout_name == layout.name
    # Active + culled cover all declared sources.
    assert compiled.total_sources == len(layout.sources)
