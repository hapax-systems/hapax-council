"""SegmentRecorder wiring around director-loop iterations.

Cc-task ``director-moves-segment-smoke`` (operator outcome 3 follow-up).
Composes alpha's ``shared.segment_observability.SegmentRecorder`` with the
director-loop's existing ``director-intent.jsonl`` emission so each
iteration window resolves into a ``SegmentEvent`` carrying a
``quality.director_moves`` rating from
``agents.studio_compositor.director_moves_quality``.

Design — read-after-emit assessment:

The director-loop already writes one record per tick to
``director-intent.jsonl`` (rotated; see ``_emit_intent_artifacts``). Rather
than instrumenting every tick site, the recorder snapshots the JSONL
position on entry, lets the iteration body run, and on exit reads back the
records the body produced, scores them, and writes the rating onto the
yielded ``SegmentEvent`` before alpha's ``SegmentRecorder`` emits HAPPENED
or DIDNT_HAPPEN. Quality is assessed regardless of which terminal lifecycle
the segment hits — a crashed iteration that managed to emit some intents
still gets a real director_moves score on the DIDNT_HAPPEN event.

The smoke test driver uses this helper to wrap deterministic micromove
emissions; production wiring will wrap the real director loop's outer
iteration in the same way.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from agents.studio_compositor.director_moves_quality import (
    assess_director_moves_quality,
)
from shared.segment_observability import (
    SegmentEvent,
    SegmentRecorder,
)

# Default location matching agents/studio_compositor/director_loop.py:
# ``_DIRECTOR_INTENT_JSONL`` resolves to ``~/hapax-state/stream-experiment/
# director-intent.jsonl``. Re-imported lazily inside the helper so the
# director-loop module's monkey-patchable module-level path stays the
# single source of truth.

__all__ = ["record_director_segment"]


def _read_records_from_offset(path: Path, byte_offset: int) -> list[dict[str, Any]]:
    """Read JSONL lines from ``byte_offset`` onward and return the parsed dicts.

    Lines that fail JSON decode are skipped silently — the director's JSONL
    rotation could leave a partial-line tail at the file edge during a
    rotation race; quality assessment should not crash on those.
    """

    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            fh.seek(byte_offset)
            for line in fh:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    parsed = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    out.append(parsed)
    except OSError:
        return []
    return out


def _current_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


@contextmanager
def record_director_segment(
    programme_role: str,
    *,
    topic_seed: str | None = None,
    intent_jsonl_path: Path | None = None,
    log_path: Path | None = None,
) -> Iterator[SegmentEvent]:
    """Wrap a director iteration window in a SegmentRecorder + quality scorer.

    Snapshots the byte offset of the director-intent JSONL on entry, yields
    the inner ``SegmentEvent`` for callers to mutate (e.g. to set
    ``event.quality.notes`` or other dimensions), then on exit reads back
    the records produced during the window, scores them, and writes the
    rating onto ``event.quality.director_moves`` before alpha's
    ``SegmentRecorder`` finalises the lifecycle.

    Args:
        programme_role: ``shared.programme.ProgrammeRole`` value as str.
        topic_seed: Optional topic seed; passed through to alpha's
            SegmentRecorder.
        intent_jsonl_path: Override the director-intent JSONL path (test
            fixtures inject a temp path). Defaults to the live director's
            module-level ``_DIRECTOR_INTENT_JSONL``.
        log_path: Override target segments JSONL path; passed through to
            alpha's SegmentRecorder.

    Yields:
        The ``SegmentEvent`` for the in-flight segment. The caller's body
        runs the director iteration; the helper handles offset capture,
        record read-back, and rating assignment automatically.
    """

    if intent_jsonl_path is None:
        # Lazy import keeps the smoke test independent of live director
        # state — the director_loop module is only imported when no
        # explicit path is supplied.
        from agents.studio_compositor.director_loop import _DIRECTOR_INTENT_JSONL

        intent_jsonl_path = _DIRECTOR_INTENT_JSONL

    start_offset = _current_size(intent_jsonl_path)

    with SegmentRecorder(
        programme_role=programme_role,
        topic_seed=topic_seed,
        log_path=log_path,
    ) as event:
        try:
            yield event
        finally:
            # Score regardless of clean exit vs exception so DIDNT_HAPPEN
            # events also carry a director_moves rating reflecting whatever
            # the loop did manage to emit before crashing. The SegmentRecorder
            # handles the actual lifecycle transition + final emit.
            records = _read_records_from_offset(intent_jsonl_path, start_offset)
            event.quality.director_moves = assess_director_moves_quality(records)
