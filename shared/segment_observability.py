"""Segment observability — canonical event surface for programme runs.

A *segment* is a programme run. Each segment has a lifecycle (started /
happened / didn't_happen) and per-outcome quality dimensions covering the
five operator outcomes that close the perception → expression loop:

    1. vocal               — hapax_daimonion TTS output
    2. programme_authoring — segmented content / programme generation
    3. director_moves      — studio_compositor director decisions
    4. chat_reactivity     — chat ingestion → impingement bus
    5. chat_response       — chat → hapax response

Operator directive (2026-05-03):
    "I want everyone running massive smoke tests, run through all wiring and
     make sure everything is flowing, with concept of 'this is a segment' +
     'it happened or didn't' + 'happened well or not well'."

This module is the keystone all five outcomes emit segment events to.
Each emission appends a JSON line to ``$HAPAX_SEGMENTS_LOG`` (default:
``~/hapax-state/segments/segments.jsonl``); the per-outcome smoke tests
read the same jsonl back to assert end-to-end flow.

Pure schema + file I/O. No external services. No Prometheus dependency.
Sister modules (Prometheus surfaces) live alongside:
``shared/programme_observability.py`` and ``shared/director_observability.py``.
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field


class SegmentLifecycle(StrEnum):
    """Lifecycle marker for a segment.

    A segment opens with STARTED, then resolves to HAPPENED on a clean
    exit or DIDNT_HAPPEN on exception / abort. Both terminal states are
    emitted; the same ``segment_id`` ties the pair together so consumers
    can stitch start + end without ambiguity.
    """

    STARTED = "started"
    HAPPENED = "happened"
    DIDNT_HAPPEN = "didnt_happen"


class QualityRating(StrEnum):
    """Per-outcome quality assessment for a segment.

    UNMEASURED is the default for any outcome the segment did not exercise
    (most segments only touch a subset of the five outcomes). The rating
    space is intentionally coarse — operator directive frames the bar as
    *"happened well or not well"*, not a numeric score.
    """

    UNMEASURED = "unmeasured"
    POOR = "poor"
    ACCEPTABLE = "acceptable"
    GOOD = "good"
    EXCELLENT = "excellent"


class SegmentQuality(BaseModel):
    """Per-outcome quality for a segment.

    Each field corresponds to one of the five operator outcomes. Default
    is UNMEASURED so segments only need to update the dimensions they
    actually exercised (e.g. a vocal-only smoke test sets ``vocal`` and
    leaves the other four UNMEASURED).
    """

    vocal: QualityRating = QualityRating.UNMEASURED  # outcome 1
    programme_authoring: QualityRating = QualityRating.UNMEASURED  # outcome 2
    director_moves: QualityRating = QualityRating.UNMEASURED  # outcome 3
    chat_reactivity: QualityRating = QualityRating.UNMEASURED  # outcome 4
    chat_response: QualityRating = QualityRating.UNMEASURED  # outcome 5
    notes: str | None = None  # human-readable trace


class SegmentEvent(BaseModel):
    """A single segment-lifecycle event.

    Three of these typically appear per segment in the jsonl: the STARTED
    on entry, then the resolved HAPPENED or DIDNT_HAPPEN on exit. The
    same ``segment_id`` is preserved across all three so consumers can
    fold start + end into one logical segment.

    ``programme_role`` is the ``shared.programme.ProgrammeRole`` value as
    string — kept as a plain str here so this module has no programme
    import dependency (programme imports this, not the other way).
    """

    segment_id: str = Field(default_factory=lambda: str(uuid4()))
    programme_role: str  # ProgrammeRole value (string)
    topic_seed: str | None = None
    lifecycle: SegmentLifecycle = SegmentLifecycle.STARTED
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    ended_at: datetime | None = None
    quality: SegmentQuality = Field(default_factory=SegmentQuality)


def _default_log_path() -> Path:
    """Resolve the default jsonl log path at call time.

    Reads ``HAPAX_SEGMENTS_LOG`` lazily so test fixtures can override the
    env var after import. Falls back to ``~/hapax-state/segments/segments.jsonl``
    — the canonical hapax-state location matching IR perception, attribution,
    and other persistent stream surfaces.
    """

    env = os.environ.get("HAPAX_SEGMENTS_LOG")
    if env:
        return Path(env)
    return Path.home() / "hapax-state" / "segments" / "segments.jsonl"


_LOG_LOCK = threading.Lock()


def emit_segment_event(event: SegmentEvent, log_path: Path | None = None) -> None:
    """Append a segment event to the jsonl log.

    Atomic per-line via a process-wide lock + a single ``f.write`` call;
    POSIX ``write`` of a < ``PIPE_BUF`` byte string is atomic, but the
    lock additionally protects the open/close ordering across threads.
    Creates the parent directory if missing.

    Args:
        event: The ``SegmentEvent`` to persist.
        log_path: Override target path. Defaults to ``$HAPAX_SEGMENTS_LOG``
            or ``~/hapax-state/segments/segments.jsonl``.
    """

    target = log_path or _default_log_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    line = event.model_dump_json() + "\n"
    with _LOG_LOCK:
        with target.open("a", encoding="utf-8") as f:
            f.write(line)


@contextmanager
def SegmentRecorder(  # noqa: N802 — context-manager class-style name is intentional
    programme_role: str,
    topic_seed: str | None = None,
    log_path: Path | None = None,
):
    """Context manager that emits start + end segment events.

    Emits ``SegmentLifecycle.STARTED`` on entry. On clean exit, mutates
    the yielded event to ``HAPPENED`` and emits again. On exception,
    mutates to ``DIDNT_HAPPEN``, emits, and re-raises. The same
    ``segment_id`` is preserved across both events so consumers can pair
    start + end.

    The yielded ``SegmentEvent`` is mutable — callers update
    ``event.quality.vocal``, ``event.quality.notes``, etc. before the
    block exits to record per-outcome quality on the terminal event.

    Args:
        programme_role: ``shared.programme.ProgrammeRole`` value as str.
        topic_seed: Optional topic seed for the programme run.
        log_path: Override target path; falls through to ``emit_segment_event``.

    Yields:
        The ``SegmentEvent`` for the in-flight segment.

    Example:
        >>> with SegmentRecorder("vocal_only", topic_seed="acid bath") as ev:
        ...     # exercise the vocal pipeline
        ...     ev.quality.vocal = QualityRating.GOOD
        ...     ev.quality.notes = "TTS latency 230ms; broadcast clean."
    """

    event = SegmentEvent(programme_role=programme_role, topic_seed=topic_seed)
    emit_segment_event(event, log_path=log_path)
    try:
        yield event
    except BaseException:
        event.lifecycle = SegmentLifecycle.DIDNT_HAPPEN
        event.ended_at = datetime.now(UTC)
        emit_segment_event(event, log_path=log_path)
        raise
    else:
        event.lifecycle = SegmentLifecycle.HAPPENED
        event.ended_at = datetime.now(UTC)
        emit_segment_event(event, log_path=log_path)
