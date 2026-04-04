# CLAUDE.md

Externalized executive function infrastructure. LLM agents handle cognitive work (tracking open loops, maintaining context, surfacing what needs attention) for a single operator on a single workstation. Single-operator is a constitutional axiom — no auth, no roles, no multi-user code anywhere.

Shared conventions (uv, ruff, testing, git workflow, pydantic-ai) are in the workspace `CLAUDE.md` — this file covers council-specific details only.

## Architecture

**Filesystem-as-bus**: Agents read/write markdown files with YAML frontmatter on disk. A reactive engine (inotify) watches for changes and cascades downstream work.

**Three tiers**:
- **Tier 1** — Interactive interfaces (hapax-logos Tauri native app, waybar GTK4 status bar, VS Code extension)
- **Tier 2** — LLM-driven agents (pydantic-ai, routed through LiteLLM at :4000). Local: TabbyAPI serves Qwen3.5-35B-A3B (EXL3) on `:5000` for `local-fast`/`coding`/`reasoning`. DMN pulse calls TabbyAPI directly; no Ollama inference fallback (VRAM coexistence constraint). Cloud: Claude Sonnet/Opus for `balanced`/governance, Gemini Flash for `fast`/vision.
- **Tier 3** — Deterministic agents (sync, health, maintenance — no LLM calls)

**Reactive engine** (`logos/engine/`): inotify watcher → 14 rules → phased execution (deterministic first, then LLM semaphore-bounded at max 2 concurrent).

**Infrastructure**: Docker Compose for databases/proxies (13 containers), systemd user units for all application services. No process-compose in production. See `systemd/README.md` for boot sequence, resource isolation, and recovery chain.

**Key services**: `hapax-secrets` (credentials) → `logos-api` (:8051) → `waybar` (GTK4 status bar) → `tabbyapi` (GPU, EXL3 inference :5000) → `hapax-daimonion` (GPU STT, CPU TTS) → `visual-layer-aggregator` → `studio-compositor` (GPU). 34 timers for sync, health, backups. Archival pipeline (audio/video recording, classification, RAG ingest) disabled — see `systemd/README.md § Disabled Services`.

## Design Language

`docs/logos-design-language.md` is the authority document for all visual surfaces. It governs color (§3), typography (§1.6), spatial model (§4), animation (§6), mode switching (§2), and scope (§11). All component colors must use CSS custom properties (`var(--color-*)`) or Tailwind classes — no hardcoded hex except detection overlays (§3.8). `docs/logos-ui-reference.md` governs region content (what appears at each depth). Classification inspector (`C` key) is exempt from density rules — diagnostic tool with theme-aware colors.

## Logos API

FastAPI on `:8051`. `uv run logos-api` to start. Containers: `docker compose up -d`.

## Orientation Panel

Replaces the old Goals + Briefing sidebar widgets with a unified orientation surface. Reads vault-native goal notes (YAML frontmatter `type: goal`), assembles per-domain state (research, management, studio, personal, health), infers session context from telemetry, and renders with stimmung-responsive density modulation.

**Key files:**
- `logos/data/vault_goals.py` — Scans Obsidian vault for `type: goal` notes, computes staleness from mtime
- `logos/data/session_inference.py` — Infers session context from git, IR, stimmung, sprint telemetry
- `logos/data/orientation.py` — Assembles domain states, conditional LLM narrative gating
- `logos/api/routes/orientation.py` — `GET /api/orientation` (slow cache tier, 5 min)
- `logos/api/routes/vault.py` — `GET /api/vault/related` (embedding similarity search)
- `config/domains.yaml` — Domain registry mapping life domains to data sources and telemetry
- `hapax-logos/src/components/sidebar/OrientationPanel.tsx` — Frontend component

**Domain ranking:** blocked gates > stale P0 goals > active > stale > dormant. Sprint progress attached to research domain only.

**Spec:** `docs/superpowers/specs/2026-04-01-orientation-panel-design.md`

## Obsidian Integration

Personal vault at `~/Documents/Personal/` (kebab-case dirs, kebab-case filenames). PARA structure: `00-inbox`, `10-meta`, `20-personal`, `20-projects`, `30-areas`, `40-calendar`, `50-templates`, `50-resources`. Syncs to phone via Obsidian Sync.

**obsidian-hapax plugin** (`obsidian-hapax/`): Context panel in right sidebar. Resolves active note to a NoteKind (Measure, Gate, SprintSummary, PosteriorTracker, Research, Concept, Briefing, Nudges, Goal, Daily, Management, Studio, Unknown) and renders domain-appropriate context from Logos API. Mobile support via LAN IP auto-detect (`Platform.isMobile`). 8s request timeout.

**Vault-native goal notes:** `type: goal` frontmatter with `domain`, `status`, `priority`, `sprint_measures`, `depends_on`. Template at `50-templates/tpl-goal.md`. FileClass at `10-meta/fileclass/goal.md`. QuickAdd "New Goal" command creates in `20-projects/hapax-goals/`.

**Agents:**
- `agents/obsidian_sync.py` — Batch vault → RAG sync (6h timer). Extracts frontmatter, writes to `rag-sources/obsidian/`. Also extracts management cadence from person notes → `~/hapax-state/management/people-cadence.json`.
- `agents/vault_context_writer.py` — Writes working context (branch, commits, sprint, stimmung) to daily note `## Log` via Obsidian Local REST API (15-min timer).
- `agents/vault_canvas_writer.py` — Generates JSON Canvas goal dependency map at `20-projects/hapax-goals/goal-map.canvas`.
- `agents/sprint_tracker.py` — Reads/writes sprint measure vault notes bidirectionally. 5-min timer.

**Plugins (11):** templater-obsidian, obsidian-tasks-plugin, periodic-notes, calendar, quickadd, obsidian-linter, dataview, obsidian-hapax, metadata-menu, obsidian-local-rest-api, obsidian-kanban.

**Linter rules:** yaml-title, yaml-key-sort, yaml-timestamp (ISO), format-yaml-array, add-blank-line-after-yaml, consecutive-blank-lines, heading-blank-lines, line-break-at-document-end, remove-multiple-spaces, space-after-list-markers. Lint-on-save enabled. Ignores `50-templates/` and `sprint/`.

**Mobile:** Plugin uses `http://192.168.68.114:8051` on mobile (LAN IP). Firewall allows LAN (`192.168.68.0/22`) and Tailscale (`100.64.0.0/10`) to port 8051.

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
- `hapax-logos/src/components/terrain/CommandRegistryBridge.tsx` — Bridges studio/detection contexts
- `hapax-logos/src/lib/commandBridge.ts` — Tauri event bridge for command relay
- `hapax-logos/src-tauri/src/commands/relay.rs` — Rust WebSocket relay server (:8052)

**State mirrors:** The provider maintains synchronous state mirrors updated eagerly by action wrappers. This ensures `query()` returns post-execution state without waiting for React re-render. Mirrors sync from React state on each render.

**Spec:** `docs/superpowers/specs/2026-03-26-logos-command-registry-design.md`

## Tauri-Only Runtime

Logos is a Tauri 2 native app. The frontend speaks **only IPC** — zero browser `fetch()` calls. All API communication goes through `invoke()` to Rust commands, which proxy to FastAPI at `:8051` internally.

**Key services inside Tauri process:**
- **IPC commands** — 60+ invoke handlers (health, state, studio, governance, proxy passthrough)
- **SSE bridge** — Rust subscribes to FastAPI SSE streams, re-emits as Tauri events (`commands/streaming.rs`)
- **Command relay** — WebSocket server on `:8052` for MCP/voice (`commands/relay.rs`)
- **HTTP frame server** — Axum on `:8053` serves visual surface JPEG frames (`visual/http_server.rs`)

**Visual surface (Hapax Reverie):** A standalone binary (`hapax-imagination`) runs as a systemd user service, rendering dynamic shader graphs via wgpu. Python compiles effect presets (`agents/effect_graph/wgsl_compiler.py`) into WGSL execution plans that the Rust `DynamicPipeline` hot-reloads from `/dev/shm/hapax-imagination/pipeline/`. The permanent vocabulary graph runs 8 passes: `noise → rd → color → drift → breath → feedback → content_layer → postprocess`. Both `rd` and `feedback` are temporal (`@accum_rd`, `@accum_fb`) enabling reaction-diffusion evolution and dwelling traces (Bachelard Amendment 2). Per-node shader params flow from Python visual chain → `uniforms.json` → Rust per-frame override bridge. Visual chain technique names match vocabulary node IDs (`noise`, `rd`, `color`, `fb`, `post`). **Param naming**: visual chain writes `{node_id}.{param_name}` (e.g., `noise.amplitude`, `rd.feed_rate`); param names must match the param_order extracted from WGSL Params structs (no `u_` prefix). The Reverie mixer (`agents/reverie/`) only writes non-zero chain deltas to uniforms.json — zero deltas would overwrite vocabulary defaults. **Multiplicative shader params** (`colorgrade.brightness`, `colorgrade.saturation`, `postprocess.master_opacity`) must default to 1.0 in the vocabulary preset, not 0.0, or the pipeline outputs black. 9 expressive dimensions in the GPU uniform buffer: intensity, tension, depth, coherence, spectral_color, temporal_distortion, degradation, pitch_displacement, diffusion. The DMN evaluative tick reads rendered frames via gemini-flash (multimodal) and writes observations for reverberation detection (Amendment 4). Frames written to `/dev/shm/hapax-visual/frame.jpg` via turbojpeg. Content layer supports per-slot immensity entry and continuation-aware crossfade. The `VisualSurface` React component fetches frames at 10fps from `:8053`. Tauri communicates via UDS (`$XDG_RUNTIME_DIR/hapax-imagination.sock`). The winit window is independently positioned (multi-monitor, fullscreen, borderless, always-on-top).

**NVIDIA + Wayland:** webkit2gtk 2.50.6 has a syncobj protocol bug that crashes the app on native Wayland with NVIDIA ([gtk#8056](https://gitlab.gnome.org/GNOME/gtk/-/issues/8056), [tauri#10702](https://github.com/tauri-apps/tauri/issues/10702)). Workaround: `__NV_DISABLE_EXPLICIT_SYNC=1` (set in systemd unit and `.envrc`). See `docs/issues/tauri-wayland-protocol-error.md`.

**Dev workflow:** `pnpm tauri dev` is the only dev path. Vite serves assets to the Tauri webview only — no proxy, no exposed API.

## Unified Semantic Recruitment

Everything that appears — visual content, tool invocation, vocal expression, destination routing — is recruited through a single `AffordancePipeline`. No bypass paths. Spec: `docs/superpowers/specs/2026-04-02-unified-semantic-recruitment-design.md`.

**Mechanism:** Impingement → embed narrative → cosine similarity against Qdrant `affordances` collection → score (0.50×similarity + 0.20×base_level + 0.10×context_boost + 0.20×thompson) → governance veto → recruited capabilities activate. Thompson sampling (optimistic prior: Beta(2,1)) + Hebbian associations learn from outcomes across sessions. Recruited candidates record success (pipeline threshold IS the quality gate); activation level drives response intensity via slot opacity. Activation state persisted every 5 minutes + on shutdown.

**Taxonomy (6 domains):** perception, expression, recall, action, communication, regulation. Each capability has a Gibson-verb affordance description (15-30 words, cognitive function not implementation). Three-level Rosch structure: Domain (organizational) → Affordance (embedded in Qdrant) → Instance (metadata payload).

**Imagination produces intent, not implementation.** `ImaginationFragment` carries: narrative, dimensions (9 canonical: intensity, tension, depth, coherence, spectral_color, temporal_distortion, degradation, pitch_displacement, diffusion), material (water/fire/earth/air/void), salience. No `content_references` — the narrative IS the only retrieval query.

**Content recruitment:** Camera feeds, text rendering, knowledge queries are registered affordances. Only appear when the pipeline recruits them based on semantic match against imagination narrative. `ContentCapabilityRouter` handles activation. No unconditional `update_camera_sources()`.

**Tool recruitment:** 31 tools registered with Gibson-verb descriptions. `ToolRecruitmentGate` converts operator utterances to impingements, pipeline selects tools per-turn, LLM sees only recruited tools. Outcomes recorded for Thompson sampling learning.

**Destinations:** `OperationalProperties.medium` field ("auditory", "visual", "textual", "notification"). `_infer_modality()` reads declared medium, not capability name substrings. Pipeline returns multi-modal candidates naturally.

**Generative substrate:** The vocabulary shader graph always runs (8-pass: noise→rd→color→drift→breath→feedback→content→post). Not registered as a capability. Not recruited. The DMN is a permanently running generative process — recruitment modulates it, content composites into it.

**Novel discovery:** `capability_discovery` meta-affordance matches boredom/curiosity impingements when no capability matches an intention. Handler stub for web search/package scanning. `consent_required=True`.

**Learning persistence:** Activation state (Thompson alpha/beta + Hebbian associations) saved to `~/.cache/hapax/affordance-activation-state.json` on daemon shutdown, loaded on startup.

## Council-Specific Conventions

- Hypothesis for property-based algebraic proofs.
- Working mode file: `~/.cache/hapax/working-mode` (research/rnd). CLI: `hapax-working-mode`.
- Safety: LLMs prepare, humans deliver. Never generate feedback language or coaching recommendations about individual team members.

## Axiom Governance

5 axioms (3 constitutional, 2 domain) enforced via `shared/axiom_*.py`, `shared/consent.py`, and commit hooks:

| Axiom | Weight | Constraint |
|-------|--------|------------|
| single_user | 100 | One operator. No auth, roles, or collaboration features. |
| executive_function | 95 | Zero-config agents, errors include next actions, routine work automated. |
| corporate_boundary | 90 | Work data stays in employer systems. Home system = personal + management-practice only. |
| interpersonal_transparency | 88 | No persistent state about non-operator persons without active consent contract. |
| management_governance | 85 | LLMs prepare, humans deliver. No generated feedback/coaching about individuals. |

T0 violations blocked by SDLC hooks. Definitions in `axioms/registry.yaml`, implications in `axioms/implications/`, consent contracts in `axioms/contracts/`.

## SDLC Pipeline

LLM-driven lifecycle via GitHub Actions: Triage → Plan → Implement → Adversarial Review (3 rounds max) → Axiom Gate → Auto-merge. Scripts in `scripts/`, workflows in `.github/workflows/`. All scripts support `--dry-run`. Observability via `profiles/sdlc-events.jsonl` + Langfuse traces. Agent PRs only on `agent/*` branches with `agent-authored` label.

## Claude Code Hooks (`hooks/scripts/`)

PreToolUse hooks enforce branch discipline and safety at the tool-call level:

| Hook | Gates | Blocks when |
|------|-------|-------------|
| `work-resolution-gate.sh` | Edit, Write | Feature branch with commits but no PR; on main with open PRs whose branch is local |
| `no-stale-branches.sh` | Bash | **Branch creation:** any unmerged branches exist. **Destructive commands** (`git reset --hard`, `git checkout .`, `git branch -f`, `git worktree remove`): on a feature branch with commits ahead of main |
| `push-gate.sh` | Bash | Push without passing tests |
| `pii-guard.sh` | Edit, Write | PII patterns in file content |
| `axiom-commit-scan.sh` | Bash | Commit messages violating axiom patterns |
| `session-context.sh` | Bash | Advisory: session context and relay status |

Destructive command detection strips quoted strings before matching to prevent false positives from commit messages that discuss git commands.

## IR Perception (Pi NoIR Edge Fleet)

3 Raspberry Pi 4s with Pi Camera Module 3 NoIR under 850nm IR flood illumination. Each runs `hapax-ir-edge` daemon: YOLOv8n (ONNX Runtime) person detection + NIR hand thresholding + adaptive screen detection. Captures via `rpicam-still`, POSTs structured JSON to council every ~3s.

**Pi fleet:**
- **Pi-1** (hapax-pi1, 192.168.68.78) — ir-desk, co-located with C920-desk
- **Pi-2** (hapax-pi2, 192.168.68.52) — ir-room, co-located with C920-room
- **Pi-4** (hapax-pi4, 192.168.68.53) — sentinel (health monitor, watch backup)
- **Pi-5** (hapax-pi5, 192.168.68.72) — rag-edge (document preprocessing)
- **Pi-6** (hapax-pi6, 192.168.68.74) — sync-hub + ir-overhead, co-located with C920-overhead

**IR data flow:** Pi daemon → `POST /api/pi/{role}/ir` (`logos/api/routes/pi.py`) → `~/hapax-state/pi-noir/{role}.json` → `ir_presence` backend (FAST tier, 14 signals) → perception engine → perception-state.json.

**Health/observability:** All 5 Pis report heartbeats every 60s via `hapax-heartbeat.timer` → `POST /api/pi/{hostname}/heartbeat` → `~/hapax-state/edge/{hostname}.json`. Health monitor `check_pi_fleet()` validates freshness, service status, CPU temp, memory, disk. Failures feed into stimmung health dimension and ntfy alerts.

**Key files:**
- `pi-edge/` — Edge daemon + heartbeat code (deployed to each Pi at `~/hapax-edge/`)
- `pi-edge/ir_report.py` — Report building (extracted from daemon)
- `shared/ir_models.py` — Shared Pydantic schema (IrDetectionReport, IrBiometrics with face_detected)
- `agents/hapax_daimonion/backends/ir_presence.py` — Perception backend (multi-Pi fusion, 14 signals)
- `agents/hapax_daimonion/backends/contact_mic_ir.py` — Cross-modal fusion (IR hand zone + contact mic DSP)
- `agents/hapax_daimonion/ir_signals.py` — State file reader
- `agents/health_monitor.py` — `PI_FLEET` dict defines expected services per Pi

**Inference:** ONNX Runtime preferred (130ms, preserves fine-tuned precision), TFLite fallback. Model: YOLOv8n fine-tuned on 30 NIR studio frames (`best.onnx`). **Person detection currently non-functional** — 30-frame training dataset insufficient for NIR domain. Retraining planned (500+ frames, two-stage COCO→FLIR→NIR transfer). See `docs/superpowers/specs/2026-03-31-ir-perception-remediation-design.md`.

**Signal quality (remediated 2026-03-31):**
- Hand detection: max_area_pct=0.25 rejects frame-spanning false positives, aspect ratio 0.3–3.0
- Screen detection: adaptive threshold (mean_brightness × 0.3) instead of fixed value
- rPPG: gated on face landmarks actually available (no phantom heart rates)
- Biometrics: face_detected field in IrBiometrics for observability

**Fusion logic:** Person detection = any() across Pis. Gaze/biometrics prefer desk Pi (face-on). Hand activity + hand zone prefer overhead Pi. Staleness cutoff: 10s. **Person detection currently non-functional** (30-frame training set) — `ir_person_detected` set to `None` (neutral) to prevent false-negative Bayesian poisoning. `ir_hand_activity` is reliable and wired into presence engine as a strong positive-only signal.

**14 signals:** ir_person_detected, ir_person_count, ir_motion_delta, ir_gaze_zone, ir_head_pose_yaw, ir_posture, ir_hand_activity, ir_hand_zone, ir_screen_looking, ir_drowsiness_score, ir_blink_rate, ir_heart_rate_bpm, ir_heart_rate_conf, ir_brightness. All 14 flow to perception-state.json.

**Cross-modal fusion:** `contact_mic_ir.py` provides `_classify_activity_with_ir()` — turntable+sliding=scratching, mpc-pads+tapping=pad-work. Function tested but not yet wired into contact mic capture loop.

## Bayesian Presence Detection

`PresenceEngine` (`agents/hapax_daimonion/presence_engine.py`) fuses 14 heterogeneous signals into a single `presence_probability` posterior via Bayesian log-odds update. Hysteresis state machine: PRESENT (≥0.7 for 2 ticks), UNCERTAIN, AWAY (<0.3 for 24 ticks).

**Signal design principle — positive-only for unreliable sensors:** Signals where absence is ambiguous (face not visible, silence, no desktop focus change, broken IR person detection) contribute `True` when detected but `None` (neutral, skipped by Bayesian update) when absent. Only structurally reliable signals (keyboard from logind, BT device connection) use bidirectional evidence.

**Primary signals (active during desk work):**

| Signal | Source | LR (True) | Type |
|--------|--------|-----------|------|
| desk_active | Contact mic Cortado MKIII via pw-cat | 18x | positive-only |
| keyboard_active | evdev raw HID (physical Keychron + Logitech) | 17x | bidirectional |
| ir_hand_active | Pi NoIR hand detection (motion-gated >0.05) | 8.5x | positive-only |

**Absence signals (drive presence DOWN when operator leaves):**

| Signal | Source | LR (False) | Condition |
|--------|--------|-----------|-----------|
| keyboard_active | evdev idle >5min | 5.6x against | No physical keystrokes for 300s |
| watch_hr | Pixel Watch HR staleness >120s | 3.3x against | Watch out of BLE range |
| ir_body_heat | IR brightness drop >15 units | 6.7x against | Body left IR camera field |

**Secondary signals:**

| Signal | Source | LR (True) | Type |
|--------|--------|-----------|------|
| midi_active | OXI One MIDI clock | 45x | bidirectional |
| operator_face | InsightFace SCRFD face ReID | 9x | positive-only |
| desktop_active | Hyprland window focus | 7.5x | positive-only |
| ambient_energy | Blue Yeti room noise floor via pw-cat | 3x | positive-only |
| room_occupancy | Multi-camera YOLO person | 4.25x | positive-only |
| vad_speech | Silero VAD | 4x | positive-only |
| ir_body_heat | IR brightness delta (body-heat proxy) | 4.67x | bidirectional |
| bt_phone_connected | BT active connection (not paired list) | 2.33x | positive-only |
| watch_connected | Pixel Watch BLE | — | positive-only |
| phone_kde_connected | KDE Connect WiFi | 3.2x | bidirectional |
| ir_person_detected | Pi NoIR YOLOv8n | 9x | positive-only (broken, always None) |
| speaker_is_operator | pyannote embedding | 47.5x | not wired (no backend) |

**Keyboard input:** `EvdevInputBackend` reads physical devices directly via `/dev/input/event*` (Keychron, Logitech USB Receiver), filtering virtual devices (RustDesk UInput, mouce-library-fake-mouse, ydotoold) by name. Replaces logind-based detection which was polluted by Claude Code subprocess activity. Falls back to logind if evdev unavailable.

**Contact mic:** Cortado MKIII on PreSonus Studio 24c Input 2 (48V phantom). Captured via `pw-cat --record --target "Contact Microphone"` at 16kHz mono int16. DSP pipeline: RMS energy, onset detection, spectral centroid, autocorrelation, gesture classification. Provides `desk_activity` (idle/typing/tapping/drumming/active), `desk_energy`, `desk_onset_rate`, `desk_tap_gesture`.

**Ambient audio:** Blue Yeti USB microphone captured via `pw-cat --record --target "Yeti Stereo Microphone"` at 16kHz. Smoothed RMS energy as room occupancy proxy — occupied rooms have higher ambient noise floor than empty rooms.

**Watch HR staleness:** Bidirectional signal. Fresh HR (<30s mtime) = presence evidence. Stale 30–120s = neutral (sync gap). Very stale >120s = absence evidence (watch out of BLE range, operator physically far away).

**IR brightness delta:** Rolling 30-sample average of `ir_brightness` from Pi NoIR fleet. Rise >15 units = body arrived (skin reflects 850nm). Drop >15 = body left. Bidirectional body-heat proxy.

**Prediction monitor:** `agents/reverie_prediction_monitor.py` (1-min systemd timer) tracks 6 behavioral predictions + live operational metrics. Grafana dashboard at `localhost:3001/d/reverie-predictions/` (16 panels). Prometheus scrape at 30s. Metrics at `/api/predictions/metrics`.

**Debug/capture tools:**
- `kill -USR1 $(pgrep -f hapax_ir_edge)` — saves greyscale frame to `/tmp/ir_debug_{role}.jpg`
- `--save-frames N` — saves every Nth frame to `~/hapax-edge/captures/` for training data collection

**Face landmarks currently disabled** — fdlite incompatible with NumPy 2.x on Trixie (`np.math` removed). Degrades gracefully. Gaze, posture, EAR, drowsiness all zero until fixed.

## Key Modules

- **`shared/config.py`** — Model aliases (`fast`→gemini-flash, `balanced`→claude-sonnet, `local-fast`/`coding`/`reasoning`→TabbyAPI Qwen3.5-35B-A3B), `get_model_adaptive()` for stimmung-aware routing, LiteLLM/Qdrant clients, CPU embedding via nomic-embed-cpu
- **`shared/working_mode.py`** — Reads `~/.cache/hapax/working-mode` (research/rnd). CLI: `hapax-working-mode`
- **`shared/notify.py`** — `send_notification()` for ntfy + desktop
- **`shared/frontmatter.py`** — Canonical frontmatter parser (never duplicate this)
- **`shared/dimensions.py`** — 11 profile dimensions. Sync agents produce behavioral facts only.
- **`shared/consent.py`** — `ConsentContract`, `ConsentRegistry`, `contract_check()`
- **`shared/agent_registry.py`** — `AgentManifest` (4-layer schema), query by category/capability/RACI

## Voice Grounding Research Continuity

Research state persists in `agents/hapax_daimonion/proofs/RESEARCH-STATE.md`. After any session with research decisions or implementation progress on the voice grounding project, update this file before ending. When the operator says "refresh research context" or "update research context", read the state file and selectively read the tier-2 documents it references.

## Composition Ladder Protocol (hapax_daimonion)

Bottom-up building discipline for the hapax_daimonion type system. 10 layers (L0–L9), all proven. 7-dimension test matrix per layer. Gate rule: no new composition on layer N unless N-1 is matrix-complete. See `agents/hapax_daimonion/LAYER_STATUS.yaml` for current status and `tests/hapax_daimonion/test_type_system_matrix*.py` for the 192 matrix tests.

**3-question heuristic** before every change:
1. What layer does this touch?
2. Is the layer below matrix-complete? (If no → fix that first)
3. Which dimensions does this test cover? (Update LAYER_STATUS.yaml)
