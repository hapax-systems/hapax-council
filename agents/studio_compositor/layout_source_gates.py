"""Runtime gates for layout-assigned compositor sources.

These gates keep incident containment honest across the whole layout stack:
if a source family is held back, it must not bypass the hold by entering
through ``render_stage`` assignments instead of the legacy overlay path.
"""

from __future__ import annotations

import os

SIERPINSKI_LAYOUT_SOURCE_IDS: frozenset[str] = frozenset({"sierpinski"})
SIERPINSKI_BASE_OVERLAY_ENV = "HAPAX_SIERPINSKI_BASE_OVERLAY_ENABLED"
SIERPINSKI_LAYOUT_SOURCE_ENV = "HAPAX_SIERPINSKI_LAYOUT_SOURCE_ENABLED"


def _env_enabled(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", "disabled"}


def layout_source_enabled(source_id: str) -> bool:
    """Return whether a layout assignment may start or draw ``source_id``."""

    if source_id in SIERPINSKI_LAYOUT_SOURCE_IDS:
        base_overlay_enabled = _env_enabled(SIERPINSKI_BASE_OVERLAY_ENV, default=True)
        layout_source_enabled = _env_enabled(SIERPINSKI_LAYOUT_SOURCE_ENV, default=False)
        return layout_source_enabled and not base_overlay_enabled
    return True
