# RAG Phase 4 — Claude Code Transcripts, Obsidian Vault, Chrome History

**Goal:** Maximize RAG coverage with the three highest-value remaining sources: Claude Code session transcripts (richest technical conversations, already on disk), Obsidian vault (second brain, meeting notes, contacts), and Chrome browsing history + bookmarks (interest signals, research patterns).

**Context:** Phases 1-3 delivered Google Drive, Calendar, Gmail, and YouTube sync agents. This phase follows the same established pattern: Pydantic schemas, incremental sync, markdown RAG output with YAML frontmatter, profiler bridge, behavioral logging, systemd timers.

---

## Agent 1: Claude Code Transcript Sync

**Agent:** `claude_code_sync.py` — No LLM. Periodic filesystem scanner.

**Source:** `~/.claude/projects/*/` — 1,138 JSONL transcript files, ~794MB total. Each file is a complete Claude Code session containing user messages, assistant responses, tool calls, file snapshots, and progress events.

### Discovery

On each run, glob `~/.claude/projects/*/` to find all project directories. Decode the directory name to recover the project path:
- `-home-hapaxlegomenon-projects-ai-agents` → `~/projects/ai-agents`
- New repos under `~/projects/` are picked up automatically when Claude Code creates a project directory for them.

### Parsing

For each `.jsonl` transcript:
1. Read line-by-line, filter to `type: "user"` and `type: "assistant"` entries
2. Extract text content only (skip `tool_use` blocks, `tool_result`, attachments)
3. Extract timestamps from message metadata
4. Build conversation markdown

### Schema

```python
class TranscriptMetadata(BaseModel):
    session_id: str          # UUID from filename
    project_path: str        # Decoded from parent dir name
    project_name: str        # basename (e.g., "ai-agents")
    message_count: int
    first_message_at: str    # ISO from first user message
    last_message_at: str     # ISO from last message
    file_size: int           # bytes, for change detection
    file_mtime: float        # for incremental sync

class ClaudeCodeSyncState(BaseModel):
    sessions: dict[str, TranscriptMetadata] = {}  # session_id → metadata
    last_sync: float = 0.0
    stats: dict[str, int] = {}
```

### State Tracking

`~/.cache/claude-code-sync/state.json` — maps `session_id → {mtime, size, message_count}`. Each run compares mtime+size to detect new or updated transcripts. Skip unchanged files. Active sessions (mtime within last 10 minutes) are re-processed on each run since they're still being written to.

### RAG Output

`rag-sources/claude-code/{project_name}/{session_id}.md`:

```yaml
---
platform: claude
service: claude-code
content_type: conversation
source_service: claude-code
project: ai-agents
session_id: 8950a2ee-abc3-40d7-a767-a91f7e391357
timestamp: 2026-03-08T19:00:00
message_count: 47
---

# Claude Code Session: ai-agents (2026-03-08)

## User (19:00:00)
let's proceed

## Assistant (19:00:05)
I'll start by implementing...
```

### Profiler Facts

Dimension: `workflow`
- `claude_code_projects`: repos with sessions, ranked by frequency
- `claude_code_topics`: extracted from first user message of each session
- `claude_code_activity`: session frequency and volume trends

### Timer

Every 2h. CLI: `--full-sync`, `--auto`, `--stats`.

### Bi-directional Agent Integration

- **Briefing:** "Recent Claude Code Activity" section — sessions in lookback window, grouped by project
- **Profiler:** consumes workflow dimension facts

---

## Agent 2: Obsidian Vault Sync

**Agent:** `obsidian_sync.py` — No LLM. Periodic vault scanner. Read-only — never modifies vault files.

**Source:** `~/Documents/Personal/` — 1,539 markdown notes. Obsidian vault synced via Obsidian Sync. Contains meeting notes, contacts, projects, periodic notes, resources.

### Filtering

**Include:** `00-inbox/`, `20-personal/`, `20 Projects/`, `30 Areas/` (and children: `31 Fleeting notes/`, `32 Literature notes/`, `33 Permanent notes/`, `34 MOCs/`, `35 Contacts/`, `36 People/`, `37 Meeting notes/`, `38 Bookmarks/`), `50 Resources/`, `Periodic Notes/`, and root-level `.md` files.

**Exclude:** `90-attachments/`, `50-templates/`, `Templates/`, `60-archive/`, `60 Archives/`, `.obsidian/`, `smart-chats/`, `textgenerator/`, `configs/`, `docs/`, `scripts/`, `research/`.

**File filter:** Only `.md` files, skip files < 50 bytes (empty stubs).

### Change Detection

Content hash (MD5) comparison. State maps `relative_path → {hash, mtime, size}`. Each run scans vault, compares hashes, processes only changed/new files. Detects deletions (in state but not on disk) — removes from rag-sources, logs behavioral change.

### Schema

```python
class VaultNote(BaseModel):
    relative_path: str       # e.g., "30 Areas/37 Meeting notes/Alice 1on1.md"
    title: str               # From first H1 or filename
    folder: str              # Top-level vault folder
    content_hash: str
    size: int
    mtime: float
    has_frontmatter: bool
    tags: list[str] = []     # Obsidian #tags
    links: list[str] = []    # [[wikilinks]]

class ObsidianSyncState(BaseModel):
    notes: dict[str, VaultNote] = {}  # relative_path → metadata
    last_sync: float = 0.0
    stats: dict[str, int] = {}
```

### RAG Output

`rag-sources/obsidian/{folder-slug}/{filename}.md`:

Preserves existing Obsidian frontmatter and prepends RAG metadata:

```yaml
---
platform: obsidian
service: obsidian-vault
content_type: note
source_service: obsidian
vault_folder: 30 Areas/37 Meeting notes
tags: [meeting, 1on1, alice]
links: [Alice Bregger, Q1 Goals]
timestamp: 2026-03-07T14:30:00
---

# Alice 1:1 — March 7

(original note content preserved verbatim)
```

### Profiler Facts

Dimension: `knowledge`
- `obsidian_active_areas`: folders with most recent edits
- `obsidian_note_volume`: total notes, notes modified this week
- `obsidian_frequent_tags`: most-used Obsidian tags

### Timer

Every 30min (active note-taking cadence).

### Bi-directional Agent Integration

- **management_prep:** if vault has notes in `37 Meeting notes/` matching a person name, surface them as additional meeting context
- **briefing:** "Vault Activity" section — notes modified in lookback window

---

## Agent 3: Chrome History + Bookmarks Sync

**Agent:** `chrome_sync.py` — No LLM. Periodic SQLite reader.

**Source files:**
- History: `~/.config/google-chrome/Default/History` (SQLite, WAL mode, locked while Chrome runs)
- Bookmarks: `~/.config/google-chrome/Default/Bookmarks` (JSON, always readable)

### Lock Handling

Copy History DB to `~/.cache/chrome-sync/history-snapshot.db` before querying. Chrome locks the DB exclusively. Copy-then-read is standard and safe. Clean up snapshot after query.

### Schema

```python
class HistoryEntry(BaseModel):
    url: str
    title: str
    domain: str              # extracted from URL
    visit_count: int
    last_visit: str          # ISO datetime
    first_visit: str         # ISO datetime

class BookmarkEntry(BaseModel):
    url: str
    title: str
    folder: str              # bookmark bar folder path
    added_at: str            # ISO datetime

class ChromeSyncState(BaseModel):
    last_visit_time: int = 0    # Chrome WebKit timestamp high-water mark
    domains: dict[str, int] = {}  # domain → total visits
    bookmark_hash: str = ""      # detect bookmark file changes
    last_sync: float = 0.0
    stats: dict[str, int] = {}
```

### Incremental Sync

Chrome stores `last_visit_time` as WebKit microseconds (epoch + 11644473600 seconds × 1,000,000). State tracks the high-water mark. Each run queries `WHERE last_visit_time > state.last_visit_time`. Full history on first run.

### Domain Filtering

Skip noise domains (configurable `SKIP_DOMAINS` set):
- Search: `google.com/search`
- Local: `localhost`, `127.0.0.1`, `chrome://`, `chrome-extension://`
- Already covered: `mail.google.com` (Gmail agent), `calendar.google.com` (Calendar agent), `drive.google.com` (Drive agent), `youtube.com` (YouTube agent)

### RAG Output

Two types in `rag-sources/chrome/`:

**Domain summaries** — `domain-{domain}.md` (one per domain with 3+ visits):

```yaml
---
platform: chrome
service: chrome-history
content_type: browsing_history
source_service: chrome
domain: github.com
total_visits: 247
first_seen: 2024-06-15T10:00:00
last_seen: 2026-03-08T21:00:00
---

# github.com (247 visits)

## Recent Pages
- GitHub: Let's build from here (142 visits, last: 2026-03-08)
- anthropics/claude-code: Issues (28 visits, last: 2026-03-07)
```

**Bookmarks** — `bookmarks.md` (single file, full folder structure):

```yaml
---
platform: chrome
service: chrome-bookmarks
content_type: bookmarks
source_service: chrome
bookmark_count: 45
---

# Chrome Bookmarks

## songs
- Track Title — https://...
```

### Profiler Facts

Dimension: `interests`
- `browsing_top_domains`: top 20 domains by visit count
- `browsing_categories`: rough categorization (dev tools, music, news, social)
- `bookmark_topics`: bookmark folder names as interest signals

### Timer

Every 1h.

### Bi-directional Agent Integration

- **Briefing:** "Recent Browsing" section — notable domains visited in lookback window (noise-filtered)
- **Profiler:** consumes interest dimension facts

---

## Deferred and Evaluated Sources

| Source | Status | Value | Notes |
|--------|--------|-------|-------|
| **Tidal** | Deferred | Music listening patterns | No official API. `tidalapi` community library fragile. Revisit if stable integration emerges. |
| **Google Keep** (live) | Deferred — low volume | Quick notes, lists | 40 notes in Takeout. `gkeepapi` unofficial. Static Takeout already ingested. |
| **Google Tasks** (live) | Deferred — low volume | Open loops, task tracking | 5 tasks in Takeout. Official API but too little data. |
| **Langfuse Traces** | Deferred | LLM usage patterns, cost | REST API available. Better as briefing data source than RAG — structured telemetry, not natural language. |
| **Proton Mail** (live) | Skip — redundant | Email metadata | All Proton forwards to Gmail. Gmail sync captures this. 28,254 historical in Takeout. |
| **Claude.ai Conversations** | Manual export | Technical conversations | No API. Manual ZIP via Settings > Export Data. `llm_export_converter.py` handles. 65 currently ingested. Run monthly. |
| **Gemini Conversations** | Manual export | AI conversation history | Via Google Takeout. 4,082 ingested. Refresh via periodic Takeout. |
| **Perplexity** | Skip | Research queries | No export API. Playwright scraping too fragile. |
| **Atuin Shell History** | Deferred | Command patterns, tool usage | SQLite DB exists. Low priority — Claude Code transcripts capture richer technical context. |
| **Google Chat** (live) | Deferred | Communication patterns | 51,601 historical in Takeout. No clear ongoing usage. |
| **n8n Workflows** | Deferred — empty | Automation patterns | 0 workflows. Revisit when populated. |
| **Signal/Discord** | Skip | Social/personal | E2E encrypted, social/gaming. Low productivity signal. |

---

## Shared Infrastructure

### Ingest Auto-tagging

`ingest.py` already has `_SERVICE_PATH_PATTERNS`. Add:
```python
"rag-sources/claude-code": "claude-code",
"rag-sources/obsidian": "obsidian",
"rag-sources/chrome": "chrome",
```

### Profiler Registration

`profiler_sources.py`:
- Add `"claude-code"`, `"obsidian"`, `"chrome"` to `BRIDGED_SOURCE_TYPES`
- Add chunk caps: `"claude-code": 200`, `"obsidian": 200`, `"chrome": 50`

### Documentation

Update `system-context.md`, `hapaxromana/CLAUDE.md`, `ai-agents/CLAUDE.md`, `ai-agents/README.md` with new agents and timers.

### Timer Summary (all Google + Phase 4)

| Timer | Schedule | Purpose |
|-------|----------|---------|
| gdrive-sync | Every 2h | Google Drive |
| gcalendar-sync | Every 30min | Google Calendar |
| gmail-sync | Every 1h | Gmail metadata |
| youtube-sync | Every 6h | YouTube likes/subs |
| claude-code-sync | Every 2h | Claude Code transcripts |
| obsidian-sync | Every 30min | Obsidian vault |
| chrome-sync | Every 1h | Chrome history + bookmarks |
