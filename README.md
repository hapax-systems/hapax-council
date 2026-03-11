# hapax-council

Externalized executive function infrastructure.

This is a personal operating environment where LLM agents handle the cognitive work that ADHD and autism make expensive: tracking open loops, maintaining context across conversations, surfacing what needs attention, and reacting to changes without requiring the operator to remember to check. It runs on a single workstation for a single person. There is no multi-user mode. That's not a limitation — it's a [constitutional axiom](https://github.com/ryanklee/hapax-constitution).

## What it does

26 agents operate across management, knowledge, sync, voice, and system domains. They don't chat with you — they read and write markdown files on disk, and a reactive engine watches for changes and cascades downstream work automatically.

**Management agents** prepare 1:1 context, generate morning briefings, track management practice patterns, and profile the operator's management self-awareness across 6 dimensions. They surface stale conversations, overloaded team members, and open loops — then nudge the operator through push notifications, not dashboards that require checking.

**Sync agents** (7 of them, running on cron in a Docker container) keep the knowledge base current: Google Drive, Calendar, Gmail, YouTube, Chrome history, Obsidian vault, and Claude Code transcripts all flow into Qdrant for RAG retrieval.

**Voice daemon** (`hapax_voice`) provides always-on voice interaction: wake word detection, speaker identification, screen awareness, and Gemini Live conversation — the system is present in the room, not just in a terminal.

**System agents** monitor infrastructure health every 15 minutes, detect documentation drift weekly, prune stale knowledge, and snapshot the infrastructure manifest. When something breaks, they fix what they can and notify about what they can't.

**A reactive engine** ties it all together. When a file changes in the data directory, inotify fires, rules evaluate, and phased actions execute: deterministic work first (unlimited), then LLM work (semaphore-bounded, max 2 concurrent). Drop a meeting transcript in the right directory and the system processes it, updates the relevant person's context, recalculates nudges, and queues a notification — without being asked.

## The governance model

Every agent operates under constitutional axioms defined in [`axioms/registry.yaml`](axioms/registry.yaml). These aren't guidelines — they're weighted constraints with derived blocking implications enforced by commit hooks:

- **single_user** (weight 100) — One operator. No auth, no roles, no collaboration features. Code that implements multi-user patterns is a constitutional violation.
- **executive_function** (weight 95) — The system exists to externalize executive function. Agents must be zero-config, errors must include next actions, routine work must be automated. If the operator has to remember to do something, the system has failed.
- **management_safety** (weight 95) — LLMs prepare, humans deliver. Agents never generate feedback language, coaching recommendations, or evaluations directed at individual team members.
- **corporate_boundary** (weight 90) — Work data stays in employer-controlled systems. The home system processes personal and management-practice data only.

See [hapax-constitution](https://github.com/ryanklee/hapax-constitution) for the full governance architecture. See [hapax-officium](https://github.com/ryanklee/hapax-officium) for a management-domain fork designed to be cloned and grown by individual engineering managers — it includes a self-demonstrating capability where the system bootstraps from synthetic data and demos itself to an audience it profiles.

## Architecture

```
State: Markdown files with YAML frontmatter on disk (filesystem-as-bus)
Agents: Pydantic AI (on-demand, CLI-invoked) + systemd timers (autonomous)
API: FastAPI cockpit with 30+ endpoints, SSE for live updates
Dashboard: React SPA (council-web)
Knowledge: Qdrant (768d, nomic-embed-text) with 4 collections
Inference: LiteLLM proxy → Anthropic / Gemini / Ollama (local RTX 3090)
Voice: Always-on daemon (wake word, speaker ID, Gemini Live, ambient awareness)
IDE: VS Code extension (chat, RAG search, management commands)
```

### Agent roster

| Category | Agents | LLM? |
|----------|--------|------|
| Management | `management_prep`, `management_briefing`, `management_profiler`, `management_activity`, `meeting_lifecycle`, `status_update`, `review_prep` | Mixed |
| Sync/RAG | `gdrive_sync`, `gcalendar_sync`, `gmail_sync`, `youtube_sync`, `chrome_sync`, `claude_code_sync`, `obsidian_sync` | No |
| Analysis | `digest`, `scout`, `drift_detector`, `research`, `code_review` | Yes |
| System | `health_monitor`, `introspect`, `knowledge_maint`, `system_check` | No |
| Content | `ingest`, `query` | Mixed |
| Voice | `hapax_voice`, `audio_processor` | Mixed |
| Demo | `demo`, `demo_eval` + `demo_pipeline/` | Yes |
| Dev narrative | `dev_story/` (git extraction, conversation correlation, critical moments) | Yes |

### Infrastructure

| Service | Purpose |
|---------|---------|
| Qdrant | Vector DB (4 collections: claude-memory, profile-facts, documents, axiom-precedents) |
| LiteLLM | API gateway with model routing + Langfuse tracing |
| Ollama | Local inference (RTX 3090, 24GB VRAM) |
| PostgreSQL | Shared DB for LiteLLM + Langfuse |
| Langfuse | LLM observability (traces, cost, latency) |
| ntfy | Push notifications |

## Quick start

```bash
git clone git@github.com:ryanklee/hapax-council.git
cd hapax-council
uv sync

# Run tests (all mocked, no infrastructure needed)
uv run pytest tests/ -q

# Run an agent
uv run python -m agents.health_monitor --history
uv run python -m agents.management_prep --person "Sarah Chen" --team-snapshot
uv run python -m agents.briefing --hours 24 --save

# Start the cockpit API
uv run python -m cockpit.api --host 127.0.0.1 --port 8051
```

## Project structure

```
hapax-council/
├── agents/           26 agents + 4 agent packages (voice, demo_pipeline, dev_story, system_ops)
├── shared/           35+ shared modules (config, axioms, profile, frontmatter, context tools)
├── cockpit/          FastAPI API + 11 data collectors + reactive engine (watcher, 12 rules, executor)
├── council-web/      React SPA dashboard
├── vscode/           VS Code extension
├── skills/           Claude Code skills (slash commands)
├── hooks/            Claude Code hooks (axiom scanning, session context)
├── axioms/           Governance axioms (registry + implications + precedents)
├── systemd/          Timer and service unit files
├── docker/           Dockerfiles + docker-compose (cockpit-api + sync-pipeline containers)
├── tests/            Test suite
└── docs/             Design documents, rules reference
```

## License

Apache 2.0 — see [LICENSE](LICENSE).
