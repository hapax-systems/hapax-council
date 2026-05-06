#!/usr/bin/env python3
"""Queue the segment-prep prediction ledger for publication when it changes."""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import publish_vault_artifact

log = logging.getLogger(__name__)

DEFAULT_LEDGER_PATH = (
    Path.home()
    / "Documents/Personal/20-projects/hapax-research/ledgers/"
    / "segment-prep-framework-prediction-ledger.md"
)
DEFAULT_STATE_PATH = (
    Path.home() / "hapax-state/publish/state/segment-prep-framework-prediction-ledger.sha256"
)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def last_published_hash(state_path: Path) -> str:
    try:
        return state_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def save_published_hash(state_path: Path, digest: str) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_path.with_suffix(state_path.suffix + ".tmp")
    tmp.write_text(digest + "\n", encoding="utf-8")
    tmp.replace(state_path)


def should_publish(path: Path, state_path: Path, *, force: bool = False) -> tuple[bool, str]:
    digest = file_sha256(path)
    if force:
        return True, digest
    return digest != last_published_hash(state_path), digest


def queue_publication(path: Path) -> int:
    return publish_vault_artifact.main([str(path)])


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.environ.get("HAPAX_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=DEFAULT_LEDGER_PATH)
    parser.add_argument("--state-path", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if not args.path.exists():
        log.error("ledger not found: %s", args.path)
        return 2

    publish, digest = should_publish(args.path, args.state_path, force=args.force)
    if not publish:
        log.info("ledger unchanged; no publish queued")
        return 0

    if args.dry_run:
        log.info("DRY RUN - would queue %s", args.path)
        return 0

    rc = queue_publication(args.path)
    if rc != 0:
        return rc

    save_published_hash(args.state_path, digest)
    log.info("queued ledger publication and recorded hash %s", digest[:12])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
