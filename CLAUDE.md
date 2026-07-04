# CLAUDE.md

Single-operator externalized executive function. No auth/roles/multi-user. Shared conventions (uv, ruff, testing, git) in workspace `CLAUDE.md`. Sister: [vscode](vscode/CLAUDE.md), [hapax-mcp](https://github.com/ryanklee/hapax-mcp). Governance: `hapax-constitution` → `hapax-sdlc` package; local axioms in `axioms/registry.yaml`. Rotation policy: `docs/superpowers/specs/2026-04-13-claude-md-excellence-design.md`.

## Architecture

Filesystem-as-bus: agents read/write markdown+YAML on disk; inotify reactive engine cascades work. Three tiers: T1 interactive (Tauri, waybar, VS Code), T2 LLM agents (pydantic-ai via LiteLLM :4000; local Command-R 35B EXL3 on TabbyAPI :5000 `gpu_split=[30]` on RTX 5090; cloud Claude/Gemini), T3 deterministic (sync/health/maintenance). Docker Compose 13 containers + systemd user units. New units → `systemd/units/` only. Key chain: hapax-secrets → logos-api(:8051) → tabbyapi(:5000) → hapax-daimonion → studio-compositor. Qdrant `operator-patterns` is dead schema — don't add writers.

## Design Language

Authority: `docs/logos-design-language.md`. No hardcoded hex — use CSS vars/Tailwind. Visual PRs MUST include before/after screenshots via `scripts/compositor-frame-capture.sh`.

## Logos API

`:8051`. `uv run logos-api`. Containers: `docker compose up -d`.

## Obsidian Integration

Vault: `~/Documents/Personal/` (kebab-case, PARA). Plugin `obsidian-hapax/` provides context panel. Goal notes: `type: goal` frontmatter. Agents: `obsidian_sync.py` (6h), `vault_context_writer.py` (15min), `vault_canvas_writer.py`, `sprint_tracker.py` (5min).

## Screwm Aggregate Runtime

Only the Logos/Tauri desktop frontend is intentionally sunsetted and disabled.
Do not revive it as the primary runtime. The aggregate target is
Screwm-native: DarkPlaces/Quake spatial rendering plus Hapax compositor, drift,
and effects capabilities re-homed behind governed contracts. Required ports
include audio reactivity, drift/modulation currency, WGSL node graph parity,
Cairo/ward atlas rendering, image/video classification, audio governance:
ducking, LUFS panic, VAD, and consent egress, layout switching and transition
FSM, director/programme control, temporal/glfeedback effects, recording/HLS
egress, and camera resilience. The `hapax-logos` workspace may still contain
shared visual crates, but the Tauri shell is not the live surface.

## Unified Semantic Recruitment

Single `AffordancePipeline` gates everything. Impingement → embed → cosine vs Qdrant `affordances` → score (similarity+base_level+context_boost+thompson×cost_weight) → governance veto → activate. Thompson sampling Beta(2,1) clamped [1,10]. 6 domains (perception/expression/recall/action/communication/regulation). Imagination produces intent not implementation. Consent gate fail-closed on `consent_required` capabilities. Face privacy at egress layer (#129). Spec: `docs/superpowers/specs/2026-04-02-unified-semantic-recruitment-design.md`.

## Studio Compositor

GStreamer pipeline: cameras → cudacompositor → GL shader chain (12 glfeedback slots) → cairooverlay (wards) → v4l2sink(/dev/video42) + HLS. Layout JSON at `config/compositor-layouts/default.json` + `config/layouts/garage-door.json`. Cairo wards render via `CairoSourceRunner` on background threads; `pip_draw_from_layout()` blits post_fx assignments ON TOP of shaders. Camera mode via `/dev/shm/hapax-compositor/layout-mode.txt` (balanced/packed/sierpinski). Key: `compositor.py`, `cairo_source.py`, `fx_chain.py`, `overlay.py`, `layout.py`. Camera resilience: per-camera sub-pipelines, fallback producers, 5-state FSM, WatchdogSec=60s.

## Reverie Vocabulary Integrity

62 WGSL nodes (60 registered in `agents/shaders/nodes/`), 88 presets, glfeedback Rust plugin. 8 always-on vocab nodes + 52 satellite-recruitable. Full affordance coverage (60/60 registered). Satellites MUST use `sat_` prefix. Two GPU bridge paths: shared 9-dim uniforms + per-node params_buffer. Regression pin: `tests/test_wgsl_node_affordance_coverage.py`.

## Audio Routing — PROTECTED INVARIANTS

**MANDATORY.** Full reference: `docs/audio-topology-reference.md` (single source of truth). The **MOTU UltraLite mk5** is the single analog I/O hub (pinned to the pro-audio profile, 48 kHz); Hapax's TTS voice is modulated by the **Torso S-4** via an **analog hardware insert** (dry send out the mk5, processed wet return back in; the S-4 sits in a `Material=Bypass` scene). The legacy **MPC / Behringer L-12 / Evil Pet** hardware-mixer chain is **RETIRED** (decommissioned 2026-05/06) — music/YT/PC/private sources now mix at the PipeWire loudnorm→tap layer, not in hardware. Golden voice chain: `TTS(hapax-daimonion) → voice-fx → loudnorm → mk5 OUT3/4 (dry send) → Torso S-4 [analog insert] → mk5 IN3/4 (wet return) → voice-wet → livestream-tap → broadcast-master → broadcast-normalized → obs-broadcast-remap → OBS`. mk5 channel map: IN1=Rode operator mic (`pro-input-0:capture_AUX0`, never dropped), IN2=Cortado contact mic (AUX1, quarantine/non-broadcast), IN3/4=S-4 wet return (AUX2/3), OUT3/4=dry send to S-4 (AUX2/3), Phones=AUX10/11 (private/operator monitor), Main=AUX0/1 (monitor, not broadcast). Music plays via `hapax-music-player.service` (yt-dlp → pw-cat → hapax-music-loudnorm), NOT a browser. Default sink must NEVER be a physical/broadcast device (mk5/S-4/M8/Yeti/HDMI/BT). Run `scripts/hapax-audio-routing-check` before/after ANY audio change. REVERT on failure. NEVER bypass the S-4 wet path or the mk5 hub. NEVER target `hapax-livestream-tap` playback from unauthorized sources. NEVER modify `~/.config/pipewire/pipewire.conf.d/` without approval.

## CC Task Tracking

SSOT: `~/Documents/Personal/20-projects/hapax-cc-tasks/`. Commands: `cc-claim <id>`, `cc-close <id> [--pr N]`. Hook `cc-task-gate.sh` auto-transitions claimed→in_progress. SessionStart shows claimed task + top 5 WSJF.

Multi-session stacks: Claude (`hapax-claude-<role>`, `scripts/hapax-claude`), Codex (`hapax-codex-cx-<color>`, `scripts/hapax-codex`), Vibe (`hapax-vibe-vbe-N`, `~/.local/bin/hapax-vibe`). Antigrav/agy is deprecated/excised as a live dispatch platform, lane, route family, and supply leaf; do not dispatch `antigrav` lanes or register Antigrav as live capacity. Any future agy/Gemini capability must re-enter as measured supply leaves with route/resource/governance receipts. Legacy `hapax-gemini` lanes are retired; Gemini-family review wrappers are review evidence only, not dispatch supply. Active interactive stacks use tmux control plane + relay YAML + `--require-ack` sends where supported. Spawn pattern: `hapax-claude --terminal tmux --role X` then `sleep 8` then `hapax-claude-send --session X -- "task"`. RTE role: 270s tick, PR drain, branch hygiene, queue health, never carries workloads. Off-limits for vbe-*: `axioms/`, `shared/governance/`, `agents/hapax_daimonion/`, `config/pipewire/`, `CODEOWNERS`, any `CLAUDE.md`.

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

55 surfaces, 3 tiers (FULL_AUTO/CONDITIONAL_ENGAGE/REFUSED). Publisher superclass enforces AllowlistGate + legal-name guard + Prometheus counter. SWH attribution pipeline. Cold-contact: citation-graph-only, ≤5/deposit, ≤3/year/candidate.

## Key Modules

`shared/config.py` (model aliases, LiteLLM/Qdrant), `shared/working_mode.py`, `shared/notify.py` (ntfy), `shared/frontmatter.py` (canonical parser), `shared/dimensions.py` (11 dims), `shared/governance/consent.py`, `shared/agent_registry.py`, `shared/telemetry.py` (hapax_span ExitStack pattern — don't refactor).

## IR Perception

3 Pi fleet: Pi-1(.78) ir-desk, Pi-2(.52) ir-room, Pi-6(.74) sync+ir-overhead. YOLOv8n ONNX, 3s cadence. Fusion: any() for person, desk-prefer for gaze, overhead-prefer for hands.

## Hooks

| Hook | Blocks |
|------|--------|
| work-resolution-gate | Edit/Write on feature branch without PR |
| no-stale-branches | Branch creation with unmerged branches; max 20 worktrees |
| pii-guard | PII patterns |
| attribution-entity-check | Product-company misattributions in publication-adjacent files (registry: `config/publication-hardening/known-entities.yaml`) |
| unguarded-cd-guard | Bash where a failed `cd` would run later commands in the wrong directory (analyzer: `hooks/scripts/unguarded_cd_guard.py`; allowed: `set -e` before the cd, full `&&` chains, `cd X \|\| exit`) |

Activation state (2026-05-29; `unguarded-cd-guard.sh` registered for Bash in `~/.claude/settings.json` 2026-06-11 — recheck: `grep -c unguarded-cd-guard ~/.claude/settings.json`; the deployed copy at `~/.cache/hapax/rebuild/worktree/hooks/scripts/` was an untracked fail-open v1 until 2026-06-12, when it was replaced in place with the tracked analyzer pair — after any merge touching these hooks, re-run `hapax-hooks-doctor --check`): `push-gate.sh` remains unwired, but the conditional in-session release gate `pr-release-gate.sh` is registered in `~/.claude/settings.json` for Bash and GitHub MCP PR create/merge paths. It runs the AVSDLC release precheck and the real test-before-push evidence check where the active task requires release evidence. `hook-presence-verify.sh` runs on session start, `visual-audio-evidence-reflex.sh` advises after visual/audio edits, and `subagent-git-safety.sh` runs on SubagentStop. Pre-commit hooks are installed in the current council and constitution clones; new clones still need the one-time bootstrap in `docs/runbooks/pre-commit-bootstrap.md`. `.github/CODEOWNERS` documents governance-protected paths, but required Code Owner review is disabled for this single-user repo because GitHub forbids self-approval. Full verification runbook: `docs/runbooks/claude-code-config-conformance.md`.

## Voice & Research

Voice FX: PipeWire filter-chain presets at `config/pipewire/voice-fx-*.conf`. Research state: `agents/hapax_daimonion/proofs/RESEARCH-STATE.md`. Composition ladder: 10 layers, 7-dim matrix, gate on N-1 complete.
