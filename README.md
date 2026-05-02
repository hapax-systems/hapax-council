# hapax-council

Externalized executive function infrastructure for a single operator. Research apparatus published as artifact, not a product, not a service, not seeking contributors. Constituent of the Hapax operating environment.

[![CI](https://github.com/ryanklee/hapax-council/actions/workflows/ci.yml/badge.svg)](https://github.com/ryanklee/hapax-council/actions/workflows/ci.yml)

## Project spine

`hapax-council` is the primary runtime of the Hapax operating environment — the single-operator development and research instrument the system itself helps build. The runtime is organized around the following commitments:

- **Single-operator infrastructure**: one operator, one workstation. No auth, no roles, no multi-user code anywhere. Constitutional axiom `single_user`.
- **Externalized executive function**: agents track open loops, maintain context, and surface what needs attention so the operator does not have to.
- **Semantic recruitment**: perception, expression, recall, action, communication, and regulation are recruited through a single `AffordancePipeline`, not statically wired.
- **Perceptual + temporal grounding**: Husserlian temporal bands, Bayesian presence fusion, apperception cascade, and a no-false-grounding discipline gating every public claim.
- **Livestream as primary research instrument**: the studio compositor, ward family, and broadcast-substrate decisions treat the public livestream as the load-bearing surface for the work.
- **Refusal as data**: declined surfaces are preserved as first-class artifacts (Refusal Brief, refusal annexes) rather than removed from the record.
- **Value-braid loop**: runtime evidence flows into deposits, citation graph, support rails, grants, and posteriors via the publication-bus surface registry.

Conversational grounding (Clark & Brennan 1991), the Single Case Experimental Design (SCED) Cycle 1 pilot, and the voice daemon stay present as **research evidence**, not as the whole identity of the project.

## Status disclosure

| Surface | Posture |
|---|---|
| Code release | Source-available archive at this repository. Not seeking contributors; pull requests, issues, and discussions are not accepted (see [`CONTRIBUTING.md`](CONTRIBUTING.md) and [`NOTICE.md`](NOTICE.md)). |
| Empirical claims | Research compendium under [`research/`](research/). Cycle 1 pilot complete (37 sessions, BF=3.66, inconclusive); Cycle 2 implementation complete, pre-registration pending. |
| Governance | Five constitutional axioms enforced via [`hapax-constitution`](https://github.com/ryanklee/hapax-constitution) and the local [`axioms/`](axioms/) registry. |
| License authority | [`NOTICE.md`](NOTICE.md), [`CITATION.cff`](CITATION.cff), and [`codemeta.json`](codemeta.json) are the canonical license statement. The [`LICENSE`](LICENSE) file is currently in transition; the reconciliation status is tracked at [`docs/governance/license-reconciliation-status.md`](docs/governance/license-reconciliation-status.md). |

## Ecosystem

This research spans six repositories (plus one external dependency):

| Repository | Role |
|-----------|------|
| **hapax-council** (this repo) | Primary runtime + research artifact |
| [hapax-constitution](https://github.com/ryanklee/hapax-constitution) | Governance specification (axioms, implications, canons; publishes `hapax-sdlc` package) |
| [hapax-officium](https://github.com/ryanklee/hapax-officium) | Management decision support |
| [hapax-watch](https://github.com/ryanklee/hapax-watch) | Wear OS biometric companion |
| [hapax-mcp](https://github.com/ryanklee/hapax-mcp) | MCP server bridging Logos APIs to Claude Code |
| [tabbyAPI](https://github.com/theroyallab/tabbyAPI) | LLM inference backend (upstream, not forked) |
| [distro-work](https://github.com/ryanklee/distro-work) | System maintenance scripts |

## Architecture

Three independent loops communicate through the filesystem and `/dev/shm`:

```
Loop 1 — Perception (voice daemon, 2.5s tick)
  Sensors → Bayesian presence → Governor → Consent → perception-state.json

Loop 2 — Visual aggregator (3s tick, adaptive 0.5–5s)
  Perception → Stimmung → Temporal bands → Apperception → /dev/shm

Loop 3 — Reactive engine (inotify, event-driven)
  profiles/ + axioms/ → Rule evaluation → Phased execution
```

### Studio + ward family

A GStreamer compositor reads camera and audio inputs, composites them with shader effects and overlays, and writes a single livestream output. Activity-reveal wards (DURF coding-session reveal, M8 instrument reveal, Polyend variant, Steam Deck variant) inherit from `ActivityRevealMixin` for visibility-ceiling enforcement, claim contracts, and HARDM hooks. See [`agents/studio_compositor/`](agents/studio_compositor/) and [`hapax-research/specs/`](hapax-research/specs/) (private) for the family unification spec.

### Affordance pipeline

Impingement → narrative embedding → cosine similarity against the affordance registry → score → governance veto → recruited capabilities activate. Tools, content, voice, and visual surfaces are all recruited through the same pipeline. See [`shared/affordance_registry.py`](shared/affordance_registry.py) and [`docs/superpowers/specs/2026-04-02-unified-semantic-recruitment-design.md`](docs/superpowers/specs/2026-04-02-unified-semantic-recruitment-design.md).

### Voice daemon

Wake word → VAD → STT (faster-whisper, GPU) → salience routing → LLM (via LiteLLM) → streaming TTS (Kokoro) → audio output.

### Constitutional governance

Five axioms (`single_user`, `executive_function`, `corporate_boundary`, `interpersonal_transparency`, `management_governance`) produce ~90 implications via four interpretive canons. Enforced at four tiers (T0 blocked → T3 lint). Novel cases produce precedents.

### Phenomenological perception

Husserlian temporal bands (retention/impression/protention/surprise), 8-signal Bayesian presence engine, 7-step apperception cascade with Qdrant persistence (768-dim cosine), six-dimension SystemStimmung.

## Quick start

```bash
git clone git@github.com:ryanklee/hapax-council.git && cd hapax-council
uv sync
uv run pytest tests/ -q                                    # unit tests
uv run ruff check .                                        # lint
uv run --no-project --with pyrefly==0.62.0 pyrefly check   # CI typecheck (fast path)
uv run pyright                                             # weekly typecheck safety net
```

For production deployment (agents, Logos API, voice daemon, studio compositor), the build chain runs through `pnpm tauri dev` for the desktop surface and systemd user units for daemons; see [`systemd/README.md`](systemd/README.md).

## Computational requirements

- **OS**: Linux (developed on CachyOS / Arch).
- **GPU**: NVIDIA RTX 3090 (24GB VRAM) for local inference + GPU effects; secondary RTX 5060 Ti for embedding routes.
- **RAM**: 32GB recommended.
- **Docker**: 13 containers (LiteLLM, Qdrant, PostgreSQL, Langfuse, Prometheus, Grafana, etc.).
- **Python**: 3.12+, managed via `uv`.

## Citation

Cite via [`CITATION.cff`](CITATION.cff). The Zenodo concept-DOI is in [`.zenodo.json`](.zenodo.json) when published; consult [`NOTICE.md`](NOTICE.md) for the authorship-indeterminacy stance per the Hapax Manifesto.

## Refusal and governance surfaces

- [`NOTICE.md`](NOTICE.md) — canonical project posture, license statement, linked artifacts.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — refusal of contributions (single-operator axiom).
- [`docs/governance/`](docs/governance/) — governance status documents and refusal records.
- [Refusal Brief](https://hapax.weblog.lol/refusal-brief) — public refusal-as-data artifact.
- [Hapax Manifesto v0](https://hapax.weblog.lol/hapax-manifesto-v0) — authorship-indeterminacy + research-as-artifact stance.

---

This README is the public entry point. It does not authorize public claims about live system health, monetization readiness, public artifact release, or empirical validation; those flow through [`agents/publication_bus/`](agents/publication_bus/) per the world-capability surface registry.
