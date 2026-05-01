"""Overlay-zones producer daemon entrypoint.

Owner: ``systemd --user`` unit ``hapax-overlay-producer.service``
(operator wires after this module lands; the unit definition is out
of scope for the Phase 1 producer-implementation cc-task).

Run via ``uv run python -m agents.overlay_producer``. The ``__main__``
delegate is at the package root so the same module path works as a
systemd ``ExecStart``.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from agents.overlay_producer.git_activity import GitActivitySource
from agents.overlay_producer.producer import OverlayProducer
from shared.text_repo import DEFAULT_REPO_PATH, TextRepo

log = logging.getLogger("hapax_overlay_producer")

#: Default tick cadence — once per minute matches the spec's §5
#: "1-minute timer" recommendation.
DEFAULT_TICK_INTERVAL_S: float = 60.0


def _build_default_producer(
    *,
    repo_path: Path,
    council_repo_path: Path,
) -> tuple[TextRepo, OverlayProducer]:
    """Construct a producer wired with the Phase 1 source set."""
    repo = TextRepo(path=repo_path)
    repo.load()
    sources = [GitActivitySource(repo_path=council_repo_path)]
    producer = OverlayProducer(repo=repo, sources=sources)
    return repo, producer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-path",
        type=Path,
        default=DEFAULT_REPO_PATH,
        help=f"TextRepo JSONL path (default: {DEFAULT_REPO_PATH})",
    )
    parser.add_argument(
        "--council-repo",
        type=Path,
        default=Path.home() / "projects" / "hapax-council",
        help="Council git worktree (read by GitActivitySource).",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_TICK_INTERVAL_S,
        help=f"Seconds between ticks (default: {DEFAULT_TICK_INTERVAL_S}).",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single tick and exit (used for smoke tests).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    _, producer = _build_default_producer(
        repo_path=args.repo_path,
        council_repo_path=args.council_repo,
    )

    if args.once:
        result = producer.tick()
        log.info(
            "overlay-producer single tick: added=%d skipped=%d failures=%d",
            result.added,
            result.skipped_existing,
            result.source_failures,
        )
        return 0

    log.info("overlay-producer daemon starting (interval=%.1fs)", args.interval)
    try:
        while True:
            result = producer.tick()
            if result.added or result.source_failures:
                log.info(
                    "overlay-producer tick: added=%d skipped=%d failures=%d",
                    result.added,
                    result.skipped_existing,
                    result.source_failures,
                )
            time.sleep(args.interval)
    except KeyboardInterrupt:
        log.info("overlay-producer daemon stopping")
        return 0


if __name__ == "__main__":
    sys.exit(main())
