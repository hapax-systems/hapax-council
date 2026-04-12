"""PluginRegistry — discovers, validates, and exposes compositor plugins.

Phase 6 of the compositor unification epic. Walks ``plugins/{name}/``
at startup and on each reload tick, loads ``manifest.json`` files,
validates them via the :class:`shared.plugin_manifest.PluginManifest`
Pydantic model, and stores :class:`LoadedPlugin` instances keyed by
name.

A directory under ``plugins/`` is a compositor plugin iff it
contains a top-level ``manifest.json`` file. Existing Rust GStreamer
plugins (gst-crossfade, gst-smooth-delay, gst-temporalfx) have only
``Cargo.toml`` and are silently ignored.

Failed loads (invalid JSON, schema validation errors, name mismatches)
are caught, logged with context, and recorded in ``list_failed()``
for observability. The compositor never crashes on a malformed
plugin — it just isn't available until the operator fixes the
manifest.

See: docs/superpowers/specs/2026-04-12-phase-6-plugin-system-design.md
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from shared.plugin_manifest import PluginManifest

log = logging.getLogger(__name__)


@dataclass
class LoadedPlugin:
    """A plugin whose manifest validated successfully."""

    name: str
    manifest: PluginManifest
    plugin_dir: Path
    manifest_mtime: float


@dataclass
class FailedPlugin:
    """A plugin whose manifest failed to load. Kept for observability.

    The registry never crashes on a bad manifest — it records the
    failure here so the operator can list them via
    :meth:`PluginRegistry.list_failed` and fix the offending file.
    """

    name: str
    plugin_dir: Path
    error: str


@dataclass
class _ScanResult:
    """Internal: aggregate counts from one scan/reload pass."""

    loaded: int = 0
    failed: int = 0
    changed_names: list[str] = field(default_factory=list)


def _default_plugins_dir() -> Path:
    """Resolve the ``plugins/`` directory at the repo root.

    Walks up from this module's location until it finds a sibling
    ``plugins`` directory. Returns the in-tree path for the
    common-case checkout. If no ``plugins`` directory exists in any
    parent, returns the canonical path under the current working
    directory — the registry will then yield zero loaded plugins,
    which is fine.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "plugins"
        if candidate.is_dir():
            return candidate
    return Path.cwd() / "plugins"


class PluginRegistry:
    """Thread-safe registry of compositor plugins.

    Use ``scan()`` once at startup to populate; call
    ``reload_changed()`` on a periodic tick (1Hz, mirroring
    LayoutStore) to pick up manifest edits.

    Concurrent reads via ``get`` / ``list_loaded`` are lock-free
    against the write path because writes acquire the internal lock
    and swap dicts atomically. Readers see a consistent snapshot.
    """

    def __init__(self, plugins_dir: Path | None = None) -> None:
        self._plugins_dir = plugins_dir or _default_plugins_dir()
        self._loaded: dict[str, LoadedPlugin] = {}
        self._failed: dict[str, FailedPlugin] = {}
        self._lock = threading.Lock()

    @property
    def plugins_dir(self) -> Path:
        return self._plugins_dir

    def scan(self) -> tuple[int, int]:
        """Scan the plugins directory and load every well-formed manifest.

        Returns ``(loaded_count, failed_count)``. Resets the registry
        — any previously-loaded plugin not present on disk is dropped.
        Idempotent: calling scan() twice with no filesystem changes
        produces the same state.
        """
        result = self._scan_internal(reset=True)
        return (result.loaded, result.failed)

    def reload_changed(self) -> list[str]:
        """Re-scan, returning the names of plugins that changed.

        Cheaper than ``scan()`` for the steady state because it
        doesn't reload manifests whose mtime is unchanged. New
        plugins are added; deleted plugins are removed; modified
        manifests are re-validated. The returned list contains the
        names of every plugin whose loaded state changed (added,
        modified, or removed).
        """
        result = self._scan_internal(reset=False)
        return list(result.changed_names)

    def get(self, name: str) -> LoadedPlugin | None:
        with self._lock:
            return self._loaded.get(name)

    def list_loaded(self) -> list[str]:
        with self._lock:
            return sorted(self._loaded)

    def list_failed(self) -> list[FailedPlugin]:
        with self._lock:
            return list(self._failed.values())

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _scan_internal(self, *, reset: bool) -> _ScanResult:
        """Walk the plugins directory and update the registry state.

        ``reset=True`` clears the registry first (full scan); ``reset=False``
        diffs against the existing state (hot-reload tick).
        """
        result = _ScanResult()
        if not self._plugins_dir.is_dir():
            log.debug("PluginRegistry: %s does not exist", self._plugins_dir)
            with self._lock:
                if reset:
                    self._loaded.clear()
                    self._failed.clear()
            return result

        candidate_dirs: dict[str, Path] = {}
        for entry in sorted(self._plugins_dir.iterdir()):
            if not self._is_plugin_dir(entry):
                continue
            candidate_dirs[entry.name] = entry

        new_loaded: dict[str, LoadedPlugin] = {}
        new_failed: dict[str, FailedPlugin] = {}

        with self._lock:
            for name, plugin_dir in candidate_dirs.items():
                manifest_path = plugin_dir / "manifest.json"
                try:
                    mtime = manifest_path.stat().st_mtime
                except OSError as exc:
                    new_failed[name] = FailedPlugin(
                        name=name,
                        plugin_dir=plugin_dir,
                        error=f"stat: {exc}",
                    )
                    continue

                if not reset:
                    existing = self._loaded.get(name)
                    if existing is not None and existing.manifest_mtime == mtime:
                        new_loaded[name] = existing
                        continue

                outcome = _load_one(plugin_dir, mtime)
                if isinstance(outcome, LoadedPlugin):
                    new_loaded[name] = outcome
                    if name not in self._loaded or self._loaded[name].manifest_mtime != mtime:
                        result.changed_names.append(name)
                else:
                    new_failed[name] = outcome
                    if name in self._loaded:
                        result.changed_names.append(name)

            # Detect deletions: plugins that were loaded last tick but
            # no longer exist on disk.
            for name in self._loaded:
                if name not in candidate_dirs and name not in result.changed_names:
                    result.changed_names.append(name)

            self._loaded = new_loaded
            self._failed = new_failed
            result.loaded = len(new_loaded)
            result.failed = len(new_failed)

        if result.loaded or result.failed:
            log.info(
                "PluginRegistry: %d loaded, %d failed (%s)",
                result.loaded,
                result.failed,
                self._plugins_dir,
            )
        return result

    @staticmethod
    def _is_plugin_dir(candidate: Path) -> bool:
        """A directory is a compositor plugin iff it has a manifest.json.

        Cargo plugins under plugins/ have Cargo.toml and no
        manifest.json — they fail this check and are silently ignored.
        """
        return candidate.is_dir() and (candidate / "manifest.json").is_file()


def _load_one(plugin_dir: Path, mtime: float) -> LoadedPlugin | FailedPlugin:
    """Load and validate a single plugin manifest.

    Returns LoadedPlugin on success, FailedPlugin (with error context)
    on any failure mode: missing manifest, invalid JSON, schema
    validation error, or directory/name mismatch.
    """
    name = plugin_dir.name
    manifest_path = plugin_dir / "manifest.json"
    try:
        raw = json.loads(manifest_path.read_text())
    except json.JSONDecodeError as exc:
        log.warning("PluginRegistry: invalid JSON in %s: %s", manifest_path, exc)
        return FailedPlugin(name=name, plugin_dir=plugin_dir, error=f"json: {exc}")
    except OSError as exc:
        log.warning("PluginRegistry: cannot read %s: %s", manifest_path, exc)
        return FailedPlugin(name=name, plugin_dir=plugin_dir, error=f"io: {exc}")

    try:
        manifest = PluginManifest.model_validate(raw)
    except ValidationError as exc:
        log.warning("PluginRegistry: validation failed for %s: %s", name, exc)
        return FailedPlugin(name=name, plugin_dir=plugin_dir, error=f"validation: {exc}")

    if manifest.name != name:
        msg = (
            f"manifest.name {manifest.name!r} does not match directory name {name!r}; "
            f"plugins must self-identify by their directory name"
        )
        log.warning("PluginRegistry: %s", msg)
        return FailedPlugin(name=name, plugin_dir=plugin_dir, error=msg)

    return LoadedPlugin(
        name=name,
        manifest=manifest,
        plugin_dir=plugin_dir,
        manifest_mtime=mtime,
    )
