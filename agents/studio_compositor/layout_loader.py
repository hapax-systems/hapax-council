"""LayoutStore — loads Layouts from disk, watches for changes.

Hot-reload via mtime polling at low cadence (1Hz, called from the
state reader loop). Active layout selected by name. The compositor reads
the active layout each frame via the Extract phase.

The store is the single source of truth for the current Layout. Mutations
go through set_active() or by editing JSON files in the watch directory.

Phase 2c of the compositor unification epic. The LayoutStore is wired
into the compositor at startup so a Layout exists in process state, but
no rendering code yet calls Extract or consumes the FrameDescription.
That's Phase 3.

See docs/superpowers/specs/2026-04-12-phase-2-data-model-design.md
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

from pydantic import ValidationError

from shared.compositor_model import Layout

log = logging.getLogger(__name__)

IGNORED_LAYOUT_FILES: frozenset[str] = frozenset({"mobile.json"})


def _looks_like_layout_document(raw: str) -> bool:
    """Return True for JSON documents shaped like ``shared.compositor_model.Layout``.

    ``config/compositor-layouts/mobile.json`` is a vertical-mobile renderer
    contract, not a Layout model.  It lives beside production layouts for
    deployment convenience, so the LayoutStore must skip it instead of
    warning once per file edit.
    """

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return True
    if not isinstance(payload, dict):
        return True
    required = {"name", "sources", "surfaces", "assignments"}
    return required.issubset(payload)


def _rescale_layout(layout: Layout) -> Layout:
    """Scale absolute pixel coordinates by ``config.LAYOUT_COORD_SCALE``.

    A+ Stage 2 (2026-04-17): layouts were authored at 1920x1080 absolute
    coordinates. When the canvas drops to 1280x720 (or any size), we
    scale x/y/w/h uniformly by the same factor so the layout maintains
    the same visual proportions. Only touches surfaces with numeric
    geometry; non-rect surfaces (video_out sinks, binding-named
    render_target) pass through unchanged.

    Returns a new Layout via Pydantic model_copy; never mutates the input.
    """
    from .config import LAYOUT_COORD_SCALE

    if abs(LAYOUT_COORD_SCALE - 1.0) < 1e-6:
        return layout  # no-op at native resolution
    new_surfaces = []
    for surface in layout.surfaces:
        geom = surface.geometry
        # Only scale rect-like geometries with numeric x/y/w/h.
        new_geom = geom
        if geom.kind == "rect" and all(
            isinstance(getattr(geom, f, None), (int, float)) for f in ("x", "y", "w", "h")
        ):
            new_geom = geom.model_copy(
                update={
                    "x": int(round(geom.x * LAYOUT_COORD_SCALE)),
                    "y": int(round(geom.y * LAYOUT_COORD_SCALE)),
                    "w": int(round(geom.w * LAYOUT_COORD_SCALE)),
                    "h": int(round(geom.h * LAYOUT_COORD_SCALE)),
                }
            )
        new_surfaces.append(surface.model_copy(update={"geometry": new_geom}))
    return layout.model_copy(update={"surfaces": new_surfaces})


def _default_layout_dir() -> Path:
    """Resolve the default layout directory.

    Looks at ~/.config/hapax-compositor/layouts/ first; if absent, falls
    back to the in-tree config/layouts/ directory (so the canonical
    garage-door.json works without an install step).
    """
    home_dir = Path.home() / ".config" / "hapax-compositor" / "layouts"
    if home_dir.exists():
        return home_dir
    # Fall back to repo-local config/layouts/ — walk up from this file
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "config" / "layouts"
        if candidate.exists():
            return candidate
    return home_dir  # last-resort: return the home path even if missing


def _extra_layout_dirs(primary: Path) -> list[Path]:
    """Additional layout dirs the LayoutStore should scan.

    Current compositor layouts live across ``config/compositor-layouts/``
    and ``config/layouts/``. Without an install step the LayoutStore
    would only see ``config/layouts/garage-door.json``, blocking the
    u6-periodic-tick-driver and segment layout control from ever
    switching off ``garage-door``.

    Returns repo-local fallback dirs that are NOT the primary. On
    name collision the primary wins (it's scanned last in
    ``_scan_directory``, but we suppress duplicates by tracking
    ``on_disk`` keys via the primary first).
    """
    extras: list[Path] = []
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "config" / "compositor-layouts"
        if candidate.exists() and candidate.resolve() != primary.resolve():
            extras.append(candidate)
            examples = candidate / "examples"
            if examples.exists():
                extras.append(examples)
            break
    # Also include repo-local config/layouts/ if primary is the home dir
    # and the primary doesn't shadow garage-door.
    home_dir = Path.home() / ".config" / "hapax-compositor" / "layouts"
    if primary.resolve() == home_dir.resolve():
        for parent in here.parents:
            candidate = parent / "config" / "layouts"
            if candidate.exists():
                extras.append(candidate)
                break
    return extras


class LayoutStore:
    """Thread-safe holder for the current Layout with disk watch.

    Layouts live at ~/.config/hapax-compositor/layouts/*.json. The store
    loads all layouts at construction time and re-scans the directory
    when reload_changed() is called (typically once per second from the
    state reader loop).

    Example:
        store = LayoutStore()
        store.set_active("garage-door")
        layout = store.get_active()
        # ... per render frame:
        changed = store.reload_changed()
        if "garage-door" in changed:
            # active layout was modified on disk and reloaded
            ...
    """

    def __init__(self, layout_dir: Path | None = None) -> None:
        # Track whether caller passed an explicit dir (test isolation):
        # when explicit, do NOT pull in repo-local fallbacks.
        explicit = layout_dir is not None
        self._layout_dir = layout_dir or _default_layout_dir()
        # u6-periodic-tick-driver: also scan additional repo-local
        # compositor-layouts dirs so current default/safety/segment
        # layouts are discoverable without an install step, but only
        # when falling back to the default layout dir, so tests passing
        # tmp_path stay isolated.
        self._extra_dirs: list[Path] = [] if explicit else _extra_layout_dirs(self._layout_dir)
        self._layouts: dict[str, Layout] = {}
        self._mtimes: dict[str, float] = {}
        self._active_name: str | None = None
        self._lock = threading.Lock()
        self._scan_directory()

    @property
    def layout_dir(self) -> Path:
        return self._layout_dir

    def get_active(self) -> Layout | None:
        """Return the currently active Layout, or None if none is set."""
        with self._lock:
            if self._active_name is None:
                return None
            return self._layouts.get(self._active_name)

    def get(self, name: str) -> Layout | None:
        """Return a layout by name, or None if not loaded."""
        with self._lock:
            return self._layouts.get(name)

    def set_active(self, name: str) -> bool:
        """Switch the active layout. Returns True if the layout exists."""
        with self._lock:
            if name not in self._layouts:
                log.warning(
                    "set_active(%s) failed: layout not loaded (available: %s)",
                    name,
                    list(self._layouts.keys()),
                )
                return False
            previous = self._active_name
            self._active_name = name
            log.info("Active layout: %s", name)
        # Update the U6 active-layout gauge outside the lock so the
        # metrics module's own lock doesn't compose with ours. Best-effort:
        # the gauge is unimportant if metrics aren't initialised (CI / unit
        # tests without prometheus_client) and we never let a metrics fault
        # break the layout switch.
        try:
            from agents.studio_compositor import metrics as _metrics

            gauge = getattr(_metrics, "HAPAX_COMPOSITOR_LAYOUT_ACTIVE", None)
            if gauge is not None:
                if previous is not None:
                    gauge.labels(layout=previous).set(0.0)
                gauge.labels(layout=name).set(1.0)
        except Exception:
            log.debug("HAPAX_COMPOSITOR_LAYOUT_ACTIVE update failed", exc_info=True)
        return True

    def active_name(self) -> str | None:
        """Return the name of the active layout, or None."""
        with self._lock:
            return self._active_name

    def list_available(self) -> list[str]:
        """Return the names of all loaded layouts."""
        with self._lock:
            return sorted(self._layouts.keys())

    def reload_changed(self) -> list[str]:
        """Re-scan the layout directory for new or modified files.

        Returns the list of layout names that were added or modified.
        Files that were deleted from disk are removed from the store.
        Failed JSON parses are logged but do not crash.

        Called from the state reader loop at low cadence (typically 1Hz).
        """
        return self._scan_directory()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _scan_directory(self) -> list[str]:
        """Scan the layout directory and reload changed files.

        Returns the list of layout names that were added or modified.
        """
        # u6-periodic-tick-driver: scan extras first so the primary
        # layout_dir (operator's ~/.config dir) overrides on name
        # collision. Extras are repo-local fallbacks for current
        # default/safety/segment layouts.
        on_disk: dict[str, Path] = {}
        for extra in self._extra_dirs:
            if not extra.exists():
                continue
            for path in sorted(extra.glob("*.json")):
                if path.name in IGNORED_LAYOUT_FILES:
                    continue
                on_disk[path.stem] = path

        if not self._layout_dir.exists():
            log.debug("Layout dir %s does not exist", self._layout_dir)
            if not on_disk:
                return []
            # Otherwise extras provide layouts even without the primary.

        changed: list[str] = []

        # Discover current files in the primary dir; primary OVERRIDES
        # extras on name collision (operator edits win).
        for path in sorted(self._layout_dir.glob("*.json")):
            if path.name in IGNORED_LAYOUT_FILES:
                continue
            on_disk[path.stem] = path

        with self._lock:
            # Load new or modified files
            for name, path in on_disk.items():
                try:
                    mtime = os.path.getmtime(path)
                except OSError as exc:
                    # Audit follow-up: was a silent `pass`. Promoted to
                    # warning so a permissions issue or a half-deleted
                    # file on /tmp surfaces instead of appearing as the
                    # layout "just not updating".
                    log.warning("LayoutStore: stat failed for %s: %s", path, exc)
                    continue
                if self._mtimes.get(name) == mtime:
                    continue
                try:
                    raw_layout = path.read_text()
                    if not _looks_like_layout_document(raw_layout):
                        log.debug("Skipping non-Layout JSON in layout scan: %s", path)
                        self._mtimes[name] = mtime
                        continue
                    layout = Layout.model_validate_json(raw_layout)
                except (ValidationError, OSError, ValueError) as exc:
                    log.warning("Failed to load layout %s: %s", path, exc)
                    # Cache the mtime even on validation failure so we don't
                    # re-log the same warning on every reload tick (1 Hz). A
                    # broken file gets logged once per actual file change,
                    # not once per scan. mobile.json was emitting ~1620
                    # warnings/hour against this loader before this cache
                    # (vertical-mobile schema; a future feature, not a
                    # current-schema layout).
                    self._mtimes[name] = mtime
                    continue
                # A+ Stage 2 (2026-04-17): rescale absolute pixel coords
                # by LAYOUT_COORD_SCALE so existing 1920x1080-authored
                # layout JSONs render correctly at 1280x720 (or any
                # other canvas size). Only touches surfaces with
                # integer/float x/y/w/h — video_out + other
                # non-rect surfaces pass through unchanged.
                layout = _rescale_layout(layout)
                self._layouts[name] = layout
                self._mtimes[name] = mtime
                changed.append(name)

            # Remove deleted files
            for name in list(self._layouts.keys()):
                if name not in on_disk:
                    del self._layouts[name]
                    self._mtimes.pop(name, None)
                    if self._active_name == name:
                        log.warning(
                            "Active layout %s was deleted from disk; clearing",
                            name,
                        )
                        self._active_name = None

        if changed:
            log.debug("Layouts changed: %s", changed)
        return changed
