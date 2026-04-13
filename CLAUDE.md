# CLAUDE.md

Externalized executive function infrastructure. LLM agents handle cognitive work (tracking open loops, maintaining context, surfacing what needs attention) for a single operator on a single workstation. Single-operator is a constitutional axiom — no auth, no roles, no multi-user code anywhere.

Shared conventions (uv, ruff, testing, git workflow, pydantic-ai) are in the workspace `CLAUDE.md` — this file covers council-specific details only.

## Architecture

**Filesystem-as-bus**: Agents read/write markdown files with YAML frontmatter on disk. A reactive engine (inotify) watches for changes and cascades downstream work.

**Three tiers**:
- **Tier 1** — Interactive interfaces (hapax-logos Tauri native app, waybar GTK4 status bar, VS Code extension)
- **Tier 2** — LLM-driven agents (pydantic-ai, routed through LiteLLM at :4000). Local: TabbyAPI serves Qwen3.5-9B (EXL3) on `:5000` for `local-fast`/`coding`/`reasoning`. No Ollama inference — Ollama is GPU-isolated (`CUDA_VISIBLE_DEVICES=""`) and used only for CPU embedding (`nomic-embed-cpu`). `qwen3:8b` deleted from Ollama and LiteLLM. See `systemd/README.md § Ollama GPU Isolation`. Cloud: Claude Sonnet/Opus for `balanced`/governance, Gemini Flash for `fast`/vision.
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

**Visual surface (Hapax Reverie):** A standalone binary (`hapax-imagination`) runs as a systemd user service, rendering dynamic shader graphs via wgpu. Python compiles effect presets (`agents/effect_graph/wgsl_compiler.py`) into WGSL execution plans that the Rust `DynamicPipeline` hot-reloads from `/dev/shm/hapax-imagination/pipeline/`. The permanent vocabulary graph runs 8 passes: `noise → rd → color → drift → breath → feedback → content_layer → postprocess`. Both `rd` and `feedback` are temporal (`@accum_rd`, `@accum_fb`) enabling reaction-diffusion evolution and dwelling traces (Bachelard Amendment 2). Per-node shader params flow from Python visual chain → `uniforms.json` → Rust per-frame override bridge. Visual chain technique names match vocabulary node IDs (`noise`, `rd`, `color`, `fb`, `post`). **Param naming**: visual chain writes `{node_id}.{param_name}` (e.g., `noise.amplitude`, `rd.feed_rate`); param names must match the param_order extracted from WGSL Params structs (no `u_` prefix). The Reverie mixer (`agents/reverie/`) only writes non-zero chain deltas to uniforms.json — zero deltas would overwrite vocabulary defaults. **Multiplicative shader params** (`colorgrade.brightness`, `colorgrade.saturation`, `postprocess.master_opacity`) must default to 1.0 in the vocabulary preset, not 0.0, or the pipeline outputs black. 9 expressive dimensions in the GPU uniform buffer: intensity, tension, depth, coherence, spectral_color, temporal_distortion, degradation, pitch_displacement, diffusion. **Plan schema is v2** (`{"version": 2, "targets": {"main": {"passes": [...]}}}`); `_uniforms._iter_passes()` handles both v1 and v2 transparently — see § Reverie Vocabulary Integrity "Bridge repair" paragraph for the post-audit routing model. The DMN evaluative tick sends the rendered frame directly to gemini-flash (multimodal) alongside sensor text — first-person visual perception, not mediated. It extracts a visual description ("Visual: ...") and trajectory assessment, writes the visual observation to `/dev/shm/hapax-vision/observation.txt` for the imagination reverberation loop (Amendment 4). Gemini Flash 2.5 requires `budget_tokens: 0` (disable thinking) for vision tasks or reasoning consumes the entire token budget. Frames written to `/dev/shm/hapax-visual/frame.jpg` via turbojpeg. Content layer supports per-slot immensity entry and continuation-aware crossfade. The `VisualSurface` React component fetches frames at 10fps from `:8053`. Tauri communicates via UDS (`$XDG_RUNTIME_DIR/hapax-imagination.sock`). The winit window is independently positioned (multi-monitor, fullscreen, borderless, always-on-top).

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

**Learning persistence:** Activation state (Thompson alpha/beta + Hebbian associations) saved to `~/.cache/hapax/affordance-activation-state.json` every 60s via background thread + on shutdown. Exploration tracker state (4-layer habituation/interest/learning/coherence) saved to `~/.cache/hapax/exploration-tracker-state.json` on the same cadence. Reverie event loop is starved by Qdrant I/O — all persistence must use background threads, not async tasks or try/else blocks.

**Exploration → SEEKING:** 13 components publish boredom/curiosity signals to `/dev/shm/hapax-exploration/`. VLA reads aggregate boredom (top-k worst third, not mean) and feeds `exploration_deficit` to stimmung. When deficit > 0.35 and all dimensions nominal, stance transitions to SEEKING (3-tick hysteresis). Reverie mixer syncs SEEKING to its AffordancePipeline, halving the recruitment threshold (0.05 → 0.025) for dormant capabilities. Deficit formula uses boredom alone (per PCT: reorganization pressure ∝ intrinsic error); curiosity modulates exploration MODE via `evaluate_control_law()`, not deficit magnitude. SEEKING is correctly suppressed by biometric dimensions (operator_energy, physiological_coherence) during late night.

**Consent gate:** Capabilities declaring `OperationalProperties.consent_required=True` are filtered out of `AffordancePipeline.select()` when no active consent contract exists in `axioms/contracts/`. The check lives in `_consent_allows()`, runs after `_retrieve()` but before scoring, and caches the registry-active state for 60 s so per-frame consumers (reverie mixer, run loops) do not re-read yaml on every call. Fail-closed on any exception. As of 2026-04-12 this gates 7 capabilities including `studio.toggle_livestream` (broadcasting to RTMP), `knowledge.search_documents`, `knowledge.search_emails`, `world.web_search`, `digital.send_message`. **Until PR #(audit-followups) the gate did not exist** — these capabilities were being recruited regardless of contract state. Axiom `interpersonal_transparency` requires the gate.

**Stream-as-affordance:** `studio.toggle_livestream` (registered in `STUDIO_AFFORDANCES` alongside `toggle_recording`) is the recruitable surface for "begin or end broadcasting the composed studio visual to a live streaming destination". `daemon=compositor` (handler lives studio-side, alpha owns), `latency_class=slow` (RTMP handshake takes seconds — keeps the recruiter from oscillating start/stop), `consent_required=True` (first studio output destination that crosses the local boundary). The compositor-side trigger that wires this to the GStreamer RTMP sink is the prerequisite for A7 (native GStreamer RTMP, eliminate OBS).

**Daimonion dispatch split (PR #555 regression, beta followup):** The daimonion spawns **two** background tasks that read ``/dev/shm/hapax-dmn/impingements.jsonl`` through independent ``ImpingementConsumer`` instances, each with its own ``cursor_path``. **CPAL loop** (``_cpal_impingement_loop`` closure in ``run_inner.py``) owns gain/error modulation and spontaneous-speech surfacing — the adapter's ``should_surface`` gate calls ``pipeline.generate_spontaneous_speech`` through ``CpalRunner.process_impingement``. **Affordance loop** (``run_loops_aux.impingement_consumer_loop``) owns everything else recruited by the pipeline: ``system.notify_operator`` → ``activate_notification``, ``studio.*`` and world-domain Thompson outcome recording, ``system_awareness.activate``, ``capability_discovery.search`` chain, and ``ExpressionCoordinator.coordinate`` cross-modal dispatch (textual + notification modalities only; auditory is owned by CPAL). The loop explicitly skips ``speech_production`` candidates to avoid double-firing with CPAL. Cursor files: ``impingement-cursor-daimonion-cpal.txt`` for CPAL, ``impingement-cursor-daimonion-affordance.txt`` for affordance dispatch. Apperception cascade is NOT handled in either loop — ``shared.apperception_tick.ApperceptionTick`` inside the visual layer aggregator owns it. **Background:** PR #555 ("CPAL as sole coordinator") silently removed the affordance loop spawn while claiming the CPAL adapter "Replaces ... impingement_consumer_loop routing" — incorrect, because the adapter only transforms impingement → gain/error. Six dispatch effects were silently dead for ~10 days. Regression pin: ``tests/hapax_daimonion/test_impingement_consumer_loop.py::TestSpawnRegressionPin``.

**Impingement consumer bootstrap (F6, PRs #702 + #705):** `shared/impingement_consumer.ImpingementConsumer` supports three bootstrap modes. **Legacy** (`cursor=0`) reads from file start — default, for tests and stateless callers. **`start_at_end=True`** (delta PR #702) bootstraps cursor to end-of-file and skips any accumulated backlog; correct for reverie, where stale visual impingements cannot meaningfully modulate the next tick. **`cursor_path=<Path>`** (beta PR #705) persists the cursor to disk via atomic tmp+rename on each advance, seeks to end on first start, and resumes from the saved cursor on subsequent restarts; correct for daimonion (CPAL loop → `impingement-cursor-daimonion-cpal.txt`) and fortress (`impingement-cursor-fortress.txt`) where missing an impingement is a correctness bug. `cursor_path` takes precedence over `start_at_end` because its bootstrap rule is strictly stronger. `FortressDaemon` takes `impingement_cursor_path` as an `__init__` parameter defaulting to `None`; production `main()` wires the concrete `IMPINGEMENT_CURSOR_PATH`, tests stay on the None path. The pattern prevents test runs from polluting `~/.cache/hapax/` state. `agents/reverie_prediction_monitor.py` includes a **P7 uniforms-freshness watchdog** (beta PR #707) that fires a critical ntfy alert when `/dev/shm/hapax-imagination/uniforms.json` mtime is ≥ 60 s stale — catches the class of silent stall that caused the multi-day dimensional drought before #696.

## Studio Compositor

GStreamer-based livestream pipeline. Distinct from Reverie (the wgpu visual surface) — they are two separate render paths. The compositor reads USB cameras, composites them into a single 1920x1080 frame, applies a 24-slot GL shader chain, draws Cairo overlays (Sierpinski triangle with YouTube frames, token pole, album cover, content zones), and writes to `/dev/video42` (OBS V4L2 source) and an HLS playlist.

**Compositor unification epic complete (Phases 2–7 + Phase 5b + followups + audit + polish):** typed Source/Surface/Assignment/Layout data model, CairoSource protocol driving all Python Cairo content on background threads, multi-target render loop, transient texture pool, per-frame budget enforcement with degraded-signal publishing, and every direct-Cairo class migrated (Sierpinski, AlbumOverlay, OverlayZoneManager, TokenPole). After Phase 3b-final there is **no Cairo rendering on the GStreamer streaming thread** — every source feeds through `CairoSourceRunner` with its own background render cadence and a cached output surface the cairooverlay callback blits synchronously.

**Key modules:**
- `agents/studio_compositor/compositor.py` — `StudioCompositor` orchestration shell
- `agents/studio_compositor/cairo_source.py` — `CairoSource` protocol + `CairoSourceRunner` (background thread + output-surface cache + budget enforcement)
- `agents/studio_compositor/sierpinski_renderer.py` — Sierpinski triangle with YT video frames in corners, 10 fps
- `agents/studio_compositor/album_overlay.py` — Floating album cover + splattribution text + PiP effects, 10 fps
- `agents/studio_compositor/overlay_zones.py` — Obsidian markdown/ANSI zones with Pango rendering + DVD-screensaver bounce, 10 fps
- `agents/studio_compositor/token_pole.py` — Vitruvian Man + golden-spiral token tracker with particle explosions, 30 fps
- `agents/studio_compositor/stream_overlay.py` — Bottom-right three-line status strip (FX preset / viewer count / chat activity), 2 fps file polling (A4, PR #695)
- `agents/studio_compositor/chat_reactor.py` — `PresetReactor`: chat keyword → preset-name match → `graph-mutation.json` write with 30s cooldown and no-op-on-current-preset guard (A5, PR #698). Hooked into `scripts/chat-monitor.py._process_message`. Consent guardrail: no per-author state, no message persistence, no author name in logs — enforced by a caplog test
- `agents/studio_compositor/budget.py` — `BudgetTracker` + `publish_costs` (envelope: `{schema_version, timestamp_ms, wall_clock, sources}`)
- `agents/studio_compositor/budget_signal.py` — `publish_degraded_signal` for VLA consumption
- `shared/compositor_model.py` — `SourceSchema`/`SurfaceSchema`/`Assignment`/`Layout` pydantic models with difflib "did you mean" hints in validation errors

**Spec + audit:**
- `docs/superpowers/plans/2026-04-12-compositor-unification-epic.md` — full epic plan
- `docs/superpowers/specs/2026-04-12-compositor-source-registry-foundation-design.md` — PR 1 of the follow-up source-registry epic: make the `Layout`/`SourceSchema`/`SurfaceSchema`/`Assignment` framework authoritative, register reverie as an `external_rgba` source, migrate the three cairo overlays to natural-size + layout-driven placement, support mid-stream PiP geometry mutation via `compositor.surface.set_geometry`, lay `appsrc` pads for every source so preset chains can reference any of them.
- `docs/superpowers/audits/2026-04-12-compositor-unification-audit.md` — multi-phase audit + action items (all HIGH/MEDIUM/LOW items shipped in PRs #673–#676)
- `docs/superpowers/handoff/2026-04-12-session-handoff.md` — Apr 12 session handoff
- `docs/superpowers/handoff/2026-04-12-alpha-stream-handoff.md` — Apr 12 alpha Stream A handoff (A1/A2/A10/A11)
- `docs/superpowers/handoff/2026-04-12-alpha-stream-handoff-2.md` — Apr 12 alpha Stream A handoff pass 2 (FU-1/FU-2/FU-5/A12/A4/A5 — 5-layer silent-failure onion closure + overlay/chat feedback loop)

**Director loop bootstrap (fixed 2026-04-12):** `DirectorLoop.start()` dispatches playlist reloads (via daemon threads) for any slot whose `yt-frame-N.jpg` file is absent AND non-zero size (PR #679 + PR #694). Without this, a `youtube-player.service` restart used to leave the Sierpinski corners blank until a human manually POSTed initial URLs — observed 2026-04-12 as a 13 h outage. Stale 0-byte files also trip the check (PR #694). The playlist helper `_load_playlist()` was deleted along with `spirograph_reactor.py` in PR #644 and restored in PR #686, which is required or the cold-start dispatch is a silent no-op. Caches to `/dev/shm/hapax-compositor/playlist.json`, falls back to `yt-dlp --flat-playlist` extraction if the cache is missing.

**Director loop max_tokens (fixed 2026-04-12):** `_call_activity_llm` uses `max_tokens=2048` (was 300 — PR #692). At 300, Claude Opus was returning `finish_reason=length` with an empty content field on every perception tick, which silently dropped the whole reaction loop for 47+ minutes after the A10 restart. Raised to 2048 to leave preamble + JSON-response headroom. The WARNING log for an empty-content branch (PR #690) stays in place so the next session notices if 2048 is *also* insufficient.

**YouTube player extraction resilience (fixed 2026-04-12):** `scripts/youtube-player.py:extract_urls` uses `timeout=45` (was 15 — PR #693) and `VideoSlot.play()` writes a `yt-finished-N` marker with `rc=-1` on extraction failure. Without the marker, a yt-dlp timeout would leave the slot with no ffmpeg process and `auto_advance_loop` never notices — the slot sits wedged until service restart. With the marker, the compositor's `VideoSlotStub.check_finished` triggers `_reload_slot_from_playlist` which picks a *different* random video from the 105-entry playlist. Self-healing via re-roll.

**Studio compositor service env (fixed 2026-04-12):** `studio-compositor.service` now loads `/run/user/1000/hapax-secrets.env` via `EnvironmentFile=` (PR #686), matching `hapax-daimonion` / `logos-api`. Without this the compositor has no `LITELLM_API_KEY` and no `LANGFUSE_PUBLIC_KEY`, so the director loop's LLM calls and all Langfuse telemetry silently fail.

**Camera USB robustness (known hardware problem):** The three Logitech BRIO cameras keep getting kicked off the bus with kernel `device descriptor read/64, error -71` (EPROTO). Almost certainly a TS4 USB3.2 Gen2 hub / cable / power issue, not software. Investigation note: `docs/research/2026-04-12-brio-usb-robustness.md`. Reboot is the current workaround; `try_reconnect_camera` in `state.py` retries every ~10s but cannot fix signal-level USB errors.

## Reverie Vocabulary Integrity

The reverie mixer caches the vocabulary preset (`presets/reverie_vocabulary.json`) in-memory once at startup via `SatelliteManager._core_vocab`. If that dict is ever mutated at runtime by a since-deleted code path, or the preset file was different when the process booted, the mixer would historically keep compiling graphs from the stale cache for as long as the service ran — even after the on-disk preset was fixed. Observed as an 18h frozen `plan.json` on 2026-04-12 (`presets/reverie_vocabulary.json` pristine, SHM plan held a stale sierpinski-corrupted state).

`SatelliteManager.maybe_rebuild()` now reloads the preset from disk on `GraphValidationError` (PR #678), so recovery is automatic at the next rebuild tick after any validation failure — the 2 s rebuild cooldown bounds the outage to at most one frozen frame. Manual recovery via `systemctl --user restart hapax-reverie.service` remains available; it is no longer the only path. Symptom if it ever recurs: `plan.json` in `/dev/shm/hapax-imagination/pipeline/` contains node types that don't match the git-tracked preset AND the reverie log shows `Graph validation failed — reloading vocabulary preset` on each tick. The defensive reload is resilience, not diagnosis — the root cause of the original corruption is still unknown.

Any Sierpinski or other satellite shader nodes in Reverie MUST be recruited dynamically via the affordance pipeline (prefix `sat_<node_type>`), NOT wired into the core vocabulary. If you see core-prefix nodes like `content: sierpinski_content` (instead of `sat_sierpinski_content`), restart the service.

**Intermediate texture pool (B4, PR #689):** `DynamicPipeline` allocates non-temporal intermediate textures through `TransientTexturePool<PoolTexture>` instead of a flat `HashMap<String, PoolTexture>`. The pool key is `hash(width, height, TEXTURE_FORMAT)` — recomputed on resize. `intermediate_slots: HashMap<String, usize>` maps the human-readable name (`@live`, `main:final`, etc.) to the slot index inside the bucket. Lookups go through three private helpers: `intermediate(name)`, `intermediate_names()`, `any_intermediate()`. Per-frame `begin_frame()` recycling, Python-side `pool_key` emission from `CompiledFrame`, and temporal-texture pooling are explicit non-goals — see `docs/superpowers/plans/2026-04-12-b4-transient-pool-wiring.md`. External observability is exposed via `DynamicPipeline::pool_metrics()` which returns a `PoolMetrics` snapshot (bucket count, total textures, acquires, allocations, reuse ratio, slot count) — wire into Prometheus or the debug overlay as needed.

**Bridge repair (2026-04-12, PR #696 + #700):** The visual chain → GPU bridge has **two independent routing paths** that together define reverie's expressive surface. Both paths must be alive.

*Path 1 — shared 9-dim uniform slots.* The imagination fragment's 9 dimensions (`intensity, tension, depth, coherence, spectral_color, temporal_distortion, degradation, pitch_displacement, diffusion`) flow `current.json` → `StateReader.imagination.dimensions` → `UniformBuffer::from_state` at `hapax-logos/crates/hapax-visual/src/uniform_buffer.rs:140-148` → shared `UniformData.{dim}` struct fields. Any shader that reads `uniforms.intensity`, `uniforms.tension`, etc. lands here. This path has always been alive.

*Path 2 — per-node `params_buffer`.* `visual_chain.compute_param_deltas()` emits `{node_id}.{param_name}` keys → `uniforms.json` → Rust `dynamic_pipeline.rs:835-855` walks `pass.param_order` positionally and writes `params_buffer[i]`. Each shader with a `@group(2) Params` struct binding (noise, rd, colorgrade, drift, breath, feedback, postprocess) receives its per-node modulation through this path. **Was broken silently** from the moment the Rust `DynamicPipeline` adopted the v2 plan schema (`{"version": 2, "targets": {"main": {"passes": [...]}}}`) because `agents/reverie/_uniforms._load_plan_defaults` was still walking the v1 flat `plan["passes"]` key. `_iter_passes()` now handles both schemas — see the regression test at `tests/test_reverie_uniforms_plan_schema.py`. Live `jq 'keys | length' /dev/shm/hapax-imagination/uniforms.json` should be ≥44 (42 plan defaults + `signal.stance` + `signal.color_warmth`); anything near 6–8 is the old drought state.

*Content layer custom[0] routing (F8 resolved).* `content_layer.wgsl` has no `@group(2) Params` binding — it composites 4 content slots and reads `material_id` / slot salience / intensity from `uniforms.custom[0]`. The fix takes option (b): `dynamic_pipeline.rs render()` routes `content.material` / `content.salience` / `content.intensity` keys from uniforms.json into `UniformData.custom[0][0..2]` on each frame, next to the existing `signal.*` override branch. The Python mixer writes all three keys from imagination fragments (`agents/reverie/_uniforms.write_uniforms`); material maps water/fire/earth/air/void → 0..4 via `MATERIAL_MAP`. Before F8 landed, material_id was effectively hardcoded to water (0) at the GPU and Bachelard Amendment 3 (material quality as shader uniform) was unreachable at runtime. Regression pin: `tests/test_reverie_uniforms_plan_schema.py::test_write_uniforms_end_to_end_produces_expected_keys` asserts all three keys land with the expected values.

**Impingement consumer start-at-end (F6, PR #(docs-f6)):** `ImpingementConsumer` accepts an optional `start_at_end=True` kwarg that seeks to the end of the JSONL file on construction. Reverie passes it, because stale impingements accumulated while reverie was restarting cannot meaningfully modulate the next visual tick and would otherwise stall the first tick for 5–15 min of Qdrant round-trips. Daimonion and fortress still use the default (`start_at_end=False`) for crash-resume semantics. Without this, restart verification of the bridge is blocked: the new code is loaded but `uniforms.json` does not receive a fresh write until the backlog drains. Symptom: `stat /dev/shm/hapax-imagination/uniforms.json` shows an mtime older than `systemctl --user show hapax-reverie.service -p ActiveEnterTimestamp --value`.

## Voice FX Chain

Hapax TTS output (Kokoro 82M CPU) can be routed through a user-configurable PipeWire `filter-chain` before hitting the Studio 24c analog output. Presets live at `config/pipewire/voice-fx-*.conf`; install one of them into `~/.config/pipewire/pipewire.conf.d/`, restart pipewire, and export `HAPAX_TTS_TARGET=hapax-voice-fx-capture` before starting `hapax-daimonion.service`. The conversation pipeline reads the env var at audio-output-open time and forwards it to `pw-cat --target`. Unset or empty falls through to default role-based wireplumber routing — the chain is fully opt-in. All presets share the same sink name so swapping presets does not require restarting daimonion. Preset inventory + install flow + troubleshooting live at `config/pipewire/README.md`.

## Council-Specific Conventions

- Hypothesis for property-based algebraic proofs.
- Working mode file: `~/.cache/hapax/working-mode` (research/rnd). CLI: `hapax-working-mode`.
- Safety: LLMs prepare, humans deliver. Never generate feedback language or coaching recommendations about individual team members.
- **Session handoffs** live at `docs/superpowers/handoff/{date}-{session}-handoff.md` (or `{date}-{session}-{pass}-handoff.md` for multi-pass sessions). Each retiring session writes one before stopping; the next session of the same role reads it as the first thing after the relay onboarding. CI's `paths-ignore` filter covers both `docs/**` AND `*.md` (root-level), so a CLAUDE.md note is NOT sufficient to unblock branch protection — bundle a non-markdown, non-docs change (a script comment, a Python no-op, a config touch). Observed the hard way on PR #706.
- **Build rebuild scripts (FU-6 / FU-6b, 2026-04-12):** `scripts/rebuild-logos.sh` builds logos/imagination in an isolated scratch worktree at `$HOME/.cache/hapax/rebuild/worktree` — the primary alpha/beta worktrees are never mutated mid-session. `scripts/rebuild-service.sh` handles Python services (daimonion, dmn, reverie, logos-api, officium, mcp) and refuses to auto-deploy a feature branch (the systemd units still read Python directly from alpha's worktree); when alpha is off main it skips the deploy, does **not** advance the SHA tracker, and emits a throttled `ntfy` (one per distinct `origin/main` SHA) so the operator notices. `rebuild-logos.sh` uses `flock -n` on `$STATE_DIR/lock` to prevent concurrent runs from racing on the shared scratch tree; `rebuild-service.sh` relies on systemd's `Type=oneshot` anti-overlap and does not flock (manual invocations are rare and the deploy operation is idempotent). The root architectural tension — alpha's worktree serving as both a dev branch and a production deploy target — is **not** resolved by these fixes; see `docs/superpowers/handoff/2026-04-12-alpha-fu6-handoff.md § Architectural follow-up`.

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
| `no-stale-branches.sh` | Bash | **Branch creation** (`git branch`, `git checkout -b`, `git switch -c`, `git worktree add` WITH `-b`/`-B`): any unmerged branches exist. **Session worktree limit:** max 4 (alpha + beta + delta + 1 spontaneous); infrastructure worktrees under `~/.cache/` are not counted. **Destructive commands** (`git reset --hard`, `git checkout .`, `git branch -f`, `git worktree remove`): on a feature branch with commits ahead of main. Delta is a first-class peer session since 2026-04-12 — attaching `git worktree add` to an EXISTING branch is not branch creation and is always allowed |
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
- `agents/health_monitor/constants.py` — `PI_FLEET` dict defines expected services per Pi

**Inference:** ONNX Runtime preferred (130ms, preserves fine-tuned precision), TFLite fallback. Model: YOLOv8n fine-tuned on 30 NIR studio frames (`best.onnx`). **Person detection currently non-functional** — 30-frame training dataset insufficient for NIR domain. Retraining planned (500+ frames, two-stage COCO→FLIR→NIR transfer). See `docs/superpowers/specs/2026-03-31-ir-perception-remediation-design.md`.

**Signal quality (remediated 2026-03-31):**
- Hand detection: max_area_pct=0.25 rejects frame-spanning false positives, aspect ratio 0.3–3.0
- Screen detection: adaptive threshold (mean_brightness × 0.3) instead of fixed value
- rPPG: gated on face landmarks actually available (no phantom heart rates)
- Biometrics: face_detected field in IrBiometrics for observability

**Fusion logic:** Person detection = any() across Pis. Gaze/biometrics prefer desk Pi (face-on). Hand activity + hand zone prefer overhead Pi. Staleness cutoff: 10s. **Person detection currently non-functional** (30-frame training set) — `ir_person_detected` set to `None` (neutral) to prevent false-negative Bayesian poisoning. `ir_hand_activity` is reliable and wired into presence engine as a strong positive-only signal.

**15 signals:** ir_person_detected, ir_person_count, ir_motion_delta, ir_gaze_zone, ir_head_pose_yaw, ir_posture, ir_hand_activity, ir_hand_zone, ir_screen_looking, ir_drowsiness_score, ir_blink_rate, ir_heart_rate_bpm, ir_heart_rate_conf, ir_brightness, ir_brightness_delta. All 15 flow to perception-state.json.

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

- **`shared/config.py`** — Model aliases (`fast`→gemini-flash, `balanced`→claude-sonnet, `local-fast`/`coding`/`reasoning`→TabbyAPI Qwen3.5-9B), `get_model_adaptive()` for stimmung-aware routing, LiteLLM/Qdrant clients, CPU embedding via Ollama nomic-embed-cpu (Ollama is GPU-isolated, CPU only)
- **`shared/working_mode.py`** — Reads `~/.cache/hapax/working-mode` (research/rnd). CLI: `hapax-working-mode`
- **`shared/notify.py`** — `send_notification()` for ntfy + desktop
- **`shared/frontmatter.py`** — Canonical frontmatter parser (never duplicate this)
- **`shared/dimensions.py`** — 11 profile dimensions. Sync agents produce behavioral facts only.
- **`shared/consent.py`** — `ConsentContract`, `ConsentRegistry`, `contract_check()`
- **`shared/agent_registry.py`** — `AgentManifest` (4-layer schema), query by category/capability/RACI
- **`shared/telemetry.py`** — `hapax_span` / `hapax_event` / `hapax_score` for Langfuse circulatory-system instrumentation. `hapax_span` uses an `ExitStack` so setup failures yield a no-op span and caller exceptions propagate cleanly — do not refactor it back to a single try/except wrapping the yield, that reintroduces the `RuntimeError: generator didn't stop after throw()` bug that silently killed the director loop for 47 min on 2026-04-12 (PR #685). Note: metadata values must be strings; non-string values are dropped with a warning by langfuse's `propagate_attributes` but do not break the span.

## Voice Grounding Research Continuity

Research state persists in `agents/hapax_daimonion/proofs/RESEARCH-STATE.md`. After any session with research decisions or implementation progress on the voice grounding project, update this file before ending. When the operator says "refresh research context" or "update research context", read the state file and selectively read the tier-2 documents it references.

## Prompt Compression Benchmark

`scripts/benchmark_prompt_compression_b6.py` is the reference harness for the §4.2 latency benchmark from the prompt-compression research plan. Hits TabbyAPI directly (`http://localhost:5000`) so the LiteLLM gateway hop does not pollute the latency measurement, and reads `prompt_time` / `completion_time` / `total_time` from TabbyAPI's per-response `usage` block (no streaming instrumentation needed). Toggles between full system prompt and compressed (Phase 1.1 — `tool_recruitment_active=True`) via `agents.hapax_daimonion.persona.system_prompt`. Sequential A→B blocks with 3-warmup-then-N-trials per condition; results land in `~/hapax-state/benchmarks/prompt-compression/phase2-ab-{ts}.json`. Conditions A/B are runnable on current hardware (Qwen3.5-9B); C/D require Hermes 3 70B and stay deferred until B5 hardware lands. Headline result and caveats: `docs/research/2026-04-12-prompt-compression-phase2-ab-results.md`.

## Composition Ladder Protocol (hapax_daimonion)

Bottom-up building discipline for the hapax_daimonion type system. 10 layers (L0–L9), all proven. 7-dimension test matrix per layer. Gate rule: no new composition on layer N unless N-1 is matrix-complete. See `agents/hapax_daimonion/LAYER_STATUS.yaml` for current status and `tests/hapax_daimonion/test_type_system_matrix*.py` for the 192 matrix tests.

**3-question heuristic** before every change:
1. What layer does this touch?
2. Is the layer below matrix-complete? (If no → fix that first)
3. Which dimensions does this test cover? (Update LAYER_STATUS.yaml)
