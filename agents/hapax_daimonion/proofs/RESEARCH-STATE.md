# Voice Grounding Research State

**Last updated:** 2026-03-31 (session 21 — temporal bands deep audit + intent gap closure)
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
- Phase A stability criterion: need 3 consecutive session means within 20% of phase mean. No sessions since Mar 25 — need fresh evening sessions to evaluate
- Sprint 0 gate: if DMN contradiction rate >15% or salience r < 0.1, must rescope those measures
- Cycle 3 contingency: if Cycle 2 shows RLHF non-compliance with Traum act directives, approach B (structural injection) needed
- Grounding acts coverage: system now instructs 5/7 Traum acts via directives; actual model compliance is the measurement target

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

## Session 19b (2026-03-29): Daimonion Full Treatment + VRAM Budget

Mixed R&D and infrastructure. No changes to experiment code or grounding theory.

**Daimonion full treatment (PR #427).** Formal tool capability model bringing tools into the Hapax recruitment meta-structure. `ToolCapability` dataclass with category, resource tier, consent requirements, backend dependencies, confirmation flag, and per-tool timeout. `ToolRegistry` with dynamic context-based filtering (stimmung, consent, backends, working mode). 26 tools migrated. Tool execution re-enabled (DEVIATION-026) with 3s per-tool timeout and bridge phrase coverage. Mode-driven grounding: always on in R&D, flag-controlled in Research. TPN_ACTIVE signaling to DMN via `/dev/shm/hapax-dmn/tpn_active`. 29 new tests. E2E verification script.

**VRAM budget resolution.** qwen3.5:27b (22GB) cannot coexist with daimonion (3GB STT+vision) + imagination (120MB) + DMN qwen3:4b (3.3GB) + embeddings (1GB) on a 24GB GPU. Caused VRAM emergency cycle: timer agents load 27b via LiteLLM → watchdog unloads → repeat every 30s. Fixed by downsizing reasoning/coding alias from qwen3.5:27b to qwen3:8b (5.2GB). Updated shared/config.py, LiteLLM proxy config, health monitor, scout. Total VRAM with all services: ~12.4GB, 12GB headroom.

## Session 19c (2026-03-29): VRAM Headroom Research + DMN Model Upgrade

Infrastructure optimization. No changes to experiment code or grounding theory.

**DMN model upgrade (PR #430).** Replaced qwen3:4b with qwen3.5:4b for both DMN pulse engine and perception classification backend. Intelligence Index improvement 18→27 (approaching old qwen3-80B-A3B quality). VRAM cost increased from ~3.3GB to ~5.6GB. Updated LiteLLM config, all code references, docs, tests.

**VRAM headroom research.** Comprehensive survey of upgrade options for the ~14GB headroom. Key findings:
- *Free upgrades:* qwen3.5:4b (done), faster-whisper large-v3-turbo (pending), YOLO26 (pending)
- *High-value additions:* qwen3.5:9b for on-demand reasoning (~5.5GB, tops IFBench), Moondream 2B for semantic scene VQA (~1GB), Chatterbox-Turbo for TTS (~4.5GB)
- *Not viable for coexistence:* Voxtral self-hosted (16GB), qwen3.5-35B-A3B (22GB), image generation (8-12GB)
- *No improvement needed:* nomic-embed-v2-moe already at efficiency frontier

**Updated VRAM budget:** Always-on ~13.1GB (53%), peak with reasoning ~18.3GB (75%), minimum headroom ~6.2GB.

**Impact on grounding research:** None. DMN quality improvement benefits situation modeling but does not affect experiment LLM paths.

**Impact on grounding research:** Tool re-enablement is gated by ToolContext — Research mode suppresses all tools unless `experiment_tools_enabled` flag is set. Phase A baseline continues unaffected. Model downsize changes the reasoning tier available to non-experiment agents but does not affect the voice daemon's experiment LLM path (routed through `balanced`/`fast` tiers).

## Session 20 (2026-03-31): Daimonion Gap Closure — Exhaustive Model-vs-Implementation Audit

Mixed R&D and research infrastructure. Changes to grounding directive text (DEVIATION-032). No changes to experiment state machine, DVs, or analysis infrastructure.

**Exhaustive audit.** Synthesized a unified model of daimonion from all conversations, design documents, and research from the last 3 days (50+ files, 80+ citations). Evaluated every claim against actual implementation code. Identified 7 gaps ranging from 20% to 90% fidelity.

**Gap 1: Mode-driven grounding activation (FIXED).** `pipeline_start.py` set `enable_grounding=True` in R&D mode but `conversation_pipeline.py` checks `grounding_directive`, `effort_modulation`, `cross_session` — different flag names. Fixed with `_apply_mode_grounding_defaults()` using `setdefault()`. R&D mode now activates all grounding features. Research mode still uses experiment config file. `experiment_mode=True` prevents override. 3 tests.

**Gap 2: Responsive grounding act directives (NEW, DEVIATION-032).** Extended `_STRATEGY_DIRECTIVES` to encode Traum's (1994) 5 responsive acts as directive text injected into VOLATILE band. REPAIR_1 → acknowledge + rephrase. REPAIR_2 → ask what's unclear. CONTESTED → acknowledge disagreement. GROUNDED → don't revisit. Neutral → check understanding. Approach A (directive-only) chosen over B (structural injection) to stay within pre-registered experiment framework. If Cycle 2 shows LLM non-compliance with directives, approach B is the Cycle 3 contingency. 6 tests.

**Gap 3: Vocal chain impingement wiring (FIXED).** `VocalChainCapability.can_resolve()` existed but nothing called it. Added `activate_from_impingement()` method that maps impingement dimensions to vocal chain MIDI dimensions. Wired into `impingement_consumer_loop` in `run_loops_aux.py`. DMN impingements with vocal affordances, stimmung shifts, or evaluative signals now activate Evil Pet + S-4 hardware modulation. 3 tests.

**Gap 4: ExpressionCoordinator wiring (FIXED).** `shared/expression.py` ExpressionCoordinator was initialized but never used by daimonion. Wired into impingement consumer: when multiple modalities recruited for the same impingement, coordinator distributes the source fragment to each. Closes queue #021 Phase 5 integration. 3 tests.

**Gap 5: Tool metadata completion (FIXED).** Added _META entries for 5 phone tools (find_phone, lock_phone, send_to_phone, media_control, phone_notifications). Registry now reports 30 capabilities (was 26). 2 tests.

**Gap 6: Documentation accuracy (FIXED).** Updated README: 9 async loops (was 5), 23 backends (was 8), updated package structure. Added Known Limitations section documenting RLHF compliance gap, keyword-based acceptance classification, and tick-driven cognitive loop.

**Impact on grounding research:** Gap 2 changes directive text in grounding_ledger.py (frozen experiment file). DEVIATION-032 filed. State machine logic unchanged. DVs unchanged. The new directive text will be active in Phase B (treatment) only when `grounding_directive` flag is true. Phase A baseline unaffected. Gap 1 makes grounding features default in R&D mode (non-experiment voice sessions) — this does not affect experiment sessions which use explicit config.

**Open question added:** Cycle 3 contingency: if Cycle 2 shows RLHF non-compliance with Traum act directives, approach B (structural act injection via prefilled assistant content or bridge phrases) becomes the next research direction.

## Session 21 (2026-03-31): Temporal Bands Deep Audit + Intent Gap Closure

R&D work on temporal subsystem (non-frozen paths). No changes to experiment code, grounding theory, or frozen files.

**Deep audit of temporal bands subsystem** (3-agent fan-out × 3 facets: structure, coverage, integration). Audited code quality AND design intent (WS1 spec) simultaneously. Findings: 80 tests passing, B+ quality, but biggest gap was the ProtentionEngine — instantiated and saved but `observe()` never called. Markov chain, flow timing model, and circadian model were always empty.

**PR #479 MERGED: Temporal bands audit fixes** (-312 net lines).
- Split 517-line `temporal_bands.py` into 4 modules (models, surprise, trend, formatter) for 300-line file size gate
- Wired `ProtentionEngine.observe()` into VLA perception tick — engine now learns from every 2.5s snapshot
- Added Pydantic field validators (confidence, surprise, age bounds), crash guards, NaN trend guards
- Narrowed 9x bare `except Exception` to specific types in apperception_tick
- Consolidated 3x `_read_temporal_block()` into `shared/temporal_shm.py`
- Deleted vendored `agents/_apperception_tick.py` (redirect to shared/)

**PR #480 MERGED: Multi-scale temporal + surprise ordering + A/B harness** (+923 lines).
- Multi-scale integration: `TemporalBandFormatter.format()` now accepts `MultiScaleContext`. XML output gains `<retention scale="minute">`, `<session_context>`, `<circadian>` sections alongside tick-level retention
- Surprise-weighted impression ordering: impression fields sorted by surprise ascending so high-surprise fields render last, exploiting RoPE's natural recency-attention boost (WS1 §2.1)
- Extracted `format_xml` to `agents/temporal_xml.py` (file size gate)
- A/B validation harness (Measure 3.1): 50 synthetic perception snapshots, 4-task battery, LLM-as-judge scoring on relevance/specificity/temporal_awareness/actionability, automated effect size + gate condition

**Intent gaps remaining (from WS1 spec):**
- Decay function comparison (3.4): exponential/power-law/stepped. Research design complete, pluggable `DecayStrategy` ABC defined, implementation ~1 session. Scheduled Day 9.
- Multi-scale retention not yet rendered by downstream consumers (phenomenal_context.py reads tick-level only). Low priority.
- A/B validation not yet executed (harness ready, run `uv run pytest tests/research/test_temporal_contrast.py -m llm -v`). Scheduled Day 3-4.

**Impact on grounding research:** None. All changes are on non-frozen temporal paths (`agents/temporal_*.py`, `shared/temporal_shm.py`, `shared/apperception_tick.py`). Temporal bands are upstream of phenomenal context (Layer 3-5) but do not affect grounding experiment variables or DVs. The protention engine now trains from live perception, which enriches temporal context quality for voice grounding — but this flows through `phenomenal_context.py` rendering, not through frozen experiment paths.

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
- Created `hapax-secrets.service`: centralized oneshot credential loader. All services now declare `Requires=hapax-secrets.service`. Eliminates 4x redundant `pass show` calls and race condition where logos-api read hapax-daimonion's env file without a dependency.
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

**Stale test repair (PR #287):** 9 test files updated to match intentional code changes. No code bugs — all failures were tests lagging behind API changes: STT model default (parakeet to distil-large-v3), perception guest_count property, removed search_conv_memory tool, notification path additions, 4 new nudge collectors, disabled cloud-skip feature, conversation buffer constant rename, profiler sync/watch fact sources, voice check process-compose httpx path. 20+ failures resolved.

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

## Session 15 (2026-03-24): System Feature Audit + Notification Wiring + Hapax-Bar Completion

Infrastructure-only. No changes to experiment code, grounding theory, or research design.

**Full system feature audit (110 features, 11 groups).** Comprehensive inventory of all Logos features across council API (16 endpoints), chat/interview (4), voice daemon (14), studio/visual (18), governance/consent (14), reactive engine (7), RAG/knowledge (7), profile (4), query dispatch (4), frontend (12), supporting systems (10). Result: 110/110 DONE. Five discrepancies investigated independently; findings added to compendium §21.

**Voice notification delivery wired (DEVIATION-010).** Added `ConversationPipeline.deliver_notification()` — direct TTS delivery during active silence, no LLM round-trip. Cognitive loop's `_handle_silence()` now dequeues from NotificationQueue and requeues on failure. Completes last-mile wiring for notification infrastructure (queue, router, listener all previously built but output path missing). Gated behind `active_silence_enabled` flag (off during experiment). 56/56 cognitive loop tests pass.

**Hapax-bar CostModule + PrivacyModule committed.** CostModule polls `/api/cost` every 5min, shows `[llm:$X.XX]` with severity coloring. PrivacyModule polls PipeWire `pw-dump` every 5s, shows `[cam]`/`[mic]` when capture nodes active. Note: bar v2 redesign (StimmungField + seam layer) happened concurrently — modules exist as standalone code but v2 layout uses stimmung field rather than discrete text indicators.

**PR #284 merged** (feat/boundary-contracts → main): resolved 3 merge conflicts (RESEARCH-STATE, DEVIATION-009, test_local_llm_gate), fixed gitleaks secrets-scan failure (home-directory-path in design doc), all 8 CI checks green.

**Documentation fixes:** Council CLAUDE.md reactive engine "12 rules" → 14. Workspace CLAUDE.md hapax-mcp "40 tools" → 34.

## Session 16 (2026-03-24): Langfuse Sync Fix + Documentation Update

Infrastructure-only. No changes to experiment code, grounding theory, or research design.

**Langfuse-sync timeout death spiral (PR #297, merged).** Incremental sync was fetching 5000 traces per run then making N+1 HTTP calls for per-trace observations, exceeding the 20-minute systemd timeout. Since state only saved on completion, the high-water mark never advanced — every subsequent run re-fetched the same 5000 traces. Three fixes: (1) cap incremental sync at 500 traces/run (timer catches up), (2) skip per-trace observation fetches for incremental runs, (3) progressive state checkpointing after each batch. Full sync unchanged.

**Cache-cleanup transient failure.** `cache-cleanup.service` failed overnight (transient — ran clean on re-execution). Cleared failed state.

**Documentation updates:**
- Added `CONTEXT-AS-COMPUTATION.md` and `dwarf-fortress-ai-game-state-research.md` to RESEARCH-INDEX.md (were on disk but not indexed)
- Updated RESEARCH-STATE.md with session 16

## Session 17 (2026-03-25): Perceptual System Hardening

Infrastructure-only. No changes to experiment code, grounding theory, or research design.

**Comprehensive perceptual system review and hardening (PR #322, merged).** Full correctness, consistency, and robustness audit of the perception–stimmung–apperception–visual-layer–GQI stack. 20 verified issues fixed across 6 batches (6 critical, 6 high, 5 moderate, 3 new findings discovered during research). 58 new tests added (239→297 total).

**Critical fixes (silent wrong results):**
- C1: Per-class stance thresholds — biometric dims can now reach DEGRADED (0.5× weight, threshold 0.40), cognitive reach CAUTIOUS (0.3× weight, threshold 0.15). Previously both structurally capped at CAUTIOUS regardless of raw severity.
- C2: WS3 stores (episode, correction, pattern) retry up to 5× at 60s intervals on Qdrant failure. Previously permanently disabled after single failure at startup.
- C3: Centered timestamps in `trend()` regression — fixes catastrophic float64 cancellation with POSIX timestamps (~1.7e9). Slope calculations were returning garbage.
- C4: Relaxed apperception retention gate — depth-4 events with high relevance (>0.5) AND strong valence (>0.3) now retained. Previously ~95% of events silently discarded.
- C5: Rumination breaker uses actual computed valence instead of fixed -0.1 sentinel. All sources now participate in rumination tracking.
- C6: Temporal file read once per apperception tick — prevents contradictory surprise+absence events from atomic file replacement between two reads.

**High fixes (correctness with practical impact):**
- H1: Safe int/float casts + fallback write in perception state writer (prevents stale state on non-numeric behavior values)
- H2: `replace_backend` checks availability before stopping old backend (prevents behavior orphaning)
- H4: Thread-safe deque for supplementary content
- H5: Event.emit() snapshots subscriber list (prevents callback skip on self-unsubscribe)
- H6: Fixed dead `readiness="collecting"` state (boolean flag instead of impossible float comparison)
- H7: Simplified IGNORE grounding branch (removed dead threshold comparison)

**Moderate fixes (design issues, latent risks):**
- M1: Epoch counter on /dev/shm files for cross-file consistency detection
- M2: _infer_activity() uses cached perception data instead of re-reading disk
- M3: Snapshot isolation for phenomenal context render() — all files read once at entry
- M4: De-escalation timer no longer reset on same-state ticks (enables proper cooldown expiry)
- M5: Effort hold counter preserved on same-rank turns (enables proper de-escalation)
- M6: 3s PERFORMATIVE exit hysteresis against ALERT signals

**New findings discovered during research:**
- N1: circadian_alignment now written to perception-state.json (was always default 0.5)
- N2: Stimmung serialized timestamp uses wall-clock time (was monotonic — cross-process comparison bomb)
- N3: Type-safe behavior accessors (_fval/_sval/_boolval/_optval replace untyped _bval)

**Spec:** `docs/superpowers/specs/2026-03-24-perceptual-system-hardening.md`
**Plan:** `docs/superpowers/plans/2026-03-24-perceptual-system-hardening.md`

**Impact on grounding research:** H7 simplifies IGNORE acceptance path (concern_overlap only). M5 fixes effort de-escalation hysteresis (was never reaching EFFICIENT from ELABORATIVE). C5 fixes rumination tracking for all sources. None affect experiment code directly — all changes are in the perceptual substrate consumed by the voice pipeline.

## Session 18 (2026-03-27): TTS Engine Swap — Kokoro+Piper → Voxtral API

Infrastructure-only. No changes to experiment code, grounding theory, or research design.

**TTS engine replacement (PR #371).** Replaced both local TTS engines (Kokoro 0.9.4 GPU, Piper CPU) with Mistral Voxtral TTS via hosted API (`voxtral-mini-tts-2603`). Voxtral outputs 24kHz — identical to Kokoro — so zero downstream audio pipeline changes. Voice cloning from 3s reference audio now available via `voxtral_ref_audio` config.

**Changes:** 17 files, -1058/+374 lines (net reduction). `tts.py` rewritten (streams from Mistral API, decodes base64 float32 PCM, converts to int16). `KokoroTTSService` → `VoxtralTTSService`. Config `kokoro_voice` → `voxtral_voice_id` + `voxtral_ref_audio`. All Piper code fully excised. Dependencies: `kokoro` and `piper-tts` removed, `mistralai>=2.1.0` added.

**Bug found:** `mistralai` 2.1.3 doesn't re-export `Mistral` at top level. Correct import: `from mistralai.client.sdk import Mistral`.

**Tests:** 17 Piper/Kokoro tests removed, 11 Voxtral tests added. 44 TTS-related tests passing. Conversation pipeline comment change required DEVIATION-021 (comment-only, no functional impact).

**Impact on grounding research:** None. TTS is downstream of all grounding evaluation. Sample rate unchanged (24kHz). Audio output format unchanged (PCM int16 mono). The `.synthesize(text, use_case)` interface is preserved. Latency profile shifts from ~100ms local to ~0.7s API streaming — this affects conversational cadence timing but not grounding mechanics. If API latency proves problematic for experiment conditions, local inference via vLLM-Omni is available as fallback.

## Session 19 (2026-03-29): Bayesian Validation Prep + Visual Pipeline + Rename

Mixed session: visual pipeline completion (R&D), infrastructure, and Bayesian validation prep.

**Bayesian validation R&D schedule created.** 21-day, 3-sprint schedule covering 27 measures across 6 tent-pole models. 7 decision gates with go/no-go criteria. Schedule in `docs/research/bayesian-validation-schedule.md`. Sprint 0 (Days 1-2) = instrumentation + quick analysis. Sprint 1 (Days 3-7) = core experiments. Sprint 2 (Days 8-14) = extended validation. Day 1 starts 2026-03-30.

**Sprint tracker agent deployed (PR #419).** Vault-native automation: reads completion signals from `/dev/shm/hapax-sprint/completed.jsonl`, updates Obsidian vault measure notes, evaluates decision gates, emits nudges. PostToolUse hook detects measure output files. 5-min systemd timer.

**Day 1 prep completed:**
- Phase A data verified: 431 activation_score + 431 context_anchor_success pairs in Langfuse (well above 50-pair threshold for measure 7.2). Sessions on Mar 21, 24, 25. No sessions since Mar 25 — fresh evening sessions needed for stability criterion.
- DMN impingement data confirmed: 355 entries in `/dev/shm/hapax-dmn/impingements.jsonl` (3.3MB, Mar 26-29). Ready for measure 4.1.
- DEVIATION-025 drafted for conversation_pipeline.py observability (3 `hapax_score()` calls: novelty, concern_overlap, dialog_feature_score). Filed at `research/protocols/deviations/DEVIATION-025.md`.
- Code change pre-planned: line 1161 of conversation_pipeline.py, inside existing `if _bd is not None:` block. `ActivationBreakdown` dataclass already has all 3 fields.
- Measure 6.2 (modulation_factor): confirmed NO deviation needed — can instrument entirely from non-frozen code (`shared/stimmung.py`, `_perception_state_writer.py`).
- Measure 6.3 (stimmung thresholds): clear integration point at `StimmungCollector.snapshot()` in `shared/stimmung.py` (not frozen).

**Hapax Reverie visual pipeline (PRs #400-#416).** Dynamic shader pipeline end-to-end: 51 WGSL nodes, content texture pipeline, temporal feedback buffers, 6 rendering techniques, 9-dimensional modulation. Python compiles effect presets into WGSL execution plans, Rust `DynamicPipeline` hot-reloads from `/dev/shm`. Named "Hapax Reverie" (2026-03-29).

**hapax-voice → hapax-daimonion rename (PR #421).** 600-file rename across entire codebase. Runtime migration to new data directories. All tests passing under new name.

**Infrastructure:**
- Auto-rebuild services for all Python services (PR #418). Path-based change detection, ntfy notifications, 5-min timer.
- Smoke test script: 55 checks across 5 tiers (PR #416).
- Fixed ambient classifier: pw-record targeting wrong source (virtual loopback → actual sink), killed 19 zombie processes, switched to Popen with explicit cleanup.
- Fixed plocate-updatedb: added `/store/data-backup` to PRUNEPATHS.
- Pi-6 sensor sync gap fixed, Google OAuth refreshed.

**Impact on grounding research:** None. Visual pipeline, infrastructure, and naming changes are all outside experiment code. DEVIATION-025 is observability-only (prepared, not yet executed). Phase A baseline collection continues unaffected.

## Operator Research Preferences

- Strip system to research essentials only
- Independent research agents per major concern
- Substrate independence: phenomena are implementation-agnostic
- Composable perspectives: decomposable, independently tappable
- Always CAPABLE model tier; willing to wait if justified
- Continuous cognitive loop, not request-response state machine
- No stale branches; PR completed work immediately
- Scientific register in all documentation; no rhetorical valence
