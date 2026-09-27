#!/usr/bin/env python3
"""Generate the stakeholder revenue brief as a DOCX.

Sending from this script is retired. It used to send the DOCX from the operator's own
Gmail account, which is not a sending route for the network's outbound correspondence.
It now only generates the document; delivery goes through the network's governed sender.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = (
    Path.home() / "Documents/Personal/20-projects/hapax-research/briefs/"
    "2026-04-29-hapax-monetary-revenue-stakeholder-brief.md"
)
DEFAULT_GENERATED_DIR = (
    Path.home() / "Documents/Personal/20-projects/hapax-research/briefs/stakeholder-revenue"
)
DEFAULT_STATE_DIR = Path.home() / ".local/state/hapax/stakeholder-revenue-brief"
SEND_RETIRED = (
    "sending from this script is retired: the operator's own mailbox is not a sending "
    "route for the network's outbound correspondence. Next action: run without --send "
    "to generate the DOCX, then deliver it through the network's governed sender."
)


@dataclass(frozen=True)
class BriefConfig:
    source_path: Path
    generated_dir: Path
    state_dir: Path
    timezone: ZoneInfo
    recipient_name: str
    delivery_note: str | None
    summary_lines: tuple[str, ...]


def _strip_frontmatter(text: str) -> tuple[list[str] | None, str]:
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return None, text
    frontmatter = text[4:end].splitlines()
    body = text[end + len("\n---\n") :].lstrip()
    return frontmatter, body


def _without_leading_h1(markdown: str) -> str:
    return re.sub(r"\A# .+\n+", "", markdown, count=1).lstrip()


def _content_hash(text: str) -> str:
    normalized = "\n".join(line.rstrip() for line in text.strip().splitlines())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _section_map(markdown: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current = "Opening"
    sections[current] = []
    for line in markdown.splitlines():
        match = re.match(r"^(#{1,3})\s+(.+?)\s*$", line)
        if match:
            current = match.group(2).strip()
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return {heading: "\n".join(lines).strip() for heading, lines in sections.items()}


def _summarize_changes(previous: str | None, current: str) -> list[str]:
    if not previous:
        return [
            "This is the first tracked DOCX dispatch; it converts the source "
            "brief into an attachment-ready Word document.",
        ]

    if _content_hash(previous) == _content_hash(current):
        return ["No material content changes since the last sent brief."]

    previous_sections = _section_map(previous)
    current_sections = _section_map(current)
    previous_headings = set(previous_sections)
    current_headings = set(current_sections)

    summary: list[str] = []
    added = sorted(current_headings - previous_headings)
    removed = sorted(previous_headings - current_headings)
    changed = sorted(
        heading
        for heading in current_headings & previous_headings
        if _content_hash(current_sections[heading]) != _content_hash(previous_sections[heading])
    )

    if added:
        suffix = "." if len(added) <= 6 else ", ..."
        summary.append("New sections: " + ", ".join(added[:6]) + suffix)
    if changed:
        suffix = "." if len(changed) <= 8 else ", ..."
        summary.append("Updated sections: " + ", ".join(changed[:8]) + suffix)
    if removed:
        suffix = "." if len(removed) <= 6 else ", ..."
        summary.append("Removed sections: " + ", ".join(removed[:6]) + suffix)

    return summary or ["The source brief changed, but the change was too small to classify."]


def _build_markdown(
    *,
    body: str,
    summary_lines: list[str],
    generated_at: datetime,
    delivery_note: str | None,
    recipient_name: str,
) -> str:
    pretty_date = generated_at.strftime("%B %-d, %Y")
    generated_stamp = generated_at.strftime("%Y-%m-%d %H:%M %Z")
    summary = "\n".join(f"- {line}" for line in summary_lines)
    note = f"\n\n{delivery_note.strip()}\n" if delivery_note else ""
    brief_body = _without_leading_h1(body)
    return f"""---
title: "Hapax Monetary And Revenue Stakeholder Brief"
subtitle: "Updated {pretty_date}"
author: "Hapax"
date: "{pretty_date}"
---

Prepared for {recipient_name}. Generated {generated_stamp}.{note}

# Changes Since Last Brief

{summary}

# Current Brief

{brief_body}
"""


def _assert_not_repo_output(path: Path, *, label: str) -> None:
    resolved = path.expanduser().resolve()
    repo = REPO_ROOT.resolve()
    if resolved == repo or repo in resolved.parents:
        raise RuntimeError(f"{label} must be outside the repository: {resolved}")


def _run_pandoc(markdown_path: Path, docx_path: Path) -> None:
    subprocess.run(
        [
            "pandoc",
            "--from",
            "markdown+pipe_tables+yaml_metadata_block",
            "--to",
            "docx",
            "--standalone",
            "--output",
            str(docx_path),
            str(markdown_path),
        ],
        check=True,
    )


def _write_docx(
    *,
    markdown: str,
    generated_at: datetime,
    generated_dir: Path,
) -> tuple[Path, Path]:
    _assert_not_repo_output(generated_dir, label="generated_dir")
    generated_dir.mkdir(parents=True, exist_ok=True)
    stamp = generated_at.strftime("%Y-%m-%d-%H%M")
    markdown_path = generated_dir / f"hapax-stakeholder-revenue-brief-{stamp}.md"
    docx_path = generated_dir / f"hapax-stakeholder-revenue-brief-{stamp}.docx"
    markdown_path.write_text(markdown, encoding="utf-8")
    _run_pandoc(markdown_path, docx_path)
    return markdown_path, docx_path


def run(config: BriefConfig, *, now: datetime | None = None) -> dict[str, Any]:
    generated_at = now or datetime.now(config.timezone)
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=config.timezone)
    generated_at = generated_at.astimezone(config.timezone)

    state = _load_json(config.state_dir / "state.json")

    source_text = config.source_path.read_text(encoding="utf-8")
    _, source_body = _strip_frontmatter(source_text)
    source_body = source_body.strip() + "\n"
    previous_snapshot_value = str(state.get("last_source_snapshot", ""))
    previous_snapshot_path = Path(previous_snapshot_value) if previous_snapshot_value else None
    previous_snapshot = (
        previous_snapshot_path.read_text(encoding="utf-8")
        if previous_snapshot_path is not None and previous_snapshot_path.exists()
        else None
    )

    summary_lines = list(config.summary_lines) + _summarize_changes(
        previous_snapshot,
        source_body,
    )
    generated_markdown = _build_markdown(
        body=source_body,
        summary_lines=summary_lines,
        generated_at=generated_at,
        delivery_note=config.delivery_note,
        recipient_name=config.recipient_name,
    )
    generated_md, docx_path = _write_docx(
        markdown=generated_markdown,
        generated_at=generated_at,
        generated_dir=config.generated_dir,
    )

    return {
        "sent": False,
        "generated_markdown": str(generated_md),
        "docx": str(docx_path),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(os.environ.get("HAPAX_STAKEHOLDER_REVENUE_BRIEF_SOURCE", DEFAULT_SOURCE)),
        help="Source markdown brief.",
    )
    parser.add_argument(
        "--generated-dir",
        type=Path,
        default=Path(
            os.environ.get(
                "HAPAX_STAKEHOLDER_REVENUE_BRIEF_GENERATED_DIR",
                DEFAULT_GENERATED_DIR,
            )
        ),
        help="Vault directory for generated markdown and DOCX outputs.",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=Path(
            os.environ.get("HAPAX_STAKEHOLDER_REVENUE_BRIEF_STATE_DIR", DEFAULT_STATE_DIR)
        ),
        help="State directory for send history and source snapshots.",
    )
    parser.add_argument("--send", action="store_true", help="Retired: refuses, with a next action.")
    parser.add_argument(
        "--no-send",
        action="store_true",
        help="Compatibility no-op; this script only generates.",
    )
    parser.add_argument(
        "--recipient-name",
        default=os.environ.get(
            "HAPAX_STAKEHOLDER_REVENUE_BRIEF_RECIPIENT_NAME",
            "the stakeholder",
        ),
        help="Display name used in generated document metadata.",
    )
    parser.add_argument(
        "--timezone",
        default=os.environ.get("HAPAX_TIMEZONE", "America/Chicago"),
        help="IANA timezone for generated timestamps.",
    )
    parser.add_argument(
        "--summary-line",
        action="append",
        default=[],
        help="Explicit change-summary bullet to prepend. May be repeated.",
    )
    parser.add_argument(
        "--delivery-note",
        help="Optional note included near the top of the generated document.",
    )
    return parser


def _config_from_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> BriefConfig:
    if args.send:
        parser.error(SEND_RETIRED)

    try:
        timezone = ZoneInfo(args.timezone)
    except Exception as exc:
        parser.error(f"invalid timezone {args.timezone!r}: {exc}")

    return BriefConfig(
        source_path=args.source,
        generated_dir=args.generated_dir,
        state_dir=args.state_dir,
        timezone=timezone,
        recipient_name=args.recipient_name,
        delivery_note=args.delivery_note,
        summary_lines=tuple(args.summary_line),
    )


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    config = _config_from_args(args, parser)
    result = run(config)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
