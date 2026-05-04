"""Gem-frame append-only log — one record per gem-producer emission.

The compositor reads the *current* gem-frame sequence from
``/dev/shm/hapax-compositor/gem-frames.json`` (overwritten on each
emission). That live file is great for the renderer, useless for
trend analysis: by the time the operator wonders whether Hapax is
saying the same thing over and over, the prior frames are gone.

This module appends a JSONL record at every emission so the rolling
variance scorer (see :mod:`shared.gem_frame_variance`) has a stable
window to score over. Records are append-only, schema-stable, and
the writer is defensive — observability must never break the
emission path.

Default log path: ``~/hapax-state/gem-frames.jsonl``. Env override
``HAPAX_GEM_FRAMES_LOG`` for tests + dev.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


_LOG_LOCK = threading.Lock()


def _default_log_path() -> Path:
    """Resolve the default jsonl path lazily so ``HAPAX_GEM_FRAMES_LOG``
    overrides take effect after import.

    Mirrors :mod:`shared.segment_observability`'s lazy-resolution
    pattern — same operator usability for tests + dev.
    """
    env = os.environ.get("HAPAX_GEM_FRAMES_LOG")
    if env:
        return Path(env)
    return Path.home() / "hapax-state" / "gem-frames.jsonl"


def log_gem_frame(
    *,
    impingement_id: str,
    impingement_source: str,
    frame_texts: Sequence[str],
    programme_role: str | None = None,
    log_path: Path | None = None,
    now: datetime | None = None,
) -> None:
    """Append one gem-emission record to the log.

    Defensive: any I/O failure is swallowed and logged at DEBUG. The
    emission path must keep running even when observability breaks
    (canonical pattern across the daimonion observability layer).

    Parameters
    ----------
    impingement_id
        ID of the impingement that triggered the emission. Lets the
        scorer correlate variance against impingement source / drive
        identity for richer reports.
    impingement_source
        Source string from the impingement (e.g.
        ``endogenous.narrative_drive``, ``operator.sidechat``,
        ``director.composition``). The scorer uses this to bucket
        variance per source.
    frame_texts
        The renderable text payloads of the emitted frames. Empty
        strings are filtered out so the variance scorer doesn't need
        to special-case the placeholder fallback.
    programme_role
        Optional active programme role at emission time. The smoke
        harness uses this to attribute the resulting segment to the
        right programme.
    log_path
        Override target path. Defaults to ``$HAPAX_GEM_FRAMES_LOG``
        or ``~/hapax-state/gem-frames.jsonl``.
    now
        Timestamp override for tests.
    """
    cleaned = [t for t in frame_texts if isinstance(t, str) and t.strip()]
    if not cleaned:
        return
    record: dict[str, Any] = {
        "timestamp": (now or datetime.now(UTC)).isoformat(),
        "impingement_id": impingement_id,
        "impingement_source": impingement_source,
        "frame_texts": cleaned,
        "programme_role": programme_role,
    }
    target = log_path or _default_log_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record) + "\n"
        with _LOG_LOCK, target.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception:
        log.debug("gem-frame log write failed", exc_info=True)


def read_recent_gem_frames(
    *,
    window_s: float = 600.0,
    log_path: Path | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return gem-emission records whose timestamp is within ``window_s``.

    Linear scan from the front — fine at vault scale (the log is
    bounded by emission cadence, ~1-2/min). If the log grows past
    ~50k lines the scorer should switch to seeking from the tail; for
    now keep it simple.

    A missing log file returns an empty list; malformed lines are
    skipped (same defensive posture as the writer).
    """
    target = log_path or _default_log_path()
    if not target.exists():
        return []
    cutoff = (now or datetime.now(UTC)).timestamp() - window_s
    out: list[dict[str, Any]] = []
    try:
        with target.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = rec.get("timestamp")
                if not isinstance(ts, str):
                    continue
                try:
                    ts_epoch = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                except ValueError:
                    continue
                if ts_epoch >= cutoff:
                    out.append(rec)
    except OSError:
        log.debug("gem-frame log read failed", exc_info=True)
        return []
    return out


def flatten_frame_texts(records: Iterable[dict[str, Any]]) -> list[str]:
    """Flatten gem-emission records into a single text-per-frame list.

    Each record contains 1-3 frames. The variance scorer compares
    *frames*, not records, so this helper preserves the within-record
    repetition signal (a record that emits the same text three times
    is more repetitive than three records each with one text).
    """
    out: list[str] = []
    for rec in records:
        texts = rec.get("frame_texts") or ()
        for t in texts:
            if isinstance(t, str) and t.strip():
                out.append(t.strip())
    return out


__all__ = [
    "flatten_frame_texts",
    "log_gem_frame",
    "read_recent_gem_frames",
]
