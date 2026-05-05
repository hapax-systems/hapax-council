#!/usr/bin/env python3
"""Producer for ``~/hapax-state/research/registry.jsonl``.

Closes the witness gap that makes the ``research_instrument_mesh`` braid
rail compute to zero (local 2026-05-04 audit, leverage-rank-9). Walks the
canonical research-artefact dirs (specs / plans / research drops / audits
/ voice-grounding / bayesian-validation), computes content-hashed
``ResearchRegistryEntry`` rows, and appends new entries to the journal.

Idempotent — same file bytes produce the same ``entry_id``, so the
producer is safe to run repeatedly without polluting the journal.

Wired into systemd as ``hapax-research-registry-producer.{service,timer}``
at 6h cadence. CLI:

    uv run scripts/research-registry-emit.py [--dry-run] \\
        [--registry-path PATH] [--repo-root PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from shared.research_registry_scanner import (
    DEFAULT_REGISTRY_PATH,
    default_scan_roots,
    scan_and_register,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Scan canonical research-artefact dirs and append new entries "
            "to ~/hapax-state/research/registry.jsonl. Closes the "
            "research_instrument_mesh braid-rail witness gap."
        )
    )
    parser.add_argument(
        "--registry-path",
        type=Path,
        default=DEFAULT_REGISTRY_PATH,
        help=f"Registry JSONL path (default: {DEFAULT_REGISTRY_PATH}).",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repo root for relative source_path resolution.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute entries but do not write to the journal.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    roots = default_scan_roots(args.repo_root)
    result = scan_and_register(
        roots,
        registry_path=args.registry_path,
        repo_root=args.repo_root,
        dry_run=args.dry_run,
    )
    print(
        json.dumps(
            {
                "registry_path": str(args.registry_path),
                "scanned": result.scanned,
                "new_entries": result.new_entries,
                "skipped_existing": result.skipped_existing,
                "errors": result.errors,
                "new_entry_ids": result.new_entry_ids,
                "dry_run": args.dry_run,
            },
            sort_keys=True,
        )
    )
    return 0 if not result.errors else 1


if __name__ == "__main__":
    sys.exit(main())
