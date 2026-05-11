# hapax-council

Single-operator runtime of the Hapax operating environment. Constituent of the Hapax operating environment. Not a product, not a service, not seeking contributors.

[![CI](https://github.com/ryanklee/hapax-council/actions/workflows/ci.yml/badge.svg)](https://github.com/ryanklee/hapax-council/actions/workflows/ci.yml)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20113515.svg)](https://doi.org/10.5281/zenodo.20113515)
[![Sponsor Hapax research](https://img.shields.io/badge/Sponsor-Hapax%20research-ea4aaa?logo=githubsponsors&logoColor=white)](https://github.com/sponsors/hapax-systems)

> **Reviewer / AI-safety orientation:** start with
> [`START_HERE.md`](START_HERE.md). It gives the short dossier for this
> repository as an empirical grounding, refusal, agentic-oversight, and
> public-egress safety artifact.

## Project spine

Single-operator infrastructure, externalized executive function, semantic recruitment, conversational grounding research, the 24/7 livestream as instrument, and refusal as data are the first-screen frame for this repository.

## Project posture

| Surface | State |
|---|---|
| Code release | Source-available archive at this repository. External patches, issues, and discussions are not accepted (see [`CONTRIBUTING.md`](CONTRIBUTING.md), [`NOTICE.md`](NOTICE.md)). |
| Empirical claims | Research compendium under [`research/`](research/) and [`docs/research/`](docs/research/). Cycle 1 SCED pilot complete (37 sessions, BF=3.66, inconclusive). Cycle 2 implementation complete; pre-registration pending. |
| Governance | 5 constitutional axioms enforced via [hapax-constitution](https://github.com/ryanklee/hapax-constitution) and [`axioms/`](axioms/). |
| License authority | [`NOTICE.md`](NOTICE.md), [`CITATION.cff`](CITATION.cff), [`codemeta.json`](codemeta.json) are canonical. The `LICENSE` file is in transition; reconciliation status at [`docs/governance/license-reconciliation-status.md`](docs/governance/license-reconciliation-status.md). |
| Authorship | Indeterminate by design: co-produced by Hapax (the system), Claude Code, and the operator (Oudepode). See [Hapax Manifesto v0](https://hapax.weblog.lol/hapax-manifesto-v0). |

## What this is

`hapax-council` is the primary runtime of the workspace. The runtime is organized around the following commitments, each defined as constitutional or domain axioms:

- **Single-operator infrastructure.** One operator, one workstation. No auth, no roles, no multi-user code (axiom `single_user`, weight 100).
- **Externalized executive function.** Agents track open loops, maintain context, surface what needs attention (axiom `executive_function`, weight 95).
- **Semantic recruitment.** Perception, expression, recall, action, communication, and regulation are recruited through one `AffordancePipeline` (`shared/affordance_pipeline.py`), not statically wired.
- **Conversational grounding research.** Implementation of Clark & Brennan (1991) grounding theory, evaluated via Single Case Experimental Design with Bayesian analysis (`agents/hapax_daimonion/proofs/`).
- **Refusal as data.** Declined surfaces preserved as first-class artifacts (`agents/publication_bus/`, [Refusal Brief](https://hapax.weblog.lol/refusal-brief)).

## Ecosystem

| Repository | Role |
|-----------|------|
| **hapax-council** (this repo) | Primary runtime + research artifact |
| [hapax-constitution](https://github.com/ryanklee/hapax-constitution) | Governance specification (axioms, implications, canons; publishes `hapax-sdlc`) |
| [hapax-officium](https://github.com/ryanklee/hapax-officium) | Management decision support |
| [hapax-watch](https://github.com/ryanklee/hapax-watch) | Wear OS biometric companion |
| [hapax-phone](https://github.com/ryanklee/hapax-phone) | Android health + context companion |
| [hapax-mcp](https://github.com/ryanklee/hapax-mcp) | MCP server bridging the logos APIs to Claude Code |
| [tabbyAPI](https://github.com/theroyallab/tabbyAPI) | LLM inference backend (upstream, not forked) |

## Architecture

### Three tiers

| Tier | Surface | Examples |
|------|---------|----------|
| 1 — interactive | Operator-facing | hapax-logos Tauri app, waybar GTK4 status bar, VS Code extensions, hapax-mcp |
| 2 — LLM agents | pydantic-ai via LiteLLM `:4000` | management agents, voice daemon, director, demo pipeline |
| 3 — deterministic | systemd timers | sync agents, health monitor, drift detector, datacite mirror |

### Three loops

```
Loop 1 — Voice daemon (2.5 s tick)
  Sensors → Bayesian presence → governor → consent → perception-state.json

Loop 2 — Visual aggregator (3 s tick, adaptive 0.5–5 s)
  Perception → Stimmung → temporal bands → apperception → /dev/shm

Loop 3 — Reactive engine (inotify, event-driven)
  profiles/ + axioms/ → rule evaluation → phased execution
```

### Affordance pipeline

`shared/affordance_pipeline.py`. Impingement → narrative embedding → cosine similarity against the Qdrant `affordances` collection → score `(0.50×similarity + 0.20×base_level + 0.10×context_boost + 0.20×thompson + w_recency×recency_distance − exact_recency_penalty) × cost_weight` → governance veto → recruited capabilities activate. Six domains: perception, expression, recall, action, communication, regulation. Spec: [`docs/superpowers/specs/2026-04-02-unified-semantic-recruitment-design.md`](docs/superpowers/specs/2026-04-02-unified-semantic-recruitment-design.md).

### Voice daemon (`agents/hapax_daimonion/`)

Wake word → VAD (Silero) → STT (faster-whisper, GPU) → salience routing → LLM (via LiteLLM) → streaming TTS (Kokoro 82 M, CPU) → audio output. Cortado MKIII contact mic (XLR on the L-12 mixer) and the Pi NoIR fleet feed the Bayesian presence engine. The TTS path runs through an optional PipeWire `filter-chain` (presets in `config/pipewire/voice-fx-*.conf`) and `hapax-loudnorm-capture` before the L-12 → Evil Pet → broadcast chain.

The daimonion spawns two impingement consumers reading `/dev/shm/hapax-dmn/impingements.jsonl`: a CPAL loop (gain/error modulation, spontaneous speech) and an affordance loop (notification, studio, world-domain Thompson recording, capability discovery). Separate cursor files prevent cross-consumer drift.

### Phenomenological perception

Husserlian temporal bands (retention/impression/protention/surprise), 8-signal Bayesian presence engine (`agents/hapax_daimonion/presence_engine.py`), 7-step apperception cascade with Qdrant persistence (`hapax-apperceptions` collection, 768-dim cosine), six-dimension `SystemStimmung`.

### Studio compositor (`agents/studio_compositor/`)

GStreamer pipeline. USB cameras → 1920×1080 composite → GL shader chain → Cairo overlays (Sierpinski with YouTube frames, token pole, album cover, content zones) → V4L2 sink at `/dev/video42` (OBS source) plus HLS playlist. Typed `Source` / `Surface` / `Assignment` / `Layout` model in `shared/compositor_model.py`. `CairoSourceRunner` runs all Cairo content on background threads; cairooverlay blits cached surfaces synchronously. Per-frame budget enforcement publishes a degraded signal when exceeded.

Camera 24/7 resilience: per-camera sub-pipelines with paired fallback producers, `interpipesrc.listen-to` hot-swap, 5-state recovery FSM with exponential backoff, pyudev monitoring, Prometheus metrics on `127.0.0.1:9482`. Native GStreamer RTMP output via `rtmp_output.py` (NVENC `p4` low-latency) to the MediaMTX relay on `127.0.0.1:1935`.

### Reverie (`hapax-logos/src-imagination/`)

Standalone Rust binary `hapax-imagination` runs as a systemd user service. Renders dynamic shader graphs via `wgpu`. Python compiles effect presets (`agents/effect_graph/wgsl_compiler.py`) into WGSL execution plans hot-reloaded from `/dev/shm/hapax-imagination/pipeline/`. Permanent vocabulary graph (8 passes): `noise → rd → color → drift → breath → feedback → content_layer → postprocess`. `agents/shaders/nodes/` contains 60 WGSL files; 60/60 are registered as affordances in `shared.affordance_registry.SHADER_NODE_AFFORDANCES`. 30 effect-graph presets in `presets/`.

Nine expressive dimensions are exposed in the GPU uniform buffer: `intensity`, `tension`, `depth`, `coherence`, `spectral_color`, `temporal_distortion`, `degradation`, `pitch_displacement`, `diffusion`. Frames are written to `/dev/shm/hapax-visual/frame.jpg` via turbojpeg and served at 10 fps over HTTP from the Tauri app on `:8053`.

### IR perception (Pi NoIR fleet)

Three Raspberry Pi 4 + Pi Camera Module 3 NoIR units run `hapax-ir-edge`: YOLOv8n (ONNX Runtime) person detection + NIR hand thresholding + adaptive screen detection.

| Pi | IP | Role |
|----|----|------|
| Pi-1 | 192.168.68.78 | ir-desk (co-located with C920-desk) |
| Pi-2 | 192.168.68.52 | ir-room (co-located with C920-room) |
| Pi-4 | 192.168.68.53 | sentinel (health monitor, watch backup) |
| Pi-5 | 192.168.68.72 | rag-edge (document preprocessing) |
| Pi-6 | 192.168.68.74 | sync-hub + ir-overhead (co-located with C920-overhead) |

Pi daemons POST `/api/pi/{role}/ir` with structured JSON every ~3 s; heartbeats every 60 s. `agents/hapax_daimonion/backends/ir_presence.py` performs multi-Pi fusion.

### Qdrant collections (`shared/qdrant_schema.py`)

| Collection | Purpose |
|------------|---------|
| `profile-facts` | Behavioral facts; SSOT for operator context |
| `documents` | RAG corpus |
| `axiom-precedents` | Governance cases |
| `operator-episodes` | Multi-session narratives |
| `studio-moments` | Compositional snapshots |
| `operator-corrections` | Manual corrections |
| `affordances` | Recruitment registry (6 domains) |
| `stream-reactions` | Livestream audience signals |
| `hapax-apperceptions` | Perception snapshots (Husserlian bands) |
| `operator-patterns` | Pending retire (zero upsert callers as of 2026-05-02 24h auditor finding #11) |

### Constitutional governance

5 axioms produce ~90 implications via 4 interpretive canons (textualist, purposivist, absurdity, omitted-case). Enforcement at 4 tiers: T0 (block at commit), T1 (review), T2 (warn), T3 (lint).

| Axiom | Weight | Constraint |
|-------|--------|-----------|
| `single_user` | 100 | One operator. No auth, no roles. |
| `executive_function` | 95 | Zero-config agents, errors include next actions, routine work automated. |
| `corporate_boundary` | 90 | Work data stays in employer systems. |
| `interpersonal_transparency` | 88 | No persistent state about non-operator persons without active consent contract. |
| `management_governance` | 85 | LLMs prepare context; humans deliver words. |

Definitions in `axioms/registry.yaml`; implications in `axioms/implications/`; consent contracts in `axioms/contracts/`. Face-obscure (SCRFD + Kalman bbox, Gruvbox-dark pixelation, fail-CLOSED on detector exception) runs per camera before any RTMP/HLS/V4L2 tee at `agents/studio_compositor/face_obscure_integration.py`.

### Publication bus (`agents/publication_bus/`)

17-surface registry across three tiers (`FULL_AUTO`, `CONDITIONAL_ENGAGE`, `REFUSED`). Concrete publishers: Bridgy webmention, omg.lol weblog, Internet Archive (S3), Bluesky (atproto), OSF preregistration, PhilArchive, Zenodo refusal-deposit, refusal-annex local writer. SWH attribution daemon (`agents/attribution/`) and DataCite citation-graph mirror (`agents/publication_bus/datacite_mirror.py`) populate the citation network around operator-authored DOIs.

## Ports

| Port | Service | Process |
|------|---------|---------|
| 8051 | Logos FastAPI | systemd `logos-api.service` |
| 8052 | Tauri WebSocket relay (MCP, voice command dispatch) | hapax-logos process |
| 8053 | Visual frame server (Axum, JPEG @ 10 fps) | hapax-logos process |
| 8042 | Watch receiver (Wear OS + phone sensor ingest) | systemd `hapax-watch-recv.service` |
| 5000 | TabbyAPI (Command-R 35B EXL3 5.0bpw) | systemd `tabbyapi.service` |
| 4000 | LiteLLM gateway | docker `litellm` |
| 3000 | Langfuse | docker `langfuse` |
| 6333 / 6334 | Qdrant (HTTP / gRPC) | docker `qdrant` |
| 5432 | Postgres (LiteLLM, Langfuse, n8n) | docker `postgres` |
| 6379 | Redis | docker `redis` |
| 8123 / 9000 | ClickHouse (HTTP / native, Langfuse traces) | docker `clickhouse` |
| 9001 / 9002 | MinIO (data / console, Langfuse blob store) | docker `minio` |
| 9090 | Prometheus | docker `prometheus` |
| 3001 | Grafana | docker `grafana` |
| 5678 | n8n | docker `n8n` |
| 8080 | Open WebUI | docker `open-webui` |
| 8090 | ntfy | docker `ntfy` |
| 9482 | Studio compositor metrics | studio-compositor process |
| 1935 | MediaMTX RTMP relay | systemd |

## Inter-repo wiring

| Caller | Endpoint | Implementation |
|--------|----------|---------------|
| hapax-watch (sensor batch, every 30 s) | `POST :8042/...` | `agents/watch_receiver.py` |
| hapax-watch (tile poll, every 60 s) | `GET :8051/api/awareness/watch-summary` | `logos/api/routes/awareness.py` |
| hapax-phone (`HealthSummaryPayload`, daily) | `POST :8042/phone/health-summary` | `agents/watch_receiver.py` |
| hapax-phone (`PhoneContextPayload`, every 60 s) | `POST :8042/phone/context` | `agents/watch_receiver.py` |
| hapax-phone (awareness consumption, every 60 s) | `GET :8051/api/awareness` | `logos/api/routes/awareness.py` |
| hapax-mcp (38 tools) | `:8051/api/*` | various route modules |
| hapax-logos (Tauri IPC) | proxy to `:8051/api/*` internally | `hapax-logos/src-tauri/` |
| Pi NoIR fleet (every ~3 s) | `POST :8042/api/pi/{role}/ir` | `agents/watch_receiver.py` |

## Quick start

```bash
git clone git@github.com:ryanklee/hapax-council.git && cd hapax-council
direnv allow                                                 # load .envrc (pass-backed secrets)
uv sync --all-extras                                         # core + audio + sync-pipeline + logos-api
uv run pytest tests/ -q                                      # tests
uv run ruff check . && uv run ruff format --check .          # lint
uv run --no-project --with pyrefly==0.62.0 pyrefly check     # CI typecheck (fast)
uv run pyright                                               # weekly typecheck safety net
```

Infrastructure containers (LiteLLM, Qdrant, Postgres, Langfuse, Prometheus, Grafana, etc.) live under `~/llm-stack/`. Application services live under `systemd/units/` (canonical path; the deploy script matches `*.service`/`*.timer` here only). After cloning:

```bash
cd ~/llm-stack && docker compose --profile full up -d
cd ~/projects/hapax-council
systemd/scripts/install-units.sh
systemctl --user daemon-reload
systemctl --user enable --now hapax.target
systemctl --user enable --now hapax-visual-stack.target
systemctl --user enable --now hapax-post-merge-deploy.path
```

## Dev surface

```bash
cd hapax-logos && pnpm tauri dev          # Tauri 2 (Vite serves Tauri webview only; no exposed proxy)
uv run logos-api                          # FastAPI on :8051
uv run agents.hapax_daimonion.main        # Voice daemon
journalctl --user -f                      # Live user-service logs
journalctl --user -u hapax-daimonion.service -n 50
```

`pnpm tauri build` produces a native binary at `~/.local/bin/hapax-logos`. NVIDIA + Wayland requires `__NV_DISABLE_EXPLICIT_SYNC=1` (set in the systemd unit and `.envrc`) per [`docs/issues/tauri-wayland-protocol-error.md`](docs/issues/tauri-wayland-protocol-error.md).

`scripts/rebuild-services.sh` and `scripts/rebuild-logos.sh` operate in an isolated scratch worktree at `$HOME/.cache/hapax/rebuild/worktree`; the operator's interactive checkout is never a deploy target. `hapax-rebuild-services.timer` (5 min) and `hapax-post-merge-deploy.path` cascade restarts when `origin/main` advances.

## Working mode

Workspace-shared mode file at `~/.cache/hapax/working-mode` (`research`/`rnd`/`fortress`). CLI: `hapax-working-mode`. Officium reads the same file but accepts only `research`/`rnd`. Logos API exposes `GET/PUT /api/working-mode`.

## Computational requirements

- Linux (developed on CachyOS / Arch).
- Dual NVIDIA: RTX 3090 (24 GB) for TabbyAPI on GPU 0, RTX 5060 Ti (16 GB) for Ollama on GPU 1. GPU pinning enforced via `/etc/systemd/system/ollama.service.d/z-gpu-5060ti.conf` (`CUDA_VISIBLE_DEVICES=1`).
- 32 GB RAM.
- 13 Docker containers under `~/llm-stack/`.
- Python 3.12+ via `uv`. Node ≥18 with `pnpm`.
- `pass` + `direnv` for secrets.

## CC-task tracking

Canonical work-state surface in the operator's Obsidian vault at `~/Documents/Personal/20-projects/hapax-cc-tasks/`. One markdown note per task with `type: cc-task` frontmatter. `cc-claim <task_id>` claims a task atomically (rewrites frontmatter and writes the per-role claim file at `~/.cache/hapax/cc-active-task-{role}`). The native `TaskTool` is permitted only for single-session ephemeral todos; cross-session items go to the vault.

Spec: [`docs/superpowers/specs/2026-04-20-cc-task-obsidian-ssot-design.md`](docs/superpowers/specs/2026-04-20-cc-task-obsidian-ssot-design.md).

## Refusal and governance surfaces

- [`NOTICE.md`](NOTICE.md) — canonical project posture, license statement, linked artifacts.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — refusal of contributions (`single_user` axiom).
- [`docs/governance/`](docs/governance/) — governance status documents and refusal records.
- [Refusal Brief](https://hapax.weblog.lol/refusal-brief) — public refusal-as-data artifact.
- [Hapax Manifesto v0](https://hapax.weblog.lol/hapax-manifesto-v0) — authorship-indeterminacy + research-as-artifact stance.

## Citation

Cite via [`CITATION.cff`](CITATION.cff). Zenodo concept-DOI in [`.zenodo.json`](.zenodo.json) when published.

---

This README is the public entry point. Public claims about live system health, monetization readiness, public artifact release, or empirical validation flow through [`agents/publication_bus/`](agents/publication_bus/) per the world-capability surface registry.
