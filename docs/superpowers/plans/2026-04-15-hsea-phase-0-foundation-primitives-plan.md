# HSEA Phase 0 — Foundation Primitives — Plan

**Date:** 2026-04-15
**Author:** delta (pre-staging extraction from HSEA epic plan per the LRR-epic extraction pattern)
**Status:** DRAFT pre-staging — awaiting operator sign-off + cross-epic dependency resolution before Phase 0 open
**Spec reference:** `docs/superpowers/specs/2026-04-15-hsea-phase-0-foundation-primitives-design.md`
**Epic reference:** `docs/superpowers/plans/2026-04-14-hsea-epic-plan.md`
**Branch target:** `feat/hsea-phase-0-foundation-primitives`
**Cross-epic authority:** `docs/research/2026-04-14-cross-epic-fold-in-lrr-hsea.md` (drop #62 ownership table §3 and shared-state design §6 take precedence over any conflicting claim in this plan)

---

## 0. Preconditions (MUST verify before task 1.1)

- [ ] **LRR UP-0 closed.** Check `~/.cache/hapax/relay/lrr-state.yaml::phase_statuses[0].status == closed` OR equivalent entry in `research-stream-state.yaml::unified_sequence[UP-0].status == closed`. If not closed, DO NOT open Phase 0.
- [ ] **LRR UP-1 closed.** Check `~/.cache/hapax/relay/lrr-state.yaml::phase_statuses[1].status == closed` OR `unified_sequence[UP-1].status == closed`. Phase 0 deliverables 0.4 and 0.5 consume LRR Phase 1 artifacts (frozen-files probe, research registry).
- [ ] **FDL-1 deployed to running compositor.** Verify:
  - `systemctl --user is-active studio-compositor` returns `active`
  - `curl -s 127.0.0.1:9482/metrics | grep compositor_uptime_seconds` returns a numeric value
  - `git log --oneline ec3d85883..HEAD | head` confirms FDL-1 commit is on the running service's deployed main
- [x] **Drop #62 §10 Q1 (substrate swap) ratified** 2026-04-15T05:10Z via operator "ratified". No Phase 0 impact; noted for completeness.
- [x] **Drop #62 §10 Q2–Q10 ratified** 2026-04-15T05:35Z via operator "I accept all your recommendations" in response to alpha's decision pack. Phase 0-relevant resolutions:
  - **Q3** (HSEA Phase 4 full rescoping to narration-only I1–I5): confirmed; `promote-patch.sh` in deliverable 0.4 expects zero I1–I5 invocations during Phase 4, only I6/I7.
  - **Q4** (state file design: sibling under shared index): confirmed; deliverable 0.6 creates `hsea-state.yaml` only.
  - **Q5** (constitutional PR strategy: one joint PR): confirmed; deliverable 0.5 produces the `.draft` artifact only.
  - **Q8** (shared index ownership: alpha-initial + operator-only-thereafter): confirmed; deliverable 0.6 VERIFIES `research-stream-state.yaml` exists (created by alpha at UP-0 fold-in) and APPENDS the HSEA Phase 0 entry to `unified_sequence[UP-2]`. Does NOT create the shared index.
- [ ] **`~/.cache/hapax/relay/research-stream-state.yaml` exists.** Created by alpha at UP-0 fold-in commit time per Q8 ratification. If this file is absent when Phase 0 opens, BLOCK on UP-0 fold-in commit landing; do NOT create the shared index preemptively.
- [ ] **Session claims the phase.** Write `~/.cache/hapax/relay/hsea-state.yaml::phase_statuses[0].status: open` + `current_phase_owner: <session>` + `current_phase_branch: feat/hsea-phase-0-foundation-primitives` + `current_phase_opened_at: <now>`. This write IS part of deliverable 0.6 but is also the phase-open signal.

---

## 1. Deliverable 0.6 — Epic state file (+ shared index + session-context extension)

Executed FIRST so session-context surfaces Phase 0 as `open` immediately and every subsequent deliverable can write to a live state file.

### 1.1 Create hsea-state.yaml

- [ ] Write `~/.cache/hapax/relay/hsea-state.yaml` with initial schema
  - [ ] Top-level fields: `epic_id: hsea`, `epic_design_doc`, `epic_plan_doc`, `thesis_doc`, `audit_doc`, `current_phase: 0`, `current_phase_owner: <session>`, `current_phase_branch: feat/hsea-phase-0-foundation-primitives`, `current_phase_opened_at: <ISO8601>`, `last_completed_phase: null`, `overall_health: green`, `health_reason: "phase 0 open"`, `phase_statuses: []`, `known_blockers: []`, `related_epics: [lrr]`, `notes: ""`
  - [ ] `phase_statuses` array with entries for phases 0–12, each with `phase: N`, `name: <slug>`, `status: pending` (except 0 which is `open`), `opened_at: null`, `closed_at: null`, `spec_path`, `plan_path`, `handoff_path: null`, `pr_url: null`, `branch_name: null`, `deliverables: []`, `dependencies: []`, `unblocks: []`, `tests_required: []`
  - [ ] Phase 0 entry: `status: open`, `opened_at: <now>`, `spec_path: docs/superpowers/specs/2026-04-15-hsea-phase-0-foundation-primitives-design.md`, `plan_path: docs/superpowers/plans/2026-04-15-hsea-phase-0-foundation-primitives-plan.md`, `deliverables: [{id: "0.1", status: "pending"}, …, {id: "0.6", status: "in_progress"}]`
- [ ] Verify: `python -c "import yaml; yaml.safe_load(open('$HOME/.cache/hapax/relay/hsea-state.yaml'))"` prints nothing on success

### 1.2 Verify research-stream-state.yaml shared index + append HSEA Phase 0 entry

Per §10 Q8 ratification (2026-04-15T05:35Z, option a), alpha creates this file at UP-0 fold-in commit time. HSEA Phase 0 VERIFIES existence and APPENDS its entry; it does NOT create from scratch.

- [ ] Verify `~/.cache/hapax/relay/research-stream-state.yaml` exists. If absent:
  - [ ] BLOCK Phase 0 open; do NOT create the shared index preemptively
  - [ ] Write an inflection to alpha requesting that the UP-0 fold-in commit land, and stop Phase 0 work until it does
  - [ ] Do not proceed to 1.3 until the file exists
- [ ] Verify the existing file is parseable YAML and has `epics: [{id: lrr, ...}]` entry; if malformed, block and escalate
- [ ] Append HSEA entry to `epics[]` if not present: `{id: hsea, state_file: hsea-state.yaml, current_phase: 0, status: active}`
- [ ] Locate `unified_sequence[UP-2]` (HSEA Phase 0 slot). If the slot exists with `status: pending`, update to `status: open`, `owner: <session>`. If the slot does not exist, append it at the UP-2 position per drop #62 §5
- [ ] Update `last_updated_at: <now>`, `last_updated_by: <session>`
- [ ] Verify: parseable YAML after the edit
- [ ] NOTE: subsequent edits to the shared index (other than appending new UP entries at phase-open/close) are operator-only per Q8 ratification. Sessions that want to modify cross-epic dependency wiring file a governance-queue request.

### 1.3 Extend session-context.sh

- [ ] Read existing `hooks/scripts/session-context.sh` to locate the LRR state-file surfacing block
- [ ] Add parallel HSEA block that reads `~/.cache/hapax/relay/hsea-state.yaml` (if present) and surfaces `HSEA: Phase N · owner=<session> · health=<color>`
- [ ] Add shared-index block that reads `~/.cache/hapax/relay/research-stream-state.yaml` (if present) and surfaces `Stream: UP-N open (<epic>/<phase>)`
- [ ] Graceful degradation when files absent: no output, no error, exit 0

### 1.4 Tests for 0.6

- [ ] Create `tests/hooks/test_session_context_hsea.sh` (~40 LOC bash test)
  - [ ] Fixture: fake `hsea-state.yaml` with Phase 3 open
  - [ ] Fixture: fake `research-stream-state.yaml` with UP-5 open
  - [ ] Invoke `session-context.sh` with fixture dir overridden via env var; assert output contains expected lines
  - [ ] Negative: absent files → no error, no output lines about HSEA
- [ ] Run tests: `bash tests/hooks/test_session_context_hsea.sh` passes
- [ ] Manually verify: open a fresh shell after sourcing; confirm `HSEA: Phase 0 · owner=<session> · health=green` appears

### 1.5 Commit 0.6

- [ ] `git add tests/hooks/test_session_context_hsea.sh hooks/scripts/session-context.sh`
- [ ] `git commit -m "feat(hsea-phase-0): 0.6 epic state file + shared index + session-context extension"`
- [ ] NOTE: the state files themselves live under `~/.cache/hapax/relay/` and are NOT committed. They are session-local infrastructure. Only the test + hook changes are committed.

---

## 2. Deliverable 0.1 — Prometheus query client

No dependencies on other Phase 0 deliverables. Tests require a running compositor per precondition.

### 2.1 Test scaffolding (TDD: tests first)

- [ ] `uv add respx --dev` (if not already installed)
- [ ] Create `tests/shared/test_prom_query.py` with failing tests:
  - [ ] `test_instant_happy_path` — `respx` mock returns `{"status":"success","data":{"resultType":"vector","result":[{"value":[1234567890,"42.0"]}]}}`, assert `InstantResult(value=42.0, ok=True)`
  - [ ] `test_instant_connection_refused` — mock raises `httpx.ConnectError`, assert `InstantResult(value=None, ok=False, error=<connection refused>)`
  - [ ] `test_instant_http_500` — mock returns 500, assert degraded state
  - [ ] `test_instant_json_malformed` — mock returns non-JSON body, assert graceful `InstantResult(ok=False)`
  - [ ] `test_instant_empty_result_set` — mock returns `{"status":"success","data":{"result":[]}}`, assert `InstantResult(value=None, ok=True)` (empty is not an error)
  - [ ] `test_range_happy_path` — mock returns 3-point series, assert ordered timestamps
  - [ ] `test_scalar_wraps_instant` — invoke `scalar(q)`, assert it returns `float | None`
  - [ ] `test_is_degraded_flip_and_recover` — trigger failure → `is_degraded()` True; trigger success → `is_degraded()` False
  - [ ] `test_watched_query_pool_worker_lifecycle` — register 3 `WatchedQuery`s at different tiers, assert each tier has a single worker thread, assert `stop()` joins all
  - [ ] `test_watched_query_pool_singleton` — `get_pool()` returns same instance twice
  - [ ] `test_cairo_callback_exception_isolation` — register a `WatchedQuery` whose `on_value` raises; assert pool worker keeps running; assert the next tick's on_value still fires
- [ ] Run tests: all fail with `ModuleNotFoundError: shared.prom_query` (expected)

### 2.2 Implementation

- [ ] Create `shared/prom_query.py` with:
  - [ ] `PromEndpoint = Literal["compositor", "central"]` + URL mapping dict
  - [ ] `@dataclass(frozen=True) class InstantResult`
  - [ ] `@dataclass(frozen=True) class RangeResult`
  - [ ] `RefreshTier = Literal[0.5, 1.0, 2.0, 5.0]`
  - [ ] `@dataclass class WatchedQuery` with `query`, `refresh_hz`, `on_value`, `endpoint`
  - [ ] `class PromQueryClient` with `__init__(endpoint, timeout_s=1.5, stale_grace_s=10.0)`, `instant(query) → InstantResult`, `range(query, start, end, step_s) → RangeResult`, `scalar(query) → float | None`, `is_degraded() → bool`
  - [ ] Internal `_http = httpx.Client(timeout=timeout_s)` member
  - [ ] `_degraded: bool` + `_last_failure_at: float | None` for hysteresis
  - [ ] Every request path catches `httpx.ConnectError | httpx.TimeoutException | httpx.HTTPStatusError | json.JSONDecodeError` and converts to `InstantResult(ok=False, error=<str>)`; never re-raises
  - [ ] `class WatchedQueryPool` with `_workers: dict[RefreshTier, threading.Thread]`, `_tier_queries: dict[RefreshTier, list[WatchedQuery]]`, `_stop: threading.Event`
  - [ ] `register(wq)` appends to tier bucket; starts worker for that tier if not running
  - [ ] Worker loop: `while not stop: sleep(1/tier); for wq in tier_queries[tier]: result = client.instant(wq.query); try: wq.on_value(result); except: log_warn(no re-raise)`
  - [ ] `stop()` sets event, joins workers
  - [ ] Module-level `_pool: WatchedQueryPool | None = None` + `get_pool() -> WatchedQueryPool` lazy singleton
- [ ] Run tests: all pass

### 2.3 Commit 0.1

- [ ] `uv run ruff check shared/prom_query.py tests/shared/test_prom_query.py`
- [ ] `uv run ruff format shared/prom_query.py tests/shared/test_prom_query.py`
- [ ] `uv run pyright shared/prom_query.py`
- [ ] `git add shared/prom_query.py tests/shared/test_prom_query.py pyproject.toml uv.lock`
- [ ] `git commit -m "feat(hsea-phase-0): 0.1 shared/prom_query.py + WatchedQueryPool"`
- [ ] Update `hsea-state.yaml::phase_statuses[0].deliverables[0.1].status: completed`

---

## 3. Deliverable 0.3 — Spawn budget ledger

Independent from 0.1 and 0.2; executed next so the budget primitive is in place before 0.4 promote scripts need to record spawn costs.

### 3.1 Test scaffolding

- [ ] Create `tests/shared/test_spawn_budget.py` with failing tests:
  - [ ] `test_ledger_append_reads_back` — append one record; `aggregate_today()` returns it
  - [ ] `test_ledger_cost_source_is_litellm_header` — pass response with `x-litellm-response-cost: "0.0123"`; assert recorded cost matches; never estimated from tokens
  - [ ] `test_check_can_spawn_under_cap` — caps YAML daily=$5.00, current=$1.00, projected=$0.10; `BudgetDecision(allowed=True)`
  - [ ] `test_check_can_spawn_over_cap` — current=$4.99, projected=$0.50; `BudgetDecision(allowed=False, reason="daily cap exceeded")`
  - [ ] `test_hysteresis_reenable_at_90pct` — cap=$5, current=$5.01 → disabled; current drops to $4.45 (< 90% of $5) → re-enabled; at 90.1% → still disabled
  - [ ] `test_reservation_context_manager` — `with ledger.reserve("test"): assert ledger.running_concurrent("test") == 1` → outside assert 0
  - [ ] `test_budget_exhausted_impingement_emitted` — simulate over-cap; assert impingement written to `/dev/shm/hapax-dmn/impingements.jsonl` with `salience == 0.55`
  - [ ] `test_aggregate_today_filters_utc_midnight` — seed records from yesterday + today; assert `daily_total_usd()` only counts today
  - [ ] `test_caps_yaml_hot_reload` — edit caps file after ledger init; assert next `check_can_spawn` reads new caps
  - [ ] `test_corrupt_caps_yaml_fallback` — malformed caps → fall back to hardcoded safe defaults; warning logged
- [ ] Run tests: all fail (module missing)

### 3.2 Implementation

- [ ] Create `shared/spawn_budget.py`:
  - [ ] `@dataclass(frozen=True) class BudgetDecision(allowed: bool, reason: str, projected_cost_usd: float, current_daily_usd: float, daily_cap_usd: float)`
  - [ ] `@dataclass(frozen=True) class TouchPointAggregate(touch_point: str, count: int, total_cost_usd: float, avg_cost_usd: float)`
  - [ ] `class Reservation` context manager with `__enter__` / `__exit__` that inc/dec the concurrent counter
  - [ ] `class SpawnBudgetLedger` with:
    - [ ] `__init__(state_path: Path, caps_path: Path)`
    - [ ] `_load_caps() -> dict` with fallback on parse error
    - [ ] `check_can_spawn(touch_point) -> BudgetDecision` reads caps, runs hysteresis, returns decision
    - [ ] `record(touch_point, spawn_id, model_tier, model_id, tokens_in, tokens_out, cost_usd, langfuse_trace_id, status) -> None` appends to JSONL via `atomic_write_json`-style append
    - [ ] `aggregate_today() -> dict[str, TouchPointAggregate]` (UTC midnight boundary)
    - [ ] `daily_total_usd() -> float`
    - [ ] `running_concurrent(touch_point) -> int`
    - [ ] `reserve(touch_point) -> Reservation`
    - [ ] Internal budget exhaustion path writes impingement JSONL entry with salience 0.55 when decision flips allowed=False
- [ ] Create `~/hapax-state/spawn-budget-caps.yaml` template (in repo at `config/spawn-budget-caps.yaml.example`; operator copies to `~/hapax-state/`):
  - [ ] `global_daily_usd: 5.00`
  - [ ] `global_weekly_usd: 30.00`
  - [ ] `hysteresis_pct: 0.10`
  - [ ] `per_touch_point: {research_drafter: {daily_usd: 2.00, max_concurrent: 1}, ...}`
- [ ] Run tests: all pass

### 3.3 Cairo overlay source

- [ ] Create `agents/studio_compositor/spawn_budget_source.py` (~140 LOC):
  - [ ] Implements `CairoSource` protocol
  - [ ] Uses `get_pool().register(WatchedQuery(...))` from deliverable 0.1 to refresh at 1 Hz
  - [ ] Queries ledger's `aggregate_today()` and `daily_total_usd()` — not prometheus (the ledger is authoritative)
  - [ ] Renders "today's spawn budget: N% used, M spawns, top 3 categories" in bottom-right Cairo region
  - [ ] Color: green <50%, yellow 50–80%, red >80% or exhausted
- [ ] Smoke test: stub CairoSource consumer logs the rendered string on each tick

### 3.4 Commit 0.3

- [ ] `uv run ruff check shared/spawn_budget.py agents/studio_compositor/spawn_budget_source.py tests/shared/test_spawn_budget.py`
- [ ] `uv run ruff format` same files
- [ ] `uv run pyright shared/spawn_budget.py`
- [ ] `git add shared/spawn_budget.py agents/studio_compositor/spawn_budget_source.py tests/shared/test_spawn_budget.py config/spawn-budget-caps.yaml.example`
- [ ] `git commit -m "feat(hsea-phase-0): 0.3 spawn budget ledger + caps YAML + Cairo overlay source"`
- [ ] Update `hsea-state.yaml::phase_statuses[0].deliverables[0.3].status: completed`

---

## 4. Deliverable 0.2 — Governance queue

Depends on 0.1 (Cairo overlay uses `WatchedQueryPool`). Executed after 0.1 + 0.3.

### 4.1 Test scaffolding

- [ ] Create `tests/shared/test_governance_queue.py`:
  - [ ] `test_append_returns_id_and_persists` — append entry; re-read; assert round-trip
  - [ ] `test_append_uses_flock` — simulate concurrent appenders (threading or subprocess) and assert no interleaved lines
  - [ ] `test_line_size_warning_at_3800` — metadata ~3900 chars triggers truncation warning
  - [ ] `test_pipe_buf_atomicity` — verify line length < 4096 for any call
  - [ ] `test_status_lifecycle` — `drafted → reviewing → approved → executed → archived` all legal
  - [ ] `test_illegal_status_transition` — `drafted → executed` rejected
  - [ ] `test_expiry_14d` — `drafted_at` older than 14d → status flips to `expired` at next reap
  - [ ] `test_pending_filter` — only drafted + reviewing are pending
  - [ ] `test_oldest_pending_age_s`
  - [ ] `test_most_recent`
  - [ ] `test_reap_moves_archived_to_archive_file`
  - [ ] `test_reader_tolerates_partial_trailing_line` — truncate last byte of JSONL; assert reader skips it
- [ ] Run tests: fail (module missing)

### 4.2 Implementation

- [ ] Create `shared/governance_queue.py`:
  - [ ] Type enum: `GovernanceEntryType = Literal["research-drop", "pr-draft", "osf-amendment", "axiom-precedent", "revenue-draft", "code-patch", "fix-proposal", "exemplar-proposal", "antipattern-proposal", "sprint-measure-update", "distribution-draft"]`
  - [ ] Status enum: `Literal["drafted", "reviewing", "approved", "rejected", "executed", "archived", "expired"]`
  - [ ] `@dataclass class GovernanceEntry` with all fields per spec
  - [ ] `class GovernanceQueue`:
    - [ ] `__init__(state_path: Path, archive_path: Path)`
    - [ ] `append(title, type, drafted_by, location, approval_path, metadata) -> str` (returns id)
    - [ ] Uses `fcntl.flock(fd, LOCK_EX)` + `os.O_APPEND` for append
    - [ ] Line length check; truncates metadata if > `warn_if_over=3800`
    - [ ] `update_status(id, new_status, actor, notes)` appends a status-history line (NOT mutating prior lines)
    - [ ] `pending(max_age_s=None) -> list[GovernanceEntry]`
    - [ ] `oldest_pending_age_s() -> float | None`
    - [ ] `most_recent() -> GovernanceEntry | None`
    - [ ] `reap(older_than_days=30) -> int` — moves archived entries to archive file
- [ ] Run tests: all pass

### 4.3 Inbox inotify watcher

- [ ] Create `agents/governance_queue_watcher.py` (~120 LOC):
  - [ ] `inotify_simple.INotify()` watching `~/Documents/Personal/00-inbox/` for `IN_ACCESS | IN_MODIFY | IN_CLOSE_WRITE`
  - [ ] On `IN_ACCESS` to a file matching `inbox-<id>.md`: call `queue.update_status(id, "reviewing", actor="operator-access")` (idempotent — guard against double-call within 5s)
  - [ ] On `IN_MODIFY` or `IN_CLOSE_WRITE`: parse frontmatter via `shared/frontmatter.py`; if `status: approved` or `status: rejected` differs from current, call `update_status`
  - [ ] Graceful shutdown on SIGTERM
  - [ ] Systemd user unit: `systemd/user/hapax-governance-queue-watcher.service` (`Type=simple`, `Restart=on-failure`, `ExecStart=uv run python -m agents.governance_queue_watcher`)

### 4.4 Cairo overlay source — DESCOPED to HSEA Phase 1 deliverable 1.5

Per the 2026-04-15 extraction of HSEA Phase 1 spec + plan, the governance queue Cairo overlay is NOT a Phase 0 deliverable. It is shipped as deliverable 1.5 of HSEA Phase 1 (see `docs/superpowers/specs/2026-04-15-hsea-phase-1-visibility-surfaces-design.md` §3.5 + the companion Phase 1 plan).

Phase 0 ships the queue primitive (module + inotify watcher + reap timer) only. The Cairo overlay is Phase 1's responsibility because:

1. The HSEA epic spec listed the overlay in BOTH Phase 0 0.2 and Phase 1 1.5 (a pre-existing inconsistency).
2. Drop #62 §7 resource budget row 2 re-listed the overlay as a Phase 1 surface.
3. The phase names themselves argue for the split: Phase 0 = "Foundation Primitives" (primitives, not surfaces); Phase 1 = "Visibility Surfaces" (where Cairo overlays belong).

Phase 0 session that opens this work should SKIP this subtask and proceed directly to task 4.5. Do NOT ship `agents/studio_compositor/governance_queue_source.py` as part of Phase 0.

### 4.5 Reap timer

- [ ] `systemd/user/hapax-governance-queue-reap.timer` — weekly
- [ ] `systemd/user/hapax-governance-queue-reap.service` — `ExecStart=uv run python -c "from shared.governance_queue import GovernanceQueue; …; GovernanceQueue(…).reap(older_than_days=30)"`

### 4.6 Commit 0.2

- [ ] Lint + format + pyright on all new files
- [ ] `git add shared/governance_queue.py agents/governance_queue_watcher.py tests/shared/test_governance_queue.py systemd/user/hapax-governance-queue-*.{timer,service}`
- [ ] NOTE: `agents/studio_compositor/governance_queue_source.py` is NOT staged here — it is HSEA Phase 1 deliverable 1.5
- [ ] `git commit -m "feat(hsea-phase-0): 0.2 governance queue module + inotify watcher + reap timer"`
- [ ] Update `hsea-state.yaml::phase_statuses[0].deliverables[0.2].status: completed`

---

## 5. Deliverable 0.4 — Promote scripts + inbox convention

Depends on 0.2 (ledger interface for status lookups). 8 scripts + 1 helper library + bats tests.

### 5.1 Helper library `_promote-common.sh`

- [ ] Create `scripts/_promote-common.sh` (~140 LOC, sourced by all promote scripts)
  - [ ] `_gq_lookup <id>` — parses `~/hapax-state/governance-queue.jsonl`, finds entry by id (python one-liner or jq); exits 2 if not found
  - [ ] `_gq_validate_approved <entry>` — asserts `status == "approved"`; exits 2 otherwise
  - [ ] `_gq_update_status <id> <new_status>` — `python -c "from shared.governance_queue import GovernanceQueue; …; gq.update_status('$1', '$2', 'promote-script', '')"`
  - [ ] `_frozen_files_check <target>` — `scripts/check-frozen-files.py --probe "$target"` (LRR Phase 1 tool); passthrough exit code. If LRR Phase 1 tool does not yet have `--probe`, add a tiny wrapper here that shells out via `check-frozen-files.py` against a temp staging area. Do NOT duplicate the check logic.
  - [ ] `_ruff_check` — `uv run ruff check . && uv run ruff format --check .`
  - [ ] `_pytest_smoke <files>` — `uv run pytest -q $files` (short-circuit on first failure)
  - [ ] `_consent_scan` — existing `scripts/scan-consent-contracts.sh` or equivalent
  - [ ] `_idempotency_check <location>` — checks for `.already-promoted` sentinel next to `<location>`
  - [ ] `_operator_override_check` — if `HAPAX_PROMOTE_SKIP_CHECKS=1`, emit red warning log + append `status_history` entry with `actor: operator-override`; return 0 (bypass)

### 5.2 Individual promote scripts

Each ~60 LOC, same skeleton: parse args → `_gq_lookup` → `_gq_validate_approved` → `_operator_override_check` → deliverable-specific checks → action → `_gq_update_status <id> executed` → exit 0.

- [ ] `scripts/promote-drop.sh <id>`:
  - [ ] Moves `/dev/shm/hapax-compositor/draft-buffer/<slug>/content.partial.md` → `docs/research/<today>-<slug>.md`
  - [ ] `git add` + `git commit -m "drop(<slug>): <title>"`
  - [ ] Calls `_frozen_files_check` on the new path (should pass — docs/research is not frozen)
- [ ] `scripts/promote-patch.sh <id>`:
  - [ ] `git apply --check` then `git apply`
  - [ ] `_frozen_files_check` + `_ruff_check` + `_pytest_smoke` on touched files
  - [ ] `git commit -m "patch(<slug>): <title>"`
  - [ ] RESERVED FOR HSEA PHASE 4 — ships the script now so the interface exists, but expected zero invocations during Phase 0
- [ ] `scripts/promote-pr.sh <id>`:
  - [ ] `gh pr create --draft --title ... --body ...` (NEVER `--draft=false`, NEVER `gh pr merge`)
  - [ ] `_gq_update_status <id> executed`
- [ ] `scripts/promote-axiom-precedent.sh <id>`:
  - [ ] Moves `axioms/precedents/hsea/<slug>.yaml.draft` → `axioms/precedents/hsea/<slug>.yaml`
  - [ ] `git add axioms/precedents/hsea/<slug>.yaml` (and `git rm` the `.draft`)
  - [ ] `git commit -m "precedent(hsea): <title>"`
- [ ] `scripts/promote-exemplar.sh <id>`:
  - [ ] Appends entry to `shared/exemplars.yaml` (empty shell created in 0.4 support file below)
  - [ ] `git commit -m "exemplar(<slug>): <title>"`
- [ ] `scripts/promote-antipattern.sh <id>`:
  - [ ] Analogous to exemplar
- [ ] `scripts/promote-revenue.sh <id>`:
  - [ ] Routes per target (clipboard copy for external platforms)
  - [ ] NO direct HTTP POST to social platforms — axiom violation
- [ ] `scripts/dispatch-approved.sh <id>`:
  - [ ] Generic clipboard-copy path for social/external posts
  - [ ] Uses `wl-copy` on Wayland

### 5.3 Empty shell support files (LRR Phase 7 populates)

- [ ] Create `shared/exemplars.yaml` with only `schema_version: 1` + empty `exemplars: []` array + comment pointing to LRR Phase 7
- [ ] Create `shared/antipatterns.yaml` similarly

### 5.4 Inbox file convention

- [ ] Create `docs/superpowers/handoff/2026-04-15-hsea-phase-0-inbox-convention.md` — operator-facing doc describing:
  - [ ] Inbox file path: `~/Documents/Personal/00-inbox/inbox-<id>.md`
  - [ ] Frontmatter schema: `id, type, status, drafted_at, drafted_by, location, approval_method, frozen_files_touched, estimated_cost_usd, notes`
  - [ ] How operator flips status: edit the markdown; save; inotify watcher picks it up
  - [ ] How Hapax never writes to inbox directly (only the governance queue writer does, via `update_status`)

### 5.5 Tests

- [ ] `tests/scripts/test_promote_drop.bats` — happy path, not-approved rejection, idempotency replay, frozen-files block, override bypass
- [ ] `tests/scripts/test_promote_patch.bats` — same structure + ruff failure + pytest failure
- [ ] `tests/scripts/test_promote_pr.bats` — mock `gh` (PATH override); assert `--draft` flag always present; assert never `--draft=false`
- [ ] `tests/scripts/test_promote_common.bats` — exercise each helper function in isolation
- [ ] Run: `bats tests/scripts/` — all pass

### 5.6 Commit 0.4

- [ ] `chmod +x scripts/promote-*.sh scripts/dispatch-approved.sh scripts/_promote-common.sh`
- [ ] `git add scripts/promote-*.sh scripts/dispatch-approved.sh scripts/_promote-common.sh shared/exemplars.yaml shared/antipatterns.yaml tests/scripts/test_promote_*.bats docs/superpowers/handoff/2026-04-15-hsea-phase-0-inbox-convention.md`
- [ ] `git commit -m "feat(hsea-phase-0): 0.4 promote scripts + inbox convention + exemplar/antipattern shells"`
- [ ] Update `hsea-state.yaml::phase_statuses[0].deliverables[0.4].status: completed`

---

## 6. Deliverable 0.5 — Axiom precedent (DRAFT form)

Ships LAST so the hook additions can reference the committed promote scripts by path. DRAFT form only — final PR is deferred to LRR Phase 6 joint constitutional PR.

### 6.1 Draft precedent YAML

- [ ] Create `axioms/precedents/hsea/management-governance-drafting-as-content.yaml.draft`:
  - [ ] `id: sp-hsea-mg-001`
  - [ ] `name: "Drafting as preparation, not delivery"`
  - [ ] `decision: "Drafting constitutes preparation (not delivery) IFF operator retains discrete revocable non-visual delivery authority"`
  - [ ] `edge_cases`: livestream clip extraction, daimonion audible narration, drafts referencing individuals (falls back to mg-boundary rules), operator approves without reading, spawn-budget-exhaustion truncation
  - [ ] `enforcement`: references `hooks/scripts/axiom-patterns.sh::check_hsea_auto_delivery()` + `check_hsea_executed_transition()`
  - [ ] `ratification_path`: "joint `hapax-constitution` PR with LRR Phase 6"
  - [ ] `status: draft-pending-lrr-phase-6`
  - [ ] `drafted_at: 2026-04-15` (or actual Phase 0 date)
  - [ ] `authored_by: hsea-phase-0`

### 6.2 Implication addition

- [ ] Append `mg-drafting-visibility-001` entry to `axioms/implications/management-governance.yaml`:
  - [ ] `id: mg-drafting-visibility-001`
  - [ ] `parent_axiom: management_governance`
  - [ ] `statement: "Governance-queue drafts are not delivered to operator surfaces (voice, visual) until operator flips inbox status to approved; drafts in `/dev/shm/hapax-compositor/draft-buffer/` are not visible on the livestream surface."`
  - [ ] `enforcement: hook hsea-auto-delivery`

### 6.3 Hook patterns

- [ ] Create or extend `hooks/scripts/axiom-patterns.sh` with:
  - [ ] `check_hsea_auto_delivery()`:
    - [ ] Blocks `gh pr merge` in commit content (not in promote-pr.sh where it's never present anyway)
    - [ ] Blocks `gh pr create --draft=false`
    - [ ] Blocks `requests.post.*(twitter|bluesky|mastodon|threads)` in python files
    - [ ] Blocks direct `httpx.post` to external social API endpoints
  - [ ] `check_hsea_executed_transition()`:
    - [ ] Grep for `governance_queue.update_status(..., "executed")` call sites
    - [ ] Allowlist: `scripts/promote-*.sh` only (or the python module invoked FROM those scripts)
    - [ ] Block any other file calling `update_status(..., "executed")`
- [ ] Wire both checks into `hooks/scripts/axiom-commit-scan.sh` after the existing pattern checks

### 6.4 Tests

- [ ] Create `tests/hooks/test_axiom_scan_hsea.sh` (~60 LOC bash):
  - [ ] Fixture: tempdir with a python file calling `requests.post("https://bsky.social/...")` → assert hook blocks commit
  - [ ] Fixture: tempdir with a python file calling `governance_queue.update_status("x", "executed")` from `agents/some_agent.py` → assert hook blocks
  - [ ] Fixture: same call from `scripts/promote-drop.sh` → assert hook passes
  - [ ] Fixture: clean file → assert hook passes

### 6.5 Axioms README update

- [ ] Edit `axioms/README.md` or equivalent to add a single line referencing the draft precedent with a note that it ships in the LRR Phase 6 joint PR

### 6.6 Commit 0.5

- [ ] `bash tests/hooks/test_axiom_scan_hsea.sh` — passes
- [ ] `git add axioms/precedents/hsea/management-governance-drafting-as-content.yaml.draft axioms/implications/management-governance.yaml hooks/scripts/axiom-patterns.sh hooks/scripts/axiom-commit-scan.sh tests/hooks/test_axiom_scan_hsea.sh axioms/README.md`
- [ ] `git commit -m "feat(hsea-phase-0): 0.5 axiom precedent draft + hook enforcement + implication addition"`
- [ ] Update `hsea-state.yaml::phase_statuses[0].deliverables[0.5].status: completed`

---

## 7. Phase 0 close

All six deliverables complete. Final steps:

### 7.1 Smoke tests

- [ ] **End-to-end governance queue smoke test:**
  - [ ] Stub drafter writes a "hello drop" governance queue entry via `GovernanceQueue.append(...)` with `type=research-drop`, `status=drafted`
  - [ ] Inbox watcher is running; operator creates `~/Documents/Personal/00-inbox/inbox-<id>.md` with the entry id and `status: approved`
  - [ ] Watcher detects modify; calls `update_status(id, "approved")`
  - [ ] Operator manually runs `scripts/promote-drop.sh <id>`
  - [ ] Script validates approved status, moves the draft to `docs/research/<date>-hello-drop.md`, commits, calls `update_status(id, "executed")`
  - [ ] `GovernanceQueue.reap(older_than_days=30)` at next timer tick catches the archived entry
- [ ] **Spawn budget smoke test:**
  - [ ] Stub drafter calls `SpawnBudgetLedger.check_can_spawn("test_touch_point")` → `BudgetDecision(allowed=True)`
  - [ ] Drafter records a fake $0.001 call via `ledger.record(...)` with a real langfuse trace id from an actual LiteLLM call
  - [ ] `ledger.aggregate_today()` returns `{"test_touch_point": TouchPointAggregate(count=1, total_cost_usd=0.001, avg_cost_usd=0.001)}`
  - [ ] Cairo overlay renders "today's spawn budget: 0.02% used" (assuming $5/day cap)
- [ ] **Prom query smoke test:**
  - [ ] Stub consumer registers `WatchedQuery(query="compositor_uptime_seconds", refresh_hz=1.0, on_value=<collect into list>, endpoint="compositor")`
  - [ ] Wait 5 seconds
  - [ ] Assert collected list has ≥ 4 entries (1 Hz over 5s allowing for startup)
  - [ ] Assert all entries have `ok=True` and `value > 0`
  - [ ] `pool.stop()` — worker joins cleanly

### 7.2 Handoff doc

- [ ] Write `docs/superpowers/handoff/2026-04-15-hsea-phase-0-complete.md`:
  - [ ] Summary of what shipped
  - [ ] Links to PRs / commits for each deliverable
  - [ ] Links to the three smoke test results
  - [ ] Known issues / deferred items (e.g. axiom precedent in `.draft` form awaiting LRR Phase 6)
  - [ ] Open questions this phase did NOT resolve (§10 questions 2, 3, 6, 7, 8, 9, 10 still open)
  - [ ] Next phase (Phase 1 — visibility surfaces) preconditions

### 7.3 State file close-out

- [ ] Edit `~/.cache/hapax/relay/hsea-state.yaml`:
  - [ ] `phase_statuses[0].status: closed`
  - [ ] `phase_statuses[0].closed_at: <now>`
  - [ ] `phase_statuses[0].handoff_path: docs/superpowers/handoff/2026-04-15-hsea-phase-0-complete.md`
  - [ ] `phase_statuses[0].deliverables[*].status: completed` (all six)
  - [ ] `last_completed_phase: 0`
  - [ ] `last_completed_at: <now>`
  - [ ] `last_completed_handoff: <path>`
  - [ ] `current_phase: null` (or 1 if phase 1 is about to open)
  - [ ] `overall_health: green`, `health_reason: "phase 0 closed; awaiting phase 1 open"`
- [ ] Edit `~/.cache/hapax/relay/research-stream-state.yaml`:
  - [ ] `unified_sequence[UP-2].status: closed`
  - [ ] `unified_sequence[UP-2].owner: null`
  - [ ] `last_updated_at: <now>`

### 7.4 axioms/README.md update

- [ ] Add a line referencing the draft precedent status: "pending LRR Phase 6 joint PR for final ratification"

### 7.5 Final verification

- [ ] `git log --oneline` shows 6 `feat(hsea-phase-0): …` commits
- [ ] `uv run pytest -q tests/shared/test_prom_query.py tests/shared/test_governance_queue.py tests/shared/test_spawn_budget.py` — all pass
- [ ] `bash tests/hooks/test_session_context_hsea.sh tests/hooks/test_axiom_scan_hsea.sh` — all pass
- [ ] `bats tests/scripts/test_promote_*.bats` — all pass
- [ ] Fresh shell shows: `HSEA: Phase 0 · owner=<session> · health=green · status=closed` (or phase 1 open)
- [ ] Write inflection to peer sessions announcing Phase 0 closure + next-phase open readiness

---

## 8. Cross-epic coordination (canonical references)

This plan defers to drop #62 §3 (ownership) and §6 (shared state) for all cross-epic questions. Specifically:

- **frozen-files hook ownership:** LRR Phase 1 (UP-1) owns `scripts/check-frozen-files.py`. HSEA Phase 0 only consumes it via `_frozen_files_check` wrapper in `_promote-common.sh`.
- **research registry + condition_id + research-marker.json:** LRR Phase 1. Phase 0 does not touch.
- **stats.py BEST port:** LRR Phase 1. Phase 0 does not touch.
- **axiom precedent joint PR vehicle:** LRR Phase 6 owns the `hapax-constitution` PR. HSEA Phase 0 produces the `.draft` artifact only.
- **Shared state index:** drop #62 §6 sibling-under-shared-index. Phase 0 creates both `hsea-state.yaml` AND `research-stream-state.yaml` in deliverable 0.6.
- **HSEA Phase 4 Cluster I demotion:** drop #62 §9 HSEA spec edits (already committed in drop #62). Phase 0 does not re-apply.
- **HSEA Phase 5 substrate swap:** drop #62 Option C, operator ratified 2026-04-15T05:10Z. See drop #62 §11 addendum. Does not affect Phase 0 scope.

---

## 9. End

This is the standalone per-phase plan for HSEA Phase 0. It is pre-staging — the plan is not executed until the phase opens per the preconditions in §0. The companion spec lives at `docs/superpowers/specs/2026-04-15-hsea-phase-0-foundation-primitives-design.md`.

Pre-staging authored by delta per the request "research and evaluate the best use of your time to push the work along" and the scope handoff in delta's 2026-04-15T05:05Z identity correction inflection.

— delta, 2026-04-15
