"""Entry point: uv run python -m agents.deliberative_council --mode labeling ..."""

from __future__ import annotations

import argparse
import asyncio
import json
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


def _cmd_audit(args: argparse.Namespace) -> None:
    from agents.deliberative_council.modes.audit import (
        discover_artifacts,
        extract_claims,
        report_to_json,
        run_audit_sweep,
    )

    scope = Path(args.scope)

    if args.dry_run:
        artifacts = discover_artifacts(scope)
        claim_count = sum(len(extract_claims(p)) for p in artifacts)
        print(
            f"Audit dry-run: {len(artifacts)} files in {scope}, "
            f"{claim_count} claims extracted (no disconfirmation invoked)"
        )
        return

    report = asyncio.run(
        run_audit_sweep(
            scope=scope,
            concurrency=args.concurrency,
            claim_limit_per_file=args.claim_limit_per_file,
        )
    )

    if args.output:
        Path(args.output).write_text(json.dumps(report_to_json(report), indent=2), encoding="utf-8")
    print(
        f"Audit sweep: scope={report.scope} files={report.files_scanned} "
        f"claims={report.total_claims} survived={report.survived} "
        f"contested={report.contested} refuted={report.refuted} "
        f"insufficient={report.insufficient}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m agents.deliberative_council",
        description="Deliberative council modes",
    )
    parser.add_argument("--mode", required=True, choices=["labeling", "ratify", "audit"])
    parser.add_argument("--input", help="Path to manifest JSON (labeling mode)")
    parser.add_argument(
        "--output",
        help=(
            "Required for labeling/ratify (label rows JSON); optional for audit (sweep report JSON)"
        ),
    )
    parser.add_argument("--review-queue", help="Path to write/read contested+hung review rows")
    parser.add_argument("--label-round", default="round1")
    parser.add_argument("--concurrency", type=int, default=4)
    # ratify mode args
    parser.add_argument("--ratification", help="Path to operator ratification rows JSON")
    parser.add_argument("--manifest", help="Path to manifest JSON (ratify mode)")
    # audit mode args
    parser.add_argument(
        "--scope",
        help="Directory or file to sweep (audit mode); e.g. docs/research/",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Audit mode: discover + extract claims only, do not call disconfirmation",
    )
    parser.add_argument(
        "--claim-limit-per-file",
        type=int,
        default=None,
        help="Audit mode: cap audited claims per file (useful for bounded runs)",
    )

    args = parser.parse_args()

    if args.mode == "labeling":
        if not args.input:
            parser.error("--input is required for labeling mode")
        if not args.output:
            parser.error("--output is required for labeling mode")
        _cmd_labeling(args)
    elif args.mode == "ratify":
        for flag in ("review_queue", "ratification", "manifest", "output"):
            if not getattr(args, flag):
                parser.error(f"--{flag.replace('_', '-')} is required for ratify mode")
        _cmd_ratify(args)
    elif args.mode == "audit":
        if not args.scope:
            parser.error("--scope is required for audit mode")
        _cmd_audit(args)
    else:
        parser.error(f"Unknown mode: {args.mode}")


if __name__ == "__main__":
    main()
