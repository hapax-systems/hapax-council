# hapax-council

Externalized executive function infrastructure governed by constitutional axioms. LLM agents handle cognitive work that produces no deliverables — tracking open loops, maintaining context across conversations, detecting staleness — for a single operator on a single workstation.

## Background

Knowledge workers perform executive function labor that compounds when neglected: recalling which direct report mentioned a blocker three meetings ago, noticing that a service has been degraded for three days without discussion, keeping documentation synchronized with a moving codebase, recognizing that a cancelled 1:1 left an issue unresolved.

For an operator with ADHD and autism, this labor represents a structural constraint. Task initiation, sustained attention, and routine maintenance are genuine cognitive bottlenecks. Conventional productivity tools assume the executive function they are meant to support — a todo list requires the same executive function to maintain that it is meant to compensate for.

hapax-council encodes these constraints as architecture. The system processes data, evaluates salience, and pushes notifications with concrete next actions. A meeting transcript placed in the right directory triggers ingestion, person context update, nudge recalculation, and notification queuing without operator involvement.

## Constitutional governance

The system is governed by five axioms defined in [hapax-constitution](https://github.com/ryanklee/hapax-constitution). These are structural constraints with formal enforcement at commit time, at runtime, and through a growing body of precedent decisions.

| Axiom | Weight | Constraint |
|-------|--------|------------|
| `single_user` | 100 | One operator. No authentication, no roles, no multi-user abstractions. |
| `executive_function` | 95 | Zero-config agents. Errors include next actions. Routine work automated. State visible without investigation. |
| `corporate_boundary` | 90 | Work data stays in employer systems. Home infrastructure is personal + management-practice only. |
| `interpersonal_transparency` | 88 | No persistent state about non-operator persons without an active, revocable consent contract. |
| `management_governance` | 85 | LLMs prepare context; humans deliver feedback. No generated coaching language about individuals. |

### Enforcement

Axioms produce concrete implications (~81 currently) using four interpretive canons from statutory and constitutional law:

- **Textualist**: what the axiom literally says. `single_user` says "one operator" — the codebase cannot contain structures that model distinct identities.
- **Purposivist**: what goal the axiom serves. `executive_function` accommodates specific cognitive constraints — an error that says "check the logs" violates the purpose even if it doesn't violate the text.
- **Absurdity doctrine**: reject interpretations that produce nonsensical results. `single_user` does not prohibit password-protecting a local interface.
- **Omitted-case**: what the axiom's silence means. `management_governance` does not say "LLMs may draft suggested feedback language" — the silence is a prohibition.

Implications are enforced at graduated tiers. **T0** implications are structurally blocked — Claude Code hooks scan every file edit, commit, and push against 20 regex patterns. **T1** requires human sign-off before merging. **T2** produces warnings. **T3** is advisory. Sufficiency probes verify positive requirements: not just "the system doesn't do X" but "the system provides Y" — error messages contain next actions, recurring agents have systemd timers.

### Precedent

When an implication encounters a novel case, the system records a precedent: the situation, the decision, the reasoning, and the distinguishing facts. Future encounters consult precedents via semantic search in Qdrant. Operator decisions (authority 1.0) bind over agent decisions (0.7), which bind over derived decisions (0.5).

See [axioms/README.md](axioms/README.md) for the full governance architecture.

### Consent framework

The `interpersonal_transparency` axiom governs data about non-operator persons. The system operates in a household with other people; cameras detect faces, microphones pick up voices, arrival patterns are observable. The enforcement mechanism is a consent contract: a bilateral agreement between operator and subject that enumerates permitted data categories, grants the subject inspection access to all data the system holds about them, and is revocable by either party at any time with full data purge on revocation. The `ConsentRegistry` gates data flows at the ingestion boundary — before embeddings, before persistence, before downstream processing.

Transient perception is permitted (VAD detects a voice but does not persist identity). Any derived or persistent state about a specific person requires a contract.

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

### Filesystem-as-bus

Agents coordinate by reading and writing markdown files with YAML frontmatter, not by calling each other through APIs or message queues. All state is human-readable, git-versioned, and debuggable with `cat` and `grep`. There is no broker, no schema migration, no service to monitor. This trades transactional consistency for debuggability and operational simplicity — a deliberate choice for a single-operator system where the operator is also the maintainer.

### Reactive engine

When a file changes in the data directory, inotify fires. The change event is enriched with metadata (document type from YAML frontmatter, file category from path). Rules — pure functions mapping events to actions — evaluate against each event. Multiple rules can fire; duplicate actions collapse. Actions execute in phases: deterministic work first (cache refreshes, metric recalculation — unlimited concurrency, zero cost), then LLM work (synthesis, evaluation — semaphore-bounded at 2 concurrent). Self-trigger prevention tracks the engine's own writes and skips events from them.

### Voice daemon and perception type system

The voice daemon (`agents/hapax_voice/`) is an always-on multimodal interaction system built on a perception type system for fusing signals that arrive at different rates — MIDI clock at <1ms, audio energy at 50ms, emotion at 1–2s, workspace analysis at 10–15s — into governance decisions.

The type system has three layers:

**Perceptives** — continuous and discrete signal abstractions. `Behavior[T]` represents a continuously-available value with a monotonic watermark. `Event[T]` represents a discrete occurrence. `Stamped[T]` is their common currency: an immutable snapshot frozen at a moment in time. These map to the Behavior/Event duality from functional reactive programming (Elliott 2009, Yampa, Reflex), adapted with watermarks from stream processing (Flink) for staleness reasoning.

**Detectives** — governance composition primitives. `VetoChain[C]` composes constraints where any link can deny, evaluated exhaustively for audit. Adding a veto can only make the system more restrictive — a monotonicity property from Cedar's authorization semantics. `FallbackChain[C, T]` selects the highest-priority eligible action with guaranteed graceful degradation. `FreshnessGuard` rejects decisions made on stale perception data.

**Directives** — action descriptions carrying full provenance. A `Command` is an immutable data object recording the selected action, the governance evaluation that produced it, the veto chain that allowed it, and the minimum watermark of the perception data that informed it. Commands do nothing until an `Executor` acts on them. The gap between description and execution is where governance evaluation occurs.

The primary combinator is `with_latest_from(trigger, behaviors)`, from Rx: when a fast event fires, sample all slow behaviors at their current values and emit a `FusedContext` with watermarks. See [agents/hapax_voice/README.md](agents/hapax_voice/README.md) for the full architecture.

### Agent manifest system

Every agent has a four-layer YAML manifest (`agents/manifests/`):

- **Structural** — identity, organizational position, dependencies, peer relationships
- **Functional** — purpose, inputs/outputs, capabilities, schedule, model requirements
- **Normative** — autonomy tier (full/supervised/advisory), decision scope, axiom bindings with roles (subject/enforcer/evaluator), RACI matrix
- **Operational** — health monitoring group, service tier, metrics source

The `AgentRegistry` loads and validates manifests, providing query methods by category, capability, autonomy tier, axiom binding, and RACI task.

### Agents

| Category | Agents | LLM | Purpose |
|----------|--------|-----|---------|
| Management | `management_prep`, `briefing`, `profiler`, `meeting_lifecycle` | Yes | 1:1 context, morning briefings, operator modeling, meeting prep |
| Sync/RAG | `gdrive_sync`, `gcalendar_sync`, `gmail_sync`, `youtube_sync`, `chrome_sync`, `claude_code_sync`, `obsidian_sync` | No | Seven cron agents keep the knowledge base current |
| Analysis | `digest`, `scout`, `drift_detector`, `research`, `code_review`, `deliberation_eval` | Yes | Content digestion, component fitness scanning, documentation drift, research |
| System | `health_monitor`, `introspect`, `knowledge_maint` | No | Health monitoring (deterministic, 15min cadence), knowledge pruning |
| Knowledge | `ingest`, `query` | Mixed | RAG ingestion pipeline, semantic search |
| Voice | `hapax_voice`, `audio_processor` | Mixed | Always-on daemon, audio processing |
| Demo | `demo`, `demo_eval` + `demo_pipeline/` | Yes | Self-demonstrating capability |
| Dev narrative | `dev_story/` | Yes | Correlates commits with conversation transcripts |

### Profile system

The operator profiler maintains a structured model across 11 dimensions, split between **trait dimensions** (stable, interview-sourced: identity, neurocognitive, values, communication style, relationships) and **behavioral dimensions** (dynamic, observation-sourced: work patterns, energy and attention, information seeking, creative process, tool usage, communication patterns). The split is enforced at write time — sync agents can only update behavioral dimensions. Traits are sealed once established through interview.

This profile is injected into every agent's system prompt. The profile updates continuously from source data; the operator does not configure it.

### SDLC pipeline

The system includes an LLM-driven software development lifecycle. The pipeline addresses the concern that velocity gains from LLM-authored code are transient while technical debt increases are persistent. Each stage includes a corresponding defense:

1. **Triage** (Sonnet) — classify type/complexity, check axiom relevance, find similar closed issues
2. **Plan** (Sonnet) — identify files, acceptance criteria, diff estimate
3. **Implement** (Opus via Claude Code) — sandboxed `agent/*` branch, run tests, open PR
4. **Adversarial Review** (Sonnet, independent context) — up to 3 rounds, then human escalation
5. **Axiom Gate** (Haiku) — structural checks + semantic LLM judge against constitutional axioms
6. **Auto-merge** (squash) on pass, block on T0 violation, advisory label on T1+

Different models are used for author and reviewer to avoid self-recognition bias. Agent PRs are restricted to `agent/*` branches with `agent-authored` labels. CODEOWNERS protects governance files. Every stage logs to a JSONL event stream with correlated trace IDs.

### Model routing

All agents reference logical model aliases, not provider model IDs:

| Alias | Current route | Use |
|-------|---------------|-----|
| `fast` | Gemini 2.5 Flash | Scheduled agents (briefing, digest, drift detection) |
| `balanced` | Claude Sonnet 4 | On-demand agents (research, profiler, code review) |
| `reasoning` | Qwen 3.5 27B (local) | Complex local reasoning |
| `local-fast` | Qwen 3 8B (local) | Lightweight local tasks |

LiteLLM provides routing with bidirectional fallback chains. When a model is updated, the alias map changes — agents do not. All inference is traced in Langfuse.

## Domain specifications

The voice perception domain maintains two complementary formal specifications:

**North Star** (`docs/superpowers/specs/2026-03-13-domain-schema-north-star.md`) — a domain schema where every prose sentence decomposes into a valid type sequence from the implemented type system. Contains behavior/event/executor registries, governance chain compositions, validation traces, and a coverage matrix.

**Dog Star** (`docs/superpowers/specs/2026-03-13-dog-star-spec.md`) — the negative complement. Forbidden type sequences derived from axioms: compositions that are syntactically constructible but semantically prohibited. Each entry identifies the violated axiom and the current enforcement level (Type/Runtime/Convention/None). Entries marked `[gap]` indicate places where forbidden sequences execute successfully.

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
├── agents/           26+ agents + 4 agent packages (hapax_voice, demo_pipeline, dev_story, system_ops)
│   └── manifests/    YAML agent manifests (4-layer schema, RACI, axiom bindings)
├── shared/           41+ shared modules (config, axioms, profile, consent, agent_registry, deliberation_metrics)
├── cockpit/          FastAPI API + 11 data collectors + reactive engine (watcher, rules, executor)
├── council-web/      React SPA dashboard (health, agents, nudges, chat, demos)
├── vscode/           VS Code extension (chat, RAG, management commands)
├── skills/           15 Claude Code skills (slash commands)
├── hooks/            Claude Code hooks (axiom scanning, session context)
├── axioms/           Governance axioms (registry + implications + precedents + consent contracts)
├── systemd/          Timer and service unit files + watchdog scripts
├── docker/           Dockerfiles + docker-compose (cockpit-api, sync-pipeline)
├── tests/            2700+ tests (all mocked, no infrastructure needed)
├── docs/             Design documents, domain specs, research, plans
│   └── superpowers/  North Star spec, Dog Star spec, enforcement gaps audit, prior art survey
└── scripts/          SDLC pipeline scripts (triage, plan, review, axiom gate)
```

## Ecosystem

Three repositories compose the hapax system:

- **[hapax-constitution](https://github.com/ryanklee/hapax-constitution)** — The pattern specification. Defines the governance architecture: axioms, implications, interpretive canon, sufficiency probes, precedent store, filesystem-as-bus, reactive engine, three-tier agent model.
- **hapax-council** (this repo) — Personal operating environment. Reference implementation of the constitution. 26+ agents, voice daemon, RAG pipeline, reactive cockpit.
- **[hapax-officium](https://github.com/ryanklee/hapax-officium)** — Management-domain extraction. Originally part of council, extracted when the management agents proved usable independently. Designed to be forked. Includes a self-demonstrating capability and a synthetic seed corpus.

The three repos share infrastructure (Qdrant, LiteLLM, Ollama, PostgreSQL) but not code. Each implementation owns its full stack. The constitution constrains both; the implementations evolve independently.

## License

Apache 2.0 — see [LICENSE](LICENSE).
