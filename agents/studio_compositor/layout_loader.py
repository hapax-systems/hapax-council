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

import logging
import os
import threading
from pathlib import Path

from pydantic import ValidationError

from shared.compositor_model import Layout

log = logging.getLogger(__name__)


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
        self._layout_dir = layout_dir or _default_layout_dir()
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
            self._active_name = name
            log.info("Active layout: %s", name)
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
        if not self._layout_dir.exists():
            log.debug("Layout dir %s does not exist", self._layout_dir)
            return []

        changed: list[str] = []

        # Discover current files on disk
        on_disk: dict[str, Path] = {}
        for path in sorted(self._layout_dir.glob("*.json")):
            on_disk[path.stem] = path

        with self._lock:
            # Load new or modified files
            for name, path in on_disk.items():
                try:
                    mtime = os.path.getmtime(path)
                except OSError:
                    continue
                if self._mtimes.get(name) == mtime:
                    continue
                try:
                    layout = Layout.model_validate_json(path.read_text())
                except (ValidationError, OSError, ValueError) as exc:
                    log.warning("Failed to load layout %s: %s", path, exc)
                    continue
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
