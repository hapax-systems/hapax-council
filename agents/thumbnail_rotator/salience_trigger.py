"""Chronicle-salience trigger for thumbnail rotation (ytb-003 Phase 2).

Replaces the Phase 1 fixed-30-min cadence with event-driven capture
on chronicle high-salience events. The capture rule:

  Trigger when:
    payload.salience >= SALIENCE_THRESHOLD (default 0.7)
    AND no high-salience event landed in the prior STABILITY_WINDOW_S
        (default 120 s)

The first clause picks moments the chronicle has already labeled as
worth attention. The second prevents thumbnail thrash during a flurry
of high-salience events: the operator's concept of "chapter stability"
means we wait until the chronicle has settled into the new visual
register before lifting the frame.

The trigger reads from ``/dev/shm/hapax-chronicle/events.jsonl`` via
``shared.impingement_consumer.ImpingementConsumer``. Cursor is
persisted at ``~/.cache/hapax/thumbnail-rotator-chronicle-cursor.txt``
so a restart resumes from where the last tick left off rather than
re-firing on backlog.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

log = logging.getLogger(__name__)

CHRONICLE_EVENTS_PATH = Path(
    os.environ.get(
        "HAPAX_CHRONICLE_EVENTS_PATH",
        "/dev/shm/hapax-chronicle/events.jsonl",
    )
)
DEFAULT_CURSOR_PATH = Path(
    os.environ.get(
        "HAPAX_THUMBNAIL_SALIENCE_CURSOR",
        str(Path.home() / ".cache/hapax/thumbnail-rotator-chronicle-cursor.txt"),
    )
)

SALIENCE_THRESHOLD: float = float(os.environ.get("HAPAX_THUMBNAIL_SALIENCE_THRESHOLD", "0.7"))
STABILITY_WINDOW_S: float = float(os.environ.get("HAPAX_THUMBNAIL_STABILITY_WINDOW_S", "120"))


class SalienceTrigger:
    """Chronicle-salience-based rotation trigger.

    Constructor parameters
    ----------------------
    events_path:
        JSONL chronicle stream path. Defaults to
        ``/dev/shm/hapax-chronicle/events.jsonl``.
    cursor_path:
        Persistence path for the chronicle byte-offset cursor. ``None``
        disables persistence (tests).
    salience_threshold:
        Minimum payload.salience to count as a high-salience event.
    stability_window_s:
        Quiet period after the last high-salience event before the
        trigger fires. Implements the "chapter stability" gate so a
        flurry of high-salience events doesn't churn thumbnails.
    clock:
        ``() -> float`` returning monotonic seconds. Tests inject a
        controllable clock; production uses ``time.monotonic``.

    The trigger is single-fire: once it fires, the next firing
    requires another high-salience event followed by a fresh
    stability window. Multiple high-salience events without an
    intervening fire collapse to a single eventual trigger.
    """

    def __init__(
        self,
        *,
        events_path: Path = CHRONICLE_EVENTS_PATH,
        cursor_path: Path | None = DEFAULT_CURSOR_PATH,
        salience_threshold: float = SALIENCE_THRESHOLD,
        stability_window_s: float = STABILITY_WINDOW_S,
        clock=None,
    ) -> None:
        self._events_path = events_path
        self._cursor_path = cursor_path
        self._salience_threshold = salience_threshold
        self._stability_window_s = stability_window_s
        self._clock = clock or time.monotonic
        # Time (monotonic) of the most recent high-salience event we've
        # observed. None until the first one lands; reset to None after
        # the trigger fires so a fresh quiet period must accumulate.
        self._last_high_salience_t: float | None = None
        # Bootstrap the cursor from disk (or seek-to-end on first run).
        self._cursor: int = self._bootstrap_cursor()

    def should_fire(self) -> bool:
        """Drain new chronicle events; return True iff the trigger fires.

        Always reads to end of stream so the cursor advances each tick.
        Skip-on-fire semantics: once True is returned, subsequent
        ticks return False until both (a) a new high-salience event
        lands AND (b) the stability window passes since that event.

        Never raises — file errors / malformed lines log and return
        False so the caller treats this as "no trigger this tick".
        """
        for event in self._drain_events():
            payload = event.get("payload") or {}
            try:
                salience = float(payload.get("salience", 0.0))
            except (TypeError, ValueError):
                continue
            if salience < self._salience_threshold:
                continue
            self._last_high_salience_t = self._clock()

        if self._last_high_salience_t is None:
            return False

        elapsed = self._clock() - self._last_high_salience_t
        if elapsed < self._stability_window_s:
            return False

        # Fire and arm for the next event-then-quiet cycle.
        self._last_high_salience_t = None
        return True

    # ── Internal: chronicle stream cursor ──────────────────────────────

    def _bootstrap_cursor(self) -> int:
        """Load cursor from disk; on first ever startup, seek to end."""
        if self._cursor_path is None:
            return self._end_of_file()
        if self._cursor_path.exists():
            try:
                return int(self._cursor_path.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                log.warning(
                    "salience cursor at %s unreadable; seeking to end",
                    self._cursor_path,
                    exc_info=True,
                )
        end = self._end_of_file()
        self._write_cursor(end)
        return end

    def _end_of_file(self) -> int:
        try:
            return self._events_path.stat().st_size
        except OSError:
            return 0

    def _write_cursor(self, byte_offset: int) -> None:
        if self._cursor_path is None:
            return
        try:
            self._cursor_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._cursor_path.with_suffix(".tmp")
            tmp.write_text(str(byte_offset), encoding="utf-8")
            tmp.replace(self._cursor_path)
        except OSError:
            log.warning("salience cursor write failed at %s", self._cursor_path, exc_info=True)

    def _drain_events(self):
        """Yield chronicle events between the cursor and end-of-file."""
        if not self._events_path.exists():
            return
        try:
            with self._events_path.open("rb") as fh:
                fh.seek(self._cursor)
                for raw in fh:
                    self._cursor += len(raw)
                    text = raw.decode("utf-8", errors="replace").strip()
                    if not text:
                        continue
                    try:
                        yield json.loads(text)
                    except json.JSONDecodeError:
                        log.debug("malformed chronicle line at %d", self._cursor)
                        continue
        except OSError:
            log.warning("chronicle read failed at %s", self._events_path, exc_info=True)
            return
        self._write_cursor(self._cursor)


__all__ = [
    "DEFAULT_CURSOR_PATH",
    "SALIENCE_THRESHOLD",
    "STABILITY_WINDOW_S",
    "SalienceTrigger",
]
