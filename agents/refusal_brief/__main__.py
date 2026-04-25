"""Refusal-brief rotator entrypoint (oneshot).

``uv run python -m agents.refusal_brief --rotate`` → rotates the live
log into the operator archive once and exits.

Wired from ``systemd/user/hapax-refusal-brief-rotate.service`` /
``.timer`` (``OnCalendar=*-*-* 00:00:00 UTC``).
"""

from __future__ import annotations

import argparse
import logging
import sys

from agents.refusal_brief.rotator import rotate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agents.refusal_brief")
    parser.add_argument(
        "--rotate",
        action="store_true",
        help="Rotate the live refusal log into the day-archive and exit.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    if not args.rotate:
        parser.print_help()
        return 2

    outcome = rotate()
    print(outcome)
    return 0 if outcome in {"ok", "noop"} else 1


if __name__ == "__main__":
    sys.exit(main())
