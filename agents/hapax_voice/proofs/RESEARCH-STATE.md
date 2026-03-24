# Voice Grounding Research State

**Last updated:** 2026-03-23 (session 14 — ingestion pipeline audit + classification inspector)
**Update convention:** After any session with research decisions or implementation progress, update this file before ending.

## Position (one paragraph)

This project implements Clark & Brennan's (1991) conversational grounding theory in a production voice AI. Current voice AI systems use profile-gated retrieval (ChatGPT Memory, Gemini, Mem0); none implement Clark's contribution-acceptance cycle. Shaikh et al. (ACL 2025) report frontier LLMs score 23.23% on grounding tasks. Shaikh et al. (NAACL 2024) identify RLHF as a factor suppressing grounding acts.

## Current Phase

- **Cycle 1:** COMPLETE (pilot, 37 sessions, BF=3.66 inconclusive, word overlap metric replaced)
- **Cycle 2:** READY FOR BASELINE DATA COLLECTION
  - All research complete (28 agents across 4 rounds, 80+ citations)
  - Implementation: **Batches 1-4 COMMITTED** + **wiring gaps closed** (PR #236, 85 tests)
  - **GQI-stimmung coupling** implemented (10th dimension, weight 0.3, cross-process via shm)
  - **Pre-registration updated** with 3+1 package, new DVs, effect size calibration
  - **Repository optimization** complete (session 3)
  - **Environment audited** (session 4): 10 audit agents, resource hogs killed, worktrees cleaned, configs corrected
  - **CI/CD + PII hardened** (session 5): Full CI pipelines on all 6 repos, SDLC pipeline consistency audit, 5 audit passes removing operator PII from tracked files + git history, speaker labels refactored ("ryan"→"operator"), gitleaks custom rules deployed, cockpit-mcp renamed to hapax-mcp
  - **cockpit→logos rename** (session 6): `cockpit/` directory → `logos/` across council (PR #263) and officium (PR #46). All Python imports, pyproject.toml scripts/extras, Docker configs, CI workflows, systemd units, cache paths updated. hapax-mcp env var `COCKPIT_BASE_URL` → `LOGOS_BASE_URL` (with fallback). ~345 files changed, 5788 tests pass
  - **RESEARCH/R&D mode isolation** (session 7): Mechanical enforcement separating experiment work from development. Pre-commit hook + CI workflow freeze experiment paths during active phases. Working mode switch (`hapax-working-mode research|rnd`) with pre-flight checklist, relay protocol integration, Langfuse environment tagging, waybar/fish visual indicators. Deviation workflow for frozen-path changes. See `experiment-freeze-manifest.txt`
  - **Experiment config** set to Phase A baseline (continuity-v2)
  - **SESSION-PROTOCOL** updated with selective flags (replaces monolithic volatile_lockdown)
  - Remaining: ORCID, OSF project, pre-registration filing, Zenodo, GitHub Pages
- **Cycle 3:** NOT STARTED (contingent on Cycle 2 results; may require fine-tuned model if RLHF anti-pattern binds)

## What Was Built (Batches 1-4)

### Batch 1 — Foundation
- `_EXPERIMENT_PROMPT` in persona.py (~200 tokens, no tools)
- `_EXPERIMENT_STYLE` in conversational_policy.py (~30 tokens, dignity floor + minimal style)
- `ThreadEntry` dataclass: verbatim operator text (preserves conceptual pacts), acceptance signal, grounding state, repair flag, seeded flag
- `_extract_substance()`: no more `split(",")[0].split(".")[0][:60]` — preserves full text, max 100 chars
- `_render_thread()`: tiered compression (recent=full+quotes, middle=referring expression, oldest=keyword)
- Thread cap: 10 entries (down from 15, Lost in the Middle research)
- Phenomenal context: stimmung-only gating for experiment
- Salience: prompt block stripped, router still computes mechanically
- Env context: presence only in experiment mode

### Batch 2 — Grounding Loop
- `grounding_ledger.py` (NEW, ~315 lines):
  - DU state machine: PENDING → GROUNDED/REPAIR-1/REPAIR-2/ABANDONED/CONTESTED/UNGROUNDED
  - Concern-aware repair thresholds (Clark's "sufficient for current purposes"): high concern + low GQI → require ACCEPT (0.9), low concern + high GQI → IGNORE is fine (0.3)
  - GQI computation: 50% EWMA acceptance + 25% trend + 15% consecutive negatives + 10% engagement
  - 2D effort calibration: activation × (1 - gqi_discount) → EFFICIENT/BASELINE/ELABORATIVE with hysteresis
  - Strategy directives injected into VOLATILE band per turn
- Pipeline wired: acceptance feeds ledger with concern_overlap, DU registered per response, directive + effort level injected

### Batch 3 — Memory Integration
- `_load_seed_entries()`: returns list[ThreadEntry] from Qdrant, prioritizes unresolved DUs
- Thread seeding: 2-3 prior session entries with `[PRIOR]` markers
- Age-out: seeded entries compress at 6 current entries, drop at 11
- Persist: unresolved DUs and grounding_state stored in Qdrant payload
- Experiment flags loaded before prompt construction (was after — bug)

### Batch 4 — Observability
- `_score_monologic()`: detects RLHF anti-pattern (monologic=1.0 vs dialogic=0.0)
- `score_directive_compliance()`: did model follow the grounding directive?
- Selective lockdown: grounding directive/effort NOT locked even with volatile_lockdown
- Salience router computes in both phases (activation/concern available mechanically)

## Critical Decisions (with reasoning)

1. **3+1 package**: 3 treatment (thread + drop + memory) + 1 diagnostic (sentinel). WHY: sentinel tests retrieval not grounding; including it as treatment threatens construct validity (Ward-Horner & Sturmey 2010).

2. **Refine BEFORE test**: gestalt effects require properly composed components. WHY: "testing an incomplete system for emergence is playing 2 of 4 notes."

3. **BEST over beta-binomial**: continuous data requires t-distributed likelihood. WHY: beta-binomial wrong for continuous metrics; autocorrelation inflates BF (Shadish et al. 2013 mean r=0.20).

4. **turn_pair_coherence** replaces context_anchor_success. WHY: word overlap penalizes abstraction/paraphrasing; qualitative grounding effects invisible to prior metric.

5. **Always CAPABLE**: intelligence is last thing shed. Salience router becomes effort calibrator, not model selector.

6. **Acceptance must actuate**: classified but not fed back = 1/3 of Clark's cycle. Closing the loop is the bridge from anchoring to grounding.

7. **Conceptual pacts**: preserve operator's verbatim terminology in thread. WHY: Metzing & Brennan 2003 — pact violations maximally costly with single known partner.

8. **Bands = grounding substrate**: STABLE band = discourse record, VOLATILE band = turn-specific directives, stimmung = GQI signal, salience = effort calibrator, concern graph = "sufficient for current purposes."

9. **Every token justified**: system prompt stripped to ~800-1000 tokens for experiment. No tool descriptions, no profile digest, no environmental modulation.

10. **GQI as stimmung dimension**: 10th dimension, unidirectional (no circular dependency). GQI reads conversation signals only, feeds stimmung, stimmung renders in Layer 1.

## Session 10 (2026-03-22): Pre-Testing Readiness + Context-as-Computation

- **Full environment audit** (10 agents): operations, methodology, research basis, data pipeline, development state, system stability, resource contention, lifecycle management, relay protocol, experiment freeze enforcement. All green except resource hogs (killed) and working mode (set to RESEARCH).
- **Context-as-Computation research** (4 agents): Established mechanistic justification for multi-band architecture. Prompt is a program (Von Oswald 2023, mesa-optimization). Position determines representation (primacy tail proven 2026). Entrainment heads elevate context-seen tokens (ACL 2025 Outstanding Paper). Acceptance signals function as reward for in-context RL. Function vectors compose additively. RLHF correction angle: we restore training-suppressed grounding capability at runtime.
- **Decision: black box first, white box if warranted.** Cycle 2 measures behavioral outputs. Internal model investigation (attention patterns, SAE features, representation similarity) deferred to Cycle 3+ and only if Cycle 2 shows positive effect.
- **New research document**: `proofs/CONTEXT-AS-COMPUTATION.md` + lab journal entry. DEVIATION-003 filed.
- **Methodology gaps identified**: stats.py still implements beta-binomial (not BEST); must fix before Phase B analysis. OSF pre-registration not yet filed. Cycle 1/2 data not segregated.

## Open Questions

- A-B-A vs A-B-A-B design (Barlow: reversal inappropriate for learning interventions)
- Effect size target from Cycle 2 baseline data
- RLHF anti-pattern: prompted Opus sufficient or fine-tuning needed? (Cycle 3 decision)
- White-box investigation: local model parallel experiment for mechanistic interpretability (Cycle 3+)
- stats.py needs BEST implementation before Phase B analysis
- 13 L8-L9 test failures (wake word debounce) — pre-existing, not from grounding changes
- Verify Shaikh et al. ACL 2025 citation accuracy (23.23% figure, venue)

## Operator Action Items (from session 3 research)

1. Get ORCID → update CITATION.cff files
2. Create OSF project → link GitHub repos
3. File pre-registration on OSF (comprehensive template + SCED addendum)
4. Connect Zenodo to GitHub → enable for council + constitution
5. Enable GitHub Pages for lab journal
6. Verify Shaikh et al. citation accuracy

## Key Documents (read to reconstruct full context)

| Document | Tokens | Content |
|----------|--------|---------|
| `THEORETICAL-FOUNDATIONS.md` | ~8K | Literature review: Clark, Traum, Brennan, SCED methodology, LLM architectures |
| `REFINEMENT-RESEARCH.md` | ~5K | 8 research streams → refined model design |
| `PACKAGE-ASSESSMENT.md` | ~4K | Component analysis, 2x2 matrix, SCED methodology |
| `POSITION.md` | ~3K | Positioning vs profile retrieval, 5 failure modes |
| `WHY-NO-ONE-IMPLEMENTED-CLARK.md` | ~3K | 35-year gap analysis: obstacles, misconceptions |
| `CYCLE-2-PREREGISTRATION.md` | ~3K | Experiment design: ABA, BEST, HDI+ROPE, session protocol |
| `CYCLE-1-PILOT-REPORT.md` | ~2K | Methods, results, 6 deviations, limitations |
| `BASELINE-ANALYSIS.md` | ~2K | 17 sessions, 8 patterns |
| `REFINEMENT-DECISION.md` | ~1K | Decision to refine before testing |
| `SYSTEM-CLEANUP-DECISION.md` | ~1K | Strip to research essentials directive |
| `REPO-OPTIMIZATION-RESEARCH.md` | ~12K | Repository optimization research (140+ sources, 6 streams) |
| Plan: `shimmering-growing-lollipop.md` | ~3K | Implementation batches 1-4 |

## Research Infrastructure (added session 3)

| Artifact | Location | Purpose |
|----------|----------|---------|
| Research compendium | `research/` | TIER/Psych-DS directory structure |
| Theory traceability | `research/THEORY-MAP.md` | Theory → code → test matrix |
| Experiment phase | `experiment-phase.json` | CI phase-gating state |
| CITATION.cff | repo root | Academic citation metadata |
| Handoff doc | `~/gdrive-drop/research-infrastructure-handoff.docx` | Operator action items |
| Freeze manifest | `experiment-freeze-manifest.txt` | Frozen paths during active experiment |
| Deviation records | `research/protocols/deviations/` | Changes to frozen paths with justification |
| Working mode | `~/.cache/hapax/working-mode` | Unified mode: research or rnd (single source of truth) |
| Mode switch | `scripts/hapax-working-mode` | Pre-flight + relay + ntfy + timers + theme + waybar |
| Theme apply | `~/.local/bin/hapax-theme-apply` | DE-wide theme switch (Solarized/Gruvbox) |
| Theme palettes | `hapax-logos/src/theme/palettes.ts` | Logos Solarized Dark + Gruvbox Hard Dark definitions |
| Theme provider | `hapax-logos/src/theme/ThemeProvider.tsx` | Runtime CSS custom property swap from working mode |
| Freeze hook | `scripts/experiment-freeze-check` | Pre-commit enforcement of frozen paths |
| CI freeze gate | `.github/workflows/experiment-freeze.yml` | PR-level freeze enforcement |
| Contract tests | `tests/contract/test_council_api_schema.py` | Schemathesis API fuzzing (97 endpoints, `contract` marker) |
| Frontmatter schemas | `shared/frontmatter_schemas.py` | Write-time validation for filesystem-as-bus documents |
| Qdrant assertions | `shared/qdrant_schema.py` | Startup collection config verification (8 collections) |
| Contract design | `docs/boundary-contract-enforcement.md` | Design doc + smoke test triage + future work |
| MCP response models | `hapax-mcp/src/hapax_mcp/models/` | Consumer-side Pydantic contracts for logos API |

## Session 5–7 Infrastructure Changes (2026-03-21)

All infrastructure-only. No changes to experiment code, grounding theory, or research design.

- **Session 5 (CI/CD + PII)**: CI pipelines on all 6 repos. Pinned GitHub Actions. PII removal (5 passes): operator name from docs/code/tests, /home/hapax/ paths, speaker labels "ryan"→"operator", family references, coordinates. Custom .gitleaks.toml. PII guard hook. cockpit-mcp → hapax-mcp rename.
- **Session 6 (cockpit→logos)**: `cockpit/` → `logos/` directory rename across council + officium. All imports, configs, Docker, systemd, CI updated. hapax-mcp env var fallback. ntfy topic stays "cockpit" (external).
- **Session 7 (mode isolation)**: Five-layer RESEARCH/R&D isolation: (1) code freeze via manifest + pre-commit + CI gate, (2) data isolation via Langfuse environment tagging, (3) working mode file + Python module, (4) relay protocol integration, (5) waybar + fish prompt visual indicators. Deviation workflow for frozen-path changes. Pre-flight checklist enforces zero stale branches before mode switch.
- **Session 8 (systemd overhaul)**: Reverted /home/operator PII scrub (incomplete, fragile symlink dependency). Normalized 168 path references across 41 files. Imported 51 untracked systemd units + 8 drop-in override directories (coverage 47%→97%). Reconciled 4 drifted units: llm-stack (--profile full), logos-api (merged 3 versions, retired drop-in), rag-ingest (Type=simple daemon), audio-recorder (pw-record pipeline). Fixed health-watchdog bug (exit code 2 discarded reports). Cleaned broken symlinks, debris, stale branches. officium-api.service now tracked in hapax-officium repo. PR #264 merged, all CI green.
- **Session 9 (drift + cockpit rename)**: Tuned drift detector to split headline count: real drift vs doc hygiene (coverage-gap, missing-section, etc). Drops reported items from 181→~20. Completed cockpit→logos rename across all 3 repos (~80 files): `COCKPIT_API_URL`→`LOGOS_API_URL`, `COCKPIT_WEB_DIR`→`LOGOS_WEB_DIR` in shared/config.py + all importers, docstrings, Tauri commands, vscode extension, specs, cache paths. Fixed Qdrant collection count (4→8), vscode port (8095→8051/8050), boundary doc sync (constitution←officium). Fixed AgentSummary to handle flat array API response (was showing "0 agents"). Fixed studio-compositor crash (PyGObject missing after Python 3.14 upgrade — `uv pip install PyGObject`). PR #265 merged, all CI green.

## Session 11 (2026-03-23): System Freeze Diagnosis + 24/7 Reliability + Service Lifecycle

Infrastructure-only. No changes to experiment code, grounding theory, or research design.

**System freeze diagnosis:** Machine hard-locked overnight (no clean shutdown, no kernel panic logged). Root cause: NVIDIA GPU hang (open driver 595.45.04 on freshly rebuilt kernel 6.18.19-lts) with `nowatchdog` kernel parameter disabling all lockup detection. Memory was fine (66% free). Journal gap from 19:39–07:03 due to hard freeze preventing flush.

**24/7 reliability hardening:**
- Removed `nowatchdog` from kernel cmdline; enabled NMI watchdog, softlockup/hung-task panic, auto-reboot on panic (10s)
- Enabled hardware watchdog (AMD SP5100 TCO) via systemd RuntimeWatchdogSec=30
- Journal persistence: SyncIntervalSec=15s, ForwardToKMsg=yes, pstore for crash dumps
- Installed prometheus-node-exporter, added to Prometheus scrape config
- Enabled snapper-timeline (hourly btrfs snapshots)
- OOM protection: earlyoom (-1000), docker (-900), pipewire (-900), ollama (-500)
- greetd autologin configured; loginctl enable-linger for unattended boot
- Docker containers: `restart: unless-stopped` → `restart: always`

**Service lifecycle consolidation (process-compose → pure systemd):**
- Created `hapax-secrets.service`: centralized oneshot credential loader. All services now declare `Requires=hapax-secrets.service`. Eliminates 4x redundant `pass show` calls and race condition where logos-api read hapax-voice's env file without a dependency.
- Migrated `visual-layer-aggregator` from process-compose to systemd (unit already existed, was disabled). Now has own cgroup with 1G memory limit (was sharing cgroup, thrashing at 256M).
- Migrated `vram-watchdog` from process-compose bash loop to systemd timer (30s interval). Updated script to use `systemctl --user show` instead of process-compose API.
- Disabled `hapax-stack.service` (process-compose wrapper). Marked `process-compose.yaml` as development-only.
- Updated 24 files: all unit files now reference `hapax-secrets.env`, all overrides point to correct dependencies.
- Fixed `hapax-env-setup` script to read from `hapax-secrets.env` (single source of truth).
- Documented in `systemd/README.md` (new), `docs/compendium.md` §14, workspace + council CLAUDE.md, README.md.

**Bug fix:** `enet_b2_8_best` → `enet_b2_8` in vision.py. hsemotion model name was invalid, causing 666 failed download attempts per hour (every 5s per camera inference cycle). The file `enet_b2_8_best.onnx` doesn't exist in the hsemotion model registry; correct name is `enet_b2_8`.

## Session 12 (2026-03-23): Unified Working Mode + Mode-Driven Theming

Infrastructure-only. No changes to experiment code, grounding theory, or research design.

**Unified working mode system (PR #276):** Collapsed two independent mode systems (cycle mode dev/prod + working mode research/rnd) into a single system. Only two modes: Research and R&D. `shared/working_mode.py` is single source of truth; `shared/cycle_mode.py` becomes backward-compat shim. Fixed inverted container cron semantics (dev mode was incorrectly slower than prod). R&D = full speed (accelerated timers, frequent syncs, probes active). Research = experiment-safe (slower timers, suppressed probes, increased engine debounce). `hapax-working-mode` script absorbs timer override logic from `hapax-mode`. API endpoint `/api/working-mode` replaces `/api/cycle-mode`. Frontend, Tauri, MCP, session hook all updated. 37 files changed, 18 new tests.

**Mode-driven theming (PR #280):** Visual theme switches with working mode across entire stack.
- **Research → Solarized Dark** (cool, clinical, precise — matches scientific register)
- **R&D → Gruvbox Hard Dark** (warm, textured, energetic — matches development velocity)
- DE components: Hyprland borders, Hyprpaper wallpaper, Foot terminal (dual-palette via USR1/USR2), Waybar CSS, Mako notifications, Fuzzel launcher, Hyprlock, Fish prompt, GTK theme — all switch via `hapax-theme-apply` script called by `hapax-working-mode`.
- Logos frontend: ThemeProvider reads working mode via API, swaps CSS custom properties on `<html>`. All Tailwind classes respond automatically. Fixed hardcoded hex in SystemStatus, HealthHistoryChart, MermaidBlock, VisualLayerPanel. Keyframe animations converted to CSS `color-mix()` with custom properties.
- Non-CLI failsafe: waybar click-to-toggle + Super+M keybind.
- Solarized GTK theme (`gtk-theme-numix-solarized`) installed from AUR.

**Data source audit (87 endpoints):** Fixed 7 broken data sources:
- `/api/consent/coverage`: MatchExcept Pydantic alias bug → IsNullCondition
- `/api/governance/authority`: AgentRegistry API mismatch (0→33 agents)
- Temporal bands: cross-process ring inaccessible → local ring in aggregator (`/dev/shm/hapax-temporal/` now populated)
- Logos API startup: blocking cache refresh (90s+) → non-blocking background load
- Boot readiness: stuck at "collecting" for 5 min (monotonic time vs init value bug) → immediate fetch
- profile-facts Qdrant: 0 points after reboot (WAL not flushed before crash) → re-indexed 2098 facts

**Frontend graceful loading:**
- Boot overlay: semi-transparent backdrop blocks interaction, fades out on ready, invalidates all React Query caches
- Camera components: placeholder tiles + fade-in on first frame
- Sidebar panels: 6 panels show loading skeletons instead of vanishing during cold cache
- Ground surface: ambient text/nudge pills bumped from 8% to 20-25% opacity, redundant CSS gradient blobs removed

**Git workflow consolidation:**
- Three permanent worktree slots: alpha (`hapax-council/`), beta (`hapax-council--beta/`), one spontaneous
- Removed `branch-switch-guard` hook (worktree isolation replaces it)
- Updated relay protocol, onboarding docs, hooks, CLAUDE.md
- Max 3 worktree enforcement in `no-stale-branches` hook

## Session 13 (2026-03-23): Boundary Contract Enforcement

Infrastructure-only. No changes to experiment code, grounding theory, or research design.

**Boundary contract enforcement across Hapax/Logos systems.** Researched contract testing landscape (Pact/CDC, Schemathesis, Testcontainers, Hypothesis+Pydantic). Rejected Pact/CDC as over-engineering for single-operator system. Implemented four targeted interventions:

1. **Schemathesis API fuzzing** (`tests/contract/`): 97 parametrized tests against council logos API OpenAPI spec via ASGI transport. Property-based fuzzing generates ~50 examples per endpoint. Behind `contract` marker (excluded from default test run). First run: 57/97 pass (all read-only endpoints clean), 32 expected failures (non-JSON content types, fuzzed path params → correct 404s), 8 actionable findings.

2. **MCP response models** (`hapax-mcp/src/hapax_mcp/models/`): 6 Pydantic consumer-side models (health, gpu, infrastructure, profile, working mode) with `extra="allow"`. `get_validated()` typed client function. `status()` compound tool now validates all 4 sub-endpoint responses. 14 tests. All models verified against live API responses.

3. **Frontmatter write-time schemas** (`shared/frontmatter_schemas.py`): 7 Pydantic models for filesystem-as-bus document types (briefing, digest, nudges, goals, decision, bridge-prompt, RAG source). All 6 vault_writer specialized writers now validate before writing. 17 tests including Hypothesis property-based roundtrips.

4. **Qdrant collection schema assertions** (`shared/qdrant_schema.py`): Startup verification of 8 collections (dimensions, distance metric) wired into logos API lifespan. Non-fatal warnings. Fixed case-insensitive distance enum comparison (Qdrant returns `COSINE` not `Cosine`). 9 tests. Verified against live Qdrant.

**Schemathesis actionable findings:** (a) `POST /api/logos/directive` accepts `bool` for `detection_tier` field declared as `int | None` — Pydantic v2 lax mode coerces `bool→int`. (b) Missing error handling in `consent/create` (unhandled filesystem I/O), `consent/overhead` (unhandled ImportError), `engine/audit` (overbroad exception handler). (c) Environment-dependent 500s in `working-mode`/`cycle-mode` PUT (shell script not available in ASGI test) and `studio/moments/search` (Qdrant not reachable in test).

**Design document:** `docs/boundary-contract-enforcement.md` — full problem statement, design rationale, implementation details, smoke test results, failure triage, future work.

## Session 14 (2026-03-23): Ingestion Pipeline Audit + Classification Inspector + Design Language Completion

Infrastructure-only. No changes to experiment code, grounding theory, or research design.

**Three-round ingestion pipeline audit** — systematic multi-agent research of every ingestion path, data sink, consumer surface, and cross-type correlation opportunity across council + officium.

**Round 1 — Infrastructure Correctness (10 fixes):**
- Atomic dedup tracker in ingest.py (tmp+fsync+rename prevents crash corruption)
- Dead-letter queue for permanently failed ingest files (`~/.cache/rag-ingest/dead-letter.jsonl`)
- Removed orphan Qdrant collections (`samples`, `claude-memory`) from health/maintenance/digest lists
- Qdrant dimension validation in health checks (768-dim expected, studio-moments 768 not 512)
- Null-safety for Qdrant payloads in council `axiom_precedents.py` and `profile_store.py`
- Import `EXPECTED_EMBED_DIMENSIONS` in officium (was hardcoded 768)
- Perception state writer error escalation (debug → warning → error after 4 consecutive failures)
- Watch receiver input bounds (bpm≤300, rmssd_ms≤500, temp_c∈[20,45], readings≤500)
- Ported officium's enhanced flag validation to council agents route (blocklist + stricter regex)
- Pinned hapax-sdlc to same commit (`cbdf204`) across both projects

**Round 2 — Consumer Value Extraction (4 fixes):**
- Wired 10 sync agent profile-facts JSONL files into profiler's `load_structured_facts()` (bridge was designed in `profiler_sources.BRIDGED_SOURCE_TYPES` but never built)
- Wired `PatternStore.search()` into perception tick as step 4 (closes WS3 L3 loop — patterns are now retrieved, not just stored)
- Removed 12 dead perception state fields never read by any consumer
- Removed stale `llm_confidence`/`llm_activity` reads from workspace_monitor (fields not serialized to JSON)

**Round 3 — Cross-Type Correlation (4 fixes):**
- Serialized `llm_activity`, `llm_flow_hint`, `llm_confidence` to perception-state.json
- Re-enabled model disagreement tracking in workspace_monitor (local LLM vs Gemini)
- Enriched episode `summary_text` with heart rate and audio energy for biometric-aware pattern extraction
- Extended pattern consolidation LLM prompt to explicitly request biometric-AV correlations
- Enriched AV correlator with `speaker_count`, `max_people`, `scene_changes` from unused sidecar fields

**Classification Inspector (new feature):**
- `C` key overlay: dedicated per-camera classification diagnostic tool
- 12 toggleable channels (detections, gaze, emotion, posture, gesture, scene, action, motion, depth, trajectory, novelty, dwell)
- Theme-aware colors from `useTheme().palette` — switches with R&D/Research mode
- Live MJPEG camera feed with canvas-rendered detection boxes, enrichment chips, trajectory arrows, novelty halos, dwell indicators
- Confidence threshold slider, localStorage persistence
- Camera name mapping fix (VL `brio-operator` ↔ stream API `operator`)
- Enrichment chip placement: inside person box near top (not clipped by canvas edge)
- Exempt from design language §4 density rules and §5 signal caps (§7.2, §3.8)

**Signal Surfacing (7 items wired in visual_layer_aggregator):**
- Music genre → `secondary_ambient_text` when no scheduler content
- LLM activity → `secondary_ambient_text` when CLAP classification silent
- Episode boundary → `profile_state` signal (activity · duration · flow)
- Pattern match → `context_time` signal (prediction text + confidence)
- Model disagreement (CLAP vs LLM) → `profile_state` signal
- Dead-letter queue → `health_infra` signal
- Flow decomposition → `activity_detail` enrichment (gaze + posture + calm + quiet contributors)

**Overlay Design Language Compliance (11 fixes):**
- SignalPip sizes: 6/7/8/10 → 6/8/10 per §5.2
- ZoneCard severity: amber-400 → yellow-400 per §3.7
- ZoneOverlay: added voice_session + system_state zones, enforced max 3 signals per zone per §5.3
- OperatorVitals: stress pip 1s → 1.5s per §5.2, 4-step severity ladders (green/yellow/orange/red) for physiological load and phone battery per §3.7
- Inspector canvas backgrounds from `palette["zinc-950"]` per §8.2, overlay opacity 88% (match investigation)

**Design Language §3.8 Completion:**
- Complete detection color vocabulary: 5 object categories, 4 gaze directions, 6 emotion tints, 2 state colors, all with hex values
- Consent gating: suppression, operator preservation (camera role), confidence withholding, refusal removal
- IR preset palette (NightVision, Silhouette, Thermal IR) with high-saturation variants
- Breathing/novelty table, halo opacity rules, label/pill background rationale
- §3.7 cross-reference fix, §5.2 pip thresholds, §5.3 density constraints formalized
- §7.2 classification inspector exception, §10.4 signal backend resolved
- Stale "partially implemented" language removed from §5.3

**Hook fix:** work-resolution-gate now resolves git context from file path (cd to dirname), not CWD. Prevents cross-repo blocking when shell CWD drifts.

**Documentation:** Updated `logos-ui-reference.md` (inspector section, keyboard shortcuts, signal sources, detection overlay spec reference, flow decomposition, deep flow gate), `CLAUDE.md` (§3.8 cross-ref fix).

**PR #284** (feat/boundary-contracts branch): 3 commits, ~1400 insertions across 38 files. TypeScript clean, Vite build clean, 373 Python tests pass (2 pre-existing), all lint clean, 105/105 health checks passing, E2E verified via Playwright on dedicated Hyprland workspace.

## Operator Research Preferences

- Strip system to research essentials only
- Independent research agents per major concern
- Substrate independence: phenomena are implementation-agnostic
- Composable perspectives: decomposable, independently tappable
- Always CAPABLE model tier; willing to wait if justified
- Continuous cognitive loop, not request-response state machine
- No stale branches; PR completed work immediately
- Scientific register in all documentation; no rhetorical valence
