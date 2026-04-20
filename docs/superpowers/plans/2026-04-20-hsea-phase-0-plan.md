# HSEA Phase 0 — Foundation Primitives — Implementation Plan

**Status:** ready-to-execute
**Date:** 2026-04-20
**Author:** alpha (refining HSEA epic spec §5 Phase 0)
**Owner:** alpha (zone)
**Spec:** `docs/superpowers/specs/2026-04-14-hsea-epic-design.md` §5 Phase 0
**Epic plan:** `docs/superpowers/plans/2026-04-14-hsea-epic-plan.md` §4 Phase 0
**Branch:** `feat/hsea-phase-0-foundation-primitives` (per epic plan §4 line 133) — NOT trio-direct; HSEA epic ships behind a feature branch per the operator-approval-gate principle.
**Total effort:** 3-4 sessions (~2,820 LOC)

## 0. Why this plan exists

Per delta sister-epic prioritization memo
(`~/.cache/hapax/relay/delta-to-alpha-sister-epic-priority-20260420.md`),
HSEA Phase 0 is the load-bearing foundation for both the HOMAGE-Scrim
umbrella (delta queue, blocked-after-HSEA per gap audit D-29) and the
governance ledger that downstream Phase 1+ touch points read.

The drop #58 audit found HSEA referenced infrastructure that didn't
exist (~55% file-reference error rate). Phase 0 explicitly builds that
infrastructure as its first deliverable, so subsequent phases have
ground to stand on.

Operator-approval-gate principle (epic spec P-12): rendering Hapax's
drafting on the livestream is preparation, NOT delivery. Delivery is a
distinct operator action via the promote-* scripts (deliverable 0.4).
This is codified as axiom precedent `sp-hsea-mg-001` (deliverable 0.5).

## 1. Pre-flight

- [ ] Operator sign-off on HSEA epic per spec status
      ("DRAFT — awaiting operator sign-off before Phase 0 open").
      **If not yet signed off, this plan is dispatch-ready but
      execution waits.** Sister-epic delta memo treats sign-off as
      effective (operator chose HSEA over alternatives).
- [ ] Verify ~/hapax-state/ is writable (Phase 0 deliverables write to
      this dir for governance-queue + spawn-budget JSONLs)
- [ ] Verify Prometheus exporter is reachable on `:9482`/`:9483`
      (deliverable 0.1 will query both)
- [ ] Verify `axioms/precedents/` exists in council repo (Phase 0
      deliverable 0.5 lands there)
- [ ] Verify `~/.cache/hapax/relay/` is the canonical relay store
      (deliverable 0.6 writes hsea-state.yaml here)
- [ ] Confirm CC-task SSOT scaffold is live (D-30 Phase 1 — yes,
      shipped 2026-04-20). Phase 0 deliverables should be filed as
      cc-task notes from day one.

## 2. Critical-path ordering

Per epic plan §4 line 136:

```
0.6 (state file, foundational)
  ↓
0.1 + 0.3 (parallel — independent)
  ↓
0.2 (depends on 0.1 for the Cairo overlay's Prometheus consumer)
  ↓
0.4 (depends on 0.2 for governance-queue write API)
  ↓
0.5 (last, depends on 0.4 for the promote-axiom-precedent script)
```

Single session, sequential within deliverables. Tests-first per
deliverable; one commit per deliverable.

## 3. Deliverable 0.6 — Epic state file (~110 LOC, 0.1 day)

### 3.1 Tasks

**T0.6.1** Create `~/.cache/hapax/relay/hsea-state.yaml` with the
schema mirroring LRR state file:

```yaml
current_phase: 0
last_completed_phase: -1
known_blockers: []
phase_statuses:
  - name: "Phase 0 — Foundation Primitives"
    status: open  # open | closed | blocked
    opened_at: 2026-04-NNTHH:MM:SSZ
    closed_at: null
    spec_path: docs/superpowers/specs/2026-04-14-hsea-epic-design.md
    plan_path: docs/superpowers/plans/2026-04-20-hsea-phase-0-plan.md
    handoff_path: null
    pr_url: null
    branch_name: feat/hsea-phase-0-foundation-primitives
    deliverables:
      - {id: "0.1", name: "Prometheus query client", status: pending}
      - {id: "0.2", name: "Governance queue", status: pending}
      - {id: "0.3", name: "Spawn budget ledger", status: pending}
      - {id: "0.4", name: "Prepare/deliver inbox", status: pending}
      - {id: "0.5", name: "Axiom precedent", status: pending}
      - {id: "0.6", name: "Epic state file", status: complete}
```

**T0.6.2** Extend `hooks/scripts/session-context.sh` to surface
`HSEA: Phase N · owner=<session> · health=<color>` alongside the
existing LRR + CC-task blocks. Health color: green (no blockers, all
deliverables on-track), yellow (1+ blockers, no overdue), red
(overdue OR multiple blockers).

### 3.2 Exit criterion

- `cat ~/.cache/hapax/relay/hsea-state.yaml | yq` returns valid YAML
  with `current_phase: 0`
- SessionStart preamble shows the new HSEA line on next session restart

### 3.3 Commit

```
feat(hsea): Phase 0 deliverable 0.6 — epic state file + session-context surface
```

## 4. Deliverable 0.1 — Prometheus query client (~430 LOC, 1 day)

### 4.1 Tasks

**T0.1.1** New `shared/prom_query.py`:
- `PromQueryClient` class with `instant(query)`, `range(query, start, end, step)`, `scalar(query)` methods
- HTTP client using `httpx` (already a council dep) targeting
  `http://localhost:9090` (Prometheus) by default; configurable via
  env var `HAPAX_PROMETHEUS_URL`
- Error handling: degraded-state flag returned on HTTP 5xx / timeout;
  never raises (Cairo render callbacks must not throw)

**T0.1.2** `WatchedQuery` declarative abstraction:
- Tiers: 0.5 Hz / 1 Hz / 2 Hz / 5 Hz refresh
- One worker thread per tier in a shared `WatchedQueryPool` (max 4 concurrent loops)
- Each query carries: PromQL string, refresh tier, callback for new value
- Pool exposes `register(query, tier, callback)` + `start()` + `stop()`

**T0.1.3** Tests at `tests/shared/test_prom_query.py`:
- `respx` mocks for Prometheus HTTP; happy + 5xx + timeout paths
- `WatchedQueryPool` start/stop lifecycle + thread cleanup
- Callback invocation with mocked time-progression
- Degraded-state flag visibility

### 4.2 Exit criterion

- `uv run pytest tests/shared/test_prom_query.py -q` green
- `uv run python -c "from shared.prom_query import PromQueryClient;
  c = PromQueryClient(); print(c.scalar('up{job=\"compositor\"}'))"`
  returns a real metric value

### 4.3 Commit

```
feat(shared): HSEA Phase 0 deliverable 0.1 — Prometheus query client + WatchedQueryPool
```

## 5. Deliverable 0.3 — Spawn budget ledger (~580 LOC, 0.5 day)

Parallel-safe with 0.1 — independent file paths + no shared imports
yet. Run as a sibling commit in a single session if time allows.

### 5.1 Tasks

**T0.3.1** New `shared/spawn_budget.py`:
- JSONL ledger at `~/hapax-state/spawn-budget.jsonl`
- Schema: `{timestamp, touch_point, spawn_id, model_tier, model_id,
  tokens_in, tokens_out, cost_usd, latency_ms, langfuse_trace_id, status}`
- `BudgetLedger.append(entry)` — atomic JSONL append per D-20 pattern
- `check_can_spawn(touch_point) → BudgetDecision(allowed, reason,
  projected_cost, current_daily_usd, daily_cap_usd)`
- Default daily cap: $5 (per spec line 196 P-8 + line 106 P-3)

**T0.3.2** Caps file at `~/hapax-state/spawn-budget-caps.yaml`:
- Default global daily $5, per-touch-point caps blank, concurrency limits 1
- Operator-editable; loaded with `_LAST_LOAD_AT` cache invalidated on
  file mtime change (1s tolerance)

**T0.3.3** Cost source: read from LiteLLM response headers when
present; fallback to Langfuse `total_cost` lookup; never estimate
from token counts (per spec line 199).

**T0.3.4** Budget-exhaustion behavior:
- Publish `budget_exhausted` impingement at salience 0.55 to the
  daimonion bus (`/dev/shm/hapax-dmn/impingements.jsonl`)
- Hysteresis: re-enable at 90% of cap (mostly triggers at UTC midnight)

**T0.3.5** Cairo overlay at
`agents/studio_compositor/spawn_budget_overlay.py`:
- "today's spawn budget: 47% used, 12 spawns, top 3 categories"
- Renders top-right corner, low opacity baseline
- Consumes WatchedQuery from deliverable 0.1 for the live
  `current_daily_usd` metric

**T0.3.6** Tests at `tests/shared/test_spawn_budget.py` +
`tests/studio_compositor/test_spawn_budget_overlay.py`.

### 5.2 Exit criterion

- `uv run pytest tests/shared/test_spawn_budget.py
  tests/studio_compositor/test_spawn_budget_overlay.py -q` green
- Manual: append a fake spawn entry, verify `check_can_spawn` reflects
  the new daily total

### 5.3 Commit

```
feat(shared): HSEA Phase 0 deliverable 0.3 — spawn budget ledger + Cairo overlay
```

## 6. Deliverable 0.2 — Governance queue (~720 LOC, 1 day)

Depends on 0.1 (Cairo overlay consumes WatchedQueryPool).

### 6.1 Tasks

**T0.2.1** New `shared/governance_queue.py`:
- JSONL at `~/hapax-state/governance-queue.jsonl`
- Schema per spec line 185
- `add(entry)` with `fcntl.flock LOCK_EX` for append; `O_APPEND` +
  sub-PIPE_BUF line sizes for atomicity
- `pending()` returns drafted + reviewing entries; `archive()` moves
  closed entries to `~/hapax-state/governance-queue-archive.jsonl`
- Status lifecycle per spec line 187:
  `drafted → reviewing → approved → executed → archived`

**T0.2.2** Obsidian inbox sync — drafters write `id:` frontmatter into
`~/Documents/Personal/00-inbox/<slug>.md`; inotify watcher updates
queue status on operator access/edit.

**T0.2.3** Cairo overlay at
`agents/studio_compositor/governance_queue_overlay.py`:
- Persistent badge: pending count + oldest age + most recent title
- Top-left corner zone

**T0.2.4** Reap: weekly systemd timer
`hapax-governance-queue-reap.{service,timer}`.

**T0.2.5** Tests at `tests/shared/test_governance_queue.py` +
`tests/studio_compositor/test_governance_queue_overlay.py`.

### 6.2 Exit criterion

- All 11 type-enum entries handled in tests (per spec line 186)
- Cairo overlay renders pending count live (smoketest fixture in
  `tests/studio_compositor/`)
- Reap timer in `systemctl --user list-timers`

### 6.3 Commit

```
feat(shared): HSEA Phase 0 deliverable 0.2 — governance queue + Cairo overlay + reap timer
```

## 7. Deliverable 0.4 — Prepare/deliver inbox (~760 LOC, 0.5 day)

Depends on 0.2 (promote scripts read governance-queue).

### 7.1 Tasks

**T0.4.1** Directory layout: `~/Documents/Personal/00-inbox/`
(existing) + `/dev/shm/hapax-compositor/draft-buffer/<slug>/`
(volatile, created on first draft).

**T0.4.2** Frontmatter schema per spec line 209.

**T0.4.3** Scripts under `scripts/` (each a thin bash wrapper around
`_promote-common.sh`):
- `promote-drop.sh` → research drops to `docs/research/<date>-<slug>.md`
- `promote-patch.sh` → `git apply` (operator only)
- `promote-pr.sh` → `gh pr create --draft` (never --draft=false)
- `promote-axiom-precedent.sh` → `axioms/precedents/hsea/`
- `promote-exemplar.sh` → `shared/exemplars.yaml` (empty shell at
  this phase; LRR Phase 7 populates)
- `promote-antipattern.sh` → `shared/antipatterns.yaml` (empty shell)
- `promote-revenue.sh` → per-target deployment (stub)
- `dispatch-approved.sh` → clipboard-copy for external platforms

**T0.4.4** Safety gates in `_promote-common.sh`:
- frozen-files probe (LRR Phase 1 hook; gracefully skip if unavailable)
- `ruff check`
- `pytest -q tests/test_smoke.py` (smoke subset)
- consent scan (re-use `hooks/scripts/pii-guard.sh` logic)
- axiom scan (re-use `hooks/scripts/axiom-commit-scan.sh` logic)
- idempotency marker (refuse to promote a file that has already been
  promoted)

**T0.4.5** Operator override: `HAPAX_PROMOTE_SKIP_CHECKS=1`.

**T0.4.6** Tests at `tests/scripts/test_promote_scripts.py` (Python-
driven via subprocess) — happy + each failure mode per script.

### 7.2 Exit criterion

- All 8 promote scripts shellcheck-clean
- Each script has a Python-subprocess test that exercises happy +
  one failure path
- Idempotency: re-running `promote-drop.sh` on the same draft is a
  no-op (operator-readable message, no double-write)

### 7.3 Commit

```
feat(scripts): HSEA Phase 0 deliverable 0.4 — promote-* scripts + safety gates
```

## 8. Deliverable 0.5 — Axiom precedent (~220 LOC, 0.5 day)

Depends on 0.4 (uses promote-axiom-precedent.sh).

### 8.1 Tasks

**T0.5.1** `axioms/precedents/hsea/management-governance-drafting-as-content.yaml`:
- Precedent ID: `sp-hsea-mg-001`
- Decision: drafting constitutes preparation (not delivery) IFF
  operator retains discrete revocable non-visual delivery authority
- Edge cases (per spec line 228): livestream clip extraction, daimonion
  audible narration, drafts referencing individuals (falls back to
  existing mg-boundary), operator approving without reading,
  spawn-budget-exhaustion truncation

**T0.5.2** New implication entry `mg-drafting-visibility-001` in
`axioms/implications/management-governance.yaml`.

**T0.5.3** Extend `hooks/scripts/axiom-commit-scan.sh` with
auto-delivery pattern detection (e.g. detects `gh pr merge` in commit
diffs without operator-approved frontmatter).

**T0.5.4** Tests at `tests/axioms/test_hsea_precedent.py` +
`tests/hooks/test_axiom_commit_scan_hsea.py`.

**T0.5.5** Update `axioms/README.md` to reference the new precedent.

### 8.2 Exit criterion

- `uv run pytest tests/axioms/ tests/hooks/test_axiom_commit_scan_hsea.py -q` green
- Hook rejects a synthetic commit message that auto-delivers without
  operator-approved frontmatter

### 8.3 Commit

```
feat(axioms): HSEA Phase 0 deliverable 0.5 — sp-hsea-mg-001 drafting-as-content precedent
```

## 9. Phase 0 closure

Per epic spec §5 Phase 0 line 241 + epic plan §4 line 139:

- [ ] All 6 deliverables merged to main (one feature branch
      `feat/hsea-phase-0-foundation-primitives`, one squash-merge PR)
- [ ] Epic state file `~/.cache/hapax/relay/hsea-state.yaml` updated:
      `phase_statuses[0].status: closed`, `closed_at: <now>`,
      `handoff_path: docs/superpowers/handoff/<date>-hsea-phase-0-complete.md`
- [ ] Precedent referenced from `axioms/README.md`
- [ ] `session-context.sh` extension merged
- [ ] One end-to-end smoke test:
      stub drafter creates a governance queue entry → operator flips
      frontmatter to `approved` → `promote-drop.sh` executes cleanly →
      file lands in `docs/research/`
- [ ] Phase 0 handoff doc written
- [ ] WSJF doc D-30 row updated (if alpha repurposes the D-NN slot
      for HSEA tracking, OR file as separate D-32)

## 10. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Prometheus exporter unreachable during Phase 0 dev | M | 0.1+0.2+0.3 blocked | `respx` mocks let development continue; live integration test is last |
| Governance queue inotify watcher conflicts with existing reactor | L | Phase 0.2 fails | Use a distinct watch path; the existing reactor watches `inflections/` not `00-inbox/` |
| Spawn budget cap default $5/day surprises operator on first activation | M | Live operator interruption | Document in SessionStart preamble; first-week soft-cap mode (warn instead of block) |
| Promote scripts' frozen-files probe gates differently than LRR's hook | L | Confusing operator | Defer probe wrapper to AFTER LRR Phase 1 (per epic plan §4 line 138) |
| Axiom precedent edge case missed | M | Future legal/governance gap | Spec enumerates 5 edge cases; tests pin each one |

## 11. Sequencing relative to other in-flight work

- **Does NOT block** D-30 (CC-task SSOT — orthogonal, both can run)
- **Does NOT block** OQ-02 Phase 1 oracles (orthogonal, those shipped)
- **DOES block** D-29 (HOMAGE Ward umbrella plan — gap audit
  blocked-after-HSEA per memo)
- **DOES block** Phases 1+ of HSEA epic (spec hard-gate per spec
  line 116 P-2 "no Phase >0 opens until Phase 0 closes")
- **Mostly orthogonal to** D-28 (programme-layer plan audit — different
  primitive set, but Phase 0.2 governance queue IS conceptually
  adjacent to Programme; cross-link in 0.2 docs)

Recommend alpha ships Phase 0 across 3-4 sessions. Operator-approval
gate on the spec status before opening; assume effective sign-off per
delta sister-epic memo.

## 12. References

- Spec: `docs/superpowers/specs/2026-04-14-hsea-epic-design.md` §5 Phase 0
- Epic plan: `docs/superpowers/plans/2026-04-14-hsea-epic-plan.md` §4 Phase 0
- Sister-epic memo: `~/.cache/hapax/relay/delta-to-alpha-sister-epic-priority-20260420.md`
- Total-workstream gap audit (NEW-1 promise): `docs/research/2026-04-20-total-workstream-gap-audit.md`
- WSJF doc: `docs/superpowers/handoff/2026-04-20-delta-wsjf-reorganization.md`
- LRR state file (template): `~/.cache/hapax/relay/lrr-state.yaml`
