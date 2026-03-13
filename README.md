# hapax-council

Externalized executive function infrastructure governed by constitutional axioms. LLM agents handle the cognitive work that produces no deliverables — tracking open loops, maintaining context across conversations, noticing when things go stale — for a single operator on a single workstation.

## The Problem This Solves

Knowledge workers perform substantial executive function labor that scales poorly with attention and compounds when neglected: remembering what needs follow-up, maintaining awareness of team dynamics, keeping documentation in sync with reality, noticing that a service degraded three days ago and nobody mentioned it. For an operator with ADHD and autism, this labor isn't merely inconvenient — task initiation, sustained attention, and routine maintenance are genuine cognitive constraints that conventional productivity tools do not address because they assume the executive function they're meant to support.

hapax-council encodes these constraints as architecture. The system doesn't remind the operator to check a dashboard; it processes the data, evaluates what matters, and pushes a notification with a concrete next action. A meeting transcript placed in the right directory is ingested, the relevant person's context is updated, nudges are recalculated, and a notification is queued — without operator involvement. The operator's cognitive budget is spent on judgment, not bookkeeping.

## Constitutional Governance

The system is governed by five axioms defined in [hapax-constitution](https://github.com/ryanklee/hapax-constitution). These are not configuration options or feature flags. They are formal constraints with weighted enforcement that cannot be relaxed by any agent, any code path, or any operational pressure.

| Axiom | Weight | Constraint |
|-------|--------|------------|
| `single_user` | 100 | One operator. No authentication, no roles, no multi-user abstractions. This is absolute. |
| `executive_function` | 95 | Zero-config agents. Errors include next actions. Routine work automated. State visible without investigation. |
| `corporate_boundary` | 90 | Work data stays in employer systems. Home infrastructure is personal + management-practice only. |
| `interpersonal_transparency` | 88 | No persistent state about non-operator persons without an active, revocable consent contract. |
| `management_governance` | 85 | LLMs prepare context; humans deliver feedback. No generated coaching language about individuals. |

Each axiom generates concrete implications at graduated enforcement tiers. **T0** implications are structurally blocked — code that violates them cannot merge. **T1** implications require human review. **T2** implications produce warnings. The system currently enforces 78+ derived implications across the five axioms, including implications that govern the system's own deliberative process.

### How Governance Works

Axioms are not aspirational statements. They are executable constraints with four enforcement mechanisms:

**Implication derivation.** Each axiom generates specific, testable implications using interpretive canons borrowed from legal reasoning: textualist reading (what does the text say), purposivist reading (what goal does it serve), absurdity doctrine (reject interpretations that produce absurd results), and omitted-case handling (what does silence mean). This produces implications like `ex-init-001` ("agents must run with zero configuration") rather than vague directives.

**Commit-time enforcement.** Claude Code hooks scan every proposed change against T0 implications. A PR that introduces a user authentication check is blocked before it reaches review. This is structural prevention, not code review.

**Precedent database.** When an axiom implication encounters a novel situation that the implication text doesn't clearly resolve, the decision is recorded as a precedent in Qdrant with authority weights (operator decisions outweigh agent decisions). Future encounters consult precedent before escalating. This is the common law mechanism — consistency over time without requiring that every edge case be specified in advance.

**Supremacy analysis.** Domain axioms (scoped to a specific subsystem) cannot override constitutional axioms (system-wide). When implications from different axioms produce conflicting guidance, the higher-weighted axiom prevails, and the tension is surfaced for operator review. This prevents the equivalent of a state law overriding a constitutional right.

### The Executive Function Axiom

The `executive_function` axiom (weight 95) deserves particular attention because it encodes disability accommodation as governance architecture, not as a quality-of-life enhancement. Its T0 implications — agents must be zero-config, errors must include next actions, routine work must be automated — are not preferences. They are structural requirements that every agent, every error path, and every operational workflow must satisfy.

This extends to the system's own meta-processes. Four implications govern the deliberation system (adversarial debates between LLM agents over axiom tensions): hoop tests detect whether multi-round exchanges involve genuine position shifts or performative agreement, activation rate tracking monitors whether deliberations produce real governance artifacts, concession asymmetry flags one-sided capitulation, and trend monitoring catches process degradation over time. The governance system governs itself through the same mechanism it uses to govern agents.

### The Consent Framework

The `interpersonal_transparency` axiom (weight 88) creates a hard boundary around non-operator person data. The system operates in a household with other people. Cameras detect faces, microphones pick up voices, arrival patterns are observable. Without explicit governance, this data would accumulate into persistent models of other people's behavior — something the operator considers ethically unacceptable regardless of technical convenience.

The enforcement mechanism is a consent contract: a bilateral agreement between operator and subject that enumerates permitted data categories, grants the subject inspection access to all data the system holds about them, and is revocable by either party at any time with full data purge on revocation. The `ConsentRegistry` gates data flows at the ingestion boundary — before embeddings are extracted, before state is persisted, before any downstream processing occurs.

This is more restrictive than most commercial systems. Transient perception is permitted (VAD detects a voice but doesn't persist identity), but any derived or persistent state requires a contract. The system doesn't default to "it's just environmental sensing."

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

### Filesystem-as-Bus

Agents coordinate by reading and writing markdown files with YAML frontmatter, not by calling each other through APIs or message queues. All state is human-readable, git-versioned, and debuggable with `cat` and `grep`. There is no broker, no schema migration, no service to monitor. If the reactive engine goes down, the data is still there. This trades transactional consistency for debuggability and operational simplicity — a deliberate choice for a single-operator system where the operator is also the maintainer.

### The Reactive Engine

When a file changes in the data directory, inotify fires. The change event is enriched with metadata (document type from YAML frontmatter, file category from path). Rules — pure functions mapping events to actions — evaluate against each event. Multiple rules can fire; duplicate actions collapse. Actions execute in phases: deterministic work first (cache refreshes, metric recalculation — unlimited concurrency, zero cost), then LLM work (synthesis, evaluation — semaphore-bounded at 2 concurrent to prevent GPU saturation or API cost runaway). Self-trigger prevention tracks the engine's own writes and skips events from them.

### The Voice Daemon and Perception Type System

The voice daemon (`agents/hapax_voice/`) is an always-on multimodal interaction system built on a perception type system that borrows from multiple research traditions — functional reactive programming, DSP audio synthesis, and distributed systems — to solve a specific problem: fusing signals that arrive at vastly different rates (MIDI clock at <1ms, audio energy at 50ms, emotion at 1–2s, workspace analysis at 10–15s) into governance decisions without losing data or correctness.

The type system has three layers:

**Perceptives** — continuous and discrete signal abstractions. `Behavior[T]` represents a continuously available value with a monotonic watermark (like a cell that always has a current reading). `Event[T]` represents a discrete occurrence (like a button press or a MIDI tick). `Stamped[T]` is an immutable snapshot with a timestamp, the common currency between the two. These map to the Behavior/Event duality from functional reactive programming (Yampa, Reflex, RxPY), adapted for a single-machine, in-process runtime without the heavyweight infrastructure of Kafka or ROS.

**Detectives** — governance composition primitives. `VetoChain[C]` composes constraints where any link can deny (deny-wins, order-independent, evaluated exhaustively for audit). `FallbackChain[C, T]` selects the highest-priority eligible action with graceful degradation (a default always exists). `FreshnessGuard` rejects decisions made on stale perception data. These compose into a pipeline: trigger → fuse → freshness check → veto → fallback → command. Adding a veto can only make the system more restrictive, never less. This monotonicity property means governance changes are safe by construction.

**Directives** — action descriptions that carry full provenance. A `Command` is an inspectable, immutable data object recording what action was selected, what governance evaluation produced it, which veto chain allowed it, and the minimum watermark of the perception data that informed it. Commands do nothing until an `Executor` acts on them. The gap between description and execution is where governance lives — a denied command carries its `VetoResult` as provenance, and the executor enforces it.

The key combinator is `with_latest_from(trigger, behaviors)`, borrowed from Rx: when a fast event fires, sample all slow behaviors at their current values and emit a `FusedContext` with watermarks. This is how MIDI-rate decisions incorporate second-scale perception without blocking or polling. See [agents/hapax_voice/README.md](agents/hapax_voice/README.md) for the full architecture.

### Agent Manifest System

Every agent has a four-layer YAML manifest (`agents/manifests/`) that serves as its formalized personnel file:

- **Structural** — identity, organizational position, dependencies, peer relationships
- **Functional** — purpose, inputs/outputs, capabilities, schedule, model requirements
- **Normative** — autonomy tier (full/supervised/advisory), decision scope, axiom bindings, RACI matrix
- **Operational** — health monitoring group, service tier, metrics source

The `AgentRegistry` loads and validates these manifests, providing query methods by category, capability, autonomy tier, axiom binding, and RACI task. This is the single source of truth for what agents exist, what they're allowed to do, and who is responsible for what.

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

### Profile System

The operator profiler maintains a structured model across 11 dimensions, split between **trait dimensions** (stable, interview-sourced: identity, neurocognitive, values, communication style, relationships) and **behavioral dimensions** (dynamic, observation-sourced: work patterns, energy and attention, information seeking, creative process, tool usage, communication patterns). The split is enforced at write time — sync agents can only update behavioral dimensions. Traits are sealed once established through interview.

This profile is injected into every agent's system prompt, so agent outputs are contextualized to this specific operator's priorities, knowledge, and cognitive patterns. The profile updates continuously from source data; the operator does not configure it.

### SDLC Pipeline

The system includes an LLM-driven software development lifecycle where issues flow through automated stages:

1. **Triage** (Sonnet) — classify type/complexity, check axiom relevance, find similar closed issues
2. **Plan** (Sonnet) — identify files, acceptance criteria, diff estimate
3. **Implement** (Opus via Claude Code) — sandboxed `agent/*` branch, run tests, open PR
4. **Adversarial Review** (Sonnet, independent context) — up to 3 rounds, then human escalation
5. **Axiom Gate** (Haiku) — structural checks + semantic LLM judge against constitutional axioms
6. **Auto-merge** (squash) on pass, block on T0 violation, advisory label on T1+

Different models are used for author and reviewer to prevent collusiveness. Agent PRs are restricted to `agent/*` branches with `agent-authored` labels. CODEOWNERS protects governance files. Every stage logs to a JSONL event stream with correlated trace IDs.

### Model Routing

All agents reference logical model aliases, not provider model IDs:

| Alias | Current route | Use |
|-------|---------------|-----|
| `fast` | Gemini 2.5 Flash | Scheduled agents (briefing, digest, drift detection) |
| `balanced` | Claude Sonnet 4 | On-demand agents (research, profiler, code review) |
| `reasoning` | Qwen 3.5 27B (local) | Complex local reasoning |
| `local-fast` | Qwen 3 8B (local) | Lightweight local tasks |

LiteLLM provides routing with bidirectional fallback chains. When a better model ships, update the alias map — agents never change. All inference is traced in Langfuse.

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

## Domain Specifications

The voice perception domain maintains two complementary formal specifications:

**North Star** (`docs/superpowers/specs/2026-03-13-domain-schema-north-star.md`) — a domain schema where every prose sentence decomposes into a valid type sequence from the implemented type system. This constrains the specification to statements that project onto real types — no aspirational prose without type backing. Contains behavior/event/executor registries, governance chain compositions, validation traces, and a coverage matrix showing which behaviors are sourced, governed, and tested.

**Dog Star** (`docs/superpowers/specs/2026-03-13-dog-star-spec.md`) — the negative complement. Forbidden type sequences derived from axioms: compositions that are syntactically constructible but semantically prohibited. Each entry identifies the axiom it violates and the current enforcement level (Type/Runtime/Convention/None). Entries marked `[gap]` indicate places where forbidden sequences execute successfully — the system is honest about where it trusts social conventions over runtime checks.

## Quick Start

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

## Project Structure

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
