#!/usr/bin/env python3
"""Narrowed-salience impingement feed for the cascade ward.

FINDING-V Phase 6 (operator Q2 = "real gap"). The
``ImpingementCascadeCairoSource`` ward already renders fine off
``_active_perceptual_signals`` (perception + stimmung state walks),
but the operator's intent for the cascade is "what just grabbed
Hapax's attention" — a salience-filtered top-N view of the DMN
impingement stream, not the raw perception field.

This daemon tails ``/dev/shm/hapax-dmn/impingements.jsonl`` every 2 s,
selects the last 15 entries with ``strength >= 0.35``, and writes
``/dev/shm/hapax-compositor/recent-impingements.json`` atomically.
The consumer (ward) prefers this file when present and falls back to
``_active_perceptual_signals`` when absent — zero-downtime hedge.

Schema:
    {
      "generated_at": <float>,
      "entries": [
        {"path": <str>, "value": <float 0..1>, "family": <str>,
         "source": <str>, "ts": <float>}
      ]
    }

where ``path`` is the one-line label the ward renders, ``value`` is
the salience bar value, ``family`` is the HomagePackage palette
family for the accent colour, ``source`` is the raw impingement
source for traceability, and ``ts`` is the impingement timestamp.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("recent-impingements-producer")

_IMPINGEMENTS_JSONL = Path("/dev/shm/hapax-dmn/impingements.jsonl")
_OUTPUT_FILE = Path("/dev/shm/hapax-compositor/recent-impingements.json")
_SALIENCE_FLOOR = 0.35
_TOP_N = 15
_POLL_INTERVAL_S = 2.0
# How much tail to read. The jsonl can grow large; 64 KiB is a
# generous window for the last ~200 records.
_TAIL_WINDOW_BYTES = 64 * 1024

_shutdown = False


def _handle_signal(signum, frame):  # noqa: ARG001
    global _shutdown
    _shutdown = True
    log.info("signal %d received, draining", signum)


def _infer_family(source: str) -> str:
    """Infer a palette family from the impingement source.

    Families match ``agents/studio_compositor/hothouse_sources.py::_infer_family``
    so the ward's accent-lookup keeps working identically regardless of
    which backend populated the row.
    """
    s = source.lower()
    if "camera" in s or "gaze" in s or "hand" in s or "face" in s or "perception" in s:
        return "camera.hero"
    if "music" in s or "midi" in s or "beat" in s or "preset" in s:
        return "preset.bias"
    if "chat" in s or "overlay" in s or "keyword" in s:
        return "overlay.emphasis"
    if "youtube" in s or "playlist" in s:
        return "youtube.direction"
    if "attention" in s or "salience" in s or "dmn" in s:
        return "attention.winner"
    if "consent" in s or "stream_mode" in s:
        return "stream_mode.transition"
    if "exploration" in s or "boredom" in s or "curiosity" in s:
        return "attention.winner"
    if "stimmung" in s:
        return "—"
    return "—"


def _label_for_entry(record: dict[str, Any]) -> str:
    """Pick a one-line label for the cascade row.

    Prefer ``content.max_novelty_edge`` (the compact exploration-signal
    tag), else the last component of ``source`` trimmed to 26 chars to
    fit the Px437-13 layout width reserved in the consumer.
    """
    content = record.get("content")
    if isinstance(content, dict):
        edge = content.get("max_novelty_edge")
        if isinstance(edge, str) and edge.strip():
            return edge.strip()[:26]
    source = str(record.get("source") or "—")
    tail = source.rsplit(".", 1)[-1] or source
    return tail[:26]


def _collect_recent() -> list[dict[str, Any]]:
    """Read the jsonl tail; return top-N entries with ``strength >= floor``.

    Returns a list of dicts in the producer schema (see module docstring).
    Empty list when the file is missing, unreadable, or produces no
    entries above the salience floor.
    """
    try:
        if not _IMPINGEMENTS_JSONL.exists():
            return []
        size = _IMPINGEMENTS_JSONL.stat().st_size
        window = min(size, _TAIL_WINDOW_BYTES)
        with _IMPINGEMENTS_JSONL.open("rb") as fh:
            fh.seek(max(0, size - window))
            tail = fh.read().decode("utf-8", errors="ignore")
    except OSError:
        log.debug("impingements.jsonl tail failed", exc_info=True)
        return []

    entries: list[dict[str, Any]] = []
    for line in tail.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        strength = record.get("strength")
        if not isinstance(strength, (int, float)):
            continue
        if strength < _SALIENCE_FLOOR:
            continue
        source = str(record.get("source") or "—")
        entries.append(
            {
                "path": _label_for_entry(record),
                "value": float(max(0.0, min(1.0, strength))),
                "family": _infer_family(source),
                "source": source,
                "ts": float(record.get("timestamp") or 0.0),
            }
        )

    # Keep the newest TOP_N by timestamp descending; the ward renders
    # newest-first so the freshest attention grabs is row 0.
    entries.sort(key=lambda e: e["ts"], reverse=True)
    return entries[:_TOP_N]


def _publish(entries: list[dict[str, Any]]) -> None:
    payload = {"generated_at": time.time(), "entries": entries}
    _OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path_s = tempfile.mkstemp(
        prefix=f".{_OUTPUT_FILE.name}.", suffix=".tmp", dir=str(_OUTPUT_FILE.parent)
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(payload, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path_s, _OUTPUT_FILE)
    except Exception:
        try:
            os.unlink(tmp_path_s)
        except OSError:
            pass
        raise


def main() -> int:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    while not _shutdown:
        try:
            entries = _collect_recent()
            _publish(entries)
        except Exception:
            log.exception("tick failed")

        slept = 0.0
        while slept < _POLL_INTERVAL_S and not _shutdown:
            time.sleep(0.5)
            slept += 0.5

    log.info("shutdown complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
