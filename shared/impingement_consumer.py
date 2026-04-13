"""shared/impingement_consumer.py — Cursor-tracked JSONL impingement reader.

Extracts the duplicated consumer pattern used by Fortress, Daimonion,
and DMN-side Reverie routing into a single reusable utility.

Usage:
    consumer = ImpingementConsumer(Path("/dev/shm/hapax-dmn/impingements.jsonl"))
    for imp in consumer.read_new():
        candidates = pipeline.select(imp)
        # daemon-specific routing

    # For daemons that only care about new impingements after restart
    # (e.g. reverie — stale impingements cannot meaningfully modulate
    # the next visual tick), pass start_at_end=True:
    consumer = ImpingementConsumer(path, start_at_end=True)
"""

from __future__ import annotations

import logging
from pathlib import Path

from shared.impingement import Impingement

log = logging.getLogger(__name__)


class ImpingementConsumer:
    """Cursor-tracked reader for JSONL impingement files.

    Reads new lines since the last call to read_new(), parses them as
    Impingement models, and advances the cursor. Malformed lines are
    skipped with a debug log. OSErrors return empty results without
    advancing the cursor.

    Parameters
    ----------
    path: Path
        JSONL file to read from.
    start_at_end: bool, default False
        If True, initialize the cursor to the current line count so the
        first ``read_new()`` call yields only impingements appended
        after construction. Use for daemons whose restart should skip
        accumulated backlog — a 4000-entry JSONL would otherwise stall
        the first tick for 5–15 min on restart while the affordance
        pipeline round-trips each stale entry through Qdrant. Default
        False preserves the original "read from beginning" behavior for
        crash-resume semantics. See F6 in
        ``docs/superpowers/specs/2026-04-12-reverie-bridge-repair-design.md``.
    """

    def __init__(self, path: Path, *, start_at_end: bool = False) -> None:
        self._path = path
        self._cursor: int = 0
        if start_at_end:
            # Seek to end without processing any existing lines. One file
            # read; if the file does not exist yet, leave cursor at 0 and
            # the next read_new() picks up whatever arrives normally.
            try:
                text = self._path.read_text(encoding="utf-8")
                lines = text.strip().split("\n") if text.strip() else []
                self._cursor = len(lines)
            except OSError:
                log.debug("Failed to seek-to-end on %s", self._path, exc_info=True)

    def read_new(self) -> list[Impingement]:
        """Return new impingements since last read. Non-blocking."""
        if not self._path.exists():
            return []
        try:
            text = self._path.read_text(encoding="utf-8")
            lines = text.strip().split("\n") if text.strip() else []
            new_lines = lines[self._cursor :]
            if not new_lines:
                return []
            self._cursor = len(lines)
            result: list[Impingement] = []
            for line in new_lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    result.append(Impingement.model_validate_json(line))
                except Exception:
                    log.debug("Malformed impingement line skipped: %s", line[:80])
            return result
        except OSError:
            log.debug("Failed to read %s", self._path, exc_info=True)
            return []

    @property
    def cursor(self) -> int:
        """Current line-based offset into the JSONL file."""
        return self._cursor
