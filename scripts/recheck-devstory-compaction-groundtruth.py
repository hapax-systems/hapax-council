#!/usr/bin/env python3
"""Recheck the dev-story compaction discriminator against real transcripts.

The unit tests use synthetic fixtures. This is the load-bearing witness: it runs the
shipped parser over actual Claude Code transcripts on this host and asserts an equality
against independently measured ground truth, plus a negative sweep.

Read-only. Skips cleanly (exit 0) where no transcripts are present, so it is safe in CI
and on hosts without a Claude Code history.

    uv run python scripts/recheck-devstory-compaction-groundtruth.py

Ground truth for the pinned session was established 2026-08-22 by direct inspection of
the transcript (`grep -n '"isCompactSummary":true'`), independently of this parser.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

from agents.dev_story.parser import parse_session

PROJECTS = pathlib.Path.home() / ".claude" / "projects"

# session id -> (compaction event count, 1-indexed record positions)
GROUND_TRUTH: dict[str, tuple[int, list[int]]] = {
    "81e6afab-b1b0-4a9c-abdb-0f1b18bfa04b": (2, [31, 3381]),
}


def find_transcript(session_id: str) -> pathlib.Path | None:
    if not PROJECTS.is_dir():
        return None
    for candidate in PROJECTS.glob(f"*/{session_id}.jsonl"):
        return candidate
    return None


# Whitespace-tolerant: Claude's wire format emits `"isCompactSummary":true`, but any other
# JSON encoder may space the colon. A byte-exact match would silently count zero and make
# the agreement sweep vacuously pass.
_MARKER_RE = re.compile(rb'"isCompactSummary"\s*:\s*true')


def raw_marker_count(path: pathlib.Path) -> int:
    """Count compaction markers on the wire, independently of the parser."""
    return len(_MARKER_RE.findall(path.read_bytes()))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--negative-sample",
        type=int,
        default=25,
        help="how many marker-free transcripts to sweep for false positives",
    )
    ap.add_argument(
        "--allow-missing-groundtruth",
        action="store_true",
        help="exit 0 when no pinned transcript is present. Off by default: absence of the "
        "witness must not read as success.",
    )
    args = ap.parse_args(argv)

    failures: list[str] = []
    # Counted on its own: a negative-sweep or agreement transcript must never make the
    # command look as though it verified the equality assertion.
    groundtruth_checked = 0

    print("== equality against independently measured ground truth ==")
    for session_id, (want_count, want_positions) in GROUND_TRUTH.items():
        path = find_transcript(session_id)
        if path is None:
            print(f"  {session_id[:8]}  SKIP (transcript not on this host)")
            continue
        groundtruth_checked += 1
        result = parse_session(path, project_path=str(pathlib.Path.home()))
        positions = [e.record_position for e in result.compaction_events]
        got = len(result.compaction_events)
        typed = sum(1 for m in result.messages if m.role == "compaction_summary")
        ok = got == want_count and positions == want_positions and typed == want_count
        print(
            f"  {session_id[:8]}  events={got}/{want_count}  "
            f"positions={positions}/{want_positions}  typed={typed}  "
            f"{'PASS' if ok else 'FAIL'}"
        )
        if not ok:
            failures.append(
                f"{session_id}: events={got} positions={positions} typed={typed}; "
                f"expected {want_count} at {want_positions}"
            )

    print("\n== negative sweep: marker-free transcripts must yield no events ==")
    swept = 0
    if PROJECTS.is_dir():
        for path in sorted(PROJECTS.glob("*/*.jsonl")):
            if swept >= args.negative_sample:
                break
            try:
                if raw_marker_count(path) != 0:
                    continue
            except OSError:
                continue
            swept += 1
            result = parse_session(path, project_path=str(pathlib.Path.home()))
            if result.compaction_events:
                failures.append(f"{path.name}: {len(result.compaction_events)} false positives")
    print(f"  {swept - sum(1 for f in failures if 'false positives' in f)}/{swept} clean")

    print("\n== agreement: parsed events == raw marker count, every affected transcript ==")
    agreed = disagreed = 0
    if PROJECTS.is_dir():
        for path in sorted(PROJECTS.glob("*/*.jsonl")):
            try:
                raw = raw_marker_count(path)
            except OSError:
                continue
            if raw == 0:
                continue
            result = parse_session(path, project_path=str(pathlib.Path.home()))
            if len(result.compaction_events) == raw:
                agreed += 1
            else:
                disagreed += 1
                failures.append(f"{path.name}: parsed {len(result.compaction_events)} != raw {raw}")
    print(f"  {agreed} agree, {disagreed} disagree")

    # The equality assertion is the load-bearing half. The sweeps are supporting evidence and
    # must never stand in for it: without a pinned transcript this command has not rechecked
    # anything, and saying PASSED would be the silent-pass it exists to prevent.
    print()
    if groundtruth_checked == 0:
        print("NOT RECHECKED: no pinned ground-truth transcript on this host.")
        print(f"  wanted one of: {', '.join(sorted(GROUND_TRUTH))}")
        print("  The negative and agreement sweeps above cannot substitute for the equality")
        print("  assertion.")
        if args.allow_missing_groundtruth:
            print("  --allow-missing-groundtruth was passed: exiting 0 WITHOUT a witness.")
            return 1 if failures else 0
        # Exit non-zero by default. A caller that treats absence as success must say so
        # explicitly; otherwise CI reads "the witness never ran" as "the witness passed",
        # which is the silent pass this command exists to prevent.
        print("  Next action: run on a host holding a pinned transcript, add one to")
        print("  GROUND_TRUTH, or pass --allow-missing-groundtruth to accept no witness.")
        return 2

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        print("  Next action: if the parser is correct, the pinned expectation is stale —")
        print("  re-measure with: grep -n '\"isCompactSummary\":true' <transcript>")
        print("  and update GROUND_TRUTH. Otherwise the discriminator has regressed.")
        return 1

    print("GROUND-TRUTH RECHECK PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
