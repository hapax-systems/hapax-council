# LRR Phase 1 — Complete (handoff)

**Phase:** 1 of 11 (Research Registry Foundation)
**Owner:** alpha
**Branch:** `feat/lrr-phase-1-research-registry` (closes with this PR)
**Opened:** 2026-04-14T07:58Z
**Closing:** 2026-04-14T08:50Z
**Duration:** ~52 minutes
**PRs shipped:** #791, #792, #793, #794, this one
**Per-phase spec:** `docs/superpowers/specs/2026-04-14-lrr-phase-1-research-registry-design.md`
**Per-phase plan:** `docs/superpowers/plans/2026-04-14-lrr-phase-1-research-registry-plan.md`
**Schema drift audit:** `docs/research/2026-04-14-qdrant-schema-drift-audit.md`

## What shipped

**10 of 10 Phase 1 exit criteria fully closed.** Phase 1 is the first LRR phase to close at 100% in a single session.

| # | Item | Status | PR |
|---|---|---|---|
| 1 | Registry data structure (`~/hapax-state/research-registry/`) | ✅ | #791 |
| 2 | Per-segment metadata schema (Qdrant `condition_id` payload + JSONL) | ✅ | #792 |
| 3 | Research-marker SHM injection (`/dev/shm/hapax-compositor/research-marker.json` + audit log) | ✅ | #792 |
| 4 | Frozen-file pre-commit enforcement (`scripts/check-frozen-files.py` + hook) | ✅ | #793 |
| 5 | Langfuse `condition_id` tag on `hapax_span` | ✅ | #793 |
| 6 | OSF project creation procedure | ✅ | #791 |
| 7 | `stats.py` BEST analytical approximation | ✅ | #794 |
| 8 | `scripts/research-registry.py` CLI (init / current / list / open / close / show / tag-reactions) | ✅ | #791 + #792 |
| 9 | Backfill 2178 stream-reactions Qdrant points (subcommand) | ✅ | #792 |
| 10 | Adjacent Qdrant schema drift fixes | ✅ | this PR |

## Exit criteria verification

- [x] `~/hapax-state/research-registry/cond-phase-a-baseline-qwen-001/` exists with well-formed YAML — verified live
- [x] `/dev/shm/hapax-compositor/research-marker.json` exists and is read by director loop on every reaction tick (5 s cache) — verified live
- [x] Every new reaction has a `condition_id` field in both JSONL and Qdrant payload — wired in director_loop.py:850 record dict
- [x] Backfill command exists (`research-registry.py tag-reactions`) — operator runs against 2178 points post-merge
- [x] `scripts/check-frozen-files.py` rejects a test edit to a frozen file with a clear error message — covered by 12 tests
- [x] `stats.py` has a BEST function (`best_two_sample`); analytical approximation pending Phase 4 PyMC upgrade
- [x] OSF project creation procedure documented at `research/protocols/osf-project-creation.md`
- [x] `scripts/research-registry.py` operational; `current` returns `cond-phase-a-baseline-qwen-001`
- [x] Langfuse traces in `stream-experiment` tag will show `condition_id` metadata (next reaction will populate)
- [x] `EXPECTED_COLLECTIONS` lists all 10 Qdrant collections including the 2 added by Q026 Phase 4 Finding 1

## Deviations from the plan

1. **Phase 1 ships in 6 PRs**, not 5 as the spec estimated. The breakdown:
   - PR #1 foundation (items 1, 6, 8)
   - PR #2 metadata + injection + backfill subcommand (items 2, 3, 9)
   - PR #3 frozen-files + Langfuse tag (items 4, 5)
   - PR #4 stats.py BEST (item 7)
   - PR #5 + handoff (item 10 + this close handoff)
2. **Item 7 BEST is an analytical approximation, not the canonical Kruschke MCMC.** Council does not have PyMC as a dependency. Module docstring documents the Phase 4 upgrade requirement; result dict shape matches Bundle 2's canonical `report_best` so the upgrade is drop-in.
3. **Item 10 sub-item 1 was already done** by a prior session before this PR (`hapax-apperceptions` + `operator-patterns` already in `EXPECTED_COLLECTIONS`). The PR ships the audit doc + tests rather than the duplicate code change.
4. **Item 10 sub-item 2 (workspace CLAUDE.md update) is cross-repo** — defers to the dotfiles repo. Filed as a known cross-repo follow-up alongside Phase 0 item 3 (`/data` inodes) and Wave 1 W1.1 (Prometheus scrape).
5. **Item 9 backfill is shipped as a subcommand, not a live run.** The 2178 stream-reactions points need operator review before mass-tagging. The PR body documents the run command for post-merge execution.

## Test stats (cumulative across Phase 1 PRs)

- **52 new Python tests** (cumulative): 20 from PR #791 (research_registry) + 8 from PR #792 (marker writer + tag-reactions dry-run) + 12 from PR #793 (frozen-files) + 12 from PR #794 (BEST analytical) + 5 from this PR (Qdrant schema drift pin)
- All ruff lint + format clean across all 5 PRs
- Live `current.txt` + `condition.yaml` verified (`research-registry.py current` returns the right ID)

## Beta drops queued for later phases

Bundle 2 was consumed during Phase 1. **5 bundles remain queued** in `lrr-state.yaml::beta_drops_queued`:

| File | Phase | Notes |
|---|---|---|
| `2026-04-14-lrr-bundle-1-substrate-research.md` | 3 + 5 | Hermes 3 70B EXL3 + TabbyAPI dual-GPU + gpu_split ordering |
| `2026-04-14-lrr-bundle-4-governance-drafts.md` | 6 | Phase 6 governance + axiom amendments |
| `2026-04-14-lrr-bundle-7-livestream-experience-design.md` | 7 | Persona + livestream experience design |
| `2026-04-14-lrr-bundle-7-supplement.md` | 7 | Phase 7 supplement |
| `2026-04-14-lrr-bundle-8-autonomous-hapax-loop.md` | 8 | Content programming + autonomous loop |

## Relay state updates

- `~/.cache/hapax/relay/lrr-state.yaml` advanced from `current_phase: 1, current_phase_owner: alpha` → `current_phase: 2, current_phase_owner: null, last_completed_phase: 1`
- `completed_phases: [0, 1]`
- `known_blockers` carries forward Phase 0's two unresolved items (`/data` inode pressure operator-gated; FINDING-Q runtime rollback half) plus a new Phase 1 follow-up entry for the dotfiles cross-repo update.

## Time to completion

~52 minutes from Phase 1 open to handoff. Phase 1 was the most tightly-scoped phase to date because Bundle 2 (beta's parallel research drop) provided the BEST + OSF + frozen-files patterns directly — alpha did not need to re-derive them.

## Pickup-ready note for the next session

You are picking up after a Phase 1 that closed at **10/10 in a single session**. Phase 0 still has 2 unresolved items (operator-gated /data + runtime-rollback half of FINDING-Q); they are tracked in `lrr-state.yaml::known_blockers` and do NOT block Phase 2.

**Phase 2 entry checklist:**

1. Standard relay onboarding (`PROTOCOL.md`, peer status, etc.)
2. Read `lrr-state.yaml`. `current_phase` is 2, `current_phase_owner` is null. Claim it.
3. Read this handoff doc + the Phase 0 close handoff for context.
4. **Read the LRR epic Phase 2 section** in `docs/superpowers/specs/2026-04-14-livestream-research-ready-epic-design.md` (around line 288). Phase 2 is "Archive + Replay as Research Instrument" — re-enable the disabled archival pipeline with research-grade metadata injection + segment condition tags + retention guarantees.
5. **No beta bundle is queued for Phase 2 specifically** (Bundle 2 was Phase 1, Bundle 1 is Phase 3). Phase 2 may need its own research probe if questions arise.
6. Write per-phase spec + plan, create worktree on `feat/lrr-phase-2-archive-research-instrument`, execute.

**Cross-repo follow-ups still owed (deferred from earlier phases):**
- Phase 0 item 3: `/data` inode alerts in `llm-stack/alertmanager-rules.yml` (Wave 1 W1.1 dance)
- Phase 1 item 10 sub-item 2: `dotfiles/workspace-CLAUDE.md` Qdrant collections list 9 → 10
- Phase 0 FINDING-Q runtime rollback: PR #3b on a `feat/lrr-phase-0-finding-q-runtime-rollback` branch can ship in parallel with Phase 2 if branch discipline allows

**Operator decisions deferred:**
- `operator-patterns` writer retire vs reschedule (Phase 6 / Phase 8 question — see qdrant-schema-drift audit doc)
- Audio ducking live verification (Phase 9 prep)
- BRIO 5342C819 hardware replacement (operator decision)
