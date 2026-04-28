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


def run_vulture(paths: Iterable[str], whitelist: Path, min_confidence: int) -> list[Finding]:
    command = [
        sys.executable,
        "-m",
        "vulture",
        *paths,
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
