#!/usr/bin/env python3
"""Verify Bachelard Amendment 4 (reverberation → accelerated cadence) is firing live.

Phase 8 of the reverie source registry completion epic. Closes the
adjacent Amendment 4 observational item from the completion epic's
Phase 8 task list.

Background: ``ImaginationLoop._check_reverberation`` compares the last
fragment's narrative against the DMN's current visual observation; when
the similarity score crosses ``REVERBERATION_THRESHOLD`` the cadence
controller accelerates. This is Bachelard Amendment 4 (material quality
reverberating through the imagination loop) shipped in earlier reverie
work. The recovery from BETA-FINDING-2026-04-13-A restored imagination
production; this script confirms the acceleration path is still live
after that recovery.

Behavior: tails ``journalctl --user -u hapax-imagination-loop.service``
for the configured window, greps for the ``Reverberation %.2f`` log
line emitted by ``_check_reverberation``, and exits 0 if at least one
high-reverberation event was observed. Exits 1 with a diagnostic if
none were observed — indicating the amendment is inert and needs
investigation. Exits 2 on journalctl failure.

Usage::

    uv run python scripts/verify_reverberation_cadence.py
    uv run python scripts/verify_reverberation_cadence.py --since "30 min ago"
    uv run python scripts/verify_reverberation_cadence.py --threshold 3
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

REVERB_LINE = re.compile(
    r"Reverberation (?P<score>[0-9]+\.[0-9]+) — visual output surprised imagination"
)
HIGH_THRESHOLD = 0.6  # matches REVERBERATION_THRESHOLD in imagination_loop.py


def tail_journal(service: str, since: str) -> str:
    """Return the journalctl output for the given service and window."""
    cmd = [
        "journalctl",
        "--user",
        "-u",
        service,
        "--since",
        since,
        "-o",
        "short-iso",
        "--no-pager",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"journalctl failed ({result.returncode}): {result.stderr.strip() or result.stdout.strip()}"
        )
    return result.stdout


def count_reverberation_events(log: str, threshold: float) -> tuple[int, int, list[float]]:
    """Return (total_reverberation_events, high_events, scores_list)."""
    total = 0
    high = 0
    scores: list[float] = []
    for match in REVERB_LINE.finditer(log):
        total += 1
        try:
            score = float(match.group("score"))
        except (TypeError, ValueError):
            continue
        scores.append(score)
        if score >= threshold:
            high += 1
    return total, high, scores


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--since",
        default="15 min ago",
        help='journalctl --since window (default: "15 min ago")',
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=HIGH_THRESHOLD,
        help=f"reverberation score threshold (default: {HIGH_THRESHOLD})",
    )
    parser.add_argument(
        "--min-high",
        type=int,
        default=1,
        help="minimum high-reverberation events required (default: 1)",
    )
    parser.add_argument(
        "--service",
        default="hapax-imagination-loop.service",
        help="systemd user service name",
    )
    args = parser.parse_args()

    try:
        log = tail_journal(args.service, args.since)
    except RuntimeError as e:
        print(f"[verify-reverberation] {e}", file=sys.stderr)
        return 2

    total, high, scores = count_reverberation_events(log, args.threshold)
    if scores:
        max_score = max(scores)
        min_score = min(scores)
        avg_score = sum(scores) / len(scores)
    else:
        max_score = min_score = avg_score = 0.0

    print(f"[verify-reverberation] window: {args.since}")
    print(f"[verify-reverberation] service: {args.service}")
    print(f"[verify-reverberation] threshold: {args.threshold:.2f}")
    print(f"[verify-reverberation] total reverberation events: {total}")
    print(f"[verify-reverberation] high-reverberation events: {high}")
    if scores:
        print(
            f"[verify-reverberation] scores: min={min_score:.2f} "
            f"max={max_score:.2f} avg={avg_score:.2f}"
        )

    if high >= args.min_high:
        print(
            f"[verify-reverberation] PASS — {high} high-reverberation event(s) >= {args.min_high}"
        )
        return 0

    print(
        f"[verify-reverberation] FAIL — {high} high-reverberation event(s) "
        f"below minimum {args.min_high}. Amendment 4 may be inert. "
        "Check the imagination loop and visual observation pipeline.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
