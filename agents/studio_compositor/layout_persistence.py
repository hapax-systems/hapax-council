"""LayoutAutoSaver + LayoutFileWatcher — Phase 5 (parent task G22).

These two cooperating threads keep ``~/.config/hapax-compositor/layouts/default.json``
and the in-memory ``LayoutState`` coherent:

- :class:`LayoutAutoSaver` subscribes to ``LayoutState`` mutations and
  writes the current layout to disk after a debounce window only when
  the layout's internal name matches the target filename stem. Writes are
  atomic (tmp + rename). Before returning it calls
  ``LayoutState.mark_self_write`` so the watcher on the other thread
  does not interpret the new mtime as an external edit.
- :class:`LayoutFileWatcher` polls the file's mtime every 100 ms and
  triggers ``LayoutState.mutate(lambda _: new_layout)`` when a valid
  external edit is detected. Invalid JSON or schema violations are
  logged and ignored (the current in-memory state stays authoritative).

Self-write detection: mtime-based, 2 s tolerance window. The autosaver
records its write's mtime via ``LayoutState.mark_self_write``; the
watcher asks ``LayoutState.is_self_write`` before reloading.

mtime polling was chosen over ``inotify_simple`` per the parent plan
rationale: the layout file is small, 100 ms polling is cheap, and the
dependency addition is avoided. Swap in real inotify in a follow-up if
latency becomes a concern.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path

from agents.studio_compositor.layout_state import LayoutState
from shared.compositor_model import Layout

log = logging.getLogger(__name__)


class LayoutAutoSaver:
    """Debounce LayoutState mutations and write to disk atomically."""

    def __init__(
        self,
        state: LayoutState,
        path: Path,
        debounce_s: float = 0.5,
    ) -> None:
        self._state = state
        self._path = Path(path)
        self._debounce_s = max(0.01, debounce_s)
        self._lock = threading.Lock()
        self._last_mutation_at: float = 0.0
        self._pending = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._state.subscribe(self._on_mutation)
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name="compositor-autosave",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def flush_now(self) -> None:
        """Skip the debounce and write the current state immediately."""
        with self._lock:
            self._pending = False
        self._write()

    def _on_mutation(self, _layout: Layout) -> None:
        with self._lock:
            self._last_mutation_at = time.monotonic()
            self._pending = True

    def _loop(self) -> None:
        poll_interval = max(0.005, self._debounce_s / 2)
        while not self._stop.is_set():
            self._stop.wait(poll_interval)
            if self._stop.is_set():
                return
            with self._lock:
                if not self._pending:
                    continue
                if time.monotonic() - self._last_mutation_at < self._debounce_s:
                    continue
                self._pending = False
            self._write()

    def _write(self) -> None:
        layout = self._state.get()
        expected_name = self._path.stem
        if expected_name and layout.name != expected_name:
            log.warning(
                "LayoutAutoSaver refusing to write layout %r to %s; filename stem is %r",
                layout.name,
                self._path,
                expected_name,
            )
            return
        dump = json.dumps(layout.model_dump(), indent=2)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp_fd, tmp_name = tempfile.mkstemp(
                prefix=".default.json.tmp-",
                dir=str(self._path.parent),
            )
        except Exception:
            log.exception("LayoutAutoSaver temp file allocation failed")
            return
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(dump)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            log.exception("LayoutAutoSaver write failed")
            return
        try:
            os.replace(tmp_name, self._path)
        except OSError:
            log.exception("LayoutAutoSaver atomic rename failed")
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            return
        try:
            self._state.mark_self_write(self._path.stat().st_mtime)
        except OSError:
            pass


class LayoutFileWatcher:
    """Poll the layout JSON for external edits and hot-reload valid ones."""

    POLL_INTERVAL_S = 0.1

    def __init__(self, state: LayoutState, path: Path) -> None:
        self._state = state
        self._path = Path(path)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_mtime: float = self._path.stat().st_mtime if self._path.exists() else 0.0

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name="compositor-fw",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(self.POLL_INTERVAL_S)
            if self._stop.is_set():
                return
            if not self._path.exists():
                continue
            try:
                mtime = self._path.stat().st_mtime
            except OSError:
                continue
            if mtime == self._last_mtime:
                continue
            if self._state.is_self_write(mtime, tolerance=2.0):
                self._last_mtime = mtime
                continue
            try:
                text = self._path.read_text(encoding="utf-8")
                if not text.strip():
                    log.warning(
                        "LayoutFileWatcher saw empty/in-flight reload of %s; retrying",
                        self._path,
                    )
                    continue
                raw = json.loads(text)
                new_layout = Layout.model_validate(raw)
            except OSError as e:
                log.warning("LayoutFileWatcher read failed for %s: %s", self._path, e)
                self._last_mtime = mtime
                continue
            except (json.JSONDecodeError, ValueError) as e:
                log.warning("LayoutFileWatcher rejected reload of %s: %s", self._path, e)
                self._last_mtime = mtime
                continue

            self._state.mutate(lambda _old: new_layout)
            try:
                self._last_mtime = self._path.stat().st_mtime
            except OSError:
                self._last_mtime = mtime
