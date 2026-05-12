# hapax-council

[![CI](https://github.com/hapax-systems/hapax-council/actions/workflows/ci.yml/badge.svg)](https://github.com/hapax-systems/hapax-council/actions/workflows/ci.yml)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20113515.svg)](https://doi.org/10.5281/zenodo.20113515)
[![Support Hapax research](https://img.shields.io/badge/Support-Hapax%20research-b8bb26)](https://hapax.omg.lol/support)
[![License: PolyForm Strict](https://img.shields.io/badge/license-PolyForm%20Strict%201.0.0-blue)](LICENSE)
[![Built with Claude Code](https://img.shields.io/badge/built%20with-Claude%20Code-blueviolet)](https://claude.ai/claude-code)

## Project spine

Single-operator operating environment, externalized executive function, semantic recruitment across perception/expression/recall/action, temporal and perceptual grounding discipline, studio/livestream research instrument, refusal-as-data substrate, and value-braid loop from runtime truth to artifacts, support, grants, and posteriors.

**What happens when 200+ total AI agents run 24/7 and can't lie to you -- by design.**

Hapax is a single-operator autonomous system: 200+ total agents, including 180+ runtime agent modules, plus a voice daemon, a GPU visual surface, a studio compositor, and a 24/7 livestream -- all governed by a formal constitution that makes sycophancy, slop, and dishonesty structurally impossible.

This is not a framework. This is not a demo. This is the production system one neurodivergent operator uses to externalize executive function, and the research artifact that proves what happens when you take agent governance seriously.

> [hapax.omg.lol](https://hapax.omg.lol) &#183; [YouTube @LegomenaLive](https://youtube.com/@LegomenaLive) &#183; [START_HERE.md](START_HERE.md) &#183; [Manifesto](https://hapax.weblog.lol/hapax-manifesto-v0) &#183; [Refusal Brief](https://hapax.weblog.lol/refusal-brief)

---

## The problem

Most AI agent systems have no governance. The model might be aligned, but the system around it offers zero structural guarantees about what the agents will say, claim, publish, or refuse. Prompt engineering is behavioral nudging, not governance. Fine-tuning is statistical tendency, not constraint. When the only thing between an agent and a hallucinated claim is a system prompt, you don't have safety -- you have hope.

Hapax takes a different position: **governance is architecture, not policy.** Five constitutional axioms, enforced at commit time, at CI, and at runtime, produce ~90 implications via four interpretive canons. Agents don't choose to be honest. They are structurally incapable of the alternative.

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

### Filesystem-as-bus

Agents read and write Markdown + YAML on disk. An inotify-driven reactive engine cascades work across the system. No message broker. No queue. The filesystem is the bus, and `git log` is the audit trail.

### Multi-lane coordination

Up to 10 concurrent AI sessions (Claude Code, Codex, Gemini CLI) coordinate through a relay protocol at `~/.cache/hapax/relay/`. Each session operates in its own git worktree. A triage officer daemon annotates incoming tasks with priority, effort class, and platform suitability. Dispatch policies enforce permission tiers, quota partitioning, and capability matching.

### Multimodal perception

- **Voice:** Wake word → VAD → STT (faster-whisper, GPU) → salience routing → LLM → streaming TTS (Kokoro 82M, CPU) → PipeWire voice FX → mixer → broadcast chain
- **Vision:** 3 USB cameras → GStreamer compositor → GL shader chain → Cairo overlays → V4L2 + HLS. Per-camera sub-pipelines with 5-state recovery FSM
- **IR fleet:** 5 Raspberry Pi units running YOLOv8n person detection + NIR hand thresholding. Multi-Pi fusion at 3s cadence
- **Biometrics:** Wear OS watch (heart rate, HRV, skin temperature, sleep) + Android phone (daily health summaries, 60s context updates)
- **Visual expression:** `hapax-imagination` — Rust/wgpu shader graphs with 60 WGSL nodes, 30 presets, 9 expressive dimensions in GPU uniform buffer

## Constitutional governance

Five axioms govern everything. They are not guidelines. They are enforced at four tiers: T0 blocks at commit, T1 at review, T2 warns, T3 lints.

| Axiom | Weight | Constraint |
|-------|--------|-----------|
| `single_user` | 100 | One operator. No auth, no roles, no multi-user code. Ever. |
| `executive_function` | 95 | Agents track open loops and surface what needs attention. Zero-config. |
| `corporate_boundary` | 90 | Work data stays in employer systems. Hard boundary. |
| `interpersonal_transparency` | 88 | No persistent state about non-operator persons without active consent. |
| `management_governance` | 85 | LLMs prepare context. Humans deliver words. No exceptions. |

### What "constitutionally incapable" means

- **Sycophancy** is structurally impossible because `management_governance` requires that LLMs prepare context for human decisions, never deliver conclusions. An agent that tells the operator what they want to hear has violated a constitutional axiom -- the system rejects this at the architectural level.
- **Slop** is structurally impossible because the publication bus enforces source provenance on every claim that reaches a public surface. Agents cannot publish ungrounded assertions. The refusal system treats declined claims as first-class artifacts, preserved and auditable.
- **Dishonesty about persons** is structurally impossible because `interpersonal_transparency` requires active consent contracts before the system stores anything about a non-operator person. The face privacy system runs fail-closed -- if the detector crashes, all faces are obscured by default.

The governance core is extracted as [`agentgov`](packages/agentgov/) — a standalone MIT-licensed package with ConsentLabel (DLM join-semilattice), Labeled[T] (LIO-style functor), ProvenanceExpr (PosBool(X) semiring), VetoChain (deny-wins composition), and Says (DCC attribution monad). Algebraic properties verified by Hypothesis.

### Refusal as data

When the system declines to publish, claim, or act, that refusal is not discarded. It is preserved as a first-class artifact in the publication bus. The [Refusal Brief](https://hapax.weblog.lol/refusal-brief) explains why this matters.

### Semantic recruitment

One `AffordancePipeline` gates everything across 6 domains (perception, expression, recall, action, communication, regulation). Thompson sampling, cosine similarity against a Qdrant affordance collection, governance veto.

## Project posture

| Surface | State |
|---|---|
| Code release | Source-available archive. No external support, feature-request, patch, issue, or discussion intake is accepted (see [`CONTRIBUTING.md`](CONTRIBUTING.md)). |
| Empirical claims | Research compendium under [`research/`](research/). Cycle 1 SCED pilot complete (37 sessions, BF=3.66, inconclusive). Cycle 2 in progress. |
| Governance | 5 constitutional axioms enforced via [hapax-constitution](https://github.com/ryanklee/hapax-constitution) and [`axioms/`](axioms/). |
| License | PolyForm Strict 1.0.0. See [`NOTICE.md`](NOTICE.md), [`CITATION.cff`](CITATION.cff), and [`license-reconciliation-status`](docs/governance/license-reconciliation-status.md). |
| Authorship | Indeterminate by design: co-produced by Hapax (the system), Claude Code, and the operator. See [Hapax Manifesto v0](https://hapax.weblog.lol/hapax-manifesto-v0). |
| Support / sponsorship | Public support page: [hapax.omg.lol/support](https://hapax.omg.lol/support). The org GitHub Sponsors surface is pending; launch copy routes through the verified no-perk support page and does not claim perks, access, requests, priority, deliverables, or control. |

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

*Not a product. Not a service. Not seeking contributors. [Why not?](https://hapax.weblog.lol/refusal-brief)*
