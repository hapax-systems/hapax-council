# HSEA Phase 0 — Foundation Primitives — Design Spec

**Date:** 2026-04-15
**Author:** delta (pre-staging extraction from HSEA epic spec per the LRR-epic extraction pattern)
**Status:** DRAFT pre-staging — awaiting operator sign-off + cross-epic dependency resolution before Phase 0 open
**Epic reference:** `docs/superpowers/specs/2026-04-14-hsea-epic-design.md` (HSEA epic; this doc extracts §5 Phase 0 and incorporates drop #62 fold-in corrections)
**Plan reference:** `docs/superpowers/plans/2026-04-15-hsea-phase-0-foundation-primitives-plan.md` (companion TDD checkbox plan)
**Branch target:** `feat/hsea-phase-0-foundation-primitives`
**Cross-epic authority:** `docs/research/2026-04-14-cross-epic-fold-in-lrr-hsea.md` (drop #62) — the ownership table in §3 and the shared-state design in §6 take precedence over any conflicting claim in this spec

---

## 1. Phase goal

Ship the 6 load-bearing primitives without which no other HSEA phase can deliver. Phase 0 is the load-bearing prerequisite for HSEA Phases 1-12 (all downstream phases consume at least one Phase 0 deliverable). Per drop #62 §5 "unified phase sequence," Phase 0 maps to **UP-2** (HSEA foundation primitives) — UP-0 is LRR Phase 0 verification and UP-1 is LRR Phase 1 research registry; HSEA Phase 0 opens only after UP-0 and UP-1 have closed.

**What this phase is NOT:** Phase 0 does not ship visibility surfaces (that is Phase 1), does not extend the director loop with new activities (that is Phase 2), and does not ship the `check-frozen-files` tool itself (that is LRR Phase 1 per drop #62 §3 row 1).

**What this phase IS:** the operator-facing governance queue + inbox convention + budget ledger + shared prometheus poller + axiom precedent + epic state file. Everything that every subsequent HSEA phase will read and write.

---

## 2. Dependencies + preconditions

**Cross-epic (from drop #62):**

1. **LRR Phase 1 (UP-1) MUST be closed before HSEA Phase 0 opens.** LRR Phase 1 ships the research registry, `check-frozen-files.sh` pre-commit hook, `scripts/research-registry.py` CLI, `/dev/shm/hapax-compositor/research-marker.json` SHM file, condition_id tagging, and the `stats.py` BEST verification. Multiple HSEA Phase 0 deliverables consume these. Session onboarding MUST verify `~/.cache/hapax/relay/lrr-state.yaml::phase_statuses[1].status == closed` OR `research-stream-state.yaml::unified_sequence[UP-1].status == closed` before opening this phase.

2. **LRR Phase 0 (UP-0) MUST be closed.** Phase 0 verification (chat-monitor fix, token ledger wiring, inode pressure, FINDING-Q steps, Sierpinski baseline, RTMP path documentation, huggingface-cli, voice transcript path, Kokoro baseline) is foundational to any subsequent work. Verify via LRR state file.

3. **FDL-1 (`ec3d85883`) MUST be deployed to a running compositor.** Phase 0 deliverable 0.1 (Prometheus query client) needs a running compositor exporting metrics at `127.0.0.1:9482` for its tests. The compositor must be operational post-mobo-swap AND FDL-1 must be running in production (not just committed to main). Verify: `systemctl --user is-active studio-compositor` returns active; `curl -s 127.0.0.1:9482/metrics | grep compositor_uptime_seconds` returns a value.

**Intra-epic:** none. Phase 0 is the first HSEA phase; no prior HSEA phase exists.

**Infrastructure:**

1. `shared/telemetry.py::hapax_span` context manager (existing, does NOT have a post-emit hook; Phase 0 works around this).
2. `agents/studio_compositor/cairo_source.py::CairoSource` + `CairoSourceRunner` (existing).
3. `agents/studio_compositor/atomic_io.py::atomic_write_json` (existing, reused for deliverable 0.2, 0.3 atomic writes).
4. `scripts/check-frozen-files.sh` or `.py` (LRR Phase 1 deliverable — this phase consumes, does not create).
5. `~/Documents/Personal/00-inbox/` (operator's Obsidian inbox, already exists with existing `.md` files).
6. `shared/frontmatter.py` (existing canonical frontmatter parser, reused for inbox file schema).
7. `httpx` for HTTP client (existing dependency per `pyproject.toml`).
8. `prometheus_client` for metric emission (existing).
9. `fcntl` for file locking (stdlib).

---

## 3. Deliverables

### 3.1 Prometheus query client (`shared/prom_query.py`)

**Scope:**
- `PromQueryClient` class with methods `instant(query) → InstantResult`, `range(query, start, end, step_s) → RangeResult`, `scalar(query) → float | None`, `is_degraded() → bool`
- `InstantResult` + `RangeResult` immutable dataclasses (value(s), timestamp, ok, error)
- `WatchedQuery` declarative abstraction: `WatchedQuery(query, refresh_hz, on_value, endpoint)`
- `WatchedQueryPool` shared thread pool with tiers 0.5/1/2/5 Hz; one worker per tier; max 4 concurrent polling loops regardless of consumer count
- Process-wide singleton `get_pool()` returning the shared pool
- Two endpoints: `compositor` (`http://127.0.0.1:9482`) and `central` (`http://127.0.0.1:9090`)
- Error handling: connection-refused/timeout/HTTP-5xx/JSON-parse-error each return `InstantResult(ok=False)` or `InstantResult(value=None, ok=True)`; degraded-state flag tracked; never raises to caller (Cairo render callbacks must not throw)
- Degraded-state re-enable: on next successful query

**Target file:** `shared/prom_query.py` (~280 LOC implementation + ~150 LOC tests ≈ 430 LOC total)

**Testability:** `respx` HTTP mocking fixture; tests cover happy path, connection-refused degradation, empty-result-set, HTTP 500, JSON malformed, pool-worker lifecycle.

**Interface sketch** (abridged from drop #62 Phase 0 design research):

```python
@dataclass(frozen=True)
class InstantResult:
    value: float | None
    timestamp: float
    ok: bool
    error: str | None = None

class PromQueryClient:
    def __init__(self, endpoint: PromEndpoint = "compositor",
                 timeout_s: float = 1.5, stale_grace_s: float = 10.0) -> None: ...
    def instant(self, query: str) -> InstantResult: ...
    def range(self, query: str, start: float, end: float, step_s: float) -> RangeResult: ...
    def scalar(self, query: str) -> float | None: ...
    def is_degraded(self) -> bool: ...

@dataclass
class WatchedQuery:
    query: str
    refresh_hz: RefreshTier     # Literal[0.5, 1.0, 2.0, 5.0]
    on_value: Callable[[InstantResult], None]
    endpoint: PromEndpoint = "compositor"

class WatchedQueryPool:
    _TIERS: tuple[RefreshTier, ...] = (0.5, 1.0, 2.0, 5.0)
    def register(self, wq: WatchedQuery) -> None: ...
    def stop(self) -> None: ...
```

**Deliverable size:** ~430 LOC, 1 day serial work.

### 3.2 Governance queue (`shared/governance_queue.py` + JSONL state + inotify watcher)

**Scope:**
- JSONL append-only ledger at `~/hapax-state/governance-queue.jsonl` with archive rotation at `~/hapax-state/governance-queue-archive.jsonl`
- Per-line schema: `{id, title, type, drafted_at, drafted_by, location, status, approval_path, approval_method, metadata, status_history[]}`
- Type enum: `research-drop | pr-draft | osf-amendment | axiom-precedent | revenue-draft | code-patch | fix-proposal | exemplar-proposal | antipattern-proposal | sprint-measure-update | distribution-draft`
- Status lifecycle: `drafted → reviewing → approved → executed → archived` OR `drafted → rejected → archived` OR `drafted → expired → archived` (14-day expiry)
- Concurrency: append via `fcntl.flock(fd, LOCK_EX)` + `O_APPEND`; line size < PIPE_BUF (4096) for POSIX atomic-append guarantees; `warn_if_over=3800` metadata truncation
- Readers read without locking; tolerate partial trailing lines
- `GovernanceQueue` module API: `append(title, type, drafted_by, location, approval_path, metadata) → id`, `update_status(id, new_status, actor, notes)`, `pending(max_age_s)`, `oldest_pending_age_s()`, `most_recent()`, `reap(older_than_days=30)`
- Obsidian inbox sync: inotify watcher on `~/Documents/Personal/00-inbox/` detects `ACCESS` → `update_status(id, "reviewing")`; detects `MODIFY` + parses frontmatter status change → `update_status(id, "approved"|"rejected")`; uses `shared/frontmatter.py` parser
- **Cairo overlay is OUT OF SCOPE for Phase 0 (descoped to HSEA Phase 1 deliverable 1.5).** The original HSEA epic spec §5 Phase 0 listed a Cairo overlay in 0.2, but it was also listed in Phase 1 as deliverable 1.5 (drop #62 §7 resource budget row 2 carried this forward). The 2026-04-15 extraction resolves the duplication: Phase 0 ships the queue primitive (module + inotify watcher + reap) and Phase 1 ships the Cairo overlay. `agents/studio_compositor/governance_queue_source.py` is a Phase 1 deliverable, not Phase 0.
- Reap: weekly systemd timer `hapax-governance-queue-reap.timer` moves archived entries out of main file

**Target files:**
- `shared/governance_queue.py` (~220 LOC module)
- `agents/governance_queue_watcher.py` or `logos/watchers/governance_queue_watcher.py` (~120 LOC inotify daemon)
- `tests/shared/test_governance_queue.py` (~200 LOC)
- `systemd/user/hapax-governance-queue-reap.timer` + `.service` (config)
- **NOT shipped by Phase 0** (HSEA Phase 1 1.5): `agents/studio_compositor/governance_queue_source.py` (~150 LOC overlay source; see `docs/superpowers/specs/2026-04-15-hsea-phase-1-visibility-surfaces-design.md` §3.5)

**Deliverable size:** ~540 LOC (was ~720; Cairo overlay ~180 LOC moved to Phase 1), 0.8 day serial work.

### 3.3 Spawn budget ledger (`shared/spawn_budget.py` + JSONL state + caps YAML + Cairo overlay)

**Scope:**
- Per-LLM-call JSONL ledger at `~/hapax-state/spawn-budget.jsonl`: `{timestamp, touch_point, spawn_id, model_tier, model_id, tokens_in, tokens_out, cost_usd, latency_ms, langfuse_trace_id, status}`
- Operator-editable caps at `~/hapax-state/spawn-budget-caps.yaml`: global daily USD cap (default $5), global weekly cap, per-touch-point daily caps + concurrency limits, hysteresis percentage (default 10% — re-enable at 90% of cap)
- `SpawnBudgetLedger` module API: `check_can_spawn(touch_point) → BudgetDecision`, `record(touch_point, spawn_id, model_tier, model_id, tokens_in, tokens_out, cost_usd, langfuse_trace_id, status)`, `aggregate_today() → dict[str, TouchPointAggregate]`, `daily_total_usd() → float`, `running_concurrent(touch_point) → int`
- `BudgetDecision(allowed, reason, projected_cost_usd, current_daily_usd, daily_cap_usd)` return type
- Reservation context manager: `ledger.reserve(touch_point) → Reservation` increments concurrent counter on `__enter__`, decrements on `__exit__`
- Cost source: authoritative from LiteLLM response (`x-litellm-response-cost` header or Langfuse `total_cost`); never estimated from tokens
- Pre-spawn projection: rolling average of last 20 calls for that touch point; seeded from `shared/config.py` tier defaults
- Budget-exhaustion behavior: publishes `budget_exhausted` impingement to `/dev/shm/hapax-dmn/impingements.jsonl` with salience 0.55; daimonion narrates; Cairo overlay flips to red
- Hysteresis: re-enable crosses at UTC midnight under normal conditions
- Cairo overlay (via deliverable 0.1 `WatchedQueryPool`): "today's spawn budget: 47% used, 12 spawns, top 3 categories"
- Integration: extends `mcp__hapax__cost` tool with `by_touch_point: bool = False` parameter reading from this ledger

**Target files:**
- `shared/spawn_budget.py` (~260 LOC ledger module)
- `~/hapax-state/spawn-budget-caps.yaml` (operator-editable config)
- `agents/studio_compositor/spawn_budget_source.py` (~140 LOC overlay)
- `tests/shared/test_spawn_budget.py` (~180 LOC)

**Deliverable size:** ~580 LOC, 0.5 day serial work.

### 3.4 Prepare/deliver inbox convention (`scripts/promote-*.sh` + `_promote-common.sh`)

**Scope:**
- Directory layout: `~/Documents/Personal/00-inbox/` (existing; extended with inbox file convention) + `/dev/shm/hapax-compositor/draft-buffer/<slug>/` (volatile work area)
- Inbox file frontmatter schema via `shared/frontmatter.py`: `id` (joins to governance queue), `type` (enum), `status` (drafted|reviewing|approved|rejected|filed|expired), `drafted_at`, `drafted_by`, `location`, `approval_method`, `frozen_files_touched`, `estimated_cost_usd`, operator-editable `notes`
- Promote scripts (operator-invoked; Hapax NEVER calls these directly):
  - `scripts/promote-drop.sh <id>` — moves `/dev/shm/.../content.partial.md` → `docs/research/<date>-<slug>.md`, commits
  - `scripts/promote-patch.sh <id>` — runs `git apply --check` then `git apply`, commits (reserved for HSEA Phase 4 Cluster I)
  - `scripts/promote-pr.sh <id>` — calls `gh pr create --draft` (never `--draft=false`, never `gh pr merge`)
  - `scripts/promote-axiom-precedent.sh <id>` — moves precedent YAML into `axioms/precedents/hsea/`
  - `scripts/promote-exemplar.sh <id>` — updates `shared/exemplars.yaml` (file shell only; population is LRR Phase 7)
  - `scripts/promote-antipattern.sh <id>` — updates `shared/antipatterns.yaml`
  - `scripts/promote-revenue.sh <id>` — routes per-target (clipboard copy for external platforms)
  - `scripts/dispatch-approved.sh <id>` — generic clipboard-copy path for social/external posts
- `_promote-common.sh` helper library (sourced by all promote scripts):
  - `_gq_lookup <id>` — reads entry from `governance-queue.jsonl`, exits 2 if not found
  - `_gq_validate_approved <entry>` — status must be "approved", exits 2 if not
  - `_gq_update_status <id> <new_status>` — appends status transition
  - `_frozen_files_check <target>` — calls `scripts/check-frozen-files.py --probe <target>` (LRR Phase 1 provides `.py` version; Phase 0 ONLY adds the `--probe` wrapper if LRR Phase 1's tool does not yet have it)
  - `_ruff_check` — `uv run ruff check . && uv run ruff format --check .`
  - `_pytest_smoke <files>` — smoke test for touched files
  - `_consent_scan` — existing consent contract scan
  - `_idempotency_check <location>` — checks `.already-promoted` marker, exits 0 if already done
- Operator override: `HAPAX_PROMOTE_SKIP_CHECKS=1` bypasses ruff / pytest / consent / frozen-files checks; emits red warning log + appends `status_history` entry with `actor: operator-override`
- Tests: `bats-core` shell tests (or pure bash with tiny harness); fixtures include a fake `governance-queue.jsonl` + dummy draft files; each script has tests for happy path, approved=false rejection, idempotency replay, frozen-files block, ruff failure, override bypass

**Target files:**
- `scripts/promote-drop.sh`, `scripts/promote-patch.sh`, `scripts/promote-pr.sh`, `scripts/promote-axiom-precedent.sh`, `scripts/promote-exemplar.sh`, `scripts/promote-antipattern.sh`, `scripts/promote-revenue.sh`, `scripts/dispatch-approved.sh` (~60 LOC each, 8 scripts)
- `scripts/_promote-common.sh` (~140 LOC helper library)
- `tests/scripts/test_promote_*.bats` (~200 LOC)

**Deliverable size:** ~760 LOC, 0.5 day serial work.

### 3.5 Axiom precedent (`axioms/precedents/hsea/management-governance-drafting-as-content.yaml`)

**Scope:**
- Precedent ID: `sp-hsea-mg-001`
- Decision: drafting constitutes preparation (not delivery) IFF operator retains discrete revocable non-visual delivery authority
- Covered edge cases: livestream clip extraction, daimonion audible narration, drafts referencing individuals (falls back to existing mg-boundary rules), operator approves without reading, spawn-budget-exhaustion truncation
- New implication `mg-drafting-visibility-001` added to `axioms/implications/management-governance.yaml`
- Enforcement hook: extends `hooks/scripts/axiom-commit-scan.sh` (via new `axiom-patterns.sh::check_hsea_auto_delivery()`) with auto-delivery pattern detection (blocks `gh pr merge`, `gh pr create --draft=false`, `requests.post.*(twitter|bluesky)`, etc.) + `check_hsea_executed_transition()` blocks non-promote-script files from calling `governance_queue.update_status(..., "executed")`
- **PR vehicle (cross-epic per drop #62 §3 row 11):** ships in the SAME `hapax-constitution` PR as LRR Phase 6 (UP-8) amendments: `it-irreversible-broadcast` implication, `su-privacy-001` clarification, `corporate_boundary` clarification. HSEA Phase 0 deliverable 0.5 drafts the YAML; LRR Phase 6 opens the single joint PR.

**This deliverable produces the YAML artifact but does NOT open the PR.** The PR open is deferred to LRR Phase 6. HSEA Phase 0 closes with the YAML committed as a draft in `axioms/precedents/hsea/management-governance-drafting-as-content.yaml.draft` or similar non-active location; the file is moved to its final path by `scripts/promote-axiom-precedent.sh` during the LRR Phase 6 joint PR open. This pre-staging is analogous to how beta + epsilon pre-staged LRR phase specs on `beta-phase-4-bootstrap` before the phases opened.

**Target files:**
- `axioms/precedents/hsea/management-governance-drafting-as-content.yaml.draft` (staged; moved to final path at LRR Phase 6 PR time)
- `axioms/implications/management-governance.yaml` — append `mg-drafting-visibility-001` entry
- `hooks/scripts/axiom-patterns.sh` — append `check_hsea_auto_delivery()` + `check_hsea_executed_transition()`
- `hooks/scripts/axiom-commit-scan.sh` — wire the new pattern checks
- `tests/hooks/test_axiom_scan_hsea.sh` (~60 LOC)

**Deliverable size:** ~220 LOC, 0.5 day serial work.

### 3.6 Epic state file (`~/.cache/hapax/relay/hsea-state.yaml`)

**Scope (per drop #62 §6 recommended sibling-files-under-shared-index design, ratified 2026-04-15T05:35Z as drop #62 §10 Q4 option (a)):**
- File location: `~/.cache/hapax/relay/hsea-state.yaml`
- Schema mirrors LRR state file at `~/.cache/hapax/relay/lrr-state.yaml`
- Top-level fields: `epic_id`, `epic_design_doc`, `epic_plan_doc`, `thesis_doc`, `audit_doc`, `current_phase`, `current_phase_owner`, `current_phase_branch`, `current_phase_pr`, `current_phase_opened_at`, `last_completed_phase`, `last_completed_at`, `last_completed_handoff`, `overall_health`, `health_reason`, `phase_statuses[]`, `known_blockers[]`, `related_epics[]`, `notes`
- Per-phase: `phase` (int), `name` (slug), `status` (pending|open|in_review|closed|deferred), `opened_at`, `closed_at`, `spec_path`, `plan_path`, `handoff_path`, `pr_url`, `branch_name`, `deliverables[]`, `dependencies[]`, `unblocks[]`, `tests_required[]`
- Per-deliverable: `id`, `name`, `status`, `loc_estimate`, `owner`
- Update conventions: phase open, deliverable transitions, blocker discovery, phase close (same as LRR pattern)
- Read conventions: `hooks/scripts/session-context.sh` extended to read `hsea-state.yaml` if present and surface `HSEA: Phase N · owner=<session> · health=<color>` in the session-context advisory
- **Shared index ownership (per drop #62 §10 Q8 ratification 2026-04-15T05:35Z):** `~/.cache/hapax/relay/research-stream-state.yaml` is written by alpha at UP-0 fold-in commit time, then operator-only thereafter. HSEA Phase 0 0.6 **verifies** its existence and appends the HSEA Phase 0 entry to `unified_sequence[UP-2]`; HSEA Phase 0 does **NOT** create the shared index from scratch. If UP-0 fold-in has not yet landed when HSEA Phase 0 opens, the phase MUST block on UP-0 close rather than creating the shared index preemptively.
- Phase 0 is the first session to write `hsea-state.yaml` — writes it at phase open with `phase_statuses[0].status: open`

**Target files:**
- `~/.cache/hapax/relay/hsea-state.yaml` (~110 lines YAML) — HSEA Phase 0 creates
- `~/.cache/hapax/relay/research-stream-state.yaml` — NOT created by HSEA Phase 0; verified-and-appended-to only. Created by alpha at UP-0 fold-in time per Q8 ratification.
- `hooks/scripts/session-context.sh` — extension to read both files (hsea-state + shared index)
- `tests/hooks/test_session_context_hsea.sh` (~40 LOC)

**Deliverable size:** ~180 LOC (mostly the HSEA YAML + shell extension), 0.1 day serial work.

---

## 4. Phase-specific decisions since epic authored

Drop #62 fold-in (2026-04-14) + operator batch ratification (2026-04-15T05:35Z via "I accept all your recommendations") made the following corrections to the original HSEA epic spec. Applied here:

1. **`scripts/check-frozen-files` is NOT a Phase 0 deliverable.** LRR Phase 1 (UP-1) owns the hook. HSEA Phase 0 deliverable 0.4 ONLY adds a thin `--probe` wrapper invocation to `_promote-common.sh` that calls the LRR-shipped tool. If LRR Phase 1's implementation already includes a probe mode (read a diff from stdin without requiring staged files), HSEA Phase 0 does NOT re-ship it.

2. **`shared/exemplars.yaml` + `shared/antipatterns.yaml` are empty shells only.** HSEA Phase 0 deliverable 0.4 creates these as empty YAML files with just a `schema_version: 1` header. Population is LRR Phase 7 (persona spec) work. Drop #62 §10 Q3 ratification (HSEA Phase 4 full rescoping to narration-only for I1–I5) does not change this: the shells remain, and the drafter-specific population still defers to LRR Phase 7.

3. **Axiom precedent ships in joint PR with LRR Phase 6 (per §10 Q5 ratification).** Deliverable 0.5 produces the YAML as a DRAFT (suffixed `.draft` or in a staging location). The final PR that moves it to `axioms/precedents/hsea/management-governance-drafting-as-content.yaml` is LRR Phase 6's `hapax-constitution` PR vehicle. HSEA Phase 0 closes with the draft committed but not in its final location. The joint PR covers 5 constitutional changes total: 4 from LRR Phase 6 (`it-irreversible-broadcast`, `su-privacy-001` clarification, `corporate_boundary` clarification, `mg-drafting-visibility-001`) + 1 from HSEA Phase 0 0.5 (`sp-hsea-mg-001`).

4. **Sibling state files under shared index (per §10 Q4 ratification).** HSEA Phase 0 creates `hsea-state.yaml`. Alpha creates `research-stream-state.yaml` at UP-0 fold-in commit time (per §10 Q8 ratification). HSEA Phase 0 0.6 verifies the shared index exists and appends the HSEA Phase 0 entry to `unified_sequence[UP-2]`; it does NOT create the shared index from scratch.

5. **Session-context.sh extension** must surface BOTH `lrr-state.yaml` AND `hsea-state.yaml` content. The existing LRR state surfacing pattern is the model; Phase 0 extends it to cover HSEA state, with the shared index file as the cross-epic surface.

6. **HSEA Phase 4 Cluster I full rescoping (per §10 Q3 ratification 2026-04-15T05:35Z):** HSEA Phase 4 sub-drafters I1/I2/I3/I4/I5 become narration-only spectator agents. Only I6 (conditional on `rtmp_output.py` frozen status) and I7 (ritualized states) remain as code drafters. This does NOT affect HSEA Phase 0 scope — Phase 0 does not stage drafter-specific primitives — but it does confirm that the `promote-patch.sh` script shipped in deliverable 0.4 expects zero Cluster I1–I5 invocations during HSEA Phase 4 execution, only I6 (if conditional passes) + I7.

7. **T2.8 LLM output guardrail bundles into UP-7a DEVIATION (per §10 Q2 ratification).** No Phase 0 impact — T2.8 is LRR-owned and ships at UP-7a execution time, not Phase 0. Noted for completeness.

---

## 5. Exit criteria

Phase 0 closes when ALL of the following are verified:

1. All 6 deliverables merged to main:
   - [ ] `shared/prom_query.py` + tests passing
   - [ ] `shared/governance_queue.py` + inotify watcher + tests passing (Cairo overlay descoped to HSEA Phase 1 1.5)
   - [ ] `shared/spawn_budget.py` + caps YAML + overlay + tests passing
   - [ ] `scripts/promote-*.sh` (8 scripts) + `_promote-common.sh` + bats tests passing
   - [ ] `axioms/precedents/hsea/management-governance-drafting-as-content.yaml.draft` committed (final promotion deferred to LRR Phase 6 joint PR)
   - [ ] `~/.cache/hapax/relay/hsea-state.yaml` + `research-stream-state.yaml` created

2. `hsea-state.yaml::phase_statuses[0].status == closed` (self-close)

3. `research-stream-state.yaml::unified_sequence[UP-2].status == closed` (shared index reflects the closure)

4. `session-context.sh` extension merged and verified by a fresh shell surfacing `HSEA: Phase 0 · owner=<session> · health=green` at session start

5. `axioms/README.md` updated with a line referencing the draft precedent (the full reference waits for LRR Phase 6)

6. **End-to-end smoke test:** a stub drafter agent writes a governance queue entry → the inbox frontmatter watcher detects the file → operator flips `status: approved` in the inbox markdown → `promote-drop.sh <id>` executes cleanly → governance queue entry transitions to `executed` → archive eventually catches it. The smoke test can use a trivial "hello drop" content file; it's testing the plumbing not the drop.

7. **Spawn budget smoke test:** a stub drafter calls `check_can_spawn("test")` → budget ledger returns `BudgetDecision(allowed=True)` → drafter records a $0.001 test call → `aggregate_today()` reflects it → the Cairo overlay shows "today's spawn budget: 0.02%" or similar.

8. **Prom query smoke test:** HUD consumer from Phase 1 registers a `WatchedQuery` for `compositor_uptime_seconds` → pool worker polls → result flows back to consumer → consumer renders. Phase 1 does NOT need to be open for this test; a stub CairoSource in the test harness is sufficient.

9. **Phase 0 handoff doc written** at `docs/superpowers/handoff/2026-04-15-hsea-phase-0-complete.md` (use today's date at actual closing)

10. **No drop #62 §10 open questions affecting Phase 0 remain unresolved.** Specifically: operator has confirmed state file design (§10 question 4 — sibling-under-index recommended).

---

## 6. Risks + mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| LRR Phase 1 not yet closed when Phase 0 opens | HIGH | Blocks 0.4 (promote scripts depend on frozen-files hook) and 0.5 (axiom precedent ships in joint PR with LRR Phase 6) | Phase 0 onboarding MUST verify LRR UP-1 closed; otherwise phase does not open |
| Compositor not running post-mobo-swap when 0.1 tests run | MEDIUM | Blocks 0.1 integration tests | Verify compositor via systemd + `/metrics` endpoint before starting 0.1 |
| PyPI `respx` dependency not installed | LOW | Blocks 0.1 tests | `uv add respx --dev` |
| `fcntl.flock` platform portability | LOW | Phase 0 assumes Linux (fcntl + O_APPEND semantics) | Documented; no Windows/BSD support needed |
| Line size exceeds PIPE_BUF on metadata-heavy governance entries | MEDIUM | Breaks append atomicity | `warn_if_over=3800` + metadata truncation; governance_queue test covers |
| Axiom precedent draft conflicts with LRR Phase 6 text when joint PR opens | MEDIUM | Merge conflict in `hapax-constitution` PR | Phase 0 commits the draft to `axioms/precedents/hsea/management-governance-drafting-as-content.yaml.draft`; LRR Phase 6 moves it. No simultaneous editing. |
| Operator decides against sibling-under-index state file design | LOW | Deliverable 0.6 changes shape | Defer 0.6 until operator answers drop #62 §10 question 4 |
| FDL-1 not deployed / compositor still failed | MEDIUM | Same as compositor-not-running risk; prerequisite for 0.1 tests | Blocker check on phase open |

---

## 7. Open questions (per drop #62 §10, Phase 0-relevant)

All drop #62 §10 open questions have been operator-ratified as of 2026-04-15T05:35Z. No open questions remain that block Phase 0. Captured resolutions:

- **§10 Q1** Substrate swap path → option (c), ratified 2026-04-15T05:10Z. No Phase 0 impact (the substrate fork affects UP-7a, not Phase 0).
- **§10 Q2** T2.8 LLM output guardrail DEVIATION cycle → option (a), bundles into UP-7a. Ratified 2026-04-15T05:35Z. No Phase 0 impact.
- **§10 Q3** HSEA Phase 4 full rescoping (I1–I5 narration-only) → option (a). Ratified 2026-04-15T05:35Z. Confirmed in §4 decision 6; `promote-patch.sh` expects only I6/I7 invocations during Phase 4.
- **§10 Q4** State file design → option (a), sibling files under shared index. Ratified 2026-04-15T05:35Z. Applied to deliverable 0.6.
- **§10 Q5** Constitutional PR strategy → option (a), one joint PR. Ratified 2026-04-15T05:35Z. Applied to deliverable 0.5.
- **§10 Q6** Cluster H (revenue) timing → option (a), accept UP-12 timing. Ratified 2026-04-15T05:35Z. No Phase 0 impact.
- **§10 Q7** Worktree allocation → option (a), 2-parallel. Ratified 2026-04-15T05:35Z. No Phase 0 impact.
- **§10 Q8** `research-stream-state.yaml` maintenance → option (a), alpha-initial + operator-only-thereafter. Ratified 2026-04-15T05:35Z. Applied to deliverable 0.6 (HSEA Phase 0 verifies-and-appends only; does not create).
- **§10 Q9** Drop #62 artifact location → option (a), keep in `docs/research/`. Ratified 2026-04-15T05:35Z. No Phase 0 impact.
- **§10 Q10** Phase ordering deviation tolerance → option (b), operator-discretion. Ratified 2026-04-15T05:35Z. No Phase 0 impact.

**Phase 0 has no remaining operator-pending dependencies from drop #62 §10.** The only preconditions are LRR UP-0 closed, LRR UP-1 closed, FDL-1 deployed, and `research-stream-state.yaml` created by alpha at UP-0 fold-in commit time (per §10 Q8 resolution).

---

## 8. Companion plan doc

TDD checkbox task breakdown at `docs/superpowers/plans/2026-04-15-hsea-phase-0-foundation-primitives-plan.md`.

Execution order inside Phase 0 (single session, sequential per delta's Phase 0 foundation research):

1. **0.6 epic state file** (hsea-state.yaml + verify-and-append research-stream-state.yaml + session-context.sh extension) — written first so session-context sees the phase as open immediately
2. **0.1 prom_query** — no dependencies; required by 0.3's spawn-budget Cairo overlay and by all HSEA Phase 1 surfaces downstream
3. **0.3 spawn_budget** — consumes 0.1 for its Cairo overlay; otherwise independent
4. **0.2 governance_queue** — independent (Cairo overlay descoped to HSEA Phase 1 1.5 per drop #62 §7 row 2 resolution); can interleave with 0.1/0.3
5. **0.4 promote scripts** — depends on 0.2 ledger module API for status lookups
6. **0.5 axiom precedent draft** — ships last so the hook additions can reference the committed promote scripts by path

Each deliverable is a separate PR (or a single multi-commit PR with reviewer pass per deliverable). Phase 0 closes when all six are merged, the shared index reflects closure, and the smoke tests pass.

---

## 9. End

This is the standalone per-phase design spec for HSEA Phase 0. It extracts the Phase 0 section of the HSEA epic spec (drop #60, `docs/superpowers/specs/2026-04-14-hsea-epic-design.md` §5) and incorporates all relevant corrections from the cross-epic fold-in (drop #62, `docs/research/2026-04-14-cross-epic-fold-in-lrr-hsea.md`). The companion plan doc ships alongside.

This spec is pre-staging. It does not open Phase 0. Phase 0 opens only when:
- LRR UP-0 (verification) is closed
- LRR UP-1 (research registry) is closed
- FDL-1 is deployed to a running compositor
- Operator has ratified drop #62 §10 Q4 (state file design) and Q5 (constitutional PR strategy)
- A session claims the phase via `hsea-state.yaml::phase_statuses[0].status: open`

Pre-staging authored by delta per the request "research and evaluate the best use of your time to push the work along."

— delta, 2026-04-15
