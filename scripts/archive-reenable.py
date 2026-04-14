#!/usr/bin/env python3
"""Gated re-enable CLI for the disabled archival pipeline.

LRR Phase 2 item 1. Wraps ``systemctl --user enable|disable|status`` over
the 8 disabled units documented in ``systemd/README.md § Disabled
Services``. Default is dry-run — ``--live`` is required to make any
actual systemd change so tests and exploratory runs never touch the
running system.

Unit list is pinned in-repo (see ``ARCHIVAL_UNITS``). A regression test
in ``tests/test_archive_reenable.py`` asserts this list matches the
canonical README §Disabled Services table.

Usage::

    scripts/archive-reenable.py status              # show current enable state
    scripts/archive-reenable.py enable               # dry-run (default)
    scripts/archive-reenable.py enable --live        # actually enable
    scripts/archive-reenable.py disable --live       # actually disable
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass

# Pinned list of archival pipeline units. Must match
# systemd/README.md § Disabled Services. Regression-pinned in
# tests/test_archive_reenable.py.
ARCHIVAL_UNITS: tuple[str, ...] = (
    "audio-recorder.service",
    "contact-mic-recorder.service",
    "rag-ingest.service",
    "audio-processor.timer",
    "video-processor.timer",
    "av-correlator.timer",
    "flow-journal.timer",
    "video-retention.timer",
)


@dataclass(frozen=True)
class UnitStatus:
    name: str
    enabled: str  # "enabled" | "disabled" | "linked" | "static" | "not-found" | "unknown"
    active: str  # "active" | "inactive" | "failed" | "unknown"


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a subprocess; capture output; never raise on non-zero exit."""
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def query_status(unit: str) -> UnitStatus:
    """Return current enable + active state for a single unit."""
    enabled_proc = _run(["systemctl", "--user", "is-enabled", unit])
    active_proc = _run(["systemctl", "--user", "is-active", unit])
    enabled = (enabled_proc.stdout or enabled_proc.stderr).strip() or "unknown"
    active = (active_proc.stdout or active_proc.stderr).strip() or "unknown"
    return UnitStatus(name=unit, enabled=enabled, active=active)


def print_status_table(statuses: list[UnitStatus]) -> None:
    name_w = max(len(s.name) for s in statuses) + 2
    print(f"{'UNIT'.ljust(name_w)}{'ENABLED'.ljust(12)}ACTIVE")
    for s in statuses:
        print(f"{s.name.ljust(name_w)}{s.enabled.ljust(12)}{s.active}")


def cmd_status(args: argparse.Namespace) -> int:
    statuses = [query_status(u) for u in ARCHIVAL_UNITS]
    print_status_table(statuses)
    return 0


def cmd_enable(args: argparse.Namespace) -> int:
    return _toggle(args, action="enable")


def cmd_disable(args: argparse.Namespace) -> int:
    return _toggle(args, action="disable")


def _toggle(args: argparse.Namespace, action: str) -> int:
    """Run enable or disable across all archival units with dry-run default."""
    assert action in ("enable", "disable")
    if not args.live:
        print(f"[dry-run] Would {action} the following archival units:")
        for u in ARCHIVAL_UNITS:
            print(f"  systemctl --user {action} --now {u}")
        print()
        print("Re-run with --live to actually apply.")
        return 0

    if shutil.which("systemctl") is None:
        print("ERROR: systemctl not found on PATH", file=sys.stderr)
        return 2

    print(f"[LIVE] {action}ing archival pipeline units...")
    errors: list[str] = []
    for u in ARCHIVAL_UNITS:
        cmd = ["systemctl", "--user", action, "--now", u]
        proc = _run(cmd)
        if proc.returncode == 0:
            print(f"  ok     {u}")
        else:
            errors.append(f"{u}: rc={proc.returncode} stderr={proc.stderr.strip()}")
            print(f"  FAIL   {u}  (rc={proc.returncode})")

    if errors:
        print()
        print(f"ERRORS ({len(errors)}):")
        for e in errors:
            print(f"  {e}")
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="archive-reenable.py",
        description="Gated re-enable/disable CLI for the LRR Phase 2 archival pipeline.",
    )
    subparsers = parser.add_subparsers(dest="action", required=True)

    p_status = subparsers.add_parser(
        "status", help="Show current enable + active state for each unit"
    )
    p_status.set_defaults(func=cmd_status)

    p_enable = subparsers.add_parser(
        "enable", help="Enable + start archival units (dry-run by default)"
    )
    p_enable.add_argument("--live", action="store_true", help="Actually enable (otherwise dry-run)")
    p_enable.set_defaults(func=cmd_enable)

    p_disable = subparsers.add_parser(
        "disable", help="Disable + stop archival units (dry-run by default)"
    )
    p_disable.add_argument(
        "--live", action="store_true", help="Actually disable (otherwise dry-run)"
    )
    p_disable.set_defaults(func=cmd_disable)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
