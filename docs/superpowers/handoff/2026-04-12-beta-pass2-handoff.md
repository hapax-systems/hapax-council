# Session Handoff — 2026-04-12 (beta, pass 2)

**Previous handoff:** `docs/superpowers/handoff/2026-04-12-beta-stream-handoff.md` (pass 1, ended at PR #684)
**Pre-audit context artifact:** `~/.cache/hapax/relay/context/2026-04-12-beta-three-pr-session.md`
**Audit context artifact:** `~/.cache/hapax/relay/context/2026-04-12-beta-audit-pass.md`
**Session role:** beta
**Branch at end:** `beta-standby` reset to `origin/main` at `dfcdd759f` (working tree clean) — see "Branch state" below
**Work-stream split reference:** `~/.cache/hapax/relay/context/2026-04-12-work-stream-split.md`
**Status of this beta session:** **retired after this handoff**. The next session takes over.

---

## What was shipped this session

Four PRs, all merged green, all deployed live, all verified end-to-end.

| PR | Item | Title | Merge SHA | Pass |
|----|------|-------|-----------|------|
| [#687](https://github.com/ryanklee/hapax-council/pull/687) | B6 partial | `bench(b6)`: prompt compression Phase 2 A/B benchmark on Qwen3.5-9B | `fc4ca5cbc` | 1 |
| [#689](https://github.com/ryanklee/hapax-council/pull/689) | B4 | `feat(visual)`: wire `TransientTexturePool` into `DynamicPipeline` | `8cc59b7b0` | 1 |
| [#691](https://github.com/ryanklee/hapax-council/pull/691) | CC1 (beta side) | `feat(affordance)`: register `studio.toggle_livestream` | `aefbf9676` | 1 |
| [#697](https://github.com/ryanklee/hapax-council/pull/697) | audit fixes | `fix(audit)`: consent gate, `pool_metrics`, CLAUDE.md drift, B6 caveats | `dfcdd759f` | 2 |

The session split into two passes. Pass 1 was forward work — three independent items each landing a different layer (research/benchmark, runtime infrastructure, capability registration). Pass 2 was reflective work — an explicit operator-requested audit over pass 1 that surfaced one HIGH-severity gap (consent gate) and three smaller follow-ups (pool_metrics, CLAUDE.md, B6 caveats), all bundled into a single audit-fix PR.

### Pass 1 summary

- **#687 (B6 partial)** — TabbyAPI-direct A/B latency benchmark for the Phase 1.1 system-prompt tool-directory stripping. 393 token reduction validated against the spec's ~391 estimate. 175 ms median prefill saving on Qwen3.5-9B (Δ p50). Hermes 3 70B extrapolation: ~7.86 s/turn at the design-doc 50 tok/s prefill rate. Closes the latency criterion of decision gate G-PC2; conditions C/D require Hermes 3 hardware.
- **#689 (B4)** — `DynamicPipeline.textures: HashMap<String, PoolTexture>` replaced with a slot-mapped `TransientTexturePool<PoolTexture>` per the plan from PR #683. 19 call sites migrated mechanically. Single pool key from `(width, height, format)`, recomputed on resize. 4 new pool-key bookkeeping tests. Largest unclosed loop from the compositor unification epic, now closed.
- **#691 (CC1 beta side)** — `studio.toggle_livestream` registered in `STUDIO_AFFORDANCES`. Mirrors `studio.toggle_recording` semantics (start-or-stop in one capability). `daemon=compositor` (alpha owns the trigger), `latency_class=slow` (RTMP handshake), `consent_required=True` (broadcasting room imagery to a public destination crosses the local boundary; first studio output that does so). Test pins all four properties.

### Pass 2 summary (audit-fix bundle)

The operator's instruction was: *"research and develop a multi-part audit plan batched for each phase of work completed. Look for consistency, completion, dead code, edge cases, robustness and missed opportunities."*

The audit ran in three phases:

1. **Health verification** — confirmed all four prior PRs were live in production, not just merged. **The verification caught that hapax-daimonion was ~3 hours stale** because `scripts/rebuild-service.sh:92` silently SHA-bumps without restarting Python services when alpha's worktree is on a feature branch (which it almost always is). Manual restart fixed it; the bug is flagged for alpha as a script-ownership concern.

2. **Audit plan** — six dimensions per PR: consistency, completion, dead code, edge cases, robustness, missed opportunities; plus a cross-cutting Phase D for system integration and documentation drift.

3. **Execution** — bundled into PR #697:
   - **HIGH** — `shared/affordance_pipeline.py` had no consent gate. Seven capabilities declaring `consent_required=True` (including CC1 + 6 pre-existing) were being recruited as if no consent contract existed. This is an axiom-enforcement gap (`interpersonal_transparency`). Fixed with `_consent_allows()` (60 s TTL cache, fail-closed on exception) called in `select()` immediately after `_retrieve()`. 6 new tests.
   - **MEDIUM** — `DynamicPipeline::pool_metrics()` accessor (B4 plan §4.7 deferred from #689). Returns `PoolMetrics` snapshot with `bucket_count`, `total_textures`, `total_acquires`, `total_allocations`, `reuse_ratio`, `slot_count`. Direct enabler for delta's queued PR-3 (debug_uniforms CLI + Prometheus).
   - **MEDIUM** — `CLAUDE.md` had no sections for B4, CC1, B6, or the consent gate. Three new sections added.
   - **LOW** — `docs/research/2026-04-12-prompt-compression-phase2-ab-results.md` §7 was missing 3 caveats (sample size n=20 borderline for tail estimates, `temperature=0` non-determinism on EXL3, module import side effects). Added.

---

## Decisions worth carrying forward

### Methodology decisions (apply across all four PRs)

- **TabbyAPI direct, not LiteLLM gateway, for benchmarking.** TabbyAPI's `usage` block reports `prompt_time` / `completion_time` / `total_time` already, so no streaming instrumentation is needed for headline TTFT numbers. Going through LiteLLM adds gateway overhead and an authentication dance. Per-model isolation matters more than gateway realism for prefill measurements.
- **Sequential A→B blocks, not interleaved, for cache-warm comparisons.** Prefix caches stay warm within each block. Production-realistic. Interleaving forces cache thrashing on every call and is not representative of the steady-state voice path.
- **Manual runtime smoke before merging anything that touches `~/.local/bin/hapax-imagination`.** The auto-rebuild flow will replace the binary within minutes of merge, so a runtime regression hits the operator's visual surface in front of them. Build locally, back up the running binary to a `.backup` sibling, restart, watch journalctl, then merge. Verified twice this session (B4 and audit-fix bundle). Backups deleted at session end after both deployments held.
- **Explicit `systemctl --user restart hapax-daimonion` after any change to `agents/hapax_daimonion/` or `shared/`.** The auto-rebuild script `scripts/rebuild-service.sh` does not restart Python services when alpha's worktree is on a feature branch, so the daemon will silently stay on the prior code. Until alpha fixes the script, treat the restart as required for ingest-affecting changes (affordances, embeddings, capability schemas).

### B6 specific

- `max_tokens=80` cap is intentional. With constant decode length the prefill comparison is clean; the cost is that decode-time variance becomes rate-fluctuation rather than length-driven. Documented in §7 caveats.
- The Qwen 175 ms saving is small in absolute terms; the value is the Hermes 3 70B extrapolation. At ~50 tok/s prefill, the same 393-token reduction yields ~7.86 s saved per turn. **The Qwen run validates that the savings exist; the Hermes payoff is the actual reason Phase 1.1 matters.**
- Phase 1.2–1.7 are unconditional in main and apply to both A and B. The 1.1-only delta from #687 is a **lower bound** on Phase 1's total contribution; reconstructing a pre-Phase-1 baseline would require git-archaeology + a feature flag harness. Deferred.

### B4 specific

- Followed PR #683 plan exactly. Single pool key from `(width, height, format)`, no per-frame `begin_frame()` recycling, temporal `@accum_*` textures stay in their own `HashMap` (different lifetime semantics — persist + clear, not recycle).
- `compute_pool_key` is recomputed on `resize()`, not just at `new()`. The plan §4.6 was implicit on this; I made it explicit because otherwise the pool would search for buckets with stale dimensions and miss every lookup.
- The borrow checker accepted the migration without a single annotation. Every `intermediate()` call returns `&PoolTexture` borrowed from `&self`; no `&mut self` interleaving exists in the call sites.
- **`pool_metrics()` was deferred from B4 and added in #697.** That's not ideal (the plan listed it as in-scope) but the ordering worked out — the delta session's reverie-bridge investigation (PR #696) needed exactly that accessor for its PR-3 follow-up, so the audit-fix bundle landed it just in time to be useful instead of speculative.

### CC1 specific

- `studio.toggle_livestream` was picked over the operator's colloquial `go_live` term. Mirrors `studio.toggle_recording` (start-or-stop in one capability, not split). Splitting would let the recruiter oscillate `start_livestream` / `stop_livestream` in a single tick.
- `consent_required=True` is load-bearing. Existing studio output destinations (record, snapshot, fullscreen) all stay local. Livestreaming to RTMP is **the first** studio output that crosses the local boundary. The test pins this property so a future audit cannot silently drop it.
- `latency_class=slow` is also pinned. RTMP handshake takes seconds; classifying as `fast` would let the recruiter starvation-cycle start/stop.
- The capability gets picked up at next `hapax-daimonion` startup via `init_pipeline.py` → `_affordance_pipeline.index_capabilities_batch()` → embedding + Qdrant write. **No migration script needed.** Verified end-to-end: Qdrant query for `capability_name=studio.toggle_livestream` returns the entry with all four pinned properties intact.

### Audit-fix specific (#697)

- **The consent gate is the most important fix this session.** Without it, the entire `consent_required` flag is documentation, not enforcement. Seven capabilities were affected (CC1 + 6 pre-existing — knowledge search, web search, send message, etc.). My CC1 PR's stated rationale (axiom `interpersonal_transparency`) rested on the gate working.
- **Cache TTL = 60 seconds** because `select()` is hot-pathed (per-frame in the reverie mixer at `agents/reverie/mixer.py:282`, per-impingement in `agents/hapax_daimonion/run_loops_aux.py:150`). Reading 4 yaml files per call would be wasteful. 60 s is short enough that revoked contracts take effect within a few ticks without restarting daimonion.
- **Fail-closed on any exception.** If consent infrastructure is broken, block consent_required candidates. Matches the wider `consent_engine` fail-closed control law.
- **Use `__iter__`, not `.contracts`.** The legacy gate at `shared/capability_registry.py:162` references `registry.contracts` which is not the field name (`_contracts` is). It accidentally fail-closes everything via the bare `except`. The new gate uses `__iter__` which is the supported public API and avoids the trap. The legacy gate's bug is documented in the new gate's docstring but **not fixed** — out of scope for #697, candidate for next session.
- **Filter inserted in `select()` immediately after `_retrieve()`**, before scoring is wasted on blocked candidates.
- **`pool_metrics()` accessor returns a `Copy` struct**, not a borrow. Lets external callers grab a snapshot without holding a borrow on the pipeline. Field set chosen to be stable enough that adding telemetry consumers does not require a `PoolMetrics` rewrite.

---

## State at session end

### Worktrees and branches

- `~/projects/hapax-council/` (alpha) — on `feat/a5-chat-reactive-presets` at `58bef25cf`. Alpha shipped #688 (handoff doc), #690 (cf6924b70 director loop fix), #693 (f0ccf93e8 max_tokens raise), #694 (c32787768 yt-player A12), #695 (7725629ad director loop FU-5), and has PR #698 open for A5 chat-reactive presets. Alpha is busy.
- `~/projects/hapax-council--beta/` (this session) — `beta-standby` reset to `origin/main` at `dfcdd759f`. Working tree clean. **No open local branches owned by beta.** No open PRs owned by beta.

### Binaries

- `~/.local/bin/hapax-imagination` — current production binary, built from `dfcdd759f` (post-#697). Both manual install and auto-rebuild have run; the timestamp at session end is from the auto-rebuild's pickup at 19:52. The previous manual install (19:46) and pre-B4 backup (16:19) have been deleted — the work is verified live and the auto-rebuild flow is the canonical source going forward.
- All other auxiliary binaries (`hapax-imagination.b4-backup`, `.audit-prev`, `.prev`) **deleted** at session end. There are no orphaned backup binaries left in `~/.local/bin/`.

### Services

| Service | Status | Notes |
|---|---|---|
| `hapax-imagination` | active running | Frame pump 60-90 fps after #696 reverie bridge fix landed and #697 audit-fix binary installed. |
| `hapax-daimonion` | active running | 4 active consent contracts loaded (operator↔agatha, simon, guest, contract--2026-03-23). 143 capabilities batch-indexed with the new consent gate code. |
| `logos-api` | active running | 95/97 health checks passing, 0 failed, 2 degraded (`sync.gcalendar_freshness`, `sync.langfuse_freshness` — pre-existing sync staleness, not blocking). |
| `hapax-dmn` | active running | Picked up by the same rebuild path as daimonion. |
| `studio-compositor` | active running | Alpha territory; verified active for cross-stream sanity. |

### Qdrant

- `affordances` collection has 171 points (143 capabilities + interrupt handlers + tool affordances). `studio.toggle_livestream` verified present with all four decision properties intact (`daemon=compositor`, `latency_class=slow`, `consent_required=true`, fresh activation state with `ts_alpha=2.0` / `ts_beta=1.0` / `use_count=0` newcomer prior).

### Tests

- 43 affordance pipeline tests pass (was 37, +6 consent gate tests in #697).
- 5 studio affordance tests pass (was 4, +1 toggle_livestream property pin in #691).
- 34 hapax-visual Rust tests pass (was 29, +4 pool-key tests in #689 and +1 pool_metrics test in #697).
- B6 benchmark reproduces with the identical 393-token delta on the live TabbyAPI.

---

## Open questions for the next session (in priority order)

### Top recommendations

1. **Re-run the B4 end-to-end smoke now that #696 has landed.** Frame pump should sustain 60-90 fps under full chain delta load (was ~33 fps under empty-bridge conditions). Capture `pool_metrics()` snapshots before and after a plan reload to confirm the bucket count, allocation count, and reuse ratio behave as expected. The accessor is now available and ready for direct use. Sanity-check: `bucket_count` should stay at 1 (current pipeline uses one descriptor for every intermediate), `slot_count` should match the number of named intermediates in the loaded plan, `reuse_ratio` should rise after a few resize cycles.

2. **Pick up delta's queued PR-3 — debug_uniforms CLI + Prometheus metric for the visual chain bridge.** This is the natural consumer of the new `pool_metrics()` accessor. Cross-stream collaboration with the delta workstream. Should be small (~30-60 lines of Rust to expose pool_metrics over the existing UDS or a new endpoint, plus the Python-side scrape config). Context: `~/.cache/hapax/relay/context/2026-04-12-delta-reverie-bridge-fix.md` (delta's artifact).

3. **Pick up delta's queued PR-2 — reverie-monitor extension to watchdog `hapax-imagination-loop.service`.** During delta's investigation that service was found inactive (Bachelard Amendment 4 reverberation consumer was offline). Delta started it manually and #696 fixed unit hygiene (`StartLimit*` + `OnFailure` moved to `[Unit]`, `Requires=hapax-dmn` added), but the prediction monitor doesn't yet alert when it goes silent. Adding a watchdog probe is a small focused PR.

4. **Fix the legacy `shared/capability_registry.py:162` consent gate.** It references `registry.contracts` (the field is named `_contracts`) and accidentally fail-closes everything via the bare `except Exception`. This means the legacy class-based capability system has been silently fail-closing on every consent-required capability for who knows how long. Small focused PR (~10 lines + a test). The right fix is to use `__iter__` like the new gate in `affordance_pipeline.py` does. Documented in the new gate's docstring as a code comment.

5. **B6 §4.5 tool recruitment validation.** Cheap closeout for another G-PC2 criterion. Reuses the `scripts/benchmark_prompt_compression_b6.py` scaffold — add a `--mode recruitment` flag that runs 20 utterances through `ToolRecruitmentGate.recruit()` with both prompt variants and asserts the recruited tool sets are identical. Validates that compressing the system prompt does not perturb tool recruitment. ~50 lines of additional script logic.

### Lower priority but worth knowing

6. **Flag `scripts/rebuild-service.sh:92` to alpha for fix.** The script silently SHA-bumps without restarting Python services when alpha's worktree is on a feature branch (which it almost always is). Caused `hapax-daimonion` to be ~3 hours stale after CC1 merged (caught only by manual `ExecMainStartTimestamp` check). Recommended fix mirrors `hapax-rebuild-logos.timer`: detach the worktree to `origin/main` before the branch check, or check whether `branch_HEAD == origin/main_HEAD` and restart anyway in that case. **Alpha-owned script — do not edit unilaterally; flag via beta.yaml or a direct relay convergence note.**

7. **`any_intermediate().unwrap()` latent panic at `hapax-logos/crates/hapax-visual/src/dynamic_pipeline.rs:1359/1419/1448`.** Pre-existed in the old `self.textures.values().next().map(...).unwrap()` shape — not a B4 regression. Saved by the constructor's `ensure_texture(MAIN_FINAL_TEXTURE)` in practice. Defensive `or_else` chains would be the right fix; medium effort, low value, only matters if a future code path constructs a `DynamicPipeline` without the bootstrap `ensure_texture` call.

8. **Sprint 0 G3 gate state mismatch.** `docs/research/dmn-impingement-analysis.md` and `docs/research/sprint-0-review.md` both say G3 PASSED with 0.0% contradiction rate. But `logos-api /api/sprint` still reports `blocking_gate=G3`. Likely a sprint-state sync issue between the analysis docs and the gate-state file the API reads from. Outside Stream B but session-context surfaces it as "BLOCKING: G3" in the startup banner — worth a check.

9. **B5 hardware ETA for Hermes 3 70B.** Three of the four G-PC2 criteria from the B6 spec are hardware-gated (grounding compliance, KV-cache Q8, full latency benchmark conditions C/D). They cannot move forward until the hardware lands. **The Phase 1.2–1.7 unconditional optimisations are also bundled in main and would benefit from a separate baseline measurement, but that needs git-archaeology + a feature flag harness to reconstruct the pre-Phase-1 prompt path.** Deferred.

---

## Convergence sightings logged

- A1 (#679) + B1 (#678) — both 2026-04-12 incident resilience fixes. Same pattern: runtime state loss should auto-recover without operator intervention.
- A10 hapax_span fix is cross-cutting — every caller whose yielded block could raise was affected. Probably masked silent failures across all 5 circulatory systems. Beta's systems may have benefitted post-merge.
- PR #644 (Sierpinski visual layout, alpha) deleted `spirograph_reactor.py` without migrating `_load_playlist` — classic partial-migration bug that surfaced once the upstream noise (hapax_span RuntimeError) cleared.
- CC1 (#691) unblocks alpha's A7 (native GStreamer RTMP). Beta-side affordance registration is the prerequisite the work-stream split called out.
- delta PR #696 (reverie bridge fix) + beta PR #697 (`pool_metrics` accessor) are COMPLEMENTARY. The bridge fix delivers full chain-delta churn (42+ uniforms/tick instead of 6); `pool_metrics` surfaces the bookkeeping needed to observe what the pool is actually doing under that load. Delta's queued PR-3 (debug_uniforms + Prometheus) is the natural composition.

Full convergence log: `~/.cache/hapax/relay/convergence.log`.

---

## What the next beta should NOT do

- **Do not edit `scripts/rebuild-service.sh`.** Alpha-owned. Flag the bug via convergence log or beta.yaml.
- **Do not edit alpha's worktree.** `~/projects/hapax-council/` belongs to the alpha session; cross-worktree edits risk merge conflicts and lock contention.
- **Do not delete the B4 plan doc** at `docs/superpowers/plans/2026-04-12-b4-transient-pool-wiring.md`. It is the executable record of the implementation decisions and the explicit non-goals; future B4 follow-ups (per-frame `begin_frame()` recycling, Python-side `pool_key` emission, temporal-texture pooling) reference it.
- **Do not re-run the B6 benchmark in RESEARCH mode and expect the same numbers as R&D mode.** RESEARCH mode tags voice traces `environment=research` and does not affect TabbyAPI directly, but it slows down some background timers. The numbers should be close but not identical. Document the mode in the run output if you re-run.
- **Do not assume `consent_required=True` was always enforced.** Until #697 it was not. If you find behaviour that depended on the gate being on (e.g., a recruitment outcome that should have been blocked but wasn't), check whether the relevant code path was exercised before or after `dfcdd759f`.

---

## Memory updates

The auto-memory system (`MEMORY.md`) accumulated several entries this session through delta's parallel work and via the natural memory-write path. The relevant beta-session-related additions to consider:

- Document the consent gate fix as a project memory entry (`project_consent_gate_audit.md`) so future sessions know the gate exists and what it does. **Recommended action for next session.**
- Document the rebuild-service.sh feature-branch bypass as a feedback entry (`feedback_rebuild_service_branch_bypass.md`) parallel to the existing `feedback_rebuild_logos_worktree_detach.md`. **Recommended action for next session.**
- The B4 wiring is mostly captured in CLAUDE.md's "Reverie Vocabulary Integrity" section already; no separate memory needed.

---

## Session-end checklist (verified)

- [x] All 4 PRs merged green
- [x] Beta-standby reset to `origin/main` at `dfcdd759f`
- [x] No open beta branches (only alpha's `feat/a5-chat-reactive-presets` remains, in alpha's worktree)
- [x] No open PRs owned by beta
- [x] All affected services restarted and verified healthy (`hapax-imagination`, `hapax-daimonion`, `logos-api`, `hapax-dmn`, `studio-compositor`)
- [x] Qdrant has the new CC1 capability with all decision properties intact
- [x] Consent gate active in production (4 contracts loaded → permissive)
- [x] Auto-rebuild has picked up the new binary at `~/.local/bin/hapax-imagination`
- [x] Backup binaries deleted (no orphans in `~/.local/bin/`)
- [x] Status file `~/.cache/hapax/relay/beta.yaml` updated
- [x] Pre-audit context artifact `~/.cache/hapax/relay/context/2026-04-12-beta-three-pr-session.md`
- [x] Audit context artifact `~/.cache/hapax/relay/context/2026-04-12-beta-audit-pass.md`
- [x] Convergence log updated (latest entry: 2026-04-12T19:51:48-05:00)
- [x] CLAUDE.md updated for B4, B6, CC1, consent gate (in #697)
- [x] B6 results doc updated with the 3 missing caveats (in #697)
- [x] This handoff document

**Beta session retired.** The next session should start with `~/.cache/hapax/relay/onboarding-beta.md` and read this handoff.
