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
