# Google Drive RAG Integration Design

## Problem

400GB Google Drive (personal) with documents, audio, images, and binaries. Currently not searchable via the Hapax RAG pipeline. Only a one-time Google Takeout export feeds into the system. No live sync, no per-source filtering, no binary metadata indexing.

## Constraints

- 354GB free disk — cannot mirror 400GB Drive locally
- Personal Gmail account — requires OAuth2 consent flow (no service account)
- Must integrate with existing rag-ingest file watcher (no new ingestion path)
- Must inform downstream consumers: digest, briefing, research agent, profiler

## Architecture: Smart Tiered Sync

New module: `agents/gdrive_sync.py` in `~/projects/ai-agents/`

### Two-Tier Strategy

| Tier | Criteria | Action | Disk cost |
|------|----------|--------|-----------|
| Documents | Docs, Sheets, Slides, PDFs, text, markdown, HTML, DOCX, PPTX, images (<=25MB) | Export/download to `rag-sources/gdrive/` | Est. 10-50GB |
| Binaries | Audio, video, ZIPs, large files (>25MB) | Metadata-only stub `.md` with YAML frontmatter | ~0 |

### Data Flow

```
Google Drive API (changes.list — incremental)
    |
    v
gdrive_sync.py
    |
    +-> Documents: download/export to ~/documents/rag-sources/gdrive/{folder_path}/
    |   |
    |   v
    |   rag-ingest file watcher (existing) -> chunk -> embed -> Qdrant "documents"
    |
    +-> Binaries: write metadata stub .md to ~/documents/rag-sources/gdrive/.meta/
    |   |
    |   v
    |   rag-ingest picks up stub -> embed metadata text -> Qdrant "documents"
    |
    +-> Structured: write drive-profile-facts.jsonl to ~/.cache/gdrive-sync/
        |
        v
        profiler_bridge pattern -> Qdrant "profile-facts" (zero LLM cost)
```

## Authentication

- Google Cloud project with Drive API enabled
- OAuth2 client credentials JSON -> `pass show gdrive/client-secret`
- One-time browser consent flow -> refresh token -> `pass show gdrive/token`
- Direct `google-api-python-client` usage (no rclone)

## Sync Engine

- **Incremental sync:** Drive API `changes.list` with stored `startPageToken`
- **Full scan:** `files.list` with pagination on first run
- **State tracking:** `~/.cache/gdrive-sync/state.json` — maps Drive file IDs to local paths, mtimes, metadata hashes
- **Google-native exports:** Docs->DOCX, Sheets->XLSX, Slides->PPTX
- **Size threshold:** <=25MB downloaded, >25MB metadata-only
- **Dedup:** Existing rag-ingest hash+mtime dedup handles re-synced files

## Output Structure

```
~/documents/rag-sources/gdrive/
+-- My Drive/
|   +-- Projects/
|   |   +-- some-doc.docx          # exported from Google Docs
|   |   +-- budget.xlsx            # exported from Google Sheets
|   +-- Notes/
|       +-- meeting-notes.md       # downloaded as-is
+-- .meta/
    +-- large-audio-file.wav.md    # metadata stub (no binary)
    +-- video-project.mp4.md       # metadata stub
    +-- archive.zip.md             # metadata stub
```

### Metadata Stub Format

```yaml
---
platform: google
service: drive
content_type: audio
source_service: gdrive
source_platform: google
record_id: <drive_file_id>
timestamp: 2026-01-15T10:30:00
modality_tags: [audio, binary]
categories: [My Drive, Samples, Drum Breaks]
gdrive_id: 1aBcDeFgHiJkLmN
gdrive_link: https://drive.google.com/file/d/1aBcDeFgHiJkLmN/view
mime_type: audio/wav
file_size: 52428800
---

# large-audio-file.wav

**Location:** My Drive / Samples / Drum Breaks
**Size:** 50.0 MB
**Type:** audio/wav
**Modified:** 2026-01-15 10:30 UTC
**Drive link:** https://drive.google.com/file/d/1aBcDeFgHiJkLmN/view
```

Enrichment keys match existing `ingest.py` allowlist: `content_type`, `source_service`, `source_platform`, `timestamp`, `modality_tags`, `categories`, `record_id`.

## Profiler Integration

Structured JSONL output at `~/.cache/gdrive-sync/drive-profile-facts.jsonl`:

- Folder structure -> `knowledge_domains` dimension
- File type distribution -> `workflow` dimension
- Recent activity patterns -> `workflow` dimension

Deterministic mapping, zero LLM cost — same pattern as `shared/takeout/profiler_bridge.py`.

## Hapax System Integration

| Consumer | How Drive data reaches it |
|----------|--------------------------|
| digest agent | Scrolls recently ingested docs (ingested_at filter) — Drive files appear automatically |
| briefing agent | Reads digest JSON — Drive sync summary in morning briefing |
| research agent | Semantic search over documents collection — Drive content searchable |
| profiler agent | Structured JSONL -> profile-facts — Drive usage informs operator profile |
| Open WebUI | RAG search backed by same Qdrant collection |

All filtering by `source_service: "gdrive"` works automatically via frontmatter enrichment.

## Scheduling & Operations

- **Timer:** `gdrive-sync.timer` — every 2 hours (systemd user)
- **Service:** `gdrive-sync.service` — `uv run python -m agents.gdrive_sync --auto`
- **CLI modes:**
  - `--full-scan` — first run, full Drive enumeration
  - `--auto` — incremental sync (changes since last token)
  - `--fetch <drive_id>` — download a specific metadata-only file for full ingestion
  - `--stats` — show sync state
- **Notifications:** ntfy push on sync completion
- **Error handling:** Failed downloads -> retry queue (exponential backoff)

## On-Demand File Fetch

For metadata-only files (binaries >25MB):

- CLI: `--fetch <drive_id>` downloads file to `rag-sources/gdrive/`, triggers re-ingestion
- Open WebUI tool: `fetch_drive_file(file_id)` calls sync agent fetch
- Enables: search metadata -> find file -> pull on demand

## Dependencies

- `google-api-python-client` + `google-auth-oauthlib` (OAuth2 flow)
- Existing: `qdrant-client`, `shared/config.py` (embed, get_qdrant)
- Existing: `shared/notify.py` (ntfy push)
- Existing: `rag-ingest.service` (file watcher)

## MIME Type Classification

| Category | MIME patterns | Action |
|----------|-------------|--------|
| Google native | `application/vnd.google-apps.*` | Export (Docs->DOCX, Sheets->XLSX, Slides->PPTX) |
| Documents | `application/pdf`, `text/*`, `application/msword`, `application/vnd.openxml*` | Download |
| Images | `image/*` (<=25MB) | Download (OCR via Docling) |
| Audio | `audio/*` | Metadata stub |
| Video | `video/*` | Metadata stub |
| Archives | `application/zip`, `application/x-*` | Metadata stub |
| Other >25MB | anything | Metadata stub |

## Content Type Inference

Map MIME type to `content_type` frontmatter value:

- `application/vnd.google-apps.document` -> `document`
- `application/vnd.google-apps.spreadsheet` -> `spreadsheet`
- `application/pdf` -> `document`
- `audio/*` -> `audio`
- `video/*` -> `video`
- `image/*` -> `image`
- `text/plain`, `text/markdown` -> `note`
- Default -> `file`

## Modality Tag Inference

Map MIME type to `modality_tags`:

- Documents/text -> `[text, knowledge]`
- Spreadsheets -> `[data, tabular]`
- Audio -> `[audio, binary]`
- Video -> `[video, binary]`
- Images -> `[image, visual]`
- Archives -> `[archive, binary]`
