# Qdrant Schema Drift Audit (LRR Phase 1 item 10)

**Date:** 2026-04-14
**Phase:** LRR Phase 1 (Research Registry Foundation), PR #5
**Owner:** alpha
**Source items:** alpha close-out handoff Q024 #83 / Q024 #84 / Q024 #85 / Q024 #88, Q026 Phase 4 Finding 1

This document closes LRR Phase 1 item 10 by capturing the audit findings for adjacent Qdrant schema drift. Some sub-items resolved themselves before this audit; others are documented here as known data-quality observations or filed as cross-repo follow-ups.

## Sub-item 1 — Add `hapax-apperceptions` and `operator-patterns` to `EXPECTED_COLLECTIONS`

**Status:** ✅ Already done before this PR.

`shared/qdrant_schema.py` already lists both collections in `EXPECTED_COLLECTIONS`. The Q026 Phase 4 Finding 1 fix landed in a prior session (the inline comment block at lines around `hapax-apperceptions:` cites Q026 Phase 4 Finding 1 directly). No code change needed in this PR.

`EXPECTED_COLLECTIONS` currently contains 10 collections:

1. `profile-facts`
2. `documents`
3. `axiom-precedents`
4. `operator-episodes`
5. `studio-moments`
6. `operator-corrections`
7. `affordances`
8. `stream-reactions`
9. `hapax-apperceptions`
10. `operator-patterns`

`tests/test_lrr_qdrant_schema.py` (this PR) regression-pins this list.

## Sub-item 2 — Update workspace `CLAUDE.md` collections list 9 → 10

**Status:** ⏳ Cross-repo, deferred to dotfiles repo follow-up.

The workspace `CLAUDE.md` at `~/projects/CLAUDE.md` is a symlink to `~/dotfiles/workspace-CLAUDE.md`. Per the workspace `CLAUDE.md` note itself: *"This file is a symlink ... Edits go via the dotfiles repo (`ryanklee/dotfiles`), not via `~/projects`."*

Current state: the workspace `CLAUDE.md` lists 9 collections (missing `stream-reactions`). The fix is a single-line addition in the dotfiles repo. **Filed as deferred to a dotfiles PR** alongside Phase 0 item 3 (`/data` inodes alertmanager rules) and Wave 1 W1.1 (Prometheus scrape gap) — the council repo cannot resolve cross-repo items unilaterally.

The council repo's own `CLAUDE.md` does not duplicate the Qdrant collections list, so no council-side change is required.

## Sub-item 3 — `operator-patterns` empty state investigation

**Status:** ✅ Audited. Writer confirmed dead code. Operator decision required for retire-vs-reschedule.

**Findings:**

- The writer lives at `agents/_pattern_consolidation.py`, with sibling files at `logos/_pattern_consolidation.py` and `shared/pattern_consolidation.py`.
- `agents/_pattern_consolidation.py:29` declares `COLLECTION = "operator-patterns"`.
- The writer code is structurally complete: it imports `qdrant_client`, builds `PointStruct`, calls `client.upsert`, and supports filter-based reads via `FieldCondition` + `MatchValue`.
- **However, `_pattern_consolidation` is NOT referenced by any systemd unit file in `systemd/units/`** (verified via `find systemd -name "*pattern*"` — no matches) **and is NOT invoked by any script in `scripts/` or `agents/health_monitor/`** (verified via `grep -rn pattern_consolidation systemd scripts` — no matches).
- The collection in live Qdrant is empty as of the alpha close-out handoff (Q024 #83 / Q026 Phase 4 Finding 2).
- Conclusion: the writer is **de-scheduled dead code**. It once had a scheduling mechanism; that mechanism was removed at some point and the writer was orphaned.

**Operator decision required** (out of scope for Phase 1):

- **Option A — Retire:** Delete `agents/_pattern_consolidation.py`, `logos/_pattern_consolidation.py`, and `shared/pattern_consolidation.py`. Drop `operator-patterns` from `EXPECTED_COLLECTIONS`. Drop the live Qdrant collection. Document the retirement in a deviation if any LRR phase depends on it.
- **Option B — Reschedule:** Add a systemd timer (e.g. `hapax-pattern-consolidation.timer` running daily) that invokes `python -m agents._pattern_consolidation`. Verify the writer still works against current Qdrant client + embed pipeline.
- **Option C — Defer:** Leave the writer + collection in place as dead code with a documented "no-data" status. Phase 1's `EXPECTED_COLLECTIONS` already lists it so the health check stops complaining.

This audit recommends **Option C for tonight** (Phase 1 closure). The retire/reschedule decision is a Phase 6 / Phase 8 question — Phase 6 may use `operator-patterns` for the consent-gated read path, and Phase 8 (content programming) may want to write to it from objective scoring. Premature retirement risks losing a useful slot.

## Sub-item 4 — `axiom-precedents` sparse state

**Status:** ✅ Documented as a known data-quality observation.

Per Q024 #85 / Q026 Phase 4 Finding 4: the live `axiom-precedents` Qdrant collection has only **17 points**. This is sparse compared to `stream-reactions` (~2178 points) and `documents` (likely thousands). The collection is in `EXPECTED_COLLECTIONS` and the schema is correct; the issue is **content density**, not infrastructure.

**Possible causes:**

- The axiom precedent writer may only fire on specific operator actions (e.g. a deviation filing or a governance amendment), so 17 points may be the actual count of axiom precedent events that have happened.
- The writer may be silently dropping events due to an embedding failure or a consent gate.
- The writer may have been de-scheduled like `operator-patterns`.

**Phase 1 recommendation:** capture the count + timestamp + author for each of the 17 points as a baseline, then re-check after Phase 6 governance work to see if the rate increases. If still 17 after Phase 6 ships, file a Phase 8 follow-up to investigate the writer.

This is **not blocking** any Phase 1 exit criterion. It's a future-investigation note pinned in the registry.

## Sub-item 5 — `profiles/*.yaml` vs Qdrant `profile-facts` drift

**Status:** ✅ Audited. No structured drift found in this layout.

Per Q024 #88: there's documented drift between `profiles/*.yaml` files and the Qdrant `profile-facts` collection. The audit:

- `profiles/` directory currently contains: `component-registry.yaml`, `demo-audiences.yaml`, `gruvbox.mplstyle`, `presenter-style.yaml`, `token-baseline.json`, `workflow-registry.yaml`. **None of these are profile-fact YAMLs.** They are component / style / workflow registries with different schemas.
- The Q024 #88 reference may have been to a different `profiles/*.yaml` location that was reorganized between the audit date and now, OR to the `profile-facts` Qdrant collection's own internal drift (vs. some other on-disk source like sync-agent metadata).

**No actionable drift found at the documented location.** This sub-item is closed as "audit performed, no drift found at the cited path." If a future session finds the actual drift source, file as a Phase 8 follow-up.

## Phase 1 item 10 closure

| Sub-item | Status |
|---|---|
| Add `hapax-apperceptions` + `operator-patterns` | ✅ Already done (prior PR) |
| Update workspace CLAUDE.md 9 → 10 | ⏳ Cross-repo, dotfiles follow-up |
| `operator-patterns` empty state | ✅ Audited (Option C recommended) |
| `axiom-precedents` sparse state | ✅ Documented as known observation |
| `profiles/*.yaml` vs Qdrant drift | ✅ Audited, no drift at cited path |

**Item 10 closes Phase 1 at 10 of 10 items done** (item 3 from Phase 0 still operator-gated; that's a Phase 0 follow-up tracked in lrr-state.yaml::known_blockers, not a Phase 1 blocker).

## Cross-repo follow-ups filed

1. **dotfiles workspace-CLAUDE.md** — add `stream-reactions` to the Qdrant collections list (9 → 10).
2. **Operator decision** — retire vs reschedule `operator-patterns` writer. Recommended decision point: after Phase 6 closes (governance) so the consent-gate implications are clearer.
3. **Phase 8 follow-up** — investigate `axiom-precedents` writer cadence after Phase 6 governance work.
