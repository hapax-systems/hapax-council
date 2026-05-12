"""ShmRgbaReader — reads RGBA frames from a shared-memory file + sidecar.

Sidecar format (``<path>.json``):
    {"w": int, "h": int, "stride": int, "frame_id": int}

The reader caches the last wrapped ``cairo.ImageSurface`` by ``frame_id`` and
re-wraps when the sidecar reports a new id. Missing file / missing sidecar /
unreadable JSON / short buffer all resolve to ``get_current_surface() -> None``
without raising — consumers get a clean "no frame yet" signal and the
compositor's ``compositor_source_frame_age_seconds`` metric catches chronic
staleness.

Part of the compositor source-registry epic PR 1. See
``docs/superpowers/specs/2026-04-12-compositor-source-registry-foundation-design.md``
§ "Source backends".
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agents.studio_compositor.gst_appsrc_limits import configure_live_appsrc_queue

if TYPE_CHECKING:
    import cairo

log = logging.getLogger(__name__)


class ShmRgbaReader:
    """Wraps an RGBA shared-memory file as a ``cairo.ImageSurface``.

    The file at ``path`` holds raw BGRA bytes (cairo FORMAT_ARGB32 is
    little-endian BGRA on all current platforms). The sidecar at
    ``<path>.json`` describes the current frame layout and the monotonic
    ``frame_id`` that increments on every producer write.
    """

    # HOMAGE #124 substrate marker (defaulted to False at the class level so
    # only ShmRgbaReader instances explicitly constructed with
    # ``is_substrate=True`` — today: the Reverie ``external_rgba`` slot —
    # are treated as always-on substrate. See
    # ``docs/superpowers/specs/2026-04-18-reverie-substrate-preservation-design.md``
    # and ``agents/studio_compositor/homage/substrate_source.py``.
    is_substrate: bool = False

    def __init__(
        self,
        path: Path,
        *,
        is_substrate: bool = False,
        max_age_s: float | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._path = Path(path)
        self._sidecar_path = self._path.with_suffix(self._path.suffix + ".json")
        self._cached_surface: cairo.ImageSurface | None = None
        self._cached_frame_id: int | None = None
        self._max_age_s = max_age_s if max_age_s is None or max_age_s > 0 else None
        self._clock = clock
        # Instance-level override of the class default. Setting it on the
        # instance (not just the class) means ``isinstance(reader,
        # HomageSubstrateSource)`` evaluates correctly per-instance —
        # non-substrate ShmRgbaReader instances never match the Protocol.
        self.is_substrate = is_substrate
        # Phase 6 H23: lazy GStreamer appsrc for the main-layer path.
        # Built on first ``gst_appsrc()`` call; the sidecar is re-read at
        # build time to pick up the natural dimensions. Phase 6b will add
        # a sidecar-watching push thread that feeds the element.
        self._gst_appsrc: Any = None

    def _frame_is_stale(self) -> bool:
        """Return True when either the RGBA payload or sidecar is too old."""
        if self._max_age_s is None:
            return False
        try:
            payload_mtime = self._path.stat().st_mtime
            sidecar_mtime = self._sidecar_path.stat().st_mtime
        except OSError:
            return False
        oldest_mtime = min(payload_mtime, sidecar_mtime)
        return self._clock() - oldest_mtime > self._max_age_s

    def gst_appsrc(self) -> Any:
        """Return (or lazily create) a GStreamer appsrc element for this source.

        Phase 6 (parent task H23). Dimensions are read from the sidecar
        JSON at the time of the first call; if the sidecar is missing
        the element is built with a fallback 640×360 cap so the pipeline
        topology stays stable until the shm producer ships its first
        frame. Caps can be renegotiated later by sending a ``stream-caps``
        event when the sidecar's dimensions change.

        Returns ``None`` if GStreamer isn't importable in the current
        environment — the caller treats that as "this source has no
        main-layer pad in this process".
        """
        if self._gst_appsrc is not None:
            return self._gst_appsrc
        try:
            import gi

            gi.require_version("Gst", "1.0")
            from gi.repository import Gst  # type: ignore[import-not-found]
        except (ImportError, ValueError):
            log.debug("ShmRgbaReader %s: gst_appsrc unavailable (no gi)", self._path)
            return None
        Gst.init(None)
        meta = self._read_sidecar() or {}
        width = int(meta.get("w", 640))
        height = int(meta.get("h", 360))
        elem = Gst.ElementFactory.make("appsrc", f"appsrc-{self._path.stem}")
        if elem is None:
            return None
        caps = Gst.Caps.from_string(
            f"video/x-raw,format=BGRA,width={width},height={height},framerate=0/1"
        )
        elem.set_property("caps", caps)
        elem.set_property("format", Gst.Format.TIME)
        elem.set_property("is-live", True)
        elem.set_property("do-timestamp", True)
        configure_live_appsrc_queue(elem)
        self._gst_appsrc = elem
        log.info(
            "ShmRgbaReader %s: gst_appsrc created (%dx%d BGRA)",
            self._path.name,
            width,
            height,
        )
        return elem

    def _read_sidecar(self) -> dict[str, Any] | None:
        """Return the sidecar JSON as a dict, or None on any failure.

        Validates the JSON root is a mapping. The ``get_current_surface``
        callsite immediately calls ``meta.get(\"frame_id\")`` and indexes
        ``meta[\"w\"]`` / ``meta[\"h\"]`` / ``meta[\"stride\"]``; a writer
        producing valid JSON whose root is null, a list, a string, or a
        number previously raised AttributeError out of the reverie surface
        render path. Same corruption-class as #2627, #2631, #2632, #2636
        (already merged) and #2640, #2642 (in flight).
        """
        if not self._sidecar_path.exists():
            return None
        try:
            data = json.loads(self._sidecar_path.read_text())
        except (OSError, json.JSONDecodeError):
            log.debug(
                "ShmRgbaReader failed to read sidecar %s",
                self._sidecar_path,
                exc_info=True,
            )
            return None
        if not isinstance(data, dict):
            log.debug(
                "ShmRgbaReader sidecar %s root is %s, expected mapping",
                self._sidecar_path,
                type(data).__name__,
            )
            return None
        return data

    def get_current_surface(self) -> cairo.ImageSurface | None:
        """Return the current frame as a cairo.ImageSurface, or None.

        The return value is cached by ``frame_id``: consecutive calls with
        the same sidecar ``frame_id`` return the same surface instance, so
        callers can rely on identity for short-term caching.
        """
        meta = self._read_sidecar()
        if meta is None:
            return None
        if not self._path.exists():
            return None
        if self._frame_is_stale():
            self._cached_surface = None
            self._cached_frame_id = None
            return None

        frame_id = meta.get("frame_id")
        if frame_id == self._cached_frame_id and self._cached_surface is not None:
            return self._cached_surface

        try:
            w = int(meta["w"])
            h = int(meta["h"])
            stride = int(meta["stride"])
        except (KeyError, TypeError, ValueError):
            log.debug("ShmRgbaReader sidecar %s missing w/h/stride", self._sidecar_path)
            return None

        try:
            raw = self._path.read_bytes()
        except OSError:
            log.debug("ShmRgbaReader failed to read %s", self._path, exc_info=True)
            return None
        if len(raw) < stride * h:
            log.debug("ShmRgbaReader buffer short: got %d, want %d", len(raw), stride * h)
            return None

        # Import cairo lazily so the module is importable in environments
        # without pycairo (e.g. documentation builders). The test suite
        # imports cairo unconditionally so this is transparent at runtime.
        import cairo

        data = bytearray(raw[: stride * h])
        surface = cairo.ImageSurface.create_for_data(data, cairo.FORMAT_ARGB32, w, h, stride)
        self._cached_surface = surface
        self._cached_frame_id = frame_id
        return surface
