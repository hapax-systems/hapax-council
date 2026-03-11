# ai-agents

Personal agent infrastructure for a single-user LLM-first computing environment. Not a framework or library — purpose-built for one operator, one workstation, one stack.

## Architecture

Three-tier system. All tiers share LiteLLM (model routing), Qdrant (vector memory), and Langfuse (observability).

```
Tier 1: Interactive    → Claude Code (command center, full MCP access)
Tier 2: On-demand      → This repo — Pydantic AI agents invoked via CLI
Tier 3: Autonomous     → systemd timers + services (health, briefing, drift, backup)
```

Flat orchestration: Claude Code invokes agents, agents never invoke each other. Agents are stateless per-invocation — persistent state lives in Qdrant or the filesystem.

## Agents

| Agent | LLM | Purpose | Invocation |
|-------|-----|---------|------------|
| research | Yes | RAG-backed research with Qdrant | `uv run python -m agents.research` |
| code-review | Yes | Code review with operator context | `uv run python -m agents.code_review` |
| profiler | Yes | Operator profile extraction from all sources | `uv run python -m agents.profiler` |
| health-monitor | No | Deterministic health checks (18 groups, ~85 checks), auto-fix | `uv run python -m agents.health_monitor` |
| introspect | No | Infrastructure manifest generator | `uv run python -m agents.introspect` |
| drift-detector | Yes | Docs vs reality comparison, `--fix` mode | `uv run python -m agents.drift_detector` |
| activity-analyzer | No* | Langfuse/health/drift telemetry aggregation | `uv run python -m agents.activity_analyzer` |
| briefing | Yes | Daily operational briefing from all telemetry | `uv run python -m agents.briefing` |
| scout | Yes | Horizon scanner — evaluates stack vs external landscape | `uv run python -m agents.scout` |
| management-prep | Yes | 1:1 prep, team snapshots, management overview | `uv run python -m agents.management_prep` |
| meeting-lifecycle | Yes | Meeting prep, transcript ingestion, weekly review | `uv run python -m agents.meeting_lifecycle` |
| digest | Yes | Content/knowledge digest — aggregates recent RAG content | `uv run python -m agents.digest` |
| knowledge-maint | No* | Qdrant vector DB hygiene — dedup, prune, stats | `uv run python -m agents.knowledge_maint` |
| gdrive-sync | No | Google Drive → RAG pipeline sync | `uv run python -m agents.gdrive_sync` |
| gcalendar-sync | No | Google Calendar → RAG pipeline sync | `uv run python -m agents.gcalendar_sync` |
| gmail-sync | No | Gmail metadata → RAG pipeline sync | `uv run python -m agents.gmail_sync` |
| youtube-sync | No | YouTube subscriptions/likes → RAG sync | `uv run python -m agents.youtube_sync` |
| claude-code-sync | No | Claude Code transcripts → RAG sync | `uv run python -m agents.claude_code_sync` |
| obsidian-sync | No | Obsidian vault → RAG sync | `uv run python -m agents.obsidian_sync` |
| chrome-sync | No | Chrome history + bookmarks → RAG sync | `uv run python -m agents.chrome_sync` |
| audio-processor | No | Ambient audio → VAD, classify, diarize, transcribe → RAG | `uv run python -m agents.audio_processor` |
| hapax-voice | Yes | Always-on voice daemon: wake word, speaker ID, PANNs ambient classification, Gemini Live S2S + local STT/TTS, context gate | `uv run python -m agents.hapax_voice` |

\* Optional `--synthesize` flag for LLM summary.

Google sync agents share common flags: `--auth` (OAuth setup), `--full-scan`/`--full-sync` (full re-sync), `--auto` (timer mode), `--stats` (show collection stats). `gdrive_sync` also supports `--fetch ID` (single file fetch). Sync agents claude-code-sync, obsidian-sync, and chrome-sync share `--full-sync`, `--auto`, and `--stats` flags.

Planned: sample-curator, draft, midi-programmer.

## Cockpit

System management web dashboard. FastAPI API server backs a React SPA frontend.

```bash
uv run cockpit                # Launch FastAPI API server on :8051
uv run cockpit --once         # Plain text CLI snapshot
```

Web frontend lives in `~/projects/cockpit-web/` (React SPA, `pnpm dev` on `:5173`).

Includes operator interview system for structured profile discovery (Socratic interrogation that feeds into the profiler pipeline).

## Takeout Processor

Multi-service Google Takeout ZIP ingestion at `shared/takeout/`. Dual data paths:

- **Unstructured** (emails, notes, documents) → markdown with YAML frontmatter → `~/documents/rag-sources/takeout/{service}/` → RAG watchdog + profiler LLM extraction
- **Structured** (search queries, purchases, calendar, location) → JSONL → deterministic ProfileFact mapping via `profiler_bridge.py` (zero LLM cost, confidence 0.95)

14 services across 3 tiers:

| Tier | Services | Parser |
|------|----------|--------|
| 1 (high signal) | chrome, search, keep, youtube, calendar, contacts, tasks | activity, chrome, keep, calendar, contacts, tasks |
| 2 (high volume) | gmail, drive, chat | gmail (MBOX streaming), drive, chat |
| 3 (supplementary) | maps, photos, purchases, gemini | location, photos, purchases, activity |

```bash
uv run python -m shared.takeout --list-services ~/Downloads/takeout.zip
uv run python -m shared.takeout ~/Downloads/takeout.zip --services chrome,keep --since 2025-01-01
uv run python -m shared.takeout ~/Downloads/takeout.zip --dry-run
uv run python -m shared.takeout ~/Downloads/takeout.zip --resume       # Resume interrupted run
uv run python -m shared.takeout --progress ~/Downloads/takeout.zip     # Show progress
```

Progress tracking enables Ctrl+C and resume for large exports. The profiler `--auto` flow loads structured facts automatically.

## Proton Mail Processor

Export ingestion for Proton Mail at `shared/proton/`. Processes paired `.eml` + `.metadata.json` files from `proton-mail-export-cli`.

Same dual-path architecture as Takeout:
- **Received mail** → markdown with YAML frontmatter → `~/documents/rag-sources/proton/mail/*.md` → RAG + profiler
- **Sent mail** → structured JSONL → `profiles/proton-structured.jsonl` → deterministic profiler facts (zero LLM cost)

Filters out spam/trash and automated senders by default. Supports date filtering and progress tracking.

```bash
uv run python -m shared.proton ~/Downloads/proton-export/mail_*/              # Process full export
uv run python -m shared.proton ~/Downloads/proton-export/mail_*/ --dry-run --max-records 50
uv run python -m shared.proton ~/Downloads/proton-export/mail_*/ --since 2025-01-01
uv run python -m shared.proton ~/Downloads/proton-export/mail_*/ --include-spam  # Include spam/trash
```

## Operator Profile

The system maintains a structured model of its operator across multiple dimensions — identity, workflow, decision patterns, music production, neurocognitive patterns, and more. This profile:

- Is built through automated extraction (config files, transcripts, Langfuse traces, Google Takeout, Proton Mail, Obsidian vault management notes) and interactive interview
- Includes management dimensions (`management_practice`, `team_leadership`) extracted deterministically from vault people/coaching/feedback/meeting notes via `shared/management_bridge.py`
- Lives in `profiles/operator.json` (structured) and `profiles/operator.md` (readable)
- Gets injected into every agent's system prompt via `shared/operator.py`
- Includes a neurocognitive dimension discovered through interview — cognitive patterns (task initiation, energy cycles, focus, motivation) that agents accommodate as system design inputs

The `executive_function` axiom in `operator.json` defines the system's core responsibility: externalized executive function infrastructure. Behavioral variance is expected baseline, not noise.

## Project Structure

```
agents/           Tier 2 agent implementations (22 agents)
cockpit/          FastAPI API server, data collectors, interview system
shared/
  config.py       Model aliases, LiteLLM/Qdrant clients, embedding (single + batch)
  email_utils.py  Shared email parsing utilities (RFC 5322, automated sender filtering)
  takeout/        Google Takeout processor (14 services, 13 parsers, dual-path output)
  proton/         Proton Mail export processor (EML + metadata.json pairs)
  notify.py       Unified notifications (ntfy + desktop)
  management_bridge.py  Deterministic management fact extraction from vault (zero LLM)
  vault_writer.py Obsidian vault egress (writes to 30-system/, 10-work/, 32-bridge/)
  operator.py     Operator profile injection
  langfuse_client.py  Langfuse API client
  llm_export_converter.py  Claude/Gemini data export → markdown
tests/            1524 tests (pytest, no LLM calls)
profiles/         Persistent state — operator profile, health history, briefing, scout reports
systemd/          Timer and service unit files
n8n-workflows/    Workflow automation definitions (briefing-push, health-relay, etc.)
```

## Shared Infrastructure

`shared/config.py` — model aliases, LiteLLM/Qdrant/Langfuse clients, embedding helpers.

| Alias | Model | Use Case |
|-------|-------|----------|
| fast | claude-haiku | Cheap, quick tasks |
| balanced | claude-sonnet | Default for most agents |
| reasoning | deepseek-r1:14b | Complex reasoning (Ollama) |
| coding | qwen-coder-32b | Code generation (Ollama) |
| local-fast | qwen-7b | Lightweight local tasks |

Embeddings: `nomic-embed-text-v2-moe` via Ollama (768d). Requires `search_query:` / `search_document:` prefixes. Both single (`embed()`) and batch (`embed_batch()`) functions available.

## Tier 3 Timers

| Timer | Schedule | Purpose |
|-------|----------|---------|
| health-monitor | Every 15 min | Auto-fix + notify on failures |
| profile-update | Every 12h | Incremental operator profile update |
| meeting-prep | Daily 06:30 | Auto-generate 1:1 prep docs |
| digest | Daily 06:45 | Content digest — 15 min before briefing |
| daily-briefing | Daily 07:00 | Morning briefing + notification |
| scout | Weekly Wed 10:00 | Horizon scan |
| knowledge-maint | Weekly Sun 04:30 | Qdrant dedup, stale pruning, stats |
| drift-detector | Weekly Sun 03:00 | Doc drift detection |
| manifest-snapshot | Weekly Sun 02:30 | Infrastructure state snapshot |
| llm-backup | Weekly Sun 02:00 | Full stack backup |
| Obsidian Desktop | Always running (autostart) | Vault sync via Obsidian Sync (desktop app, not a timer) |
| gdrive-sync | Every 2h | Google Drive RAG sync |
| gcalendar-sync | Every 30min | Google Calendar RAG sync |
| gmail-sync | Every 1h | Gmail metadata RAG sync |
| youtube-sync | Every 6h | YouTube subscriptions/likes sync |
| claude-code-sync | Every 2h | Claude Code transcript RAG sync |
| obsidian-sync | Every 30min | Obsidian vault RAG sync |
| chrome-sync | Every 1h | Chrome history + bookmarks sync |
| audio-recorder | Always on | Continuous mic recording (Blue Yeti, ffmpeg) |
| audio-processor | Every 30min | Audio segmentation + transcription + RAG |
| audio-archiver | Daily 03:00 | Archive raw audio to Google Drive (rclone) |

Manual timer invocation:

```bash
systemctl --user start health-monitor.service     # Run health check now
systemctl --user start daily-briefing.service      # Generate briefing now
systemctl --user start scout.service               # Run horizon scan now
systemctl --user list-timers                       # Show all timer schedules
journalctl --user -u health-monitor.service -n 20  # View recent logs
```

## Multi-Channel Access

| Channel | Transport | Ingress | Egress |
|---------|-----------|---------|--------|
| Desk | localhost | Web dashboard, chat | Web dashboard, notify-send |
| Mobile | Tailscale + Telegram | Telegram bot messages | ntfy push, Telegram replies |
| Knowledge | Obsidian Sync | Vault notes → RAG | System → vault markdown |
| Cloud | rclone (Google Drive) | Drive files → RAG | (read-only) |

## Dependencies

- Python 3.12+, managed with `uv`
- pydantic-ai with LiteLLM backend
- FastAPI + uvicorn (cockpit API server)
- qdrant-client, langfuse, ollama, pyyaml
- Audio ML: faster-whisper, pyannote-audio, panns-inference, silero-vad, torchaudio

## Development

```bash
uv sync                       # Install dependencies
uv run pytest tests/ -q       # Run tests (1524 passing)
uv run cockpit                # Launch API server on :8051
```

All LLM calls route through LiteLLM at `localhost:4000`. Secrets loaded via `pass` + `direnv`. Never hardcoded.
