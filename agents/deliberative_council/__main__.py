"""Entry point: uv run python -m agents.deliberative_council --mode labeling ..."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path


def _cmd_labeling(args: argparse.Namespace) -> None:
    from agents.deliberative_council.modes.labeling import run_labeling

    label_rows, review_rows = asyncio.run(
        run_labeling(
            manifest_path=Path(args.input),
            output_path=Path(args.output),
            review_queue_path=Path(args.review_queue) if args.review_queue else None,
            label_round=args.label_round,
            concurrency=args.concurrency,
        )
    )
    print(f"Labeled: {len(label_rows)} ratified, {len(review_rows)} sent to review queue")


def _cmd_ratify(args: argparse.Namespace) -> None:
    from agents.deliberative_council.modes.labeling import run_ratification

    ratified = run_ratification(
        review_queue_path=Path(args.review_queue),
        ratification_path=Path(args.ratification),
        output_path=Path(args.output),
        manifest_path=Path(args.manifest),
        label_round=args.label_round,
    )
    print(f"Ratified: {len(ratified)} records written to {args.output}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m agents.deliberative_council",
        description="Deliberative council modes",
    )
    parser.add_argument("--mode", required=True, choices=["labeling", "ratify"])
    parser.add_argument("--input", help="Path to manifest JSON (labeling mode)")
    parser.add_argument("--output", required=True, help="Path to write output label rows JSON")
    parser.add_argument("--review-queue", help="Path to write/read contested+hung review rows")
    parser.add_argument("--label-round", default="round1")
    parser.add_argument("--concurrency", type=int, default=4)
    # ratify mode args
    parser.add_argument("--ratification", help="Path to operator ratification rows JSON")
    parser.add_argument("--manifest", help="Path to manifest JSON (ratify mode)")

    args = parser.parse_args()

    if args.mode == "labeling":
        if not args.input:
            parser.error("--input is required for labeling mode")
        _cmd_labeling(args)
    elif args.mode == "ratify":
        for flag in ("review_queue", "ratification", "manifest"):
            if not getattr(args, flag):
                parser.error(f"--{flag.replace('_', '-')} is required for ratify mode")
        _cmd_ratify(args)
    else:
        parser.error(f"Unknown mode: {args.mode}")


if __name__ == "__main__":
    main()
