"""logos/engine/watcher.py — Watchdog-based recursive filesystem monitoring.

Uses asyncio.Queue as thread-to-async bridge. Watchdog handler puts events
on a thread-safe queue; a consumer coroutine reads and calls the callback.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path

from watchdog.events import (
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

from logos._frontmatter import parse_frontmatter
from logos.engine.models import ChangeEvent

_log = logging.getLogger(__name__)

# Path-based doc_type inference for non-markdown files
_PATH_DOC_TYPES: dict[str, str] = {
    "health-history.jsonl": "health-event",
    "sdlc-events.jsonl": "sdlc-event",
    "drift-report.json": "drift-report",
    "scout-report.json": "scout-report",
    "operator-profile.json": "operator-profile",
}

# Directory-based patterns for axiom files
_DIR_DOC_TYPES: list[tuple[str, str, str]] = [
    ("axioms", "implications", "axiom-implication"),
    ("axioms", "precedents", "axiom-precedent"),
]

_EVENT_TYPE_MAP: dict[type, str] = {
    FileCreatedEvent: "created",
    FileModifiedEvent: "modified",
    FileDeletedEvent: "deleted",
    FileMovedEvent: "moved",
}


def _infer_doc_type(path: Path) -> tuple[str | None, dict | None]:
    """Infer doc_type from frontmatter or path patterns.

    Returns (doc_type, frontmatter_dict).
    """
    # Try frontmatter for markdown files
    if path.suffix == ".md" and path.exists():
        fm, _ = parse_frontmatter(path)
        if fm:
            return fm.get("doc_type"), fm

    # Path-based inference for known filenames
    for filename, dtype in _PATH_DOC_TYPES.items():
        if path.name == filename:
            return dtype, None

    # Directory-based inference for axiom files
    parts = path.parts
    for parent_dir, sub_dir, dtype in _DIR_DOC_TYPES:
        if parent_dir in parts and sub_dir in parts:
            return dtype, None

    return None, None


def _should_skip(path: Path) -> bool:
    """Filter out dotfiles and processed/ directories."""
    parts = path.parts
    for part in parts:
        if part.startswith("."):
            return True
        if part == "processed":
            return True
    return False


class _EventHandler(FileSystemEventHandler):
    """Watchdog handler that puts events onto an asyncio-safe queue."""

    def __init__(self, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__()
        self._queue = queue
        self._loop = loop

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        event_type = _EVENT_TYPE_MAP.get(type(event))
        if event_type is None:
            return
        self._loop.call_soon_threadsafe(self._queue.put_nowait, (event.src_path, event_type))


class DirectoryWatcher:
    """Recursive directory watcher with debounce and self-trigger prevention."""

    def __init__(
        self,
        watch_paths: list[Path],
        callback: Callable[[ChangeEvent], Awaitable[None]],
        debounce_ms: int = 500,
        loop: asyncio.AbstractEventLoop | None = None,
        data_dir: Path | None = None,
    ) -> None:
        self._watch_paths = watch_paths
        self._callback = callback
        self._debounce_s = debounce_ms / 1000.0
        self._loop = loop
        self._data_dir = data_dir

        # Debounce state
        self._lock = threading.Lock()
        self._pending: dict[Path, tuple[str, datetime]] = {}
        self._timers: dict[Path, threading.Timer] = {}

        # Self-trigger prevention
        self._own_writes: set[Path] = set()
        self._own_write_timers: dict[Path, threading.Timer] = {}

        # Runtime
        self._queue: asyncio.Queue | None = None
        self._consumer_task: asyncio.Task | None = None
        self._observer: Observer | PollingObserver | None = None
        self._handler: _EventHandler | None = None

    def _create_observer(self) -> Observer | PollingObserver:
        if os.environ.get("ENGINE_POLLING_OBSERVER") == "1":
            return PollingObserver()
        return Observer()

    async def start(self) -> None:
        """Start watching directories and consuming events."""
        if self._loop is None:
            self._loop = asyncio.get_running_loop()

        self._queue = asyncio.Queue()
        self._handler = _EventHandler(self._queue, self._loop)
        self._observer = self._create_observer()

        for path in self._watch_paths:
            if path.exists():
                self._observer.schedule(self._handler, str(path), recursive=True)
                _log.info("Watching: %s", path)
            else:
                _log.warning("Watch path does not exist, skipping: %s", path)

        self._observer.start()
        self._consumer_task = asyncio.create_task(self._consume())

    async def _consume(self) -> None:
        """Read events from the queue and debounce them."""
        if self._queue is None:
            raise RuntimeError("Watcher not started")
        while True:
            try:
                src_path, event_type = await self._queue.get()
                path = Path(src_path)

                if _should_skip(path):
                    continue

                with self._lock:
                    if path in self._own_writes:
                        self._own_writes.discard(path)
                        _log.debug("Ignored own-write: %s", path)
                        continue

                self._debounce(path, event_type)
            except asyncio.CancelledError:
                return
            except (OSError, FileNotFoundError, ValueError):
                _log.exception("Error in watcher consumer")

    def _debounce(self, path: Path, event_type: str) -> None:
        """Collapse multiple events on the same path within the debounce window."""
        with self._lock:
            if path not in self._pending:
                self._pending[path] = (event_type, datetime.now())

            # Cancel existing timer
            if path in self._timers:
                self._timers[path].cancel()

            # Set new timer
            timer = threading.Timer(self._debounce_s, self._fire, args=[path])
            self._timers[path] = timer
            timer.start()

    def _fire(self, path: Path) -> None:
        """Fire the callback after debounce window expires."""
        with self._lock:
            pending = self._pending.pop(path, None)
            self._timers.pop(path, None)

        if pending is None:
            return

        event_type, timestamp = pending
        doc_type, frontmatter = _infer_doc_type(path)

        event = ChangeEvent(
            path=path,
            event_type=event_type,
            doc_type=doc_type,
            frontmatter=frontmatter,
            timestamp=timestamp,
            data_dir=self._data_dir,
        )

        if self._loop is not None and self._loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(self._callback(event), self._loop)
            except RuntimeError:
                _log.debug("Loop stopped before event could be dispatched: %s", path)

    def ignore_fn(self, path: Path) -> None:
        """Register a path as an own-write to prevent self-triggering.

        One-shot: consumed on first matching event. Auto-clears after 2x debounce window.
        """
        with self._lock:
            self._own_writes.add(path)

            # Auto-clear timer at 2x debounce window
            if path in self._own_write_timers:
                self._own_write_timers[path].cancel()

            timer = threading.Timer(self._debounce_s * 2, self._clear_own_write, args=[path])
            self._own_write_timers[path] = timer
            timer.start()

    def _clear_own_write(self, path: Path) -> None:
        """Remove an own-write entry after timeout."""
        with self._lock:
            self._own_writes.discard(path)
            self._own_write_timers.pop(path, None)

    async def stop(self) -> None:
        """Stop watching and clean up all timers."""
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None

        # Cancel all debounce timers
        for timer in self._timers.values():
            timer.cancel()
        self._timers.clear()
        self._pending.clear()

        # Cancel all own-write timers
        for timer in self._own_write_timers.values():
            timer.cancel()
        self._own_write_timers.clear()
        self._own_writes.clear()

        # Cancel consumer task
        if self._consumer_task is not None:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
            self._consumer_task = None

        _log.info("Watcher stopped")
