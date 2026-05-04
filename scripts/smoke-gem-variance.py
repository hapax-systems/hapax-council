#!/usr/bin/env python3
"""End-to-end smoke for outcome 1 vocal substance — gem-frames variance scoring.

Companion to ``scripts/smoke-vocal-segment.py`` (PR #2475). That harness
checks the *cadence* dimension of vocal-as-fuck (TTS frequency on
target). This one checks the *substance* dimension: are the gem-frames
varied, or is Hapax saying the same thing over and over?

Reads append-only ``~/hapax-state/gem-frames.jsonl`` (written by
:mod:`shared.gem_frame_log` from the gem_producer emission point),
applies :func:`shared.gem_frame_variance.score_variance`, wraps the
window in :class:`shared.segment_observability.SegmentRecorder`, and
emits the resulting ``QualityRating`` on ``event.quality.vocal``. The
other four outcome dimensions stay UNMEASURED — this script measures
substance only; cadence is measured separately by the sibling smoke.

Usage::

    uv run python scripts/smoke-gem-variance.py
    uv run python scripts/smoke-gem-variance.py --window-s 1800
    HAPAX_GEM_FRAMES_LOG=/tmp/gems.jsonl uv run python scripts/smoke-gem-variance.py
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from shared.gem_frame_log import flatten_frame_texts, read_recent_gem_frames
from shared.gem_frame_variance import VarianceReport, score_variance
from shared.segment_observability import (
    QualityRating,
    SegmentRecorder,
)

DEFAULT_WINDOW_S = 600.0
DEFAULT_PROGRAMME_ROLE_FALLBACK = "ambient"


@dataclass(frozen=True)
class SmokeResult:
    """Pure-function output: rating + a one-line note for the operator."""

    rating: QualityRating
    note: str


def _resolve_programme_role(records: list[dict]) -> str:
    """Best-effort programme role from the most recent record."""
    for rec in reversed(records):
        role = rec.get("programme_role")
        if isinstance(role, str) and role.strip():
            return role
    return DEFAULT_PROGRAMME_ROLE_FALLBACK


def assess(report: VarianceReport, n_records: int) -> SmokeResult:
    """Build the operator-facing rating + note from a VarianceReport.

    Pure function; tested separately so the boundary mapping is
    explicit and independent of the I/O paths.
    """
    note = f"{report.note} n_records={n_records}"
    return SmokeResult(rating=report.rating, note=note)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gem-variance smoke test")
    parser.add_argument(
        "--window-s",
        type=float,
        default=DEFAULT_WINDOW_S,
        help="window of gem-emission records to score (default 600s)",
    )
    parser.add_argument(
        "--topic-seed",
        type=str,
        default=None,
        help="optional topic seed to record on the segment event",
    )
    args = parser.parse_args(argv)

    records = read_recent_gem_frames(window_s=args.window_s)
    texts = flatten_frame_texts(records)
    variance_report = score_variance(texts)
    role = _resolve_programme_role(records)
    result = assess(variance_report, n_records=len(records))

    with SegmentRecorder(programme_role=role, topic_seed=args.topic_seed) as event:
        event.quality.vocal = result.rating
        event.quality.notes = result.note

    print(f"vocal_quality={result.rating.value} note={result.note!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
