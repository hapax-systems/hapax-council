"""CLI entry point for the novelty-shift emitter (one-shot per timer tick)."""

from __future__ import annotations

import argparse
import json
import sys

from agents.novelty_emitter import emit_if_shifted


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

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
