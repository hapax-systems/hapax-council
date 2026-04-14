# LRR Phase 1 — Research Registry Foundation (per-phase plan)

**Spec:** `docs/superpowers/specs/2026-04-14-lrr-phase-1-research-registry-design.md`
**Branch:** `feat/lrr-phase-1-research-registry`
**Estimated effort:** 5 PRs across 2-3 sessions

## Stage 1 — Phase 1 PR #1 foundation (this PR)

### Task 1.1 — Claim Phase 1 in lrr-state.yaml ✓

- [x] Set `current_phase_owner: alpha`, `current_phase_branch: feat/lrr-phase-1-research-registry`, `current_phase_opened_at: 2026-04-14T07:58:00Z`

### Task 1.2 — Per-phase spec + plan ✓

- [x] `docs/superpowers/specs/2026-04-14-lrr-phase-1-research-registry-design.md`
- [x] `docs/superpowers/plans/2026-04-14-lrr-phase-1-research-registry-plan.md` (this file)

### Task 1.3 — Item 1: registry data structure + first condition

- [ ] Create `~/hapax-state/research-registry/cond-phase-a-baseline-qwen-001/` dir
- [ ] Write `condition.yaml` per the schema in spec §3 item 1
- [ ] Compute SHA-256 of `agents/hapax_daimonion/grounding_directives.py` (or note `null` if file doesn't exist) and populate `directives_manifest`
- [ ] Create `~/hapax-state/research-registry/current.txt` containing the active condition_id
- [ ] Verify the file is parseable YAML and matches the schema

### Task 1.4 — Item 8: research-registry.py CLI

- [ ] Create `scripts/research-registry.py` (executable)
- [ ] Implement `init` subcommand (idempotent — refuses if registry exists)
- [ ] Implement `current` subcommand (prints active condition_id)
- [ ] Implement `list` subcommand (lists open + closed conditions)
- [ ] Implement `open <slug>` (creates a new condition.yaml, advances current.txt)
- [ ] Implement `close <condition_id>` (sets `closed_at`, no-op on already-closed)
- [ ] Implement `show <condition_id>` (prints the YAML contents)
- [ ] Use atomic write pattern (tmp+rename) for current.txt mutations
- [ ] Use file locking via `fcntl.flock` on the registry directory for concurrent CLI runs

### Task 1.5 — Item 6: OSF project creation procedure

- [ ] Create `research/protocols/osf-project-creation.md` based on Bundle 2 §2
- [ ] Adapt the template for the Shaikh claim
- [ ] Document the 6-step operator procedure
- [ ] Include the post-filing condition.yaml update commands

### Task 1.6 — Tests

- [ ] `tests/test_research_registry.py`
  - [ ] Schema regression pin (16 required fields)
  - [ ] CLI init + current + list + open + close + show round trip
  - [ ] File locking pattern (two concurrent CLI runs don't corrupt registry)
  - [ ] YAML round-trip preserves all fields
  - [ ] Open with existing slug re-uses; close + reopen creates a new condition
- [ ] `uv run pytest tests/test_research_registry.py -q` → all pass
- [ ] `uv run ruff check scripts/research-registry.py tests/test_research_registry.py` → clean

### Task 1.7 — Commit + push + PR

- [ ] Commit (one commit per task where reasonable)
- [ ] Push `feat/lrr-phase-1-research-registry`
- [ ] Open PR with title `feat(lrr): Phase 1 PR #1 — research registry foundation (data structure + CLI + OSF procedure)`
- [ ] PR body includes the exit-criteria checklist (3 of 10 closed)

## Stage 2 — Phase 1 PR #2 metadata + injection + backfill

### Task 2.1 — Item 2: per-segment metadata schema extension

- [ ] Add `condition_id` field to the `stream-reactions` Qdrant payload schema in `shared/qdrant_schema.py`
- [ ] Update the writer in `agents/studio_compositor/director_loop.py` (or wherever reactions get written) to populate `condition_id` from the SHM marker
- [ ] Add `condition_id` to the JSONL log writer for `reactor-log-YYYY-MM.jsonl`
- [ ] Tests for both writers

### Task 2.2 — Item 3: research-marker SHM injection

- [ ] Create `/dev/shm/hapax-compositor/research-marker.json` writer in the research-registry CLI (`open` and `close` subcommands write the marker)
- [ ] Director loop reads `research-marker.json` on every reaction tick (cache for 5 s, re-read on inotify or on cache expiry)
- [ ] Atomic write semantics — tmp+rename
- [ ] Audit log: `~/hapax-state/research-registry/research_marker_changes.jsonl` with frame-accurate timestamps for every condition change
- [ ] Tests for the marker reader + writer

### Task 2.3 — Item 9: backfill 2178 existing reactions

- [ ] Add `tag-reactions <start-ts> <end-ts> <condition_id>` to `scripts/research-registry.py`
- [ ] Implementation reads Qdrant `stream-reactions` collection in batches (~100 points), updates the payload's `condition_id` field, writes back
- [ ] Run the backfill: tag all pre-2026-04-14 reactions with `cond-phase-a-baseline-qwen-001`
- [ ] Verify: `count(stream-reactions where condition_id = 'cond-phase-a-baseline-qwen-001')` ≈ 2178
- [ ] Backfill the JSONL logs for the current month with the same tag

## Stage 3 — Phase 1 PR #3 frozen-files + Langfuse tag

### Task 3.1 — Item 4: frozen-file pre-commit enforcement

- [ ] Implement `scripts/check-frozen-files.sh` per Bundle 2 §3 Approach A (Python entry point preferred over shell)
- [ ] Read current condition's `frozen_files` from the registry
- [ ] Compare against staged files (`git diff --cached --name-only`)
- [ ] Reject commit on overlap unless an explicit `DEVIATION-NNN` is filed
- [ ] Install hook via `.pre-commit-config.yaml` (or `.git/hooks/pre-commit`)
- [ ] Tests: synthetic edit to a frozen file → reject; synthetic edit to a non-frozen file → pass; deviation override → pass

### Task 3.2 — Item 5: Langfuse condition_id tag

- [ ] Update `hapax_span` and `hapax_score` calls in `director_loop.py` to attach `condition_id` from the SHM marker
- [ ] ~3-line change
- [ ] Verify: a fresh director_loop tick produces a Langfuse trace with `condition_id` in the metadata

## Stage 4 — Phase 1 PR #4 stats.py BEST verification

### Task 4.1 — Item 7: stats.py BEST audit + migration

- [ ] Locate council's current `stats.py`
- [ ] Read it; check whether it implements BEST / beta-binomial / two-sample t-test
- [ ] If BEST: verify priors + likelihood match the canonical PyMC pattern from Bundle 2 §1, document in registry as a known-good
- [ ] If beta-binomial or t-test: migrate to BEST per the Bundle 2 §1 template
- [ ] Smoke test in `tests/test_stats_best.py`: synthetic group_a, group_b → BEST returns valid posterior, HDI brackets the true difference, no NaN

## Stage 5 — Phase 1 PR #5 Qdrant schema drift fixes

### Task 5.1 — Item 10: adjacent Qdrant fixes

- [ ] Add `hapax-apperceptions` + `operator-patterns` to `EXPECTED_COLLECTIONS` in `shared/qdrant_schema.py`
- [ ] Investigate `operator-patterns` empty state — re-schedule writer or explicitly retire
- [ ] Update `CLAUDE.md` Qdrant collections list 9 → 10
- [ ] Document `axiom-precedents` sparse state (17 points) in the condition registry as a known data-quality observation
- [ ] Reconcile `profiles/*.yaml` vs Qdrant `profile-facts` drift — decide authoritative source, document in registry

## Stage 6 — Phase 1 close

- [ ] All 10 exit criteria in spec §5 satisfied
- [ ] Write `docs/superpowers/handoff/2026-04-14-lrr-phase-1-complete.md` per LRR plan §7 template
- [ ] Update `~/.cache/hapax/relay/lrr-state.yaml`: `current_phase: 2`, `last_completed_phase: 1`, append `1` to `completed_phases`
- [ ] Open Phase 2 (or hand off to next session)

---

## Notes

- **Bundle 2 is the load-bearing reference.** Re-read Bundle 2 sections at PR boundaries to make sure each PR absorbs the relevant pattern.
- **Operator-in-the-loop check-ins:** none mandatory in Phase 1. Item 6 (OSF procedure) is a doc only — actual filing happens in Phase 4.
- **Frozen-file enforcement is the critical research-validity piece.** Phase 1 PR #3 must ship before Phase 4 baseline collection or operator/alpha may accidentally edit a frozen file mid-experiment.
- **Verification-before-claiming-done:** every checkbox above has a paired verification command in the spec § exit criteria. Don't tick the box until the verification passes.
