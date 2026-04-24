"""Consume broadcast-orchestrator events and emit cuepoints.

The orchestrator writes one ``broadcast_rotated`` event per ~11h
rotation; each rotation is a natural segment-boundary chapter. We
debounce so back-to-back events in a sync-fail-and-retry storm do not
flood the API with redundant cuepoints.

Uses an inline JSONL tailer with a persistent cursor — deliberately
not ``shared.impingement_consumer.ImpingementConsumer`` because that
validates against the ``Impingement`` schema and broadcast events are
a different shape. A restart resumes from the saved cursor so prior
rotations do not re-emit.

Programme-boundary cuepoints are deferred to a follow-up because the
programme_manager currently emits only Prometheus counters, not a
JSONL surface. See ytb-004 implementation notes for the deferred path.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shared.youtube_api_client import YouTubeApiClient

from .api import emit_cuepoint

log = logging.getLogger(__name__)

EVENT_PATH = Path(
    os.environ.get("HAPAX_BROADCAST_EVENT_PATH", "/dev/shm/hapax-broadcast/events.jsonl")
)
CURSOR_PATH = Path(
    os.environ.get(
        "HAPAX_LIVE_CUEPOINTS_CURSOR",
        str(Path.home() / ".cache/hapax/live-cuepoints-cursor.txt"),
    )
)
DEBOUNCE_S = float(os.environ.get("HAPAX_CUEPOINT_DEBOUNCE_S", "90"))
MAX_PER_HOUR = int(os.environ.get("HAPAX_CUEPOINT_MAX_PER_HOUR", "60"))


try:
    from prometheus_client import Counter, Histogram

    _EMITTED_TOTAL = Counter(
        "hapax_broadcast_cuepoints_emitted_total",
        "Cuepoints emitted, broken down by outcome and originating event source.",
        ["result", "source"],
    )
    _EMIT_DURATION = Histogram(
        "hapax_broadcast_cuepoint_emit_duration_s",
        "Latency of a single cuepoint API call.",
    )

    def _record_emit(result: str, source: str) -> None:
        _EMITTED_TOTAL.labels(result=result, source=source).inc()

    def _record_duration(secs: float) -> None:
        _EMIT_DURATION.observe(secs)
except ImportError:

    def _record_emit(result: str, source: str) -> None:
        log.debug("prometheus unavailable; skipping metric")

    def _record_duration(secs: float) -> None:
        pass


@dataclass
class _RateWindow:
    """Sliding-window counter to enforce MAX_PER_HOUR."""

    emits: list[float]

    def allow(self, now: float, max_per_hour: int) -> bool:
        cutoff = now - 3600.0
        self.emits = [t for t in self.emits if t >= cutoff]
        return len(self.emits) < max_per_hour

    def record(self, now: float) -> None:
        self.emits.append(now)


class _JsonlTailer:
    """Minimal line-cursor JSONL reader with persistent cursor.

    On first run (cursor file missing), seeks to end-of-file so prior
    rotations don't re-emit. Thereafter, the cursor is persisted atomically
    via tmp+rename after each successful read.
    """

    def __init__(self, path: Path, cursor_path: Path) -> None:
        self._path = path
        self._cursor_path = cursor_path
        self._cursor = self._load_cursor()

    def _load_cursor(self) -> int:
        if not self._cursor_path.exists():
            # First startup: skip existing lines.
            existing = self._line_count()
            self._write_cursor(existing)
            return existing
        try:
            return int(self._cursor_path.read_text().strip() or "0")
        except (ValueError, OSError) as exc:
            log.warning("cursor parse failed (%s); seeking to end", exc)
            existing = self._line_count()
            self._write_cursor(existing)
            return existing

    def _line_count(self) -> int:
        if not self._path.exists():
            return 0
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                return sum(1 for _ in fh)
        except OSError:
            return 0

    def _write_cursor(self, value: int) -> None:
        tmp = self._cursor_path.with_suffix(self._cursor_path.suffix + ".tmp")
        self._cursor_path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(str(value))
        tmp.replace(self._cursor_path)

    def read_new(self) -> list[dict[str, Any]]:
        """Return new records since last call. Tolerates malformed lines."""
        if not self._path.exists():
            return []
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                lines = fh.readlines()
        except OSError:
            return []

        if len(lines) < self._cursor:
            log.warning(
                "event file shrank from %d to %d lines; resetting cursor",
                self._cursor,
                len(lines),
            )
            self._cursor = len(lines)
            self._write_cursor(self._cursor)
            return []

        new = lines[self._cursor :]
        if not new:
            return []

        self._cursor = len(lines)
        self._write_cursor(self._cursor)

        out: list[dict[str, Any]] = []
        for raw in new:
            raw = raw.strip()
            if not raw:
                continue
            try:
                out.append(json.loads(raw))
            except json.JSONDecodeError:
                log.warning("malformed event line: %r", raw[:200])
        return out


class CuepointConsumer:
    """Tail broadcast events and emit cuepoints on chapter-worthy items.

    Persistent cursor so a restart doesn't re-emit every prior rotation.
    Debounce so the API never sees two cuepoints within ``debounce_s``.
    """

    def __init__(
        self,
        client: YouTubeApiClient,
        *,
        event_path: Path = EVENT_PATH,
        cursor_path: Path = CURSOR_PATH,
        debounce_s: float = DEBOUNCE_S,
        max_per_hour: int = MAX_PER_HOUR,
        time_fn: Any = time.time,
    ) -> None:
        self._client = client
        self._debounce_s = debounce_s
        self._max_per_hour = max_per_hour
        self._time = time_fn
        self._last_emit_ts: float = 0.0
        self._rate_window = _RateWindow(emits=[])
        self._tailer = _JsonlTailer(event_path, cursor_path)

    def poll_once(self) -> int:
        """Read one batch of new events and emit cuepoints for chapter-worthy ones.

        Returns the number of cuepoints successfully emitted.
        """
        emitted = 0
        for event in self._tailer.read_new():
            if _is_chapter_worthy(event):
                if self._maybe_emit(event):
                    emitted += 1
        return emitted

    def _maybe_emit(self, event: dict[str, Any]) -> bool:
        now = self._time()
        source = event.get("event_type", "unknown")
        broadcast_id = event.get("incoming_broadcast_id") or event.get("active_broadcast_id")
        if not broadcast_id:
            log.warning("chapter-worthy event without broadcast id: %s", event)
            _record_emit("missing_broadcast_id", source)
            return False

        if now - self._last_emit_ts < self._debounce_s:
            log.debug("debounced cuepoint (last emit %.1fs ago)", now - self._last_emit_ts)
            _record_emit("debounced", source)
            return False

        if not self._rate_window.allow(now, self._max_per_hour):
            log.warning("cuepoint rate cap %d/h hit; skipping", self._max_per_hour)
            _record_emit("rate_capped", source)
            return False

        started = self._time()
        resp = emit_cuepoint(self._client, broadcast_id=broadcast_id)
        _record_duration(self._time() - started)

        if resp is None:
            _record_emit("api_skip", source)
            return False

        self._last_emit_ts = now
        self._rate_window.record(now)
        _record_emit("ok", source)
        log.info("cuepoint emitted: broadcast=%s source=%s", broadcast_id, source)
        return True


def _is_chapter_worthy(event: dict[str, Any]) -> bool:
    """Return True when the event should fire a cuepoint.

    Today: ``broadcast_rotated`` only. Future: programme-boundary events
    once programme_manager gains a JSONL surface (deferred — see ytb-004
    impl notes).
    """
    return event.get("event_type") == "broadcast_rotated"


def iter_events(path: Path = EVENT_PATH) -> Iterator[dict[str, Any]]:
    """Iterate all parseable events in the file. Used by the ``--once`` CLI
    to cherry-pick the most-recent rotation for manual test.
    """
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                yield json.loads(raw)
            except json.JSONDecodeError:
                continue
