# hapax-council

Constitutional governance for personal AI systems. LLM agents handle cognitive work — tracking open loops, maintaining context, detecting staleness — for a single operator on a single workstation, governed by five weighted axioms with formal enforcement at commit time, runtime, and through accumulated precedent.

**Core guarantee**: Data about non-operator persons cannot propagate through the system without an active consent contract. Consent labels form a verified join-semilattice (DLM). Labeled values are functorial wrappers that preserve consent through all transformations. Principals enforce non-amplification of delegated authority. These properties are universally quantified via property-based testing, not spot-checked.

## Key properties

- **Consent as information flow control** — ConsentLabel implements the Decentralized Label Model (Myers & Liskov 2000) as a join-semilattice with bottom. LIO-style floating labels (Stefan et al. 2011) prevent consent laundering through transformation chains.
- **Constitutional governance with legal interpretation** — Five axioms produce ~90 implications via four interpretive canons from statutory law (textualist, purposivist, absurdity doctrine, omitted-case). Enforcement at four tiers: T0 blocked, T1 flagged, T2 advisory, T3 lint.
- **Perception type system** — Behavior/Event duality from FRP (Elliott 2009), watermarks from stream processing (Flink), suppression envelopes from DSP. 10-layer composition ladder, each layer proven via 7-dimension test matrix.
- **Alignment tax inversion** — Governance overhead ~20% vs. 30-40% literature baseline. LLMs as both governed and governance reduces alignment cost.
- **4594 tests**, all mocked, no infrastructure needed. 18+ algebraic properties proven via Hypothesis.

## Quick start

```bash
git clone git@github.com:ryanklee/hapax-council.git && cd hapax-council
uv sync
uv run pytest tests/ -q          # full suite, all mocked
uv run ruff check .               # lint
uv run pyright                    # type check
```

For production use (agents, cockpit API, voice daemon), see [Architecture](#architecture) below.

## For researchers

Three papers are in preparation targeting POST/CSF, AAMAS, and FAccT. Each is independently self-contained.

| Paper | Contribution | Venue | Status |
|-------|-------------|-------|--------|
| A: Consent as Information Flow | DLM labels + LIO floating labels + PosBool why-provenance for consent propagation | POST, CSF | Types proven, threading L0-L1 implemented |
| B: Epistemic Carrier Dynamics | Factor graphs + LDPC sparsity bounds for cross-domain error correction | AAMAS | Theoretical, carrier type implemented |
| C: Constitutional Governance | Alignment tax inversion, norm refinement with interpretive canons, separation of powers | FAccT | Governance stack fully implemented |

**Theory-to-code map**: See [`shared/README.md`](shared/README.md) for a complete mapping from formal concepts to source files with proven properties.

**Exposition**: Progressive introduction from system overview to expert-conversation vocabulary in [`docs/superpowers/exposition/`](docs/superpowers/exposition/).

**Theory document**: Full formal specification in [`docs/superpowers/specs/2026-03-13-computational-constitutional-governance.md`](docs/superpowers/specs/2026-03-13-computational-constitutional-governance.md).

## For developers

```bash
uv run python -m agents.health_monitor --history    # run an agent
uv run python -m agents.briefing --hours 24 --save  # morning briefing
uv run python -m cockpit.api --host 127.0.0.1 --port 8051  # API server
```

Agents require LiteLLM (localhost:4000), Qdrant (localhost:6333), and Ollama (localhost:11434) for production use. Tests are fully mocked.

- **Architecture**: [below](#architecture)
- **Governance**: [`axioms/README.md`](axioms/README.md)
- **Perception type system**: [`agents/hapax_voice/README.md`](agents/hapax_voice/README.md)
- **Consent algebra**: [`shared/README.md`](shared/README.md)

## Status

| Claim | Status | Evidence |
|-------|--------|----------|
| ConsentLabel is a join-semilattice | **Proven** | 10 hypothesis properties ([`tests/test_consent_label.py`](tests/test_consent_label.py)) |
| Labeled[T] is a functor | **Proven** | 5 hypothesis properties ([`tests/test_labeled.py`](tests/test_labeled.py)) |
| Principal non-amplification | **Proven** | 3 hypothesis properties ([`tests/test_principal.py`](tests/test_principal.py)) |
| Governor consistent with can_flow_to | **Proven** | Hypothesis property ([`tests/test_governor.py`](tests/test_governor.py)) |
| Perception type system (L0-L9) | **Proven** | 192 matrix tests + 62 hypothesis ([`tests/hapax_voice/`](tests/hapax_voice/)) |
| Consent threads through composition (L0-L9) | **Proven** | All 10 layers, 4 test files, 6 hypothesis ([`tests/hapax_voice/test_consent_threading_*.py`](tests/hapax_voice/)) |
| Constitutive rules with defeasible override | **Built** | 27 tests ([`tests/test_constitutive.py`](tests/test_constitutive.py)) |
| Governance coherence (rule→implication→enforcement) | **Proven** | 6 hypothesis properties: factory ≡ can_flow_to, role symmetry, idempotence ([`tests/test_agent_governor.py`](tests/test_agent_governor.py)) |
| Revocation cascades through provenance | **Built** | 26 tests, runtime-wired to carrier registry ([`tests/test_revocation*.py`](tests/)) |
| Carrier dynamics (cross-domain error correction) | **Built** | 22 tests, reactive engine integration ([`tests/test_carrier_intake.py`](tests/test_carrier_intake.py)) |
| Alignment tax ≤ 20% | **Estimated** | Self-reported, not independently measured |

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

Agents coordinate by reading and writing markdown files with YAML frontmatter, not by calling each other through APIs or message queues. All state is human-readable, git-versioned, and debuggable with `cat` and `grep`. This trades transactional consistency for debuggability and operational simplicity — a deliberate choice for a single-operator system.

### Reactive engine

inotify watches the data directory. Change events are enriched with metadata (document type from frontmatter, file category from path). Rules — pure functions mapping events to actions — evaluate against each event. Actions execute in phases: deterministic work first (unlimited concurrency), then LLM work (semaphore-bounded at 2 concurrent).

### Constitutional governance

Five axioms with weighted severity, refined into ~90 implications via four interpretive canons from statutory law. Enforced at four tiers (T0 blocked → T3 advisory). Novel cases produce precedents stored in Qdrant with authority hierarchy (operator 1.0 > agent 0.7 > derived 0.5). See [`axioms/README.md`](axioms/README.md).

### Consent framework

ConsentLabel (DLM join-semilattice) → Labeled[T] (LIO functor wrapper) → GovernorWrapper (AMELI boundary enforcement) → RevocationPropagator (PosBool why-provenance cascading). See [`shared/README.md`](shared/README.md).

### Voice daemon and perception type system

10-layer composition ladder fusing signals from sub-millisecond (MIDI clock) to 15-second (LLM workspace analysis) cadences. FRP Behavior/Event duality with stream-processing watermarks and DSP suppression envelopes. See [`agents/hapax_voice/README.md`](agents/hapax_voice/README.md).

### Agents

| Category | Agents | LLM | Purpose |
|----------|--------|-----|---------|
| Management | `management_prep`, `briefing`, `profiler`, `meeting_lifecycle` | Yes | 1:1 context, morning briefings, operator modeling |
| Sync/RAG | `gdrive_sync`, `gcalendar_sync`, `gmail_sync`, `youtube_sync`, `chrome_sync`, `claude_code_sync`, `obsidian_sync` | No | Seven cron agents keep the knowledge base current |
| Analysis | `digest`, `scout`, `drift_detector`, `research`, `code_review`, `deliberation_eval` | Yes | Content digestion, fitness scanning, documentation drift |
| System | `health_monitor`, `introspect`, `knowledge_maint` | No | Health monitoring (deterministic, 15min cadence) |
| Voice | `hapax_voice`, `audio_processor` | Mixed | Always-on daemon, audio processing |

### Background

This system exists because conventional productivity tools assume the executive function they are meant to support. For an operator with ADHD and autism, task initiation, sustained attention, and routine maintenance are genuine cognitive bottlenecks. A todo list requires the same executive function to maintain that it is meant to compensate for. hapax-council encodes these constraints as architecture: the `executive_function` axiom (weight 95) is a disability accommodation enforced as a constitutional requirement.

## Project structure

```
hapax-council/
├── agents/           26+ agents + 4 agent packages (hapax_voice, demo_pipeline, dev_story, system_ops)
│   └── manifests/    YAML agent manifests (4-layer schema, RACI, axiom bindings)
├── shared/           68+ shared modules (consent algebra, axiom enforcement, config)
├── cockpit/          FastAPI API + data collectors + reactive engine
├── council-web/      React SPA dashboard (health, agents, nudges, chat, demos)
├── vscode/           VS Code extension (chat, RAG, management commands)
├── axioms/           Governance axioms (registry + implications + precedents + contracts)
├── tests/            4594 tests (all mocked, no infrastructure needed)
├── docs/             Theory specs, research, exposition, design documents
│   └── superpowers/  Formal specifications, prior art survey, publication strategy
├── skills/           15 Claude Code skills (slash commands)
├── hooks/            Claude Code hooks (axiom scanning, session context)
├── scripts/          SDLC pipeline scripts (triage, plan, review, axiom gate)
├── systemd/          Timer and service unit files
└── docker/           Dockerfiles + docker-compose
```

## Ecosystem

- **[hapax-constitution](https://github.com/ryanklee/hapax-constitution)** — The pattern specification. Governance architecture: axioms, implications, interpretive canons, precedent store, filesystem-as-bus.
- **hapax-council** (this repo) — Reference implementation. 26+ agents, voice daemon, RAG pipeline, reactive cockpit.
- **[hapax-officium](https://github.com/ryanklee/hapax-officium)** — Management-domain extraction. Designed to be forked.

## Citation

```bibtex
@software{hapax_council,
  author = {Lee, Ryan K.},
  title = {hapax-council: Constitutional Governance for Personal AI Systems},
  url = {https://github.com/ryanklee/hapax-council},
  year = {2026}
}
```

## License

Apache 2.0 — see [LICENSE](LICENSE).
