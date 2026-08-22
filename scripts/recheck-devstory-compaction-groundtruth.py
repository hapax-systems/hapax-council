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
import json
import pathlib
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


def raw_marker_count(path: pathlib.Path) -> int:
    return path.read_bytes().count(b'"isCompactSummary":true')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--negative-sample",
        type=int,
        default=25,
        help="how many marker-free transcripts to sweep for false positives",
    )
    args = ap.parse_args()

    failures: list[str] = []
    checked_any = False

    print("== equality against independently measured ground truth ==")
    for session_id, (want_count, want_positions) in GROUND_TRUTH.items():
        path = find_transcript(session_id)
        if path is None:
            print(f"  {session_id[:8]}  SKIP (transcript not on this host)")
            continue
        checked_any = True
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
            checked_any = True
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
            checked_any = True
            result = parse_session(path, project_path=str(pathlib.Path.home()))
            if len(result.compaction_events) == raw:
                agreed += 1
            else:
                disagreed += 1
                failures.append(f"{path.name}: parsed {len(result.compaction_events)} != raw {raw}")
    print(f"  {agreed} agree, {disagreed} disagree")

    if not checked_any:
        print("\nSKIP: no Claude Code transcripts on this host; nothing to recheck.")
        return 0

    print()
    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("GROUND-TRUTH RECHECK PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
