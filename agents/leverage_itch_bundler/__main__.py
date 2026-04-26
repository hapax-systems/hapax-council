"""Itch.io PWYW bundle — Phase 1 dry-run CLI entry."""

from __future__ import annotations

import argparse
import sys

from agents.leverage_itch_bundler import render_dry_run_report, scan_local_artifacts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="leverage_itch_bundler")
    parser.add_argument(
        "--commit",
        action="store_true",
        help=(
            "Issue actual butler push for each artifact. Phase 2.5 — "
            "deferred until `pass insert itch/butler-token` lands."
        ),
    )
    args = parser.parse_args(argv)

    if args.commit:
        print(
            "ERROR: --commit path is Phase 2.5 (deferred until "
            "`pass insert itch/butler-token` lands).",
            file=sys.stderr,
        )
        return 2

    manifest = scan_local_artifacts()
    print(render_dry_run_report(manifest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
