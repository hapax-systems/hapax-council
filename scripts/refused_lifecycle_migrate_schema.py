#!/usr/bin/env python3
"""One-shot schema migration for refused-lifecycle substrate.

Adds seven frontmatter fields to every cc-task with
``automation_status: REFUSED``. Idempotent — files where ``refusal_history``
already exists are skipped. Body after the closing ``---`` is preserved
verbatim. Default cadence is +30d (constitutional trigger); the
classification-pass cc-task overrides per slug.

Usage::

    uv run python scripts/refused_lifecycle_migrate_schema.py [--dry-run] [--active-dir PATH]

Output is a census table summarising migrated / skipped / total counts.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

DEFAULT_ACTIVE_DIR = Path.home() / "Documents/Personal/20-projects/hapax-cc-tasks/active"
DEFAULT_NEXT_EVAL_DAYS = 30  # constitutional default; type-A overridden by classification-pass


def _split_frontmatter(text: str) -> tuple[dict, str] | None:
    if not text.startswith("---\n"):
        return None
    rest = text[4:]
    end = rest.find("\n---\n")
    if end == -1:
        return None
    fm = yaml.safe_load(rest[:end]) or {}
    body = rest[end + len("\n---\n") :]
    return fm, body


def _atomic_write(path: Path, fm: dict, body: str) -> None:
    text = "---\n" + yaml.safe_dump(fm, sort_keys=False) + "---\n" + body
    tmp = path.with_suffix(f".md.tmp.{os.getpid()}")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise


def _build_extension(now: datetime, fm: dict) -> dict:
    """Return the seven new field values to merge into the frontmatter."""
    created_at = fm.get("created_at") or now.isoformat()
    return {
        "evaluation_trigger": ["constitutional"],
        "evaluation_probe": {
            "url": None,
            "conditional_path": None,
            "depends_on_slug": None,
            "lift_keywords": [],
            "last_etag": None,
            "last_lm": None,
            "last_fingerprint": None,
        },
        "last_evaluated_at": now.isoformat(),
        "next_evaluation_at": (now + timedelta(days=DEFAULT_NEXT_EVAL_DAYS)).isoformat(),
        "refusal_history": [
            {
                "date": created_at,
                "transition": "created",
                "reason": fm.get("refusal_reason", "(legacy refusal; reason inline)"),
                "evidence_url": None,
            }
        ],
        "superseded_by": None,
        "acceptance_evidence": None,
        "removed_reason": None,
    }


def migrate(active_dir: Path, now: datetime, *, dry_run: bool = False) -> list[Path]:
    """Migrate every REFUSED cc-task in ``active_dir``; idempotent.

    Returns the list of paths that were migrated (or, in dry-run mode,
    would have been migrated). Files where ``refusal_history`` already
    exists are skipped — the script can be re-run safely.
    """
    if not active_dir.exists():
        return []

    migrated: list[Path] = []
    for path in sorted(active_dir.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            log.warning("could not read %s", path)
            continue

        split = _split_frontmatter(text)
        if split is None:
            continue
        fm, body = split

        if fm.get("automation_status") != "REFUSED":
            continue
        if "refusal_history" in fm:
            continue  # idempotent skip

        extension = _build_extension(now, fm)
        # Preserve original frontmatter ordering by appending new keys at the end.
        fm.update(extension)

        if not dry_run:
            _atomic_write(path, fm, body)
        migrated.append(path)

    return migrated


def _print_census(active_dir: Path, migrated: list[Path]) -> None:
    """Emit a small census table summarising what migrate touched."""
    refused_total = 0
    if active_dir.exists():
        for path in active_dir.glob("*.md"):
            split = _split_frontmatter(path.read_text(encoding="utf-8"))
            if split and split[0].get("automation_status") == "REFUSED":
                refused_total += 1
    skipped = max(0, refused_total - len(migrated))
    print(f"Migrated:  {len(migrated):>3}")
    print(f"Skipped:   {skipped:>3} (already-migrated)")
    print(f"Total REFUSED: {refused_total:>3}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--active-dir", type=Path, default=DEFAULT_ACTIVE_DIR)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    now = datetime.now(UTC)
    migrated = migrate(args.active_dir, now, dry_run=args.dry_run)
    _print_census(args.active_dir, migrated)
    if args.dry_run:
        print("(dry-run — no files written)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
