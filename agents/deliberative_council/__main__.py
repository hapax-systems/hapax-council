"""Entry point: uv run python -m agents.deliberative_council --mode labeling ..."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

STANDARD_INTAKE_MODEL_ALIASES = ("opus", "balanced", "gemini-3-pro")
HIGH_LOAD_INTAKE_MODEL_ALIASES = ("opus",)
INTAKE_HIGH_LOAD_PER_CORE = 1.0
DEFAULT_REQUESTS_DIR = (
    Path.home() / "Documents" / "Personal" / "20-projects" / "hapax-requests" / "active"
)


def _load_per_core() -> float:
    try:
        load_1 = os.getloadavg()[0]
    except OSError:
        return 0.0
    return load_1 / max(os.cpu_count() or 1, 1)


def _intake_default_model_aliases() -> tuple[str, ...]:
    return (
        HIGH_LOAD_INTAKE_MODEL_ALIASES
        if _load_per_core() >= INTAKE_HIGH_LOAD_PER_CORE
        else STANDARD_INTAKE_MODEL_ALIASES
    )


def _parse_models_csv(value: str) -> tuple[str, ...]:
    aliases = tuple(alias.strip() for alias in value.split(",") if alias.strip())
    if not aliases:
        raise argparse.ArgumentTypeError("--models must include at least one model alias")
    return aliases


def _requests_dir() -> Path:
    configured = os.environ.get("HAPAX_REQUESTS_DIR")
    if configured:
        return Path(configured).expanduser()
    return DEFAULT_REQUESTS_DIR


def _captured_request_paths(requests_dir: Path) -> list[Path]:
    from shared.frontmatter import parse_frontmatter

    if not requests_dir.is_dir():
        return []

    captured: list[Path] = []
    for path in sorted(requests_dir.rglob("*.md")):
        frontmatter, _body = parse_frontmatter(path)
        if str(frontmatter.get("status") or "").strip() == "captured":
            captured.append(path)
    return captured


def _intake_config(model_aliases: tuple[str, ...]):
    from agents.deliberative_council.members import model_family
    from agents.deliberative_council.models import CouncilConfig

    families = {model_family(alias) for alias in model_aliases}
    return CouncilConfig(
        model_aliases=model_aliases,
        min_valid_members=len(model_aliases),
        min_valid_families=max(1, len(families)),
        min_axis_values=min(2, len(model_aliases)),
    )


async def _run_intake_paths(
    paths: Sequence[Path],
    *,
    model_aliases: tuple[str, ...],
    write_back: bool,
) -> None:
    from agents.deliberative_council.modes.intake import intake_axis_score_map, run_intake

    config = _intake_config(model_aliases)
    failures = 0
    for path in paths:
        try:
            receipt = await run_intake(path, config=config, write_back=write_back)
        except Exception as exc:
            failures += 1
            print(f"Intake failed for {path}: {exc}", file=sys.stderr)
            continue
        print(
            f"Intake {path}: verdict={receipt.verdict.value} "
            f"recommendation={receipt.recommendation.value} "
            f"convergence={receipt.convergence_status.value} "
            f"composite={receipt.composite_score:.2f} "
            f"axes={','.join(f'{axis}={score}' for axis, score in intake_axis_score_map(receipt).items())}"
        )

    if failures:
        raise SystemExit(1)


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


async def _cmd_intake(args: argparse.Namespace) -> None:
    model_aliases = args.models or _intake_default_model_aliases()
    if args.scan:
        requests_dir = _requests_dir()
        paths = _captured_request_paths(requests_dir)
        if not paths:
            print(f"Intake scan: no captured requests under {requests_dir}")
            return
    else:
        paths = [Path(args.input)]

    await _run_intake_paths(
        paths,
        model_aliases=model_aliases,
        write_back=not args.dry_run,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m agents.deliberative_council",
        description="Deliberative council modes",
    )
    parser.add_argument("--mode", required=True, choices=["labeling", "ratify", "audit", "intake"])
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
        help=(
            "Audit mode: discover + extract claims only, do not call disconfirmation; "
            "intake mode: do not write back to request frontmatter"
        ),
    )
    parser.add_argument(
        "--claim-limit-per-file",
        type=int,
        default=None,
        help="Audit mode: cap audited claims per file (useful for bounded runs)",
    )
    # intake mode args
    parser.add_argument(
        "--models",
        type=_parse_models_csv,
        default=None,
        help=(
            "Intake mode: comma-separated model aliases. Default is opus under high "
            "system load, otherwise opus,balanced,gemini-3-pro."
        ),
    )
    parser.add_argument(
        "--scan",
        action="store_true",
        help="Intake mode: process all captured request notes under HAPAX_REQUESTS_DIR",
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
    elif args.mode == "intake":
        if not args.scan and not args.input:
            parser.error("--input is required for intake mode unless --scan is set")
        asyncio.run(_cmd_intake(args))
    else:
        parser.error(f"Unknown mode: {args.mode}")


if __name__ == "__main__":
    main()
