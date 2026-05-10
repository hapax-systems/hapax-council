# CLAUDE.md

Single-operator externalized executive function. No auth/roles/multi-user. Shared conventions (uv, ruff, testing, git) in workspace `CLAUDE.md`. Sister: [vscode](vscode/CLAUDE.md), [hapax-mcp](https://github.com/ryanklee/hapax-mcp). Governance: `hapax-constitution` → `hapax-sdlc` package; local axioms in `axioms/registry.yaml`. Rotation policy: `docs/superpowers/specs/2026-04-13-claude-md-excellence-design.md`.

## Architecture

Filesystem-as-bus: agents read/write markdown+YAML on disk; inotify reactive engine cascades work. Three tiers: T1 interactive (Tauri, waybar, VS Code), T2 LLM agents (pydantic-ai via LiteLLM :4000; local Command-R 35B EXL3 on TabbyAPI :5000 `gpu_split=[16,10]`; cloud Claude/Gemini), T3 deterministic (sync/health/maintenance). Docker Compose 13 containers + systemd user units. New units → `systemd/units/` only. Key chain: hapax-secrets → logos-api(:8051) → tabbyapi(:5000) → hapax-daimonion → studio-compositor. Qdrant `operator-patterns` is dead schema — don't add writers.

## Design Language

Authority: `docs/logos-design-language.md`. No hardcoded hex — use CSS vars/Tailwind. Visual PRs MUST include before/after screenshots via `scripts/compositor-frame-capture.sh`.

## Logos API

`:8051`. `uv run logos-api`. Containers: `docker compose up -d`.

## Obsidian Integration

Vault: `~/Documents/Personal/` (kebab-case, PARA). Plugin `obsidian-hapax/` provides context panel. Goal notes: `type: goal` frontmatter. Agents: `obsidian_sync.py` (6h), `vault_context_writer.py` (15min), `vault_canvas_writer.py`, `sprint_tracker.py` (5min).

## Tauri-Only Runtime

Logos = Tauri 2, IPC only (zero `fetch()`). 60+ invoke handlers, SSE bridge, command relay WS on :8052, frame server on :8053. Reverie: `hapax-imagination` systemd service, wgpu shader graphs, 8-pass vocabulary (`noise→rd→color→drift→breath→feedback→content_layer→postprocess`). Params: `uniforms.json` per-node, multiplicative defaults=1.0. 9 expressive dims in GPU uniform buffer. NVIDIA Wayland workaround: `__NV_DISABLE_EXPLICIT_SYNC=1`. Dev: `pnpm tauri dev`.

## Unified Semantic Recruitment

Single `AffordancePipeline` gates everything. Impingement → embed → cosine vs Qdrant `affordances` → score (similarity+base_level+context_boost+thompson×cost_weight) → governance veto → activate. Thompson sampling Beta(2,1) clamped [1,10]. 6 domains (perception/expression/recall/action/communication/regulation). Imagination produces intent not implementation. Consent gate fail-closed on `consent_required` capabilities. Face privacy at egress layer (#129). Spec: `docs/superpowers/specs/2026-04-02-unified-semantic-recruitment-design.md`.

## Studio Compositor

GStreamer pipeline: cameras → cudacompositor → GL shader chain (12 glfeedback slots) → cairooverlay (wards) → v4l2sink(/dev/video42) + HLS. Layout JSON at `config/compositor-layouts/default.json` + `config/layouts/garage-door.json`. Cairo wards render via `CairoSourceRunner` on background threads; `pip_draw_from_layout()` blits post_fx assignments ON TOP of shaders. Camera mode via `/dev/shm/hapax-compositor/layout-mode.txt` (balanced/packed/sierpinski). Key: `compositor.py`, `cairo_source.py`, `fx_chain.py`, `overlay.py`, `layout.py`. Camera resilience: per-camera sub-pipelines, fallback producers, 5-state FSM, WatchdogSec=60s.

## Reverie Vocabulary Integrity

64 WGSL nodes (60 live in `agents/shaders/nodes/`), 30 presets, glfeedback Rust plugin. 8 always-on vocab nodes + 52 satellite-recruitable. Full affordance coverage (60/60 registered). Satellites MUST use `sat_` prefix. Two GPU bridge paths: shared 9-dim uniforms + per-node params_buffer. Regression pin: `tests/test_wgsl_node_affordance_coverage.py`.

## Audio Routing — PROTECTED INVARIANTS

**MANDATORY.** Golden chain: `TTS → voice-fx → loudnorm → MPC(AUX2/3) → L-12[analog] → L-12 USB return → livestream-tap → broadcast-master → broadcast-normalized → obs-broadcast-remap → OBS`. Run `scripts/hapax-audio-routing-check` before/after ANY audio change. REVERT on failure. NEVER bypass MPC/L-12. NEVER target `hapax-livestream-tap` playback from unauthorized sources. NEVER modify `~/.config/pipewire/pipewire.conf.d/` without approval.

## CC Task Tracking

SSOT: `~/Documents/Personal/20-projects/hapax-cc-tasks/`. Commands: `cc-claim <id>`, `cc-close <id> [--pr N]`. Hook `cc-task-gate.sh` auto-transitions claimed→in_progress. SessionStart shows claimed task + top 5 WSJF.

Multi-session stacks: Claude (`hapax-claude-<role>`, `scripts/hapax-claude`), Codex (`hapax-codex-cx-<color>`, `scripts/hapax-codex`), Gemini (`hapax-gemini-<role>`, `scripts/hapax-gemini`), Antigrav (`hapax-antigrav`, `~/.local/bin/hapax-antigrav`), Vibe (`hapax-vibe-vbe-N`, `~/.local/bin/hapax-vibe`). All use tmux control plane + relay YAML + `--require-ack` sends. Spawn pattern: `hapax-claude --terminal tmux --role X` then `sleep 8` then `hapax-claude-send --session X -- "task"`. RTE role: 270s tick, PR drain, branch hygiene, queue health, never carries workloads. Off-limits for vbe-*/antigrav: `axioms/`, `shared/governance/`, `agents/hapax_daimonion/`, `config/pipewire/`, `CODEOWNERS`, any `CLAUDE.md`.

## Axiom Governance

| Axiom | Weight | Constraint |
|-------|--------|------------|
| single_user | 100 | No auth/roles/collaboration |
| executive_function | 95 | Zero-config, errors include next actions |
| corporate_boundary | 90 | Work data in employer systems only |
| interpersonal_transparency | 88 | No persistent state on non-operator without consent |
| management_governance | 85 | LLMs prepare, humans deliver |

Non-formal referents: "The Operator"/"Oudepode"/"OTO" (sticky per utterance via `shared.operator_referent`).

## V5 Publication Bus

49 surfaces, 3 tiers (FULL_AUTO/CONDITIONAL_ENGAGE/REFUSED). Publisher superclass enforces AllowlistGate + legal-name guard + Prometheus counter. SWH attribution pipeline. Cold-contact: citation-graph-only, ≤5/deposit, ≤3/year/candidate.

## Key Modules

`shared/config.py` (model aliases, LiteLLM/Qdrant), `shared/working_mode.py`, `shared/notify.py` (ntfy), `shared/frontmatter.py` (canonical parser), `shared/dimensions.py` (11 dims), `shared/governance/consent.py`, `shared/agent_registry.py`, `shared/telemetry.py` (hapax_span ExitStack pattern — don't refactor).

## IR Perception

5 Pi fleet: Pi-1(.78) ir-desk, Pi-2(.52) ir-room, Pi-4(.53) sentinel, Pi-5(.72) rag-edge, Pi-6(.74) sync+ir-overhead. YOLOv8n ONNX, 3s cadence. Fusion: any() for person, desk-prefer for gaze, overhead-prefer for hands.

## Hooks

| Hook | Blocks |
|------|--------|
| work-resolution-gate | Edit/Write on feature branch without PR |
| no-stale-branches | Branch creation with unmerged branches; max 20 worktrees |
| push-gate | Push without tests |
| pii-guard | PII patterns |
| attribution-entity-check | Product-company misattributions in publication-adjacent files (registry: `config/publication-hardening/known-entities.yaml`) |

## Voice & Research

Voice FX: PipeWire filter-chain presets at `config/pipewire/voice-fx-*.conf`. Research state: `agents/hapax_daimonion/proofs/RESEARCH-STATE.md`. Composition ladder: 10 layers, 7-dim matrix, gate on N-1 complete.
