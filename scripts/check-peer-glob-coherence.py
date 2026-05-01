#!/usr/bin/env python3
"""Peer-glob coherence lint — P-8 absence-bug class.

Files that read or look up the same canonical resource via different
glob shapes silently drift: one tool can match files the other can't,
and a refactor that updates one will leave its peer broken without
warning. This lint asserts that paired files referencing the same
vault path use identical primary + fallback glob shapes.

Currently checks one peer group:

  ``cc-task-vault-by-id`` — files that look up a single cc-task by
  ``task_id`` under ``hapax-cc-tasks/active/``. Every member must
  contain BOTH:
    primary  = ``active/$task_id-*.md`` (the descriptor-suffix shape)
    fallback = ``active/$task_id.md`` (the descriptor-less shape)

  This pairing exists because operator-pre-claimed tasks may be
  named ``<task_id>.md`` rather than ``<task_id>-<descriptor>.md``;
  any tool that looks up a single task must support both shapes or
  silently miss half the cc-task corpus.

Usage:
    python3 scripts/check-peer-glob-coherence.py [--repo-root PATH]

Exit codes:
    0  All peer groups coherent.
    1  At least one group has drift; details on stderr.

Source: ``~/.cache/hapax/relay/research/2026-04-26-absence-bugs-synthesis-for-beta.md`` P-8.
cc-task: ``p8-peer-glob-coherence-lint``.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_REPO_ROOT = Path(__file__).resolve().parent.parent

PRIMARY_GLOB_RE = re.compile(r'active/\$task_id-["\']?\*\.md')
FALLBACK_GLOB_RE = re.compile(r"active/\$task_id\.md")


@dataclass(frozen=True)
class PeerGroup:
    name: str
    members: tuple[str, ...]
    description: str


PEER_GROUPS: tuple[PeerGroup, ...] = (
    PeerGroup(
        name="cc-task-vault-by-id",
        members=(
            "scripts/cc-claim",
            "scripts/cc-close",
            "hooks/scripts/cc-task-gate.sh",
        ),
        description=(
            "single-task lookup under hapax-cc-tasks/active/ — "
            "must accept both <task_id>-<descriptor>.md and bare <task_id>.md"
        ),
    ),
)


def _check_group(repo_root: Path, group: PeerGroup) -> list[str]:
    errors: list[str] = []
    for relpath in group.members:
        path = repo_root / relpath
        if not path.exists():
            errors.append(f"[{group.name}] {relpath}: file missing — paired group is broken")
            continue
        text = path.read_text(encoding="utf-8")
        if not PRIMARY_GLOB_RE.search(text):
            errors.append(
                f"[{group.name}] {relpath}: missing primary glob "
                f"'active/$task_id-*.md' — peer-glob drift "
                f"(must match shape used by other group members)"
            )
        if not FALLBACK_GLOB_RE.search(text):
            errors.append(
                f"[{group.name}] {relpath}: missing fallback "
                f"'active/$task_id.md' — descriptor-less task_ids will be invisible"
            )
    return errors


def lint(repo_root: Path) -> list[str]:
    errors: list[str] = []
    for group in PEER_GROUPS:
        errors.extend(_check_group(repo_root, group))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Peer-glob coherence lint (P-8).")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=DEFAULT_REPO_ROOT,
        help="Repository root to lint (default: %(default)s).",
    )
    args = parser.parse_args()

    errors = lint(args.repo_root)
    if errors:
        print("peer-glob coherence lint FAILED:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    member_count = sum(len(g.members) for g in PEER_GROUPS)
    print(
        f"peer-glob coherence: {len(PEER_GROUPS)} group(s), {member_count} file(s) — all coherent"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
