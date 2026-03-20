# hapax-council

Externalized executive function infrastructure for a single operator. 45+ LLM agents coordinate through a filesystem-as-bus, governed by five weighted axioms with formal enforcement. Includes a voice daemon with conversational grounding measurement, a multi-camera temporal classification pipeline, a visual compositor, a reactive engine, and a consent framework.

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

Wake word (Whisper-based, fuzzy phonetic matching) → VAD → STT (faster-whisper, GPU) → Salience routing (concern graph activation, 4 weighted signals) → LLM (5 tiers via LiteLLM) → Streaming TTS (Kokoro, clause-level chunking) → Audio output. Phenomenal context renderer injects temporal bands and self-band, scaled per tier. Includes Bayesian presence engine (10 signals), frustration detector (8 mechanical signals), echo canceller (speexdsp AEC), and per-turn grounding evaluation (context anchoring, reference accuracy, acceptance classification).

### Hapax Logos

Tauri 2 desktop app with wgpu visual surface (6 GPU technique layers: gradient, reaction-diffusion, voronoi, wave, physarum, feedback) and React control panel. Terrain navigation (surface → horizon → field → ground → watershed → bedrock) with per-stratum data visualization. Includes system anatomy Flow page (live topology with particle-density edges), multi-camera ground core (6-camera grid with per-feed composite effects), and full-screen ambient canvas. Performance-optimized: image pool recycling, unified rAF loop, batch snapshot API, ambient shader LOD scaling.

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
| Conversational continuity (claims 1-5) | **Phase B** | 10/20 intervention sessions, BF=2.48 (continue) |
| Temporal classification (vision) | **Built** | MoViNet-A2 + CLIP ViT-B/32 + ByteTrack |

## Active research

### Conversational continuity

Investigates whether conversational context anchoring — injecting a
turn-by-turn conversation thread into the system prompt — produces
measurable grounding improvements over stateless per-turn processing.

Grounded in Clark & Brennan (1991) theory of conversational grounding.
Five pre-registered claims tested via Bayesian SCED (single-case
experimental design) with sequential stopping rules. Experiment
infrastructure includes per-turn Langfuse scoring (context anchoring
success, reference accuracy, acceptance type, frustration detection,
salience activation), trajectory analysis (within-session grounding
slopes), and turn-pair coherence metrics.

**Phase A (baseline)**: 20 sessions collected, all components OFF.
Baseline mean context_anchor_success: 0.320. Anchor trajectory
negative (-0.241) — grounding declines within sessions without thread.

**Phase B (intervention)**: stable_frame=true (conversation thread
injected). 10 of 20 sessions collected. Phase B mean anchor: 0.367
(+0.046 over baseline). Bayes Factor: 2.48 (anecdotal, continue
collecting). Sustained high-anchor sequences (0.7-0.8) observed in
substantive discussions — never seen in baseline. First positive
within-session trajectory at session 3.

**Measurement framework**: three score classes distinguish grounding-native
metrics (structurally zero for stateless systems), retrieval-parity
metrics (must match industry baselines), and failure-mode detectors
(alert if the system regresses toward profile-retrieval patterns).

Design documents, pre-registered hypotheses, and session data in
`agents/hapax_voice/proofs/`.

### Temporal classification (vision)

Multi-model inference pipeline for continuous environment understanding
across 4-6 cameras. Three subsystems:

- **Action recognition**: MoViNet-A2 streaming inference (~10ms/frame),
  classifies operator activity from discrete camera snapshots
- **Scene state**: CLIP ViT-B/32 zero-shot classification (~5ms/image),
  arbitrary scene states via text prompts without training
- **Change detection**: frame differencing + SSIM + background
  subtraction for environmental transitions

Cross-camera person tracking via ByteTrack with entity-level enrichment
(gaze, emotion, posture, gesture, action, depth). Temporal delta
correlator derives motion signals (velocity, direction, dwell time,
entry/exit) from sighting history. All enrichments consent-gated.

### Compositor performance

Five-batch optimization of the Tauri 2 / wgpu visual surface:
image pool recycling, gradient caching, unified rAF loop, backend
batch snapshot API (N HTTP round trips → 1), ambient shader LOD
scaling. Targets sustained 60fps with 6 camera feeds and 6 GPU
technique layers.

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
├── tests/            470+ test files
├── docs/             30+ research documents, design plans
└── skills/           17 Claude Code skills
```

## Ecosystem

- **[hapax-constitution](https://github.com/ryanklee/hapax-constitution)** — Governance specification (axioms, implications, canons)
- **hapax-council** (this repo) — Reference implementation
- **[hapax-officium](https://github.com/ryanklee/hapax-officium)** — Management-domain extraction
- **[hapax-watch](https://github.com/ryanklee/hapax-watch)** — Wear OS biometric companion
- **[cockpit-mcp](https://github.com/ryanklee/cockpit-mcp)** — MCP server for Claude Code (40 tools)

## License

Apache 2.0 — see [LICENSE](LICENSE).
