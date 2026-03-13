# Ingestion Pipeline Expansion Plan

**Date:** 2026-03-13
**Status:** Planned
**Scope:** 10 independent batches, each self-contained and shippable

---

## Overview

Expand the hapax-council RAG ingestion surface from 8 sync agents to 18+, adding git history, LLM traces, music taste, health biometrics, location, and GitHub activity. Each batch follows the established sync agent pattern: state tracking, incremental sync, RAG markdown output, profile facts, systemd timer, watchdog with notification.

---

## Batch 1: Git History Sync

**Priority:** Critical — architectural decisions live in commits, not docs
**Effort:** Low (all data local, no API auth)

### Research
- [x] Repos to ingest: hapax-council, hapax-officium, hapax-constitution, distro-work
- [x] Data model: commit hash, author, date, message, files changed, diff stats
- [x] Incremental strategy: track last-seen commit SHA per repo

### Implementation
1. Create `agents/git_sync.py`
   - Walk all repos in `~/projects/` (or explicit list)
   - `git log --format=json` equivalent via `subprocess` or `gitpython`
   - For each commit: message, files changed, insertions/deletions, branch, tags
   - Optionally include diff hunks for commits touching key files (manifests, CLAUDE.md, configs)
   - Incremental: store last SHA per repo in state.json
   - Output: one markdown file per repo covering recent N commits (rolling window, e.g. 90 days)
   - Profile facts: commit frequency, active repos, languages touched, time-of-day patterns
2. Create `agents/manifests/git_sync.yaml`
3. Create systemd timer: `git-sync.timer` (every 6h)
4. Create watchdog: `systemd/watchdogs/git-sync-watchdog`
5. Tests: mock git output, verify incremental state, verify markdown format

### Key decisions
- Diff inclusion: full diffs are noisy. Include only for files matching `*.py`, `*.md`, `*.yaml`, `CLAUDE.md` — skip generated files
- Repo discovery: explicit list preferred over auto-discovery (avoids ingesting forks/vendored repos)
- Chunk strategy: one markdown file per repo (not per commit) to keep vector count manageable

---

## Batch 2: Langfuse Trace Sync

**Priority:** Critical — every LLM interaction becomes searchable
**Effort:** Medium (Langfuse REST API, pagination, data volume)

### Research
- [ ] Langfuse API endpoints: `GET /api/public/traces`, `GET /api/public/observations`
- [ ] Auth: public/secret key pair (already in pass store)
- [ ] Rate limits and pagination strategy
- [ ] Data volume estimate: how many traces per day?
- [ ] What fields are most valuable for RAG? (prompt, completion, model, cost, latency, metadata)

### Implementation
1. Create `agents/langfuse_sync.py`
   - Fetch traces via Langfuse REST API
   - Incremental: track latest trace timestamp in state.json
   - For each trace: extract model, prompt (truncated), completion summary, cost, latency, tags
   - Group by session/day for markdown output
   - Output: daily markdown files in `~/documents/rag-sources/langfuse/`
   - Profile facts: model usage distribution, daily cost trends, most common prompt patterns
   - Include LiteLLM spend data: query `/spend/report` endpoint for per-model cost breakdowns
2. Create manifest, timer (every 6h), watchdog
3. Privacy: truncate long prompts/completions to first 500 chars in RAG (full data stays in Langfuse)

### Key decisions
- Granularity: per-trace or per-session? Per-session groups related calls, reduces vector count
- Cost data: combine Langfuse trace costs with LiteLLM `/spend/report` for a unified cost picture
- Retention in RAG: rolling 30-day window (older traces are in Langfuse, not needed in vector search)

---

## Batch 3: YouTube Music Sync

**Priority:** High — completes the music taste profile alongside Tidal
**Effort:** Low (mature unofficial library)

### Research
- [ ] Install and test `ytmusicapi` in project venv
- [ ] Auth flow: extract browser cookies, test connection
- [ ] Available data: liked songs, library albums/artists, playlists, play history
- [ ] Overlap with existing `youtube_sync.py` — can they share state/timer?
- [ ] Rate limits or anti-abuse measures?

### Implementation
1. Create `agents/ytmusic_sync.py`
   - Auth: browser cookie extraction (one-time setup, store headers file)
   - Sync: liked songs, library, playlists, play history (if available)
   - Incremental: track last sync timestamp, compare liked song count
   - Output: `~/documents/rag-sources/ytmusic/` — liked songs list, playlist summaries
   - Profile facts: genre distribution, listening recency, artist diversity
2. Create manifest, timer (every 12h — music changes slowly), watchdog
3. Cookie refresh: document re-auth procedure, alert if auth fails

### Key decisions
- Separate from youtube_sync or merged? Keep separate — different API, different auth, different data semantics
- Play history availability: may be limited by Google's API restrictions
- Playlist contents: include track lists or just metadata? Include track lists (valuable for taste inference)

---

## Batch 4: Tidal Sync

**Priority:** High — primary music streaming service
**Effort:** Low (mature Python library)

### Research
- [ ] Install and test `tidalapi` in project venv
- [ ] Auth flow: OAuth2 device flow or session login
- [ ] Available data: favorites (tracks/albums/artists), playlists, listening history
- [ ] Listening history depth: how far back does the API go?
- [ ] Rate limits?

### Implementation
1. Create `agents/tidal_sync.py`
   - Auth: `tidalapi` session with stored credentials (pass store or token file)
   - Sync: favorite tracks, albums, artists, playlists, listening history
   - Incremental: track last seen favorites count + last history timestamp
   - Output: `~/documents/rag-sources/tidal/` — favorites by type, playlist summaries, recent listens
   - Profile facts: top genres, top artists, listening volume, discovery rate (new vs revisited)
2. Create manifest, timer (every 12h), watchdog
3. Token refresh: handle session expiry gracefully with notification on auth failure

### Key decisions
- Official API vs `tidalapi` lib: use `tidalapi` — more complete for personal data access
- Genre extraction: Tidal has rich genre/mood metadata — extract and use for profile facts
- Cross-reference with YouTube Music: don't deduplicate across services (different listening contexts)

---

## Batch 5: Fitbit Health Sync

**Priority:** High — continuous biometric data replaces dead Google Fit
**Effort:** Medium (OAuth2, multiple endpoints, rate limits)

### Research
- [ ] Register "Personal" app at dev.fitbit.com (unlocks intraday data)
- [ ] OAuth2 PKCE flow implementation or use existing google_auth.py pattern
- [ ] Available endpoints: heart rate, steps, sleep, SpO2, weight, activity logs
- [ ] Rate limits: 150 requests/hour for personal apps — plan request budget
- [ ] Intraday data granularity: 1-minute or 1-second resolution?
- [ ] Overlap with existing health-connect-parse agent

### Implementation
1. Create `agents/fitbit_sync.py`
   - Auth: OAuth2 PKCE, store tokens in pass or encrypted file
   - Sync daily summaries: HR resting + zones, steps, sleep stages, SpO2, weight
   - Incremental: track last synced date, pull only new days
   - Output: `~/documents/rag-sources/fitbit/` — daily health summaries (markdown)
   - Profile facts: resting HR trend, sleep quality score, activity level, weight trend
   - Coordinate with health-connect-parse: avoid duplicate health data
2. Create manifest, timer (daily at 06:00 — after sleep data finalizes), watchdog
3. Token refresh: automated refresh token flow, alert on OAuth expiry

### Key decisions
- Intraday vs daily: daily summaries for RAG (intraday is too granular for vector search)
- Sleep data: include sleep stages (light/deep/REM/awake) — high value for health correlation
- Merge with health-connect-parse? Keep separate — different data source, different auth, different cadence
- Weight/body: only include if user tracks it (check during first sync)

---

## Batch 6: GitHub Activity Sync

**Priority:** Medium — professional signal, trivial to implement
**Effort:** Low (`gh` CLI already authenticated)

### Research
- [ ] `gh api` endpoints: starred repos, notifications, issues commented on, PRs reviewed
- [ ] Data volume: how many starred repos, how active across orgs?
- [ ] Relevant activity: contributions to own repos (already covered by git sync) vs external activity

### Implementation
1. Create `agents/github_sync.py`
   - Auth: `gh` CLI (already authenticated)
   - Sync: starred repos (with topics/description), notifications (recent 30d), contribution activity
   - Incremental: track starred repo count + last notification ID
   - Output: `~/documents/rag-sources/github/` — starred repos by topic, recent notifications
   - Profile facts: starred repo topics (technology interests), contribution patterns
2. Create manifest, timer (every 12h), watchdog
3. Avoid overlap with git_sync: this covers *external* GitHub activity, git_sync covers *local* repo history

### Key decisions
- Starred repos: include README excerpts? No — just name, description, topics, language, star date
- Issues/PRs: only include those the user authored or commented on (not all repo activity)
- Notifications: filter to actionable types (review requests, mentions, CI failures)

---

## Batch 7: Location Tracking (Dawarich + OwnTracks)

**Priority:** Medium — rich contextual signal but requires phone setup
**Effort:** Medium (Docker service + phone app setup + Google Takeout backfill)

### Research
- [ ] Dawarich Docker Compose requirements (Rails, Sidekiq, PostgreSQL+PostGIS, Redis)
- [ ] Resource impact on existing Docker infrastructure (`/dev/sda1`)
- [ ] OwnTracks GMS build setup on Pixel
- [ ] Google Takeout export process for location history backfill
- [ ] Dawarich REST API for pulling location data into RAG
- [ ] Coexistence verification with Google Location Services

### Implementation
1. Add Dawarich to `~/llm-stack/docker-compose.yml` (or separate compose file)
   - PostgreSQL+PostGIS, Redis, Rails app, Sidekiq worker
   - Reverse proxy: expose on localhost port (e.g. :3002)
   - Persistent storage in `~/llm-data/dawarich/`
2. Install OwnTracks (GMS build) on Pixel
   - HTTP mode → `http://localhost:3002/api/v1/owntracks/points?api_key=<key>`
   - Significant Changes mode (battery-friendly)
   - Disable battery optimization for OwnTracks
3. Backfill: export Google Takeout location history, import into Dawarich
4. Create `agents/location_sync.py`
   - Query Dawarich API for recent locations/visits
   - Incremental: track last synced timestamp
   - Output: daily location summaries (places visited, time spent, travel patterns)
   - Profile facts: home/work locations, commute patterns, frequent places
5. Create manifest, timer (daily), watchdog

### Key decisions
- Dawarich vs raw OwnTracks recorder: Dawarich — provides web UI, API, and import tools
- Expose externally? Only if needed for phone access outside LAN (Tailscale tunnel recommended)
- Granularity in RAG: daily summaries with place names, not raw GPS coordinates
- Privacy: location data stays local (Dawarich is self-hosted)

---

## Batch 8: Shell History + System Behavioral Sync

**Priority:** Low-medium — lightweight behavioral signal
**Effort:** Low (local files only)

### Research
- [x] Fish history format: `~/.local/share/fish/fish_history` (custom format, not plain text)
- [x] Profiler already has `shell-history` source — check implementation status
- [ ] VS Code recently opened projects / extension list

### Implementation
1. Extend profiler `shell-history` source or create standalone `agents/shell_sync.py`
   - Parse fish history file (entries are `- cmd:` blocks with timestamps)
   - Extract: command frequency, tools used, directories visited, time patterns
   - Output: periodic behavioral summary (not raw commands — too noisy for RAG)
   - Profile facts: top commands, tool adoption, workflow patterns
2. Add VS Code workspace sync
   - Read `~/.var/app/com.visualstudio.code/config/Code/User/globalStorage/state.vscdb`
   - Extract: recently opened projects, installed extensions
   - Profile facts: IDE usage patterns, technology interests from extensions
3. Timer: daily (behavioral data changes slowly)

### Key decisions
- Raw commands vs summaries: summaries only — raw shell history is too noisy and may contain secrets
- Privacy: strip any commands containing passwords, tokens, or env vars
- VS Code: read-only, just extract workspace list and extension names

---

## Batch 9: Claude.ai Web Conversation Import

**Priority:** Low-medium — fills gap in LLM conversation coverage
**Effort:** Low (manual export + automated parser)

### Research
- [ ] Export format: JSON structure from claude.ai Settings > Export
- [ ] Data volume: how many conversations, how large?
- [ ] Overlap with Claude Code transcripts (different conversations)
- [ ] Browser extension options for more frequent exports

### Implementation
1. Create `agents/claude_web_import.py`
   - Watch directory: `~/documents/rag-sources/claude-web/` for dropped ZIP/JSON exports
   - Parse: extract conversations, messages, timestamps, project names
   - Format: per-conversation markdown (same pattern as claude_code_sync)
   - Incremental: track conversation IDs to avoid re-processing
   - Profile facts: conversation topics, model usage, project distribution
2. Integrate with rag-ingest file watcher (auto-ingest when export is dropped)
3. Document the manual export workflow (Settings > Export > download > drop in folder)
4. Optional: install browser extension for easier exports

### Key decisions
- Automation level: semi-automated (manual export trigger, automated parsing)
- Frequency: weekly manual export is sufficient
- Conversation filtering: include all? Or filter by length (skip very short exchanges)?

---

## Batch 10: Work Obsidian Vault + Cross-Vault Sync

**Priority:** Low — depends on vault content
**Effort:** Very low (config change only)

### Research
- [ ] What's in `~/Documents/Work/`? Just a `30-system` directory?
- [ ] Is this a separate Obsidian vault or part of the Personal vault?
- [ ] Any confidentiality concerns with work content in personal RAG?

### Implementation
1. If separate vault: add `~/Documents/Work/` as a second watched path in `obsidian_sync.py`
   - Add vault-specific metadata tag (`vault: work` vs `vault: personal`)
   - Same filter logic (include/exclude dirs) but with work-specific patterns
2. If just a few files: symlink relevant dirs into `~/documents/rag-sources/` for direct ingest
3. Profile facts: work topic distribution, cross-vault theme overlap

### Key decisions
- Separate RAG metadata tag for work vs personal content
- Any filtering needed for sensitive work content?

---

## Implementation Order

| Phase | Batches | Rationale |
|-------|---------|-----------|
| **Phase 1** | 1 (Git), 2 (Langfuse), 10 (Work Vault) | Highest value, lowest effort, no external APIs |
| **Phase 2** | 3 (YouTube Music), 4 (Tidal), 6 (GitHub) | Music taste + professional signal, light API work |
| **Phase 3** | 5 (Fitbit), 8 (Shell/VS Code) | Health data (needs OAuth setup), behavioral signals |
| **Phase 4** | 7 (Location), 9 (Claude.ai) | Infrastructure (Docker service), semi-manual pipeline |

---

## Common Pattern (all batches)

Each sync agent follows the established pattern:

```
agents/{service}_sync.py          # Agent code
agents/manifests/{service}_sync.yaml  # Manifest
systemd/units/{service}-sync.timer    # Timer
systemd/units/{service}-sync.service  # Service unit
systemd/watchdogs/{service}-sync-watchdog  # Notification wrapper
~/.cache/{service}-sync/state.json    # Incremental state
~/.cache/{service}-sync/changes.jsonl # Change log
~/.cache/{service}-sync/{service}-profile-facts.jsonl  # Profile facts
~/documents/rag-sources/{service}/    # RAG markdown output
```

Each agent must:
- Support `--auto` (unattended timer mode) and `--full-sync` (force re-process)
- Write incremental state to `~/.cache/{service}-sync/state.json`
- Generate profile facts JSONL for the profiler
- Use `shared.notify.send_notification()` for status updates (respects dedup)
- Handle errors gracefully (log + continue, don't crash the daemon)
- Set `source_service` in markdown frontmatter for Qdrant filtering

---

## Infrastructure Prerequisites

- **Dawarich (Batch 7 only):** 4 additional Docker containers (Rails, Sidekiq, PostgreSQL+PostGIS, Redis)
- **Fitbit (Batch 5):** OAuth2 app registration at dev.fitbit.com
- **YouTube Music (Batch 3):** One-time browser cookie extraction
- **Tidal (Batch 4):** `tidalapi` session authentication
- **All others:** No new infrastructure needed
