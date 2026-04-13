"""shared/impingement_consumer.py — Cursor-tracked JSONL impingement reader.

Extracts the duplicated consumer pattern used by Fortress, Daimonion,
and DMN-side Reverie routing into a single reusable utility.

Three bootstrap modes, in increasing order of durability:

1. **Legacy (default):** cursor starts at 0, the first ``read_new()``
   returns every line currently in the file. Preserves original
   semantics for callers and tests that have not opted in.

2. **Skip backlog on restart** — ``start_at_end=True`` (F6, delta PR #702).
   Cursor bootstraps to the current end-of-file; the consumer only sees
   impingements appended after construction. Fixes the 5–15 min
   startup stall caused by re-reading a multi-thousand-entry JSONL on
   every restart. Crash-resume semantics are lost. Correct for daemons
   where stale impingements cannot meaningfully modulate the next tick
   (e.g. reverie visual pipeline).

3. **Persist cursor across restarts** — ``cursor_path=<Path>``. Combines
   the startup-skip property of (2) with crash-resume semantics:

   - First-ever startup (cursor file missing): seek to end, write
     cursor file. Subsequent restarts resume from the saved cursor.
   - Each ``read_new()`` advance atomically persists the new cursor to
     the cursor file via tmp + rename.
   - Corrupt cursor files fall back to seek-to-end with a warning.
   - File shrinkage (rotation or truncation) is detected and resets
     the cursor to the new end-of-file.
   - If ``cursor_path`` is set, it takes precedence — ``start_at_end``
     is ignored, because cursor_path's bootstrap rule is strictly
     stronger (seek-to-end on first run, then persist thereafter).

   Correct for daemons where missing an impingement would be a
   correctness bug (e.g. daimonion voice state, fortress governance).

Usage:
    # Legacy (tests, stateless callers)
    ImpingementConsumer(Path("/dev/shm/hapax-dmn/impingements.jsonl"))

    # Skip-on-restart (reverie visual pipeline)
    ImpingementConsumer(path, start_at_end=True)

    # Persisted cursor (daimonion, fortress)
    ImpingementConsumer(
        path,
        cursor_path=Path.home() / ".cache/hapax/impingement-cursor-daimonion.txt",
    )
"""

from __future__ import annotations

import logging
from pathlib import Path

from shared.impingement import Impingement

__all__ = ["ImpingementConsumer"]

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
        accumulated backlog without persisting state. Ignored when
        ``cursor_path`` is set. See F6 in
        ``docs/superpowers/specs/2026-04-12-reverie-bridge-repair-design.md``.
    cursor_path: Path | None, default None
        If set, persist the cursor to this file after each advance.
        First-ever startup (cursor file missing) seeks to end so the
        accumulated backlog is skipped; subsequent restarts resume
        from the saved cursor for crash-recovery semantics. Corrupt
        cursor files fall back to seek-to-end. File rotation / shrinkage
        is detected and resets the cursor.
    """

    def __init__(
        self,
        path: Path,
        *,
        start_at_end: bool = False,
        cursor_path: Path | None = None,
    ) -> None:
        self._path = path
        self._cursor_path = cursor_path
        self._cursor: int = 0

        if cursor_path is not None:
            self._cursor = self._bootstrap_persisted_cursor()
        elif start_at_end:
            self._cursor = self._line_count()

    def _line_count(self) -> int:
        """Count non-empty lines currently in the impingements file."""
        if not self._path.exists():
            return 0
        try:
            text = self._path.read_text(encoding="utf-8")
        except OSError:
            log.debug("Failed to seek-to-end on %s", self._path, exc_info=True)
            return 0
        stripped = text.strip()
        return len(stripped.split("\n")) if stripped else 0

    def _bootstrap_persisted_cursor(self) -> int:
        """Load persisted cursor, or seek to end of current file."""
        assert self._cursor_path is not None

        if self._cursor_path.exists():
            try:
                text = self._cursor_path.read_text(encoding="utf-8").strip()
                saved = int(text)
                if saved < 0:
                    raise ValueError(f"negative cursor: {saved}")
                return saved
            except (OSError, ValueError) as exc:
                log.warning(
                    "Impingement cursor file %s unreadable (%s) — falling back to end-of-file",
                    self._cursor_path,
                    exc,
                )

        end = self._line_count()
        self._write_cursor(end)
        return end

    def _write_cursor(self, value: int) -> None:
        """Persist cursor atomically (tmp file + rename). No-op if unset."""
        if self._cursor_path is None:
            return
        try:
            self._cursor_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._cursor_path.with_suffix(self._cursor_path.suffix + ".tmp")
            tmp.write_text(str(value), encoding="utf-8")
            tmp.replace(self._cursor_path)
        except OSError:
            log.warning(
                "Failed to persist impingement cursor to %s",
                self._cursor_path,
                exc_info=True,
            )

    def read_new(self) -> list[Impingement]:
        """Return new impingements since last read. Non-blocking."""
        if not self._path.exists():
            return []
        try:
            text = self._path.read_text(encoding="utf-8")
            lines = text.strip().split("\n") if text.strip() else []

            if len(lines) < self._cursor:
                log.warning(
                    "Impingement file %s shrank from %d to %d lines — resetting cursor",
                    self._path,
                    self._cursor,
                    len(lines),
                )
                self._cursor = len(lines)
                self._write_cursor(self._cursor)
                return []

            new_lines = lines[self._cursor :]
            if not new_lines:
                return []
            self._cursor = len(lines)
            self._write_cursor(self._cursor)
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
