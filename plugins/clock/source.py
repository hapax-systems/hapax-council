"""Reference plugin: clock widget.

Renders the current time as text using the shared text_render helper
landed in Phase 3c. This is the end-to-end example of a Phase 6
compositor plugin — copy this directory as a starting template for
your own plugins.

Plugin lifecycle: a plugin source provides a ``render(cr, w, h, t,
state)`` method matching the :class:`CairoSource` protocol. The
:class:`CairoSourceRunner` (Phase 3b) drives it on a background
thread at the configured cadence and writes the cached surface
through the source protocol so the wgpu side can sample it.

Phase 6c of the compositor unification epic. See:
docs/superpowers/specs/2026-04-12-phase-6-plugin-system-design.md
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from agents.studio_compositor.cairo_source import CairoSource
from agents.studio_compositor.text_render import TextStyle, render_text

if TYPE_CHECKING:
    import cairo


class ClockSource(CairoSource):
    """A CairoSource that renders the current time on every tick.

    The instance is configured at construction time from the manifest
    parameters (``format``, ``font_family``, ``font_size_pt``). The
    operator's compositor code is responsible for instantiating this
    class — the registry only declares it exists; lazy import via
    ``manifest.source_module``.
    """

    def __init__(
        self,
        format: str = "%H:%M:%S",
        font_family: str = "JetBrains Mono",
        font_size_pt: float = 24.0,
    ) -> None:
        self._format = format
        self._font_description = f"{font_family} {int(font_size_pt)}"

    def render(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        text = time.strftime(self._format)
        style = TextStyle(
            text=text,
            font_description=self._font_description,
            color_rgba=(1.0, 1.0, 1.0, 1.0),
            outline_color_rgba=(0.0, 0.0, 0.0, 0.85),
        )
        render_text(cr, style, x=8, y=8)
