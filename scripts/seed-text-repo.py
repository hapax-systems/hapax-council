#!/usr/bin/env -S uv run python
"""seed-text-repo — migrate Obsidian overlay notes into the text repo (task #126).

Walks the existing Obsidian ``stream-overlays`` folder(s), converts each
note into a :class:`shared.text_repo.TextEntry` record, and appends it to
the repo JSONL at :data:`shared.text_repo.DEFAULT_REPO_PATH`.

Idempotent-ish: entries are deduped by deterministic id derived from the
source file path, so rerunning the script after editing notes updates
those entries in place (via JSONL append-then-compact). Existing entries
with non-seed ids (e.g. operator ``add-text`` entries) are preserved.

Usage::

    seed-text-repo.py                         # seed from default overlay folders
    seed-text-repo.py --folder PATH [...]     # custom source folders
    seed-text-repo.py --dry-run               # preview without writing
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.text_repo import DEFAULT_REPO_PATH, TextEntry, TextRepo  # noqa: E402

DEFAULT_FOLDERS = (
    Path.home() / "Documents" / "Personal" / "30-areas" / "stream-overlays",
    Path.home() / "Documents" / "Personal" / "30-areas" / "stream-overlays" / "research",
)

SEED_SUFFIXES = frozenset({".md", ".txt", ".ansi"})

log = logging.getLogger("seed-text-repo")


def _seed_id_for(path: Path) -> str:
    """Deterministic id derived from the absolute path of the seed file."""
    digest = hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()
    return f"seed-{digest[:8]}"


def _context_keys_for(path: Path) -> list[str]:
    """Infer soft context keys from the folder name (research → study/research)."""
    parts = {p.lower() for p in path.parts}
    keys: list[str] = []
    if "research" in parts:
        keys.extend(["research", "study"])
    return keys


def seed_from_folders(
    folders: list[Path],
    *,
    repo: TextRepo | None = None,
    dry_run: bool = False,
) -> tuple[int, int]:
    """Seed ``repo`` from the given folders. Returns (seen, written)."""
    target = repo if repo is not None else TextRepo()
    target.load()

    seen = 0
    written = 0
    for folder in folders:
        folder = folder.expanduser()
        if not folder.is_dir():
            log.info("skip missing folder: %s", folder)
            continue
        for file in sorted(folder.iterdir()):
            if not file.is_file():
                continue
            if file.suffix.lower() not in SEED_SUFFIXES:
                continue
            try:
                body = file.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                log.debug("unreadable: %s", file, exc_info=True)
                continue
            if not body:
                continue
            seen += 1
            entry_id = _seed_id_for(file)
            context_keys = _context_keys_for(file)
            if dry_run:
                log.info("[dry-run] would write id=%s len=%d file=%s", entry_id, len(body), file)
                continue
            try:
                new_entry = TextEntry(
                    id=entry_id,
                    body=body[:4096],
                    tags=["seed", "obsidian", file.stem],
                    context_keys=context_keys,
                    priority=5,
                )
            except Exception:
                log.debug("validation failed for %s", file, exc_info=True)
                continue
            target.upsert(new_entry)
            written += 1
    if not dry_run and written:
        target.save()
    return seen, written


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--folder",
        action="append",
        type=Path,
        help="Source folder (repeatable). Defaults to stream-overlays + research.",
    )
    p.add_argument("--dry-run", action="store_true", help="Preview without writing.")
    p.add_argument(
        "--path",
        type=Path,
        default=None,
        help=f"Override repo JSONL path (default {DEFAULT_REPO_PATH}).",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    folders = list(args.folder) if args.folder else list(DEFAULT_FOLDERS)
    repo = TextRepo(path=args.path) if args.path is not None else None
    seen, written = seed_from_folders(folders, repo=repo, dry_run=args.dry_run)
    log.info("seed complete: seen=%d written=%d dry_run=%s", seen, written, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
