"""processor.py — CLI entrypoint and orchestration for Takeout ingestion.

Usage:
    uv run python -m shared.takeout --list-services ~/Downloads/takeout.zip
    uv run python -m shared.takeout ~/Downloads/takeout-*.zip --services chrome,keep --since 2025-01-01
    uv run python -m shared.takeout ~/Downloads/takeout-*.zip --dry-run
    uv run python -m shared.takeout ~/Downloads/takeout-*.zip --resume
    uv run python -m shared.takeout --progress ~/Downloads/takeout-*.zip

Supports multiple ZIP files (Google Takeout splits large exports across
multiple archives). Each ZIP is processed sequentially with its own
progress tracking. Structured facts are generated once after all ZIPs.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import logging
import sys
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from shared.takeout.chunker import DEFAULT_OUTPUT_DIR, STRUCTURED_OUTPUT, StructuredWriter, write_record
from shared.takeout.models import ServiceConfig
from shared.takeout.progress import ProgressTracker
from shared.takeout.registry import SERVICE_REGISTRY, detect_services

log = logging.getLogger("takeout")


@dataclass
class ProcessResult:
    """Summary of a processing run."""
    services_found: list[str] = field(default_factory=list)
    services_processed: list[str] = field(default_factory=list)
    records_by_service: dict[str, int] = field(default_factory=dict)
    records_written: int = 0
    records_skipped: int = 0
    errors: list[str] = field(default_factory=list)


def _load_parser(parser_name: str):
    """Dynamically import a parser module from shared.takeout.parsers."""
    module = importlib.import_module(f"shared.takeout.parsers.{parser_name}")
    if not hasattr(module, "parse"):
        raise ImportError(f"Parser {parser_name} has no parse() function")
    return module.parse


def _purge_service_from_jsonl(structured_path: Path, service_name: str) -> int:
    """Remove records for a given service from the structured JSONL file.

    Used on resume to prevent duplicate records when re-processing a service
    that was interrupted mid-way. Returns the number of records removed.

    Operates atomically: writes to a temp file then replaces the original.
    """
    if not structured_path.exists():
        return 0

    kept_lines: list[str] = []
    removed = 0

    with open(structured_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError:
                kept_lines.append(line)
                continue
            if record.get("service") == service_name:
                removed += 1
            else:
                kept_lines.append(line)

    if removed > 0:
        import tempfile
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=structured_path.parent, suffix=".jsonl"
        )
        try:
            with open(tmp_fd, "w", encoding="utf-8") as f:
                f.writelines(kept_lines)
            Path(tmp_path).replace(structured_path)
        except Exception:
            Path(tmp_path).unlink(missing_ok=True)
            raise
        log.info("Purged %d records for %s from %s (resume dedup)",
                 removed, service_name, structured_path.name)

    return removed


def _run_id(zip_path: Path) -> str:
    """Generate a stable run ID from the ZIP path + size for progress tracking."""
    stat = zip_path.stat()
    raw = f"{zip_path.resolve()}:{stat.st_size}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def process_takeout(
    zip_path: Path,
    *,
    services: list[str] | None = None,
    since: str = "",
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    structured_path: Path = STRUCTURED_OUTPUT,
    dry_run: bool = False,
    max_records: int = 0,
    resume: bool = False,
    _skip_facts: bool = False,
) -> ProcessResult:
    """Process a Google Takeout ZIP file.

    Args:
        zip_path: Path to the Takeout ZIP.
        services: List of service names to process. None = all detected.
        since: ISO date — skip records before this date.
        output_dir: Base output directory for markdown files.
        structured_path: Path for structured JSONL output.
        dry_run: Don't write files, just report.
        max_records: Maximum records per service (0 = unlimited).
        resume: If True, skip services already completed in a prior run.

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
    if not dry_run:
        tracker = ProgressTracker(_run_id(zip_path))

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        detected = detect_services(names)
        result.services_found = sorted(detected.keys())

        if not detected:
            log.warning("No known services found in %s", zip_path)
            return result

        # Filter to requested services
        to_process: dict[str, ServiceConfig] = {}
        if services:
            for svc in services:
                if svc in detected:
                    to_process[svc] = detected[svc]
                else:
                    log.warning("Service %r not found in ZIP (available: %s)",
                                svc, ", ".join(sorted(detected)))
        else:
            to_process = detected

        # Pre-purge all services that need re-processing (before opening writer)
        if resume and not dry_run:
            for svc_name, svc_config in sorted(to_process.items()):
                if not (tracker and tracker.is_completed(svc_name)):
                    _purge_service_from_jsonl(structured_path, svc_name)
                    # Clean orphaned .md files from interrupted unstructured output
                    if svc_config.data_path == "unstructured":
                        svc_dir = output_dir / svc_name
                        if svc_dir.exists():
                            import shutil
                            shutil.rmtree(svc_dir)
                            log.info("Removed %s for clean re-processing", svc_dir)

        # Open structured writer for buffered, dedup-aware JSONL writes
        with StructuredWriter(structured_path, dry_run=dry_run) as sw:
            for svc_name, svc_config in sorted(to_process.items()):
                # Resume: skip completed services
                if resume and tracker and tracker.is_completed(svc_name):
                    prev = tracker.summary()["services"].get(svc_name, {})
                    prev_count = prev.get("records", 0)
                    log.info("Skipping %s (already completed, %d records)", svc_name, prev_count)
                    result.records_by_service[svc_name] = prev_count
                    result.records_written += prev_count
                    result.services_processed.append(svc_name)
                    continue

                log.info("Processing: %s (tier %d, %s)", svc_name, svc_config.tier, svc_config.data_path)

                if svc_config.experimental:
                    log.warning("Parser for %s is experimental and unvalidated against real data", svc_name)

                if tracker:
                    tracker.start_service(svc_name)

                try:
                    parse_fn = _load_parser(svc_config.parser)
                except (ImportError, AttributeError) as e:
                    error = f"Failed to load parser {svc_config.parser!r}: {e}"
                    log.error("  %s", error)
                    result.errors.append(error)
                    if tracker:
                        tracker.fail_service(svc_name, error)
                    continue

                count = 0
                skipped = 0

                had_error = False
                try:
                    for record in parse_fn(zf, svc_config):
                        # Date filter
                        if since_dt and record.timestamp:
                            if record.timestamp.replace(tzinfo=None) < since_dt.replace(tzinfo=None):
                                skipped += 1
                                continue

                        # Max records cap
                        if max_records and count >= max_records:
                            break

                        write_record(
                            record,
                            output_dir=output_dir,
                            structured_path=structured_path,
                            dry_run=dry_run,
                            structured_writer=sw,
                        )
                        count += 1

                except Exception as e:
                    had_error = True
                    error = f"Error processing {svc_name}: {e}"
                    log.error("  %s", error)
                    result.errors.append(error)
                    if tracker:
                        tracker.fail_service(svc_name, error)

                if not had_error:
                    if tracker:
                        tracker.complete_service(svc_name, records=count, skipped=skipped)
                    result.services_processed.append(svc_name)
                else:
                    log.warning("  %s partially failed after %d records", svc_name, count)

                result.records_by_service[svc_name] = count
                result.records_written += count
                result.records_skipped += skipped

                log.info("  %d records%s", count,
                          f" ({skipped} skipped by date filter)" if skipped else "")

    # Generate structured facts if we wrote structured data
    # Skipped in batch mode (caller runs once after all ZIPs)
    if not dry_run and not _skip_facts and structured_path.exists():
        try:
            from shared.takeout.profiler_bridge import generate_facts
            fact_count = generate_facts(jsonl_path=structured_path)
            if fact_count:
                log.info("Generated %d structured profile facts", fact_count)
        except Exception as e:
            log.warning("Failed to generate structured facts: %s", e)

    return result


def process_batch(
    zip_paths: list[Path],
    *,
    services: list[str] | None = None,
    since: str = "",
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    structured_path: Path = STRUCTURED_OUTPUT,
    dry_run: bool = False,
    max_records: int = 0,
    resume: bool = False,
) -> ProcessResult:
    """Process multiple Takeout ZIPs sequentially.

    Each ZIP gets its own progress tracking. Structured fact generation
    runs once after all ZIPs are processed. Results are aggregated.
    """
    aggregate = ProcessResult()

    for i, zp in enumerate(zip_paths, 1):
        log.info("=== ZIP %d/%d: %s ===", i, len(zip_paths), zp.name)

        result = process_takeout(
            zp,
            services=services,
            since=since,
            output_dir=output_dir,
            structured_path=structured_path,
            dry_run=dry_run,
            max_records=max_records,
            resume=resume,
            _skip_facts=True,  # Defer to end
        )

        # Aggregate results
        for svc in result.services_found:
            if svc not in aggregate.services_found:
                aggregate.services_found.append(svc)
        aggregate.services_processed.extend(result.services_processed)
        for svc, count in result.records_by_service.items():
            aggregate.records_by_service[svc] = (
                aggregate.records_by_service.get(svc, 0) + count
            )
        aggregate.records_written += result.records_written
        aggregate.records_skipped += result.records_skipped
        aggregate.errors.extend(result.errors)

    aggregate.services_found.sort()

    # Generate structured facts once after all ZIPs
    if not dry_run and structured_path.exists():
        try:
            from shared.takeout.profiler_bridge import generate_facts
            fact_count = generate_facts(jsonl_path=structured_path)
            if fact_count:
                log.info("Generated %d structured profile facts", fact_count)
        except Exception as e:
            log.warning("Failed to generate structured facts: %s", e)

    return aggregate


def list_services(zip_paths: list[Path]) -> None:
    """List all detected services across one or more Takeout ZIPs."""
    all_detected: dict[str, tuple[ServiceConfig, str]] = {}  # svc -> (config, zip_name)

    for zp in zip_paths:
        with zipfile.ZipFile(zp) as zf:
            names = zf.namelist()
            detected = detect_services(names)

        for name, cfg in detected.items():
            if name not in all_detected:
                all_detected[name] = (cfg, zp.name)

        if len(zip_paths) > 1:
            if detected:
                print(f"{zp.name}: {', '.join(sorted(detected))}")
            else:
                print(f"{zp.name}: no known services")

    if not all_detected:
        print("No known services found in any ZIP")
        return

    if len(zip_paths) > 1:
        print()

    print(f"Total: {len(all_detected)} services across {len(zip_paths)} ZIPs:\n")
    for name in sorted(all_detected):
        cfg, source = all_detected[name]
        src = f"  ({source})" if len(zip_paths) > 1 else ""
        exp = "  (experimental)" if cfg.experimental else ""
        print(f"  {name:15s}  tier={cfg.tier}  path={cfg.data_path:12s}  "
              f"type={cfg.content_type}{src}{exp}")


def show_progress(zip_paths: list[Path]) -> None:
    """Show progress for one or more Takeout ZIPs."""
    for zp in zip_paths:
        run_id = _run_id(zp)
        tracker = ProgressTracker(run_id)
        summary = tracker.summary()

        if not summary["services"]:
            print(f"No progress found for {zp.name}")
            continue

        print(f"Progress for {zp.name} (run {run_id}):\n")
        for svc, info in sorted(summary["services"].items()):
            status = info["status"]
            records = info["records"]
            skipped = info.get("skipped", 0)
            marker = {"completed": "+", "failed": "!", "in_progress": "~", "pending": " "}.get(status, "?")
            skip_str = f" ({skipped} skipped)" if skipped else ""
            print(f"  [{marker}] {svc:15s}  {status:12s}  {records} records{skip_str}")

    print(f"\n  Completed: {summary['completed']}, Failed: {summary['failed']}, Pending: {summary['pending']}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Process Google Takeout exports for RAG and profiler ingestion",
        prog="python -m shared.takeout",
    )
    parser.add_argument("zip_paths", type=Path, nargs="+",
                        help="Path(s) to Takeout ZIP file(s) — supports multiple ZIPs")
    parser.add_argument("--list-services", action="store_true",
                        help="List detected services and exit")
    parser.add_argument("--progress", action="store_true",
                        help="Show progress of last run and exit")
    parser.add_argument("--services", type=str, default="",
                        help="Comma-separated list of services to process (default: all)")
    parser.add_argument("--since", default="",
                        help="Only include records after this date (ISO format)")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
                        help=f"Output directory for markdown files (default: {DEFAULT_OUTPUT_DIR})")
    parser.add_argument("--structured-output", type=Path, default=STRUCTURED_OUTPUT,
                        help=f"Path for structured JSONL output (default: {STRUCTURED_OUTPUT})")
    parser.add_argument("--max-records", type=int, default=0,
                        help="Maximum records per service (0 = unlimited)")
    parser.add_argument("--resume", action="store_true",
                        help="Resume a previously interrupted run")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be written without writing")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Verbose output")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )

    # Validate all zip paths
    for zp in args.zip_paths:
        if not zp.exists():
            log.error("File not found: %s", zp)
            sys.exit(1)
        if not zipfile.is_zipfile(zp):
            log.error("Not a valid ZIP file: %s", zp)
            sys.exit(1)

    if args.list_services:
        list_services(args.zip_paths)
        return

    if args.progress:
        show_progress(args.zip_paths)
        return

    svc_list = [s.strip() for s in args.services.split(",") if s.strip()] or None

    # Use batch processing for multiple ZIPs, single for one
    if len(args.zip_paths) == 1:
        result = process_takeout(
            args.zip_paths[0],
            services=svc_list,
            since=args.since,
            output_dir=args.output_dir,
            structured_path=args.structured_output,
            dry_run=args.dry_run,
            max_records=args.max_records,
            resume=args.resume,
        )
    else:
        result = process_batch(
            args.zip_paths,
            services=svc_list,
            since=args.since,
            output_dir=args.output_dir,
            structured_path=args.structured_output,
            dry_run=args.dry_run,
            max_records=args.max_records,
            resume=args.resume,
        )

    prefix = "[dry-run] " if args.dry_run else ""
    zip_label = f" across {len(args.zip_paths)} ZIPs" if len(args.zip_paths) > 1 else ""
    print(f"\n{prefix}Results{zip_label}:")
    print(f"  Services found:     {len(result.services_found)} ({', '.join(result.services_found)})")
    print(f"  Services processed: {len(result.services_processed)}")
    print(f"  Records written:    {result.records_written}")
    if result.records_skipped:
        print(f"  Records skipped:    {result.records_skipped}")
    if result.errors:
        print(f"  Errors:             {len(result.errors)}")
        for err in result.errors:
            print(f"    - {err}")

    for svc, count in sorted(result.records_by_service.items()):
        print(f"  {svc}: {count} records")


if __name__ == "__main__":
    main()
