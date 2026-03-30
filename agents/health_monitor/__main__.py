"""CLI entry point for health_monitor.

Usage:
    uv run python -m agents.health_monitor                     # Full check, human output
    uv run python -m agents.health_monitor --json              # Machine-readable JSON
    uv run python -m agents.health_monitor --check docker,gpu  # Specific groups only
    uv run python -m agents.health_monitor --fix               # Run remediation for failures
    uv run python -m agents.health_monitor --fix --yes         # Skip confirmation
    uv run python -m agents.health_monitor --verbose           # Show detail fields
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

# Ensure all checks are registered
from . import checks  # noqa: F401
from .output import format_history, format_human, rotate_history, run_fixes, run_fixes_v2
from .registry import CHECK_REGISTRY
from .runner import run_checks
from .snapshot import write_infra_snapshot

log = logging.getLogger("agents.health_monitor")


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stack health monitor \u2014 zero LLM calls, parallel async checks",
        prog="python -m agents.health_monitor",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON",
    )
    parser.add_argument(
        "--check",
        metavar="GROUPS",
        help="Comma-separated check groups (docker,gpu,systemd,qdrant,profiles,endpoints,credentials,disk)",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Run remediation commands for failures",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip confirmation for --fix",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Auto-apply safe fixes via LLM pipeline (for watchdog timer)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Evaluate fixes but don't execute (shows what would happen)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detail fields for all checks",
    )
    parser.add_argument(
        "--history",
        metavar="N",
        nargs="?",
        const=20,
        type=int,
        help="Show last N health check results from history (default: 20)",
    )

    args = parser.parse_args()

    if args.history is not None:
        print(format_history(args.history))
        return

    groups = None
    if args.check:
        groups = [g.strip() for g in args.check.split(",") if g.strip()]
        unknown = set(groups) - set(CHECK_REGISTRY.keys())
        if unknown:
            print(f"Unknown check groups: {', '.join(sorted(unknown))}", file=sys.stderr)
            print(f"Available: {', '.join(sorted(CHECK_REGISTRY.keys()))}", file=sys.stderr)
            sys.exit(1)

    report = await run_checks(groups)

    # Write infra snapshot for logos-api container (full runs only)
    if groups is None:
        write_infra_snapshot(report)

    if args.json:
        print(report.model_dump_json(indent=2))
    else:
        color = sys.stdout.isatty()
        print(format_human(report, verbose=args.verbose, color=color))

    if args.apply or args.dry_run:
        mode = "dry_run" if args.dry_run else "apply"
        await run_fixes_v2(report, mode=mode)
    elif args.fix:
        await run_fixes(report, yes=args.yes)

    # Rotate history if needed
    try:
        rotate_history()
    except Exception as e:
        log.warning("History rotation failed: %s", e)

    # Exit code reflects overall status
    from .models import Status

    if report.overall_status == Status.FAILED:
        sys.exit(2)
    elif report.overall_status == Status.DEGRADED:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
