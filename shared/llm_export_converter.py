"""llm_export_converter.py — Convert LLM platform data exports to markdown.

Supports Claude.ai and Gemini (Google Takeout) data exports (ZIP files).
Outputs markdown files with YAML frontmatter into the RAG source directory,
where existing infrastructure (watchdog ingest + profiler) picks them up
automatically.

Usage:
    uv run python -m shared.llm_export_converter --platform claude ~/Downloads/export.zip
    uv run python -m shared.llm_export_converter --platform gemini takeout.zip --dry-run
    uv run python -m shared.llm_export_converter --platform gemini takeout.zip --since 2025-01-01
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from shared.config import RAG_SOURCES_DIR

log = logging.getLogger("llm-export")

DEFAULT_OUTPUT_DIR = RAG_SOURCES_DIR / "llm-conversations"


# ── Data structures ──────────────────────────────────────────────────────────


@dataclass
class Message:
    role: str  # "user" | "assistant"
    content: str
    timestamp: str = ""  # ISO 8601 or empty
    attachments: list[str] = field(default_factory=list)  # filenames (Claude)


@dataclass
class Conversation:
    id: str
    title: str
    platform: str  # "claude" | "gemini"
    created_at: str
    updated_at: str
    messages: list[Message] = field(default_factory=list)


@dataclass
class ConvertResult:
    total: int
    written: int
    skipped: int
    output_dir: Path


# ── Filename sanitization ────────────────────────────────────────────────────


def sanitize_filename(name: str) -> str:
    """Convert a string to a filesystem-safe filename, truncated to 64 chars."""
    # Replace anything that isn't alphanumeric, hyphen, or underscore
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "-", name)
    # Collapse multiple hyphens
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    # Strip leading/trailing hyphens
    cleaned = cleaned.strip("-")
    # Truncate
    if len(cleaned) > 64:
        cleaned = cleaned[:64].rstrip("-")
    return cleaned or "untitled"


# ── Platform parsers ─────────────────────────────────────────────────────────


def parse_claude_zip(zip_path: Path) -> list[Conversation]:
    """Parse a Claude.ai data export ZIP.

    Expects conversations.json at the ZIP root with structure:
    [{uuid, name, created_at, updated_at, chat_messages: [{sender, text, created_at, attachments}]}]
    """
    with zipfile.ZipFile(zip_path) as zf:
        try:
            raw = zf.read("conversations.json")
        except KeyError:
            log.warning("No conversations.json found in %s", zip_path)
            return []

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        log.error("Invalid JSON in conversations.json: %s", e)
        return []

    if not isinstance(data, list):
        log.error("conversations.json is not a list")
        return []

    conversations: list[Conversation] = []
    for entry in data:
        conv_id = entry.get("uuid", entry.get("id", ""))
        if not conv_id:
            continue

        messages: list[Message] = []
        for msg in entry.get("chat_messages", []):
            sender = msg.get("sender", "")
            # Normalize: "human" (older exports) and "user" both → "user"
            if sender in ("human", "user"):
                role = "user"
            elif sender == "assistant":
                role = "assistant"
            else:
                continue

            text = msg.get("text", "")
            if not text:
                continue

            attachment_names = [
                a.get("file_name", "") for a in msg.get("attachments", []) if a.get("file_name")
            ]

            messages.append(
                Message(
                    role=role,
                    content=text,
                    timestamp=msg.get("created_at", ""),
                    attachments=attachment_names,
                )
            )

        conversations.append(
            Conversation(
                id=conv_id,
                title=entry.get("name", "") or "Untitled",
                platform="claude",
                created_at=entry.get("created_at", ""),
                updated_at=entry.get("updated_at", ""),
                messages=messages,
            )
        )

    return conversations


def parse_gemini_zip(zip_path: Path) -> list[Conversation]:
    """Parse a Google Gemini (Takeout) data export ZIP.

    Expects JSON files under a Takeout/ directory structure. Each JSON file
    contains a single conversation with messages using author: "user"|"model".
    """
    conversations: list[Conversation] = []

    with zipfile.ZipFile(zip_path) as zf:
        json_files = [n for n in zf.namelist() if n.endswith(".json") and not n.endswith("/")]

        for name in sorted(json_files):
            try:
                raw = zf.read(name)
                data = json.loads(raw)
            except (json.JSONDecodeError, KeyError):
                continue

            if not isinstance(data, dict):
                continue

            conv_id = data.get("id", Path(name).stem)
            messages: list[Message] = []

            for msg in data.get("messages", []):
                author = msg.get("author", "")
                if author == "model":
                    role = "assistant"
                elif author == "user":
                    role = "user"
                else:
                    continue

                # Content can be a string or nested in parts
                content = msg.get("content", "")
                if not content and "parts" in msg:
                    parts = msg["parts"]
                    if isinstance(parts, list):
                        content = " ".join(
                            p.get("text", "") if isinstance(p, dict) else str(p) for p in parts
                        ).strip()

                if not content:
                    continue

                messages.append(
                    Message(
                        role=role,
                        content=content,
                        timestamp=msg.get("create_time", msg.get("timestamp", "")),
                    )
                )

            title = data.get("title", "") or data.get("name", "") or Path(name).stem
            conversations.append(
                Conversation(
                    id=conv_id,
                    title=title,
                    platform="gemini",
                    created_at=data.get("create_time", ""),
                    updated_at=data.get("update_time", data.get("create_time", "")),
                    messages=messages,
                )
            )

    return conversations


PARSERS = {
    "claude": parse_claude_zip,
    "gemini": parse_gemini_zip,
}


# ── Markdown rendering ──────────────────────────────────────────────────────


def conversation_to_markdown(conv: Conversation) -> str:
    """Render a Conversation as markdown with YAML frontmatter."""
    # Escape quotes in title for YAML
    safe_title = conv.title.replace('"', '\\"')

    lines = [
        "---",
        f"platform: {conv.platform}",
        f"conversation_id: {conv.id}",
        f'title: "{safe_title}"',
        f"created_at: {conv.created_at}",
        f"updated_at: {conv.updated_at}",
        f"message_count: {len(conv.messages)}",
        "---",
        "",
    ]

    for msg in conv.messages:
        # Header: ## Role (timestamp)
        ts_part = f" ({msg.timestamp})" if msg.timestamp else ""
        role_display = msg.role.capitalize()
        lines.append(f"## {role_display}{ts_part}")
        lines.append("")
        lines.append(msg.content)

        # Attachments (Claude)
        if msg.attachments:
            lines.append("")
            lines.append("**Attachments:**")
            for att in msg.attachments:
                lines.append(f"- {att}")

        lines.append("")

    return "\n".join(lines)


# ── Conversion orchestrator ──────────────────────────────────────────────────


def convert_export(
    zip_path: Path,
    platform: str,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    since: str = "",
    dry_run: bool = False,
) -> ConvertResult:
    """Convert an LLM platform export ZIP to markdown files.

    Args:
        zip_path: Path to the export ZIP file.
        platform: One of "claude", "gemini".
        output_dir: Base output directory. Files go to {output_dir}/{platform}/.
        since: ISO date string — skip conversations created before this date.
        dry_run: If True, don't write files, just report what would be written.

    Returns:
        ConvertResult with counts and output directory.
    """
    parser = PARSERS.get(platform)
    if not parser:
        raise ValueError(f"Unknown platform: {platform!r}. Choose from: {', '.join(PARSERS)}")

    conversations = parser(zip_path)
    total = len(conversations)
    written = 0
    skipped = 0

    platform_dir = output_dir / platform

    # Filter by date if --since specified
    since_dt: datetime | None = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
        except ValueError:
            log.warning("Invalid --since date %r, ignoring filter", since)

    for conv in conversations:
        # Date filter
        if since_dt and conv.created_at:
            try:
                conv_dt = datetime.fromisoformat(conv.created_at.replace("Z", "+00:00"))
                if conv_dt.replace(tzinfo=None) < since_dt.replace(tzinfo=None):
                    skipped += 1
                    continue
            except ValueError:
                pass  # Can't parse date, include it

        # Skip empty conversations
        if not conv.messages:
            skipped += 1
            continue

        filename = sanitize_filename(conv.id) + ".md"
        filepath = platform_dir / filename

        if dry_run:
            log.info("[dry-run] Would write %s (%d messages)", filepath, len(conv.messages))
            written += 1
            continue

        platform_dir.mkdir(parents=True, exist_ok=True)
        md = conversation_to_markdown(conv)
        filepath.write_text(md, encoding="utf-8")
        written += 1
        log.debug("Wrote %s (%d messages)", filepath, len(conv.messages))

    return ConvertResult(
        total=total,
        written=written,
        skipped=skipped,
        output_dir=platform_dir,
    )


# ── CLI ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert LLM platform data exports to markdown for RAG ingestion",
        prog="python -m shared.llm_export_converter",
    )
    parser.add_argument("zip_path", type=Path, help="Path to the export ZIP file")
    parser.add_argument("--platform", required=True, choices=list(PARSERS), help="Source platform")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--since",
        default="",
        help="Only include conversations created after this date (ISO format)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be written without writing"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")

    args = parser.parse_args()

    from shared.log_setup import configure_logging

    configure_logging(agent="llm-export", level="DEBUG" if args.verbose else None)

    if not args.zip_path.exists():
        log.error("File not found: %s", args.zip_path)
        sys.exit(1)

    if not zipfile.is_zipfile(args.zip_path):
        log.error("Not a valid ZIP file: %s", args.zip_path)
        sys.exit(1)

    result = convert_export(
        zip_path=args.zip_path,
        platform=args.platform,
        output_dir=args.output_dir,
        since=args.since,
        dry_run=args.dry_run,
    )

    prefix = "[dry-run] " if args.dry_run else ""
    print(f"{prefix}{result.written}/{result.total} conversations written to {result.output_dir}")
    if result.skipped:
        print(f"{prefix}{result.skipped} skipped (empty or filtered)")


if __name__ == "__main__":
    main()
