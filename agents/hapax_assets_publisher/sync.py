"""Idempotent source → checkout tree sync + commit message composition.

Pure Python, no rsync subprocess — keeps the publisher testable without
external tools and without a subprocess dance for diffing. The sync walks
`source_dir`, copies new/modified files into `checkout_dir`, and deletes
files in `checkout_dir` that have no corresponding `source_dir` entry.

External-repo artifacts (README, .github/, CNAME) live at the root of the
checkout alongside the synced tree; they are NOT in `source_dir` and must
not be deleted by the sync. The sync's deletion scope is limited to paths
that exist under `source_dir` root-relative.
"""

from __future__ import annotations

import filecmp
import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ChangeKind = Literal["added", "modified", "deleted"]


@dataclass(frozen=True)
class PathChange:
    path: str
    kind: ChangeKind


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _iter_src_files(source_dir: Path) -> list[Path]:
    return sorted(p for p in source_dir.rglob("*") if p.is_file())


def _iter_dst_files_in_src_namespace(source_dir: Path, dst_dir: Path) -> list[Path]:
    """List files in dst that fall under source_dir's root-relative namespace.

    Only top-level directories + files that exist in source_dir qualify as
    "synced" — anything else in dst (README.md, .github/, CNAME) is considered
    external-repo artifact and left untouched.
    """
    synced_tops = {p.name for p in source_dir.iterdir()}
    result: list[Path] = []
    for top in synced_tops:
        top_path = dst_dir / top
        if not top_path.exists():
            continue
        if top_path.is_file():
            result.append(top_path)
        else:
            result.extend(p for p in top_path.rglob("*") if p.is_file())
    # Root-level files in source_dir that exist directly at dst root.
    for src_file in source_dir.iterdir():
        if not src_file.is_file():
            continue
        dst_file = dst_dir / src_file.name
        if dst_file.is_file() and dst_file not in result:
            result.append(dst_file)
    return sorted(result)


def sync_tree(source_dir: Path, dst_dir: Path) -> list[PathChange]:
    changes: list[PathChange] = []
    source_dir = source_dir.resolve()
    dst_dir = dst_dir.resolve()

    # Copy added / modified files.
    for src_file in _iter_src_files(source_dir):
        rel = src_file.relative_to(source_dir)
        dst_file = dst_dir / rel
        if not dst_file.exists():
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst_file)
            changes.append(PathChange(str(rel), "added"))
            continue
        if not filecmp.cmp(src_file, dst_file, shallow=False):
            shutil.copy2(src_file, dst_file)
            changes.append(PathChange(str(rel), "modified"))

    # Delete files that live under source_dir's namespace but no longer exist in source.
    src_rels = {p.relative_to(source_dir) for p in _iter_src_files(source_dir)}
    for dst_file in _iter_dst_files_in_src_namespace(source_dir, dst_dir):
        rel = dst_file.relative_to(dst_dir)
        if rel not in src_rels:
            dst_file.unlink()
            changes.append(PathChange(str(rel), "deleted"))

    return changes


def has_diff(source_dir: Path, dst_dir: Path) -> bool:
    """Fast predicate: does source_dir differ from dst_dir's synced namespace?

    Returns True on any added/modified/deleted — same scope as sync_tree but
    without performing writes.
    """
    source_dir = source_dir.resolve()
    dst_dir = dst_dir.resolve()

    for src_file in _iter_src_files(source_dir):
        rel = src_file.relative_to(source_dir)
        dst_file = dst_dir / rel
        if not dst_file.exists():
            return True
        if not filecmp.cmp(src_file, dst_file, shallow=False):
            return True

    src_rels = {p.relative_to(source_dir) for p in _iter_src_files(source_dir)}
    for dst_file in _iter_dst_files_in_src_namespace(source_dir, dst_dir):
        rel = dst_file.relative_to(dst_dir)
        if rel not in src_rels:
            return True

    return False


def build_commit_message(changes: list[PathChange]) -> str:
    if not changes:
        return ""

    count = len(changes)
    noun = "file" if count == 1 else "files"
    kinds = {c.kind for c in changes}
    verb = (
        "add"
        if kinds == {"added"}
        else "update"
        if kinds == {"modified"}
        else "remove"
        if kinds == {"deleted"}
        else "sync"
    )

    subject = f"sync({verb}): {count} {noun}"
    if count <= 3:
        subject = f"sync({verb}): {count} {noun} — " + ", ".join(c.path for c in changes)

    body_lines = [f"- {c.kind}: {c.path}" for c in changes[:10]]
    if len(changes) > 10:
        body_lines.append(f"- ... and {len(changes) - 10} more")

    return subject + "\n\n" + "\n".join(body_lines) + "\n"
