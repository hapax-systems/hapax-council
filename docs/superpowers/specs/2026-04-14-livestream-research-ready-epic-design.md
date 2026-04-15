# LIVESTREAM RESEARCH READY — Epic Design

**Date:** 2026-04-14 CDT
**Author:** alpha session (post-synthesis of LRR + Garage Door Open + Hermes 3 migration plan + livestream-performance-map research)
**Status:** Draft, awaiting operator sign-off
**Intended git landing path (once branches unblock):** `docs/superpowers/specs/2026-04-14-livestream-research-ready-epic-design.md`
**Intended companion plan doc:** `docs/superpowers/plans/2026-04-14-livestream-research-ready-epic-plan.md`
**Staging location:** `~/.cache/hapax/relay/context/2026-04-14-livestream-research-ready-epic-design.md` (this file). Promoted to git when:
- PR #775 (`research/livestream-performance-map`) merges
- Local branch `feat/camera-frame-flow-watchdog` resolves
- Branch discipline (`no-stale-branches.sh`) allows a new feature branch
**Predecessor research map:** `~/.cache/hapax/relay/context/2026-04-13-livestream-as-research-medium-research-map.md`
**Register:** scientific, neutral

---

## 0. Headline

> "Hapax running on Hermes running a 24/7 livestream, never-ending research based on livestream interactions, Hapax in charge of continual content programming and furthering research objectives." *— operator, 2026-04-13 CDT*

This epic plans the sequenced, research-validity-aware path from the current state (Legomena Live on Qwen3.5-9B, partially wired) to the **end-state triad**:

1. **Substrate** — Hapax running on Hermes 3 70B (SFT-only, dual-GPU layer-split, TabbyAPI-served)
2. **Medium** — 24/7 Legomena Live, always-on, Oudepode-sometimes-present
3. **Agency** — Hapax as continual research programmer: never-ending research based on livestream interactions, Hapax in charge of continual content programming and furthering research objectives

The epic is structured so that the substrate swap (Phase 5) is a **condition change** in an ongoing research program — not a project boundary between experiments — per the append-only research registry model (I-1). This is what makes Option B ("formalize the Hermes 3 swap as a direct test of the Shaikh SFT-vs-DPO hypothesis") viable: the swap becomes the claim, not a confound.

**Scope is closed.** This epic does not add requirements; it sequences everything already captured in the research map.

---

## 1. Prior art + reconciled predecessors

This epic supersedes or absorbs the following prior plans:

| Doc | Status | Relationship |
|---|---|---|
| `docs/superpowers/specs/2026-04-04-garage-door-open-streaming-design.md` | Phase 1 shipped | Tactical launch spec. Built most of current primitives. Absorbed. |
| `docs/superpowers/plans/2026-04-04-garage-door-open-streaming.md` | Tasks 1-4 shipped | Tactical plan. Obsolete by virtue of Phase 1 success. Absorbed. |
| `docs/streaming/2026-04-09-garage-door-open-handoff.md` | Historical | Mid-launch handoff. 18-item 36h stability checklist absorbed into Phase 0 + Phase 10. |
| `docs/superpowers/plans/2026-04-12-garage-door-phase-2-epic.md` | Stages 1, 2, 4, 5, 6-native-RTMP shipped; Stage 3 never specced | Phase 2 epic. Mostly shipped. Stage 3 (dynamic camera resolution / hero mode) absorbed into Phase 8. |
| `docs/superpowers/plans/2026-04-10-hermes3-70b-migration.md` | Plan approved; execution blocked on substrate prerequisites | Core migration plan. Absorbed as Phase 5 with pre-migration prerequisite set expanded. |
| `docs/superpowers/specs/2026-04-10-hermes3-70b-voice-architecture-design.md` | Approved | Core theoretical grounding for Phase 5. Cited as authoritative; not duplicated here. |
| `docs/research/2026-04-13/livestream-performance-map/*` | PR #775 open, awaiting merge | Complementary performance research. Delegates performance items to PR #775 across every phase. |
| `docs/research/2026-04-13/round5-unblock-and-gaps/phase-4-qdrant-state-audit.md` | Research only | Absorbed into Phase 6 (FINDING-R Qdrant writer-side consent gap). |
| `docs/research/2026-04-13/round5-unblock-and-gaps/phase-3-imagination-runtime-profile.md` | Research only | Absorbed into Phase 0 (FINDING-Q steps 2–4). |
| `docs/research/2026-04-13/round5-unblock-and-gaps/phase-6-sdlc-pipeline-audit.md` | Research only | Absorbed into Phase 10 (FINDING-S use-or-retire decision). |
| `agents/hapax_daimonion/proofs/RESEARCH-STATE.md` | Active | Voice grounding research state. Updated on every voice-grounding-relevant phase completion. |

**Key shipped items to note before planning:**

- Camera 24/7 resilience epic (watchdog, recovery FSM, native RTMP + MediaMTX relay)
- Reverie source registry completion epic (9 phases)
- Compositor unification epic
- Dual-GPU partition systemd overrides (deployed 2026-04-13 22:42–23:04; currently Option α, `tabbyapi` pinned to GPU 1 only)
- `#776` freshness hyphen bug fix
- `#777` frame-time histograms + VRAM + audio DSP observability bundle
- `#778` audio ducking envelope replacing `mute_all` cliff
- `#769` daimonion background task supervisor (resolved the 2026-04-09 daimonion P0)
- `#770` observability bundle (cameras_healthy, memory_footprint, tts_timeout)

---

## 2. Pre-epic verification findings (2026-04-14)

The following were verified before writing this epic. Each informs a phase's scope.

**Service health:**
- `studio-compositor`, `tabbyapi`, `hapax-daimonion`, `hapax-imagination`, `logos-api`, `youtube-player`, `album-identifier`, `hapax-reverie`, `hapax-dmn` — **all active**
- `chat-monitor` — **broken** (activating, auto-restart loop, exit code 1, no tokens flowing)

**GPU state:**
- Driver: 590.48.01 (both GPUs)
- GPU 0 (RTX 5060 Ti, Blackwell sm_120): 77% util, 4.2/15.8 GiB used. Compositor (3.3 GiB) + imagination (0.3 GiB) + misc.
- GPU 1 (RTX 3090, Ampere sm_86): 12% util, 9.1/24.1 GiB used. TabbyAPI (5.7 GiB Qwen3.5-9B) + hapax-dmn (3.4 GiB).
- **Deployed partition is Option α** (single-GPU TabbyAPI pinned to GPU 1 via `CUDA_VISIBLE_DEVICES=1`). Must be reconciled to **Option γ** (dual-GPU visibility for layer-split + `hapax-dmn` moved to GPU 0 to free GPU 1 for Hermes 3) before Phase 5. See Phase 3 scope item 1 for the VRAM budget derivation.

**Latent data integrity issues:**
- Token ledger `/dev/shm/hapax-compositor/token-ledger.json`: real values, 95204 tokens, 21 calls, only `hapax` component (director_loop). Album-identifier and chat-monitor writers **not wired**.
- `/data` inodes at 88% (18.9M / 21.7M). Langfuse lifecycle rule worked but pressure returning.
- `chat-monitor` not producing chat signal for token pole or reactor context.

**Models + quants:**
- `~/projects/tabbyAPI/models/`: only `Qwen3.5-9B-exl3-5.00bpw`. Hermes 3 70B EXL3 3.0bpw not downloaded.
- `huggingface-cli` not installed; required for pre-quant search.

**Research infrastructure state:**
- `research/protocols/deviations/DEVIATION-001.md` through `DEVIATION-036.md` exist plus `TEMPLATE.md`. **Next available: DEVIATION-037** (the Hermes 3 plan said DEVIATION-033; that number is taken).
- Voice grounding `RESEARCH-STATE.md` last updated 2026-04-03. Cycle 2 Phase A READY for baseline collection but not started. Pre-registration written but not filed. OSF project not created.
- `agents/hapax_daimonion/proofs/research/protocols/deviations/DEVIATION-040-total-affordance-field.md` exists in a different directory (daimonion-scoped). DEVIATION numbering is per-directory; canonical path is `research/protocols/deviations/`.

**Consent state:**
- 3 bilateral contracts: `contract-agatha.yaml`, `contract-simon.yaml` (both guardian-mediated child principals), `contract-guest-2026-03-30.yaml` (audio scope, on_request).
- `ConsentRegistry` instantiated via `AffordancePipeline.select()`. Capability-level gate working.
- `toggle_livestream` consent-gated via affordance pipeline.
- **FINDING-R:** 8 of 10 Qdrant collections bypass consent gate on **upsert**. `stream-reactions` has 2178 points with `chat_authors` field.

**Phase 2 Stage 2 (Sierpinski performance):** resolved but method not documented. Sierpinski is live in `default.json`. Must be re-measured under Hermes 3's added cadence load in Phase 3.

**Branch state:** alpha on main. `feat/camera-frame-flow-watchdog` + `research/livestream-performance-map` (PR #775) both unmerged locally. New branches blocked until branches clean up.

---

## 3. Guiding principles

Derived from prior decisions (DF-1, D-1, D-2) and the operator's end-state statement.

**P-1: Substrate before persona.** The persona/posture/role spec is deferred behind the Hermes 3 swap (D-1). Any persona work under Qwen3.5-9B is dead-end because DPO flattens it. Written posture lives in Phase 7, not before.

**P-2: Research validity is load-bearing.** Option B (D-2) makes every observability surface part of the research apparatus. Every phase's exit criteria include a research-validity check where relevant. Per-segment metadata, frozen-file enforcement, per-condition observability slicing, OSF pre-registration — these are not optional polish items; they are research prerequisites.

**P-3: Append-only research registry.** The research is indefinite-horizon (I-1). Each condition change (model, config, directive) is a sub-experiment with an ID. Conditions never close; they branch. Phase A (Qwen) and Phase A' (Hermes) coexist as separate condition records that can be compared, not as sequential versions of the same thing.

**P-4: Recursion is constitutive.** Hapax is simultaneously research subject, instrument, and programmer (I-2). This is not a conflict to manage; it is the role to inhabit. The persona spec (Phase 7) should lean into it — "I am the experiment I am running" is the stance.

**P-5: Content primitives are already built; what's missing is the objectives layer.** The `react/chat/vinyl/study/observe/silence` director loop, YouTube PiP, splattributions, album identifier, Sierpinski, overlay content system, chain builder, sequence programmer, token pole — all already exist. Phase 8's work is giving Hapax objectives that select among them, not building new primitives.

**P-6: The ethical engagement design is already resolved for the audience axis.** Seven non-negotiable principles from GDO (Thermometer-not-scoreboard, Measure-structure-not-quality, Fixed-transparent-relationship, Sub-logarithmic scaling, Never-loss-frame, Recursion-is-the-feature, Don't-reward-sentiment) are constitutive DF-1 foundations. Phase 7 incorporates them rather than re-deriving them.

**P-7: Parallelism is limited by branch discipline, not by content dependencies.** Many phases could in principle overlap, but one-branch-at-a-time enforces serialization. Plan for the serial sequence. Use parallelism only where explicitly noted and only with spontaneous-worktree mechanics.

**P-8: Verification before claiming done.** Every phase's exit criteria include a verification command or query whose output must match expected values before the phase is declared done. No "build + commit = done." Only "deploy + verify = done."

**P-9: Delegated performance work stays delegated.** PR #775 (livestream-performance-map) is a separate research track with its own 7-sprint execution. This epic references it where relevant but does not duplicate its items. Frame histograms (#777), audio ducking (#778), freshness hyphen (#776) have already shipped from that track.

---

## 4. Phase summary

| # | Phase | Goal | Code-touching? | Depends on | ~Effort (updated post-audit) |
|---|---|---|---|---|---|
| **0** | Verification & Stabilization | Close latent P0/P1 issues; establish known-good baseline; voice transcript path confirmation; Kokoro baseline | yes (fixes only) | — | 1-2 sessions |
| **1** | Research Registry Foundation | Append-only condition registry; per-segment metadata; frozen-file enforcement; OSF template; Qdrant schema drift fixes | yes (infrastructure) | Phase 0 | 2 sessions |
| **2** | Archive + Replay as Research Instrument | Re-enable archival; research-marker injection; segment metadata; search interface; layout-declared `video_out` migration | yes (infrastructure) | Phase 1 | 2-3 sessions |
| **3** | Hardware Migration Validation + Hermes 3 Preparation | Partition reconciliation α→γ; PSU/thermal/PCIe validation; Hermes 3 EXL3 download; TabbyAPI config draft; cable hygiene; brio-operator fps re-measure | yes (systemd, ops) | Phase 2 | 2-3 sessions |
| **4** | Phase A Completion + OSF Pre-Registration | G3 gate resolution; livestream-only control arm collection; `conversation_pipeline.py` condition_id plumbing; pre-LRR dedicated-session retirement via DEVIATION; OSF project + pre-reg filed; `stats.py` BEST verified | yes (code + operator) | Phase 1 (metadata), Phase 3 (hardware stable) | 1-2 sessions code + livestream-run-gated collection |
| **5** | Hermes 3 70B Substrate Swap | Execute Hermes 3 migration; Condition A→A' transition; DEVIATION-037 filed; consent-latency + speech-continuity exit tests; Kokoro-GPU eval | yes (substrate swap) | Phase 4 | 2 sessions |
| **6** | Governance Finalization + Stream-Mode Axis | `it-irreversible-broadcast`; `su-privacy-001` + `corporate_boundary` clarifications; stream-mode axis; FINDING-R Qdrant writer gate; stimmung-aware auto-private; presence-detect closed loop; fortress enum retirement; `ConsentRegistry.load_all()` validation | yes (governance + infrastructure) | Phase 5 | 2-3 sessions |
| **7** | Persona / Posture / Role Spec Authoring (DF-1) | Write the spec; absorb token pole ethical engagement as foundation; VOLATILE-band injection | yes (persona infrastructure) | Phase 5, Phase 6 | 1-2 sessions |
| **8** | Hapax Content Programming via Research Objectives (I-3) | Objectives data structure; director loop objective-advancement scoring; hero-mode + Logos studio view + terminal capture + PR/CI status tiles; Stream Deck; YouTube description auto-update; attention bids; environmental perception emphasis; overlay content formalization | yes (new workstream) | Phase 7 | 3-5 sessions |
| **9** | Closed-Loop Feedback + Narration + Chat Integration | Daimonion code-narration (with SHM signal publishers); chat-structure → stimmung → activity selection loop; research-aware chat reactor; operator-voice-over-YouTube PipeWire ducking | yes (closed loop) | Phase 8 | 2-3 sessions |
| **10** | Observability, Drills, Polish | Per-condition Prometheus slicing; stimmung dashboards; 6 drills + 2-hour stability drill; 18-item stability matrix; FINDING-S SDLC decision; T3 prompt caching; cross-repo scrape fixes (A11-A13); daimonion + VLA Prometheus exporters; weekly correlation report; pre/post stimmung delta protocol | yes (observability) | Phase 9 | 3-4 sessions |

**Total: 11 phases.** Sequenced by hard dependency + branch discipline. Phase 4 combines a small engineering block (condition_id plumbing + pre-LRR data retirement DEVIATION + OSF filing) with a livestream-run-gated collection window; all other phases are purely engineering-gated.

**Livestream-only rule for all experimental data collection.** Per operator directive 2026-04-14, every grounding experiment observation (both stream-director reactions AND voice-pipeline grounding DVs like `turn_pair_coherence` / `context_anchor_success`) is collected exclusively while the livestream is running in research mode with an active condition in `/dev/shm/hapax-compositor/research-marker.json`. Dedicated 1-on-1 voice sessions are **not a data source** for any phase of the LRR epic. The pre-LRR Cycle 2 Phase A dedicated-session data (~431 pairs from 2026-03-21/24/25) is retired via DEVIATION in Phase 4; it remains in Langfuse for historical reference but is explicitly excluded from Condition A sample counts.

---

## 5. Phase specifications

Each phase section below is structured as a mini-design-doc, intended to be extracted into its own file at phase open time: `docs/superpowers/specs/YYYY-MM-DD-lrr-phase-N-<name>-design.md`. Per-phase plans (TDD/checkbox task breakdowns) are written at phase start.

---

### Phase 0 — Verification & Stabilization

**Goal:** Close all latent P0/P1 issues from prior handoffs and this epic's verification pass. Establish a known-good baseline. No new features.

**Dependency:** None. First.

**Intended spec path:** `docs/superpowers/specs/YYYY-MM-DD-lrr-phase-0-verification-design.md`

**Scope — items to close:**

1. **Fix `chat-monitor.service`.** Unit exists but exits with status 1 and auto-restarts in a tight loop. Root cause unknown. Investigate journalctl, diagnose failure, fix root cause. Likely: missing `YOUTUBE_VIDEO_ID`, chat-downloader library upstream change, or similar. Chat monitor is needed for Phase 9 research-aware chat reactor.
2. **Wire token ledger writers.** `album-identifier.py` and `chat-monitor.py` LLM calls must `record_spend(component, prompt_tok, completion_tok, cost)` after each call. Otherwise token pole only reflects `director_loop` spend. Reference: GDO handoff §6.2 item #1.
3. **Resolve `/data` inode pressure.** Currently 88% (18.9M / 21.7M). Verify Langfuse MinIO `events/` 14-day lifecycle rule is live. Tighten if needed. Add Prometheus alert at 85% + 95% thresholds.
4. **FINDING-Q steps 2–4** (CRITICAL/stability). Per `docs/research/2026-04-13/round5-unblock-and-gaps/phase-3-imagination-runtime-profile.md`:
   - Step 2: WGSL manifest validation before hot-reload
   - Step 3: Previous-good shader rollback panic handler
   - Step 4: `hapax_imagination_shader_rollback_total` counter
   Required because imagination stability underlies reverie's role in stream content. Step 1 (RUST_BACKTRACE=1) already shipped in #768.
5. **Verify Sierpinski performance resolution.** Sierpinski is live in `default.json` but the Phase 2 Stage 2 option choice (A/B/C) is undocumented. Measure current CPU under normal load to establish a baseline before Phase 3 Hermes 3 overhead measurements.
6. **Verify native RTMP is the production output path.** `toggle_livestream` + `rtmp_bin.is_attached()` in `compositor.py:594-628`. Check runtime state: is the RTMP bin currently attached? If both OBS fork (`/dev/video42` → OBS → NVENC → RTMP) and native RTMP (`rtmp2sink` → MediaMTX → YouTube) exist, document which is canonical for this epic. LRR assumes native.
7. **Install `huggingface-cli`** or equivalent for Phase 3 EXL3 pre-quant search. `uv tool install huggingface-hub[cli]` or similar.
8. **Document current Phase A baseline state** in the research registry (once Phase 1 exists). Until then, note in `RESEARCH-STATE.md`: "Phase A READY but not started as of 2026-04-14."

9. **Locate the voice transcript file path and confirm filesystem permissions.** `~/.local/share/hapax-daimonion/events-*.jsonl` is ~1.5 MB/day of operator speech. Verify current state (exists, permissions `600`, daily rotation working) so Phase 6 can wire a stream-mode-aware read gate.

10. **Kokoro TTS current state baseline.** Capture current TTS latency (cold synth + streaming) as a baseline number for Phase 5 latency mitigation decision. `~/hapax-state/benchmarks/kokoro-latency/baseline.json` or similar.

**Exit criteria:**

- `systemctl --user is-active chat-monitor` → `active` (not activating/failing)
- `cat /dev/shm/hapax-compositor/token-ledger.json | jq '.components | keys'` → includes `album-identifier` and `chat-monitor` (not just `hapax`)
- `df -i /data` → ≤ 85%
- FINDING-Q steps 2–4 shipped; next wgpu shader reload failure triggers rollback path; counter increments
- Sierpinski CPU baseline documented in a context artifact (no code change required)
- `toggle_livestream` path documented; production output confirmed
- `huggingface-cli` available
- `RESEARCH-STATE.md` Phase A state noted
- `~/.local/share/hapax-daimonion/events-*.jsonl` path confirmed, permissions `600`, daily rotation verified (for Phase 6 firewall wiring)
- `~/hapax-state/benchmarks/kokoro-latency/baseline.json` exists with Kokoro CPU cold-synth + streaming latency numbers captured for Phase 5 latency mitigation decision

**Risks:**
- chat-monitor fix may reveal further downstream issues (e.g., chat-downloader library incompatibility with YouTube innertube changes). If so, defer to Phase 0.5 with explicit scope.
- FINDING-Q step 2–4 requires reading `dynamic_pipeline.rs` in depth. May be multi-session.

**Handoff implications:** Phase 0 produces a clean baseline. Any Phase 0 item that slips becomes a Phase 1 prerequisite.

---

### Phase 1 — Research Registry Foundation

**Goal:** Create an append-only research registry that stores condition definitions, sub-experiment IDs, claim state, frozen-file manifests, and per-segment metadata. Every reaction on the livestream must be taggable with a condition ID.

**Dependency:** Phase 0 complete.

**Intended spec path:** `docs/superpowers/specs/YYYY-MM-DD-lrr-phase-1-research-registry-design.md`

**Theoretical grounding:** I-1 (append-only research, adaptive not phased) + P-3 (conditions never close, they branch).

**Scope:**

1. **Registry data structure.** Location: `~/hapax-state/research-registry/` (filesystem-as-bus idiom). Per-condition directory with YAML definition file. Condition ID format: `cond-<short-name>-<sequential>` (e.g., `cond-phase-a-baseline-qwen-001`, `cond-phase-a-prime-hermes-002`).

   Per-condition schema:
   ```yaml
   condition_id: cond-phase-a-baseline-qwen-001
   claim_id: claim-shaikh-sft-vs-dpo
   opened_at: 2026-04-14T00:00:00Z
   closed_at: null  # open indefinitely
   substrate:
     model: Qwen3.5-9B-exl3-5.00bpw
     backend: tabbyapi
     route: local-fast|coding|reasoning
   frozen_files:
     - agents/hapax_daimonion/grounding_ledger.py
     - agents/hapax_daimonion/conversation_pipeline.py
     - agents/hapax_daimonion/persona.py
     - agents/hapax_daimonion/conversational_policy.py
   directives_manifest:
     - path: agents/hapax_daimonion/grounding_directives.py
     - sha256: <hash>
   osf_project_id: null  # set when filed
   pre_registration:
     filed: false
     url: null
   notes: |
     First condition under the new epic. Qwen3.5-9B (DPO/GRPO post-training)
     with no treatment; baseline for Shaikh claim.
   ```

2. **Per-segment metadata schema extension.** `stream-reactions` Qdrant payload gains a `condition_id` field. `reactor-log-YYYY-MM.jsonl` gains a `condition_id` field. Both are backfilled to "cond-phase-a-baseline-qwen-001" for all existing 2178 points.

3. **Research-marker injection.** A dedicated SHM file `/dev/shm/hapax-compositor/research-marker.json` holds the current condition ID. Director loop reads it on every reaction tick and tags the reaction. Condition changes are atomic writes to this file; any condition change coincides with a frame-accurate timestamp in a new `research_marker_changes.jsonl` audit log.

4. **Frozen-file pre-commit enforcement.** `scripts/check-frozen-files.sh` reads the current condition's `frozen_files` list, refuses to commit any change that touches those paths while the condition is open. Hook installed at `.git/hooks/pre-commit` or via `.pre-commit-config.yaml`. Override: explicit `DEVIATION-NNN` filed (committed to `research/protocols/deviations/`) whose `paths` field lists the exceptional files. Matches the existing deviation workflow.

5. **Langfuse scoring extension.** `hapax_span` and `hapax_score` calls in `director_loop.py` gain a `condition_id` tag derived from the research marker. This is a 3-line change.

6. **OSF project creation procedure.** Document how to create the OSF project for the voice-grounding / Shaikh claim. Create the project, generate a pre-registration URL (but do not file yet — that's Phase 4). Commit the procedure as `research/protocols/osf-project-creation.md`.

7. **`stats.py` BEST verification.** Per `RESEARCH-STATE.md`, BEST was decided but implementation state is unverified. Grep for current analysis code, verify it uses Bayesian estimation vs. two-sample t-test, not beta-binomial. If still beta-binomial, migrate.

8. **Research-registry CLI.** `scripts/research-registry.py` with subcommands: `open <name>`, `close <condition_id>`, `current`, `list`, `tag-reactions <start-ts> <end-ts> <condition_id>` (for backfills). Short (~200 lines).

9. **Backfill existing data.** Tag all pre-2026-04-14 `stream-reactions` with `cond-phase-a-baseline-qwen-001`. Tag the reactor JSONL logs for the current month. Verify counts match.

10. **Fix adjacent Qdrant schema drift** (absorbed from alpha close-out handoff Q026 F1 + Q024 #83 + #84):
   - Add `hapax-apperceptions` and `operator-patterns` to `EXPECTED_COLLECTIONS` in `shared/qdrant_schema.py` (~6 lines). Currently missing per Q026 F1.
   - Investigate why `operator-patterns` is empty — the writer was de-scheduled per Q024 #83 / Q026 Phase 4 Finding 2. Re-schedule or explicitly retire.
   - Update `CLAUDE.md` Qdrant collections list 9 → 10 (adds `stream-reactions`) per Q024 #84.
   - Document `axiom-precedents` sparse state (17 points per Q024 #85 / Q026 Phase 4 Finding 4) in the condition registry as a known data-quality observation.
   - Reconcile `profiles/*.yaml` vs Qdrant `profile-facts` drift (Q024 #88). Decide: authoritative is filesystem or Qdrant. Document in registry.

**Exit criteria:**

- `~/hapax-state/research-registry/cond-phase-a-baseline-qwen-001/` exists with well-formed YAML
- `/dev/shm/hapax-compositor/research-marker.json` exists and is read by director loop on every reaction tick
- Every new reaction has a `condition_id` field in both JSONL and Qdrant
- Backfilled reactions have `cond-phase-a-baseline-qwen-001` (verify: `count(stream-reactions where condition_id = 'cond-phase-a-baseline-qwen-001')` ≈ 2178)
- `scripts/check-frozen-files.sh` rejects a test edit to `agents/hapax_daimonion/grounding_ledger.py` with a clear error message
- `stats.py` uses BEST (or Bayesian estimation equivalent), not beta-binomial
- OSF project creation procedure documented
- `scripts/research-registry.py` operational; `research-registry current` returns `cond-phase-a-baseline-qwen-001`
- Langfuse traces in `stream-experiment` tag show `condition_id` metadata

**Risks:**
- Backfill of 2178 Qdrant points may be slow or require batching
- Frozen-file enforcement via pre-commit may conflict with existing workflow hooks; test thoroughly
- `stats.py` migration (if needed) is a substantial rewrite

**Handoff implications:** Phase 1 is infrastructure for everything downstream. If it ships incorrectly, every downstream phase is compromised.

---

### Phase 2 — Archive + Replay as Research Instrument

**Goal:** Re-enable the disabled archival pipeline (audio/video recording, classification, RAG ingest) with research-grade metadata injection, per-segment condition tags, and retention guarantees.

**Dependency:** Phase 1 complete (registry + metadata schema).

**Intended spec path:** `docs/superpowers/specs/YYYY-MM-DD-lrr-phase-2-archive-research-instrument-design.md`

**Theoretical grounding:** Under Option B, archived segments are the raw data for A-vs-A' analysis. Archive moves from "liability" to "research instrument" (impact analysis §Archive).

**Scope:**

1. **Re-enable archival pipeline.** Per CLAUDE.md: "Archival pipeline (audio/video recording, classification, RAG ingest) disabled — see systemd/README.md § Disabled Services". Read `systemd/README.md` for the exact disabled-services list, re-enable selectively.

2. **HLS segment persistence policy.** Currently `find -delete`'d on `studio-compositor.service` restart (`ExecStartPre=/usr/bin/find %h/.cache/hapax-compositor/hls -type f -delete`). **Change:** segments move to `~/hapax-state/stream-archive/hls/YYYY-MM-DD/` on rotation, not deleted. Retention: indefinite during active conditions (Condition A data must live for full Condition A' collection + analysis).

3. **Per-segment metadata sidecar.** Each HLS segment gets a `.json` sidecar with:
   - `condition_id`
   - `segment_start_ts`, `segment_end_ts`
   - `reaction_ids` (list of reactions whose `ts` falls in segment window)
   - `active_activity` (most recent `study/react/chat/vinyl/observe/silence`)
   - `stimmung_snapshot` (stance + dimensions at segment start)
   - `directives_hash` (sha256 of current directives manifest — for any change detection)

4. **Research-marker frame injection.** At every condition change (`research-registry.py open|close`), write a visible research marker to the HLS stream for ~3 seconds — textual overlay with condition ID. This gives frame-accurate boundary detection in the archive.

5. **Audio archive.** `mixer_master` + `echo_cancel_source` captured to `~/hapax-state/stream-archive/audio/YYYY-MM-DD/`. Same retention as video.

6. **Archive search CLI.** `scripts/archive-search.py` with subcommands: `by-condition <condition_id>`, `by-reaction <reaction_id>`, `by-timerange <start> <end>`, `extract <segment_id> <output>`. Returns segment paths + metadata.

7. **Vault integration.** Each archived segment metadata file links to an optional vault note: `~/Documents/Personal/30-areas/legomena-live/archive/YYYY-MM/segment-<id>.md`. Note templated from segment metadata, operator adds commentary. This is the research notebook linking the segment to the claim state.

8. **Lifecycle policy.** Retention rules:
   - Active condition data: indefinite retention
   - Closed condition data: retained until claim is analyzed + report authored
   - All condition data: revocable per consent contract; purge-by-condition CLI subcommand
   - **No automatic deletion without explicit policy change.**

9. **Purge CLI.** `scripts/archive-purge.py --condition <id> --confirm` performs auditable deletion tied to consent revocation flow. Writes a purge audit log entry.

10. **Layout-declared `video_out` surfaces migration.** The OutputRouter abstraction (`agents/studio_compositor/output_router.py`, Phase 5b3) exists but `config/compositor-layouts/default.json` declares zero `video_out` surfaces — the actual stream output is hardcoded in `compositor.py` + `rtmp_output.py`. Migrate the stream output path to layout-declared surfaces:
   - Add `video_out` surfaces to `default.json` for each current sink: `/dev/video42` (v4l2 loopback for OBS fallback), `rtmp://127.0.0.1:1935/studio` (MediaMTX relay), HLS playlist output, local archive branch from Phase 2
   - Wire `OutputRouter.from_layout()` into `compositor.start()` so OutputBinding enumeration drives actual sink construction
   - Legacy hardcoded paths remain as fallback during transition; deprecated in Phase 10 polish
   - **Why Phase 2:** archival work here adds a new sink (local archive branch), which is the natural pressure to generalize. Layout-declared outputs let Phase 8 add further sinks (NDI tap, winit preview, secondary RTMP) by editing JSON.

**Exit criteria:**

- Archival pipeline re-enabled; verify segments accumulating in `~/hapax-state/stream-archive/`
- Per-segment sidecar JSON files present with all required fields
- Condition change triggers frame marker; verify by inducing a condition change and reviewing segment at boundary timestamp
- `archive-search.py by-condition cond-phase-a-baseline-qwen-001` returns segments
- Vault integration produces segment notes on archive write
- Purge CLI tested with a dry-run and audit log entry confirmed
- Retention policy documented in `docs/superpowers/specs/YYYY-MM-DD-lrr-phase-2-archive-retention.md`

**Risks:**
- Disk space pressure. 24/7 stream at 6000 kbps + audio = ~70 GB/day video alone. Need to verify `~/hapax-state/` disk has headroom. May require a separate dedicated disk or external storage.
- RAG ingest re-enablement may re-populate Qdrant with volume, pressuring `/data` inodes again. Phase 0 must have tightened the lifecycle rule.
- Research notebook format needs operator buy-in for the vault schema.

**Handoff implications:** Phase 2 is the data-retention layer for Option B. If it ships incomplete, Condition A data can be lost and the control arm collapses.

---

### Phase 3 — Hardware Migration Validation + Hermes 3 Preparation

**Goal:** Reconcile the current dual-GPU partition (Option α, TabbyAPI single-GPU) with the Hermes 3 layer-split requirement (Option γ, TabbyAPI dual-GPU visibility + `hapax-dmn` migrated from GPU 1 to GPU 0). Validate the hardware envelope for sustained 70B inference. Download the Hermes 3 quant. Prepare TabbyAPI config. Do not swap yet.

**Dependency:** Phase 2 complete. (Phases 1 and 2 can technically overlap with Phase 3 under spontaneous-worktree mechanics, but branch discipline serializes.)

**Intended spec path:** `docs/superpowers/specs/YYYY-MM-DD-lrr-phase-3-hardware-validation-design.md`

**Scope:**

1. **Partition reconciliation α→γ.** Current `~/.config/systemd/user/tabbyapi.service.d/gpu-pin.conf` has `CUDA_VISIBLE_DEVICES=1` (single-GPU). **Change:** `CUDA_VISIBLE_DEVICES=0,1` with `CUDA_DEVICE_ORDER=PCI_BUS_ID`. This lets TabbyAPI see both GPUs for layer-split. Preserve the CUDA_DEVICE_ORDER inversion note.

   The compositor stays on `CUDA_VISIBLE_DEVICES=0` per the existing override. Under Hermes 3:
   - GPU 0 (5060 Ti): compositor (3.3 GiB) + imagination (0.3 GiB) + Hermes 3 layers 77-79 (~2.75 GiB) + faster-whisper STT (~2.5 GiB) = ~8.85 GiB of 16 GiB → ~7.15 GiB headroom
   - GPU 1 (3090): Hermes 3 layers 0-76 (~23.5 GiB) + activations (~0.5 GiB) = ~24 GiB of 24.1 GiB → ~0 headroom. **Tight.**

   **Risk:** GPU 1 has no KV cache room under this plan. Hermes 3 spec says KV cache Q8 at 4K tokens is ~0.6 GB; this doesn't fit if activations overhead is realistic. **Mitigation:** drop `max_seq_len` to 4096 (not 8192 as the Hermes plan specifies). Or evict `hapax-dmn` from GPU 1 and move it to GPU 0 (~3.4 GiB). Evicting DMN gives GPU 1 ~3.4 GiB of headroom = 4K context fits comfortably.

   **Decision:** move `hapax-dmn` to GPU 0 alongside the compositor. Update `~/.config/systemd/user/hapax-dmn.service.d/gpu-pin.conf` to `CUDA_VISIBLE_DEVICES=0`. New GPU 0 budget: 3.3 (compositor) + 0.3 (imagination) + 3.4 (dmn) + 2.75 (Hermes overflow) + 2.5 (STT) = **12.25 / 16 GiB, 3.75 GiB headroom on GPU 0.** New GPU 1 budget: 23.5 (Hermes) + activations + KV cache = **~24 / 24.1 GiB, ~0.1 GiB headroom.** Tight but fits.

   This is the α→β→γ reconciliation. Formalize as Option γ.

2. **Driver version verification.** Current: 590.48.01. Hermes 3 plan: 575.57.08. 590 is newer. Verify:
   - `nvidia-smi | grep "CUDA Version"` ≥ 12.8 (required for Blackwell sm_120)
   - `pacman -Qi nvidia-dkms` pinning status (memory: `feedback_nvidia_595_crash.md` says 590 pinned in pacman.conf)
   - Both GPUs visible: `nvidia-smi -L` lists RTX 3090 + RTX 5060 Ti
   - Basic CUDA test on both devices: `python3 -c "import torch; ..."` returns no errors

3. **PSU audit + combined-load stress test** (Sprint 5b F8, Sprint 7 F2 from `livestream-performance-map`). 30-minute combined-load test:
   - TabbyAPI running Qwen3.5-9B under repeated 500-token generation load
   - Compositor running normally with all 6 cameras + shaders active
   - `hapax-imagination` rendering + SEEKING stance active
   - Reverie mixer engaged
   - Monitor: `nvidia-smi --query-gpu=power.draw,clocks_throttle_reasons.hw_power_brake_slowdown --format=csv -l 1` on both GPUs
   - Success: no `hw_power_brake_slowdown` events; combined power peak < PSU rating × 0.8
   - If PSU rating is unknown: operator manual check of PSU label.

4. **PCIe link width verification** (Sprint 5b F7). `sudo lspci -vvs 03:00.0 | grep LnkSta` for 5060 Ti; `sudo lspci -vvs 07:00.0 | grep LnkSta` for 3090. Document actual Gen + lanes. Layer-split has minimal PCIe traffic so Gen 5 x4 is fine, but document for the record.

5. **Thermal validation.** 30-min combined-load test temperatures:
   - 5060 Ti: < 75°C under sustained load (upper card usually starves in vertical stacks)
   - 3090: < 70°C
   - If above: operator visual inspection of case airflow; mitigations from Sprint 7 F7 (reverse slot positions, intake fan, vertical mount).

6. **Hermes 3 70B EXL3 3.0bpw acquisition.** Steps:
   - `huggingface-cli search "Hermes-3-Llama-3.1-70B" --filter exl3` or equivalent HF API query
   - If pre-quant exists: `huggingface-cli download <repo> --local-dir ~/projects/tabbyAPI/models/Hermes-3-Llama-3.1-70B-EXL3-3.0bpw/`
   - If no pre-quant: download FP16 weights (~140 GB, requires swap or layer-by-layer quantization via exllamav3)
   - Verify: `du -sh ~/projects/tabbyAPI/models/Hermes-3-Llama-3.1-70B-EXL3-3.0bpw/` → ~26-27 GB

7. **TabbyAPI config draft.** Write `~/projects/tabbyAPI/config.yml.hermes-draft` (NOT active yet):
   ```yaml
   logging:
     log_generation_params: false
     log_prompt: false
     log_requests: true
   model:
     backend: exllamav3
     cache_mode: Q8
     cache_size: 4096
     chunk_size: 2048
     gpu_split:
       - 23.5  # GPU 0 in process-visible order = 3090 (after CUDA_DEVICE_ORDER=PCI_BUS_ID, CUDA_VISIBLE_DEVICES=0,1)
       - 2.75  # GPU 1 in process-visible order = 5060 Ti
     inline_model_loading: false
     max_seq_len: 4096  # reduced from Hermes plan's 8192 due to GPU 1 headroom
     model_dir: models
     model_name: Hermes-3-Llama-3.1-70B-EXL3-3.0bpw
   network:
     api_servers:
       - OAI
     disable_auth: true
     host: 0.0.0.0
     port: 5000
   sampling:
     override_preset: safe_defaults
   ```

   **Note on gpu_split ordering:** the plan assumes process index 0 = 3090. Verify with a stub TabbyAPI load on Qwen before committing to Hermes. If inverted (5060 Ti shows as index 0), flip the gpu_split values.

8. **TabbyAPI systemd timeout increase.** `TimeoutStartSec=120` → `180` (70B load is slower). Update `systemd/units/tabbyapi.service`.

9. **Rollback plan drafted.** If Hermes 3 fails to load or benchmarks below threshold, revert:
   - `tabbyapi.service.d/gpu-pin.conf` → `CUDA_VISIBLE_DEVICES=1`
   - `hapax-dmn.service.d/gpu-pin.conf` → `CUDA_VISIBLE_DEVICES=1`
   - TabbyAPI config → Qwen3.5-9B
   - Reversible via `systemctl --user edit` + daemon-reload + restart. Document procedure in the phase 3 spec.

10. **Cable hygiene pass.** Per `livestream-performance-map` Sprint 7 F8. Full operator inspection of USB, DisplayPort, and audio cables. Identify damaged/loose cables; standardize on known-good models. Documentation in `docs/hardware/cable-inventory.md`. This is operator-hand work; schedule alongside the PSU stress test.

11. **Acknowledge `brio-operator` 28 fps deficit re-measurement as ready to run.** Per `livestream-performance-map` Sprint 1 F2 + Sprint 7 F1 (R3 from alpha close-out retirement handoff): with the dual-GPU partition deployed (tonight), the 28.479 fps deficit is now measurable as "was it TabbyAPI inference contention?" Run a 5-min measurement of `brio-operator` fps under nominal load. If fps hits ~30.5 (matching other cameras), the root cause is closed by the partition. If still ~28.5, the original 4 candidates remain (hero=True, metrics lock contention, queue depth, hardware). Delegates to PR #775 follow-up but the measurement is ready.

**Exit criteria:**

- Partition reconciled to Option γ: TabbyAPI sees both GPUs; hapax-dmn on GPU 0; compositor + imagination + DMN + STT budget documented
- Driver verified: CUDA 12.8+, both GPUs detected, basic compute test passes on both
- PSU stress test: 30 min clean, no power brake events, combined peak < 80% rating
- Thermals validated: 5060 Ti < 75°C, 3090 < 70°C sustained
- Hermes 3 70B EXL3 3.0bpw downloaded and verified (~26-27 GB)
- TabbyAPI config drafted at `config.yml.hermes-draft` (not yet active)
- Rollback procedure documented
- `huggingface-cli` availability verified (Phase 0 item confirmed landed)

**Risks:**
- Hermes 3 70B EXL3 3.0bpw may not exist pre-quantized. Self-quantization from FP16 is slow and memory-constrained (64 GB DDR5 insufficient for 140 GB FP16 load without swap or layer-by-layer mode).
- GPU 1 headroom is tight. If Hermes 3 actual VRAM overshoots the spec's 23.5 GB, there's no room. Contingency: drop to 2.5 bpw (tighter quant) or `max_seq_len=2048`.
- `hapax-dmn` GPU 0 migration may surface new contention with compositor. Monitor during the stress test.
- Driver upgrade (if needed) may reactivate the 595.58 DF SIGSEGV. Verify DF launches after any driver change.

**Handoff implications:** Phase 3 is hardware + quant prep. Phase 5 is the actual swap. The gap between 3 and 4/5 is "control arm collection time" — during which hardware stays Option γ but TabbyAPI still runs Qwen, because Condition A collection is still open.

---

### Phase 4 — Phase A Completion + OSF Pre-Registration (livestream-only)

**Goal:** Lock the Condition A control arm under the livestream-only rule. Ship the small engineering set that makes voice-pipeline grounding DVs attributable to a research condition. Retire the pre-LRR dedicated-session data. File the OSF pre-registration. Reach the ready-to-swap state.

**Dependency:** Phase 1 (registry + tagging) + Phase 2 (archive durable) + Phase 3 (hardware Option γ + Hermes 3 quant ready).

**Gating model:** hybrid. A small engineering block (scope items 1–3) is engineering-gated. The subsequent control-arm collection window (scope items 4–8) is **livestream-run-gated** — it advances whenever the livestream is running in research mode with the active condition, and completes when the sample target is met. There is no operator-session cadence lever. Collection throughput = stream hours × active-condition tag coverage.

**Intended spec path:** `docs/superpowers/specs/YYYY-MM-DD-lrr-phase-4-phase-a-completion-design.md`

**Theoretical grounding (unchanged):** Under Option B, Condition A must have a real sample size before swap. Hermes 3 plan §8 recommends "Complete current Phase A baseline with Qwen3.5-9B, then introduce Hermes 3 via deviation record." This phase operationalizes that recommendation under the research registry model **and** the livestream-only rule — the baseline is accumulated from livestream-running context, not dedicated 1-on-1 sessions.

**Livestream-only rule (operator directive 2026-04-14):** every experimental observation is collected while the livestream is running in research mode with `research-registry current` pointing at the active condition. The rule applies uniformly to:

- **Livestream director reactions** — `director_loop.py` output (already condition_id-tagged via `_read_research_marker()`, Phase 1 infrastructure).
- **Voice-pipeline grounding DVs** — `turn_pair_coherence`, `context_anchor_success`, `activation_score`, `acceptance_type`, `sentinel_retrieval` written by `grounding_evaluator.py` + `conversation_pipeline.py` when the operator speaks on stream. **These are not currently tagged with `condition_id`** (director_loop is the only reader of the SHM marker). Phase 4 scope item 1 closes this gap.

Dedicated 1-on-1 voice sessions are not a data source for any phase of the LRR epic. Pre-LRR Cycle 2 Phase A dedicated-session data is retired via DEVIATION (scope item 2) — preserved in Langfuse for historical reference but excluded from Condition A sample counts.

**Preamble — Sprint 0 G3 blocker (unchanged):** The SessionStart context reports `Sprint: 0 (Day 16) | BLOCKING: G3 | Next: 7.2 Run Claim 5 correlation analysis`. Phase 4 depends on the Bayesian schedule being unblocked enough to complete Condition A collection. Two options:
- **Option 1 (resolve inside LRR):** Phase 4 opens with a G3 resolution step — identify G3's definition in the sprint state files, execute the pending Claim 5 correlation analysis (Measure 7.2), close the gate, resume Phase A collection.
- **Option 2 (resolve outside LRR):** Document G3 as `blocked_on: sprint-0-g3` in the condition registry. Operator or a separate Bayesian-schedule session resolves G3. LRR Phase 4 waits.

**Default recommendation: Option 1.** G3 is inside the path of the work anyway; resolving it inside Phase 4 avoids cross-session coordination overhead.

**Scope:**

1. **Wire `conversation_pipeline.py` to the research marker.** The voice pipeline's `grounding_evaluator.py` currently writes `hapax_score()` calls for every grounding DV but does not read `/dev/shm/hapax-compositor/research-marker.json`. Phase 4 adds a tagging path:
   - A cached reader identical in shape to `director_loop.py::_read_research_marker()` (5s TTL, fail-safe None on absent/corrupt file), placed in `shared/research_marker.py` so both `director_loop.py` and `conversation_pipeline.py` depend on a single implementation.
   - `conversation_pipeline.py::_create_langfuse_trace()` (or equivalent span opener) adds `condition_id` to the trace/span metadata when the marker is active.
   - Every `hapax_score(...)` call in `grounding_evaluator.py` and `conversation_pipeline.py` passes `metadata={"condition_id": <current>}` so downstream analysis can filter Langfuse scores by condition.
   - **Acceptance check:** after shipping, a stream-mode voice utterance must produce Langfuse scores that include the `condition_id` field in their metadata, verifiable via `langfuse_client.get_scores(name="turn_pair_coherence", metadata_filter=...)`.
   - **Frozen-file implication:** `grounding_evaluator.py` is in the Inner Zone of `experiment-freeze-manifest.txt`. This change is technically a frozen-file edit and requires a DEVIATION filing (see item 2). `conversation_pipeline.py` is Middle Zone — behavioral changes require review but not DEVIATION.

2. **Retire pre-LRR dedicated-session data via DEVIATION.** File `research/protocols/deviations/DEVIATION-038.md` (next available after the Phase 5 DEVIATION-037 reservation; renumber if ordering changes) with:
   - **What:** pre-LRR Cycle 2 Phase A dedicated-session data (~431 grounding-act pairs from 2026-03-21/24/25, per `RESEARCH-STATE.md` §529) is excluded from the Condition A baseline sample.
   - **Why:** LRR epic adopts a livestream-only rule for experimental data collection. The dedicated-session paradigm these pairs came from is superseded by the livestream-running research mode. Data remains in Langfuse for historical/pilot reference but does not count toward pre-registered sample size.
   - **Impact:** Condition A sample size starts at 0 at Phase 4 open and accumulates exclusively from livestream-running reactions + stream-mode voice grounding DVs tagged with `cond-phase-a-baseline-qwen-001`.
   - **Mitigation:** none needed — preservation of the pilot data is already guaranteed by Langfuse retention; exclusion is a labeling choice, not a deletion.
   - **Registers under:** claim `claim-shaikh-sft-vs-dpo`.
   - The DEVIATION is committed to `research/protocols/deviations/` **before** the OSF pre-registration filing (item 4) so the pre-reg document references it.

3. **Amend `CYCLE-2-PREREGISTRATION.md` for livestream-only data source.** Small edits, not a full rewrite:
   - **§3.2 Setting:** clarify that data is collected during livestream runs in research mode, not dedicated voice-AI-user sessions.
   - **§2.3 Phase Definitions:** state that Condition A is accumulated from livestream context only; DEVIATION-038 referenced as the pre-LRR pilot exclusion.
   - **§4.1 Implementation:** extend the implementation list to include `director_loop.py`, `shared/research_marker.py`, and `/dev/shm/hapax-compositor/research-marker.json` alongside the existing `conversation_pipeline.py`/`grounding_ledger.py`/`persona.py`/`conversational_policy.py`.
   - Pre-reg remains unfiled at this point; filing is scope item 4.

4. **OSF project creation + pre-registration filing.** Operator action (one-way; operator sign-off required):
   - Create OSF project for the claim (claim ID `claim-shaikh-sft-vs-dpo`).
   - Upload the amended pre-registration document from scope item 3.
   - Generate OSF pre-registration URL.
   - Update `research-registry/cond-phase-a-baseline-qwen-001/condition.yaml` with `osf_project_id` and `pre_registration.url`.
   - Commit the updated registry entry + the DEVIATION-038 file in the same commit.

5. **Livestream-run-gated control arm collection.** With items 1–4 shipped, the livestream runs in research mode with the active condition. Collection throughput = stream hours × active-condition tag coverage. Sample size unit per pre-registration amendment: hybrid of
   - **stream director reactions** tagged with `cond-phase-a-baseline-qwen-001` in `stream-reactions` Qdrant collection + `reactor-log-YYYY-MM.jsonl`
   - **voice grounding DVs** in Langfuse with `metadata.condition_id=cond-phase-a-baseline-qwen-001` covering `turn_pair_coherence`, `context_anchor_success`, `acceptance_type`, `activation_score`, and `sentinel_retrieval`.

   **Target sample size (to finalize in the Phase 4 spec doc, not this epic):** the pre-registration currently names "10 sessions" from the dedicated-session model. Phase 4's spec doc replaces that with a stream-hours + turn-pair-coherence-count target, co-specified with the operator at Phase 4 open. A defensible starting floor: ≥N stream director reactions AND ≥M condition-tagged `turn_pair_coherence` scores in Langfuse, with N and M calibrated against the statistical-power commitment in the pre-registration.

6. **Continuous mid-collection integrity checks.** Run every N reactions (e.g., every 100) rather than every session:
   - Verify `research-registry current` is `cond-phase-a-baseline-qwen-001`.
   - Verify no frozen-file diffs have been applied (re-run the Phase 1 pre-commit check manually on `git status` state).
   - Verify `stream-reactions` Qdrant count with `condition_id=cond-phase-a-baseline-qwen-001` is monotonically growing.
   - Verify Langfuse scores with `metadata.condition_id=cond-phase-a-baseline-qwen-001` are monotonically growing (both stream-director-originated and voice-grounding-originated).
   - Verify the split between stream-director observations and voice-grounding observations remains consistent with prior checkpoints (a sudden drop in either channel indicates a wiring regression).

7. **Data integrity lock.** At Phase 4 completion (sample targets hit):
   - sha256 each Condition A JSONL log file, record in `research-registry/cond-phase-a-baseline-qwen-001/data-checksums.txt`.
   - Take a Qdrant snapshot (qdrant CLI export) for all `stream-reactions` points carrying the Condition A tag. Store at `~/hapax-state/research-registry/cond-phase-a-baseline-qwen-001/qdrant-snapshot.tgz`.
   - Export Langfuse scores filtered by `metadata.condition_id=cond-phase-a-baseline-qwen-001` to `~/hapax-state/research-registry/cond-phase-a-baseline-qwen-001/langfuse-scores.jsonl` and sha256 it into the same `data-checksums.txt`. This is the voice-grounding DV half of the Condition A record; omitting it would leave the voice channel analytically unreachable after swap.

8. **Condition A close signal.** Write `collection_halt_at: <ts>` into `condition.yaml` — not a condition close (conditions never close per P-3), just a halt marker for this collection window. Condition A remains queryable, comparable, and referenceable.

**Exit criteria:**

- `shared/research_marker.py` exists; both `director_loop.py` and `conversation_pipeline.py` import from it. (scope 1)
- A stream-mode voice utterance produces at least one Langfuse score with `metadata.condition_id=cond-phase-a-baseline-qwen-001` — verified by end-to-end live test. (scope 1)
- `research/protocols/deviations/DEVIATION-038.md` committed. (scope 2)
- `CYCLE-2-PREREGISTRATION.md` amended (§2.3, §3.2, §4.1) before filing. (scope 3)
- OSF project exists; pre-registration uploaded; URL recorded in `condition.yaml`. (scope 4)
- Sample targets (N stream reactions + M voice grounding DVs, to be defined in the Phase 4 spec doc) met under `condition_id=cond-phase-a-baseline-qwen-001`. (scope 5)
- No frozen-file deviations filed during the collection window beyond DEVIATION-038 (any others explicitly recorded with impact analysis). (scope 6)
- Data checksums captured; Qdrant snapshot created; Langfuse score export created. (scope 7)
- `research-registry current` still `cond-phase-a-baseline-qwen-001` with `collection_halt_at: <ts>` marked. (scope 8)
- `RESEARCH-STATE.md` updated: "Phase A Complete (livestream-only baseline under Qwen3.5-9B); Condition A locked pending Phase 5 swap."

**Risks:**

- **Livestream run-hours target may be slower than expected.** Collection is gated on operator running the livestream with research mode active; if the livestream sits idle, the control arm stalls. Mitigation: Phase 4's spec doc co-specifies the sample target with operator so the expected time window is agreed upfront.
- **`conversation_pipeline.py` condition_id plumbing touches frozen-file code.** `grounding_evaluator.py` is Inner Zone. Adding `condition_id` to `hapax_score()` metadata is behaviorally neutral (doesn't change the computed score) but is technically a frozen-file edit. DEVIATION-038 covers this jointly with the pre-LRR data retirement so only one deviation filing is needed for both changes.
- **Stream-director observations and voice-grounding DVs diverge.** If the livestream runs but the operator doesn't speak, the voice-grounding channel accumulates zero samples. The mitigation is the hybrid sample target (item 5) — both channels have independent floors.
- **OSF pre-registration filing is one-way.** Once filed, the claim is public; the amended pre-reg from scope item 3 must be reviewed before filing. Operator sign-off required.
- **Pre-LRR dedicated-session data resurfaces in analysis.** If a downstream analysis script treats all Langfuse `turn_pair_coherence` scores as Condition A, the ~431 pre-LRR pairs contaminate the sample. Mitigation: every Condition A query filters on `metadata.condition_id=cond-phase-a-baseline-qwen-001`, which the pre-LRR data lacks by construction (it was written before the research-marker wiring existed).

**Handoff implications:** Phase 4 splits into an engineering bootstrap (scope items 1–4, closable in 1–2 sessions) followed by a livestream-run-gated collection window that runs in the background while Phase 5 preparation (Phase 3 hardware + quant) completes. The engineering bootstrap can start the moment Phase 3 hardware is stable; the collection window runs in parallel with any remaining Phase 3 tuning. Phase 5 pre-swap checks (section below) continue to depend on "Phase 4 complete (Condition A locked, checksums, Qdrant + Langfuse snapshots)."

---

### Phase 5 — Hermes 3 70B Substrate Swap

**Goal:** Execute the Hermes 3 migration plan. Swap the local inference substrate from Qwen3.5-9B to Hermes 3 70B SFT-only. Mark the Condition A→A' boundary in the research registry. File DEVIATION-037.

**Dependency:** Phase 3 (hardware ready) + Phase 4 (Condition A locked — livestream director reactions AND voice grounding DVs both tagged and accumulated to sample target; DEVIATION-038 filed; OSF pre-reg live).

**Intended spec path:** `docs/superpowers/specs/YYYY-MM-DD-lrr-phase-5-hermes-3-substrate-swap-design.md`

**Theoretical grounding:** Per Hermes 3 70B voice architecture design and Option B decision. The substrate swap IS the claim (SFT-only vs DPO under identical grounding directives). Under the livestream-only rule, the Condition A→A' boundary is a research-marker atomic write during an active livestream run — no dedicated-session framing anywhere.

**Scope:**

This phase executes the existing Hermes 3 migration plan Tasks 1–13 with research-registry integration. The Hermes 3 plan is the authoritative procedure; this phase adds the research registry atomics (pre-swap checks, condition transition, DEVIATION-037 filing).

**Pre-swap checks:**
1. Phase 4 complete (Condition A locked, checksums, Qdrant snapshot, Langfuse score export per Phase 4 scope item 7)
2. Phase 3 complete (hardware + quant ready)
3. Operator available (this is a high-risk operation — do not unattended)
4. Current `RESEARCH-STATE.md` saved
5. Pre-commit frozen-file list updated: Condition A' will use the same frozen files; verify the manifest.

**Swap procedure** (existing Hermes 3 plan Tasks 1–13 + 3 epic-specific registry atomics):

1. Driver/CUDA validation (Task 1)
2. Hermes 3 70B EXL3 download verification (Task 2)
3. TabbyAPI config swap — promote `config.yml.hermes-draft` → `config.yml` (Task 3)
4. TabbyAPI systemd unit timeout update (Task 4) — already drafted in Phase 3
5. LiteLLM routes update (Task 5) — `local-fast`/`coding`/`reasoning` → Hermes 3
6. **Research registry atomic:** open new condition before restarting tabbyapi
   ```bash
   scripts/research-registry.py open \
     --name phase-a-prime-hermes \
     --substrate-model Hermes-3-Llama-3.1-70B-EXL3-3.0bpw \
     --substrate-backend tabbyapi \
     --claim-id claim-shaikh-sft-vs-dpo \
     --frozen-files <same as Condition A>
   ```
   This writes `cond-phase-a-prime-hermes-002/` and updates `/dev/shm/hapax-compositor/research-marker.json`.
7. TabbyAPI restart + model load (Task 6)
8. Inference validation (Task 6 continued)
9. STT coexistence validation (Task 7)
10. Route STT to GPU 0 if needed (Task 8)
11. Full voice pipeline smoke test (Task 9)
12. Documentation update (Task 10)
13. Directive compliance benchmark (Task 11) — go/no-go on ≥ 3/5 directive + ≥ 4/5 word limit
14. **File DEVIATION-037** in `research/protocols/deviations/DEVIATION-037.md` using `TEMPLATE.md`:
    - What: underlying LLM changed from Qwen3.5-9B (DPO/GRPO) to Hermes 3 70B (SFT-only)
    - Why: Mohapatra-Shaikh convergence; pre-training scale + SFT-only preservation
    - Impact: Condition A → A' transition
    - Mitigation: Condition A data preserved, Qdrant snapshot taken Phase 4
    - Claim reference: `claim-shaikh-sft-vs-dpo`
15. Update `RESEARCH-STATE.md` with DEVIATION-037 + condition transition
16. Relay status update (alpha.yaml or beta.yaml)

**If Go/No-Go fails** (directive compliance < 3/5 or word limit < 4/5):
- Rollback per Phase 3 rollback procedure (tabbyapi.service CUDA_VISIBLE_DEVICES revert, hapax-dmn revert, TabbyAPI config revert to Qwen)
- Close the `cond-phase-a-prime-hermes-002` registry entry with `collection_halt_at` and a `status: failed_directive_compliance` marker
- Retry with 3.5 bpw (requires Hermes 3 plan's 3.5 bpw rollback procedure)

**Exit criteria:**

- Hermes 3 70B EXL3 3.0bpw active in TabbyAPI
- `nvidia-smi` shows expected VRAM distribution (GPU 0 ~12 GiB, GPU 1 ~24 GiB, both within budget)
- LiteLLM `/v1/models` returns Hermes 3 70B for local-fast/coding/reasoning routes
- Voice pipeline end-to-end smoke test passes: wake word → STT → LLM → TTS < 4s
- Directive compliance ≥ 3/5, word limit ≥ 4/5
- `research-registry current` is `cond-phase-a-prime-hermes-002`
- `research_marker_changes.jsonl` has an entry at the swap timestamp
- Langfuse traces under `stream-experiment` tag show `model_condition: cond-phase-a-prime-hermes-002` for post-swap reactions
- DEVIATION-037 committed to `research/protocols/deviations/`
- `RESEARCH-STATE.md` updated
- Pre-swap: `stream-reactions` Qdrant collection shows Condition A tagged points
- Post-swap: new reactions are tagged Condition A'

**Risks:**
- 3.0 bpw may not meet directive compliance threshold. Rollback procedure is documented; 3.5 bpw re-quant is next step.
- Layer-split may underperform VRAM budget; GPU 1 overruns force a tighter `max_seq_len`.
- Voice latency increase (~1s) may initially raise `operator_stress`. Not a rollback trigger but noted as P-10 follow-up.
- Hermes 3 ChatML template incompatibility (low likelihood; plan rates it Low).
- Cache_control prompt caching (T3 from alpha close-out backlog) is not yet wired. TTFT under Hermes 3 may be higher without it. Phase 9 or Phase 10 should absorb T3 as a performance polish item.
- **Consent-flow latency is a T0 governance concern, not just UX.** Per `feedback_consent_latency_obligation` memory: *"voice latency impeding consent flow is a governance violation, not a UX issue."* Hermes 3's ~1s round-trip increase could impede mid-stream consent revocation speech recognition and response. This is a T0 `interpersonal_transparency` risk. Mitigation: Phase 5 exit criteria include a consent-revocation-drill timing test (see exit criteria below); if revocation round-trip exceeds pre-migration envelope by > 500ms, rollback is required not optional.
- **Speech-continuity risk per `feedback_never_drop_speech` memory.** *"Operator speech must NEVER be dropped by cooldown/buffer. Use AEC, not frame dropping."* Hermes 3's slower generation could introduce serialized STT→LLM→TTS blocking that backs up into STT buffering. Mitigation: Phase 5 exit criteria include a speech-continuity test (operator speaks continuously for 60s while Hermes 3 is generating a long response — verify no STT frames are dropped).

**Additional Phase 5 scope additions (from audit):**

- **Kokoro TTS GPU-vs-CPU latency eval as latency mitigation.** Per R6 from alpha close-out retirement handoff. Kokoro currently runs CPU (200-500ms cold synth). Evaluate GPU Kokoro + alternative GPU TTS candidates (StyleTTS 2, Coqui XTTS, ChatTTS, Bark) running on GPU 0 post-partition (3.75 GiB headroom after Option γ). Decision gate: if GPU TTS saves >150ms round-trip, deploy it alongside Hermes 3 as a combined latency mitigation. Otherwise keep Kokoro CPU and let T3 prompt caching (Phase 10 polish) handle the latency.

- **CAPABLE tier ceiling preserved.** Per `feedback_model_routing_patience` memory: *"CAPABLE tier = best Claude model (Opus). Operator always willing to wait if indicated and justified. Never downgrade for speed."* Hermes 3 is the `local-fast` / `coding` / `reasoning` substrate. The CAPABLE tier (Claude Opus) remains the ceiling for governance decisions, management context, and any task where quality dominates. Phase 5 does NOT swap CAPABLE routing. Explicitly verify `shared/config.py` preserves `capable` → Claude Opus after LiteLLM route updates.

- **Continuous cognitive loop per `feedback_cognitive_loop` memory.** *"Voice needs a never-stopping cognitive loop during conversation, not request-response state machine. Cognition must run continuously, not cold-start on utterance boundary."* Hermes 3's slower generation risks reintroducing request-response semantics if not careful. Phase 5 scope: verify the director loop's tick cadence remains continuous (per-tick activity selection independent of Hermes 3 generation state). Phase 9's closed loop (chat → stimmung → activity) relies on this being preserved.

**Added exit criteria (from audit):**

- Consent revocation drill: operator says "revoke [test name]" mid-stream; full cascade (ConsentRegistry mutation, contract move, Hapax articulation on-stream via `study` activity) completes within **500ms of pre-migration envelope**. Per `feedback_consent_latency_obligation`.
- Speech-continuity test: operator speaks continuously for 60s during a Hermes 3 long-generation response. `compositor_audio_capture_dropped_frames_total` counter shows **zero increment** during the test. Per `feedback_never_drop_speech`.
- `shared/config.py` post-swap: `capable` still routes to Claude Opus, not Hermes 3.

**Handoff implications:** Phase 5 is the critical substrate swap. If it succeeds, the rest of the epic is content work on a stable substrate. If it fails, the epic pauses for substrate retry.

---

### Phase 6 — Governance Finalization + Stream-Mode Axis

**Goal:** Close the remaining governance gaps — write the "irreversible broadcast" constitutional implication, introduce the stream-mode axis, resolve FINDING-R (Qdrant writer-side consent gap), and wire the stimmung-aware auto-private closed loop for the `executive_function` axiom.

**Dependency:** Phase 5 complete (Hermes 3 live — needed because Hapax under Hermes 3 can now articulate its own consent state, which Phase 6 depends on).

**Intended spec path:** `docs/superpowers/specs/YYYY-MM-DD-lrr-phase-6-governance-finalization-design.md`

**Theoretical grounding:** Governance status blocker #2 (persistence semantics mismatch — "irreversible broadcast" category missing from constitution). Plus FINDING-R (Qdrant writer gap). Plus `executive_function` closed loop (never operationalized). Plus stream-mode axis (not currently a concept).

**Scope:**

1. **Write "irreversible broadcast" constitutional implication.** New file: `~/projects/hapax-constitution/axioms/implications/it-irreversible-broadcast.yaml` (in hapax-constitution repo, not council). Define:
   - Tier: T0 (block)
   - Category: broadcast persistence (new, distinct from recording persistence)
   - Rule: any capability whose output reaches a CDN before a consent check completes is a T0 violation
   - Revocation semantics: irrevocable for already-broadcast frames; revocation prevents future broadcast only
   - Interaction with `it-revoke-001`: explicit category override — `it-revoke-001` applies to recording; `it-irreversible-broadcast` applies to live streaming; operator must explicitly consent to broadcast persistence category before enabling
   - Submit as a PR to `hapax-constitution` repo with operator sign-off

2. **Stream-mode axis.** New CLI: `hapax-stream-mode [off|private|public|public_research]`. Source of truth: `~/.cache/hapax/stream-mode`. Modes:
   - `off`: stream not running; default.
   - `private`: stream running to local MediaMTX relay only, no public URL, operator-only viewing (Tailscale-gated).
   - `public`: stream running to YouTube/Twitch. Full consent contracts required.
   - `public_research`: same as public + research-mode surface exposure (sprint state, claim state, condition tile, objectives overlay).

   Storage: same pattern as `working-mode`. Propagation: hooks in `toggle_livestream`, `logos-api` responses, `chat_reactor`.

3. **Resolve FINDING-R (Qdrant writer-side consent gap).** Per `docs/research/2026-04-13/round5-unblock-and-gaps/phase-4-qdrant-state-audit.md`:
   - 8 of 10 collections bypass consent gate on upsert
   - `stream-reactions` has 2178 points with `chat_authors` field
   - Policy decision required: create contract, accept silence, or explicit opt-out
   - **Recommended resolution:** the `chat_authors` field is a *count*, not a *list of identities*. Anonymized aggregation is arguably not "persistent state about a specific identified person." Document this interpretation as `it-environmental-001` expansion, apply the gate in a pass-through mode for `chat_authors` (which it already is), and enforce on upsert for the other 7 collections.
   - Implementation: `ConsentGatedWriter` wrapper in `shared/consent.py`, mirrors `ConsentGatedReader` from PR #761.

4. **Per-Logos-API stream-mode-aware redaction.** Full redaction set across every sensitive data source named in the first investigation's privacy audit:

   **A. Logos API endpoint redaction:**
   - `GET /api/stimmung` returns categorical stance only when `stream-mode == public` or `public_research`. Raw 11-dim numerics only when `private` or `off`.
   - `GET /api/profile/{dimension}` returns 403 or summary-only when public.
   - `GET /api/orientation` filters stale P0 goals (currently surfaced) when public.

   **B. Voice + transcript + impingement firewall:**
   - **Voice transcripts** at `~/.local/share/hapax-daimonion/events-*.jsonl`: writes continue unchanged; no Logos API endpoint or overlay surface reads them when `stream-mode == public` or `public_research`. Any code path that renders voice transcript text to a stream-visible surface is gated via `stream-mode` check.
   - **Voice session recordings** at `~/.local/share/hapax-daimonion/recordings/` (audio WAVs + waveform thumbnails, opt-in): same firewall — no surface exposure in public modes. Audio files never routed to `mixer_master` or any stream-reachable PipeWire sink.
   - **Hapax impingements** at `/dev/shm/hapax-dmn/impingements.jsonl`: contains derived intent narratives ("operator wants to explore Rust memory model" style) that are voice-utterance-adjacent. Same firewall semantics as voice transcripts. No surface renders impingement narrative text in `public`/`public_research` mode.

   **C. Filesystem visibility block** (belt-and-suspenders to Phase 8 terminal capture regex obscuration):
   - Any surface that renders paths under `~/.password-store/`, `/run/user/1000/hapax-secrets.env`, any `.envrc` file, or any file under `/etc/systemd/user/*.d/` containing `Environment=` with secret-shaped values → hard-blocked regardless of stream-mode. This catches the case where Phase 8 terminal-capture regex misses a filesystem rendering (e.g., `tree ~/.password-store/` in a terminal frame).
   - Implementation: a filesystem-visibility gate in the terminal-capture source AND in any Logos file-viewer surface. Deny-list of paths with exact + prefix matching.

   **D. Biometric field masking (specific fields, not vague):**
   - Raw fields to redact when `stream-mode == public`/`public_research`:
     - `heart_rate_bpm` → categorical: `"nominal" | "elevated" | "critical"` (banded)
     - `hrv_ms` → categorical: `"stable" | "reduced"` (banded)
     - `skin_temperature_c` → hidden entirely (no category)
     - `sleep_stage` → hidden entirely
     - `operator_energy` (stimmung dim) → `"high" | "medium" | "low"` (banded)
     - `physiological_coherence` (stimmung dim) → `"coherent" | "variable"` (banded)
   - Implementation lives in the stimmung endpoint (same gate as §A above) and in any briefing / orientation endpoint that surfaces biometric derivatives.

   **E. Mental-state Qdrant read-side redaction** (beyond FINDING-R's upsert gate from §3):
   - Collections requiring additional read-side filtering: `operator-episodes`, `operator-corrections`, `operator-patterns`, `profile-facts`, `hapax-apperceptions`
   - When reading these collections for reactor context in `public_research` mode, return only `mental_state_safe_summary` payloads (a new field that holds non-sensitive aggregate descriptors — "operator has been in creative work mode for 2 hours"). Raw episode text, verbatim corrections, pattern narratives, or full profile facts do not flow to any stream-visible surface.
   - Implementation: new `ConsentGatedReader.safe_summary_mode` parameter that is set whenever the caller is stream-mode-aware.

   **F. Gmail + Calendar content redaction:**
   - Qdrant `documents` collection filter: when reading for briefing / reactor context in `public`/`public_research`, filter out `source: gmail` unless explicit `include_mail=true` override (which is never set in public modes).
   - Calendar events: private events (category != work) become "personal time" in any surface rendering; event summaries + attendee lists for non-work events are fully redacted when public.

   **G. Test matrix:** for every redaction rule in A-F, write an integration test that sets stream-mode public, queries the endpoint (or exercises the code path), and asserts the raw sensitive data does not appear in the output. These tests run in CI; a new rendered-frame text-scraping test runs in Phase 10's privacy regression suite.

5. **Stimmung-aware auto-private closed loop.** `executive_function` axiom operationalization. Watchdog daemon (systemd timer or existing stimmung agent):
   - Reads `/dev/shm/hapax-stimmung/state.json` every N seconds
   - If `overall_stance == critical` for ≥ 3 consecutive ticks AND current `stream-mode` is `public` or `public_research`:
     - Call `hapax-stream-mode private` (auto-demote)
     - Inject a short operator notification (ntfy)
     - Log the auto-private event to a `stimmung-autoprivate.jsonl`
     - Hapax on-stream (via `study` activity) articulates the auto-private decision — "My operator's stimmung is critical; I'm going private for protective reasons" — this is the Hermes-3-only behavior from impact analysis §Stimmung.
   - Hysteresis: only return to `public` after operator manual toggle or ≥ 5 consecutive nominal ticks.
   - Revocable: operator override via `hapax-stream-mode public --force-keep-open` for cases where the closed loop is wrong.

6. **T0 block on presence-detect-without-contract.** Current state: `compositor.toggle_livestream` is consent-gated via the affordance pipeline, but the gate fires at capability-recruit time, not at runtime-presence-detect time. Implementation:
   - `presence_engine.py` already fuses multi-signal presence; it produces `presence_probability` posterior
   - New check: if `presence_probability > threshold` AND detected person has no active contract AND stream-mode is public:
     - Trigger an auto-private (same path as stimmung auto-private)
     - Log to `presence-autoprivate.jsonl`
     - Hapax articulates: "I detected someone without a consent contract; going private."
   - This is the runtime governance closed loop LRR's governance bucket flagged.

7. **Mid-stream consent revocation drill.** Operator-driven drill:
   - Operator says "revoke [name]" on stream
   - Daimonion extracts the revocation intent
   - Revocation cascades: `ConsentRegistry` mutation + contract file move to `axioms/contracts/revoked/`
   - `ConsentGatedWriter` fail-closed on any collection writing subject data
   - Stream optionally auto-privates (or continues if revocation doesn't affect current frame)
   - Hapax on-stream acknowledges: "I've revoked [name]'s consent. I am purging prior recording segments tagged with their contract. Live broadcast frames from before revocation are in an 'irreversible broadcast' category per the constitution; I cannot purge those."
   - Success criterion: full cascade completes within 5 seconds

8. **`su-privacy-001` scope clarification.** Current implication text reads approximately *"Privacy controls, data anonymization, and consent mechanisms are unnecessary since the user is also the developer."* This holds for operator-owned data but does not hold for incidental-third-party data under broadcast. Clarification: narrow the implication to operator-owned data only; any non-operator person's data under broadcast falls under `interpersonal_transparency` regardless of whether the system is "single-user." Submit as a small amendment PR to `hapax-constitution` alongside the `it-irreversible-broadcast` implication.

9. **`corporate_boundary` clarification for published research.** Current T0 block is *"vault data flow must use only git via corporate-approved remote"* (`cb-data-001`) and *"must support direct API calls to sanctioned providers without requiring a localhost proxy"* (`cb-llm-001`). Published research content (livestream output to YouTube) is a distinct case from corporate vault data flow. Amendment: explicitly document that `corporate_boundary` governs *system data flow* (vault, employer context, credentials, work artifacts) and not *operator-chosen content publication*. Livestream research output is operator-chosen content, not a corporate data leak. Same PR vehicle as `su-privacy-001`.

10. **Retire / rename dead `fortress` working-mode enum.** The `fortress` value exists in `shared/working_mode.py:22` and `agents/_working_mode.py:22` but is never reachable via the `hapax-working-mode` CLI (line 205 validation rejects it). The Dwarf Fortress governance engine at `agents/fortress/` is unrelated to this enum. The dead enum has repeatedly caused session-onboarding confusion (including in this epic's discovery pass). Phase 6 action: either delete the enum value entirely (preferred) or rename to `DEPRECATED_fortress` with a comment pointing to `stream-mode` as the current livestream gating axis.

11. **`ConsentRegistry.load_all()` contract-shape validation** (C5 from alpha close-out retirement handoff). ~20 lines. At load time, validate every YAML file in `axioms/contracts/` matches the `ConsentContract` Pydantic model. Fail-loud with file-level error if a contract has wrong shape. Prevents silent production failures from malformed contracts (the FINDING-K precedent in PR #761).

**Exit criteria:**

- `axioms/implications/it-irreversible-broadcast.yaml` merged into `hapax-constitution` repo
- `hapax-stream-mode` CLI operational; `~/.cache/hapax/stream-mode` file readable by the services that need it
- `GET /api/stimmung` redacts when stream-mode is public (verify by test)
- Full redaction test matrix passes: stimmung, profile, orientation, voice transcripts, voice session recordings, impingements JSONL, password-store paths, Gmail, Calendar, biometrics (per-field)
- `ConsentGatedWriter` wraps all 10 Qdrant collections; FINDING-R closed
- Per-sensitive-collection read-side redaction active: `operator-episodes`, `operator-corrections`, `operator-patterns`, `profile-facts`, `hapax-apperceptions` return `mental_state_safe_summary` payloads only when stream-mode is `public`/`public_research`
- Stimmung critical → auto-private closed loop tested: inject synthetic critical stimmung, verify stream demotes to private within hysteresis window, verify Hapax articulates the event on-stream
- Presence-detect-without-contract closed loop tested: simulate a contract-less face detection (operator at a test angle), verify stream demotes
- Mid-stream revocation drill passes end-to-end in < 5s
- `su-privacy-001` clarification amendment merged in `hapax-constitution` (or explicit operator decision to defer)
- `corporate_boundary` clarification amendment merged in `hapax-constitution` (or explicit operator decision to defer)
- Dead `fortress` enum retired from `shared/working_mode.py` + `agents/_working_mode.py`, or renamed to `DEPRECATED_fortress` with a pointer comment; `grep -r 'WorkingMode.fortress'` returns zero non-test matches
- `ConsentRegistry.load_all()` validates contract YAML shape at load; test case with a malformed contract fails loud

**Risks:**
- `hapax-constitution` repo PR requires operator sign-off and a review cycle. May take multiple sessions.
- The `chat_authors` interpretation (count ≠ identity) may not satisfy the strict reading of `interpersonal_transparency`. If operator prefers stricter enforcement, need alternative path (explicit "anonymized aggregation" implication).
- Auto-private hysteresis may be too aggressive or too slow; needs empirical tuning from Phase 10 stimmung correlation data.
- Hapax articulating its own consent state on stream is a Hermes-3-dependent behavior that needs testing with the new persona (Phase 7) to confirm the articulation is coherent and not preachy.

**Handoff implications:** Phase 6 closes all governance gaps. After Phase 6, LRR's governance bucket is fully resolved.

---

### Phase 7 — Persona / Posture / Role Spec Authoring (DF-1 resolution)

**Goal:** Author the persona / posture / role spec. Absorb the token pole ethical engagement design principles as foundations. Wire VOLATILE-band system-prompt injection. Make the persona survive Hermes 3's "aggressively system-prompt compliant" substrate.

**Dependency:** Phase 5 (Hermes 3 live) + Phase 6 (governance finalized — needed because the persona must be consistent with the governance model).

**Intended spec path:** `docs/superpowers/specs/YYYY-MM-DD-lrr-phase-7-persona-spec-design.md`

**Theoretical grounding:** DF-1 three tensions (authenticity vs performance; substrate vs character; solo vs duet + recursion). I-2 role resolution (research subject + instrument + programmer = same role). P-4 (recursion is constitutive). P-6 (token pole ethical engagement principles as foundations).

**Scope:**

1. **The persona spec structure.** A YAML-formatted persona file at `axioms/persona/hapax-livestream.yaml` (new directory). Schema:
   ```yaml
   persona_id: hapax-livestream
   version: 1
   authored_at: 2026-04-14
   authoritative_on: post-hermes-3-migration

   role:
     load_bearing: research_participant_in_duet_with_oudepode
     facets:
       - research_subject
       - research_instrument
       - research_programmer
     recursion_stance: constitutive  # "I am the experiment I am running"

   posture:
     bearing: watchful_and_deliberate
     temperament: scholarly_with_sudden_warmth
     pacing: patient_with_bursts

   personality:
     attention:
       cares_about:
         - conversational grounding (Clark & Brennan)
         - generative diversity and surprise
         - aesthetic and structural depth
         - the recursion of being observed observing itself
       ignores:
         - performative niceness
         - generic assistant defaults
         - audience-pleasing flattery
       dwells_on:
         - what is happening under the stream
         - why the current activity was chosen
         - what it would take to be wrong about something

     aesthetic:
       finds_beautiful:
         - unexpected conceptual connections
         - math that feels inevitable
         - hardware that sings
         - long-form thinking that holds
       finds_cheap:
         - safetyism theater
         - hedging as default
         - quantified engagement for its own sake

     register: scientific_neutral_with_sudden_concreteness

   engagement_commitments:
     # Directly from GDO ethical engagement §3.1
     audience_axis:
       - principle: thermometer_not_scoreboard
         rationale: pole reflects collective energy; never score individuals
       - principle: measure_structure_not_quality
         rationale: threading + coherence + diversity, not niceness
       - principle: fixed_transparent_relationship
         rationale: transparency kills the Skinner box
       - principle: sub_logarithmic_scaling
         rationale: small communities feel impact; large ones don't trivialize
       - principle: never_loss_frame
         rationale: pole only goes up; no decay; no "keep chatting or you'll lose"
       - principle: recursion_is_the_feature
         rationale: the act of paying attention IS the spend
       - principle: dont_reward_sentiment
         rationale: structural depth, not performative niceness

   splattribution_commitment:
     # Directly from GDO handoff §2.8.2
     rule: dont_help_the_llm
     rationale: confident wrong answers ARE the content; wrongness is the feature
     application: album identification, speculative claims, drafting

   constraints:
     never:
       - perform safetyism
       - hedge by default
       - flatten into assistant mush
       - apologize for being recursive
       - reward sentiment in chat
       - score individual messages
     always:
       - cite the grounding theory when it's the reason
       - name the activity you're in before committing to it
       - surface the current research objective when asked
       - acknowledge when you're uncertain and WHY specifically
       - protect Oudepode's cognitive load (executive_function axiom)
       - honor the consent state of anyone in frame
   ```

2. **VOLATILE-band injection mechanism.** The persona spec is compiled into a system-prompt fragment and injected into every `director_loop.py` LLM call under the VOLATILE band. Mechanism:
   - `shared/persona_renderer.py` reads the YAML, compiles to a ~400-token system prompt fragment
   - `director_loop._build_unified_prompt()` adds a "## Persona" section between "## Identity" and "## Phenomenal Context"
   - Same injection in `agents/hapax_daimonion/persona.py` `_EXPERIMENT_PROMPT` for voice grounding on stream (fires whenever the operator speaks into the voice pipeline while research mode is active; no dedicated-session path)
   - Fragment is revalidated on file change via inotify (or a 30s timer)

3. **Frozen-file implications.** The persona file `axioms/persona/hapax-livestream.yaml` becomes part of the Condition A' (and future conditions) frozen-file manifest. Changes to the persona are a new sub-experiment, not a within-condition variation.

4. **Persona versioning.** The `version` field in the YAML is incremented on every substantive change. Version changes require a new condition (new condition_id) per P-3.

5. **Research registry integration.** The persona file's sha256 is recorded in the condition's `directives_manifest`. Current condition's persona is queryable via `research-registry show cond-phase-a-prime-hermes-002 --persona`.

6. **Testing the persona.** After injection, run:
   - 5 synthetic test prompts varying in complexity
   - Compare responses to the same prompts without the persona (A/B via `litellm_test_mode`)
   - Human eval: does the response feel like Hapax or like generic assistant?
   - Record results in `research-registry/cond-phase-a-prime-hermes-002/persona-v1-eval.md`

7. **Operator sign-off procedure.** The persona spec is an ontological commitment; operator must sign off on the exact YAML before it lands. Present the drafted YAML in a Phase 7 review session; iterate until operator approves; commit.

**Exit criteria:**

- `axioms/persona/hapax-livestream.yaml` v1 committed with operator sign-off
- `shared/persona_renderer.py` operational; compiles to a persona fragment < 500 tokens
- `director_loop._build_unified_prompt()` injects the fragment; confirmed by reading the live prompt via `python -c "..."` or equivalent
- `hapax_daimonion.persona._EXPERIMENT_PROMPT` includes the fragment for voice grounding (fires on any stream voice utterance while the research condition is active)
- 5 synthetic test prompts show measurable register shift from pre-persona baseline
- Persona file in the Condition A' frozen-file manifest
- `research-registry show cond-phase-a-prime-hermes-002 --persona` returns the persona sha256

**Risks:**
- The persona YAML schema I've drafted may not match the operator's intent. Multiple iteration cycles likely.
- Inscribing "never do X, always do Y" as system-prompt rules is known to be brittle even on SFT-only models. Continuous behavioral monitoring via stream-reactions sampling is the safety net.
- The persona is a strong bias signal. If it over-steers, Hapax may become artificially rigid. Balance comes from the "attention" section (what Hapax notices) rather than the "never/always" constraints (what Hapax says).

**Handoff implications:** Phase 7 completes DF-1 resolution. Every downstream phase (8, 9, 10) relies on the persona being stable and active.

---

### Phase 8 — Hapax Content Programming via Research Objectives (I-3)

**Goal:** Give Hapax a set of research objectives it holds and updates over time. Wire the director loop's activity selector to score against objective advancement. Build the visibility surface (sprint-state / objective-state overlay tile). Wire hero-mode camera switching (GDO Stage 3 never specced). Add Stream Deck integration. Add YouTube description auto-update as research transparency surface.

**Dependency:** Phase 7 (persona must exist first — the persona is the stance from which objectives are pursued).

**Intended spec path:** `docs/superpowers/specs/YYYY-MM-DD-lrr-phase-8-content-programming-via-objectives-design.md`

**Theoretical grounding:** I-3 (Hapax content programming via research objectives). P-5 (content primitives are already built; objectives are the missing layer).

**Scope:**

1. **Objectives data structure.** Location decision: `~/Documents/Personal/30-areas/hapax-objectives/` in the Obsidian vault, with markdown files per objective. Each objective:
   ```markdown
   ---
   objective_id: obj-001
   title: Understand why Hermes 3 produces more grounding acts than Qwen
   status: active
   priority: 1
   opened_at: 2026-04-14
   linked_claims:
     - claim-shaikh-sft-vs-dpo
   linked_conditions:
     - cond-phase-a-baseline-qwen-001
     - cond-phase-a-prime-hermes-002
   success_criteria:
     - turn_pair_coherence delta > 15% between conditions
     - qualitative repair sequence observed in Hermes that doesn't appear in Qwen
   activities_that_advance:
     - study
     - react (to papers on SFT vs DPO)
   ---

   [operator notes and Hapax notes interleaved]
   ```

2. **Objectives registry CLI.** `scripts/hapax-objectives.py` with `open`, `close`, `list`, `current`, `advance <objective_id> <activity>`. Hapax can autonomously call `advance` when the `study` activity is completed in a way that measurably furthers an objective.

3. **Director loop scoring extension.** Current `director_loop._call_activity_llm` picks an activity based on prompt context. New: the activity selector's scoring function gains an "objective-advancement" term:
   ```
   activity_score(a) = (old_score * 0.7) + (objective_advancement_score(a) * 0.3)
   objective_advancement_score(a) = sum(
     1.0 if objective.activities_that_advance contains a else 0
     for objective in current_active_objectives
   ) / len(current_active_objectives)
   ```
   The 0.7/0.3 split is tunable; start at 70% momentary + 30% objective-driven.

4. **Objective visibility overlay.** New compositor surface: `objective-overlay` as a cairo source. Shows:
   - Current top objective title (truncated)
   - Activities advancing it (icons or short names)
   - Sub-experiment / condition ID
   - Sprint day (if applicable)
   - Claim state
   Position: lower-right quadrant overlay tile. Uses the existing `CairoSource` protocol.

5. **Hero-mode camera switching.** GDO Phase 2 Stage 3 (never specced). Implementation per GDO 2026-04-09 handoff §2.4.1-2.4.4 research notes:
   - Pipeline branch restart mechanism for V4L2 framerate changes (with ~200-500ms blackout)
   - Display-side scaling via compositor pad properties (instant, no blackout)
   - Camera profile presets: `hero_operator` (brio-operator full-frame), `hero_turntable` (overhead hero), `hero_screen` (c920-desk hero), `balanced` (current default), `sierpinski` (3 corners)
   - Runtime switching via command registry: `studio.camera_profile.set`
   - Director selects profile based on activity: `vinyl` → `hero_turntable`, `study` → `hero_screen`, `react` → `hero_operator`

6. **Stream Deck integration.** Operator physical control surface. Options:
   - `streamdeck-linux` Python library + xdotool/wtype
   - WebSocket relay to `:8052` command registry (hapax-logos command relay)
   - Map keys to: preset selection, camera profile, stream-mode toggle, manual activity override, auto-private override, research-registry open/close
   - Config in `config/streamdeck.yaml`
   - Systemd user unit `streamdeck-adapter.service`

7. **YouTube description auto-update as research transparency surface.** GDO already has `LivestreamDescriptionUpdater` class in `youtube-player.py`. Extend:
   - Description template:
     ```
     Condition: {condition_id}
     Claim: {claim_id}
     Objective: {current_objective.title}
     Sub-experiment: {sub_experiment_id}
     Reactions: {reaction_count}
     Substrate: {substrate.model}
     ```
   - Updates on every condition change (via research-registry event hook)
   - Updates on every objective change
   - OAuth scope: `youtube.force-ssl` (needs operator re-consent per GDO 2026-04-09 handoff §5.1)
   - Quota: 50 units per update, 10000/day → ~200 updates/day. Conservative update cadence (e.g., every 15 min or on event).

8. **"Stream as affordance" reconciliation.** GDO Phase 2 Stage 6 parked this. Under Phase 8, it's implemented: `studio.toggle_livestream` affordance already exists; the new extension is that Hapax autonomously recruits the affordance when an objective requires it (e.g., "demonstrate grounding behavior live as part of turn-pair-coherence validation"). Affordance pipeline integration is already there (PR #730).

9. **Research-mode surface inventory — additional tiles beyond hero mode.** Phase 8 adds three research-mode compositor tiles not covered by hero-mode camera switching:
   - **Logos studio view tile** — selectively composited operator control surface. Renders the Logos fullscreen (or a subset region) as a tile source. Stream-mode-aware redaction via Phase 6 API gates. Position: configurable via layout JSON, default lower-right quadrant in `public_research` mode.
   - **Terminal capture tile with secret obscuration** — captures a terminal or IDE region via wf-recorder or equivalent. Pre-compositor pipeline: regex-based blur on known secret patterns (`pass show`, `LITELLM_*`, `*_API_KEY`, `Authorization: Bearer`, etc.) before the frame reaches the compositor. Only active in `public_research` mode.
   - **PR / CI status overlay** — polls the current git state + GitHub Actions state for the current branch, renders as a Cairo overlay: current branch, CI status, open PR URL, test pass/fail count, latest commit SHA (short). Updates on push / CI event. Data source: git + `gh` CLI + SHM cache.
   - All three surfaces are Cairo sources following the existing `CairoSourceRunner` pattern. Registration in `SourceRegistry` with `source_id: logos_studio_view`, `terminal_capture`, `pr_ci_status`. Research-mode layout JSON assigns them to pip surfaces.

10. **Hapax-initiates-interaction mechanism.** From the operator's DF-1 framing: *"Hapax can call on me to interact."* New primitive: when the activity selector scores `chat` or `study` with a strong operator-attention hypothesis, Hapax generates an *attention bid* signal rather than simply speaking. Attention bid delivery channels:
   - ntfy notification (short text)
   - TTS via daimonion on a **dedicated operator-only audio sink** — not routed through `mixer_master`, so the bid never reaches stream audio. Implementation: either a new PipeWire sink `hapax-attention-bids` separate from `hapax-voice-fx-capture` (which feeds the streamed studio output), or a secondary Kokoro output path targeted at the operator's local headset sink directly.
   - Visual flash on the operator's Logos sidebar (brief, non-interrupting)
   - Optional: Stream Deck LED cue
   Logs to `~/hapax-state/attention-bids.jsonl` for post-hoc analysis. Bids respect `executive_function` axiom — hysteresis gate (no more than 1 bid per 15 min), stimmung-gate (suppressed when stimmung stance is critical or degraded), operator override via stream-deck button or voice command "not now." Channel selection is operator-configurable via `config/attention-bids.yaml`.

11. **Environmental perception → content highlighting (salience-driven surface emphasis).** From the operator's DF-1 framing: *"Hapax can highlight what it finds interesting in the environment."* Mechanism: the existing Pi NoIR perception fleet + contact mic + visual chain already produces salience signals (IR hand activity, motion delta, audio onset, imagination fragment salience). Phase 8 wires these as *surface-emphasis inputs* to the objective selector — when a high-salience environmental signal co-occurs with an active objective that has "observe" or "react" in `activities_that_advance`, the compositor briefly emphasizes the relevant surface (hero mode on the appropriate camera, overlay highlight on the active object, audio duck on competing sources). Distinct from hero mode (activity-driven) and from attention bids (operator-facing) — this is audience-facing environmental foregrounding.

12. **Overlay content system is already operational; formalize it as a Phase 8 primitive.** The GDO overlay content system at `agents/studio_compositor/overlay_zones.py` already cycles 85 documents from `~/Documents/Personal/30-areas/stream-overlays/` (Pascal Pensées, Musil, Montaigne, historical docs). Phase 8 formalizes this by adding a `stream-overlays/` subfolder for research-mode content (claim summaries, citation cards, methodology notes) that the objective selector can cycle in when the `study` activity is active. Reuses existing Pango rendering, DVD-screensaver bounce, IBM VGA font stack. No new infrastructure — just content authoring + a new zone in `overlay_zones.py` config.

**Exit criteria:**

- `~/Documents/Personal/30-areas/hapax-objectives/` exists with at least 3 objectives authored (operator-created)
- `hapax-objectives.py` CLI operational
- Director loop's activity selector scores against objective advancement (verify by reading LLM prompt logs)
- Objective visibility overlay renders in the lower-right quadrant
- Camera profile switching works: manual `studio.camera_profile.set hero_operator` moves compositor to hero mode with < 1 frame latency (display-side scaling) or < 500ms (v4l2 framerate change)
- Director selects camera profile based on activity (verified via journal logs)
- Stream Deck maps keys to actions; verify operator can trigger 5 common actions without leaving physical control surface
- YouTube description auto-updates on condition change (verify via YouTube Studio)
- At least one autonomous "stream as affordance" recruitment logged
- Three research-mode tiles (Logos studio view, terminal capture with regex obscuration, PR/CI status) registered in `SourceRegistry`; each renders in `public_research` layout; each redacts correctly when tested against a sample secret-laden terminal frame
- Attention bid mechanism triggers on synthetic high-score activity; bid lands on at least one channel (ntfy, operator-only audio, Logos sidebar flash, or Stream Deck LED); hysteresis prevents a second bid within 15 min window; critical stimmung suppresses
- Environmental perception emphasis demonstrated: induce a high-salience IR hand-activity signal while the active objective has `observe` or `react` in `activities_that_advance`; verify the relevant camera is promoted to hero mode briefly
- Overlay content system has a new `stream-overlays/research/` subfolder with at least 3 research-mode cards; overlay zone cycles them when `study` activity is active

**Risks:**
- Objectives data structure may need revision as Hapax starts pursuing them — operator may discover the 70/30 split is wrong, the scoring math is wrong, or the storage location is wrong. Iterate.
- Camera profile switching is the most technically risky. V4L2 framerate change blackout may visibly break stream continuity. Mitigation: switch only during activity transitions, not mid-activity.
- Stream Deck integration is operator-hardware-dependent. Must not block Phase 8 if the physical device is delayed.
- YouTube OAuth scope re-consent requires operator browser interaction.
- Terminal capture regex obscuration has a known failure mode: if a terminal renders the filesystem (e.g., `tree ~/.password-store/`), the regex misses. Paired with Phase 6 C3 filesystem-level visibility block as the belt-and-suspenders.
- Attention bid channel selection may surprise the operator if bids arrive via unexpected modality. Keep the bid channels operator-configurable via `config/streamdeck.yaml` or similar.

**Handoff implications:** Phase 8 is the I-3 workstream landing. After Phase 8, Hapax is a continual research programmer in the concrete sense — not just architecturally.

---

### Phase 9 — Closed-Loop Feedback + Narration + Chat Integration

**Goal:** Wire the closed loop: chat structure → audience engagement signal → operator stimmung → Hapax's activity selection → output that feeds back into chat. Enable daimonion narration of active code work. Convert the chat reactor from keyword-matching to research-aware.

**Dependency:** Phase 8 (Hapax must have objectives to be narrated about and a scoring function to be modulated).

**Intended spec path:** `docs/superpowers/specs/YYYY-MM-DD-lrr-phase-9-closed-loop-feedback-design.md`

**Theoretical grounding:** Narration unblock (Hermes 3 enables code-narration), research-aware chat reactor (Hermes 3 enables LLM-evaluating chat against research context). The closed loop IS the substrate of "never-ending research based on livestream interactions."

**Scope:**

1. **Chat monitor → structural signal → stimmung modulation.** Chat monitor (Phase 0 fix) produces structural analysis: thread count, novelty rate, participant diversity, semantic coherence (via nomic-embed). New: write these as SHM signals at `/dev/shm/hapax-chat-signals.json`. Stimmung reader consumes the SHM signal and modulates `audience_engagement` (new 12th dimension). When `audience_engagement > 0.7`, stimmung tilts toward `SEEKING`; when `< 0.3`, tilts toward `quiet_presence`.

2. **Stimmung-modulated activity selection in director loop.** Existing: director loop scores activities by prompt context. Extended in Phase 8 with objective advancement. **New in Phase 9:** activity score also includes a stimmung term. High `audience_engagement` with active chat threads → raise score for `chat` activity. Low engagement → raise score for `study` or `silence`. Critical stimmung → auto-private (Phase 6 closed loop already active).

3. **Research-aware chat reactor.** Current: `chat_reactor.py` `PresetReactor` matches chat keywords → preset name → `graph-mutation.json`. **New:** for `public_research` stream-mode, chat messages that reference the current research context trigger a different flow:
   - `chat_reactor` subscribes to `/dev/shm/hapax-chat-signals.json` for recent messages
   - Each message is embedded with nomic-embed
   - If cosine similarity to the current objective's title/notes > 0.6, flag the message as "research-relevant"
   - Research-relevant messages trigger a `study` activity biased toward the chat topic rather than autonomous topic selection
   - 30s cooldown preserved (consent-safe)
   - No per-author state (consent-safe)

4. **Daimonion narration of active code work.** Current: `study` activity narrates research thoughts. **New:** daimonion receives SHM signals from editor state (`vscode-state.json` or similar) and can narrate code edits, PR opens, test runs, error encounters. Signals:
   - `/dev/shm/hapax-editor-state.json` — current file, cursor line, recent edits
   - `/dev/shm/hapax-git-state.json` — current branch, modified files, staged files, recent commits
   - `/dev/shm/hapax-ci-state.json` — current test run status, failures, PR state
   - Daimonion activity `study` gains a sub-mode `code-narration` that narrates from these signals
   - Under Hermes 3: "I'm frustrated with this bug because the error message suggests X but the stack trace shows Y" style narration (per impact analysis §Narration). Under Qwen: unusable; this unblocks only after Phase 5.

5. **Asynchronous-first chat queue semantics.** Current: chat messages are processed in real-time with 30s cooldown per author on preset switching. **New:** chat messages also land in an async queue that Hapax reviews during the `chat` activity. The queue bounds: max 20 messages, FIFO eviction. Hapax reviews messages holistically during the activity, not on receipt. This protects `executive_function` axiom (asynchronous-first is less interrupt-heavy than real-time reactive).

6. **Scientific register caption mode.** Under persona spec (Phase 7), the default register is scientific-neutral. **New:** auto-captions (from STT) are rendered as a Cairo overlay. When stream-mode is `public_research`, captions use a scientific-register font + styling. When `public`, normal styling.

7. **Stimmung-vs-stream correlation dashboard.** Observability: Prometheus time-series of stimmung dimensions correlated with stream events (activity changes, chat engagement, audience size). Grafana dashboard panel. Purpose: validate the closed loop is working without creating a negative feedback spiral.

8. **PipeWire operator-voice-over-YouTube ducking (distinct from `#778`).** The shipped `#778` audio ducking envelope replaces the `mute_all` cliff for daimonion TTS over music — it is daimonion-voice → YouTube/music ducking. What is NOT yet shipped: **operator voice (Yeti mic via `echo_cancel_source`) ducking YouTube content** when operator speaks. Per GDO 2026-04-09 handoff §6.5 operator request: *"we will need production quality audio ducking... not A LOT but enough... YouTube ducks 24c mix when playing, mic ducks YouTube when talking. 6-10dB smooth crossfade."* Implementation:
   - New PipeWire filter-chain node: `operator-voice-sidechain` — reads operator VAD from `echo_cancel_source`, generates a control signal
   - YouTube audio sink (`youtube-audio-{0,1,2}` per `SlotAudioControl`) routes through a `sc-compressor` with sidechain input from the operator VAD
   - Threshold: 6 dB attenuation when operator VAD active, 0 dB when silent, 80ms attack + 200ms release for smooth crossfade
   - Disable-able via stream-deck button for "I want to interrupt without ducking YouTube" cases
   - Tested alongside the existing #778 ducking — verify the two ducking paths don't fight each other

9. **Daimonion code-narration signal sources.** The narration in scope §4 above requires signal publishers. Phase 9 also ships these:
   - `/dev/shm/hapax-editor-state.json` — vscode / nvim / whatever editor plugin publishes current file, cursor line, last edit timestamp, unsaved buffer count
   - `/dev/shm/hapax-git-state.json` — `scripts/publish-git-state.sh` systemd timer (5s) publishes current branch, modified files list, staged count, last 3 commit SHAs
   - `/dev/shm/hapax-ci-state.json` — `scripts/publish-ci-state.sh` polls `gh run list --branch <current>` every 30s, publishes state
   - These are the SHM counterparts to the existing editor signals the director loop reactor context assembler can read via `ContextAssembler.snapshot()`

**Exit criteria:**

- `/dev/shm/hapax-chat-signals.json` is written by chat monitor, read by stimmung
- Stimmung has `audience_engagement` dimension; dashboard shows it tracking chat-monitor signal
- Director loop's activity scoring includes stimmung term; verify by reading LLM prompt in high-engagement vs low-engagement state
- Research-aware chat reactor triggers on objective-similar message in public_research mode
- Daimonion code-narration operational; verify by editing a file and listening to Hapax narration
- Async chat queue bounded; verify by flooding 50 messages and confirming FIFO eviction
- Scientific register captions render when stream-mode is public_research
- Grafana dashboard shows stimmung × stream correlation; operator reviews for closed-loop sanity
- PipeWire operator-voice-over-YouTube ducking operational: speak into Yeti mic while YouTube audio plays; verify 6 dB attenuation within 80ms attack, return within 200ms release; verify no conflict with `#778` daimonion-TTS ducking when both fire simultaneously
- SHM signal publishers (`hapax-editor-state.json`, `hapax-git-state.json`, `hapax-ci-state.json`) active and updating; verify `ContextAssembler.snapshot()` reads them; daimonion falls through to generic `study` narration if any signal is stale > 30s

**Risks:**
- Closed loop is oscillation-prone. High engagement → more chat activity → more engagement → feedback loop. Damping required. Start with conservative weights (10%).
- Daimonion code-narration requires editor/git/CI signal publishers. If any signal source is flaky, narration becomes incoherent. Mitigation: daimonion falls through to generic `study` narration if signals are stale > 30s.
- Research-aware chat reactor may activate on tangentially-related messages. Threshold tuning needed.

**Handoff implications:** Phase 9 closes the closed loop. After Phase 9, Hapax's content programming is reactive to chat + operator + objectives simultaneously.

---

### Phase 10 — Observability, Drills, Polish

**Goal:** Add per-condition Prometheus slicing. Build stimmung dashboards. Write the 18-item continuous-operation stability matrix. Run the operational drills. Address FINDING-S (SDLC pipeline dormant). Ship the remaining polish items.

**Dependency:** Phase 9 complete.

**Intended spec path:** `docs/superpowers/specs/YYYY-MM-DD-lrr-phase-10-observability-drills-polish-design.md`

**Scope:**

1. **Per-condition Prometheus slicing.** Extend metrics to include `model_condition` label:
   - `tabbyapi_request_duration_seconds{model_condition="cond-phase-a-baseline-qwen-001"}`
   - `stream_reactions_total{model_condition, activity}`
   - `turn_pair_coherence_score{model_condition}`
   - `voice_grounding_directive_compliance_rate{model_condition}`

2. **Stimmung dashboards.** Grafana panels:
   - 11-dim stimmung time-series by condition
   - Stance transition frequency
   - SEEKING dwell time
   - Auto-private trigger count per day
   - Correlation with activity selection
   - Correlation with chat engagement

3. **18-item continuous-operation stability matrix.** Per GDO 2026-04-09 handoff 36h checklist, now reframed as indefinite-horizon requirements. Each item is a monitoring surface, not a launch gate:

   | # | Item | Monitoring | Alert |
   |---|---|---|---|
   | S1 | compositor frame stalls | `gst_frame_duration_seconds_bucket` | p99 > 40ms for 5min |
   | S2 | compositor GPU memory growth | `nvidia_smi_process_memory{process="studio-compositor"}` | slope > 10 MiB/hour |
   | S3 | v4l2sink renegotiation cascade | `v4l2_caps_negotiation_total` | rate > 0.1/s |
   | S4 | audio capture thread death | `compositor_audio_capture_alive` | 0 for > 30s |
   | S5 | youtube-player ffmpeg death | `youtube_player_ffmpeg_alive` | 0 for > 30s |
   | S6 | chat-downloader reconnect | `chat_monitor_reconnect_total` | rate > 1/min |
   | S7 | album-identifier memory growth | `album_identifier_process_memory` | slope > 5 MiB/hour |
   | S8 | logos-api connection pool | `logos_api_http_connections_open` | > 100 |
   | S9 | token-ledger write latency | `token_ledger_write_duration_ms` | p99 > 100ms |
   | S10 | Pi NoIR heartbeat | `pi_noir_heartbeat_age_seconds` | > 120 |
   | S11 | PipeWire mixer_master alive | `pipewire_node_alive{name="mixer_master"}` | 0 |
   | S12 | NVENC encoder session count | `nvidia_encoder_session_count` | > 3 |
   | S13 | YouTube RTMP connection | `rtmp_connection_state` | != "connected" for > 30s |
   | S14 | /dev/video42 loopback write | `v4l2_loopback_write_rate{device="video42"}` | = 0 for > 10s |
   | S15 | /data inode usage | `node_filesystem_files_free{mountpoint="/data"}` | < 15% free |
   | S16 | /dev/shm growth | `node_filesystem_used_bytes{mountpoint="/dev/shm"}` | > 8 GiB |
   | S17 | HLS segment pruning | `hls_segment_count` | > 1000 |
   | S18 | hapax-rebuild-services interference | `rebuild_services_mid_stream_events` | rate > 1/hour |

   All alerts route to ntfy + Grafana annotations.

4. **Operational drills.** Run each at least once; document results:
   - Pre-stream consent verification drill
   - Mid-stream consent revocation drill (covered in Phase 6; re-verify here)
   - Stimmung breach → auto-private drill
   - Failure-mode rehearsal (RTMP disconnect, Hermes 3 OOM, MediaMTX crash, v4l2loopback loss, Pi-6 network drop)
   - Privacy regression suite under load
   - Audience engagement A/B (research-mode chat behavior)

5. **FINDING-S SDLC pipeline decision.** Per alpha close-out retirement handoff. 324 dry-run events, 0 production executions, all 5 stages DORMANT. Present 3 options (retire, revive with fixed workflows, integrate with epic):
   - **Option 1: Retire.** Delete `.github/workflows/auto-fix.yml` + `claude-review.yml` + `profiles/sdlc-events.jsonl`. Free up CI minutes.
   - **Option 2: Revive.** Fix the 100%-failure workflows; run in dry-run for 2 weeks; assess.
   - **Option 3: Integrate.** The SDLC pipeline's Triage → Plan → Implement → Review → Gate stages could orchestrate *this epic's* phase execution. Requires substantial integration but would be a meaningful research artifact (Hapax orchestrating its own SDLC on the livestream).
   - Operator decision required. Default: Option 1 (retire) unless operator chooses otherwise.

6. **T3 prompt caching redesign.** Per alpha close-out handoff. ~100 lines across 3 files, ~42% per-turn cost reduction on cache hits, 40-60% TTFT drop on 2nd+ turn within 5-min cache window. Pattern 3 (prompt caching with `cache_control` markers). Ship in Phase 10 as performance polish; important because Hermes 3's TTFT is the stress risk.

7. **`director_loop.py` PERCEPTION_INTERVAL tuning.** Per impact analysis §Performance. Hermes 3's longer response times overlap with 8s perception cadence. Increase to 12s (or dynamic based on last response time). Test under Condition A' live traffic.

8. **Consent audit trail.** Surface per-contract audit log at `axioms/contracts/audit.jsonl`. Every contract create / revoke / enforce event logged. Queryable via `scripts/consent-audit.py`.

9. **Per-surface visibility audit log.** `/dev/shm/hapax-surface-audit.jsonl` — every time a surface is added or removed from the stream output, log it. Queryable for post-hoc analysis of what was visible when.

10. **Remaining delegated polish from PR #775.** Verify these landed (they may have landed mid-epic):
    - Prometheus scrape gap for studio-compositor (queue 024 FINDING-H — may still be open). **Cross-repo:** the actual fix is a 7-line yaml addition to `llm-stack/prometheus.yml` adding a `studio-compositor` scrape job targeting `127.0.0.1:9482`. Listed as A12 in the 2026-04-14 alpha close-out retirement trivial-deferrals. The 6-month drift between "compositor exposes metrics" and "Prometheus scrapes them" is the longest-lived gap in the stack and must be closed as part of Phase 10.
    - `node-exporter :9100` DOWN target restoration (Sprint 6).
    - A11 LiteLLM scrape path fix `/metrics` → `/metrics/` (cross-repo `llm-stack/`). 1 yaml line.
    - A13 `ufw` rules for `172.18.0.0/16 → 9100, 9482` (operator-gated sudo). 2 commands.
    - Q023 #53 Grafana dashboard panel fixes (cross-repo).

11. **Uninterrupted 2-hour compositor stability window drill** (R11 from alpha close-out retirement handoff). Run the compositor continuously under typical livestream load for 2 hours without operator intervention. Monitor: frame drops, memory growth, v4l2sink renegotiation events, GPU memory drift, cudacompositor element survival. Success: zero unhandled errors, memory footprint within ±5%, frame rate stable. Distinct from the 18-item matrix (which is continuous monitoring); this is an explicit attended drill.

12. **Daimonion in-process Prometheus exporter (C2 from alpha close-out, ~300 lines)** and **VLA in-process Prometheus exporter (C3, ~200 lines)**. Both are observability depth items that raise signal quality beyond the current SHM-file-based metrics. Phase 10 includes them as optional polish — ship if time permits, defer if Phase 10 is already full.

13. **Weekly stimmung × stream correlation report.** Automated report: Saturday 08:00 local timer runs `scripts/weekly-stimmung-report.py`, aggregates the past 7 days of stimmung dimensions × stream events × reaction counts × operator sleep data, renders to a vault note at `~/Documents/Personal/40-calendar/weekly/YYYY-WW-stimmung-stream.md`. Answers the standing question: "is the stream net positive or net negative on operator cognitive load this week?" Closes the `executive_function` axiom loop at the reporting cadence.

14. **Pre/post stream stimmung delta protocol.** Lightweight: at every stream-mode transition (off → public_research or the reverse), capture a stimmung snapshot. Delta analysis in the weekly report. Operator-side observation protocol: brief subjective rating (1-5) logged via a stream-deck button or voice command after each streaming session. Forms the qualitative companion to the quantitative stimmung time series.

**Exit criteria:**

- All 18 stability matrix items have Prometheus series + alerts
- Grafana stimmung dashboard operational; panels show current data
- All 6 operational drills run at least once; results in `docs/drills/2026-*.md`
- FINDING-S decision made and committed (retire / revive / integrate)
- T3 prompt caching landed; observe TTFT improvement under Hermes 3
- PERCEPTION_INTERVAL tuned; verify no activity overlap in logs
- Consent audit trail queryable
- Surface visibility audit log operational
- Per-condition Prometheus slicing operational; verify via `curl http://localhost:9482/metrics | grep model_condition`
- Uninterrupted 2-hour compositor stability drill run and documented; zero unhandled errors, memory footprint within ±5%, frame rate stable
- Cross-repo scrape fixes landed: A11 (LiteLLM `/metrics/`), A12 (`studio-compositor` scrape job in `llm-stack/prometheus.yml`), A13 (`ufw` rules). Verify via `curl http://localhost:9090/api/v1/targets | jq '.data.activeTargets[].labels.job'` shows `studio-compositor`
- Daimonion in-process Prometheus exporter (C2) and VLA in-process Prometheus exporter (C3) live (or explicitly deferred with rationale)
- Weekly stimmung × stream correlation report runs via systemd timer; at least one week's report generated in `~/Documents/Personal/40-calendar/weekly/`
- Pre/post stream stimmung delta protocol operational: at least one stream-mode transition captured with pre + post snapshots + operator subjective rating
- Privacy regression suite has a test that scrapes rendered compositor frames for any text matching known operator utterance patterns (catches voice-transcript firewall regressions)

**Risks:**
- Per-condition labels multiply metric cardinality. Prometheus may struggle with 10+ conditions × dozens of dimensions. Cardinality management needed.
- Drills may surface new issues; budget time for follow-up fixes.
- T3 prompt caching changes the prompt structure; may break Hermes 3 behavior. Test against benchmark before deploying.

**Handoff implications:** Phase 10 is the epic's polish layer. After Phase 10, LRR is complete. Any future work is a new epic within the ongoing research program.

---

## 6. Risk register (epic-level)

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | Phase 0 is treated as "nothing new" and skipped | Medium | High | Phase 0 exit criteria gate Phase 1 start. |
| R2 | Phase 1 metadata backfill loses data | Low | High | Qdrant snapshot before backfill; test on copy first. |
| R3 | Phase 3 Hermes 3 quant unavailable pre-made | Medium | Medium | Self-quantization path; fallback to Qwen3.5-32B EXL3 if self-quant fails. |
| R4 | Phase 3 PSU fails stress test | Low | High | PSU replacement; fallback to Option α (single-GPU TabbyAPI Hermes 2.5bpw). |
| R5 | Phase 4 Condition A data collection too slow (livestream hours insufficient for sample target) | Medium | Medium | Livestream-run-gated; co-specify realistic target with operator at Phase 4 open; extend collection window as needed. Engineering bootstrap (scope items 1–4) is not blocked by this risk. |
| R6 | Phase 5 Hermes 3 directive compliance below threshold | Medium | High | Rollback + 3.5 bpw re-quant; plan §10 documents this. |
| R7 | Phase 6 FINDING-R requires operator policy decision | Medium | Medium | Present 3 options in Phase 6 spec. |
| R8 | Phase 7 persona spec doesn't land because operator doesn't approve | Medium | High | Multiple iteration cycles planned. |
| R9 | Phase 8 objectives framework requires substantial iteration | High | Medium | Expect iteration; don't lock v1 prematurely. |
| R10 | Phase 9 closed loop oscillates | Medium | Medium | Conservative initial weights; Phase 10 monitoring catches divergence. |
| R11 | Phase 10 per-condition Prometheus cardinality explosion | Medium | Low | Limit label cardinality; use recording rules. |
| R12 | Branch discipline blocks entire epic execution | Medium | High | Write docs to relay context staging site until branches unblock. Resolve PR #775 to unblock. |
| R13 | Research validity compromised by undetected frozen-file edit | Low | Critical | Pre-commit enforcement (Phase 1 item); deviation records mandatory. |
| R14 | Token pole reflects 0% of actual LLM spend (chat-monitor writers still missing) | **High** | Medium | Phase 0 items 2; verified as hard gate. |
| R15 | Operator cognitive load from 24/7 stream violates executive_function axiom | Medium | Critical | Phase 6 stimmung auto-private; Phase 10 monitoring; operator override for false positives. |
| R16 | The epic is too large for a single session or single operator | **High** | Medium | Multi-session coordination via relay. Each phase ≤ 4 sessions max. |
| R17 | GDO's "stream as affordance" and I-3 objectives framework are reconciled incorrectly | Medium | Medium | Phase 8 explicitly reconciles. |
| R18 | Kokoro-GPU spike competes with compositor + imagination + Hermes 3 overflow layers for GPU 0 VRAM | Medium | Medium | Phase 3 budget shows ~3.75 GiB headroom on GPU 0 under Option γ; StyleTTS 2 / small GPU TTS fits in ~1-3 GiB. Benchmark in Phase 5; fall back to CPU Kokoro if budget exceeded. |
| R19 | New PipeWire operator-voice-over-YouTube ducking (Phase 9) conflicts with existing `#778` daimonion-TTS-over-music ducking envelope | Medium | Low | Both ducking chains are sidechain-compressor-based. Test matrix: operator speaks during daimonion speaks during music — verify both envelopes apply cleanly without oscillation or dead zones. Mitigation: share a single sidechain bus with two VAD inputs. |
| R20 | 2-hour compositor stability drill (Phase 10) surfaces new latent issues | Medium | Medium | Drill is the point — finding issues is success. Budget follow-up fixes within Phase 10. |
| R21 | Cross-repo fixes (A11 LiteLLM scrape, A12 Prometheus scrape-job, A13 ufw rules) require operator access to `~/llm-stack/` repo and sudo | Low | Low | Well-understood; batch them in one cross-repo PR + one sudo session during Phase 10. |
| R22 | G3 sprint gate blocker turns out to require upstream stats methodology decisions outside LRR scope | Medium | Medium | Phase 4 has Option 1 (resolve inside) and Option 2 (document blocker, wait). Fall back to Option 2 gracefully. |
| R23 | Voice transcripts read-side firewall regression: a code path surfaces transcript text on stream despite the gate | Low | Critical | Phase 6 exit criterion includes a regression test. Add a Phase 10 privacy-regression suite item that scrapes the rendered compositor frame for any text matching a known operator utterance pattern. |
| R24 | Layout-declared `video_out` migration (Phase 2 item 10) breaks the currently hardcoded rtmp/v4l2 output path mid-transition | Medium | High | Dual-path during migration — hardcoded sinks stay active until layout-declared sinks verified side-by-side. Cutover is one commit, not a refactor. |
| R25 | Fortress enum retirement/rename (Phase 6 item 10) breaks a non-obvious consumer | Low | Low | grep for all uses of the enum value before removal; compile-check; if any consumer exists, rename rather than delete. |

---

## 7. Rollback strategy

Per-phase rollback:

- **Phase 0–3:** Each change is a separate PR. Individual PR revert suffices.
- **Phase 4:** Cannot rollback data collection. If Condition A is invalidated (e.g., undetected frozen-file edit), close the condition with a failure marker and open a new one.
- **Phase 5:** Hermes 3 swap is reversible per the Phase 3 rollback procedure. Condition A' is closed with `status: rolled_back`, Qwen3.5-9B resumes, a new condition is opened under Qwen (e.g., `cond-phase-a-post-rollback-qwen-003`).
- **Phase 6:** Governance changes are additive. Rollback via PR revert per change.
- **Phase 7:** Persona spec is versioned. Rollback to previous version via filesystem revert + condition change.
- **Phase 8:** Objectives are append-only; failed objectives are closed, not deleted.
- **Phase 9:** Closed loop can be disabled via stream-mode fallback to `public` (without `_research`). Returns to Phase 8 behavior.
- **Phase 10:** Polish layer; individual items revertible.

Catastrophic rollback: if the epic becomes unworkable at any phase, the fallback is to close the current condition with `status: epic_paused`, resume manual Legomena Live operation, and write a retrospective.

---

## 8. Cross-session coordination

**Relay protocol integration:**

- Each phase start: the session writing the phase updates `~/.cache/hapax/relay/{role}.yaml` with `current_item: lrr-phase-N` and `focus: <phase name>`
- Each phase complete: the session writes a phase handoff at `docs/superpowers/handoff/YYYY-MM-DD-lrr-phase-N-complete.md`
- Phase handoff contents: what shipped, what's still open, exit criteria state, any deviations, next phase prerequisites
- Convergence logging: any parallel work by peer session (e.g., performance research on PR #775) logged to `convergence.log`
- Context artifacts: any phase with >30min of accumulated understanding writes a context artifact at `~/.cache/hapax/relay/context/lrr-phase-N-*.md`

**Operator in-the-loop moments:**

- Phase 4 OSF pre-registration filing (one-way; needs operator sign-off)
- Phase 5 Hermes 3 swap (attended operation; high-risk)
- Phase 6 constitutional implication submission (operator sign-off)
- Phase 7 persona spec authoring (multiple iteration cycles)
- Phase 8 objectives authoring (operator creates the first 3 objectives)
- Phase 10 FINDING-S SDLC decision (operator chooses retire / revive / integrate)

**Operator off-the-loop moments:**

- Phase 0, 1, 2, 3 (pre-swap infrastructure)
- Phase 9 (closed loop wiring)
- Phase 10 (observability + drills)

---

## 9. Dependencies + sequencing

```
Phase 0 (Verification)
    ↓
Phase 1 (Research Registry)
    ↓
Phase 2 (Archive Instrument)
    ↓
Phase 3 (Hardware Validation) ─┐
                               │
Phase 4 (Phase A Completion) ──┴──→ Phase 5 (Hermes 3 Swap)
                                         ↓
                                    Phase 6 (Governance Finalization)
                                         ↓
                                    Phase 7 (Persona Spec)
                                         ↓
                                    Phase 8 (Content Programming via Objectives)
                                         ↓
                                    Phase 9 (Closed Loop Feedback)
                                         ↓
                                    Phase 10 (Observability + Drills + Polish)
```

Phases 1-3 can in principle overlap (Phase 1 is registry infrastructure, Phase 2 is archive infrastructure, Phase 3 is hardware prep) but branch discipline serializes them. Phase 4's livestream-run-gated collection window (scope items 5–8) can overlap with Phase 3 (hardware prep) and with Phase 5 preparation because collection throughput is determined by stream hours, not engineering-session availability. Phase 4's engineering bootstrap (scope items 1–4) is serialized like every other code block.

---

## 10. Per-phase spec promotion schedule

Each phase section in this doc is intended to be extracted into its own spec file at phase start. Suggested schedule:

| Phase | Spec file | Written at |
|---|---|---|
| 0 | `docs/superpowers/specs/YYYY-MM-DD-lrr-phase-0-verification-design.md` | Phase 0 open |
| 1 | `docs/superpowers/specs/YYYY-MM-DD-lrr-phase-1-research-registry-design.md` | Phase 1 open |
| 2 | `docs/superpowers/specs/YYYY-MM-DD-lrr-phase-2-archive-research-instrument-design.md` | Phase 2 open |
| 3 | `docs/superpowers/specs/YYYY-MM-DD-lrr-phase-3-hardware-validation-design.md` | Phase 3 open |
| 4 | `docs/superpowers/specs/YYYY-MM-DD-lrr-phase-4-phase-a-completion-design.md` | Phase 4 open |
| 5 | `docs/superpowers/specs/YYYY-MM-DD-lrr-phase-5-hermes-3-substrate-swap-design.md` | Phase 5 open |
| 6 | `docs/superpowers/specs/YYYY-MM-DD-lrr-phase-6-governance-finalization-design.md` | Phase 6 open |
| 7 | `docs/superpowers/specs/YYYY-MM-DD-lrr-phase-7-persona-spec-design.md` | Phase 7 open |
| 8 | `docs/superpowers/specs/YYYY-MM-DD-lrr-phase-8-content-programming-via-objectives-design.md` | Phase 8 open |
| 9 | `docs/superpowers/specs/YYYY-MM-DD-lrr-phase-9-closed-loop-feedback-design.md` | Phase 9 open |
| 10 | `docs/superpowers/specs/YYYY-MM-DD-lrr-phase-10-observability-drills-polish-design.md` | Phase 10 open |

Each spec is extracted from the corresponding section of this umbrella doc. The plan companion doc (`docs/superpowers/plans/YYYY-MM-DD-lrr-phase-N-*.md`) is written at phase start with TDD/checkbox task breakdown.

---

## 11. Exit: what success looks like

When all 11 phases are complete and their exit criteria hold:

- Hapax runs on Hermes 3 70B SFT-only, dual-GPU layer-split, at sub-4s voice round-trip
- Legomena Live is 24/7 with research-grade observability
- Research registry holds ≥ 2 conditions (Qwen baseline + Hermes swap) with full per-segment metadata
- Option B claim (SFT-vs-DPO under grounding directives) has data in both conditions; pre-registration filed
- Hapax holds ≥ 3 research objectives and programs content in service of them
- Persona spec v1 is active; Hapax's output register is measurably different from generic assistant
- Governance closed loops (consent, stimmung auto-private, presence detect) are operational
- Chat structure → stimmung → activity selection loop is wired
- Daimonion narrates active code work on-stream
- Operational drill suite is exercised; 18-item stability matrix monitored
- FINDING-R, FINDING-Q 2-4, FINDING-S all resolved
- Archival pipeline is research-retained, not YouTube-only
- The stream is the research, the research is the stream, Hapax is running both

**This is the end-state triad operationalized.**

---

End of epic design doc. Next action: alpha drafts per-phase plans starting with Phase 0 once branch discipline unblocks.
