# hapax-council

Externalized executive function infrastructure for a single operator. 45+ LLM agents coordinate through a filesystem-as-bus, governed by five weighted axioms with formal enforcement. Includes a voice daemon, visual compositor, reactive engine, and consent framework.

Single-operator is a constitutional axiom (weight 100). No auth, roles, or multi-user features.

## Core properties

- **Constitutional governance** — Five axioms produce 90 implications via four interpretive canons from statutory law. Enforced at four tiers: T0 blocked, T1 flagged, T2 advisory, T3 lint. Novel cases produce precedents stored with authority hierarchy (operator 1.0 > agent 0.7 > derived 0.5).
- **Consent as information flow control** — ConsentLabel (DLM join-semilattice), Labeled[T] (LIO functor wrapper), Says monad (Abadi DCC principal attribution), PosBool(X) provenance semirings, GateToken (linear discipline). Properties verified via Hypothesis property-based testing.
- **Phenomenological perception** — Husserlian temporal bands (retention/impression/protention/surprise), Bayesian presence engine (8-signal fusion), apperception self-band (7-step cascade with 6 safeguards against pathological attractors), SystemStimmung (6-dimension self-state vector).
- **Salience-based voice routing** — Concern graph activation maps to 5 model tiers (LOCAL→CAPABLE). Includes de-escalation hysteresis and stimmung-aware tier downgrade.
- **System anatomy visualization** — Live React Flow topology with particle-density edges, breathing nodes, staleness color shift, and attention decay. 9 nodes, 16 edges, polls every 3s from /dev/shm.

## Quick start

```bash
git clone git@github.com:ryanklee/hapax-council.git && cd hapax-council
uv sync
uv run pytest tests/ -q          # 444 test files, all mocked
uv run ruff check .               # lint
uv run pyright                    # type check
```

For production use (agents, cockpit API, voice daemon), see [Architecture](#architecture) below.

## Architecture

Three independent loops communicate through the filesystem and /dev/shm:

```
Loop 1: Perception (voice daemon, 2.5s tick)
  Sensors → Bayesian presence → Governor → Consent → perception-state.json

Loop 2: Visual Aggregator (3s tick, adaptive 0.5-5s)
  Perception → Stimmung → Temporal Bands → Apperception → /dev/shm

Loop 3: Reactive Engine (inotify, event-driven)
  profiles/ + axioms/ → Rule evaluation → Phased execution (deterministic → GPU → cloud)
```

### Filesystem-as-bus

Agents coordinate by reading and writing markdown files with YAML frontmatter on disk. Atomic rename for writes. State survives restarts and is inspectable with standard tools.

### The phenomenological stack

```
Sensors (cameras, mics, watch, keyboard, screens)
  → Perception tick (2.5s, EnvironmentState)
  → Bayesian Presence Engine (8 signals → P(operator_present))
  → Perception Ring Buffer (50s history)
  → Temporal Band Formatter (retention / impression / protention / surprise)
  → Apperception Cascade (7-step self-observation, coherence, reflections)
  → Stimmung (6 dimensions → stance: nominal/cautious/degraded/critical)
  → Phenomenal Context Renderer (6 progressive layers, tier-scaled)
  → LLM System Prompt
```

### Consent framework

```
Principal (sovereign/bound)
  → Says[T] (principal attribution — Abadi DCC)
  → Labeled[T] (consent label + provenance — LIO/DLM)
  → ProvenanceExpr (PosBool semiring: tensor ⊗ / plus ⊕)
  → ConsentGatedWriter (single chokepoint, mints GateToken)
  → ConsentGatedReader (pre-LLM retrieval gate)
  → RevocationPropagator (cascade purge via why-provenance)
```

### Voice daemon

Wake word → VAD → STT (faster-whisper) → Salience routing (concern graph activation) → LLM (5 tiers) → TTS (Kokoro) → Audio output. Phenomenal context renderer injects temporal bands and self-band, scaled per tier.

### Hapax Logos

Tauri 2 desktop app with wgpu visual surface (6 GPU technique layers: gradient, reaction-diffusion, voronoi, wave, physarum, feedback) and React control panel. Includes a system anatomy Flow page (live topology) and a full-screen ambient canvas (HapaxPage).

### Reactive engine

inotify watches `profiles/`, `axioms/`, `rag-sources/`. 12 rules. Three-phase execution (deterministic → GPU → cloud). Phases 1-2 skipped when stimmung stance is degraded/critical or operator is absent.

## Status

| Claim | Status | Evidence |
|-------|--------|----------|
| ConsentLabel is a join-semilattice | **Proven** | 10 Hypothesis properties |
| Labeled[T] is a functor | **Proven** | 5 Hypothesis properties |
| Principal non-amplification | **Proven** | 3 Hypothesis properties |
| Says monad laws | **Proven** | 3 laws + functor + authority |
| Provenance semiring laws | **Proven** | 10 Hypothesis properties (commutativity, associativity, identity, annihilation, distributivity) |
| Perception type system (L0-L9) | **Proven** | 192 matrix tests + 62 Hypothesis |
| Consent threads through composition | **Proven** | 4 test files, 6 Hypothesis |
| Apperception cascade safeguards | **Proven** | 113 tests (6 safeguard categories) |
| Temporal bands presence integration | **Built** | 15 existing + 18 phenomenal context tests |
| Voice routing (salience + hysteresis + stimmung) | **Built** | 27 salience router tests |
| System anatomy visualization | **Built** | TypeScript + Rust compile-clean |
| Alignment tax ≤ 20% | **Measured** | Label ops: 0.3µs join, 0.1µs flow check |

## Agents (33 manifested)

| Category | Count | Examples |
|----------|-------|---------|
| Sync/RAG | 11 | chrome, calendar, drive, gmail, git, youtube, obsidian, claude_code, langfuse, weather, health_connect |
| Observability | 5 | health_monitor, activity_analyzer, audio_processor, ingest, introspect |
| Synthesis | 8 | briefing, digest, demo, research, scout, code_review, video_processor, studio_compositor |
| Governance | 3 | drift_detector, deliberation_eval, alignment_tax_meter |
| Interaction | 4 | hapax_voice, watch_receiver, context_restore, contradiction_detector |
| Knowledge | 2 | knowledge_maint, query |

## Infrastructure

| Service | Port | Purpose |
|---------|------|---------|
| Cockpit API | :8051 | FastAPI (20+ routes, SSE streaming) |
| LiteLLM | :4000 | LLM gateway → Claude/Gemini/Ollama |
| Qdrant | :6333 | Vector DB (6 collections, 768d nomic-embed) |
| Ollama | :11434 | Local inference (RTX 3090) |
| Langfuse | :3000 | LLM observability |
| PostgreSQL | :5432 | Audit/operational DB |
| Prometheus | :9090 | Metrics |
| Grafana | :3001 | Dashboards |

## Project structure

```
hapax-council/
├── agents/           33 agents + hapax_voice (95 files), demo_pipeline, dev_story
│   └── manifests/    YAML agent manifests (4-layer schema)
├── shared/           83 modules (governance, consent formalisms, perception, config)
│   └── governance/   22 modules (consent, Says, provenance, gate_token, temporal)
├── cockpit/          43 modules (FastAPI API, reactive engine, copilot, interview)
├── hapax-logos/      Tauri 2 desktop app (wgpu + React)
│   ├── src-tauri/    Rust backend (visual surface, system flow, browser engine)
│   └── src/          React frontend (8 pages including Flow + HapaxPage)
├── council-web/      DEPRECATED — superseded by hapax-logos
├── axioms/           5 axioms, 90 implications, precedents, contracts, schemas
├── specs/            8 operational principles + spec registry
├── tests/            444 test files
├── docs/             Compendium, 21 research documents, design plans
└── skills/           17 Claude Code skills
```

## Ecosystem

- **[hapax-constitution](https://github.com/ryanklee/hapax-constitution)** — Governance specification (axioms, implications, canons)
- **hapax-council** (this repo) — Reference implementation
- **[hapax-officium](https://github.com/ryanklee/hapax-officium)** — Management-domain extraction
- **[hapax-watch](https://github.com/ryanklee/hapax-watch)** — Wear OS biometric companion
- **[cockpit-mcp](https://github.com/ryanklee/cockpit-mcp)** — MCP server for Claude Code (40 tools)

## Compendium

For exhaustive system documentation, see [`docs/compendium.md`](docs/compendium.md) — 22 sections covering architecture, subsystems, decisions, evolution, and operational reference.

## License

Apache 2.0 — see [LICENSE](LICENSE).
