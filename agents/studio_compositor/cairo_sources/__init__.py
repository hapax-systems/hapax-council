"""Registry of migrated CairoSource classes, keyed by class_name.

``SourceRegistry.construct_backend`` looks up cairo sources here by the
``params.class_name`` field from the Layout JSON so new sources can be
declared in config without editing a hardcoded dispatch table — drop a
module with a CairoSource subclass into the codebase, import it at the
bottom of this file, and it's declarable in any Layout.

The Phase 3b compositor-unification epic already migrated the four core
cairo sources into their ``*CairoSource`` classes (TokenPoleCairoSource,
AlbumOverlayCairoSource, SierpinskiCairoSource, OverlayZonesCairoSource).
This package re-exports three of them for the source-registry PR 1
default layout (OverlayZones is deliberately left out — it renders at
full canvas via DVD-bounce and isn't a natural-size PiP candidate; its
migration is a follow-up).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.studio_compositor.cairo_source import CairoSource

_CAIRO_SOURCE_CLASSES: dict[str, type[CairoSource]] = {}


def register(name: str, cls: type[CairoSource]) -> None:
    """Register a CairoSource subclass under ``name``.

    Idempotent on duplicate registration of the same class. Raises
    :class:`ValueError` if ``name`` is already bound to a different class —
    we fail loud rather than silently overwriting (silent-failure discipline).
    """
    existing = _CAIRO_SOURCE_CLASSES.get(name)
    if existing is None:
        _CAIRO_SOURCE_CLASSES[name] = cls
        return
    if existing is cls:
        return
    raise ValueError(
        f"cairo_sources: name {name!r} already bound to {existing.__name__}, not {cls.__name__}"
    )


def get_cairo_source_class(name: str) -> type[CairoSource]:
    """Return the CairoSource subclass registered under ``name``.

    Raises :class:`KeyError` with the unknown name if not registered.
    """
    try:
        return _CAIRO_SOURCE_CLASSES[name]
    except KeyError as e:
        raise KeyError(f"cairo source class not registered: {name}") from e


def list_classes() -> list[str]:
    """Return the sorted list of registered class names."""
    return sorted(_CAIRO_SOURCE_CLASSES.keys())


# --- Built-in registrations -------------------------------------------------
#
# Import the three migrated classes at module load time so they show up in
# ``list_classes()`` and ``get_cairo_source_class()`` without the caller
# having to import them. Each import is late (inside a function) only to
# break circular imports between cairo_source and cairo_sources — direct
# imports are fine here.


def _register_builtins() -> None:
    from agents.studio_compositor.album_overlay import AlbumOverlayCairoSource
    from agents.studio_compositor.captions_source import CaptionsCairoSource
    from agents.studio_compositor.research_marker_overlay import ResearchMarkerOverlay
    from agents.studio_compositor.sierpinski_renderer import SierpinskiCairoSource
    from agents.studio_compositor.stream_overlay import StreamOverlayCairoSource
    from agents.studio_compositor.token_pole import TokenPoleCairoSource

    register("TokenPoleCairoSource", TokenPoleCairoSource)
    register("AlbumOverlayCairoSource", AlbumOverlayCairoSource)
    register("SierpinskiCairoSource", SierpinskiCairoSource)
    # LRR Phase 9 §3.6 — scientific-register caption overlay. Registered
    # so the class is declarable from Layout JSON; operator decides when
    # to add a captions surface.
    register("CaptionsCairoSource", CaptionsCairoSource)
    # Post-epic layout fix: StreamOverlayCairoSource renders the
    # preset/viewers/chat-activity three-line status strip, anchored
    # to the bottom-right of whatever canvas it is drawn into. It
    # feeds the ``stream_overlay`` source in the default layout's
    # ``pip-lr`` quadrant — operator's "chat stats LR" default.
    register("StreamOverlayCairoSource", StreamOverlayCairoSource)
    # Phase 10 carry-over from Phase 2 item 4: expose the research
    # marker overlay in the class-name registry so it's declarable
    # from layout JSON. Actual layout surface + assignment is a
    # separate operator-owned decision (the overlay is a top-strip
    # banner so it needs a full-width surface, unlike the other PiP
    # cairo sources). Registering here unblocks ``ResearchMarkerOverlay``
    # layout declarations without forcing a default-layout change.
    register("ResearchMarkerOverlay", ResearchMarkerOverlay)


_register_builtins()
