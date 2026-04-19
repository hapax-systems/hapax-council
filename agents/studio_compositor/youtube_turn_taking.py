"""YouTube turn-taking gate — director-driven single-slot enablement.

HOMAGE Phase D2 (plan: docs/superpowers/plans/2026-04-19-homage-completion-plan.md).

Operator directive: only one YouTube video plays at a time on the livestream
surface. The gate reads the director's compositional-impingement stream from
``~/hapax-state/stream-experiment/director-intent.jsonl`` and answers, for a
given tick, whether YouTube content is director-nominated — if so, which
slot is the nominated one.

The contract:

- The gate consumes :class:`DirectorIntent` records. Each ``compositional_impingements``
  entry carries ``intent_family``; records with ``intent_family="youtube.direction"``
  nominate the YouTube surface for this window.
- If no ``youtube.direction`` record appears in the tail-window, the gate
  reports ``enabled=False`` with reason ``no-nomination``. This is the
  fail-closed default — per operator governance (memory
  ``feedback_no_expert_system_rules.md``), behaviour emerges from recruitment;
  director absence is director silence, which should hide the video.
- If the most recent nomination record's narrative contains ``cut-away``
  semantics (checked loosely against the narrative string), the gate reports
  ``enabled=False`` with reason ``cut-away``. Otherwise ``enabled=True``.
- Active-slot selection is retained from the existing director_loop.py
  ``_active_slot`` field, which is mutated by ``_honor_youtube_direction``
  on the ``advance-queue``/``cut-to`` dispatches. The gate surfaces this
  value only as advisory context; it does not own slot rotation itself.

This module is consumed by:

- ``agents/studio_compositor/sierpinski_renderer.py`` —
  :class:`SierpinskiCairoSource.render_content` skips all non-active slot
  draws when ``enabled=False``; ``active_slot`` continues to own opacity.
- ``agents/studio_compositor/audio_control.py`` — :class:`SlotAudioControl`
  mutes all slots when ``enabled=False`` (no active audio).

The gate never writes, never invokes an LLM, never starts/stops ffmpeg
processes. It is a pure read function over the director-intent JSONL tail.
Tick latency: ~1 ms on a 5 MB JSONL (file shrinks via rotation at that
threshold, so tail-read is bounded).
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


# Path mirrors ``director_loop._DIRECTOR_INTENT_JSONL``. Kept duplicated so
# the gate has zero dependency on director_loop (which imports a lot of
# LLM/compositor machinery); the path is a stable artifact location.
DIRECTOR_INTENT_JSONL: Path = Path(
    os.path.expanduser("~/hapax-state/stream-experiment/director-intent.jsonl")
)

# Tail window: consider only records emitted in the last N seconds. Default
# 90 s covers the slow structural cadence + buffer. Older nominations are
# treated as stale (the director has moved on).
DEFAULT_TAIL_WINDOW_S: float = 90.0

# How many final lines to read from the JSONL. 64 is comfortably more than
# three structural ticks; anything older than that is either rotated or
# stale per ``DEFAULT_TAIL_WINDOW_S``.
_MAX_TAIL_LINES: int = 64

# Loose cut-away cues — if the most recent nomination's narrative contains
# any of these substrings (case-insensitive), the gate reports disabled.
# This is intentionally minimal: the pipeline dispatcher
# (``dispatch_youtube_direction``) is the authoritative cut-away source;
# the gate surfaces cut-away signals in the narrative only so an inert
# pipeline (affordance mis-scored) doesn't keep video visible despite a
# director emitting "cut away from the video" language.
_CUT_AWAY_CUES: tuple[str, ...] = (
    "cut away",
    "cut-away",
    "away from the video",
    "away from youtube",
)

YOUTUBE_DIRECTION_FAMILY: str = "youtube.direction"


@dataclass(frozen=True)
class YouTubeGateState:
    """Immutable snapshot of the gate decision for a tick.

    ``enabled`` — if False, callers should suppress YouTube video/audio.
    ``active_slot`` — advisory hint; the gate defers to the director_loop's
    own slot rotator for the authoritative value, reported here as 0 when
    unknown so callers can safely use it as an index.
    ``reason`` — short string for observability; values:

    - ``"no-nomination"`` — no youtube.direction record in tail window
    - ``"cut-away"`` — most recent nomination cues a cut-away
    - ``"director-nominated"`` — enabled by a live nomination
    - ``"jsonl-missing"`` — the director hasn't run yet / file absent
    - ``"read-error"`` — transient IO / decode failure (fails-closed)

    ``last_nomination_ts`` — epoch seconds of the most recent nomination's
    emitted_at, or ``None`` if no nomination was found.
    """

    enabled: bool
    active_slot: int = 0
    reason: str = "no-nomination"
    last_nomination_ts: float | None = None


def _tail_lines(path: Path, limit: int) -> list[str]:
    """Return the last ``limit`` lines from ``path``.

    Uses a windowed read from the end of the file to avoid loading large
    JSONL files fully. Returns ``[]`` on any read error.
    """
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            # Heuristic: 1 KB per record is a generous upper bound; read
            # 128 KB × limit-of-64 only at worst (8 MB). The JSONL rotates
            # at 5 MB so in practice a single tail read suffices.
            read_bytes = min(size, max(4096, 2048 * limit))
            fh.seek(size - read_bytes, os.SEEK_SET)
            raw = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    lines = raw.splitlines()
    return lines[-limit:]


def _record_has_youtube_direction(record: dict) -> bool:
    """True if any ``compositional_impingements`` entry targets YouTube."""
    impingements = record.get("compositional_impingements")
    if not isinstance(impingements, list):
        return False
    for imp in impingements:
        if not isinstance(imp, dict):
            continue
        if imp.get("intent_family") == YOUTUBE_DIRECTION_FAMILY:
            return True
    return False


def _record_cut_away_cue(record: dict) -> bool:
    """True if the YT-targeting impingements' narratives carry cut-away cues."""
    impingements = record.get("compositional_impingements")
    if not isinstance(impingements, list):
        return False
    for imp in impingements:
        if not isinstance(imp, dict):
            continue
        if imp.get("intent_family") != YOUTUBE_DIRECTION_FAMILY:
            continue
        narrative = str(imp.get("narrative") or "").lower()
        if any(cue in narrative for cue in _CUT_AWAY_CUES):
            return True
    return False


def read_gate_state(
    *,
    jsonl_path: Path | None = None,
    now: float | None = None,
    tail_window_s: float = DEFAULT_TAIL_WINDOW_S,
    active_slot: int = 0,
) -> YouTubeGateState:
    """Read the current turn-taking gate state.

    Parameters match the module defaults for production callers; tests pass
    an explicit ``jsonl_path`` and ``now`` for deterministic behaviour.

    Reads the tail of the JSONL, scans backwards for the most recent record
    whose compositional_impingements include a ``youtube.direction`` entry.
    If that record was emitted within ``tail_window_s`` of ``now``, the gate
    is enabled (unless the narrative cues a cut-away). Otherwise disabled.
    """
    path = jsonl_path if jsonl_path is not None else DIRECTOR_INTENT_JSONL
    if not path.exists():
        return YouTubeGateState(
            enabled=False,
            active_slot=active_slot,
            reason="jsonl-missing",
            last_nomination_ts=None,
        )

    lines = _tail_lines(path, _MAX_TAIL_LINES)
    if not lines:
        return YouTubeGateState(
            enabled=False,
            active_slot=active_slot,
            reason="read-error",
            last_nomination_ts=None,
        )

    current = now if now is not None else time.time()
    cutoff = current - tail_window_s

    # Scan newest-first; the most recent nomination wins.
    for line in reversed(lines):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        if not _record_has_youtube_direction(record):
            continue
        emitted_at = record.get("emitted_at")
        try:
            emitted_ts = float(emitted_at) if emitted_at is not None else None
        except (TypeError, ValueError):
            emitted_ts = None
        # Out-of-window nominations are stale — keep scanning in case a
        # newer record later in the tail is in-window, but since we read
        # newest-first, if this one is stale then all earlier ones are
        # equally stale or older.
        if emitted_ts is None or emitted_ts < cutoff:
            return YouTubeGateState(
                enabled=False,
                active_slot=active_slot,
                reason="no-nomination",
                last_nomination_ts=emitted_ts,
            )
        if _record_cut_away_cue(record):
            return YouTubeGateState(
                enabled=False,
                active_slot=active_slot,
                reason="cut-away",
                last_nomination_ts=emitted_ts,
            )
        return YouTubeGateState(
            enabled=True,
            active_slot=active_slot,
            reason="director-nominated",
            last_nomination_ts=emitted_ts,
        )

    return YouTubeGateState(
        enabled=False,
        active_slot=active_slot,
        reason="no-nomination",
        last_nomination_ts=None,
    )


__all__ = [
    "DIRECTOR_INTENT_JSONL",
    "DEFAULT_TAIL_WINDOW_S",
    "YOUTUBE_DIRECTION_FAMILY",
    "YouTubeGateState",
    "read_gate_state",
]
