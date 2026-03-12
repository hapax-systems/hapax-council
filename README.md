# hapax-council

A personal operating environment where LLM agents are governed by constitutional axioms, coordinated through filesystem artifacts, and adapted to a structured model of their single human operator.

## What this is

Knowledge workers perform substantial executive function work that produces no deliverables: tracking what needs follow-up, maintaining context across conversations, noticing when things go stale, remembering to check things that don't remind them. This work scales poorly with attention and compounds when neglected. The operator has ADHD and autism, which makes executive function — task initiation, sustained attention, routine maintenance — a genuine cognitive constraint.

hapax-council externalizes this work into infrastructure. 26 agents on a single workstation handle management context, knowledge curation, system health, voice interaction, and environmental awareness. They coordinate through markdown files on disk (not message queues or databases), and a reactive engine watches for changes and cascades downstream work automatically. A meeting transcript placed in the right directory is processed, the relevant person's context is updated, nudges are recalculated, and a notification is queued — without operator action.

The cognitive constraint is encoded as a constitutional axiom (`executive_function`, weight 95): agents must be zero-config, errors must include next actions, routine work must be automated, state must be visible without investigation. The axiom produces 40+ derived implications enforced at commit time.

The system is constrained by four constitutional axioms defined in [hapax-constitution](https://github.com/ryanklee/hapax-constitution). Axioms are formal constraints with weighted enforcement, derived implications at graduated tiers (T0 blocks code from existing, T1 requires review, T2 warns), and commit-time hooks that prevent violations from landing. Single-operator is absolute (weight 100): no auth, no roles, no multi-user code anywhere. Management safety (weight 85) ensures agents never generate feedback language or coaching recommendations about individuals. An interpretive canon handles unforeseen cases; a precedent store builds consistency over time. See the constitution for the full governance architecture.

## Architecture

```
Coordination:  Markdown files with YAML frontmatter on disk (filesystem-as-bus)
Agents:        Pydantic AI, invoked by CLI/API/timer (stateless per-invocation)
Scheduling:    systemd timers (autonomous) + CLI (on-demand) + Claude Code (interactive)
API:           FastAPI cockpit (30+ endpoints, SSE for live updates)
Dashboard:     React SPA (council-web/)
Knowledge:     Qdrant (768d nomic-embed-text-v2-moe, 4 collections)
Inference:     LiteLLM proxy → Anthropic Claude / Google Gemini / Ollama (local RTX 3090)
Voice:         Always-on daemon (wake word, speaker ID, ambient perception, Gemini Live)
IDE:           VS Code extension + Claude Code skills and hooks
```

**Filesystem-as-bus** means agents coordinate by reading and writing files, not by calling each other. All state lives as markdown with YAML frontmatter — human-readable, git-versioned, debuggable with `cat` and `grep`. No broker, no schema migrations, no service to monitor. If the reactive engine goes down, the data is still there. Trades transactional consistency for debuggability. See [hapax-constitution](https://github.com/ryanklee/hapax-constitution) for the full rationale.

### Agents

**Management.** Prepare 1:1 context, generate morning briefings, track management practice across 6 dimensions, surface stale conversations and overloaded team members. Nudge the operator through push notifications, not dashboards that require checking.

**Sync pipeline.** Seven agents run on cron in a Docker container, keeping the knowledge base current: Google Drive, Calendar, Gmail, YouTube, Chrome history, Obsidian vault, and Claude Code transcripts flow into Qdrant for RAG retrieval.

**Voice daemon.** Always-on multimodal interaction with a perception engine that fuses audio and visual signals. Fast tick (2–3s): VAD, face detection, gaze tracking. Slow enrichment (10–15s): ambient sound classification, LLM workspace analysis. A governor maps environment state to pipeline directives using two composable primitives:

- **VetoChain** — constraint composition where any link can deny. A chain of conditions (e.g., "meeting in progress", "operator stressed", "ambient noise too high") is evaluated in order; the first veto wins and the action is blocked. Example: during a meeting, the veto chain blocks voice output.
- **FallbackChain** — priority-ordered action selection with graceful degradation. Tries the highest-priority action first (e.g., full voice response), falls back to the next (notification), then the next (silent log). If the preferred output mode is unavailable, the chain degrades without failing.

Both are composable — chains can be nested, and veto and fallback can be combined. The governor evaluates the full tree each tick.

**Analysis.** Content digestion, horizon scanning for component fitness, documentation drift detection and correction, interactive research with RAG context, code review.

**System.** Health monitoring every 15 minutes (deterministic, zero LLM), documentation drift detection weekly, knowledge base pruning (stale entries, near-duplicates), infrastructure manifest snapshots. When something breaks, agents fix what they can and notify about what they can't.

**Operator profiler.** Extracts and maintains a structured model of the operator across 13 dimensions (goals, constraints, work patterns, communication style, cognitive patterns, creative preferences) from 6 source types (config files, Claude Code transcripts, git repos, Langfuse traces, Obsidian vault, calendar data). The profile is injected into every agent's system prompt, so agent outputs are contextualized to this specific operator's priorities, knowledge, and working style. The profile updates continuously from source data; the operator does not configure it.

**Dev narrative.** Correlates git commits with Claude Code conversation transcripts to reconstruct why decisions were made, not just what changed.

| Category | Agents | LLM calls |
|----------|--------|-----------|
| Management | `management_prep`, `briefing`, `profiler`, `meeting_lifecycle` | Yes |
| Sync/RAG | `gdrive_sync`, `gcalendar_sync`, `gmail_sync`, `youtube_sync`, `chrome_sync`, `claude_code_sync`, `obsidian_sync` | No |
| Analysis | `digest`, `scout`, `drift_detector`, `research`, `code_review` | Yes |
| System | `health_monitor`, `introspect`, `knowledge_maint` | No |
| Knowledge | `ingest`, `query` | Mixed |
| Voice | `hapax_voice`, `audio_processor` | Mixed |
| Demo | `demo`, `demo_eval` + `demo_pipeline/` | Yes |
| Dev narrative | `dev_story/` | Yes |

### Reactive engine

When a file changes in the data directory, inotify fires. The change event is enriched with metadata (document type from YAML frontmatter, file category from path). Rules — pure functions mapping events to actions — evaluate against each event. Multiple rules can fire; duplicate actions collapse. Actions execute in phases: deterministic work first (cache refreshes, metric recalculation — unlimited concurrency, zero cost), then LLM work (synthesis, evaluation — semaphore-bounded at 2 concurrent to prevent GPU saturation or API cost runaway).

**Self-trigger prevention:** when the engine writes an output file, inotify fires again. Without prevention, the engine evaluates its own output in an infinite loop. The engine tracks its own writes and skips events from them. Notification delivery batches on a configurable interval to prevent storms.

### Model routing

All agents reference logical model aliases, not provider model IDs:

| Alias | Current route | Use |
|-------|---------------|-----|
| `fast` | Gemini 2.5 Flash | Scheduled agents (briefing, digest, drift detection) |
| `balanced` | Claude Sonnet 4 | On-demand agents (research, profiler, code review) |
| `reasoning` | Qwen 3.5 27B (local) | Complex local reasoning |
| `local-fast` | Qwen 3 8B (local) | Lightweight local tasks |

LiteLLM provides the routing layer with bidirectional fallback chains (cloud→cloud, local→cloud). When a better model ships, update the alias map — agents never change. All inference is traced in Langfuse with a $50/30d spend cap.

### Infrastructure

| Service | Purpose |
|---------|---------|
| Qdrant | Vector DB — collections: `claude-memory`, `profile-facts`, `documents`, `axiom-precedents` |
| LiteLLM | API gateway with model routing, fallback chains, Langfuse tracing |
| Ollama | Local inference on RTX 3090 (24GB VRAM) |
| PostgreSQL | Shared DB (LiteLLM, Langfuse) |
| Langfuse | LLM observability (traces, cost, latency) |
| ClickHouse + Redis + MinIO | Langfuse v3 backend |
| ntfy | Push notifications |
| n8n | Workflow automation |

## Quick start

```bash
git clone git@github.com:ryanklee/hapax-council.git
cd hapax-council
uv sync

# Run tests (all mocked, no infrastructure needed)
uv run pytest tests/ -q

# Run an agent
uv run python -m agents.health_monitor --history
uv run python -m agents.briefing --hours 24 --save
uv run python -m agents.research --interactive

# Start the cockpit API
uv run python -m cockpit.api --host 127.0.0.1 --port 8051
```

Agents require LiteLLM (localhost:4000), Qdrant (localhost:6333), and Ollama (localhost:11434) for production use. Tests are fully mocked.

## Project structure

```
hapax-council/
├── agents/           26 agents + 4 agent packages (hapax_voice, demo_pipeline, dev_story, system_ops)
├── shared/           40 shared modules (config, axioms, profile, frontmatter, context, embedding)
├── cockpit/          FastAPI API + 11 data collectors + reactive engine (watcher, rules, executor)
├── council-web/      React SPA dashboard
├── vscode/           VS Code extension
├── skills/           Claude Code skills (slash commands)
├── hooks/            Claude Code hooks (axiom scanning, session context)
├── axioms/           Governance axioms (registry + implications + precedents)
├── systemd/          Timer and service unit files + watchdog scripts
├── docker/           Dockerfiles + docker-compose (cockpit-api, sync-pipeline)
├── tests/            Test suite
└── docs/             Design documents, rules reference, plans
```

## Ecosystem

Three repositories compose the hapax system:

- **[hapax-constitution](https://github.com/ryanklee/hapax-constitution)** — The pattern specification. Defines the governance architecture: axioms, implications, interpretive canon, sufficiency probes, precedent store, filesystem-as-bus, reactive engine, three-tier agent model.
- **hapax-council** (this repo) — Personal operating environment. Reference implementation of the constitution. 26+ agents, voice daemon, RAG pipeline, reactive cockpit.
- **[hapax-officium](https://github.com/ryanklee/hapax-officium)** — Management-domain extraction. Originally part of council, extracted when the management agents proved usable independently. Designed to be forked. Includes a self-demonstrating capability and a synthetic seed corpus.

The three repos share infrastructure (Qdrant, LiteLLM, Ollama, PostgreSQL) but not code. Each implementation owns its full stack — agents, shared modules, reactive engine, API, dashboard. The constitution constrains both; the implementations evolve independently.

## License

Apache 2.0 — see [LICENSE](LICENSE).
