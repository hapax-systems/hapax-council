# Google Drive RAG Integration — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Sync Google Drive into the Hapax RAG pipeline with smart tiered strategy — full download for documents, metadata-only stubs for binaries — integrated with digest, briefing, research, and profiler agents.

**Architecture:** OAuth2 via google-api-python-client, incremental sync via Drive changes API, output to ~/documents/rag-sources/gdrive/ for existing rag-ingest file watcher pickup. Metadata stubs for large/binary files enable semantic search without downloading 400GB.

**Tech Stack:** google-api-python-client, google-auth-oauthlib, pydantic v2, shared.config (embed, get_qdrant), shared.notify, systemd user timer

**Design doc:** `docs/plans/2026-03-08-gdrive-rag-design.md`

---

## Task 1: Add Dependencies + OAuth Credential Setup

**Files:**
- Modify: `~/projects/ai-agents/pyproject.toml`
- Create: `~/projects/ai-agents/agents/gdrive_sync.py` (skeleton only)
- Create: `~/projects/ai-agents/tests/test_gdrive_sync.py`

**Step 1: Add google dependencies to pyproject.toml**

In `~/projects/ai-agents/pyproject.toml`, add to `dependencies`:

```toml
"google-api-python-client>=2.100.0",
"google-auth-oauthlib>=1.2.0",
```

**Step 2: Install dependencies**

```bash
cd ~/projects/ai-agents && uv sync
```

Expected: Clean install, no conflicts.

**Step 3: Create Google Cloud OAuth credentials**

1. Go to https://console.cloud.google.com/
2. Create project "hapax-gdrive-sync" (or reuse existing)
3. Enable "Google Drive API"
4. Create OAuth 2.0 Client ID (Desktop application type)
5. Download JSON credentials file

```bash
pass insert -m gdrive/client-secret < ~/Downloads/client_secret_*.json
```

**Step 4: Write the OAuth flow script (part of gdrive_sync.py skeleton)**

Create `~/projects/ai-agents/agents/gdrive_sync.py`:

```python
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
import hashlib
import logging
import mimetypes
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

CACHE_DIR = Path.home() / ".cache" / "gdrive-sync"
STATE_FILE = CACHE_DIR / "state.json"
PROFILE_FACTS_FILE = CACHE_DIR / "drive-profile-facts.jsonl"
RAG_SOURCES = Path.home() / "documents" / "rag-sources"
GDRIVE_DIR = RAG_SOURCES / "gdrive"
META_DIR = GDRIVE_DIR / ".meta"

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

# Size threshold: files above this get metadata-only stubs
SIZE_THRESHOLD = 25 * 1024 * 1024  # 25 MB

# Google-native export MIME mappings
EXPORT_MIMES: dict[str, tuple[str, str]] = {
    "application/vnd.google-apps.document": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
    "application/vnd.google-apps.spreadsheet": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
    "application/vnd.google-apps.presentation": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx"),
    "application/vnd.google-apps.drawing": ("image/png", ".png"),
}

# MIME categories for tiering
BINARY_MIME_PREFIXES = ("audio/", "video/", "application/zip", "application/x-")
DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".pptx", ".xlsx", ".html", ".md", ".txt", ".csv", ".json", ".yaml", ".yml"}

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
    last_full_scan: float = 0.0
    last_sync: float = 0.0
    stats: dict[str, int] = Field(default_factory=dict)


# ── Auth ─────────────────────────────────────────────────────────────────────

def _get_credentials():
    """Load or refresh OAuth2 credentials from pass store."""
    import subprocess
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    # Try loading existing token
    try:
        token_json = subprocess.check_output(
            ["pass", "show", "gdrive/token"],
            stderr=subprocess.DEVNULL,
        ).decode()
        creds = Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)
        if creds.valid:
            return creds
        if creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
            # Save refreshed token
            _save_token(creds)
            return creds
    except (subprocess.CalledProcessError, Exception):
        pass

    # No valid token — run OAuth flow
    client_json = subprocess.check_output(
        ["pass", "show", "gdrive/client-secret"],
        stderr=subprocess.DEVNULL,
    ).decode()
    flow = InstalledAppFlow.from_client_config(json.loads(client_json), SCOPES)
    creds = flow.run_local_server(port=0)
    _save_token(creds)
    return creds


def _save_token(creds) -> None:
    """Save OAuth token to pass store."""
    import subprocess
    token_data = json.dumps({
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or []),
    })
    proc = subprocess.run(
        ["pass", "insert", "-m", "gdrive/token"],
        input=token_data.encode(),
        capture_output=True,
    )
    if proc.returncode != 0:
        log.warning("Failed to save token to pass: %s", proc.stderr.decode())


def _get_drive_service():
    """Build authenticated Drive API service."""
    from googleapiclient.discovery import build
    creds = _get_credentials()
    return build("drive", "v3", credentials=creds)


# ── placeholder: remaining functions in later tasks ──
```

**Step 5: Write skeleton test**

Create `~/projects/ai-agents/tests/test_gdrive_sync.py`:

```python
"""Tests for gdrive_sync — schemas, MIME classification, metadata stubs."""
from __future__ import annotations

import pytest

from agents.gdrive_sync import (
    DriveFile,
    SyncState,
    EXPORT_MIMES,
    CONTENT_TYPE_MAP,
    SIZE_THRESHOLD,
)


def test_drive_file_defaults():
    f = DriveFile(drive_id="abc", name="test.pdf", mime_type="application/pdf")
    assert f.is_metadata_only is False
    assert f.size == 0
    assert f.folder_path == ""


def test_sync_state_empty():
    s = SyncState()
    assert s.start_page_token == ""
    assert s.files == {}


def test_export_mimes_covers_google_types():
    assert "application/vnd.google-apps.document" in EXPORT_MIMES
    assert "application/vnd.google-apps.spreadsheet" in EXPORT_MIMES
    assert "application/vnd.google-apps.presentation" in EXPORT_MIMES


def test_size_threshold():
    assert SIZE_THRESHOLD == 25 * 1024 * 1024
```

**Step 6: Run tests**

```bash
cd ~/projects/ai-agents && uv run pytest tests/test_gdrive_sync.py -v
```

Expected: 4 PASS.

**Step 7: Run OAuth flow**

```bash
cd ~/projects/ai-agents && uv run python -m agents.gdrive_sync --auth
```

This opens a browser for Google consent. After approval, token is saved to `pass show gdrive/token`.

**Step 8: Commit**

```bash
git add pyproject.toml agents/gdrive_sync.py tests/test_gdrive_sync.py
git commit -m "feat(gdrive): add skeleton module, OAuth flow, schemas, dependencies"
```

---

## Task 2: State Management + Folder Resolution

**Files:**
- Modify: `~/projects/ai-agents/agents/gdrive_sync.py`
- Modify: `~/projects/ai-agents/tests/test_gdrive_sync.py`

**Step 1: Write failing tests for state management and folder resolution**

Add to `tests/test_gdrive_sync.py`:

```python
import json
from pathlib import Path
from unittest.mock import MagicMock, patch


def test_load_state_empty(tmp_path):
    """Loading state from nonexistent file returns empty SyncState."""
    from agents.gdrive_sync import _load_state
    state = _load_state(tmp_path / "state.json")
    assert state.files == {}
    assert state.start_page_token == ""


def test_save_load_roundtrip(tmp_path):
    """State survives save/load roundtrip."""
    from agents.gdrive_sync import _load_state, _save_state
    state_file = tmp_path / "state.json"
    state = SyncState(start_page_token="tok123")
    state.files["abc"] = DriveFile(
        drive_id="abc", name="test.txt", mime_type="text/plain",
    )
    _save_state(state, state_file)
    loaded = _load_state(state_file)
    assert loaded.start_page_token == "tok123"
    assert "abc" in loaded.files


def test_resolve_folder_path():
    """Folder path resolution builds full path from parent chain."""
    from agents.gdrive_sync import _resolve_folder_path
    folder_names = {"root": "My Drive", "a": "Projects", "b": "Client X"}
    # b -> a -> root
    folder_parents = {"b": "a", "a": "root"}
    path = _resolve_folder_path("b", folder_names, folder_parents)
    assert path == "My Drive/Projects/Client X"


def test_resolve_folder_path_no_parent():
    """Folder with no parent returns just its name."""
    from agents.gdrive_sync import _resolve_folder_path
    path = _resolve_folder_path("a", {"a": "Orphan"}, {})
    assert path == "Orphan"
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_gdrive_sync.py -v -k "state or folder"
```

Expected: FAIL (functions not defined).

**Step 3: Implement state management and folder resolution**

Add to `agents/gdrive_sync.py`:

```python
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
```

**Step 4: Run tests**

```bash
uv run pytest tests/test_gdrive_sync.py -v -k "state or folder"
```

Expected: 4 PASS.

**Step 5: Commit**

```bash
git add agents/gdrive_sync.py tests/test_gdrive_sync.py
git commit -m "feat(gdrive): state management and folder path resolution"
```

---

## Task 3: MIME Classification + Metadata Stub Generation

**Files:**
- Modify: `~/projects/ai-agents/agents/gdrive_sync.py`
- Modify: `~/projects/ai-agents/tests/test_gdrive_sync.py`

**Step 1: Write failing tests**

Add to `tests/test_gdrive_sync.py`:

```python
def test_classify_document():
    from agents.gdrive_sync import _classify_file
    tier, ctype, tags = _classify_file("report.pdf", "application/pdf", 1000)
    assert tier == "document"
    assert ctype == "document"
    assert "text" in tags


def test_classify_large_audio():
    from agents.gdrive_sync import _classify_file
    tier, ctype, tags = _classify_file("beat.wav", "audio/wav", 50_000_000)
    assert tier == "metadata_only"
    assert ctype == "audio"
    assert "binary" in tags


def test_classify_google_doc():
    from agents.gdrive_sync import _classify_file
    tier, ctype, tags = _classify_file("My Doc", "application/vnd.google-apps.document", 0)
    assert tier == "document"
    assert ctype == "document"


def test_classify_small_image():
    from agents.gdrive_sync import _classify_file
    tier, ctype, tags = _classify_file("photo.jpg", "image/jpeg", 2_000_000)
    assert tier == "document"
    assert ctype == "image"
    assert "visual" in tags


def test_classify_large_unknown():
    from agents.gdrive_sync import _classify_file
    tier, ctype, tags = _classify_file("blob.bin", "application/octet-stream", 100_000_000)
    assert tier == "metadata_only"


def test_generate_metadata_stub():
    from agents.gdrive_sync import _generate_metadata_stub
    stub = _generate_metadata_stub(DriveFile(
        drive_id="abc123",
        name="drum-break.wav",
        mime_type="audio/wav",
        size=52_428_800,
        modified_time="2026-01-15T10:30:00.000Z",
        folder_path="My Drive/Samples/Drum Breaks",
        web_view_link="https://drive.google.com/file/d/abc123/view",
    ))
    assert "platform: google" in stub
    assert "service: drive" in stub
    assert "source_service: gdrive" in stub
    assert "drum-break.wav" in stub
    assert "audio/wav" in stub
    assert "Drum Breaks" in stub
    assert "abc123" in stub
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/test_gdrive_sync.py -v -k "classify or stub"
```

**Step 3: Implement classification and stub generation**

Add to `agents/gdrive_sync.py`:

```python
# ── MIME Classification ──────────────────────────────────────────────────────

def _classify_file(
    name: str, mime_type: str, size: int,
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
```

**Step 4: Run tests**

```bash
uv run pytest tests/test_gdrive_sync.py -v
```

Expected: All PASS.

**Step 5: Commit**

```bash
git add agents/gdrive_sync.py tests/test_gdrive_sync.py
git commit -m "feat(gdrive): MIME classification and metadata stub generation"
```

---

## Task 4: Drive API — Full Scan + Incremental Sync

**Files:**
- Modify: `~/projects/ai-agents/agents/gdrive_sync.py`

**Step 1: Implement full scan**

Add to `agents/gdrive_sync.py`:

```python
# ── Drive API Operations ─────────────────────────────────────────────────────

FIELDS = "nextPageToken, files(id, name, mimeType, size, modifiedTime, parents, webViewLink, md5Checksum)"

def _full_scan(service, state: SyncState) -> int:
    """Enumerate all Drive files and folders. Returns file count."""
    log.info("Starting full Drive scan...")

    # Phase 1: Build folder tree
    log.info("Building folder tree...")
    folder_parents: dict[str, str] = {}
    page_token = None
    while True:
        resp = service.files().list(
            q="mimeType='application/vnd.google-apps.folder' and trashed=false",
            fields="nextPageToken, files(id, name, parents)",
            pageSize=1000,
            pageToken=page_token,
        ).execute()
        for f in resp.get("files", []):
            state.folder_names[f["id"]] = f["name"]
            if f.get("parents"):
                folder_parents[f["id"]] = f["parents"][0]
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    log.info("Found %d folders", len(state.folder_names))

    # Phase 2: Enumerate all non-folder files
    count = 0
    page_token = None
    while True:
        resp = service.files().list(
            q="mimeType!='application/vnd.google-apps.folder' and trashed=false",
            fields=FIELDS,
            pageSize=1000,
            pageToken=page_token,
        ).execute()
        for f in resp.get("files", []):
            drive_id = f["id"]
            parent_id = f.get("parents", [""])[0] if f.get("parents") else ""
            folder_path = _resolve_folder_path(parent_id, state.folder_names, folder_parents) if parent_id else ""

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
    folder_parents: dict[str, str] = {}

    # Rebuild folder parents (lightweight — only needed for path resolution)
    for fid, fname in state.folder_names.items():
        # We don't track folder parents persistently, but existing files have folder_path
        pass

    while True:
        resp = service.changes().list(
            pageToken=page_token,
            fields="nextPageToken, newStartPageToken, changes(fileId, removed, file(id, name, mimeType, size, modifiedTime, parents, webViewLink, md5Checksum))",
            pageSize=1000,
            includeRemoved=True,
        ).execute()

        for change in resp.get("changes", []):
            file_id = change["fileId"]

            if change.get("removed"):
                if file_id in state.files:
                    df = state.files.pop(file_id)
                    # Delete local file if it exists
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
                continue

            parent_id = f.get("parents", [""])[0] if f.get("parents") else ""
            folder_path = _resolve_folder_path(parent_id, state.folder_names, {}) if parent_id else ""

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
```

**Step 2: Commit**

```bash
git add agents/gdrive_sync.py
git commit -m "feat(gdrive): full scan and incremental sync via Drive API"
```

---

## Task 5: File Download + Export + Stub Writing

**Files:**
- Modify: `~/projects/ai-agents/agents/gdrive_sync.py`

**Step 1: Implement download/export/stub pipeline**

Add to `agents/gdrive_sync.py`:

```python
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
    stub_path = META_DIR / f"{safe_name}.md"

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
            from googleapiclient.http import MediaIoBaseDownload
            import io
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
            f_data = service.files().get(
                fileId=drive_id,
                fields="id, name, mimeType, size, modifiedTime, parents, webViewLink, md5Checksum",
            ).execute()
        except Exception as exc:
            log.error("Failed to fetch metadata for %s: %s", drive_id, exc)
            return False
        parent_id = f_data.get("parents", [""])[0] if f_data.get("parents") else ""
        folder_path = _resolve_folder_path(parent_id, state.folder_names, {}) if parent_id else ""
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
```

**Step 2: Commit**

```bash
git add agents/gdrive_sync.py
git commit -m "feat(gdrive): download, export, metadata stub, and on-demand fetch"
```

---

## Task 6: Profiler Bridge + Stats

**Files:**
- Modify: `~/projects/ai-agents/agents/gdrive_sync.py`
- Modify: `~/projects/ai-agents/tests/test_gdrive_sync.py`

**Step 1: Write failing test**

```python
def test_generate_profile_facts():
    from agents.gdrive_sync import _generate_profile_facts, SyncState, DriveFile
    state = SyncState()
    state.files = {
        "1": DriveFile(drive_id="1", name="beat.wav", mime_type="audio/wav", size=50_000_000, folder_path="Samples/Drums"),
        "2": DriveFile(drive_id="2", name="notes.md", mime_type="text/markdown", size=1000, folder_path="Projects/Track1"),
        "3": DriveFile(drive_id="3", name="synth.wav", mime_type="audio/wav", size=30_000_000, folder_path="Samples/Synths"),
    }
    facts = _generate_profile_facts(state)
    assert len(facts) > 0
    dims = {f["dimension"] for f in facts}
    assert "workflow" in dims or "knowledge_domains" in dims
    assert all(f["confidence"] == 0.95 for f in facts)
```

**Step 2: Implement profiler bridge and stats**

```python
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
        elif f.mime_type in EXPORT_MIMES or f.mime_type.startswith("text/") or f.mime_type == "application/pdf":
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
        dist = ", ".join(f"{k} ({v/total:.0%})" for k, v in mime_counts.most_common(5))
        facts.append({
            "dimension": "workflow",
            "key": "gdrive_file_types",
            "value": dist,
            "confidence": 0.95,
            "source": source,
            "evidence": f"Distribution across {total} Drive files",
        })

    # Active folders
    if folder_counts:
        top_folders = ", ".join(f[0] for f in folder_counts.most_common(10))
        facts.append({
            "dimension": "knowledge_domains",
            "key": "gdrive_active_folders",
            "value": top_folders,
            "confidence": 0.95,
            "source": source,
            "evidence": f"Top folders by file count across {sum(folder_counts.values())} files",
        })

    # Total storage
    if total_size:
        gb = total_size / (1024**3)
        facts.append({
            "dimension": "workflow",
            "key": "gdrive_storage_usage",
            "value": f"{gb:.1f} GB across {len(state.files)} files",
            "confidence": 0.95,
            "source": source,
            "evidence": "Computed from Drive API file sizes",
        })

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
        if f.mime_type.startswith("audio/"): mime_cats["audio"] += 1
        elif f.mime_type.startswith("video/"): mime_cats["video"] += 1
        elif f.mime_type.startswith("image/"): mime_cats["image"] += 1
        else: mime_cats["documents/other"] += 1

    print(f"Google Drive Sync State")
    print(f"{'='*40}")
    print(f"Total files:     {total:,}")
    print(f"Downloaded:      {downloaded:,}")
    print(f"Metadata-only:   {meta_only:,}")
    print(f"Pending sync:    {pending:,}")
    print(f"Total size:      {total_size / (1024**3):.1f} GB")
    print(f"Last full scan:  {datetime.fromtimestamp(state.last_full_scan).isoformat() if state.last_full_scan else 'never'}")
    print(f"Last sync:       {datetime.fromtimestamp(state.last_sync).isoformat() if state.last_sync else 'never'}")
    print(f"\nBy type:")
    for cat, count in mime_cats.most_common():
        print(f"  {cat}: {count:,}")
```

**Step 3: Run tests**

```bash
uv run pytest tests/test_gdrive_sync.py -v
```

**Step 4: Commit**

```bash
git add agents/gdrive_sync.py tests/test_gdrive_sync.py
git commit -m "feat(gdrive): profiler bridge facts and stats display"
```

---

## Task 7: CLI + Main Entry Point

**Files:**
- Modify: `~/projects/ai-agents/agents/gdrive_sync.py`

**Step 1: Implement CLI and orchestration**

Add to `agents/gdrive_sync.py`:

```python
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
    for drive_id, f in state.files.items():
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

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

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
```

**Step 2: Test CLI help works**

```bash
cd ~/projects/ai-agents && uv run python -m agents.gdrive_sync --help
```

Expected: Help text with all modes.

**Step 3: Commit**

```bash
git add agents/gdrive_sync.py
git commit -m "feat(gdrive): CLI entry point with full-scan, auto, fetch, stats modes"
```

---

## Task 8: Systemd Timer + Service

**Files:**
- Create: `~/.config/systemd/user/gdrive-sync.service`
- Create: `~/.config/systemd/user/gdrive-sync.timer`

**Step 1: Create service unit**

```ini
[Unit]
Description=Google Drive RAG sync (incremental)
After=network.target

[Service]
Type=oneshot
WorkingDirectory=/home/hapaxlegomenon/projects/ai-agents
ExecStart=/home/hapaxlegomenon/.local/bin/uv run python -m agents.gdrive_sync --auto
Environment=PATH=/home/hapaxlegomenon/.local/bin:/usr/local/bin:/usr/bin:/bin
Environment=HOME=/home/hapaxlegomenon
Environment=GNUPGHOME=/home/hapaxlegomenon/.gnupg
Environment=PASSWORD_STORE_DIR=/home/hapaxlegomenon/.password-store
MemoryMax=1G
CPUQuota=50%
StandardOutput=journal
StandardError=journal
SyslogIdentifier=gdrive-sync

[Install]
WantedBy=default.target
```

**Step 2: Create timer**

```ini
[Unit]
Description=Google Drive RAG sync every 2 hours

[Timer]
OnCalendar=*-*-* 00/2:15:00
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
```

**Step 3: Enable timer**

```bash
systemctl --user daemon-reload
systemctl --user enable --now gdrive-sync.timer
systemctl --user list-timers | grep gdrive
```

**Step 4: Commit**

```bash
git add agents/gdrive_sync.py
git commit -m "feat(gdrive): systemd timer for 2-hour incremental sync"
```

---

## Task 9: Integration Test — End-to-End

**Step 1: Run OAuth flow (if not done in Task 1)**

```bash
cd ~/projects/ai-agents && uv run python -m agents.gdrive_sync --auth
```

**Step 2: Run full scan**

```bash
uv run python -m agents.gdrive_sync --full-scan -v
```

Expected: Scans all Drive files, downloads documents, writes metadata stubs. Watch for:
- Folder count and file count in logs
- Files appearing in `~/documents/rag-sources/gdrive/`
- Metadata stubs in `~/documents/rag-sources/gdrive/.meta/`
- Profile facts in `~/.cache/gdrive-sync/drive-profile-facts.jsonl`

**Step 3: Verify stats**

```bash
uv run python -m agents.gdrive_sync --stats
```

**Step 4: Verify rag-ingest picks up files**

```bash
journalctl --user -u rag-ingest -f --no-pager
```

Watch for gdrive files being ingested.

**Step 5: Test incremental sync**

```bash
uv run python -m agents.gdrive_sync --auto -v
```

Expected: "No changes to sync" (or picks up any changes made since full scan).

**Step 6: Test on-demand fetch**

Pick a metadata-only file from stats output and fetch it:

```bash
uv run python -m agents.gdrive_sync --fetch <drive_id>
```

**Step 7: Run all unit tests**

```bash
uv run pytest tests/test_gdrive_sync.py -v
```

Expected: All PASS.

**Step 8: Final commit**

```bash
git add -A
git commit -m "test(gdrive): end-to-end integration verification complete"
```

---

## Summary

| Task | Description | Est. |
|------|-------------|------|
| 1 | Dependencies + OAuth + skeleton | Setup |
| 2 | State management + folder resolution | Core |
| 3 | MIME classification + metadata stubs | Core |
| 4 | Full scan + incremental sync | Core |
| 5 | Download + export + stub writing | Core |
| 6 | Profiler bridge + stats | Integration |
| 7 | CLI entry point | Wiring |
| 8 | Systemd timer + service | Operations |
| 9 | End-to-end integration test | Verification |
