"""CLI for the local visual pool.

Usage:
  uv run python -m agents.visual_pool init
  uv run python -m agents.visual_pool ingest ./frame.png --tier operator-cuts --tag sierpinski
"""

from __future__ import annotations

import argparse
from pathlib import Path

from agents.visual_pool.repository import (
    DEFAULT_VISUAL_POOL_ROOT,
    TIER_DIRECTORIES,
    LocalVisualPool,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m agents.visual_pool")
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_VISUAL_POOL_ROOT,
        help="Visual pool root (default: ~/hapax-pool/visual).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Create the tiered visual pool layout.")

    ingest = sub.add_parser("ingest", help="Copy a local frame asset into the pool.")
    ingest.add_argument("asset", type=Path)
    ingest.add_argument("--tier", choices=sorted(TIER_DIRECTORIES), required=True)
    ingest.add_argument("--tag", action="append", default=[], dest="tags")
    ingest.add_argument("--motion-density", type=float, default=0.5)
    ingest.add_argument("--color", action="append", default=[], dest="colors")
    ingest.add_argument("--duration-seconds", type=float, default=0.0)
    ingest.add_argument("--source")
    ingest.add_argument("--content-risk", choices=sorted(set(TIER_DIRECTORIES.values())))
    ingest.add_argument("--broadcast-safe", action=argparse.BooleanOptionalAction, default=None)
    ingest.add_argument("--title")
    ingest.add_argument("--license")
    ingest.add_argument("--provenance-url")
    ingest.add_argument("--slug")
    ingest.add_argument("--force", action="store_true")

    sub.add_parser("list", help="List valid assets that pass sidecar validation.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    pool = LocalVisualPool(args.root)
    if args.command == "init":
        pool.ensure_layout()
        print(pool.root)
        return 0
    if args.command == "ingest":
        tags = args.tags or ["sierpinski"]
        asset = pool.ingest(
            args.asset,
            tier_directory=args.tier,
            aesthetic_tags=tags,
            motion_density=args.motion_density,
            color_palette=args.colors,
            duration_seconds=args.duration_seconds,
            source=args.source,
            content_risk=args.content_risk if args.content_risk else None,
            broadcast_safe=args.broadcast_safe,
            title=args.title,
            license=args.license,
            provenance_url=args.provenance_url,
            slug=args.slug,
            force=args.force,
        )
        print(asset.path)
        return 0
    if args.command == "list":
        for asset in pool.scan():
            print(
                f"{asset.tier_directory}\t{asset.metadata.content_risk}\t"
                f"{','.join(asset.metadata.aesthetic_tags)}\t{asset.path}"
            )
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
