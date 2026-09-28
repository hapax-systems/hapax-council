#!/usr/bin/env python3
"""Refuse a push whose added lines carry a registered principal's name.

Called by the tracked `scripts/pre-push` wrapper. Names come from
`hooks/scripts/principal-name-map.sh` (`HAPAX_PRINCIPAL_NAME_MAP` overrides).
No name or path is printed: a refusal reports `path_sha256=<digest>:<line>`.
Absent registry means none; unreadable or invalid fails closed. Every pushed
commit is scanned against its first parent; a root commit against the empty tree.

Match rule: direct word-boundary; short literals concatenated in source order;
identifier pieces split on camelCase, separators and letter/digit transitions,
with registry names of 4+ characters also substring-matched.

usage: check-principal-names-diff.py [--base SHA --head SHA] [--root DIR]
exit: 0 clean; 1 a registered name is present; 2 fail-closed refusal.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
NAME_MAP = REPO_ROOT / "hooks" / "scripts" / "principal-name-map.sh"
#: A literal longer than this is not part of an assembled run: a name is split into SHORT pieces, and
#: assembling long prose would only manufacture false positives.
MAX_FRAGMENT = 8
#: Registered names shorter than this are not matched as arbitrary substrings.
MIN_SUBSTRING = 4
_LITERAL_RE = re.compile(r'"([^"\\]*)"|\'([^\'\\]*)\'')
_IDENTIFIER_RE = re.compile(r"[0-9A-Za-z]+")
_SPLIT_RE = re.compile(
    r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])"
    r"|(?<=[A-Za-z])(?=[0-9])|(?<=[0-9])(?=[A-Za-z])"
)


def _git(*args: str, root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", "-C", str(root), *args),
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _empty_tree(root: Path) -> str:
    proc = _git("hash-object", "-t", "tree", "/dev/null", root=root)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise ValueError("the empty tree is unavailable, so a new branch cannot be scanned safely")
    return proc.stdout.strip()


def _is_zero(sha: str) -> bool:
    return bool(sha) and set(sha) == {"0"}


def _base_for_unverified_branch(root: Path, head: str) -> str:
    """Every commit not on any remote, then origin/main's merge-base, then the empty tree."""
    rev = _git("rev-list", "--reverse", head, "--not", "--remotes", root=root)
    if rev.returncode == 0:
        commits = [line for line in rev.stdout.splitlines() if line]
        if commits:
            parent = _git("rev-parse", "--verify", "--quiet", f"{commits[0]}^", root=root)
            if parent.returncode == 0 and parent.stdout.strip():
                return parent.stdout.strip()
            return _empty_tree(root)
    merge_base = _git("merge-base", head, "origin/main", root=root)
    if merge_base.returncode == 0 and merge_base.stdout.strip():
        return merge_base.stdout.strip()
    return _empty_tree(root)


def registry_names(root: Path) -> tuple[list[str], str | None]:
    """The registered given names, from the map's own reader. Never re-implemented here."""
    proc = subprocess.run(
        ["bash", "-c", '. "$1"; principal_names', "bash", str(NAME_MAP)],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return [], proc.stderr.strip() or "the principal-name registry cannot be read"
    return [line for line in proc.stdout.splitlines() if line.strip()], None


def _literals(line: str) -> list[str]:
    return [a or b for a, b in _LITERAL_RE.findall(line)]


def _assembled(line: str) -> str:
    """The line's short literals, concatenated in source order — the joined-fragment view."""
    return "".join(part for part in _literals(line) if 0 < len(part) <= MAX_FRAGMENT)


def _identifier_tokens(line: str) -> set[str]:
    """Camel-case, separator and letter/digit pieces of every alphanumeric run on the line."""
    return {
        piece.casefold()
        for run in _IDENTIFIER_RE.findall(line)
        for piece in _SPLIT_RE.split(run)
        if piece
    }


def _path_digest(path: str) -> str:
    return hashlib.sha256(path.encode("utf-8")).hexdigest()


def matches(line: str, names: list[str]) -> bool:
    folded = line.casefold()
    assembled = _assembled(line).casefold()
    tokens = _identifier_tokens(line)
    for name in names:
        needle = name.casefold()
        if re.search(rf"(?<![0-9a-z]){re.escape(needle)}(?![0-9a-z])", folded):
            return True
        if needle in assembled:
            return True
        if needle in tokens:
            return True
        if len(needle) >= MIN_SUBSTRING and needle in folded:
            return True
    return False


def added_lines(root: Path, base: str, head: str) -> list[tuple[str, int, str]]:
    """(path, line number at head, text) for every line the range ADDS."""
    diff = _git(
        "diff",
        "--text",
        "--no-color",
        "--no-ext-diff",
        "--no-textconv",
        "--unified=0",
        base,
        head,
        root=root,
    )
    if diff.returncode != 0:
        raise SystemExit(2)
    out: list[tuple[str, int, str]] = []
    path, lineno, remaining = "", 0, 0
    for line in diff.stdout.split("\n"):
        if line.startswith("diff --git "):
            remaining = 0
        elif not remaining and line.startswith("+++ b/"):
            path = line[6:]
        elif line.startswith("@@"):
            plus = line.split("+", 1)[1].split(" ", 1)[0]
            start, _, count = plus.partition(",")
            lineno, remaining = int(start), int(count) if count else 1
        elif remaining and line.startswith(("+", " ")):
            if line.startswith("+"):
                out.append((path, lineno, line[1:]))
            lineno, remaining = lineno + 1, remaining - 1
    return out


def ranges_from_stdin(root: Path) -> list[tuple[str, str]]:
    """The (base, head) ranges git hands a pre-push hook on stdin."""
    ranges: list[tuple[str, str]] = []
    for line in sys.stdin.read().splitlines():
        parts = line.split()
        if len(parts) != 4:
            continue
        _local_ref, local_sha, _remote_ref, remote_sha = parts
        if _is_zero(local_sha):
            continue  # a deletion pushes no content
        if (
            not _is_zero(remote_sha)
            and _git("cat-file", "-e", f"{remote_sha}^{{commit}}", root=root).returncode == 0
        ):
            ranges.append((remote_sha, local_sha))
        else:
            ranges.append((_base_for_unverified_branch(root, local_sha), local_sha))
    return ranges


def commits_in_range(root: Path, base: str, head: str) -> list[str]:
    """Every commit the range pushes, oldest first."""
    kind = _git("cat-file", "-t", base, root=root)
    if kind.returncode == 0 and kind.stdout.strip() == "commit":
        rev = _git("rev-list", "--reverse", head, "--not", base, root=root)
    else:
        rev = _git("rev-list", "--reverse", head, root=root)
    if rev.returncode != 0:
        raise ValueError("the pushed commit range cannot be enumerated")
    return [line for line in rev.stdout.splitlines() if line]


def first_parent(root: Path, commit: str) -> str:
    """The commit's first parent, or the empty tree when it is a root commit."""
    row = _git("rev-list", "--parents", "-n", "1", commit, root=root)
    if row.returncode != 0 or not row.stdout.strip():
        raise ValueError("a pushed commit cannot be read")
    parts = row.stdout.split()
    return parts[1] if len(parts) > 1 else _empty_tree(root)


def ranges_from_precommit(root: Path) -> list[tuple[str, str]]:
    """The range pre-commit exposes to a pre-push hook through its environment."""
    from_ref = os.environ.get("PRE_COMMIT_FROM_REF")
    to_ref = os.environ.get("PRE_COMMIT_TO_REF")
    if from_ref or to_ref:
        if not (from_ref and to_ref):
            raise ValueError("pre-commit supplied only one end of its push range")
        return [(from_ref, to_ref)]
    head = _git("rev-parse", "HEAD", root=root)
    if head.returncode != 0:
        raise ValueError("pre-commit supplied no push range and HEAD is unavailable")
    return [(_empty_tree(root), head.stdout.strip())]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--base")
    parser.add_argument("--head")
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)
    root = args.root.resolve()

    try:
        if args.base and args.head:
            ranges = [(args.base, args.head)]
        elif os.environ.get("PRE_COMMIT") == "1":
            ranges = ranges_from_precommit(root)
        else:
            ranges = ranges_from_stdin(root)
    except ValueError as error:
        print(f"principal-name-scan: REFUSED — {error}.", file=sys.stderr)
        return 2
    names, failure = registry_names(root)
    if failure is not None:
        print(f"principal-name-scan: REFUSED — {failure}", file=sys.stderr)
        print("  This check fails closed: repair the registry, or remove it.", file=sys.stderr)
        return 2
    if not names or not ranges:
        return 0

    hits: list[str] = []
    seen: set[str] = set()
    for base, head in ranges:
        for commit in commits_in_range(root, base, head):
            if commit in seen:
                continue
            seen.add(commit)
            parent = first_parent(root, commit)
            for path, lineno, text in added_lines(root, parent, commit):
                if matches(text, names):
                    hits.append(f"path_sha256={_path_digest(path)}:{lineno}")
    if not hits:
        return 0
    print(
        "principal-name-scan: REFUSED — a registered principal's name is in the outgoing diff.",
        file=sys.stderr,
    )
    for hit in sorted(set(hits)):
        print(f"  {hit}", file=sys.stderr)
    print(
        "  The name is withheld by design. Reword the line to use the opaque referent "
        "(principal-<id>) or the sanctioned referents.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
