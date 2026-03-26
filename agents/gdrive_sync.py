"""Google Drive RAG sync — smart tiered strategy.

Usage:
    uv run python -m agents.gdrive_sync --auth        # One-time OAuth consent
    uv run python -m agents.gdrive_sync --full-scan   # First run, full enumeration
    uv run python -m agents.gdrive_sync --auto        # Incremental sync
    uv run python -m agents.gdrive_sync --fetch ID    # Download specific file
    uv run python -m agents.gdrive_sync --stats       # Show sync state
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

try:
    from shared import langfuse_config  # noqa: F401
except ImportError:
    pass
from opentelemetry import trace

_tracer = trace.get_tracer(__name__)

log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

CACHE_DIR = Path.home() / ".cache" / "gdrive-sync"
STATE_FILE = CACHE_DIR / "state.json"
PROFILE_FACTS_FILE = CACHE_DIR / "drive-profile-facts.jsonl"
DELETIONS_LOG = CACHE_DIR / "deletions.jsonl"
RAG_SOURCES = Path.home() / "documents" / "rag-sources"
GDRIVE_DIR = RAG_SOURCES / "gdrive"
META_DIR = GDRIVE_DIR / ".meta"

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

# Size threshold: files above this get metadata-only stubs
SIZE_THRESHOLD = 25 * 1024 * 1024  # 25 MB

# Google-native export MIME mappings
EXPORT_MIMES: dict[str, tuple[str, str]] = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptx",
    ),
    "application/vnd.google-apps.drawing": ("image/png", ".png"),
}

# MIME categories for tiering
BINARY_MIME_PREFIXES = ("audio/", "video/", "application/zip", "application/x-")
# Content type inference from MIME
CONTENT_TYPE_MAP: dict[str, str] = {
    "application/vnd.google-apps.document": "document",
    "application/vnd.google-apps.spreadsheet": "spreadsheet",
    "application/vnd.google-apps.presentation": "presentation",
    "application/pdf": "document",
    "text/plain": "note",
    "text/markdown": "note",
    "text/html": "document",
}

# Modality tag inference from MIME prefix
MODALITY_MAP: dict[str, list[str]] = {
    "text/": ["text", "knowledge"],
    "application/pdf": ["text", "knowledge"],
    "application/vnd.google-apps.document": ["text", "knowledge"],
    "application/vnd.google-apps.spreadsheet": ["data", "tabular"],
    "application/vnd.google-apps.presentation": ["text", "visual"],
    "audio/": ["audio", "binary"],
    "video/": ["video", "binary"],
    "image/": ["image", "visual"],
    "application/zip": ["archive", "binary"],
    "application/x-": ["archive", "binary"],
}


# ── Schemas ──────────────────────────────────────────────────────────────────


class DriveFile(BaseModel):
    """Tracked state for a single Drive file."""

    drive_id: str
    name: str
    mime_type: str
    size: int = 0
    modified_time: str = ""
    parents: list[str] = Field(default_factory=list)
    folder_path: str = ""
    web_view_link: str = ""
    local_path: str = ""
    is_metadata_only: bool = False
    synced_at: float = 0.0
    md5: str = ""


class SyncState(BaseModel):
    """Persistent sync state across runs."""

    start_page_token: str = ""
    files: dict[str, DriveFile] = Field(default_factory=dict)  # drive_id -> DriveFile
    folder_names: dict[str, str] = Field(default_factory=dict)  # folder_id -> name
    folder_parents: dict[str, str] = Field(default_factory=dict)  # folder_id -> parent_id
    last_full_scan: float = 0.0
    last_sync: float = 0.0
    stats: dict[str, int] = Field(default_factory=dict)


# ── Auth ─────────────────────────────────────────────────────────────────────


def _get_drive_service():
    """Build authenticated Drive API service."""
    from shared.google_auth import build_service

    return build_service("drive", "v3", SCOPES)


# ── State Management ─────────────────────────────────────────────────────────


def _load_state(path: Path = STATE_FILE) -> SyncState:
    """Load sync state from disk."""
    if path.exists():
        try:
            return SyncState.model_validate_json(path.read_text())
        except Exception as exc:
            log.warning("Corrupt state file, starting fresh: %s", exc)
    return SyncState()


def _save_state(state: SyncState, path: Path = STATE_FILE) -> None:
    """Persist sync state to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(state.model_dump_json(indent=2))
    tmp.rename(path)


def _log_deletion(f: DriveFile) -> None:
    """Append deletion event to JSONL log for behavioral analysis."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _, ctype, tags = _classify_file(f.name, f.mime_type, f.size)
    entry = json.dumps(
        {
            "drive_id": f.drive_id,
            "name": f.name,
            "folder_path": f.folder_path,
            "mime_type": f.mime_type,
            "content_type": ctype,
            "size": f.size,
            "had_local_copy": bool(f.local_path and not f.is_metadata_only),
            "deleted_at": datetime.now(UTC).isoformat(),
        }
    )
    with open(DELETIONS_LOG, "a", encoding="utf-8") as fh:
        fh.write(entry + "\n")
    log.info("Logged deletion: %s (%s)", f.name, f.folder_path)


# ── Folder Resolution ────────────────────────────────────────────────────────


def _resolve_folder_path(
    folder_id: str,
    folder_names: dict[str, str],
    folder_parents: dict[str, str],
    _seen: set[str] | None = None,
) -> str:
    """Build full folder path by walking parent chain."""
    if _seen is None:
        _seen = set()
    if folder_id in _seen:
        return folder_names.get(folder_id, "")
    _seen.add(folder_id)
    name = folder_names.get(folder_id, "")
    parent = folder_parents.get(folder_id)
    if parent and parent in folder_names:
        parent_path = _resolve_folder_path(parent, folder_names, folder_parents, _seen)
        return f"{parent_path}/{name}" if parent_path else name
    return name


# ── MIME Classification ──────────────────────────────────────────────────────


def _classify_file(
    name: str,
    mime_type: str,
    size: int,
) -> tuple[str, str, list[str]]:
    """Classify file into tier, content_type, and modality_tags.

    Returns:
        (tier, content_type, modality_tags)
        tier: "document" (download) or "metadata_only" (stub)
    """
    # Google-native formats are always documents (exported, no raw size)
    if mime_type in EXPORT_MIMES:
        ctype = CONTENT_TYPE_MAP.get(mime_type, "document")
        tags = _infer_modality(mime_type)
        return "document", ctype, tags

    # Binary MIME prefixes -> always metadata-only regardless of size
    for prefix in BINARY_MIME_PREFIXES:
        if mime_type.startswith(prefix):
            ctype = _infer_content_type(mime_type, name)
            tags = _infer_modality(mime_type)
            return "metadata_only", ctype, tags

    # Size-based tiering for everything else
    if size > SIZE_THRESHOLD:
        ctype = _infer_content_type(mime_type, name)
        tags = _infer_modality(mime_type)
        return "metadata_only", ctype, tags

    ctype = _infer_content_type(mime_type, name)
    tags = _infer_modality(mime_type)
    return "document", ctype, tags


def _infer_content_type(mime_type: str, name: str) -> str:
    """Infer content_type from MIME or filename."""
    if mime_type in CONTENT_TYPE_MAP:
        return CONTENT_TYPE_MAP[mime_type]
    if mime_type.startswith("audio/"):
        return "audio"
    if mime_type.startswith("video/"):
        return "video"
    if mime_type.startswith("image/"):
        return "image"
    ext = Path(name).suffix.lower()
    if ext in {".md", ".txt"}:
        return "note"
    if ext in {".pdf", ".docx", ".html"}:
        return "document"
    if ext in {".xlsx", ".csv"}:
        return "spreadsheet"
    return "file"


def _infer_modality(mime_type: str) -> list[str]:
    """Infer modality_tags from MIME type."""
    for prefix, tags in MODALITY_MAP.items():
        if mime_type.startswith(prefix) or mime_type == prefix:
            return list(tags)
    return ["binary"]


# ── Metadata Stub Generation ─────────────────────────────────────────────────


def _generate_metadata_stub(f: DriveFile) -> str:
    """Generate a markdown metadata stub for a binary/large file."""
    _, ctype, tags = _classify_file(f.name, f.mime_type, f.size)

    # Parse folder path into categories list
    categories = [p for p in f.folder_path.split("/") if p] if f.folder_path else []

    # Format size
    if f.size >= 1_073_741_824:
        size_str = f"{f.size / 1_073_741_824:.1f} GB"
    elif f.size >= 1_048_576:
        size_str = f"{f.size / 1_048_576:.1f} MB"
    elif f.size >= 1024:
        size_str = f"{f.size / 1024:.1f} KB"
    else:
        size_str = f"{f.size} bytes"

    # Parse timestamp
    ts = f.modified_time.replace("Z", "+00:00") if f.modified_time else ""
    if ts:
        try:
            dt = datetime.fromisoformat(ts)
            ts_display = dt.strftime("%Y-%m-%d %H:%M UTC")
            ts_frontmatter = dt.strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            ts_display = f.modified_time
            ts_frontmatter = f.modified_time
    else:
        ts_display = "unknown"
        ts_frontmatter = ""

    categories_str = "[" + ", ".join(categories) + "]" if categories else "[]"
    tags_str = "[" + ", ".join(tags) + "]"
    link = f.web_view_link or f"https://drive.google.com/file/d/{f.drive_id}/view"
    location = f.folder_path or "My Drive"

    return f"""---
platform: google
service: drive
content_type: {ctype}
source_service: gdrive
source_platform: google
record_id: {f.drive_id}
timestamp: {ts_frontmatter}
modality_tags: {tags_str}
categories: {categories_str}
gdrive_id: {f.drive_id}
gdrive_link: {link}
mime_type: {f.mime_type}
file_size: {f.size}
---

# {f.name}

**Location:** {location}
**Size:** {size_str}
**Type:** {f.mime_type}
**Modified:** {ts_display}
**Drive link:** {link}
"""


# ── Drive API Operations ─────────────────────────────────────────────────────

FIELDS = "nextPageToken, files(id, name, mimeType, size, modifiedTime, parents, webViewLink, md5Checksum)"


def _full_scan(service, state: SyncState) -> int:
    """Enumerate all Drive files and folders. Returns file count."""
    log.info("Starting full Drive scan...")

    # Phase 1: Build folder tree
    log.info("Building folder tree...")
    page_token = None
    while True:
        resp = (
            service.files()
            .list(
                q="mimeType='application/vnd.google-apps.folder' and trashed=false",
                fields="nextPageToken, files(id, name, parents)",
                pageSize=1000,
                pageToken=page_token,
            )
            .execute()
        )
        for f in resp.get("files", []):
            state.folder_names[f["id"]] = f["name"]
            if f.get("parents"):
                state.folder_parents[f["id"]] = f["parents"][0]
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    log.info("Found %d folders", len(state.folder_names))

    # Phase 2: Enumerate all non-folder files
    count = 0
    page_token = None
    while True:
        resp = (
            service.files()
            .list(
                q="mimeType!='application/vnd.google-apps.folder' and trashed=false",
                fields=FIELDS,
                pageSize=1000,
                pageToken=page_token,
            )
            .execute()
        )
        for f in resp.get("files", []):
            drive_id = f["id"]
            parent_id = f.get("parents", [""])[0] if f.get("parents") else ""
            folder_path = (
                _resolve_folder_path(parent_id, state.folder_names, state.folder_parents)
                if parent_id
                else ""
            )

            state.files[drive_id] = DriveFile(
                drive_id=drive_id,
                name=f["name"],
                mime_type=f.get("mimeType", ""),
                size=int(f.get("size", 0)),
                modified_time=f.get("modifiedTime", ""),
                parents=f.get("parents", []),
                folder_path=folder_path,
                web_view_link=f.get("webViewLink", ""),
                md5=f.get("md5Checksum", ""),
            )
            count += 1
            if count % 500 == 0:
                log.info("Scanned %d files...", count)

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    # Get initial change token for future incremental syncs
    resp = service.changes().getStartPageToken().execute()
    state.start_page_token = resp["startPageToken"]
    state.last_full_scan = time.time()

    log.info("Full scan complete: %d files, %d folders", count, len(state.folder_names))
    return count


def _incremental_sync(service, state: SyncState) -> list[str]:
    """Process changes since last sync. Returns list of changed drive_ids."""
    if not state.start_page_token:
        log.warning("No start page token — run --full-scan first")
        return []

    changed_ids: list[str] = []
    page_token = state.start_page_token

    while True:
        resp = (
            service.changes()
            .list(
                pageToken=page_token,
                fields="nextPageToken, newStartPageToken, changes(fileId, removed, file(id, name, mimeType, size, modifiedTime, parents, webViewLink, md5Checksum))",
                pageSize=1000,
                includeRemoved=True,
            )
            .execute()
        )

        for change in resp.get("changes", []):
            file_id = change["fileId"]

            if change.get("removed"):
                if file_id in state.files:
                    df = state.files.pop(file_id)
                    _log_deletion(df)
                    if df.local_path:
                        lp = Path(df.local_path)
                        if lp.exists():
                            lp.unlink()
                            log.info("Deleted: %s", lp)
                continue

            f = change.get("file")
            if not f:
                continue

            # Handle folder updates
            if f.get("mimeType") == "application/vnd.google-apps.folder":
                state.folder_names[f["id"]] = f["name"]
                if f.get("parents"):
                    state.folder_parents[f["id"]] = f["parents"][0]
                continue

            parent_id = f.get("parents", [""])[0] if f.get("parents") else ""
            folder_path = (
                _resolve_folder_path(parent_id, state.folder_names, state.folder_parents)
                if parent_id
                else ""
            )

            existing = state.files.get(file_id)
            new_md5 = f.get("md5Checksum", "")

            # Skip if unchanged
            if existing and existing.md5 and new_md5 and existing.md5 == new_md5:
                continue

            state.files[file_id] = DriveFile(
                drive_id=file_id,
                name=f["name"],
                mime_type=f.get("mimeType", ""),
                size=int(f.get("size", 0)),
                modified_time=f.get("modifiedTime", ""),
                parents=f.get("parents", []),
                folder_path=folder_path,
                web_view_link=f.get("webViewLink", ""),
                md5=new_md5,
                local_path=existing.local_path if existing else "",
                is_metadata_only=existing.is_metadata_only if existing else False,
            )
            changed_ids.append(file_id)

        page_token = resp.get("nextPageToken")
        if not page_token:
            state.start_page_token = resp.get("newStartPageToken", state.start_page_token)
            break

    state.last_sync = time.time()
    log.info("Incremental sync: %d changes", len(changed_ids))
    return changed_ids


# ── File Operations ──────────────────────────────────────────────────────────


def _sync_file(service, f: DriveFile, state: SyncState) -> bool:
    """Sync a single file — download, export, or write metadata stub.

    Returns True if file was written/updated.
    """
    tier, _, _ = _classify_file(f.name, f.mime_type, f.size)

    if tier == "metadata_only":
        return _write_metadata_stub(f, state)
    else:
        return _download_or_export(service, f, state)


def _write_metadata_stub(f: DriveFile, state: SyncState) -> bool:
    """Write a metadata-only markdown stub for a binary/large file."""
    META_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = f.name.replace("/", "_")
    # Include short drive_id suffix to prevent filename collisions across folders
    stub_path = META_DIR / f"{safe_name}_{f.drive_id[:8]}.md"

    content = _generate_metadata_stub(f)
    stub_path.write_text(content, encoding="utf-8")

    f.local_path = str(stub_path)
    f.is_metadata_only = True
    f.synced_at = time.time()
    state.files[f.drive_id] = f
    log.debug("Wrote metadata stub: %s", stub_path.name)
    return True


def _download_or_export(service, f: DriveFile, state: SyncState) -> bool:
    """Download a regular file or export a Google-native file."""
    # Build local path preserving folder structure
    if f.folder_path:
        local_dir = GDRIVE_DIR / f.folder_path
    else:
        local_dir = GDRIVE_DIR

    local_dir.mkdir(parents=True, exist_ok=True)

    if f.mime_type in EXPORT_MIMES:
        export_mime, ext = EXPORT_MIMES[f.mime_type]
        safe_name = f.name.replace("/", "_")
        local_path = local_dir / f"{safe_name}{ext}"
        try:
            content = service.files().export(fileId=f.drive_id, mimeType=export_mime).execute()
            local_path.write_bytes(content)
        except Exception as exc:
            log.error("Export failed for %s: %s", f.name, exc)
            # Fall back to metadata stub
            return _write_metadata_stub(f, state)
    else:
        safe_name = f.name.replace("/", "_")
        local_path = local_dir / safe_name
        try:
            import io

            from googleapiclient.http import MediaIoBaseDownload

            request = service.files().get_media(fileId=f.drive_id)
            buf = io.BytesIO()
            downloader = MediaIoBaseDownload(buf, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            local_path.write_bytes(buf.getvalue())
        except Exception as exc:
            log.error("Download failed for %s: %s", f.name, exc)
            return _write_metadata_stub(f, state)

    f.local_path = str(local_path)
    f.is_metadata_only = False
    f.synced_at = time.time()
    state.files[f.drive_id] = f
    log.debug("Downloaded: %s -> %s", f.name, local_path)
    return True


def _fetch_single(service, drive_id: str, state: SyncState) -> bool:
    """On-demand download of a specific file (even if >25MB)."""
    if drive_id not in state.files:
        # Fetch file metadata from API
        try:
            f_data = (
                service.files()
                .get(
                    fileId=drive_id,
                    fields="id, name, mimeType, size, modifiedTime, parents, webViewLink, md5Checksum",
                )
                .execute()
            )
        except Exception as exc:
            log.error("Failed to fetch metadata for %s: %s", drive_id, exc)
            return False
        parent_id = f_data.get("parents", [""])[0] if f_data.get("parents") else ""
        folder_path = (
            _resolve_folder_path(parent_id, state.folder_names, state.folder_parents)
            if parent_id
            else ""
        )
        df = DriveFile(
            drive_id=drive_id,
            name=f_data["name"],
            mime_type=f_data.get("mimeType", ""),
            size=int(f_data.get("size", 0)),
            modified_time=f_data.get("modifiedTime", ""),
            parents=f_data.get("parents", []),
            folder_path=folder_path,
            web_view_link=f_data.get("webViewLink", ""),
            md5=f_data.get("md5Checksum", ""),
        )
    else:
        df = state.files[drive_id]

    # Force download regardless of size
    return _download_or_export(service, df, state)


# ── Profiler Integration ─────────────────────────────────────────────────────


def _generate_profile_facts(state: SyncState) -> list[dict]:
    """Generate deterministic profile facts from Drive state."""
    from collections import Counter

    mime_counts: Counter[str] = Counter()
    folder_counts: Counter[str] = Counter()
    total_size = 0

    for f in state.files.values():
        # Count MIME categories
        if f.mime_type.startswith("audio/"):
            mime_counts["audio"] += 1
        elif f.mime_type.startswith("video/"):
            mime_counts["video"] += 1
        elif f.mime_type.startswith("image/"):
            mime_counts["image"] += 1
        elif (
            f.mime_type in EXPORT_MIMES
            or f.mime_type.startswith("text/")
            or f.mime_type == "application/pdf"
        ):
            mime_counts["documents"] += 1
        else:
            mime_counts["other"] += 1

        total_size += f.size

        # Top-level folder
        if f.folder_path:
            top = f.folder_path.split("/")[0]
            if top and top != "My Drive":
                folder_counts[top] += 1

    facts = []
    source = "gdrive-sync:drive-profile-facts"

    # File type distribution
    if mime_counts:
        total = sum(mime_counts.values())
        dist = ", ".join(f"{k} ({v / total:.0%})" for k, v in mime_counts.most_common(5))
        facts.append(
            {
                "dimension": "information_seeking",
                "key": "gdrive_file_types",
                "value": dist,
                "confidence": 0.95,
                "source": source,
                "evidence": f"Distribution across {total} Drive files",
            }
        )

    # Active folders
    if folder_counts:
        top_folders = ", ".join(f[0] for f in folder_counts.most_common(10))
        facts.append(
            {
                "dimension": "information_seeking",
                "key": "gdrive_active_folders",
                "value": top_folders,
                "confidence": 0.95,
                "source": source,
                "evidence": f"Top folders by file count across {sum(folder_counts.values())} files",
            }
        )

    # Total storage
    if total_size:
        gb = total_size / (1024**3)
        facts.append(
            {
                "dimension": "tool_usage",
                "key": "gdrive_storage_usage",
                "value": f"{gb:.1f} GB across {len(state.files)} files",
                "confidence": 0.95,
                "source": source,
                "evidence": "Computed from Drive API file sizes",
            }
        )

    # Deletion patterns (from log)
    if DELETIONS_LOG.exists():
        del_counts: Counter[str] = Counter()
        del_total = 0
        for line in DELETIONS_LOG.read_text().splitlines():
            try:
                entry = json.loads(line)
                del_total += 1
                ct = entry.get("content_type", "unknown")
                del_counts[ct] += 1
            except json.JSONDecodeError:
                continue
        if del_total:
            dist = ", ".join(f"{k} ({v})" for k, v in del_counts.most_common(5))
            facts.append(
                {
                    "dimension": "work_patterns",
                    "key": "gdrive_deletion_patterns",
                    "value": f"{del_total} deletions: {dist}",
                    "confidence": 0.95,
                    "source": source,
                    "evidence": f"Accumulated from {del_total} Drive deletion events",
                }
            )

    return facts


def _write_profile_facts(state: SyncState) -> None:
    """Write profile facts JSONL for profiler bridge consumption."""
    facts = _generate_profile_facts(state)
    if not facts:
        return
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(PROFILE_FACTS_FILE, "w", encoding="utf-8") as fh:
        for fact in facts:
            fh.write(json.dumps(fact) + "\n")
    log.info("Wrote %d profile facts to %s", len(facts), PROFILE_FACTS_FILE)


# ── Stats ────────────────────────────────────────────────────────────────────


def _print_stats(state: SyncState) -> None:
    """Print sync statistics."""
    from collections import Counter

    total = len(state.files)
    meta_only = sum(1 for f in state.files.values() if f.is_metadata_only)
    downloaded = sum(1 for f in state.files.values() if f.local_path and not f.is_metadata_only)
    pending = total - meta_only - downloaded

    mime_cats: Counter[str] = Counter()
    total_size = 0
    for f in state.files.values():
        total_size += f.size
        if f.mime_type.startswith("audio/"):
            mime_cats["audio"] += 1
        elif f.mime_type.startswith("video/"):
            mime_cats["video"] += 1
        elif f.mime_type.startswith("image/"):
            mime_cats["image"] += 1
        else:
            mime_cats["documents/other"] += 1

    print("Google Drive Sync State")
    print(f"{'=' * 40}")
    print(f"Total files:     {total:,}")
    print(f"Downloaded:      {downloaded:,}")
    print(f"Metadata-only:   {meta_only:,}")
    print(f"Pending sync:    {pending:,}")
    print(f"Total size:      {total_size / (1024**3):.1f} GB")
    print(
        f"Last full scan:  {datetime.fromtimestamp(state.last_full_scan, tz=UTC).strftime('%Y-%m-%d %H:%M UTC') if state.last_full_scan else 'never'}"
    )
    print(
        f"Last sync:       {datetime.fromtimestamp(state.last_sync, tz=UTC).strftime('%Y-%m-%d %H:%M UTC') if state.last_sync else 'never'}"
    )
    print("\nBy type:")
    for cat, count in mime_cats.most_common():
        print(f"  {cat}: {count:,}")


# ── Orchestration ────────────────────────────────────────────────────────────


def run_auth() -> None:
    """Interactive OAuth consent flow."""
    print("Authenticating with Google Drive...")
    service = _get_drive_service()
    about = service.about().get(fields="user").execute()
    print(f"Authenticated as: {about['user']['emailAddress']}")
    print("Token saved to pass store (gdrive/token).")


def run_full_scan() -> None:
    """Full scan + sync all files."""
    from shared.notify import send_notification

    service = _get_drive_service()
    state = _load_state()

    count = _full_scan(service, state)
    _save_state(state)

    # Sync files
    synced = 0
    errors = 0
    for _drive_id, f in state.files.items():
        if f.synced_at > 0:
            continue
        try:
            if _sync_file(service, f, state):
                synced += 1
        except Exception as exc:
            log.error("Failed to sync %s: %s", f.name, exc)
            errors += 1
        if synced % 100 == 0 and synced > 0:
            _save_state(state)
            log.info("Progress: %d/%d synced", synced, count)

    _save_state(state)
    _write_profile_facts(state)

    # Sensor protocol — write state + impingement
    from shared.sensor_protocol import emit_sensor_impingement, write_sensor_state

    write_sensor_state("gdrive", {"file_count": len(state.files), "last_sync": time.time()})
    emit_sensor_impingement("gdrive", "information_seeking", ["full_scan"])

    msg = f"Full scan: {count} files found, {synced} synced, {errors} errors"
    log.info(msg)
    send_notification("GDrive Sync", msg, tags=["cloud"])


def run_auto() -> None:
    """Incremental sync — changes since last run."""
    from shared.notify import send_notification

    service = _get_drive_service()
    state = _load_state()

    if not state.start_page_token:
        log.info("No previous sync state — running full scan instead")
        run_full_scan()
        return

    changed_ids = _incremental_sync(service, state)

    synced = 0
    errors = 0
    for drive_id in changed_ids:
        f = state.files.get(drive_id)
        if not f:
            continue
        try:
            if _sync_file(service, f, state):
                synced += 1
        except Exception as exc:
            log.error("Failed to sync %s: %s", f.name, exc)
            errors += 1

    _save_state(state)
    _write_profile_facts(state)

    # Sensor protocol — write state + impingement on changes
    from shared.sensor_protocol import emit_sensor_impingement, write_sensor_state

    write_sensor_state("gdrive", {"file_count": len(state.files), "last_sync": time.time()})
    if synced:
        emit_sensor_impingement("gdrive", "information_seeking", ["incremental_sync"])

    if synced or errors:
        msg = f"Sync: {synced} updated, {errors} errors (of {len(changed_ids)} changes)"
        log.info(msg)
        send_notification("GDrive Sync", msg, tags=["cloud"])
    else:
        log.info("No changes to sync")


def run_fetch(drive_id: str) -> None:
    """On-demand download of a specific file."""
    service = _get_drive_service()
    state = _load_state()

    if _fetch_single(service, drive_id, state):
        f = state.files[drive_id]
        _save_state(state)
        print(f"Downloaded: {f.name} -> {f.local_path}")
    else:
        print(f"Failed to fetch {drive_id}", file=sys.stderr)
        sys.exit(1)


def run_stats() -> None:
    """Display sync statistics."""
    state = _load_state()
    if not state.files:
        print("No sync state found. Run --full-scan first.")
        return
    _print_stats(state)


# ── CLI ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Google Drive RAG sync")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--auth", action="store_true", help="Run OAuth consent flow")
    group.add_argument("--full-scan", action="store_true", help="Full Drive scan + sync")
    group.add_argument("--auto", action="store_true", help="Incremental sync")
    group.add_argument("--fetch", metavar="DRIVE_ID", help="Download specific file")
    group.add_argument("--stats", action="store_true", help="Show sync statistics")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    from shared.log_setup import configure_logging

    configure_logging(agent="gdrive-sync", level="DEBUG" if args.verbose else None)

    action = (
        "auth"
        if args.auth
        else "full_scan"
        if args.full_scan
        else "auto"
        if args.auto
        else "fetch"
        if args.fetch
        else "stats"
    )
    with _tracer.start_as_current_span(
        f"gdrive_sync.{action}",
        attributes={"agent.name": "gdrive_sync", "agent.repo": "hapax-council"},
    ):
        if args.auth:
            run_auth()
        elif args.full_scan:
            run_full_scan()
        elif args.auto:
            run_auto()
        elif args.fetch:
            run_fetch(args.fetch)
        elif args.stats:
            run_stats()


if __name__ == "__main__":
    main()
