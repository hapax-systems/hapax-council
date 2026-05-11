# hapax-council

Single-operator cognitive infrastructure: 180+ agent modules, 330+ systemd unit files, constitutional governance with algebraic proofs, multi-lane AI coordination, multimodal perception, and a studio compositor/livestream research instrument - running on one workstation for one person.

[![CI](https://github.com/hapax-systems/hapax-council/actions/workflows/ci.yml/badge.svg)](https://github.com/hapax-systems/hapax-council/actions/workflows/ci.yml)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20113515.svg)](https://doi.org/10.5281/zenodo.20113515)

> **Reviewer / AI-safety orientation:** start with
> [`START_HERE.md`](START_HERE.md) — the short dossier for this repository
> as an empirical grounding, refusal, agentic-oversight, and public-egress
> safety artifact.

## Project spine

Single-operator operating environment, externalized executive function, semantic recruitment across perception/expression/recall/action, temporal and perceptual grounding discipline, studio/livestream research instrument, refusal-as-data substrate, and value-braid loop from runtime truth to artifacts, support, grants, and posteriors.

## What this is

An operating environment that externalizes executive function for a neurodivergent solo operator. Not a product, not a service, not seeking contributors — research infrastructure published as artifact.

The system perceives (cameras, microphones, biometrics, IR fleet), reasons (180+ agent modules via LLM and deterministic pipelines), acts (voice, visuals, compositor, publication), and governs itself (5 constitutional axioms with algebraic enforcement). Everything runs locally on a single workstation.

### Core commitments

- **Single-operator.** No auth, no roles, no multi-user code. Constitutional axiom, weight 100.
- **Externalized executive function.** ADHD + autism accommodation is the design constraint. Agents track open loops, maintain context, surface what needs attention, automate routine work.
- **Constitutional governance.** 5 axioms produce ~90 implications via 4 interpretive canons. Consent contracts govern non-operator person data. The governance algebra is verified by Hypothesis: join-semilattice, non-amplification, provenance semirings, deny-wins composition. Extracted as the standalone [`agentgov`](packages/agentgov/) package.
- **Semantic recruitment.** One `AffordancePipeline` gates everything across 6 domains (perception, expression, recall, action, communication, regulation). Thompson sampling, cosine similarity against a Qdrant affordance collection, governance veto.
- **Refusal as data.** Declined surfaces are first-class artifacts. The publication bus enforces a 3-tier allowlist (`FULL_AUTO` / `CONDITIONAL_ENGAGE` / `REFUSED`).

## Architecture

```
                    ┌────────────────────────────────────────────┐
                    │          Operator (single user)            │
                    └──────────┬──────────────┬─────────────────┘
                               │              │
                    ┌──────────▼──────┐  ┌────▼────────────────┐
                    │  Logos app      │  │  Voice daemon        │
                    │  (Tauri 2/wgpu) │  │  (STT→LLM→TTS)      │
                    └──────────┬──────┘  └────┬────────────────┘
                               │              │
              ┌────────────────▼──────────────▼──────────────────┐
              │              Logos API (:8051)                    │
              │              + MCP bridge                         │
              └────────────────┬─────────────────────────────────┘
                               │
         ┌─────────────────────┼──────────────────────┐
         │                     │                      │
    ┌────▼─────┐      ┌───────▼───────┐      ┌───────▼────────┐
    │ 180      │      │ Reactive      │      │ Studio         │
    │ agents   │      │ engine        │      │ compositor     │
    │          │      │ (inotify)     │      │ (GStreamer+GL) │
    └────┬─────┘      └───────┬───────┘      └───────┬────────┘
         │                    │                      │
    ┌────▼────────────────────▼──────────────────────▼────────┐
    │  Infrastructure: LiteLLM, Qdrant, Langfuse, Prometheus, │
    │  TabbyAPI (Command-R 35B), Docker x13, systemd 330+     │
    └─────────────────────────────────────────────────────────┘
```

### Three tiers

| Tier | Surface | Examples |
|------|---------|----------|
| Interactive | Operator-facing | Logos Tauri app, waybar, hapax-mcp, watch/phone companions |
| LLM agents | pydantic-ai via LiteLLM | Triage officer, voice daemon, publication bus, content resolver |
| Deterministic | systemd timers | Sync agents, health monitor, drift detector, audio routing checks |

### Multi-lane coordination

Up to 10 concurrent AI sessions (Claude Code, Codex, Gemini CLI) coordinate through a relay protocol at `~/.cache/hapax/relay/`. Each session operates in its own git worktree. A triage officer daemon annotates incoming tasks with priority, effort class, and platform suitability. Dispatch policies enforce permission tiers, quota partitioning, and capability matching.

### Multimodal perception

- **Voice:** Wake word → VAD → STT (faster-whisper, GPU) → salience routing → LLM → streaming TTS (Kokoro 82M, CPU) → PipeWire voice FX → mixer → broadcast chain
- **Vision:** 3 USB cameras → GStreamer compositor → GL shader chain → Cairo overlays → V4L2 + HLS. Per-camera sub-pipelines with 5-state recovery FSM
- **IR fleet:** 5 Raspberry Pi units running YOLOv8n person detection + NIR hand thresholding. Multi-Pi fusion at 3s cadence
- **Biometrics:** Wear OS watch (heart rate, HRV, skin temperature, sleep) + Android phone (daily health summaries, 60s context updates)
- **Visual expression:** `hapax-imagination` — Rust/wgpu shader graphs with 60 WGSL nodes, 30 presets, 9 expressive dimensions in GPU uniform buffer

### Constitutional governance

5 axioms, algebraically verified:

| Axiom | Weight | Constraint |
|-------|--------|-----------|
| `single_user` | 100 | One operator. No auth, no roles. |
| `executive_function` | 95 | Zero-config, errors include next actions, routine automated. |
| `corporate_boundary` | 90 | Work data stays in employer systems. |
| `interpersonal_transparency` | 88 | No persistent state about non-operator persons without consent contract. |
| `management_governance` | 85 | LLMs prepare context; humans deliver words. |

Enforcement at 4 tiers: T0 (block at commit), T1 (review), T2 (warn), T3 (lint). Face-obscure runs fail-CLOSED per camera before any egress. The governance core is extracted as [`agentgov`](packages/agentgov/) — a standalone MIT-licensed package with ConsentLabel (DLM join-semilattice), Labeled[T] (LIO-style functor), ProvenanceExpr (PosBool(X) semiring), VetoChain (deny-wins composition), and Says (DCC attribution monad).

## Project posture

| Surface | State |
|---|---|
| Code release | Source-available archive. No external support, feature-request, patch, issue, or discussion intake is accepted (see [`CONTRIBUTING.md`](CONTRIBUTING.md)). |
| Empirical claims | Research compendium under [`research/`](research/). Cycle 1 SCED pilot complete (37 sessions, BF=3.66, inconclusive). Cycle 2 in progress. |
| Governance | 5 constitutional axioms enforced via [hapax-constitution](https://github.com/ryanklee/hapax-constitution) and [`axioms/`](axioms/). |
| License | PolyForm Strict 1.0.0. See [`NOTICE.md`](NOTICE.md), [`CITATION.cff`](CITATION.cff), and [`license-reconciliation-status`](docs/governance/license-reconciliation-status.md). |
| Authorship | Indeterminate by design: co-produced by Hapax (the system), Claude Code, and the operator. See [Hapax Manifesto v0](https://hapax.weblog.lol/hapax-manifesto-v0). |

## Ecosystem

| Repository | Role |
|-----------|------|
| **hapax-council** (this repo) | Primary runtime, 180+ agent modules, 330+ systemd unit files |
| [agentgov](https://github.com/hapax-systems/agentgov) | Extracted governance hooks/package for AI coding agents |
| [hapax-constitution](https://github.com/ryanklee/hapax-constitution) | Governance specification (axioms, implications, canons; publishes `hapax-sdlc`) |
| [hapax-officium](https://github.com/ryanklee/hapax-officium) | Management decision support (`:8050`) |
| [hapax-assets](https://github.com/ryanklee/hapax-assets) | SHA-pinned aesthetic-library CDN |
| hapax-watch | Wear OS biometric companion; private/not a public repo as of 2026-05-11 |
| hapax-phone | Android health + context companion; private/not a public repo as of 2026-05-11 |
| hapax-mcp | MCP server bridging logos APIs to Claude Code; private/not a public repo as of 2026-05-11 |

## Quick start

```bash
git clone git@github.com:hapax-systems/hapax-council.git && cd hapax-council
direnv allow                                             # load .envrc (pass-backed secrets)
uv sync --all-extras                                     # install all dependencies
uv run pytest tests/ -q                                  # test suite
uv run ruff check . && uv run ruff format --check .      # lint
uv run --no-project --with pyrefly==0.62.0 pyrefly check # CI typecheck
uv run pyright                                           # weekly typecheck safety net
```

Infrastructure (LiteLLM, Qdrant, Postgres, Langfuse, Prometheus, Grafana, etc.) via Docker Compose under `~/llm-stack/`. Application services via systemd user units in `systemd/units/`:

```bash
cd ~/llm-stack && docker compose --profile full up -d
systemd/scripts/install-units.sh
systemctl --user daemon-reload && systemctl --user enable --now hapax.target
```

## Refusal and governance surfaces

- [`NOTICE.md`](NOTICE.md) — canonical project posture and license.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — refusal of contributions (`single_user` axiom).
- [`docs/governance/`](docs/governance/) — governance status and refusal records.
- [Refusal Brief](https://hapax.weblog.lol/refusal-brief) — public refusal-as-data artifact.
- [Hapax Manifesto v0](https://hapax.weblog.lol/hapax-manifesto-v0) — authorship-indeterminacy stance.

## Citation

Cite via [`CITATION.cff`](CITATION.cff). Zenodo DOI: [10.5281/zenodo.20113515](https://doi.org/10.5281/zenodo.20113515).

---

This README is the public entry point. Public claims about live system health, monetization readiness, or empirical validation flow through [`agents/publication_bus/`](agents/publication_bus/) per the world-capability surface registry.
