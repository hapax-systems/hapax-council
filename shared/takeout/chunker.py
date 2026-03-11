"""chunker.py — Convert NormalizedRecords to output formats.

Two output paths:
- Unstructured → markdown files with YAML frontmatter (for RAG + profiler)
- Structured → JSONL records (for deterministic profiler mapping)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import IO

from shared.config import RAG_SOURCES_DIR
from shared.takeout.models import NormalizedRecord

log = logging.getLogger("takeout")

DEFAULT_OUTPUT_DIR = RAG_SOURCES_DIR / "takeout"
STRUCTURED_OUTPUT = (
    Path(__file__).resolve().parent.parent.parent / "profiles" / "takeout-structured.jsonl"
)


class StructuredWriter:
    """Buffered, dedup-aware writer for structured JSONL records.

    Keeps the file handle open for the lifetime of the context manager
    (eliminates per-record open/close overhead) and tracks record IDs
    to skip duplicates on re-runs.
    """

    def __init__(self, path: Path, *, dry_run: bool = False) -> None:
        self._path = path
        self._dry_run = dry_run
        self._seen: set[str] = set()
        self._fh: IO[str] | None = None
        self.written = 0
        self.deduped = 0

    def __enter__(self) -> StructuredWriter:
        if self._path.exists():
            with open(self._path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        record = json.loads(stripped)
                        rid = record.get("record_id", "")
                        if rid:
                            self._seen.add(rid)
                    except json.JSONDecodeError:
                        continue
            if self._seen:
                log.debug("StructuredWriter: loaded %d existing record IDs", len(self._seen))

        if not self._dry_run:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(self._path, "a", encoding="utf-8")

        return self

    def __exit__(self, *exc: object) -> bool:
        if self._fh:
            self._fh.close()
            self._fh = None
        if self.deduped:
            log.info("StructuredWriter: skipped %d duplicate records", self.deduped)
        return False

    def write(self, record: NormalizedRecord) -> bool:
        """Write a structured record. Returns True if written, False if duplicate."""
        if record.record_id in self._seen:
            self.deduped += 1
            return False

        self._seen.add(record.record_id)

        if self._dry_run:
            log.info("[dry-run] Would append to %s", self._path)
            self.written += 1
            return True

        line = record_to_jsonl(record)
        assert self._fh is not None
        self._fh.write(line + "\n")
        self.written += 1
        return True

    def remove_ids(self, ids_to_remove: set[str]) -> None:
        """Remove IDs from the seen set (used after resume purge)."""
        self._seen -= ids_to_remove


def _yaml_list(items: list[str]) -> str:
    """Format a list for YAML inline syntax, quoting items with special chars."""
    escaped = []
    for item in items:
        if any(c in item for c in ",:[]{}&*#!|\"'"):
            safe = item.replace("\\", "\\\\").replace('"', '\\"')
            escaped.append(f'"{safe}"')
        else:
            escaped.append(item)
    return "[" + ", ".join(escaped) + "]"


def record_to_markdown(record: NormalizedRecord) -> str:
    """Render a NormalizedRecord as markdown with YAML frontmatter.

    The frontmatter enables downstream enrichment of Qdrant payloads
    when the RAG pipeline ingests these files.
    """
    lines = ["---"]
    lines.append(f"platform: {record.platform}")
    lines.append(f"service: {record.service}")
    lines.append(f"content_type: {record.content_type}")
    lines.append(f"record_id: {record.record_id}")

    if record.timestamp:
        lines.append(f"timestamp: {record.timestamp.isoformat()}")

    if record.modality_tags:
        tags_str = ", ".join(record.modality_tags)
        lines.append(f"modality_tags: [{tags_str}]")

    if record.people:
        lines.append(f"people: {_yaml_list(record.people)}")

    if record.location:
        lines.append(f'location: "{record.location}"')

    if record.categories:
        lines.append(f"categories: {_yaml_list(record.categories)}")

    lines.append("---")
    lines.append("")

    # Title
    lines.append(f"# {record.title}")
    lines.append("")

    # Body
    if record.text:
        lines.append(record.text)
        lines.append("")

    return "\n".join(lines)


def record_to_jsonl(record: NormalizedRecord) -> str:
    """Serialize a NormalizedRecord to a JSON line for structured output."""
    data = {
        "record_id": record.record_id,
        "platform": record.platform,
        "service": record.service,
        "title": record.title,
        "text": record.text,
        "content_type": record.content_type,
        "timestamp": record.timestamp.isoformat() if record.timestamp else None,
        "modality_tags": record.modality_tags,
        "people": record.people,
        "location": record.location,
        "categories": record.categories,
        "structured_fields": record.structured_fields,
        "data_path": record.data_path,
        "source_path": record.source_path,
    }
    return json.dumps(data, ensure_ascii=False)


def sanitize_filename(name: str) -> str:
    """Convert a string to a filesystem-safe filename, truncated to 64 chars."""
    import re

    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "-", name)
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    cleaned = cleaned.strip("-")
    if len(cleaned) > 64:
        cleaned = cleaned[:64].rstrip("-")
    return cleaned or "untitled"


def write_record(
    record: NormalizedRecord,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    structured_path: Path = STRUCTURED_OUTPUT,
    *,
    dry_run: bool = False,
    structured_writer: StructuredWriter | None = None,
) -> Path | None:
    """Write a record to the appropriate output path.

    Returns the output file path, or None for structured records
    (which append to JSONL).

    If structured_writer is provided, structured records are written
    through it (buffered + deduped). Otherwise falls back to direct
    per-record append.
    """
    if record.data_path == "unstructured":
        service_dir = output_dir / record.service
        filename = sanitize_filename(record.record_id) + ".md"
        filepath = service_dir / filename

        if dry_run:
            log.info("[dry-run] Would write %s", filepath)
            return filepath

        service_dir.mkdir(parents=True, exist_ok=True)
        md = record_to_markdown(record)
        filepath.write_text(md, encoding="utf-8")
        return filepath

    else:
        # Structured: use writer if available, else direct append
        if structured_writer:
            structured_writer.write(record)
            return None

        if dry_run:
            log.info("[dry-run] Would append to %s", structured_path)
            return None

        structured_path.parent.mkdir(parents=True, exist_ok=True)
        line = record_to_jsonl(record)
        with open(structured_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        return None
