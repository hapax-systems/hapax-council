#!/usr/bin/env python3
"""Diff-aware vulture gate for newly introduced unused callables."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

SOURCE_PATHS = ("agents", "logos", "shared", "scripts")
DEFAULT_WHITELIST = Path("scripts/vulture_whitelist.py")
CALLABLE_KINDS = {"function", "method", "class", "property"}

# Handed a DIRECTORY, vulture collects *.py and nothing else. The estate keeps 146 Python
# entrypoints in scripts/ with no extension (cc-claim, cc-dispatch, cc-stage-advance, ...), so they
# were invisible to this gate in both directions: a shared/ helper called only from one of them
# reads as unused, and dead code inside them is never detected at all.
#
# The documented remedy for the first case is a vulture_whitelist.py entry — which suppresses that
# symbol NAME everywhere, permanently, to work around the scanner not having read the file that
# calls it. That trades a false positive for a durable blind spot, 146 files over. Feed vulture the
# files instead.
#
# Named explicitly, vulture parses an extensionless file normally. Directory arguments still
# contribute only *.py, so there is no double-reporting. Widening the scan also cannot break
# existing PRs: findings are filtered to lines the diff touched, so pre-existing dead code in these
# scripts stays dormant until someone edits it.
SHEBANG_SCAN_BYTES = 128

FINDING_RE = re.compile(
    r"^(?P<path>.+?):(?P<line>\d+): unused (?P<kind>function|method|class|property) "
    r"'(?P<name>[^']+)' \((?P<confidence>\d+)% confidence\)$"
)
DIFF_FILE_RE = re.compile(r"^\+\+\+ b/(?P<path>.+)$")
DIFF_HUNK_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@"
)


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    kind: str
    name: str
    confidence: int
    raw: str


def parse_vulture_output(output: str) -> list[Finding]:
    findings: list[Finding] = []
    for raw_line in output.splitlines():
        match = FINDING_RE.match(raw_line)
        if match is None:
            continue
        kind = match.group("kind")
        if kind not in CALLABLE_KINDS:
            continue
        findings.append(
            Finding(
                path=Path(match.group("path")),
                line=int(match.group("line")),
                kind=kind,
                name=match.group("name"),
                confidence=int(match.group("confidence")),
                raw=raw_line,
            )
        )
    return findings


def _normalize_diff_path(path: str) -> Path | None:
    if path == "/dev/null":
        return None
    return Path(path)


def parse_changed_lines(diff_text: str) -> dict[Path, set[int]]:
    changed: dict[Path, set[int]] = {}
    current_path: Path | None = None

    for line in diff_text.splitlines():
        file_match = DIFF_FILE_RE.match(line)
        if file_match is not None:
            current_path = _normalize_diff_path(file_match.group("path"))
            if current_path is not None:
                changed.setdefault(current_path, set())
            continue

        hunk_match = DIFF_HUNK_RE.match(line)
        if hunk_match is None or current_path is None:
            continue

        start = int(hunk_match.group("new_start"))
        count = int(hunk_match.group("new_count") or "1")
        if count == 0:
            continue
        changed[current_path].update(range(start, start + count))

    return changed


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def git_diff_lines(args: argparse.Namespace) -> dict[Path, set[int]]:
    command = ["git", "diff", "--unified=0"]
    if args.staged:
        command.append("--cached")
    elif args.diff_range:
        command.append(args.diff_range)
    elif args.base_ref:
        command.append(f"{args.base_ref}...HEAD")
    else:
        command.append("HEAD")
    command.extend(["--", *SOURCE_PATHS])

    result = run_command(command)
    if result.returncode != 0:
        print(result.stdout, file=sys.stderr, end="")
        raise SystemExit(result.returncode)
    return parse_changed_lines(result.stdout)


def has_python_shebang(path: Path) -> bool:
    """True when an extensionless file declares a Python interpreter on line 1."""
    try:
        with path.open("rb") as handle:
            first = handle.readline(SHEBANG_SCAN_BYTES)
    except OSError:
        return False
    return first.startswith(b"#!") and b"python" in first


def extensionless_python_files(paths: Iterable[str]) -> list[str]:
    """Python entrypoints under `paths` that vulture's directory walk would not collect."""
    found: list[str] = []
    for raw in paths:
        root = Path(raw)
        if not root.is_dir():
            continue
        for candidate in sorted(root.rglob("*")):
            if candidate.suffix or not candidate.is_file():
                continue
            if has_python_shebang(candidate):
                found.append(str(candidate))
    return found


def run_vulture(paths: Iterable[str], whitelist: Path, min_confidence: int) -> list[Finding]:
    paths = list(paths)
    command = [
        sys.executable,
        "-m",
        "vulture",
        *paths,
        *extensionless_python_files(paths),
        str(whitelist),
        "--min-confidence",
        str(min_confidence),
    ]
    result = run_command(command)
    if result.returncode not in (0, 3):
        print(result.stdout, file=sys.stderr, end="")
        raise SystemExit(result.returncode)
    return parse_vulture_output(result.stdout)


def findings_on_changed_lines(
    findings: Iterable[Finding],
    changed_lines: dict[Path, set[int]] | None,
) -> list[Finding]:
    if changed_lines is None:
        return list(findings)

    active: list[Finding] = []
    for finding in findings:
        lines = changed_lines.get(finding.path)
        if lines is not None and finding.line in lines:
            active.append(finding)
    return active


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument(
        "--staged",
        action="store_true",
        help="check only callables newly added to the staged diff",
    )
    scope.add_argument(
        "--base-ref",
        help="check only callables newly added since merge-base with this ref or SHA",
    )
    scope.add_argument(
        "--diff-range",
        help="check only callables newly added in an explicit git diff range",
    )
    scope.add_argument(
        "--all",
        action="store_true",
        help="check every current callable finding; intended for audits, not CI",
    )
    parser.add_argument(
        "--min-confidence",
        type=int,
        default=60,
        help="vulture confidence threshold for callable findings",
    )
    parser.add_argument(
        "--whitelist",
        type=Path,
        default=DEFAULT_WHITELIST,
        help="vulture whitelist module for justified dynamic entrypoints",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=list(SOURCE_PATHS),
        help="Python source paths to scan",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.whitelist.exists():
        print(f"unused-function gate missing whitelist: {args.whitelist}", file=sys.stderr)
        return 2

    changed_lines = None if args.all else git_diff_lines(args)
    if changed_lines == {}:
        return 0

    findings = run_vulture(args.paths, args.whitelist, args.min_confidence)
    active_findings = findings_on_changed_lines(findings, changed_lines)
    if not active_findings:
        return 0

    print("New unused callable definitions detected by vulture:")
    for finding in active_findings:
        print(f"  {finding.raw}")
    print()
    print(
        "Remove the unused callable, add a real static call path, or add a justified "
        f"dynamic-entrypoint reference to {args.whitelist}."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
