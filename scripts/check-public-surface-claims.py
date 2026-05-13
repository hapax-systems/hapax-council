#!/usr/bin/env python3
"""Deterministic public-surface claim gate for weblog and omg copy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from shared.publication_hardening.lint import LintFinding, lint_file

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGETS = (
    REPO_ROOT / "agents" / "omg_web_builder" / "static" / "index.html",
    REPO_ROOT / "docs" / "publication-drafts",
)


def iter_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(p for p in path.rglob("*") if p.suffix in {".html", ".md"}))
        elif path.exists():
            if path.suffix in {".html", ".md"}:
                files.append(path)
        else:
            raise FileNotFoundError(path)
    return files


def finding_to_dict(finding: LintFinding) -> dict[str, object]:
    return {
        "file": finding.file,
        "line": finding.line,
        "level": finding.level,
        "rule": finding.rule,
        "message": finding.message,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, help="files or directories to scan")
    parser.add_argument("--json", action="store_true", help="emit JSON findings")
    parser.add_argument(
        "--warnings-fail",
        action="store_true",
        help="treat warnings as failures, not only errors",
    )
    args = parser.parse_args(argv)

    paths = args.paths or list(DEFAULT_TARGETS)
    findings: list[LintFinding] = []
    for path in iter_files(paths):
        findings.extend(lint_file(path))

    if args.json:
        print(json.dumps([finding_to_dict(f) for f in findings], indent=2, sort_keys=True))
    else:
        for finding in findings:
            print(
                f"{finding.file}:{finding.line}: {finding.level}: {finding.rule}: {finding.message}"
            )

    failing_levels = {"error", "warning"} if args.warnings_fail else {"error"}
    return 1 if any(f.level in failing_levels for f in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
