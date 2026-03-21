# hapax-council

An implementation of Clark & Brennan's (1991) conversational grounding theory in a production voice AI, evaluated via Single Case Experimental Design (SCED) with Bayesian analysis.

[![CI](https://github.com/ryanklee/hapax-council/actions/workflows/ci.yml/badge.svg)](https://github.com/ryanklee/hapax-council/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

## Background

Current voice AI systems implement memory as profile-gated retrieval. Clark & Brennan's (1991) contribution-acceptance cycle, repair sequences, and effort calibration have not been implemented in production systems. Shaikh et al. (ACL 2025) report that frontier LLMs score 23.23% on grounding tasks. Shaikh et al. (NAACL 2024) identify RLHF as a factor suppressing grounding acts in trained models.

This project implements grounding mechanics external to the LLM: a discourse unit state machine (Traum 1994), concern-aware repair thresholds, acceptance classification, Grounding Quality Index (GQI), and 2D effort calibration. These are injected as directives into the system prompt rather than trained into model weights.

## Research Design

**Methodology:** ABA reversal SCED (Single Case Experimental Design) with Bayesian Estimation Supersedes the t-Test (BEST). Sequential stopping rules. HDI+ROPE decision criteria.

**Independent variable:** Grounding system (3 treatment components + 1 diagnostic sentinel):
1. Conversation thread with conceptual pact preservation (Brennan & Clark 1996)
2. Grounding ledger with DU state machine and strategy directives
3. Memory integration with cross-session DU persistence
4. Sentinel fact (diagnostic only — tests retrieval, not grounding)

**Dependent variables:** Turn-pair coherence (embedding-based), GQI, acceptance rate, monologic score, directive compliance.

**Current status:**
- Cycle 1 (pilot): Complete. 37 sessions, BF=3.66 (inconclusive). Word overlap metric replaced by embedding-based turn-pair coherence.
- Cycle 2: Implementation complete (Batches 1-4, 76 tests). Pre-registration and OSF registration pending.

See [`research/`](research/) for the research compendium and [`agents/hapax_voice/proofs/`](agents/hapax_voice/proofs/) for theoretical foundations.

## Ecosystem

This research spans six repositories (plus one external dependency):

| Repository | Role | Description |
|-----------|------|-------------|
| **hapax-council** (this repo) | Primary research artifact | 45+ agents, voice daemon, grounding system, experiment infrastructure |
| [hapax-constitution](https://github.com/ryanklee/hapax-constitution) | Governance specification | Axioms, implications, canons. Publishes `hapax-sdlc` package |
| [hapax-officium](https://github.com/ryanklee/hapax-officium) | Supporting software | Management decision support (17 agents) |
| [hapax-watch](https://github.com/ryanklee/hapax-watch) | Research instrument | Wear OS biometric companion (HR, HRV, skin temp) |
| [cockpit-mcp](https://github.com/ryanklee/cockpit-mcp) | Infrastructure | MCP server bridging cockpit APIs to Claude Code (40 tools) |
| [tabbyAPI](https://github.com/theroyallab/tabbyAPI) | Infrastructure (external) | ExllamaV2/V3 LLM inference backend (upstream, not forked) |
| [distro-work](https://github.com/ryanklee/distro-work) | System maintenance | Scripts and configuration |

## Quick Start

```bash
git clone git@github.com:ryanklee/hapax-council.git && cd hapax-council
uv sync
uv run pytest tests/ -q          # 470+ test files
uv run ruff check .               # lint
uv run pyright                    # type check
```

For production use (agents, cockpit API, voice daemon), see [Architecture](#architecture).

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

### Grounding system (research core)

```
Operator utterance
  → Acceptance classifier (ACCEPT/CLARIFY/IGNORE/REJECT)
  → Grounding ledger (DU state: PENDING → GROUNDED/REPAIR/ABANDONED/CONTESTED)
  → Concern-aware repair threshold ("sufficient for current purposes")
  → GQI computation (50% EWMA acceptance + 25% trend + 15% neg penalty + 10% engagement)
  → 2D effort calibration (activation × GQI discount → EFFICIENT/BASELINE/ELABORATIVE)
  → Strategy directive (advance/rephrase/elaborate/present_reasoning/move_on)
  → Injected into VOLATILE band of system prompt
```

### Voice daemon

Wake word → VAD → STT (faster-whisper, GPU) → Salience routing → LLM (via LiteLLM) → Streaming TTS (Kokoro) → Audio output. Phenomenal context renderer injects temporal bands and stimmung, scaled per tier.

### Constitutional governance

Five axioms produce 90 implications via four interpretive canons. Enforced at four tiers (T0 blocked → T3 lint). Novel cases produce precedents with authority hierarchy.

### Consent framework

ConsentLabel (DLM join-semilattice), Labeled[T] (LIO functor), Says monad (Abadi DCC), PosBool(X) provenance semirings, GateToken (linear discipline). Properties verified via Hypothesis.

### Phenomenological perception

Husserlian temporal bands (retention/impression/protention/surprise), Bayesian presence engine (8-signal fusion), apperception cascade (7-step, 6 safeguards), SystemStimmung (6 dimensions).

## Computational Requirements

- **OS:** Linux (tested on CachyOS/Arch)
- **GPU:** NVIDIA RTX 3090 (24GB VRAM) for local inference + GPU effects
- **RAM:** 32GB recommended
- **Docker:** 13 containers (Qdrant, PostgreSQL, LiteLLM, Langfuse, Prometheus, Grafana, etc.)
- **Python:** 3.12+, managed via uv

## Proofs and Evidence

| Claim | Status | Evidence |
|-------|--------|----------|
| ConsentLabel is a join-semilattice | **Proven** | 10 Hypothesis properties |
| Labeled[T] is a functor | **Proven** | 5 Hypothesis properties |
| Says monad laws | **Proven** | 3 laws + functor + authority |
| Provenance semiring laws | **Proven** | 10 Hypothesis properties |
| Perception type system (L0-L9) | **Proven** | 192 matrix tests + 62 Hypothesis |
| Apperception cascade safeguards | **Proven** | 113 tests |
| Grounding ledger DU state machine | **Built** | 76 tests (Batches 1-4) |
| Turn-pair coherence metric | **Built** | Embedding-based, replaces word overlap |
| Conversational grounding (Cycle 1) | **Pilot** | 37 sessions, BF=3.66 (inconclusive) |

## Infrastructure

| Service | Port | Purpose |
|---------|------|---------|
| Cockpit API | :8051 | FastAPI (20+ routes, SSE streaming) |
| LiteLLM | :4000 | LLM gateway → Claude/Gemini/Ollama |
| Qdrant | :6333 | Vector DB (6 collections, 768d nomic-embed) |
| Ollama | :11434 | Local inference (RTX 3090) |
| Langfuse | :3000 | LLM observability |
| PostgreSQL | :5432 | Audit/operational DB |

## Project Structure

```
hapax-council/
├── agents/           45+ agents including hapax_voice
│   └── hapax_voice/  Voice daemon + grounding system + proofs/
├── research/         Research compendium (protocols, data, analysis, results)
├── lab-journal/      Quarto lab journal (GitHub Pages)
├── shared/           83 modules (governance, consent, perception, config)
├── cockpit/          43 modules (FastAPI API, reactive engine)
├── hapax-logos/      Tauri 2 desktop app (wgpu + React)
├── axioms/           5 axioms, 90 implications, precedents, contracts
├── tests/            470+ test files
└── docs/             Research documents, design plans
```

## Citation

If you use this software in your research, please cite it using the [CITATION.cff](CITATION.cff) file.

## License

Apache 2.0 — see [LICENSE](LICENSE).
