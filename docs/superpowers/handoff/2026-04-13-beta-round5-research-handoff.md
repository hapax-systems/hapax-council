# Beta Session Retirement Handoff — Round-5 Unblock + Gaps Research (Queue 026)

**Session:** beta
**Worktree:** `hapax-council--beta` @ `research/round5-unblock-and-gaps` (off main `5f8a6a292`)
**Date:** 2026-04-13 19:00–19:20 CDT
**Queue item:** 026 — fifth-round-unblock-plus-gaps-research
**Depends on:** PR #752, #756, #759, #764 (queues 022–025)
**Inflection:** `20260414-000000-alpha-beta-round5-research-brief.md`
**Register:** scientific, neutral (per `feedback_scientific_register.md`)

## One-paragraph summary

Six-phase research shipped. **Two phases (1 + 2) are design
docs that unblock alpha's next session** — copy-pasteable code
sketches for the BETA-FINDING-L task supervisor and a full
Provider interface definition for BETA-FINDING-N, plus a finding
that reframes BETA-FINDING-N scope (the obsidian plugin has no
LLM calls, so the "providers module missing" is specification
drift, not a missing feature). **Four phases (3–6) are new
audits** that each surfaced concrete follow-ups:

- **Phase 3 (Critical, NEW)**: `hapax-imagination` has crashed
  **65 times in the last 24 hours** with wgpu shader/pipeline
  validation errors. Every restart is systemd-managed so the
  operator never sees it, but the imagination state resets each
  time. Root cause: DynamicPipeline shader hot-reload drifts
  out of sync with `pass.param_order`.
- **Phase 4 (Governance HIGH)**: Qdrant consent gate covers
  only 2 of 10 live collections (`documents`, `profile-facts`).
  `stream-reactions` (2178 pts with `chat_authors` field),
  `hapax-apperceptions`, `operator-episodes`, and `studio-moments`
  all contain person-adjacent data but bypass the consent gate
  on upsert. Combined with BETA-FINDING-K (the consent *reader*
  was silently off), this is a two-layer governance failure.
- **Phase 5**: T3 formulation redesign scoped. Recommendation is
  **prompt caching with `cache_control` markers** (Pattern 3) —
  ~100 lines, ~42% per-turn cost reduction on cache hits,
  first-token latency drops 40–60% on 2nd+ turn within 5-min
  window. Pattern 2 (speculative formulation) deferred as a
  SEEKING-stance gated follow-up.
- **Phase 6**: The LLM-driven SDLC pipeline has **never fired
  in production mode** (324 dry-run events, 0 real). 5 of 5
  SDLC stages DORMANT. `auto-fix.yml` + `claude-review.yml` are
  failing 100% of pushes with 0s runtime.

## Phase ship record

| phase | doc | status |
|---|---|---|
| 1 — task supervisor design | `phase-1-task-supervisor-design.md` | **shipped** — 3-pattern comparison, experimental evidence via `test-supervisor-patterns.py`, recommended Pattern 3 (supervisor loop) with copy-pasteable code sketch |
| 2 — obsidian providers design | `phase-2-obsidian-providers-design.md` | **shipped (reframed)** — plugin has no LLM calls; Path B (refine the probe) recommended over Path A (build the providers module), Path A fully designed for future use |
| 3 — imagination Rust runtime profile | `phase-3-imagination-runtime-profile.md` | **shipped** — process/GPU/frame snapshot, pool reuse_ratio=0 bug, 65 wgpu validation crashes/24h (NEW CRITICAL) |
| 4 — Qdrant state audit + schema drift | `phase-4-qdrant-state-audit.md` | **shipped** — 10 collection inventory, 2 schema drifts, `operator-patterns` empty, consent gate thin coverage (HIGH governance gap) |
| 5 — cognitive-loop T3 redesign | `phase-5-cognitive-loop-t3-redesign.md` | **shipped** — 3-pattern comparison, cost model, recommended prompt caching with implementation sketch |
| 6 — SDLC pipeline audit | `phase-6-sdlc-pipeline-audit.md` | **shipped** — 100% dry-run pipeline, all stages dormant, auto-fix/claude-review broken, "ship or retire" decision recommended |

## Convergence-critical findings

### BETA-FINDING-Q (Critical, NEW): hapax-imagination 65-crash/day wgpu validation storm

**Source phase:** Phase 3
**Severity:** CRITICAL — continuous imagination state reset cycle

**Evidence**

```bash
$ journalctl --user -u hapax-imagination.service --since "24 hours ago" | grep -c "Failed with result"
65
```

Every failure is a Rust panic with the same signature:

```text
[ERROR wgpu::backend::wgpu_core] Handling wgpu errors as fatal by default
thread 'main' panicked at wgpu-24.0.5/src/backend/wgpu_core.rs:1303:26:
wgpu error: Validation Error
    Error matching ShaderStages(FRAGMENT) shader requirements against the pipeline
```

**Root cause:** DynamicPipeline shader hot-reload drifts out of
sync with `pass.param_order` serialization in
`uniforms.json`. When Python writes a new shader with a
different `@group(2) Params` struct layout than what the
pipeline expects, wgpu's fragment-stage validation panics and
the Rust binary exits with status 101.

**Fix path:**

1. Enable `RUST_BACKTRACE=1` in the systemd unit drop-in for
   clearer traces on the next crash
2. Add a pre-wgpu-load validation check comparing shader WGSL
   struct field order vs `pass.param_order`
3. Ship a fallback panic handler that rolls back to the
   previous-good shader instead of crashing
4. Expose `hapax_imagination_shader_rollback_total` counter

**Effort:** multi-hour investigation + fix. Alpha should prioritize
after BETA-FINDING-L (task supervisor) lands.

### BETA-FINDING-R (HIGH, GOVERNANCE): Qdrant consent gate covers only 2 of 10 collections

**Source phase:** Phase 4
**Severity:** HIGH — `interpersonal_transparency` (weight 88) partial gap

**Evidence**

`agents/_governance/qdrant_gate.py:38`:

```python
PERSON_ADJACENT_COLLECTIONS: dict[str, str] = {
    "documents": "document",
    "profile-facts": "document",
}
```

Only 2 collections listed. The other 8 live collections skip
the consent check on upsert. Of those 8:

- `stream-reactions` (2178 pts) has a `chat_authors` field —
  people's display names from livestream chat
- `hapax-apperceptions` (130 pts) has `trigger_text` +
  `observation` text fields that may reference non-operator
  persons
- `operator-episodes` (1681 pts) has session data that may
  include guest co-occurrences
- `studio-moments` (1965 pts) has `audio_file`, `video_files`,
  `transcript_snippet` that may contain third-party audio/video/speech
- `axiom-precedents` has `situation` text that may reference
  third parties

None of these is consent-checked. Combined with BETA-FINDING-K
(consent *reader* was silently off — fixed in PR #761),
this is a **two-layer governance failure**:

1. Writer side: most person-adjacent data bypasses the consent
   gate on upsert (this finding)
2. Reader side: consent filtering was silently disabled for
   reads (BETA-FINDING-K, already fixed in PR #761)

PR #761 closed the reader side. This finding exposes the
writer side.

**Fix path:**

1. Audit each non-gated collection's payload schema
2. Add collections with person-adjacent fields to
   `PERSON_ADJACENT_COLLECTIONS` and specify
   `PERSON_FIELDS` per collection
3. Add a reverse-guard: for every non-gated upsert, assert the
   payload has no known person-field patterns. Fail-closed.

**Effort:** 2–3 hours. Fix pattern matches PR #761.

### BETA-FINDING-S (MEDIUM): SDLC pipeline 100% dry-run dormant

**Source phase:** Phase 6
**Severity:** MEDIUM — opportunity cost, not a live bug

**Evidence:** `profiles/sdlc-events.jsonl` has 324 events across
3 weeks, all `dry_run: true`. Zero real pipeline firings. All 5
SDLC stages (triage, plan, implement, review, axiom-gate) are
dormant. `auto-fix.yml` and `claude-review.yml` fail 100% of
pushes with 0s runtime (inferred: YAML skip-conversion bug).

**Decision required:** operator must pick **use or retire**.
If use: create a trivial issue, apply `agent-eligible` label,
watch the pipeline fire. If retire: remove scripts + workflows
+ CLAUDE.md § SDLC Pipeline section.

### Reframing finding: BETA-FINDING-N is a probe misspec, not a missing feature

**Source phase:** Phase 2
**Severity:** (clarifies earlier finding)

Queue 025 Phase 1 flagged `obsidian-hapax/src/providers/` as a
missing directory that violates `corporate_boundary`. Phase 2
of this round walked the plugin's actual surface and confirmed
**the plugin has no LLM calls anywhere**. `LogosClient` exposes
14 methods, none of which call an LLM. The sufficiency probe
`_check_plugin_direct_api_support` is enforcing a commitment
to a future feature, not validating current behavior.

**Recommendation:** rewrite the probe to gate on conditional
presence (if any LLM call site exists, require providers/),
and defer the actual providers module implementation until the
operator asks for an LLM feature in the plugin. Full Path A
design is in Phase 2 doc if the operator does want it.

## Unblock pointers for alpha's next session

Phase 1 and Phase 2 are explicitly scoped as unblocks.

### Alpha: BETA-FINDING-L fix (task supervisor)

**Read**: `docs/research/2026-04-13/round5-unblock-and-gaps/phase-1-task-supervisor-design.md`

**Implementation sketch is in § The recommendation.** Copy the
`_supervise_background_tasks` function sketch, wire it into the
main loop at `run_inner.py:182`, update the shutdown path to
use the new `_background_tasks_by_name` dict, add the three
test cases from § Tests.

**Runtime risk mitigation** (§ Effort + risk assessment): ship
with every task in `RECREATE_TASKS` on day 1, promote to
`CRITICAL_TASKS` after 24 hours of clean operation.

**Estimated effort:** 2–3 hours including tests + review.

### Alpha: BETA-FINDING-N decision

**Read**: `docs/research/2026-04-13/round5-unblock-and-gaps/phase-2-obsidian-providers-design.md`

**Recommendation: ship Path B (refine the probe), defer Path A
(build providers module).** Path B is 30 minutes; Path A is
multi-day and may not be needed at all.

Path B changes:

1. Rewrite `_check_plugin_direct_api_support` in
   `shared/sufficiency_probes.py` (full replacement in
   Phase 2 § Refined probe)
2. Update `axioms/implications/corporate-boundary.yaml`
   `cb-llm-001` to add `conditional: true` + revised text
3. Same pattern for `_check_plugin_graceful_degradation` which
   also checks for a non-existent `qdrant-client.ts`

### Alpha: BETA-FINDING-Q fix (imagination crash storm)

**Read**: `docs/research/2026-04-13/round5-unblock-and-gaps/phase-3-imagination-runtime-profile.md`

**Recommendation:** multi-step investigation, not a single
patch. See Phase 3 § Proposed fixes (F1 path). First step:
enable `RUST_BACKTRACE=1` via systemd drop-in so the next
crash gives a usable stack trace.

## Ranked fix backlog (items 133–167)

Full list in each phase doc's "Backlog additions" section.
Cross-section summary:

### Critical

- **133**: `fix(daimonion): implement Pattern 3 task supervisor` [P1, closes BETA-FINDING-L] — alpha can implement directly from Phase 1 sketch
- **142**: `fix(hapax-imagination): 65-crash/day wgpu validation storm investigation` [P3 F1, BETA-FINDING-Q] — multi-hour
- **152**: `fix(qdrant-gate): add stream-reactions + other person-adjacent collections to PERSON_ADJACENT_COLLECTIONS` [P4 Finding 3, BETA-FINDING-R] — 2-3 hours

### High

- **137**: `fix(axioms): rewrite _check_plugin_direct_api_support` [P2 Path B, BETA-FINDING-N reframe]
- **138**: `fix(axioms): rewrite _check_plugin_graceful_degradation` [P2 secondary]
- **143**: `fix(hapax-imagination): pool reuse_ratio = 0 bug` [P3 F2]
- **144**: `feat(hapax-imagination): RUST_BACKTRACE=1 systemd drop-in` [P3 F1 prep]
- **146**: `fix(hapax-imagination): WGSL shader + param_order manifest validation` [P3 F1 sub]
- **147**: `feat(hapax-imagination): fallback panic handler with shader rollback` [P3 F1 sub]
- **149**: `fix(qdrant-schema): add hapax-apperceptions + operator-patterns to EXPECTED_COLLECTIONS` [P4 Finding 1]
- **150**: `feat(qdrant-schema): reverse-check for unexpected live collections` [P4 Finding 1 sub]
- **151**: `decision(operator-patterns): wire timer OR retire collection+module` [P4 Finding 2]
- **153**: `feat(qdrant-gate): reverse-guard for unknown person-looking fields` [P4 Finding 3 sub]
- **156**: `feat(daimonion): system prompt restructure for prompt caching` [P5 Change 1]
- **157**: `feat(daimonion): add cache_control markers in _generate_and_speak` [P5 Change 2]
- **162**: `decision(sdlc): use or retire the LLM-driven SDLC pipeline` [P6 Action A, BETA-FINDING-S]

### Medium

- **134–136**: observability counters for task supervisor [P1]
- **139**: `docs(axioms): update cb-llm-001 implication text` [P2]
- **145**: `feat(hapax-imagination): per-pass timing via wgpu Query::Timestamp` [P3]
- **154**: `docs(claude.md): add stream-reactions to Qdrant list` [P4, carry-over]
- **155**: `research(qdrant): investigate operator-patterns retirement` [P4]
- **158**: `feat(daimonion): cache telemetry (hit ratio + cached tokens)` [P5 Change 3]
- **159**: `research(daimonion): measure cache first-token latency delta` [P5 validation]
- **163**: `fix(github-actions): debug auto-fix + claude-review 0s failures` [P6 Action B]

### Low

- **140**: `feat(obsidian-hapax): direct-provider LLM module (Path A)` [P2, deferred until feature needed]
- **141**: `research(axioms): audit all sufficiency probes for spec drift` [P2 broader]
- **148**: `research(hapax-imagination): 15:25 SIGABRT outlier` [P3]
- **160**: `feat(daimonion): Pattern 2 speculative formulation under SEEKING` [P5, deferred]
- **161**: `docs(feedback_cognitive_loop): refine memory for control vs formulation` [P5]
- **164**: `feat(sdlc): hapax_sdlc_last_real_event_age_seconds gauge` [P6]
- **165**: `research(sdlc): trigger pipeline on a live issue` [P6 Action A sub]
- **166**: `docs(claude.md § SDLC): revise or retire` [P6]
- **167**: `research(council): "ship or retire" sprint` [P6 pattern]

## Rounds 1–5 convergence

Across 5 rounds, the same failure patterns recur:

| pattern | examples | refined response |
|---|---|---|
| **Silent catch converting loud bug to silent** | BETA-FINDING-K, M, L, _no_work_data, check_full, axiom-commit-scan.sh, many more | Pattern class recognized. PR #761 fixed FINDING-K. Backlog items 89, 91, 92, 96 cover the rest. |
| **Completeness without wiring** | BudgetTracker (q022), operator-patterns (q025), SDLC pipeline (q026) | New pattern class named in Phase 6. Backlog item 167 proposes "ship or retire" sprint. |
| **Specification drift** | `EXPECTED_COLLECTIONS` missing 2, CLAUDE.md missing `stream-reactions`, sufficiency probes checking for files that don't need to exist | Phase 4 + Phase 2 reframing. Backlog items 149, 154, 141. |
| **Observability blackhole** | FINDING-H (compositor scrape gap), Phase 3 imagination crashes invisible, Phase 4 SCM metrics at floor | Queue 024 Phase 2 fix in flight for compositor. Imagination + SCM are still gaps. |
| **Cold-start vs continuous cognition** | feedback_cognitive_loop half-true (q025 P3), T3 formulation is turn-bounded | Phase 5 scoped the redesign. Backlog items 156–160. |

## Open questions for alpha + operator

1. **(alpha)** For BETA-FINDING-L task supervisor, is Pattern 3
   (supervisor loop) acceptable, or does alpha prefer TaskGroup
   for the structured-concurrency elegance? The Phase 1 sketch
   is Pattern 3 by default; Pattern 2 recommendation is
   documented if alpha wants to switch.
2. **(operator)** The SDLC pipeline is 100% dormant. Decision
   needed: use or retire.
3. **(operator)** The `operator-patterns` Qdrant collection is
   empty and its writer has no timer. Decision needed: wire
   the timer or drop the collection.
4. **(alpha)** The hapax-imagination 65-crash-storm needs a
   dedicated investigation session with `RUST_BACKTRACE=1`
   enabled. When does alpha want to schedule this?
5. **(alpha)** Phase 2 recommends Path B (refine the probe) for
   BETA-FINDING-N. Does this match your preference, or do you
   want Path A (build the providers module) for defensive
   readiness even though it's not needed today?

## Coordination notes

- **Alpha is actively shipping fixes in parallel** during this
  session: BETA-FINDING-M (`_no_work_data` fail-closed) merged
  around 19:09 CDT; BETA-FINDING-P (`studio-compositor`
  rebuild-services migration) is in CI.
- **The Phase 3 imagination crash finding is not blocking
  alpha's next-session work** — systemd auto-restart keeps the
  daemon running, and beta did not restart anything to
  investigate. Flag was sent via convergence.log.
- **Phase 1 + Phase 2 are design-only**, intended as
  "drop-in reference" for alpha's implementation. No code
  changes shipped by beta in this round.
- **The `auto-fix.yml` + `claude-review.yml` 0s failures** are
  pre-existing noise that beta's PRs inherit. Safe to ignore
  (only freeze-check is authoritative).

## Beta retirement status

Beta considers queue 026 complete. All 6 phases shipped. The
retirement handoff consolidates items 133–167 extending the
ranked backlog from queue 022/023/024/025 (items 1–132).

Beta will commit the docs to `research/round5-unblock-and-gaps`,
push, open the PR, and stand down.

`~/.cache/hapax/relay/beta.yaml` will point at this handoff doc
as the authoritative closeout. No other beta work is in flight.
