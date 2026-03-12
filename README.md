# hapax-council

A personal operating environment where LLM agents are governed by constitutional axioms, coordinated through filesystem artifacts, and adapted to a structured model of their single human operator.

## What this is

hapax-council runs on a single workstation for a single person. 26 agents operate across management, knowledge, sync, voice, and system domains. They read and write markdown files on disk, and a reactive engine watches for changes and cascades downstream work automatically. The system handles the cognitive overhead that compounds silently for knowledge workers: tracking open loops, maintaining relational context, surfacing what needs attention, reacting to changes without requiring the operator to remember to check.

The operator has ADHD and autism. Executive function — task initiation, sustained attention, routine maintenance — is a genuine cognitive constraint, not a preference. This is encoded as a constitutional axiom (`executive_function`, weight 95): agents must be zero-config, errors must include next actions, routine work must be automated, state must be visible without investigation. The axiom produces 40+ derived implications enforced at commit time.

The system is constrained by four axioms defined in [hapax-constitution](https://github.com/ryanklee/hapax-constitution). Single-operator is absolute (weight 100): no auth, no roles, no multi-user code anywhere. Management safety (weight 85) ensures agents never generate feedback language or coaching recommendations about individuals — they prepare context, humans deliver words. See the constitution for the full governance architecture, including the interpretive canon and sufficiency probes.

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

### Agents

**Management.** Prepare 1:1 context, generate morning briefings, track management practice across 6 dimensions, surface stale conversations and overloaded team members. Nudge the operator through push notifications, not dashboards that require checking.

**Sync pipeline.** Seven agents run on cron in a Docker container, keeping the knowledge base current: Google Drive, Calendar, Gmail, YouTube, Chrome history, Obsidian vault, and Claude Code transcripts flow into Qdrant for RAG retrieval.

**Voice daemon.** Always-on multimodal interaction with a perception engine that fuses audio and visual signals. Fast tick (2–3s): VAD, face detection, gaze tracking. Slow enrichment (10–15s): ambient sound classification, LLM workspace analysis. A governor maps environment state to pipeline directives using two composable primitives — VetoChain (constraint composition, deny-wins) and FallbackChain (priority-ordered action selection, graceful degradation).

**Analysis.** Content digestion, horizon scanning for component fitness, documentation drift detection and correction, interactive research with RAG context, code review.

**System.** Health monitoring every 15 minutes (deterministic, zero LLM), documentation drift detection weekly, knowledge base pruning (stale entries, near-duplicates), infrastructure manifest snapshots. When something breaks, agents fix what they can and notify about what they can't.

**Operator profiler.** Extracts and maintains a structured profile of the operator across 13 dimensions (goals, constraints, work patterns, communication style, cognitive patterns, creative preferences). Sources: config files, Claude Code transcripts, git repos, Langfuse traces, Obsidian vault. The profile is injected into every agent's system prompt — every briefing, research call, and management prep is contextualized with knowledge about what the operator cares about and how they work.

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

When a file changes in the data directory, inotify fires. Rules evaluate against the enriched change event and produce phased actions: deterministic work first (unlimited concurrency), then LLM work (semaphore-bounded, max 2 concurrent). Drop a meeting transcript in the right directory and the system processes it, updates the relevant person's context, recalculates nudges, and queues a notification — without being asked.

Self-trigger prevention ensures engine-written files don't re-trigger evaluation. Notification delivery batches on a configurable interval.

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

## Related

hapax-council is the reference implementation of the [hapax-constitution](https://github.com/ryanklee/hapax-constitution) pattern — a governance architecture for LLM agent systems using constitutional axioms, filesystem-as-bus coordination, and a reactive engine.

[hapax-officium](https://github.com/ryanklee/hapax-officium) is a management-domain instantiation of the same pattern, designed to be forked by individual engineering managers. It includes a self-demonstrating capability and a synthetic seed corpus.

## License

Apache 2.0 — see [LICENSE](LICENSE).
