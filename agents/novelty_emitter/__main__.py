"""CLI entry point for the novelty-shift emitter."""

from __future__ import annotations

import argparse
import json
import sys

from agents.novelty_emitter import emit_if_shifted, run_loop


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--json", action="store_true")
    p.add_argument(
        "--loop",
        action="store_true",
        help="run continuously instead of emitting a single tick",
    )
    p.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="loop interval in seconds when --loop is set",
    )
    p.add_argument(
        "--max-ticks",
        type=int,
        default=None,
        help="stop after N ticks; intended for tests and diagnostics",
    )
    args = p.parse_args(argv)

    if args.loop:
        callback = None
        if args.json:

            def callback(report: dict) -> None:
                print(json.dumps(report), flush=True)

        try:
            run_loop(
                interval_s=args.interval,
                max_ticks=args.max_ticks,
                report_callback=callback,
            )
        except ValueError as exc:
            p.error(str(exc))
        return 0

    report = emit_if_shifted()
    if args.json:
        print(json.dumps(report))
    else:
        print(
            f"status={report['status']} gqi={report.get('gqi')} "
            f"prev_gqi={report.get('prev_gqi')} shifted={report.get('shifted')} "
            f"dispatched_total={report.get('dispatched_total')}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
