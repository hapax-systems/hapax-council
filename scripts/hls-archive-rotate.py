#!/usr/bin/env python3
"""CLI wrapper for the LRR Phase 2 HLS archive rotation pass.

Invoked periodically by a systemd timer or manually by the operator.
Walks ``~/.cache/hapax-compositor/hls/`` and rotates stable segments to
the stream archive with per-segment sidecars.

Exit codes::

    0  clean pass (even if nothing to rotate)
    1  rotation pass produced errors on individual segments
    2  argparse / environment error
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agents.studio_compositor.hls_archive import (
    DEFAULT_HLS_SOURCE_DIR,
    DEFAULT_STABLE_MTIME_WINDOW_SECONDS,
    rotate_pass,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="hls-archive-rotate.py",
        description="Rotate stable HLS segments from the compositor cache to the research archive.",
    )
    p.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_HLS_SOURCE_DIR,
        help=f"HLS source directory (default: {DEFAULT_HLS_SOURCE_DIR})",
    )
    p.add_argument(
        "--stable-window",
        type=float,
        default=DEFAULT_STABLE_MTIME_WINDOW_SECONDS,
        help=f"Seconds of mtime stability before rotating (default: {DEFAULT_STABLE_MTIME_WINDOW_SECONDS})",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output instead of human-readable text",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = rotate_pass(
        source_dir=args.source,
        window_seconds=args.stable_window,
    )

    if args.json:
        print(
            json.dumps(
                {
                    "scanned": result.scanned,
                    "rotated": result.rotated,
                    "skipped_unstable": result.skipped_unstable,
                    "skipped_already_rotated": result.skipped_already_rotated,
                    "skipped_zero_byte": result.skipped_zero_byte,
                    "skipped_playlist_current": result.skipped_playlist_current,
                    "skipped_open": result.skipped_open,
                    "errors": result.errors,
                }
            )
        )
    else:
        print(
            f"scanned={result.scanned} rotated={result.rotated} "
            f"skipped_unstable={result.skipped_unstable} "
            f"skipped_already_rotated={result.skipped_already_rotated} "
            f"skipped_zero_byte={result.skipped_zero_byte} "
            f"skipped_playlist_current={result.skipped_playlist_current} "
            f"skipped_open={result.skipped_open} "
            f"errors={len(result.errors)}"
        )
        for err in result.errors:
            print(f"  ERR {err}", file=sys.stderr)

    return 1 if result.errors else 0


if __name__ == "__main__":
    sys.exit(main())
