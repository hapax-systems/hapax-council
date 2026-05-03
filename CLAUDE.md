# CLAUDE.md

Externalized executive function infrastructure. LLM agents handle cognitive work (tracking open loops, maintaining context, surfacing what needs attention) for a single operator on a single workstation. Single-operator is a constitutional axiom — no auth, no roles, no multi-user code anywhere.

Shared conventions (uv, ruff, testing, git workflow, pydantic-ai) are in the workspace `CLAUDE.md` — this file covers council-specific details only.

**Sister surfaces:** the [vscode extension](vscode/CLAUDE.md) is the operator's editor-side reading surface; [`hapax-mcp`](https://github.com/ryanklee/hapax-mcp) provides the same Logos API to Claude Code via MCP. **Spec dependency:** governance axioms come from [`hapax-constitution`](https://github.com/ryanklee/hapax-constitution) via the `hapax-sdlc` package; locally extended set in `axioms/registry.yaml`.

CLAUDE.md rotation policy: `docs/superpowers/specs/2026-04-13-claude-md-excellence-design.md`. Bug-fix retrospectives, PR fingerprints, and incident narratives do not belong here.

## Architecture

**Filesystem-as-bus**: Agents read/write markdown files with YAML frontmatter on disk. A reactive engine (inotify) watches for changes and cascades downstream work.

**Three tiers**:
- **Tier 1** — Interactive interfaces (hapax-logos Tauri native app, waybar GTK4 status bar, VS Code extension)
- **Tier 2** — LLM-driven agents (pydantic-ai, routed through LiteLLM at :4000). Local: TabbyAPI serves **Command-R 35B EXL3 5.0bpw** on `:5000` for `local-fast`/`coding`/`reasoning`, `gpu_split=[16, 10]` (primary 3090 + secondary 5060 Ti), `cache_size=16384`/`max_seq_len=16384` at Q4 cache mode. Ollama runs on GPU 1 (5060 Ti) per `/etc/systemd/system/ollama.service.d/z-gpu-5060ti.conf` (`CUDA_VISIBLE_DEVICES=1 OLLAMA_NUM_GPU=999`) — currently loading only `nomic-embed-cpu` (CPU-tagged), but the dual-GPU pinning is intentional so LLM embedding / light inference can land on the secondary card without colliding with TabbyAPI's 3090 residency. Cloud: Claude Sonnet/Opus for `balanced`/governance, Gemini Flash for `fast`/vision.
- **Tier 3** — Deterministic agents (sync, health, maintenance — no LLM calls)

**Reactive engine** (`logos/engine/`): inotify watcher → rules → phased execution (deterministic first, then LLM semaphore-bounded at max 2 concurrent).

**Infrastructure**: Docker Compose for databases/proxies (13 containers), systemd user units for all application services. No process-compose in production. See `systemd/README.md` for boot sequence, resource isolation, and recovery chain. **Canonical path for new systemd units: `systemd/units/`** — `scripts/hapax-post-merge-deploy` matches `systemd/units/*.service|*.timer` only; files placed elsewhere (e.g., `systemd/user/`) are silently invisible to the deploy chain.

> **Qdrant collection footnote (24h auditor finding #11, 2026-05-02):** The `operator-patterns` collection in the workspace Qdrant schema has zero upsert callers across the codebase (dead schema). Marked **pending retire decision** — do not add new writers; route operator-pattern facts through `profile-facts` or `operator-corrections` until a decommission PR lands.

**Key services**: `hapax-secrets` (credentials) → `logos-api` (:8051) → `waybar` (GTK4 status bar) → `tabbyapi` (GPU, EXL3 inference :5000) → `hapax-daimonion` (GPU STT, CPU TTS) → `visual-layer-aggregator` → `studio-compositor` (GPU). Timers for sync, health, backups. Archival pipeline (audio/video recording, classification, RAG ingest) disabled — see `systemd/README.md § Disabled Services`.

## Design Language

`docs/logos-design-language.md` is the authority document for all visual surfaces. It governs color (§3), typography (§1.6), spatial model (§4), animation (§6), mode switching (§2), and scope (§11). All component colors must use CSS custom properties (`var(--color-*)`) or Tailwind classes — no hardcoded hex except detection overlays (§3.8). `docs/logos-ui-reference.md` governs region content (what appears at each depth). Classification inspector (`C` key) is exempt from density rules — diagnostic tool with theme-aware colors.

## Logos API

FastAPI on `:8051`. `uv run logos-api` to start. Containers: `docker compose up -d`.

## Orientation Panel

Unified orientation surface replacing the old Goals + Briefing sidebar widgets. Reads vault-native goal notes (YAML frontmatter `type: goal`), assembles per-domain state (research, management, studio, personal, health), infers session context from telemetry, and renders with stimmung-responsive density modulation.

- `logos/data/vault_goals.py` — Scans Obsidian vault for `type: goal` notes, computes staleness from mtime
- `logos/data/session_inference.py` — Infers session context from git, IR, stimmung, sprint telemetry
- `logos/data/orientation.py` — Assembles domain states, conditional LLM narrative gating
- `logos/api/routes/orientation.py` — `GET /api/orientation` (slow cache tier, 5 min)
- `config/domains.yaml` — Domain registry mapping life domains to data sources and telemetry
- `hapax-logos/src/components/sidebar/OrientationPanel.tsx` — Frontend

Domain ranking: blocked gates > stale P0 goals > active > stale > dormant. Sprint progress attached to research domain only. Spec: `docs/superpowers/specs/2026-04-01-orientation-panel-design.md`.

## Obsidian Integration

Personal vault at `~/Documents/Personal/` (kebab-case dirs, kebab-case filenames). PARA structure: `00-inbox`, `10-meta`, `20-personal`, `20-projects`, `30-areas`, `40-calendar`, `50-templates`, `50-resources`. Syncs to phone via Obsidian Sync.

**obsidian-hapax plugin** (`obsidian-hapax/`): Context panel in right sidebar. Resolves active note to a NoteKind (Measure, Gate, SprintSummary, PosteriorTracker, Research, Concept, Briefing, Nudges, Goal, Daily, Management, Studio, Unknown) and renders domain-appropriate context from Logos API. Mobile support via LAN IP auto-detect. 8s request timeout.

**Vault-native goal notes:** `type: goal` frontmatter with `domain`, `status`, `priority`, `sprint_measures`, `depends_on`. Template at `50-templates/tpl-goal.md`. FileClass at `10-meta/fileclass/goal.md`.

**Agents:**
- `agents/obsidian_sync.py` — Batch vault → RAG sync (6h timer). Extracts frontmatter, writes to `rag-sources/obsidian/`. Also extracts management cadence from person notes.
- `agents/vault_context_writer.py` — Writes working context to daily note `## Log` via Obsidian Local REST API (15-min timer).
- `agents/vault_canvas_writer.py` — Generates JSON Canvas goal dependency map.
- `agents/sprint_tracker.py` — Reads/writes sprint measure vault notes bidirectionally. 5-min timer.

**Lint-on-save** via obsidian-linter with a fixed rule set (see plugin config). Ignores `50-templates/` and `sprint/`. Mobile: plugin auto-detects LAN IP for Logos API; firewall allows LAN (`192.168.68.0/22`) and Tailscale (`100.64.0.0/10`) to port 8051.

## Command Registry

Centralized automation layer for all Logos UI actions. Every action (focus region, activate preset, toggle overlay) is a registered command with typed args and observable events.

**Access points:**
- **Playwright / browser console**: `window.__logos.execute("terrain.focus", { region: "ground" })`
- **Keyboard**: Single adapter in `CommandRegistryProvider`, key map in `lib/keyboardAdapter.ts`
- **External (MCP, voice)**: WebSocket relay at `ws://localhost:8052/ws/commands` (Rust, inside Tauri)
- **CommandPalette**: Reads from `registry.list()` dynamically

**Key files:**
- `hapax-logos/src/lib/commandRegistry.ts` — Core registry (framework-agnostic)
- `hapax-logos/src/lib/commands/*.ts` — Domain registrations (terrain, studio, overlay, detection, nav, split, data)
- `hapax-logos/src/lib/commands/sequences.ts` — Built-in sequences (studio.enter, studio.exit, escape)
- `hapax-logos/src/lib/keyboardAdapter.ts` — Key map with `when`-clause conditional bindings
- `hapax-logos/src/contexts/CommandRegistryContext.tsx` — React provider, `window.__logos`, keyboard handler
- `hapax-logos/src-tauri/src/commands/relay.rs` — Rust WebSocket relay server (:8052)

The provider maintains synchronous state mirrors updated eagerly by action wrappers, so `query()` returns post-execution state without waiting for React re-render. Spec: `docs/superpowers/specs/2026-03-26-logos-command-registry-design.md`.

## Tauri-Only Runtime

Logos is a Tauri 2 native app. The frontend speaks **only IPC** — zero browser `fetch()` calls. All API communication goes through `invoke()` to Rust commands, which proxy to FastAPI at `:8051` internally.

**Inside the Tauri process:**
- **IPC commands** — 60+ invoke handlers (health, state, studio, governance, proxy passthrough)
- **SSE bridge** — Rust subscribes to FastAPI SSE streams, re-emits as Tauri events (`commands/streaming.rs`)
- **Command relay** — WebSocket server on `:8052` for MCP/voice (`commands/relay.rs`)
- **HTTP frame server** — Axum on `:8053` serves visual surface JPEG frames (`visual/http_server.rs`)

**Visual surface (Hapax Reverie):** standalone binary `hapax-imagination` runs as a systemd user service, rendering dynamic shader graphs via wgpu. Python compiles effect presets (`agents/effect_graph/wgsl_compiler.py`) into WGSL execution plans that the Rust `DynamicPipeline` hot-reloads from `/dev/shm/hapax-imagination/pipeline/`. The permanent vocabulary graph runs 8 passes: `noise → rd → color → drift → breath → feedback → content_layer → postprocess`; `rd` and `feedback` are temporal (Bachelard Amendment 2).

Per-node shader params flow from Python visual chain → `uniforms.json` → Rust per-frame override bridge. Visual chain writes `{node_id}.{param_name}` keys; `{param_name}` must match WGSL Params struct field order (no `u_` prefix). Multiplicative params (`colorgrade.brightness`, `colorgrade.saturation`, `postprocess.master_opacity`) default to 1.0 or the pipeline outputs black. Plan schema is v2 (`{"version": 2, "targets": {"main": {"passes": [...]}}}`); `_uniforms._iter_passes()` handles v1 and v2 transparently.

9 expressive dimensions in the GPU uniform buffer: intensity, tension, depth, coherence, spectral_color, temporal_distortion, degradation, pitch_displacement, diffusion. The DMN evaluative tick sends the rendered frame directly to gemini-flash (multimodal) alongside sensor text — first-person visual perception, not mediated. Gemini Flash 2.5 requires `budget_tokens: 0` for vision. Frames written to `/dev/shm/hapax-visual/frame.jpg` via turbojpeg. `VisualSurface` React component fetches frames at 10fps from `:8053`. Tauri communicates with imagination daemon via UDS (`$XDG_RUNTIME_DIR/hapax-imagination.sock`).

**NVIDIA + Wayland:** webkit2gtk 2.50.6 has a syncobj protocol bug that crashes the app on native Wayland with NVIDIA. Workaround: `__NV_DISABLE_EXPLICIT_SYNC=1` (set in systemd unit and `.envrc`). Details: `docs/issues/tauri-wayland-protocol-error.md`.

**Dev workflow:** `pnpm tauri dev` is the only dev path. Vite serves assets to the Tauri webview only — no proxy, no exposed API.

## Unified Semantic Recruitment

Everything that appears — visual content, tool invocation, vocal expression, destination routing — is recruited through a single `AffordancePipeline`. No bypass paths. Spec: `docs/superpowers/specs/2026-04-02-unified-semantic-recruitment-design.md`.

**Mechanism:** Impingement → embed narrative → cosine similarity against Qdrant `affordances` collection → score `(0.50×similarity + 0.20×base_level + 0.10×context_boost + 0.20×thompson + w_recency×recency_distance − exact_recency_penalty) × cost_weight` → governance veto → recruited capabilities activate. `cost_weight = 1.0 − cost×0.5` where `cost = 0.3` for GPU-required capabilities and `max(cost, 0.5)` for slow-latency-class capabilities (`shared/affordance_pipeline.py:756`). Thompson sampling (optimistic prior: Beta(2,1)) + Hebbian associations learn from outcomes across sessions; alpha/beta posterior parameters are clamped to `[1.0, 10.0]` via `_TS_FLOOR`/`_TS_CAP` to prevent saturation (geometric decay `α·γ + 1` with γ=0.99 would otherwise converge alpha→100 and produce deterministic Beta(100, ~0) samples — see `shared/affordance.py:109,129`). Activation state persisted every 60s via background thread + on shutdown.

**Taxonomy (6 domains):** perception, expression, recall, action, communication, regulation. Each capability has a Gibson-verb affordance description (15-30 words, cognitive function not implementation). Three-level Rosch structure: Domain → Affordance (embedded in Qdrant) → Instance (metadata payload).

**Imagination produces intent, not implementation.** `ImaginationFragment` carries narrative, 9 canonical dimensions, material (water/fire/earth/air/void), salience. The narrative IS the only retrieval query.

**Content recruitment:** Camera feeds, text rendering, knowledge queries are registered affordances. Appear only when pipeline recruits them. `ContentCapabilityRouter` handles activation.

**Tool recruitment:** 31 tools registered with Gibson-verb descriptions. `ToolRecruitmentGate` converts operator utterances to impingements, pipeline selects tools per-turn, LLM sees only recruited tools.

**Destinations:** `OperationalProperties.medium` ("auditory", "visual", "textual", "notification"). `_infer_modality()` reads declared medium, not capability name substrings.

**Generative substrate:** The vocabulary shader graph always runs. Not a capability. Not recruited. The DMN is a permanently running generative process — recruitment modulates it, content composites into it.

**Exploration → SEEKING:** 13 components publish boredom/curiosity signals to `/dev/shm/hapax-exploration/`. VLA reads aggregate boredom (top-k worst third, not mean) and feeds `exploration_deficit` to stimmung. When deficit > 0.35 and all dimensions nominal, stance transitions to SEEKING (3-tick hysteresis). Reverie mixer halves the recruitment threshold (0.05 → 0.025) for dormant capabilities while SEEKING.

**Consent gate:** Capabilities declaring `OperationalProperties.consent_required=True` are filtered out of `AffordancePipeline.select()` when no active consent contract exists in `axioms/contracts/`. Fail-closed; state cached 60s. Axiom `interpersonal_transparency` mandates this gate. **Scope (post 2026-04-18 retirement):** the consent gate now governs non-visual capabilities only — audio capture, transcription persistence, interaction recording, person-identified ward content. Visual privacy at livestream egress is enforced at the face-obscure pipeline layer (#129) in `agents/studio_compositor/face_obscure_integration.py`, which pixelates every camera frame (fail-CLOSED on detector failure) before any RTMP/HLS/V4L2 tee. The legacy consent-safe layout-swap gate in `agents/studio_compositor/consent_live_egress.py` is DISABLED by default; set `HAPAX_CONSENT_EGRESS_GATE=1` to restore legacy fail-closed layout-swap behavior. Rationale: `docs/governance/consent-safe-gate-retirement.md`.

**Daimonion impingement dispatch:** the daimonion spawns two independent consumers reading `/dev/shm/hapax-dmn/impingements.jsonl`. CPAL loop owns gain/error modulation and spontaneous-speech surfacing via `CpalRunner.process_impingement`. Affordance loop (`run_loops_aux.impingement_consumer_loop`) owns notification, studio, world-domain Thompson recording, capability discovery, and cross-modal dispatch (textual + notification modalities; auditory is CPAL's). Separate cursor files (`impingement-cursor-daimonion-cpal.txt`, `impingement-cursor-daimonion-affordance.txt`). Regression pin: `tests/hapax_daimonion/test_impingement_consumer_loop.py::TestSpawnRegressionPin`.

**Impingement consumer bootstrap:** `shared/impingement_consumer.ImpingementConsumer` supports three modes. Default (`cursor=0`) for tests and stateless callers. `start_at_end=True` for reverie, where stale visual impingements cannot meaningfully modulate the next tick. `cursor_path=<Path>` with atomic tmp+rename for daimonion and fortress, where missing an impingement is a correctness bug. `cursor_path` takes precedence over `start_at_end`.

## Studio Compositor

GStreamer-based livestream pipeline. Distinct from Reverie (the wgpu visual surface) — two separate render paths. The compositor reads USB cameras, composites them into a single 1920x1080 frame, applies a GL shader chain, draws Cairo overlays (Sierpinski triangle with YouTube frames, token pole, album cover, content zones), and writes to `/dev/video42` (OBS V4L2 source) plus an HLS playlist.

**Architecture (compositor unification epic complete):** typed `Source` / `Surface` / `Assignment` / `Layout` data model (`shared/compositor_model.py`), `CairoSource` protocol driving all Python Cairo content on background threads (`cairo_source.py::CairoSourceRunner` with its own render cadence and cached output surface the cairooverlay callback blits synchronously), multi-target render loop, transient texture pool, per-frame budget enforcement with degraded-signal publishing. **No Cairo rendering on the GStreamer streaming thread.**

**Key modules:**
- `agents/studio_compositor/compositor.py` — `StudioCompositor` orchestration shell
- `agents/studio_compositor/cairo_source.py` — `CairoSource` protocol + `CairoSourceRunner`
- `agents/studio_compositor/{sierpinski_renderer,album_overlay,overlay_zones,token_pole}.py` — Cairo surfaces at 10–30 fps
- `agents/studio_compositor/chat_reactor.py` — `PresetReactor`: chat keyword → preset name → `graph-mutation.json` write with 30s cooldown. Consent guardrail: no per-author state, no persistence, no author in logs (caplog test enforced)
- `agents/studio_compositor/budget.py` — `BudgetTracker` + `publish_costs`; `budget_signal.py` publishes degraded signal for VLA
- `shared/compositor_model.py` — Pydantic Source/Surface/Assignment/Layout models. `SurfaceKind.fx_chain_input` for main-layer appsrc pads

**Specs and handoffs:**
- `docs/superpowers/plans/2026-04-12-compositor-unification-epic.md` — the unification epic
- `docs/superpowers/specs/2026-04-12-compositor-source-registry-foundation-design.md` — source-registry epic (register reverie as `external_rgba`, migrate cairo overlays to natural-size + layout-driven placement)
- `docs/superpowers/specs/2026-04-13-reverie-source-registry-completion-design.md` — umbrella epic that finishes the above plan + adjacent observability work (freshness gauges, pool metrics IPC, F7/F10 decisions, Amendment 4 verification)
- `docs/superpowers/plans/2026-04-13-reverie-source-registry-completion-plan.md` — master plan for the completion epic (9 phases, serial execution)
- `docs/superpowers/handoff/2026-04-12-delta-source-registry-handoff.md` — delta session pickup

**Camera 24/7 resilience epic (shipped):** software-layer containment of Logitech BRIO USB bus-kick (kernel `device descriptor read/64, error -71`, hardware-level). Per-camera sub-pipelines with paired fallback producers, hot-swap via `interpipesrc.listen-to`, 5-state recovery FSM with exponential backoff, pyudev monitoring, Prometheus metrics on `127.0.0.1:9482`, `Type=notify` + `WatchdogSec=60s`, native GStreamer RTMP output via `rtmp_output.py` (NVENC p4 low-latency, MediaMTX relay on `127.0.0.1:1935`). Retirement handoff: `docs/superpowers/handoff/2026-04-13-alpha-camera-247-epic-handoff.md`. Dependencies: `gst-plugin-interpipe`, `mediamtx-bin`, `python-prometheus_client`, `sdnotify`.

Test harness in `scripts/`: `studio-install-udev-rules.sh`, `studio-simulate-usb-disconnect.sh <role>`, `studio-smoke-test.sh`.

## Reverie Vocabulary Integrity

Effect-graph WGSL inventory: **64 shader nodes** in-tree (`find . -name '*.wgsl' | wc -l`, verified 2026-05-02 per 24h auditor finding #11; previously stated as 56 in user-memory `project_effect_graph` — refresh that index entry). 30 presets in `presets/`, glfeedback Rust plugin, SlotPipeline.

The reverie mixer caches the vocabulary preset (`presets/reverie_vocabulary.json`) in memory via `SatelliteManager._core_vocab`. `SatelliteManager.maybe_rebuild()` reloads the preset from disk on `GraphValidationError`, so recovery is automatic at the next rebuild tick after any validation failure.

Any Sierpinski or other satellite shader nodes in Reverie MUST be recruited dynamically via the affordance pipeline (prefix `sat_<node_type>`), NOT wired into the core vocabulary. If core-prefix nodes like `content: sierpinski_content` appear (instead of `sat_sierpinski_content`), restart the service.

**WGSL node catalog (audit U7, 2026-05-03):** `agents/shaders/nodes/` carries 60 `.wgsl` files (legacy `hapax-logos/crates/hapax-visual/src/shaders` adds 4 more for a 64-file total; that path is decommissioned and not reachable at runtime). Of the 60 live nodes, 8 are the always-on permanent vocabulary (`noise → rd → color → drift → breath → feedback → content_layer → postprocess`); the remaining 52 are satellite-recruitable but only register-as-affordance get cosine-similarity-discovered by the AffordancePipeline. As of cc-task `wgsl-node-affordance-coverage-batch-4` the floor is **60 of 60 nodes registered** in `shared.affordance_registry.SHADER_NODE_AFFORDANCES` — full coverage; every WGSL file in `agents/shaders/nodes/` is recruitable by the AffordancePipeline. Description-quality tuning is now the next axis (see `affordance-description-quality-audit` cc-task). Regression pin: `tests/test_wgsl_node_affordance_coverage.py` (`MIN_REGISTERED_NODES`).

**Intermediate texture pool:** `DynamicPipeline` allocates non-temporal intermediate textures through `TransientTexturePool<PoolTexture>`. Pool key is `hash(width, height, TEXTURE_FORMAT)`, recomputed on resize. External observability via `DynamicPipeline::pool_metrics()` (bucket count, total textures, acquires, allocations, reuse ratio).

**Visual chain → GPU bridge has two paths, both must be alive:**
1. **Shared 9-dim uniform slots.** Imagination fragment's 9 dimensions flow `current.json` → `StateReader.imagination.dimensions` → `UniformBuffer::from_state` → shared `UniformData.{dim}`. Any shader reading `uniforms.intensity` etc. lands here.
2. **Per-node `params_buffer`.** `visual_chain.compute_param_deltas()` emits `{node_id}.{param_name}` → `uniforms.json` → `dynamic_pipeline.rs` walks `pass.param_order` positionally. Each shader with a `@group(2) Params` binding (noise, rd, colorgrade, drift, breath, feedback, postprocess) receives per-node modulation.

Live `jq 'keys | length' /dev/shm/hapax-imagination/uniforms.json` should be ≥44 (42 plan defaults + `signal.stance` + `signal.color_warmth`). `content_layer.wgsl` has no `@group(2) Params` binding — it reads `material_id` / slot salience / intensity from `uniforms.custom[0]`; mixer writes all three keys, material maps water/fire/earth/air/void → 0..4 via `MATERIAL_MAP`. Regression pin: `tests/test_reverie_uniforms_plan_schema.py`.

## Voice FX Chain

Hapax TTS output (Kokoro 82M CPU) can be routed through a user-configurable PipeWire `filter-chain` before being normalised by `hapax-loudnorm-capture` and reaching the L-12 → Evil Pet → broadcast path. (Historical: prior to the 24c retirement 2026-05-03, the chain terminated at the PreSonus Studio 24c analog output.) Presets at `config/pipewire/voice-fx-*.conf`; install into `~/.config/pipewire/pipewire.conf.d/`, restart pipewire, export `HAPAX_TTS_TARGET=hapax-voice-fx-capture` before starting `hapax-daimonion.service`. Unset falls through to default wireplumber routing. All presets share the same sink name so swapping does not require restarting daimonion. Details: `config/pipewire/README.md`.

## CC Task Tracking (Obsidian SSOT — D-30)

**Canonical work-state surface:** `~/Documents/Personal/20-projects/hapax-cc-tasks/` in the operator's Obsidian vault. One markdown note per task with `type: cc-task` frontmatter (status, assigned_to, priority, wsjf, etc.). Operator-facing dashboards under `_dashboard/` use Dataview queries (Tasks + Dataview plugins, both already deployed).

**Per-session interaction:**
- `cc-claim <task_id>` (in `scripts/cc-claim`, symlink to `~/.local/bin/`) — atomic claim: rewrites frontmatter (status: claimed; assigned_to: $CLAUDE_ROLE) + writes the per-role claim file at `~/.cache/hapax/cc-active-task-{role}`.
- First file mutation triggers PreToolUse hook `hooks/scripts/cc-task-gate.sh` which auto-transitions claimed → in_progress and rejects if status doesn't match the role's claim.
- `cc-close <task_id> [--pr N]` — closes the task: status → done (or withdrawn/superseded), moves note to `closed/`, clears claim file.
- SessionStart preamble (`hooks/scripts/session-context.sh` D-30 Phase 4) shows currently-claimed task + top 5 offered tasks by WSJF.

**Codex multi-session control plane:** load-bearing Codex lanes use tmux as the control plane (`hapax-codex-cx-<color>`). `scripts/hapax-codex --terminal tmux` is acceptable for headless worker lanes; `--terminal foot` attaches a visible foot window to the same tmux session. `cx-red` and protected `cx-violet` stay screen-visible, but `cx-amber`/`cx-blue`/`cx-cyan` may be headless when `~/Documents/Personal/20-projects/hapax-cc-tasks/_dashboard/codex-session-health.md`, relay YAML, active claim files, and PR state are current. Parent instructions that assign or redirect work should use `scripts/hapax-codex-send --require-ack`; a successful key paste is not task receipt.

**Claude Code multi-session control plane:** symmetric stack for the greek-named Claude lanes (alpha/beta/delta/epsilon). Targets are tmux sessions named `hapax-claude-<role>` and/or foot windows with class `hapax-claude-<role>`. `scripts/hapax-claude --terminal {tmux,foot}` spawns a lane in its canonical worktree with identity envvars wired (`HAPAX_AGENT_INTERFACE=claude`, `HAPAX_AGENT_NAME=<role>`, `CLAUDE_ROLE=<role>`). `scripts/hapax-claude-send --require-ack` is the synchronous parent-to-child send: tmux paste-and-submit + token-based ACK file + busy-pane refusal + auto-nudge. `scripts/hapax-claude-smoke-send` exercises the path against a throwaway bash-backed tmux session for CI use. `scripts/hapax-claude-health [--write-obsidian]` reports per-lane tmux/foot presence, claim↔relay-yaml consistency, and renders `_dashboard/claude-session-health.md`. Designed to mirror the codex stack 1:1 so the operator can dispatch directives across both interfaces without remembering separate idioms.

**Gemini Code multi-session control plane (Gemini CLI Interactive):** third peer-worker stack alongside Claude Code and Codex, replacing the one-shot Jr-Gemini packet model with a persistent interactive REPL lane. Lanes are greek-named (`iota` shipped first; `kappa`/`lambda`/`mu` follow if iota is stable for 24h) and target tmux sessions named `hapax-gemini-<role>`. `scripts/hapax-gemini --terminal {tmux,foot}` spawns a lane in `$HAPAX_GEMINI_WORKTREE_ROOT/hapax-council--<role>` with identity envvars wired (`HAPAX_AGENT_INTERFACE=gemini`, `HAPAX_AGENT_NAME=<role>`, `GEMINI_ROLE=<role>`) and invokes `gemini --approval-mode plan --include-directories=<vault>,<relay> --policy ~/.gemini/policies/hapax-governance-firewall.toml --resume latest`. `--resume latest` reloads context from `~/.gemini/tmp/<friendly-project>/chats/session-*.jsonl` so the lane survives respawns. `scripts/hapax-gemini-send --require-ack` is the synchronous parent-to-child send: tmux paste-and-submit + 10-second screen-idle stability check (avoids Ink/React redraw races) + token-based ACK file + JSONL-tail ACK fallback (watches the latest session file for a `type:"gemini"` event terminating with a `tokens` block) + busy-pane refusal (StreamingState spinner detection) + auto-nudge. `scripts/hapax-gemini-smoke-send` exercises the path against a throwaway bash-backed tmux session for CI use. `systemd/units/hapax-gemini-iota-watchdog.service` (Type=notify, WatchdogSec=120s, Restart=always) scans the tmux pipe-pane log every 60s for the catastrophic Flash-downgrade banner ("forcefully and permanently switched over to Flash") and respawns the lane on detection — `--resume latest` recovers context. The iota lane operates exclusively in plan mode (no shell exec, no file write, no commits, no cc-claim/cc-close) until the operator explicitly widens it; the bootstrap prompt at `prompts/peer-gemini-bootstrap.md` codifies the constraint surface and the Findings/Evidence/Uncertainty/Next-action output contract that senior peers (Claude Code, Codex) consume. Quotas are per-Google-account (60 RPM / 1k RPD); all gemini lanes share the OAuth credential at `~/.gemini/oauth_creds.json` (single-account is fine for one lane). The legacy one-shot `scripts/hapax-gemini-jr-team` packet path is unchanged and continues to coexist for stateless one-thing-and-done research jobs.

**Native `TaskCreate` is deprecated for cross-session workstream items** — use the vault SSOT instead. Native TaskTool remains permitted for single-session ephemeral todos that don't need operator visibility.

**Bridges:**
- Native CC TaskTool → vault: one-shot migration `scripts/migrate_native_tasks_to_vault.py` (already applied 2026-04-20: 221 native tasks → 39 active + 182 closed).
- Relay yaml `active_queue_items[]` → vault: 5-min systemd timer `hapax-relay-to-cc-tasks.timer` mirrors operator-author queue items into vault notes (idempotent, preserves operator hand-edits).

**Hook bypass for incident response:** `HAPAX_CC_TASK_GATE_OFF=1`. Hook is OFF BY DEFAULT until D-30 Phase 7 validation completes (currently in progress).

References:
- Spec: `docs/superpowers/specs/2026-04-20-cc-task-obsidian-ssot-design.md`
- Plan: `docs/superpowers/plans/2026-04-20-cc-task-obsidian-ssot-plan.md`
- Origin: `docs/research/2026-04-20-total-workstream-gap-audit.md` §6 P0
- Tracking: WSJF doc D-30
- Vault README: `~/Documents/Personal/20-projects/hapax-cc-tasks/_dashboard/cc-readme.md`

## Council-Specific Conventions

- Hypothesis for property-based algebraic proofs.
- Working mode file: `~/.cache/hapax/working-mode` (research/rnd). CLI: `hapax-working-mode`.
- Safety: LLMs prepare, humans deliver. Never generate feedback language or coaching recommendations about individual team members.
- **Session handoffs** live at `docs/superpowers/handoff/{date}-{session}-handoff.md`. Each retiring session writes one before stopping; the next session of the same role reads it after relay onboarding. Docs-only and root-level markdown PRs now trigger required-check sentinels, so branch protection stays satisfied without a carrier-file change.
- **Build rebuild scripts:** `scripts/rebuild-logos.sh` builds logos/imagination in an isolated scratch worktree at `$HOME/.cache/hapax/rebuild/worktree`; primary alpha/beta worktrees are never mutated mid-session. `scripts/rebuild-service.sh` handles Python services and refuses to deploy a feature branch — when alpha is off main it skips the deploy and emits a throttled ntfy so the operator notices. `flock -n` on `$STATE_DIR/lock` prevents concurrent runs. The underlying tension (alpha's worktree doubles as dev branch and production deploy target) is documented in the FU-6 handoff.

## Axiom Governance

5 axioms (3 constitutional, 2 domain) enforced via `shared/axiom_*.py`, `shared/governance/consent.py`, and commit hooks:

| Axiom | Weight | Constraint |
|-------|--------|------------|
| single_user | 100 | One operator. No auth, roles, or collaboration features. |
| executive_function | 95 | Zero-config agents, errors include next actions, routine work automated. |
| corporate_boundary | 90 | Work data stays in employer systems. Home system = personal + management-practice only. |
| interpersonal_transparency | 88 | No persistent state about non-operator persons without active consent contract. |
| management_governance | 85 | LLMs prepare, humans deliver. No generated feedback/coaching about individuals. |

T0 violations blocked by SDLC hooks. Definitions in `axioms/registry.yaml`, implications in `axioms/implications/`, consent contracts in `axioms/contracts/`.

**Non-formal operator referent policy** (`su-non-formal-referent-001`, directive 2026-04-24): in non-formal contexts (livestream narration, captions, social-surface posts, YouTube metadata, chat attribution, scope-nudge framing), the operator is referred to exclusively by one of four equally-weighted referents — `"The Operator"`, `"Oudepode"`, `"Oudepode The Operator"`, `"OTO"`. Selection is sticky-per-utterance via `shared.operator_referent.OperatorReferentPicker`; seed with `pick_for_tick(tick_id)` for director narration, `pick_for_vod_segment(video_id)` for YouTube / cross-surface posts. Legal name is reserved for formal-address-required contexts only (partner-in-conversation role, consent contracts, axiom precedents, git author metadata, profile persistence) — `logos.voice.operator_name()` remains the formal-context function. Spec: `docs/superpowers/specs/2026-04-24-operator-referent-policy-design.md`. Canonical spelling is **Oudepode** (with `e`) — matches existing IPA `uˈdɛpoʊdeɪ` in `shared/speech_lexicon.py`.

## Aesthetic Library & CDN

Canonical ingest surface for authentic third-party visual assets (BitchX splash/quotes/palette, Px437 IBM VGA 8×16 font). Source of truth lives in-repo at `assets/aesthetic-library/` with `_manifest.yaml` (SHA-256 per asset) and per-group `provenance.yaml` (source URL, license, attribution). The `shared.aesthetic_library.library()` singleton provides typed `Asset`/`Manifest`/`Provenance` models, integrity verification, and SHA-pinned web URL synthesis. Integrity is gated by `scripts/verify-aesthetic-library.py` in the lint CI job — drift fails fast. License hygiene: BSD-3-Clause (BitchX), CC-BY-SA-4.0 (Px437, unmodified-only). Europa.c GPL-2 plugin explicitly excluded.

**Public CDN** (`ytb-AUTH-HOSTING`): `agents/hapax_assets_publisher/` daemon mirrors `assets/aesthetic-library/` → `ryanklee/hapax-assets` (GitHub Pages, `gh-pages` branch auto-deployed via `.github/workflows/publish.yml` in the external repo). omg.lol surfaces embed via SHA-pinned URLs from `library().web_url(asset)`. Bootstrap (one-time operator action): `scripts/setup-hapax-assets-repo.sh` creates the external repo + seeds workflow + clones into `~/.cache/hapax/hapax-assets-checkout/` + enables Pages. Then `systemctl --user enable --now hapax-assets-publisher.service`. Publisher is idempotent, push-throttled (30s min interval via `PushThrottle`), and logs-and-skips cleanly when the checkout is not yet configured.

**Provenance gate** (`ytb-AUTH2`): `scripts/verify-aesthetic-library.py` runs three checks in CI's lint job — `_manifest.yaml` + `_NOTICES.md` currency, SHA-256 byte-level integrity, and **every manifest source has a sibling `provenance.yaml`** (`AestheticLibrary.missing_provenance()`). `hooks/scripts/asset-provenance-gate.sh` is a PreToolUse hook that runs the same check on local `git commit` / `git push`, so the commit-time gate and the CI gate are one script. Governance: implication `it-attribution-001` under `interpersonal_transparency` mandates attribution for redistributed third-party content. CODEOWNERS pins `LICENSE.*`, `_NOTICES.md`, `_manifest.yaml`, and `**/provenance.yaml` for governance review.

## SDLC Pipeline

LLM-driven lifecycle via GitHub Actions: Triage → Plan → Implement → Adversarial Review (3 rounds max) → Axiom Gate → Auto-merge. Scripts in `scripts/`, workflows in `.github/workflows/`. All scripts support `--dry-run`. Observability via `profiles/sdlc-events.jsonl` + Langfuse traces. Agent PRs only on `agent/*` branches with `agent-authored` label.

## Claude Code Hooks (`hooks/scripts/`)

PreToolUse hooks enforce branch discipline and safety at the tool-call level:

| Hook | Gates | Blocks when |
|------|-------|-------------|
| `work-resolution-gate.sh` | Edit, Write | Feature branch with commits but no PR; on main with open PRs whose branch is local |
| `no-stale-branches.sh` | Bash | **Branch creation**: any unmerged branches exist. **Session worktree limit:** max 4 (alpha + beta + delta + 1 spontaneous); infrastructure worktrees under `~/.cache/` not counted. **Destructive commands** (`git reset --hard`, `git checkout .`, `git branch -f`, `git worktree remove`): on a feature branch with commits ahead of main |
| `push-gate.sh` | Bash | Push without passing tests |
| `pii-guard.sh` | Edit, Write | PII patterns in file content |
| `axiom-commit-scan.sh` | Bash | Commit messages violating axiom patterns |
| `session-context.sh` | Bash | Advisory: session context and relay status |

Destructive command detection strips quoted strings before matching to prevent false positives from commit messages that discuss git commands.

## IR Perception (Pi NoIR Edge Fleet)

3 Raspberry Pi 4s with Pi Camera Module 3 NoIR under 850nm IR flood illumination. Each runs `hapax-ir-edge` daemon: YOLOv8n (ONNX Runtime) person detection + NIR hand thresholding + adaptive screen detection. Captures via `rpicam-still`, POSTs structured JSON to council every ~3s.

**Pi fleet:**
- **Pi-1** (192.168.68.78) — ir-desk, co-located with C920-desk
- **Pi-2** (192.168.68.52) — ir-room, co-located with C920-room
- **Pi-4** (192.168.68.53) — sentinel (health monitor, watch backup)
- **Pi-5** (192.168.68.72) — rag-edge (document preprocessing)
- **Pi-6** (192.168.68.74) — sync-hub + ir-overhead, co-located with C920-overhead

**Data flow:** Pi daemon → `POST /api/pi/{role}/ir` → `~/hapax-state/pi-noir/{role}.json` → `ir_presence` backend → perception engine → `perception-state.json`. Heartbeats every 60s via `hapax-heartbeat.timer` → `POST /api/pi/{hostname}/heartbeat`. Health monitor `check_pi_fleet()` validates freshness, service status, CPU temp, memory, disk.

**Key files:**
- `pi-edge/` — Edge daemon + heartbeat code (deployed to each Pi at `~/hapax-edge/`)
- `shared/ir_models.py` — Shared Pydantic schema
- `agents/hapax_daimonion/backends/ir_presence.py` — Perception backend (multi-Pi fusion)
- `agents/hapax_daimonion/backends/contact_mic_ir.py` — Cross-modal fusion (IR hand zone + contact mic DSP)
- `agents/health_monitor/constants.py` — `PI_FLEET` dict (expected services per Pi)

**Inference:** ONNX Runtime preferred (130ms), TFLite fallback. Model: YOLOv8n fine-tuned on NIR studio frames (`best.onnx`). **Signal quality invariants** (`docs/superpowers/specs/2026-03-31-ir-perception-remediation-design.md`): hand detection `max_area_pct=0.25` rejects frame-spanning false positives, aspect ratio 0.3–3.0, screen detection uses adaptive threshold (`mean_brightness × 0.3`), rPPG gated on face landmarks actually available, `face_detected` field exposed on `IrBiometrics`.

**Fusion logic:** Person detection = any() across Pis. Gaze/biometrics prefer desk Pi. Hand activity + hand zone prefer overhead Pi. Staleness cutoff 10s. Signals: ir_person_detected, ir_person_count, ir_motion_delta, ir_gaze_zone, ir_head_pose_yaw, ir_posture, ir_hand_activity, ir_hand_zone, ir_screen_looking, ir_drowsiness_score, ir_blink_rate, ir_heart_rate_bpm, ir_heart_rate_conf, ir_brightness, ir_brightness_delta. `contact_mic_ir.py::_classify_activity_with_ir()` provides cross-modal fusion (turntable+sliding=scratching, mpc-pads+tapping=pad-work).

**Debug:** `kill -USR1 $(pgrep -f hapax_ir_edge)` saves a greyscale frame to `/tmp/ir_debug_{role}.jpg`. `--save-frames N` saves every Nth frame to `~/hapax-edge/captures/` for training.

## Bayesian Presence Detection

`PresenceEngine` (`agents/hapax_daimonion/presence_engine.py`) fuses heterogeneous signals into a single `presence_probability` posterior via Bayesian log-odds update. Hysteresis state machine: PRESENT (≥0.7 for 2 ticks), UNCERTAIN, AWAY (<0.3 for 24 ticks).

**Signal design principle — positive-only for unreliable sensors:** signals where absence is ambiguous (face not visible, silence, no desktop focus change) contribute `True` when detected but `None` (skipped by Bayesian update) when absent. Only structurally reliable signals (keyboard from evdev, BT connection) use bidirectional evidence.

**Primary signals** (desk work):

| Signal | Source | LR | Type |
|---|---|---|---|
| desk_active | Contact mic Cortado MKIII via pw-cat | 18x | positive-only |
| keyboard_active | evdev raw HID (Keychron + Logitech) | 17x | bidirectional |
| ir_hand_active | Pi NoIR hand detection (motion-gated >0.05) | 8.5x | positive-only |

**Absence signals:**

| Signal | Source | LR (False) | Condition |
|---|---|---|---|
| keyboard_active | evdev idle >5min | 5.6x | No physical keystrokes for 300s |
| watch_hr | Pixel Watch staleness >120s | 3.3x | Watch out of BLE range |
| ir_body_heat | IR brightness drop >15 units | 6.7x | Body left IR field |

**Secondary signals:** midi_active (OXI One MIDI clock, 45x), operator_face (InsightFace SCRFD, 9x), desktop_active (Hyprland focus, 7.5x), ambient_energy (Blue Yeti room noise, 3x), room_occupancy (multi-camera YOLO, 4.25x), vad_speech (Silero, 4x), bt_phone_connected (2.33x), phone_kde_connected (3.2x).

**Keyboard input:** `EvdevInputBackend` reads `/dev/input/event*` directly (Keychron, Logitech USB Receiver), filtering virtual devices (RustDesk UInput, mouce-library-fake-mouse, ydotoold) by name. Replaces logind-based detection which was polluted by Claude Code subprocess activity.

**Contact mic:** Cortado MKIII on the L-12 mixer XLR input (CH2, AUX1; 48V phantom). Captured via `pw-cat --record --target "Contact Microphone"` at 16kHz mono int16. DSP: RMS energy, onset detection, spectral centroid, autocorrelation, gesture classification. Provides `desk_activity` (idle/typing/tapping/drumming/active), `desk_energy`, `desk_onset_rate`, `desk_tap_gesture`. (Historical: prior to the 24c retirement 2026-05-03, the contact mic landed on PreSonus Studio 24c Input 2.)

**Prediction monitor:** `agents/reverie_prediction_monitor.py` (1-min systemd timer) tracks 6 behavioral predictions + live operational metrics. Grafana dashboard at `localhost:3001/d/reverie-predictions/`. Prometheus scrape at 30s. Metrics at `/api/predictions/metrics`.

## Citation Graph Mirror

`agents/publication_bus/datacite_mirror.py` — daily GraphQL mirror of the operator's authored works from DataCite Commons (`https://api.datacite.org/graphql`, public + unauthenticated). Snapshots persist to `~/hapax-state/datacite-mirror/{iso-date}.json`; `compute_diff()` returns added/removed DOIs and citation-count deltas. systemd unit `hapax-datacite-mirror.{service,timer}` runs daily at 04:00 UTC. Operator action: set `HAPAX_OPERATOR_ORCID` env var (e.g. via `~/.config/hapax/datacite-mirror.env`) — daemon no-ops with `outcome=no-orcid-configured` until configured. Phase 2 (cred-gated): graph_publisher mints version-DOI under "Hapax Citation Graph" concept-DOI when diff is non-empty.

`agents/attribution/datacite_graphql_snapshot.py` — nightly snapshot of the citation network AROUND specific DOI/SWHID/ORCID nodes (distinct from the operator-authored mirror above). systemd unit `hapax-datacite-snapshot.{service,timer}` at 03:30 UTC. Snapshots persist to `~/hapax-state/attribution/datacite-snapshot-{iso-date}.json`. Phase 1 ships DOI tier; SWHID + ORCID tiers in Phase 2.

## V5 Publication Bus

Per V5 weave §2.1 PUB-P0-B keystone (`agents/publication_bus/publisher_kit/`). Three load-bearing invariants every publisher enforces in the superclass `publish()` method: AllowlistGate, legal-name-leak guard (skipped for `requires_legal_name=True` surfaces like Zenodo creators), Prometheus Counter `hapax_publication_bus_publishes_total`. Subclass shape ~80 LOC: surface metadata as ClassVar + `_emit()` override.

**Surface registry** (`agents/publication_bus/surface_registry.py`): 17-surface dict (V5 canonical 14 + `osf-prereg` + `zenodo-refusal-deposit` extensions). Three tiers — `FULL_AUTO` (daemon-side end-to-end after one-time credential bootstrap), `CONDITIONAL_ENGAGE` (one-time human action, e.g. Playwright login or session-cookie extraction), `REFUSED` (subclass exists to record refusal, never to attempt publication). Helpers `is_engageable()`, `refused_surfaces()`, `auto_surfaces()`.

**Concrete publishers shipped:**
- `BridgyPublisher` (`bridgy-webmention-publish`) — POSSE webmention to brid.gy/publish/webmention
- `RefusalAnnexPublisher` (`marketing-refusal-annex`) — local file write to `~/hapax-state/publications/refusal-annex-{slug}.md`
- `OmgLolWeblogPublisher` (`omg-lol-weblog-bearer-fanout`) — wraps `OmgLolClient.set_entry`
- `InternetArchiveS3Publisher` (`internet-archive-ias3`) — bare-`requests` PUT against `https://s3.us.archive.org/{item}/{filename}` with `LOW {access}:{secret}` header
- `BlueskyPublisher` (`bluesky-atproto-multi-identity`) — 2-step XRPC auth (`createSession` → `createRecord`)
- `OSFPreregPublisher` (`osf-prereg`) — bare-`requests` POST against `https://api.osf.io/v2/registrations/` with Bearer PAT; JSON:API envelope. Distinct from the legacy `agents/osf_preprint_publisher/` (preprints `/v2/preprints/`) — preregistration is a different OSF deposit type
- `PhilArchivePublisher` (`philarchive-deposit`) — bare-`requests` form-POST to `philarchive.org/deposit` with session cookie; `requires_legal_name=True` because PhilArchive author field uses formal name per ORCID linkage. Constitutional Brief + Manifesto class artefacts route here per V5 weave §2.2
- `RefusalBriefPublisher` (`zenodo-refusal-deposit`) — Zenodo deposit specialized for the refusal-brief deposit type per drop-5 fresh-pattern §2; carries refusal-shaped `RelatedIdentifier` edges (`IsRequiredBy` to target surface, `IsObsoletedBy` to sibling refusals) so refusal nodes participate in the DataCite citation graph
- `BandcampRefusedPublisher` / `DiscogsRefusedPublisher` / `RymRefusedPublisher` / `CrossrefEventDataRefusedPublisher` — REFUSED tier; `__init_subclass__` auto-wires empty AllowlistGate so any `publish()` call records refusal-as-data via the canonical refusal_brief log

**Helper modules:**
- `RelatedIdentifier` graph (`agents/publication_bus/related_identifier.py`) — DataCite RelatedIdentifier dataclass + 6 RelationType + 7 IdentifierType, `to_zenodo_dict()` for snake_case Zenodo REST
- `RefusalFooterInjector` (`agents/publication_bus/refusal_footer_injector.py`) — auto-injects `NON_ENGAGEMENT_CLAUSE_LONG` into deposit descriptions; reads recent refusals from the canonical log
- `omg_rss_fanout` (`agents/publication_bus/omg_rss_fanout.py`) — cross-weblog fanout helper composes multiple `OmgLolWeblogPublisher` instances
- `orcid_verifier` (`agents/publication_bus/orcid_verifier.py`) — daily verification of operator's ORCID record vs minted concept-DOIs (no auth; ORCID public API)
- `compose_refusal_related_identifiers()` + `scan_refused_cc_tasks()` (in `agents/publication_bus/refusal_brief_publisher.py`) — refusal-as-data graph composition + vault scanner (regex frontmatter parser, no PyYAML dep) for the daemon path that mints refusal-deposit DOIs

**Marketing surfaces** (`agents/marketing/`):
- `RefusalAnnex` series (renderer + cross-linker) writes per-annex markdown to `~/hapax-state/publications/`. 8 seed annex slugs (`declined-bandcamp`, `declined-alphaxiv`, etc.). Cross-linker resolves slug ↔ cc-task ID for the operator dashboard.

**Cold-contact path** (`agents/cold_contact/`):
- `candidate_registry` — Pydantic CandidateEntry + 14-vector AUDIENCE_VECTORS controlled vocabulary; **no email/telephone fields by design** (direct outreach is REFUSED per family-wide stance)
- `orcid_validator` — validates each entry against ORCID public API
- `graph_touch_policy` — citation-graph-only touch path; ≤5 candidates/deposit, ≤3/year/candidate cadence cap, JSONL touch log at `~/hapax-state/cold-contact/touches.jsonl`

**SWH attribution** (`agents/attribution/`):
- `swh_register` — Software Heritage save-origin endpoint (unauthenticated)
- `swh_archive_daemon` — daemon orchestrates trigger → poll → resolve over HAPAX_REPOS; persists `~/hapax-state/attribution/swhids.yaml`
- `citation_feature` — pulls BibTeX from SWH Citation Feature endpoint per resolved SWHID
- `citation_cff_updater` — adds/replaces `identifiers: [{type: swh}]` in CITATION.cff
- `bibtex_collector` — orchestrates SWHIDs → BibTeX → `~/hapax-state/attribution/bibtex.bib`

**Self-federate** (`agents/self_federate/`):
- `rss_validator` — weekly Sunday 03:00 UTC validation of Hapax weblog RSS feed (https://hapax.weblog.lol/rss); DOI cross-link extraction via Crossref-spec regex

## Key Modules

- **`shared/config.py`** — Model aliases (`fast`→gemini-flash, `balanced`→claude-sonnet, `local-fast`/`coding`/`reasoning`→TabbyAPI Command-R 35B EXL3 5bpw), `get_model_adaptive()` for stimmung-aware routing, LiteLLM/Qdrant clients
- **`shared/working_mode.py`** — Reads `~/.cache/hapax/working-mode` (research/rnd). CLI: `hapax-working-mode`
- **`shared/notify.py`** — `send_notification()` for ntfy + desktop
- **`shared/frontmatter.py`** — Canonical frontmatter parser (never duplicate this)
- **`shared/dimensions.py`** — 11 profile dimensions. Sync agents produce behavioral facts only.
- **`shared/governance/consent.py`** — `ConsentContract`, `ConsentRegistry`, `contract_check()`. Companion modules: `shared/governance/consent_context.py` (contextvar registry), `consent_gate.py` (capability filtering), `revocation.py` (contract purge).
- **`shared/agent_registry.py`** — `AgentManifest` (4-layer schema), query by category/capability/RACI
- **`shared/telemetry.py`** — `hapax_span` / `hapax_event` / `hapax_score` for Langfuse instrumentation. `hapax_span` uses an `ExitStack` so setup failures yield a no-op span and caller exceptions propagate cleanly; do not refactor it to a single try/except wrapping the yield. Metadata values must be strings; non-string values are dropped by langfuse's `propagate_attributes`.

## Voice Grounding Research Continuity

Research state persists in `agents/hapax_daimonion/proofs/RESEARCH-STATE.md`. After any session with research decisions or implementation progress, update this file before ending. When the operator says "refresh research context" or "update research context", read the state file and selectively read the tier-2 documents it references.

## Prompt Compression Benchmark

`scripts/benchmark_prompt_compression_b6.py` is the reference harness for the §4.2 latency benchmark from the prompt-compression research plan. Hits TabbyAPI directly at `http://localhost:5000` so the LiteLLM gateway does not pollute latency measurement, reads `prompt_time` / `completion_time` / `total_time` from the per-response `usage` block. Toggles full vs compressed system prompt via `agents.hapax_daimonion.persona.system_prompt`. Results land in `~/hapax-state/benchmarks/prompt-compression/`.

## Composition Ladder Protocol (hapax_daimonion)

Bottom-up building discipline for the hapax_daimonion type system. 10 layers (L0–L9). 7-dimension test matrix per layer. Gate rule: no new composition on layer N unless N-1 is matrix-complete. See `agents/hapax_daimonion/LAYER_STATUS.yaml` for current status and `tests/hapax_daimonion/test_type_system_matrix*.py` for the matrix tests.

**3-question heuristic** before every change:
1. What layer does this touch?
2. Is the layer below matrix-complete? (If no → fix that first)
3. Which dimensions does this test cover? (Update LAYER_STATUS.yaml)
