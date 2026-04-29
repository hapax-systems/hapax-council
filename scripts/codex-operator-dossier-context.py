#!/usr/bin/env python3
"""Render a safe operator-dossier block for Codex bootstrap prompts."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPO_ROOT / "config" / "codex" / "operator-dossier-summary.md"
MAX_BYTES = 24_000

_FORBIDDEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "secret-like assignment",
        re.compile(
            r"(?im)\b[A-Z0-9_]*(?:API[_-]?KEY|SECRET|PASSWORD|TOKEN|CREDENTIAL|PRIVATE[_-]?KEY)"
            r"[A-Z0-9_]*\s*[:=]"
        ),
    ),
    (
        "common secret token",
        re.compile(
            r"(?i)\b(?:sk-[A-Za-z0-9_-]{10,}|gh[opsu]_[A-Za-z0-9_]{10,}|github_pat_[A-Za-z0-9_]{10,})"
        ),
    ),
    (
        "raw dialogue marker",
        re.compile(
            r"(?im)\b(?:private|raw|verbatim)\s+transcript\b|"
            r"^\s*(?:operator|user|assistant|claude|codex)\s*:\s+"
        ),
    ),
)


def _source_from_env(value: str | None) -> Path:
    if not value:
        return DEFAULT_SOURCE

    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _leak_reasons(text: str) -> list[str]:
    reasons: list[str] = []
    for name, pattern in _FORBIDDEN_PATTERNS:
        if pattern.search(text):
            reasons.append(name)
    return reasons


def _unavailable_block(source: Path, reason: str) -> str:
    return "\n".join(
        [
            "## Codex-Visible Operator Dossier",
            "",
            "- status: unavailable",
            f"- source: {_display_path(source)}",
            f"- reason: {reason}",
            "- fallback: Use the explicit user message, CLAUDE.md, AGENTS.md, cc-task note, and relay state only.",
            "- repair: Update the sanitized summary or set HAPAX_CODEX_OPERATOR_DOSSIER to a reviewed safe file.",
        ]
    )


def render_context(source: Path) -> str:
    if not source.exists():
        return _unavailable_block(source, "source file missing")
    if not source.is_file():
        return _unavailable_block(source, "source is not a regular file")

    size = source.stat().st_size
    if size > MAX_BYTES:
        return _unavailable_block(source, f"source exceeds {MAX_BYTES} byte bootstrap limit")

    text = source.read_text(encoding="utf-8").strip()
    reasons = _leak_reasons(text)
    if reasons:
        reason_text = "source failed leak guard: " + ", ".join(sorted(reasons))
        return _unavailable_block(source, reason_text)

    return "\n".join(
        [
            "## Codex-Visible Operator Dossier",
            "",
            "- status: safe_summary",
            f"- source: {_display_path(source)}",
            "- visibility: safe to include in generated Codex bootstrap prompts",
            "",
            text,
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        default=os.environ.get("HAPAX_CODEX_OPERATOR_DOSSIER"),
        help="Safe dossier summary path. Defaults to config/codex/operator-dossier-summary.md.",
    )
    args = parser.parse_args(argv)

    source = _source_from_env(args.source)
    sys.stdout.write(render_context(source))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
