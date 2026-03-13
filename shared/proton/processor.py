"""processor.py — CLI entrypoint and orchestration for Proton Mail export ingestion.

Usage:
    uv run python -m shared.proton ~/Downloads/proton-export/mail_20260302_011517/
    uv run python -m shared.proton ~/Downloads/proton-export/mail_*/ --dry-run --max-records 50
    uv run python -m shared.proton ~/Downloads/proton-export/mail_*/ --since 2025-01-01
    uv run python -m shared.proton ~/Downloads/proton-export/mail_*/ --resume
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from shared.config import RAG_SOURCES_DIR
from shared.proton.parser import parse_export
from shared.takeout.chunker import write_record
from shared.takeout.progress import ProgressTracker

log = logging.getLogger("proton")

DEFAULT_OUTPUT_DIR = RAG_SOURCES_DIR / "proton"
STRUCTURED_OUTPUT = (
    Path(__file__).resolve().parent.parent.parent / "profiles" / "proton-structured.jsonl"
)


@dataclass
class ProcessResult:
    """Summary of a processing run."""

    total_files: int = 0
    records_written: int = 0
    records_skipped: int = 0
    errors: list[str] = field(default_factory=list)


def _run_id(export_dir: Path) -> str:
    """Generate a stable run ID from the export directory path."""
    raw = str(export_dir.resolve())
    return "proton-" + hashlib.sha256(raw.encode()).hexdigest()[:12]


def process_export(
    export_dir: Path,
    *,
    since: str = "",
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    structured_path: Path = STRUCTURED_OUTPUT,
    dry_run: bool = False,
    max_records: int = 0,
    skip_spam: bool = True,
    resume: bool = False,
) -> ProcessResult:
    """Process a Proton Mail export directory.

    Args:
        export_dir: Path to the Proton export directory containing .eml + .metadata.json pairs.
        since: ISO date — skip records before this date.
        output_dir: Base output directory for markdown files.
        structured_path: Path for structured JSONL output.
        dry_run: Don't write files, just report.
        max_records: Maximum records to process (0 = unlimited).
        skip_spam: Skip spam and trash (default True).
        resume: If True, skip if already completed in a prior run.

    Returns:
        ProcessResult with counts and any errors.
    """
    result = ProcessResult()

    since_dt: datetime | None = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
        except ValueError:
            log.warning("Invalid --since date %r, ignoring filter", since)

    tracker: ProgressTracker | None = None
    service_name = "proton-mail"

    if not dry_run:
        tracker = ProgressTracker(_run_id(export_dir))
        if resume and tracker.is_completed(service_name):
            prev = tracker.summary()["services"].get(service_name, {})
            prev_count = prev.get("records", 0)
            log.info("Skipping proton-mail (already completed, %d records)", prev_count)
            result.records_written = prev_count
            return result

    # Count files for reporting
    meta_files = list(export_dir.glob("*.metadata.json"))
    result.total_files = len(meta_files)

    if tracker:
        tracker.start_service(service_name)

    count = 0
    skipped = 0

    try:
        for record in parse_export(export_dir, since=since_dt, skip_spam=skip_spam):
            if max_records and count >= max_records:
                break

            write_record(
                record,
                output_dir=output_dir,
                structured_path=structured_path,
                dry_run=dry_run,
            )
            count += 1

            if count % 1000 == 0:
                log.info("  Processed %d records...", count)

    except Exception as e:
        error = f"Error processing proton mail: {e}"
        log.error(error)
        result.errors.append(error)
        if tracker:
            tracker.fail_service(service_name, error)

    # Skipped = total files minus records written minus errors
    skipped = max(0, result.total_files - count - len(result.errors))

    if not result.errors and tracker:
        tracker.complete_service(service_name, records=count, skipped=skipped)

    result.records_written = count
    result.records_skipped = skipped

    if skipped:
        log.info("Skipped %d emails (spam, trash, automated, filtered)", skipped)

    # Generate structured facts if we wrote structured data
    if not dry_run and structured_path.exists():
        try:
            from shared.takeout.profiler_bridge import generate_facts

            facts_output = structured_path.parent / "proton-structured-facts.json"
            fact_count = generate_facts(jsonl_path=structured_path, output_path=facts_output)
            if fact_count:
                log.info("Generated %d structured profile facts", fact_count)
        except Exception as e:
            log.warning("Failed to generate structured facts: %s", e)

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Process Proton Mail exports for RAG and profiler ingestion",
        prog="python -m shared.proton",
    )
    parser.add_argument("export_dir", type=Path, help="Path to the Proton Mail export directory")
    parser.add_argument(
        "--since", default="", help="Only include records after this date (ISO format)"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory for markdown files (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--structured-output",
        type=Path,
        default=STRUCTURED_OUTPUT,
        help=f"Path for structured JSONL output (default: {STRUCTURED_OUTPUT})",
    )
    parser.add_argument(
        "--max-records", type=int, default=0, help="Maximum records to process (0 = unlimited)"
    )
    parser.add_argument(
        "--skip-spam",
        action="store_true",
        default=True,
        help="Skip spam and trash emails (default)",
    )
    parser.add_argument("--include-spam", action="store_true", help="Include spam and trash emails")
    parser.add_argument("--resume", action="store_true", help="Resume a previously completed run")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be written without writing"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")

    args = parser.parse_args()

    from shared.log_setup import configure_logging

    configure_logging(agent="proton", level="DEBUG" if args.verbose else None)

    if not args.export_dir.is_dir():
        log.error("Not a directory: %s", args.export_dir)
        sys.exit(1)

    skip_spam = not args.include_spam

    result = process_export(
        args.export_dir,
        since=args.since,
        output_dir=args.output_dir,
        structured_path=args.structured_output,
        dry_run=args.dry_run,
        max_records=args.max_records,
        skip_spam=skip_spam,
        resume=args.resume,
    )

    prefix = "[dry-run] " if args.dry_run else ""
    print(f"\n{prefix}Results:")
    print(f"  Export files:    {result.total_files} pairs")
    print(f"  Records written: {result.records_written}")
    if result.records_skipped:
        print(f"  Records skipped: {result.records_skipped}")
    if result.errors:
        print(f"  Errors:          {len(result.errors)}")
        for err in result.errors:
            print(f"    - {err}")


if __name__ == "__main__":
    main()
