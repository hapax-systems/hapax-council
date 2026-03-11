"""drive.py — Parser for Google Drive exports.

Drive Takeout contains the actual files. Strategy:
- Text files (.md, .txt) → read content, route unstructured
- Document files (.docx, .pdf) → metadata only (let RAG pipeline handle full parse)
- Other files → metadata only

We extract file metadata (name, size, modified date) and text content
where cheaply available. Heavy parsing (PDF, DOCX) is left to the
RAG pipeline's Docling converter.
"""

from __future__ import annotations

import logging
import zipfile
from collections.abc import Iterator
from datetime import datetime
from pathlib import PurePosixPath

from shared.takeout.models import NormalizedRecord, ServiceConfig, make_record_id

log = logging.getLogger("takeout.drive")

# Extensions we can read directly as text
TEXT_EXTENSIONS = {".md", ".txt", ".csv", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg"}

# Extensions we emit metadata-only records for
METADATA_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".pptx", ".doc", ".xls", ".ppt"}

# Extensions to skip entirely (binary, media)
SKIP_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".webp",
    ".svg",
    ".mp3",
    ".mp4",
    ".wav",
    ".flac",
    ".ogg",
    ".avi",
    ".mov",
    ".zip",
    ".tar",
    ".gz",
    ".7z",
    ".rar",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
}

MAX_TEXT_CHARS = 5000


def parse(zf: zipfile.ZipFile, config: ServiceConfig) -> Iterator[NormalizedRecord]:
    """Parse Drive files from a Takeout ZIP."""
    prefix_options = [
        "Takeout/Drive/",
        "Drive/",
    ]

    for info in zf.infolist():
        if info.is_dir():
            continue

        matched_prefix = ""
        for prefix in prefix_options:
            if info.filename.startswith(prefix):
                matched_prefix = prefix
                break

        if not matched_prefix:
            continue

        # Get relative path within Drive
        rel_path = info.filename[len(matched_prefix) :]
        if not rel_path:
            continue

        path = PurePosixPath(rel_path)
        ext = path.suffix.lower()

        if ext in SKIP_EXTENSIONS:
            continue

        if ext in TEXT_EXTENSIONS:
            record = _parse_text_file(zf, info, path, config)
        elif ext in METADATA_EXTENSIONS:
            record = _parse_metadata_only(info, path, config)
        else:
            # Unknown extension — emit metadata
            record = _parse_metadata_only(info, path, config)

        if record:
            yield record


def _parse_text_file(
    zf: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    rel_path: PurePosixPath,
    config: ServiceConfig,
) -> NormalizedRecord | None:
    """Read a text file and create an unstructured record."""
    try:
        raw = zf.read(info.filename)
        text = raw.decode("utf-8", errors="replace")
    except Exception as e:
        log.debug("Failed to read %s: %s", info.filename, e)
        return None

    if not text.strip():
        return None

    # Truncate very large files
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS] + "\n\n[truncated]"

    title = rel_path.name
    record_id = make_record_id("google", "drive", str(rel_path))

    # Try to get timestamp from ZIP metadata
    timestamp = _zip_datetime(info)

    return NormalizedRecord(
        record_id=record_id,
        platform="google",
        service="drive",
        title=title,
        text=text,
        content_type="document",
        timestamp=timestamp,
        modality_tags=list(config.modality_defaults),
        structured_fields={
            "path": str(rel_path),
            "extension": rel_path.suffix.lower(),
            "size_bytes": info.file_size,
        },
        data_path="unstructured",
        source_path=info.filename,
    )


def _parse_metadata_only(
    info: zipfile.ZipInfo,
    rel_path: PurePosixPath,
    config: ServiceConfig,
) -> NormalizedRecord:
    """Create a metadata-only record for binary/document files."""
    title = rel_path.name
    timestamp = _zip_datetime(info)
    record_id = make_record_id("google", "drive", str(rel_path))

    text = f"File: {rel_path}\nSize: {info.file_size} bytes\nType: {rel_path.suffix.lower()}"

    return NormalizedRecord(
        record_id=record_id,
        platform="google",
        service="drive",
        title=title,
        text=text,
        content_type="document",
        timestamp=timestamp,
        modality_tags=list(config.modality_defaults),
        structured_fields={
            "path": str(rel_path),
            "extension": rel_path.suffix.lower(),
            "size_bytes": info.file_size,
        },
        data_path="structured",
        source_path=info.filename,
    )


def _zip_datetime(info: zipfile.ZipInfo) -> datetime | None:
    """Extract datetime from ZipInfo.date_time tuple."""
    try:
        return datetime(*info.date_time)
    except (ValueError, TypeError):
        return None
