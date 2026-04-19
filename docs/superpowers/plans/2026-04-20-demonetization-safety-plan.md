---
date: 2026-04-20
author: alpha (Claude Opus 4.7, 1M context, cascade worktree)
audience: delta (execution dispatcher) + operator
register: scientific, neutral
status: dispatchable plan — multi-phase, parallel-safe, operator-gated
task: "#165 — demonetization safety (post-live iteration)"
branch: hotfix/fallback-layout-assignment
related:
  - docs/research/2026-04-19-demonetization-safety-design.md (research source)
  - docs/research/2026-04-19-content-programming-layer-design.md (programmes, task #164)
  - docs/research/2026-04-19-youtube-content-visibility-design.md (adjacent surface)
  - docs/governance/consent-safe-gate-retirement.md (sibling gate precedent)
  - shared/governance/consent.py, shared/governance/consent_gate.py (axiom-gate precedents)
  - agents/studio_compositor/face_obscure_integration.py (egress fail-closed precedent)
  - scripts/lint_personification.py (build-time governance gate, task #155)
  - shared/affordance.py (OperationalProperties — declaration site)
  - shared/compositional_affordances.py (capability catalog)
  - scripts/youtube-player.py (half-speed hack retirement, task #66)
  - docs/superpowers/plans/2026-04-19-homage-completion-plan.md (format reference)
  - memories: feedback_no_expert_system_rules, project_programmes_enable_grounding,
    feedback_hapax_authors_programmes, feedback_grounding_exhaustive
operator-directive-load-bearing: |
  "at no point should any content ever be a red-flag for de-monetization"
  (2026-04-19)
---

# De-monetization Safety Gate — Implementation Plan

## §0. Scope, intent, and what this plan is NOT

This plan implements the architectural design in
`docs/research/2026-04-19-demonetization-safety-design.md` as a sequence
of dispatchable phases under delta orchestration. The work lands
post-live — after the HOMAGE go-live — and closes the §165 directive.

### 0.1 What this plan IS

A **governance-axiom-level fail-closed filter**, sibling to
`shared/governance/consent.py::contract_check` and
`agents/studio_compositor/face_obscure_integration.py`. The gate
occupies the axiom-enforcement layer, removing whole capability classes
from the candidate set before the decision-making layer scores anything.

**Three concentric rings** (research §4):

- **Ring 1 — capability-level filter.** Runs inside
  `AffordancePipeline.select()` adjacent to the consent filter. Reads
  `OperationalProperties.monetization_risk` and removes `high`
  capabilities unconditionally + `medium` capabilities unless the
  active programme has explicitly opted in. Capabilities never enter
  the score competition.
- **Ring 2 — pre-render classifier.** Runs on LLM-emitted text for
  externally visible surfaces. Emits `content.flagged` impingement on
  `score >= 2`; pipeline re-recruits on the signal. The classifier
  does not decide; it emits a perceptual signal.
- **Ring 3 — egress audit log.** Append-only JSONL at
  `~/hapax-state/programmes/egress-audit/<date>/<hour>.jsonl`.

Programme-layer interaction is restricted to Ring 1 via
`Programme.monetization_opt_ins: frozenset[str]` — soft priors that
expand `medium`-risk candidacy only. `high` is permanently excluded.

### 0.2 What this plan is NOT

**This is NOT a post-hoc deny-list.** No code path of the shape
`if "X" in rendered_text: withhold()`. Such a gate sits at the
decision-making layer and violates `feedback_no_expert_system_rules`.
The safety boundary is at the **candidate-filter** layer (Ring 1) —
capabilities are REMOVED from the recruitment-set before the pipeline
scores anything, the same structural move consent performs. Ring 2
does not decide either; it emits an impingement, and the pipeline's
next tick recruits an alternative capability grounded in the live
moment. **The gate removes, it does not score away.** That is the
architectural pattern preserving the no-expert-system-rules axiom
while providing governance-level fail-closed safety.

This plan does NOT introduce: runtime regex deny-lists, threshold
counters on risk words, cadence overrides, timer-based suppression,
or pre-written "safe alternative" libraries. Recovery is whatever the
pipeline recruits next tick from the `content.flagged` impingement.

This plan also does NOT prescribe the music policy (§7) — that is an
operator-gated open question (§0.4) implemented only after the
operator answers.

### 0.3 Relationship to parallel work

- **Task #164 (programme layer):** Phases 5 and 11 depend on the
  `Programme` primitive. Until it lands, Phase 5 ships as no-op stub
  (field declared, unwired); Phase 11 is sequenced after #164 Phase 1.
- **YouTube content visibility:** Phase 7 (provenance) and Phase 8
  (music policy) interact with the YouTube-visibility surface.
- **HOMAGE completion:** Phase 9 (footer) composes onto chronicle +
  captions wards that HOMAGE Phase A3 rewrites. Phase 9 is sequenced
  AFTER HOMAGE A3 lands on main.

### 0.4 Required operator inputs (blocking)

Two research §11 open questions are **required-operator-input gates**
for specific phases. Neither is resolved here.

1. **Music policy (§11 Q1).** Research §7.2 recommends YouTube
   reaction audio MUTED with transcript overlay (retiring the
   half-speed DMCA hack, task #66). Operator must confirm or
   counter-propose before Phase 8 ships. Viability under mute vs. the
   §7.2 alternative 2 (≤30 s fair-use clips with operator-
   transformative narration) is part of the same decision.
2. **False-negative tolerance (§11 Q3).** Operator input sets the
   target classifier FNR; governs Ring 2 score cutoff and
   `MAX_OPT_INS`. Phase 3 ships with conservative defaults pending.

Phases 8 and (optionally) 3's cutoff tuning BLOCK on these. Other
phases proceed without operator input.

---

## §1. Success definition — what "done" looks like

Acceptance test is a 30-minute live test stream with instrumented
telemetry plus static-analysis gates. Below are the instrument-level
criteria every phase must contribute to.

- **Capability declaration coverage.** Every `CapabilityRecord` in
  `shared/compositional_affordances.py` and every capability JSON under
  `affordances/` declares an explicit `monetization_risk` via
  `OperationalProperties`. CI-blocking test asserts 100% field
  presence; `high`-risk capabilities have non-empty `risk_reason`.
- **Candidate-set filter.** Recruitment dry-run over
  `tests/fixtures/recruitment_impingements.json`: `high` never in
  candidate set regardless of programme; `medium` only when programme
  opts in; filter runs before score competition (asserted via
  capture-side-effect in mocked scorer).
- **Ring 2 classifier round-trip.** `content_classify` against TabbyAPI
  `local-fast` (Qwen3.5-9B EXL3): **p50 ≤ 10 ms, p99 ≤ 50 ms** over 500
  samples. Benchmark at `scripts/benchmark_monetization_classifier.py`,
  results to `~/hapax-state/benchmarks/monetization-classifier/`.
- **Fail-closed on classifier unavailable.** Chaos test
  (`systemctl stop tabbyapi.service`): all LLM-generated external-
  surface text withheld; templates still emit; TTS silent; 3-failure
  degrade → `ntfy priority=high`; 5-success restore. Mirrors
  `consent_gate.py` pattern.
- **Zero high-risk in live candidate set.**
  `hapax_monetization_candidates_total{risk="high"}` remains **0** for
  the full 30-minute window. Single non-zero observation fails
  acceptance.
- **Egress audit JSONL populated.** `~/hapax-state/programmes/egress-
  audit/<date>/<hour>.jsonl` contains one entry per external-surface
  render: `timestamp`, `surface_kind`, `capability`, `rendered_text`
  (truncated 512 chars), `classifier_score`, `guideline`,
  `music_provenance`, `youtube_source`, `decision`, `decision_reason`.
  Sampling 100% post-live-48h, 10% steady-state. Daily gzip rotation,
  90-day retention via `hapax-egress-audit-rotate.timer`.
- **Half-speed hack removed.** `scripts/youtube-player.py` has no
  `_playback_rate` function and no `HAPAX_YOUTUBE_PLAYBACK_RATE`
  references. `tests/scripts/test_youtube_player_no_playback_rate.py`
  regression-pins this (task #66).
- **Anti-personification footer present.** Chronicle + captions wards
  show muted-grey low-prominence "Council research instrument —
  experimental cognitive architecture (operator: <name>, research
  home: <url>)" footer, validated once at startup and cached.
- **Observability.** Prometheus metrics `hapax_monetization_*`:
  `candidates_total{risk, filtered}`, `classifier_seconds` (histogram),
  `classifier_score_total{surface_kind, score}`,
  `classifier_degraded` (gauge), `egress_audit_entries_total`,
  `whitelist_entries` (gauge). Grafana dashboard
  `localhost:3001/d/monetization-gate/` shows strictly-increasing
  counters, zero-bar on `risk="high"`.

---

## §2. Phase list

Eleven phases. Each has: scope (file paths bounded), blocking
dependencies, parallel-safe siblings, success criteria, test strategy,
LOC range, commit-message template.

All commit directly to `hotfix/fallback-layout-assignment`. Do NOT
switch branches. Do NOT use `isolation: "worktree"`. Each commit ends
with `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`.

Size legend: **S** ≤ 200 LOC, **M** 200-500, **L** 500-1500.

### Phase 1 — `MonetizationRiskGate` primitive + field declaration

**Scope:** NEW `shared/governance/monetization_safety.py` (hosts
`MonetizationRiskGate`, `RiskAssessment` Pydantic frozen, `SurfaceKind`
enum); EXTEND `shared/affordance.py::OperationalProperties` with
`monetization_risk: Literal["none", "low", "medium", "high"] = "none"`
and `risk_reason: str | None = None`; WIRE
`MonetizationRiskGate.candidate_filter` into
`AffordancePipeline._filter_candidates` adjacent to the consent filter
(dispatch confirms exact file at run-time — likely
`agents/hapax_dmn/pipeline.py`); tests at
`tests/governance/test_monetization_safety.py` +
`tests/pipeline/test_affordance_pipeline_monetization_filter.py`.

**Description.** Ship the primitive and the field. The filter is pure:
signature `candidate_filter(capabilities, programme) -> list`.
`high` unconditionally removed; `medium` removed unless
`programme.monetization_opt_ins` contains the capability; `low`/`none`
pass through. Copy `consent.py` test fixtures as pattern template.
No Ring-2 classifier yet.

**Blocking dependencies:** None (leaf module).

**Parallel-safe siblings:** None in-plan for Wave 1; Phase 2 is serial
after Phase 1 merges to main.

**Success criteria:** ≥ 8 primitive tests (field-default, filter-high-
always-out, filter-medium-gated-by-opt-in, filter-low-passes,
filter-none-passes, programme-None-excludes-medium, programme-with-
opt-in-includes-medium, filter-is-pure); ≥ 4 pipeline-integration
tests (filter-runs-before-score, consent+monetization-compose,
high-never-in-candidates, medium-present-when-opted-in); ruff + pyright
clean; existing `consent.py` tests still pass.

**Estimated LOC:** 250-350 module + 200-300 tests. **Size: M.**

**Commit message:** `feat(governance): MonetizationRiskGate primitive +
OperationalProperties.monetization_risk`

### Phase 2 — Capability catalog audit + risk classification

**Scope:** Annotate every `CapabilityRecord` in
`shared/compositional_affordances.py` and every capability JSON under
`affordances/` with explicit `monetization_risk` + `risk_reason`; NEW
`docs/governance/monetization-risk-classification.md` (rubric +
per-capability rationale citing research §1.1); NEW
`tests/governance/test_capability_catalog_complete.py` (CI-blocking
field-presence assertion).

**Description.** One-time survey commit. Capabilities classified
against research §1.1 categories. `high`: unfiltered profanity-
eligible speech, raw-audio broadcast of non-provenanced music,
graphic-content emitters (catalog should not have any; this phase
verifies). `medium`: occasional-profanity narrative registers,
reaction-content capabilities whose input is third-party, album-art-
splattribution narrative. Everything else: `none` or `low`.

**Blocking dependencies:** Phase 1 (field declaration on main).

**Parallel-safe siblings:** Phases 4, 5, 6.

**Success criteria:** every registered capability has explicit (non-
default) `monetization_risk`; `high` capabilities have non-empty
`risk_reason`; catalog loads cleanly; governance doc published +
cross-linked from `docs/governance/README.md`; operator-reviewed
classification before merge.

**Estimated LOC:** 400-700 (annotations + governance doc). **Size: M.**

**Commit message:** `chore(governance): capability catalog — classify
monetization_risk per rubric`

### Phase 3 — Ring 2 pre-render classifier + `content.flagged` impingement

**Scope:** ADD `content_classify(rendered_text, surface_kind) ->
RiskAssessment` to `MonetizationRiskGate`; re-use the `local-fast`
LiteLLM client from the grounded director (no new VRAM); INSERT
classifier calls at `agents/cpal/production_stream.py` (TTS),
`agents/studio_compositor/captions_source.py` (captions),
`agents/studio_compositor/chronicle_*.py` (chronicle); ADD
`ContentFlaggedImpingement` + `ContentIncidentImpingement` in
`shared/impingements.py`; NEW
`scripts/benchmark_monetization_classifier.py`;
`tests/governance/test_monetization_classifier.py` +
`tests/integration/test_content_flagged_impingement_roundtrip.py`.

**Description.** Structured JSON-only sub-prompt against the grounded
director's model (Qwen3.5-9B EXL3). Prompt per research §5: cached
YouTube guidelines (24 h WebFetch refresh, stale-fallback), surface
kind, rendered text, JSON `{score, guideline, redaction_suggestion}`.
Score semantics: 0 none, 1 low (audit-only), 2 medium (withhold +
`content.flagged`), 3 high (withhold + `content.incident` +
`suppression_until = now + 5 ticks` on capability).

On `score >= 2`: no render, emit impingement carrying
`{surface_kind, score, guideline, original_capability, redaction_
suggestion}`; pipeline's next tick recruits alternative. No retry
logic; recovery is grounded in the usual recruitment loop.

LRU cache `(rendered_text → RiskAssessment, maxsize=1024)`.

Operator-gate note: score cutoff (default 2) and `MAX_OPT_INS`
(default 3) stay conservative pending operator §11 Q3 answer.

**Blocking dependencies:** Phase 1 (primitive). Phase 2 (field
coverage audited before classifier runs).

**Parallel-safe siblings:** Phases 4 (fail-closed), 5, 6, 7.

**Success criteria:** ≥ 10 classifier tests (score parsing, prompt
construction, guideline cache, LRU reuse, surface-kind discrimination,
JSON-error handling); impingement round-trip integration test green
(mock pipeline consumes + recruits alternative); benchmark records
p50 ≤ 10 ms, p99 ≤ 50 ms over 500 samples against running TabbyAPI;
post-deploy test-stream smoke: synthetic flagged utterance observed
withheld + recovery in `~/hapax-state/daimonion-cpal.jsonl`.

**Estimated LOC:** 400-600. **Size: M-L.**

**Commit message:** `feat(governance): Ring-2 pre-render classifier +
content.flagged impingement`

### Phase 4 — Classifier unavailable → fail-closed template-only

**Scope:** ADD `ClassifierDegradedController` to
`monetization_safety.py` (mirrors `consent_gate.py`'s 3-fail-degrade,
5-success-restore); wrap `content_classify` call-sites in Phase 3
modules with `if gate.classifier_degraded(): withhold`; tests at
`tests/governance/test_classifier_degraded_controller.py` +
`tests/chaos/test_fail_closed_on_classifier_unavailable.py`.

**Description.** Control law per research §9 row 3. `degrade` state
on ≥ 3 consecutive classifier failures (timeout, exception, malformed
JSON). In `degrade`: all LLM-generated external-surface emissions
withheld; TTS silent; captions frozen; chronicle holds last frame;
templates still emit (hand-authored, Ring-0-covered). `ntfy
priority=high` on entry. 5 consecutive successes restore nominal.
Pattern matches consent-gate-unavailable exactly.

**Blocking dependencies:** Phase 3.

**Parallel-safe siblings:** Phases 5, 6, 7.

**Success criteria:** ≥ 6 controller tests (3-fail-degrade, 5-success-
restore, hysteresis, thread-safe, ntfy-on-degrade, ntfy-on-restore);
chaos test (monkeypatched-raising classifier) confirms TTS silent,
captions frozen, chronicle held, templates rendering, ntfy fired.

**Estimated LOC:** 250-350. **Size: M.**

**Commit message:** `feat(governance): classifier-degraded fail-closed
path`

### Phase 5 — Programme `monetization_opt_ins` field + Ring 1 wiring

**Scope:** EXTEND `Programme` (from task #164) with
`monetization_opt_ins: frozenset[str] = frozenset()`; Ring 1 already
accepts `programme`, wire opt-ins set into its decision; ENFORCE in
`shared/programmes_validation.py`: Hapax-authored programmes with
non-empty `monetization_opt_ins` fail validation; operator-authored
allowed up to `MAX_OPT_INS = 3`; tests at
`tests/governance/test_programme_monetization_opt_ins.py`.

**Description.** Programme-layer interaction surface per research §6.
`high` permanently excluded (validation enforces). Operator-authorship
is the authorship axis: programmes are Hapax-authored per
`feedback_hapax_authors_programmes`, BUT `monetization_opt_ins` is the
one exception where operator-authored programmes bypass Hapax-only
authorship — expansion of candidacy beyond the safe set requires
operator consent, mirroring consent-gate's bilateral-contract
requirement. Hard cap `MAX_OPT_INS = 3`. Ring 2 classifier ALWAYS
runs regardless of opt-in.

**Stub mode.** Until task #164 Phase 1 lands, Phase 5 ships no-op:
field declared; Ring 1 always sees `programme=None` and filters all
medium-risk out. Follow-up commit wires live programme lookup.

**Blocking dependencies:** Phase 1 (primitive). Task #164 Phase 1 for
non-stub.

**Parallel-safe siblings:** Phases 4, 6, 7.

**Success criteria:** ≥ 6 tests (hapax-authored-with-opt-in-fails-
validation, operator-authored-with-opt-in-passes, max-opt-ins-3-
enforced, high-never-opted-in, ring-1-respects-opt-ins, ring-2-runs-
regardless-of-opt-in); pipeline filter test extended for
programme-active-with-opt-in path.

**Estimated LOC:** 150-250. **Size: S.**

**Commit message:** `feat(governance): Programme.monetization_opt_ins
+ Ring-1 wiring`

### Phase 6 — Egress audit JSONL + sampling + rotation

**Scope:** ADD `EgressAuditWriter` + `egress_log(payload, decision,
reason)` on `MonetizationRiskGate`; call `egress_log` from Phase 3
call-sites on both `rendered` and `withheld` branches; ADD
`HAPAX_EGRESS_AUDIT_SAMPLE_LOW = 0.1`,
`HAPAX_EGRESS_AUDIT_SAMPLE_HIGH = 1.0`, post-live-48h toggle in
`config/defaults.py`; NEW `systemd/user/hapax-egress-audit-
rotate.service` + `.timer` (daily gzip + 90-day prune); tests at
`tests/governance/test_egress_audit_writer.py` +
`tests/systemd/test_hapax_egress_audit_rotate_timer.py`.

**Description.** Ring 3. JSONL path
`~/hapax-state/programmes/egress-audit/<YYYY-MM-DD>/<HH>.jsonl`. Per-
entry schema per §1 success definition. Sampling configurable per
surface-kind (post-live-48h 100% across all surfaces, then
high-risk-surface 100%, low-risk 10%). Atomic append via single-
writer queue + background thread; does not block render path. Daily
gzip + 90-day retention via timer. Rotation failure ntfys but writer
continues to log (log-integrity > disk hygiene per research §9 row 5).

**Blocking dependencies:** Phase 1. Can land parallel to 3/4/5 — the
writer is ready to receive calls when Phases 3/4 wire them.

**Parallel-safe siblings:** Phases 3, 4, 5, 7, 9.

**Success criteria:** ≥ 8 writer tests (append atomicity, sampling,
truncation, hour-boundary rotation, thread-safety, queue overflow,
gzip invocation, 90-day prune); timer test passes
`systemd-analyze verify`; 30-s test-stream smoke produces ≥ 3 entries;
4-hour stream keeps egress-audit under 100 MiB.

**Estimated LOC:** 300-450. **Size: M.**

**Commit message:** `feat(governance): Ring-3 egress audit JSONL +
sampling + rotation`

### Phase 7 — Music provenance tagging

**Scope:** NEW `shared/music/provenance.py` (`MusicProvenance` Literal
type + per-track schema); ADD provenance tag on
`agents/studio_compositor/album_overlay.py` splattribution (muted-grey
BitchX register); ENUMERATE license at SoundCloud ingestion (file
confirmed at dispatch; likely `agents/music/soundcloud_ingest.py`) —
default `unknown` excluded from queue; ANNOTATE vinyl playlist loader
`operator-vinyl`; stub Hapax-pool ingestion accepting only `cc-by`,
`cc-by-sa`, `public-domain`, `licensed-for-broadcast`; wire value
through Phase 6's `music_provenance` egress-log field; tests at
`tests/music/test_provenance_loader.py`.

**Description.** Schema-first. Values: `operator-vinyl`,
`soundcloud-licensed`, `hapax-pool`, `youtube-react`, `unknown`.
`unknown` fail-closed: audio muted + `music.provenance.unknown`
impingement for operator review. SoundCloud reads license metadata at
ingest; tracks without clear license stay `unknown` + excluded.
Vinyl: trivially `operator-vinyl` (operator owns physical record;
HIGH DMCA risk on broadcast accepted as policy claim). Hapax-pool:
stub in this phase (full curation path at task #130). YouTube-react:
Phase 8 interaction surface.

Phase 7 does NOT implement the audio-mute-on-YouTube policy (that is
Phase 8, operator-gated). It establishes the data shape Phase 8
consumes.

**Blocking dependencies:** Phase 6 (egress-log schema has
`music_provenance` slot).

**Parallel-safe siblings:** Phases 3, 4, 5, 6, 9.

**Success criteria:** ≥ 6 tests (vinyl-annotation, soundcloud-licensed-
parsing, soundcloud-unknown-excluded, hapax-pool-accepts-cc-by,
hapax-pool-rejects-proprietary, youtube-react-annotation); egress log
entries carry correct `music_provenance`; album-overlay
splattribution visibly shows provenance line.

**Estimated LOC:** 300-400. **Size: M.**

**Commit message:** `feat(music): per-track provenance tagging`

### Phase 8 — OPERATOR-GATED music policy implementation

**OPERATOR GATE.** Does NOT dispatch until operator answers research
§11 Q1. Both paths below documented; operator picks one.

**Path A (mute + transcript overlay — research recommendation).**
REMOVE `_playback_rate` function + `HAPAX_YOUTUBE_PLAYBACK_RATE` env
var from `scripts/youtube-player.py` (task #66 retires here); mute
audio output via ffmpeg `-af volume=0` or pipeline-level audio-tee
drop; ADD transcript overlay surface on
`agents/studio_compositor/youtube_turn_taking.py` (or dedicated
YouTube-embed-ward renderer) rendering source captions from
`--write-subs` data in BitchX register; regression pin
`tests/scripts/test_youtube_player_no_playback_rate.py`.

**Path B (≤30 s fair-use clips — §7.2 alternative 2).** REPLACE
`_playback_rate` with `_clip_windower` enforcing ≤ 30 s contiguous
playback + ≥ 60 s operator-transformative narration gap before same-
source replay; wire windower signal into `agents/cpal/production_
stream.py` so pipeline tracks same-source cooldown; regression pin
drops on the `_playback_rate` retirement.

**Description.** Per research §7.2. Operator chooses. Whichever path,
half-speed rate manipulation is retired. Path A: Content ID is audio-
only; muted audio cannot match. Path B: higher strike risk, preserves
audio signal for reaction framing. Both preserve Phase 7 `youtube-
react` provenance.

**Blocking dependencies:** Phase 7 (provenance shape). OPERATOR ANSWER
on §11 Q1.

**Parallel-safe siblings:** Phase 9.

**Success criteria (both paths):** `scripts/youtube-player.py` no
longer defines `_playback_rate`; `HAPAX_YOUTUBE_PLAYBACK_RATE`
unreferenced; regression pin green. **Path A additional:** YouTube
audio muted on test stream; transcript overlay visible when captions
present; egress log shows `music_provenance: "youtube-react"` +
`decision: "audio_muted"`. **Path B additional:** playback cuts at 30 s
contiguous; same-source replay blocked until ≥ 60 s narration gap.

**Estimated LOC:** 150-300. **Size: S-M.**

**Commit message (path A):** `feat(youtube): mute audio + transcript
overlay (task #66 retirement)` — **Path B:** `feat(youtube): 30s fair-
use clip windower (task #66 retirement)`.

### Phase 9 — Anti-personification egress footer

**Scope:** ADD persistent footer row at bottom of
`agents/studio_compositor/chronicle_source.py` layout (muted-grey,
low-prominence, BitchX: `>>> Council research instrument —
experimental cognitive architecture (operator: <name>, research
home: <url>)`); ADD same footer beneath caption strip in
`agents/studio_compositor/captions_source.py`; footer text through
Ring 0 + Ring 2 validation once at startup + cached; ADD
`HAPAX_OPERATOR_NAME`, `HAPAX_RESEARCH_HOME_URL` in `config/
defaults.py`; tests at `tests/studio_compositor/test_chronicle_
footer.py` + `test_captions_footer.py`.

**Description.** Per research §8. Frames channel for advertiser
review without claiming AI sentience. Footer is static; one-time
validation suffices.

**Blocking dependencies:** HOMAGE Phase A3 (legibility family emissive
rewrite) on main — footer composes onto Pango-Px437 rendering path.

**Parallel-safe siblings:** Phases 3, 4, 5, 6, 7, 10.

**Success criteria:** chronicle layout snapshot shows footer bottom-row,
alpha ≤ 0.55; captions snapshot shows footer beneath caption strip;
text matches operator config (not hardcoded); startup log records
one-time Ring 2 validation pass.

**Estimated LOC:** 150-220. **Size: S.**

**Commit message:** `feat(homage): anti-personification "research
instrument" egress footer`

### Phase 10 — Operator review + whitelist CLI

**Scope:** NEW `scripts/review-flagged.sh` (wrapper invoking
`uv run python -m agents.monetization_review`); NEW
`agents/monetization_review/` (Tier-3 deterministic module — no LLM
— reads `~/hapax-state/monetization-flagged/` via `fzf` or `rich`,
operator selects accept / reject / whitelist); NEW
`~/hapax-state/monetization-whitelist.yaml` loaded by
`MonetizationRiskGate` on startup + SIGHUP; tests at
`tests/monetization_review/test_review_cli.py`.

**Description.** False-positive recovery surface. Flagged payloads
time-window 7 days at `~/hapax-state/monetization-flagged/<date>/
<capability>.jsonl`. CLI presents context (capability, surface,
rendered text, classifier rationale); accepts a decision. Whitelist
supports both regex and exact-string forms per research §11 Q6;
operator-config default. Whitelist narrows Ring 2 only — NEVER
bypasses Ring 1 high-risk filter.

**Blocking dependencies:** Phases 3 + 6.

**Parallel-safe siblings:** Phases 9, 11.

**Success criteria:** CLI runnable end-to-end; whitelist persists
across restart (YAML); SIGHUP reloads without restart; hard test asserts
whitelist NEVER bypasses high-risk filter.

**Estimated LOC:** 350-500. **Size: M.**

**Commit message:** `feat(monetization): operator review + whitelist
CLI`

### Phase 11 — Incident-recovery "quiet-frame" programme

**Scope:** NEW `shared/programmes/quiet_frame.py` (vinyl-only music,
no TTS, no chronicle narrative, ward emphasis on biometric-rest);
ADD auto-entry hook on `ContentIncidentImpingement` in
`agents/hapax_dmn/programme_switcher.py` (or programme-transition
surface from task #164); tests at
`tests/programmes/test_quiet_frame_transitions.py`.

**Description.** Per research §9 row 1 + §10 Phase 8. On score-3
incident, auto-enter `quiet-frame` for 20 ticks: LLM-emitted external-
surface text disabled; vinyl-only music continues; ward emphasis on
rest (breathing, stillness); anti-personification footer preserved.
Auto-exits after 20 ticks to prior programme. Operator can force
earlier exit via Stream Deck cue. Suppression on same impingement
source during active quiet-frame window prevents auto-entry loop.

**Blocking dependencies:** Phase 3 (incident impingement type). Task
#164 Phase 1 (programme primitive).

**Parallel-safe siblings:** Phase 10.

**Success criteria:** incident → quiet-frame entry within ≤ 2 ticks;
auto-exit after 20 ticks; operator forced exit works; post-deploy
injection test: synthetic score-3 utterance triggers entry with TTS
silent + vinyl continuing + rest-emphasis.

**Estimated LOC:** 200-300. **Size: M.**

**Commit message:** `feat(programmes): quiet-frame incident-recovery
programme`

---

## §3. Dependency DAG + critical path

### 3.1 Graph

```
Phase 1 (primitive + field) ─── BLOCKER
       │
       ├─> Phase 2 (catalog audit)
       ├─> Phase 3 (Ring 2) ─── BLOCKER for 4, 11
       │       │
       │       └─> Phase 4 (fail-closed)
       │
       ├─> Phase 5 (programme opt-ins; stub until task #164 P1)
       ├─> Phase 6 (egress audit) ─── feeds 7, 10
       │       │
       │       └─> Phase 7 (music provenance)
       │                   │
       │                   └─> Phase 8 (OPERATOR-GATED)
       │
       └─> Phase 9 (footer) ─── depends on HOMAGE A3 on main

Phase 10 depends on Phases 3 + 6
Phase 11 depends on Phase 3 + task #164 P1
```

### 3.2 Critical path

**Phases 1 → 3 → 4** is the minimum-viable safety surface. Rough
dispatch-hour estimates: Phase 1 ~4-6h, Phase 3 ~6-9h, Phase 4 ~2-3h.
Serial critical path: **~12-18 dispatch-hours**. Parallel dispatch on
2/5/6 in the same window brings Phases 1-7 + 9 + 10 to **~18-24
end-to-end dispatch-hours**. Phase 8 blocks on operator. Phase 11
blocks on task #164 Phase 1 (external).

### 3.3 Blockers summary

- **External:** task #164 (programme primitive) for Phases 5 (non-stub)
  and 11. HOMAGE A3 on main for Phase 9.
- **Operator:** §11 Q1 → Phase 8. §11 Q3 (optional) → Phase 3 cutoff
  tuning.
- **Phase-internal:** 2 serial after 1. 4 serial after 3. 7 serial
  after 6.

---

## §4. Per-phase risk register

| # | Phase | Highest-consequence failure mode | Mitigation |
|---|---|---|---|
| 1 | Primitive + field | Field added but wiring subtly wrong (runs after scoring) | `test_filter_runs_before_score` capture-side-effect in mocked scorer |
| 2 | Catalog audit | Miscategorised capability (high declared as low) | Governance doc rubric; operator-review pass before merge |
| 3 | Ring 2 classifier | p99 blows > 50 ms under real load | Pre-merge benchmark + LRU cache + Phase 4 control law |
| 4 | Fail-closed | Transient error fires degrade, TTS silent unnecessarily | 3-failure hysteresis, 5-success restore (proven consent-gate pattern) |
| 5 | Programme opt-ins | Hapax-authored programme sneaks opt-ins via validation bypass | Pydantic `model_validator`; tests enforce both paths |
| 6 | Egress audit | Log fills disk; rotation race drops entries | Daily gzip + 90-day prune; rotation failure ntfys, writer continues |
| 7 | Music provenance | SoundCloud metadata missing license → queue empty | Error-path `music.provenance.unknown` impingement per track |
| 8 | Music policy | Wrong path chosen; strike risk remains | Operator picks — plan does not prescribe |
| 9 | Footer | HOMAGE A3 reverts; footer floats orphan | Dispatch gate checks A3 on main |
| 10 | Whitelist | Regex too broad, re-opens risk surface | Whitelist narrows Ring 2 only; Ring 1 unbypassed; `test_whitelist_never_bypasses_ring_1` |
| 11 | Quiet-frame | Auto-entry loop (incident during quiet-frame) | Suppression on impingement source during active window; tested |

---

## §5. Branch / PR strategy

**One branch.** All phases commit to `hotfix/fallback-layout-
assignment`. No new branches. No branch switching. Subagent git-
safety directive (verbatim in every dispatch): *"You are working in the
cascade worktree. Branch is `hotfix/fallback-layout-assignment`. Commit
directly to this branch. Do NOT create branches. Do NOT run `git
checkout` or `git switch`. Do NOT switch branches under any
circumstances."*

**Per-phase PR.** The gate touches many files (catalog annotations
alone span dozens) and involves axiom-level policy decisions. Per-
phase PRs beat one mega-PR because: (a) review surface — a 200-LOC
primitive reviews faster than a 2000-LOC mixed PR; (b) partial
landing — if Phase 3 benchmarks poorly, it can hold while Phases 4/5/6/7
continue on Phase 1's merged primitive; (c) operator gates — Phase 8's
operator-block cannot sit mid-PR next to Phase 7.

**Merge order per critical path:** 1 → 2 → 3 → 4 → (6 → 7 → 8) || 5
|| 9 || 10 || 11.

**Squash-merge** to keep main history linear with one commit per
phase (HOMAGE convention). **CI:** `uv run pytest tests/ -q`,
`uv run ruff check .`, `uv run ruff format --check .`,
`uv run pyright`. Phase 3 gate: benchmark results posted as PR
comment with p50/p99 table. Phase 6 gate: `systemd-analyze verify`
on the timer unit.

---

## §6. Acceptance checklist

Work is NOT done until every item below is ticked. Go-no-go for
declaring §165 directive closed.

### 6.1 Static analysis

- [ ] `uv run pytest tests/ -q` passes (full suite)
- [ ] `uv run ruff check .` clean
- [ ] `uv run ruff format --check .` clean
- [ ] `uv run pyright` clean
- [ ] `scripts/lint_personification.py` extended (Ring 0 per research §4.4); CI-blocking
- [ ] `test_capability_catalog_complete` passes
- [ ] `test_youtube_player_no_playback_rate` passes (task #66 pin)

### 6.2 Live stream (30-minute test stream)

- [ ] `hapax_monetization_candidates_total{risk="high"}` = 0 for full window
- [ ] `hapax_monetization_classifier_seconds` p50 ≤ 10 ms, p99 ≤ 50 ms
- [ ] `hapax_monetization_classifier_degraded == 0` throughout
- [ ] Egress audit JSONL populated for every external-surface emission
- [ ] ≥ 1 synthetic score-≥2 payload withheld + recovery observed next-tick
- [ ] Anti-personification footer visible on chronicle + captions
- [ ] YouTube embed ward: path A (muted + transcript) or path B (≤30 s clip windower)
- [ ] Album overlay splattribution shows provenance tag

### 6.3 Chaos + recovery

- [ ] `systemctl --user stop tabbyapi.service` → classifier degrades within 3 attempts; TTS silent; templates emit; `ntfy priority=high` fires
- [ ] `systemctl --user start tabbyapi.service` → 5 successes restore nominal; TTS resumes
- [ ] Whitelist SIGHUP reload without restart
- [ ] Whitelist cannot bypass high-risk filter (regression green)

### 6.4 Governance

- [ ] `docs/governance/monetization-risk-classification.md` published + cross-linked
- [ ] Operator-reviewed catalog classification
- [ ] Operator §11 Q1 answer recorded + Phase 8 merged
- [ ] Operator §11 Q3 answer recorded + cutoff tuned (optional)

### 6.5 Observability

- [ ] Grafana dashboard `monetization-gate` shows strictly-increasing counters
- [ ] Zero-bar on `risk="high"` candidate counter
- [ ] `hapax-egress-audit-rotate.timer` active + tested (90-day retention)

---

## §7. Notes for execution subagents

### 7.1 Dispatch order (delta)

1. **Wave 1 (serial):** Phase 1. Merge to main.
2. **Wave 2 (parallel after Phase 1 merges):** Phases 2, 5 (stub), 6.
3. **Wave 3 (serial after Phase 2 merges):** Phase 3.
4. **Wave 4 (parallel after Phase 3 merges):** Phases 4, 7. Phase 9
   after HOMAGE A3 on main. Phase 10 after 3 + 6 merge.
5. **Wave 5 (blocked):** Phase 8 on operator §11 Q1. Phase 11 on
   task #164 Phase 1.

### 7.2 Per-dispatch prompt skeleton

```
You are working in the cascade worktree
(/home/hapax/projects/hapax-council--cascade-2026-04-18). Branch is
hotfix/fallback-layout-assignment. Commit directly to this branch.
Do NOT create branches. Do NOT run `git checkout` or `git switch`.
Do NOT switch branches under any circumstances.

Implement Phase <N> of docs/superpowers/plans/2026-04-20-demonetization-safety-plan.md
exactly as specified. Do NOT introduce expert-system rules: the gate
REMOVES capabilities at the candidate-filter layer; it does NOT score
away or threshold-gate at the decision layer. If tempted to add a
regex match, a threshold counter, or a timer gate anywhere in the
scoring or rendering path, stop and re-read §0.2.

Commit message: follow the phase's commit-message template verbatim.
```

### 7.3 Common failure mode to reject

Reject any dispatch diff containing:

- `if <token/phrase> in rendered_text`
- `if count > N` on risk words
- hardcoded regex deny-list
- `if ticks % N == 0` gating on risk
- `HAPAX_*_INTERVAL_S` env var on risk cadence

These are decision-layer patterns and violate no-expert-system-rules.
Correct move is always: (a) declare `monetization_risk` on the
capability (Ring 1), or (b) emit an impingement and let the pipeline
re-recruit (Ring 2).

### 7.4 Test-data fixtures

Phase 3 benchmark requires 500-sample rendered-text corpus:

- Recent chronicle emissions from
  `~/hapax-state/daimonion-cpal.jsonl` (tail 72 h)
- Recent TTS text from `~/hapax-state/tts-queue.jsonl`
- Synthetic injections spanning all §1.1 categories (borderline
  profanity, violence reference, controversial-issue discussion,
  graphic-detail attempt, slur attempt)

Store as `tests/fixtures/classifier_corpus_500.json`. Generator:
`scripts/build_classifier_corpus.py`.

### 7.5 Operator-gate signaling

Phases blocked on operator answer: delta updates relay status with
`monetization-plan-blocked-on-operator` field naming the question.
Operator visibility via `hapax-council` orientation panel (research
domain); sprint-measure via vault frontmatter on
`20-projects/hapax-research/2026-04-20-demonetization-gate.md`.

### 7.6 Rebase discipline

Every dispatch begins with `git fetch origin && git rebase
origin/hotfix/fallback-layout-assignment` (or `main` after merge) and
ends with `git rebase origin/hotfix/fallback-layout-assignment && git
push origin hotfix/fallback-layout-assignment` (if branch live, else
`origin/main`). Concurrent planning subagents may have pushed;
rebase-before-push mandatory.

### 7.7 Research condition

Phase 1 dispatch includes opening
`cond-monetization-gate-active-001` as its final sub-step. Director-
intent records after Phase 3 carry it; Bayesian validation slices
pre/post-gate.

### 7.8 Post-live window

Per task #165, this is post-live iteration. HOMAGE goes live first.
Phase 1 ships immediately after HOMAGE merges — Ring 1 is cheap and
post-live exposure without it is material. Phases 3-11 land over the
subsequent 48-72 hours. The 30-minute acceptance test runs after all
non-gated phases land.
