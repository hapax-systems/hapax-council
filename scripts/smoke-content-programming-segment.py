#!/usr/bin/env python3
"""Run the content-programming segment smoke and emit programme-authoring quality.

Usage:
    uv run python scripts/smoke-content-programming-segment.py
    uv run python scripts/smoke-content-programming-segment.py --expected-programmes 2
    HAPAX_SEGMENTS_LOG=/tmp/segments.jsonl uv run python scripts/smoke-content-programming-segment.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agents.hapax_daimonion.content_programming_segment_smoke import (
    DEFAULT_EXPECTED_PROGRAMMES,
    run_content_programming_smoke,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Content-programming segment smoke test")
    parser.add_argument("--prep-dir", type=Path, default=None)
    parser.add_argument("--expected-programmes", type=int, default=DEFAULT_EXPECTED_PROGRAMMES)
    parser.add_argument("--topic-seed", type=str, default="content-programming-smoke")
    parser.add_argument("--segment-log", type=Path, default=None)
    args = parser.parse_args(argv)

    result = run_content_programming_smoke(
        prep_dir=args.prep_dir,
        expected_programmes=args.expected_programmes,
        topic_seed=args.topic_seed,
        log_path=args.segment_log,
    )
    assessment = result.assessment
    print(f"programme_authoring_quality={assessment.rating.value} note={assessment.notes!r}")
    return 0 if assessment.rating.value in {"acceptable", "good", "excellent"} else 13


def _cli_entrypoint(argv: list[str] | None = None) -> int:
    try:
        return main(argv)
    except Exception as exc:
        print(f"DIDNT_HAPPEN: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 13


if __name__ == "__main__":
    sys.exit(_cli_entrypoint())
