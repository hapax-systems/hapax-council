# System Topology

## Management Agents (~/projects/hapax-council/)

Invoke: `cd ~/projects/hapax-council && uv run python -m agents.<name> [flags]`

| Agent | LLM? | Key Flags |
|-------|------|-----------|
| management_prep | Yes | `--person NAME`, `--team-snapshot`, `--overview` |
| meeting_lifecycle | Yes | `--prepare`, `--transcript FILE`, `--weekly-review` |
| briefing | Yes | `--hours N`, `--save` |
| profiler | Yes | `--auto`, `--digest`, `--source TYPE` |
| scout | Yes | |
| demo | Yes | `--topic TOPIC`, `--duration N`, `--voice`, `--audience NAME` |
| demo_eval | Yes | `--demo-dir PATH` |
| research | Yes | `--interactive` |
| code_review | Yes | `--file PATH`, `--diff` |
| digest | Yes | `--save` |
| health_monitor | No | `--fix`, `--history` |
| drift_detector | Yes | `--fix`, `--json` |
| knowledge_maint | No | `--summarize` |
| activity_analyzer | No | `--hours N`, `--json` |
| introspect | No | `--json` |
| query | No | `--collection NAME` |
| ingest | No | `--watch`, `--stats` |
| gdrive_sync | No | `--auth`, `--full-scan`, `--auto`, `--fetch ID`, `--stats` |
| gcalendar_sync | No | `--auth`, `--full-sync`, `--auto`, `--stats` |
| gmail_sync | No | `--auth`, `--full-sync`, `--auto`, `--stats` |
| youtube_sync | No | `--auth`, `--full-sync`, `--auto`, `--stats` |
| claude_code_sync | No | `--full-sync`, `--auto`, `--stats` |
| obsidian_sync | No | `--full-sync`, `--auto`, `--stats` |
| chrome_sync | No | `--full-sync`, `--auto`, `--stats` |
| audio_processor | No | `--process`, `--stats`, `--reprocess FILE` |
| hapax_voice | No | `--check`, `--config PATH` (daemon — runs as always-on service) |

Shared modules: `shared/google_auth.py` (OAuth2 token management for all Google agents), `shared/calendar_context.py` (calendar-aware context for briefing/prep agents).

## Management Timers (systemd user)

| Timer | Schedule | Purpose |
|-------|----------|---------|
| meeting-prep | Daily 06:30 | Auto-generate 1:1 prep docs |
| digest | Daily 06:45 | Content/knowledge digest |
| daily-briefing | Daily 07:00 | Morning briefing (consumes digest) |
| profile-update | Every 6h | Incremental operator profile |
| health-monitor | Every 15 min | Deterministic health checks + auto-fix |
| vram-watchdog | Every 30 min | GPU memory management |
| scout | Weekly Wed 10:00 | Horizon scan |
| drift-detector | Weekly Sun 03:00 | Documentation drift detection |
| knowledge-maint | Weekly Sun 04:30 | Qdrant dedup/pruning/stats |
| manifest-snapshot | Weekly Sun 02:30 | Infrastructure state snapshot |
| llm-backup | Weekly Sun 02:00 | Full stack backup |
| obsidian-webui-sync | Every 6h | Vault sync to Open WebUI |
| audio-recorder | Always on | Continuous mic recording (ffmpeg) |
| audio-processor | Every 30min | Audio segmentation + transcription + RAG (GPU) |
| audio-archiver | Daily 03:00 | rclone move raw audio to Google Drive |
| hapax-voice | Always on | Voice interaction daemon (wake word, presence, TTS/STT) |
| bt-keepalive | Always on | Silent stream to iLoud BT monitors (prevents auto-standby) |

### Sync Pipeline Container

7 RAG sync agents run in a Docker container (`hapax-sync-pipeline`) via supercronic, replacing their former systemd timers. Managed by `docker compose` in `~/projects/hapax-council/`.

| Agent | Prod Schedule | Purpose |
|-------|---------------|---------|
| gdrive_sync | Every 2h | Google Drive RAG sync |
| gcalendar_sync | Every 30min | Google Calendar RAG sync |
| gmail_sync | Every 1h | Gmail metadata RAG sync |
| youtube_sync | Every 6h | YouTube subscriptions/likes sync |
| claude_code_sync | Every 2h | Claude Code transcript RAG sync |
| obsidian_sync | Every 30min | Obsidian vault RAG sync |
| chrome_sync | Every 1h | Chrome history + bookmarks sync |

`CYCLE_MODE` env var selects `crontab.prod` or `crontab.dev` (reduced frequencies). audio_processor stays on host (requires GPU/CUDA).

### Cycle Modes

Timer schedules contract during heavy development. `hapax-mode dev` installs systemd timer drop-in overrides for non-containerized timers (profile-update, digest, daily-briefing, drift-detector, knowledge-maint). `hapax-mode prod` removes overrides. Mode file: `~/.cache/hapax/cycle-mode`. See `systemd/overrides/dev/` for dev schedules.

For the 7 containerized sync agents, cycle mode is controlled by `CYCLE_MODE=dev` env var: `CYCLE_MODE=dev docker compose up -d sync-pipeline`.

## Model Aliases (via LiteLLM at :4000)

| Alias | Model | Use |
|-------|-------|-----|
| fast | claude-haiku | Cheap quick tasks |
| balanced | claude-sonnet | Default for agents |
| reasoning | deepseek-r1:14b | Complex reasoning (local) |
| coding | qwen-coder-32b | Code generation (local) |
| local-fast | qwen-7b | Lightweight local tasks |

Embedding: nomic-embed-text-v2-moe (768d). Requires `search_query:` / `search_document:` prefixes.
VRAM: RTX 3090 = 24GB. One large Ollama model at a time.

## Qdrant Collections

| Collection | Dims | Purpose |
|-----------|------|---------|
| claude-memory | 768 | Claude Code persistent memory |
| profile-facts | 768 | Operator profile facts |
| documents | 768 | RAG document chunks (payloads include `source_service`, `source_platform` metadata from Google sync agents) |
| axiom-precedents | 768 | Axiom governance precedents |

## Key Paths

| Path | Purpose |
|------|---------|
| ~/llm-stack/ | Docker compose + service configs |
| ~/projects/hapax-council/ | Agent implementations + cockpit API |
| ~/projects/hapaxromana/ | Architecture specs + axioms |
| ~/projects/hapax-system/ | Claude Code skills/rules/hooks |
| ~/projects/cockpit-web/ | Management dashboard (React SPA) |
| ~/projects/hapax-vscode/ | VS Code extension (chat, RAG, management) |
| ~/Documents/Work/ | Work vault (git-synced) |
| ~/Documents/Personal/ | Personal vault (local) |
| ~/Documents/Work/10-work/people/ | Team member notes |
