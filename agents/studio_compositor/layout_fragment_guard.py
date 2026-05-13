"""Shared whole-surface guard for segment-driven layout activation."""

from __future__ import annotations

import os
from typing import Any

from shared.compositor_model import Layout

DIRECTOR_SEGMENT_SOURCE = "director_segment_runner"
SEGMENT_FRAGMENT_ENV = "HAPAX_DIRECTOR_SEGMENT_FRAGMENT_LAYOUTS_ENABLED"
SEGMENT_MIN_SOURCES_ENV = "HAPAX_DIRECTOR_SEGMENT_MIN_LAYOUT_SOURCES"
DEFAULT_SEGMENT_MIN_SOURCES = 6


def _env_truthy(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, *, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def segment_min_source_count() -> int:
    return max(
        1,
        _env_int(
            SEGMENT_MIN_SOURCES_ENV,
            default=DEFAULT_SEGMENT_MIN_SOURCES,
        ),
    )


def source_count(layout: Layout | Any) -> int:
    return len(getattr(layout, "sources", ()) or ())


def is_segment_layout_name(layout_name: str | None) -> bool:
    return isinstance(layout_name, str) and layout_name.startswith("segment-")


def compose_segment_fragment_over_layout(
    *,
    layout_name: str,
    fragment_layout: Layout | Any,
    base_layout: Layout | Any,
) -> Layout | None:
    """Return a whole-surface segment layout by overlaying a segment panel.

    ``segment-*`` JSON files are intentionally small panel fragments. They are
    safe as overlays, but not as whole-surface replacements. Runtime segment
    activation needs a full layout readback whose name matches the bounded
    segment posture, so we compose the selected panel over the current rendered
    full-surface layout instead of bypassing the guard.
    """

    if not is_segment_layout_name(layout_name):
        return None
    if source_count(fragment_layout) >= segment_min_source_count():
        return None
    if source_count(base_layout) < segment_min_source_count():
        return None
    if not isinstance(base_layout, Layout) or not isinstance(fragment_layout, Layout):
        return None
    if getattr(base_layout, "name", None) == layout_name:
        fragment_source_ids = {source.id for source in fragment_layout.sources}
        base_source_ids = {source.id for source in base_layout.sources}
        if fragment_source_ids.issubset(base_source_ids):
            return base_layout

    base_source_ids = {source.id for source in base_layout.sources}
    sources = [*base_layout.sources]
    for source in fragment_layout.sources:
        if source.id not in base_source_ids:
            sources.append(source)
            base_source_ids.add(source.id)

    base_surface_ids = {surface.id for surface in base_layout.surfaces}
    surfaces = [*base_layout.surfaces]
    fragment_surface_ids: set[str] = set()
    for surface in fragment_layout.surfaces:
        if surface.id in base_surface_ids:
            continue
        if getattr(surface.geometry, "kind", None) == "video_out":
            continue
        surfaces.append(surface)
        fragment_surface_ids.add(surface.id)
        base_surface_ids.add(surface.id)

    source_ids = {source.id for source in sources}
    assignments = [*base_layout.assignments]
    seen_assignments = {(item.source, item.surface) for item in assignments}
    for assignment in fragment_layout.assignments:
        key = (assignment.source, assignment.surface)
        if key in seen_assignments:
            continue
        if assignment.source not in source_ids or assignment.surface not in fragment_surface_ids:
            continue
        assignments.append(assignment)
        seen_assignments.add(key)

    if len(sources) < segment_min_source_count() or not fragment_surface_ids:
        return None

    description = getattr(fragment_layout, "description", None) or ""
    base_name = getattr(base_layout, "name", "base")
    composed_description = (
        f"{description} Composed over {base_name} as a whole-surface segment activation."
    ).strip()
    return base_layout.model_copy(
        update={
            "name": layout_name,
            "description": composed_description,
            "sources": sources,
            "surfaces": surfaces,
            "assignments": assignments,
        }
    )


def segment_fragment_layout_error(
    *,
    layout_name: str,
    layout: Layout | Any,
    source: str | None = None,
) -> dict[str, Any] | None:
    """Return a structured error if a fragment would replace the full stream.

    Segment layouts are legitimate panel fragments, but they are not legitimate
    whole-surface replacements unless explicitly enabled. This guard is shared
    between the command server and autonomous layout tick driver so all segment
    activation paths observe the same contract.
    """
    if source is not None and source != DIRECTOR_SEGMENT_SOURCE:
        return None
    if not is_segment_layout_name(layout_name):
        return None
    if _env_truthy(SEGMENT_FRAGMENT_ENV):
        return None
    min_sources = segment_min_source_count()
    count = source_count(layout)
    if count >= min_sources:
        return None
    return {
        "error": "segment_fragment_layout_not_full_surface",
        "layout_name": layout_name,
        "source_count": count,
        "min_source_count": min_sources,
        "hint": (
            "segment layouts are panel fragments; fragment panels must not replace "
            "the livestream surface"
        ),
    }
