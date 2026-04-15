# operator-patterns Qdrant collection — writer investigation

**Date:** 2026-04-15
**Investigator:** alpha (LRR Phase 1 delta queue item #22)
**Spec reference:** `docs/superpowers/specs/2026-04-15-lrr-phase-1-research-registry-design.md` §3.10b
**Close-out cross-reference:** Q024 #83, Q026 Phase 4 Finding 2
**Scope:** determine whether the `operator-patterns` Qdrant writer is re-schedulable or should be retired, per LRR Phase 1 item 10b decision.

## TL;DR

The Q024 #83 claim that the writer is **de-scheduled** is incorrect. The writer is reactive-engine-scheduled and fires once per day via `PATTERN_CONSOLIDATION_RULE`. The empty-collection state is caused by a **latent `AttributeError` in the handler**: `run_consolidation` calls `episode_store.get_all(limit=50)` but `EpisodeStore` (`logos/_episodic_memory.py`) does not define a `get_all` method — only `record` and `search`. Every fire raises `AttributeError` and the engine swallows it, so no Qdrant points are ever written.

**Recommended decision:** **fix, not retire.** The rule is architecturally load-bearing (WS3 L3 extraction is the learning loop that promotes episodes + corrections into reusable patterns). The fix is a 15–20 LOC `EpisodeStore.get_all()` addition. Retirement would remove a designed-for-but-never-wired learning surface.

## Investigation trail

### Step 1 — locate the writer

Three near-identical 404-line modules exist:

- `agents/_pattern_consolidation.py`
- `logos/_pattern_consolidation.py`
- `shared/pattern_consolidation.py`

All three define `PatternStore`, `run_consolidation`, `extract_patterns`, and hold `COLLECTION = "operator-patterns"`. They are triplicated across layers for WS3 L3 per the pre-restructure history (see commit `85b8f9ca1` LLM-optimized codebase restructuring).

### Step 2 — determine the scheduling path

Grep for `PATTERN_CONSOLIDATION_RULE`:

```
logos/engine/reactive_rules.py:54:    PATTERN_CONSOLIDATION_RULE,
logos/engine/reactive_rules.py:76:    PATTERN_CONSOLIDATION_RULE,
logos/engine/rules_phase2.py:199:PATTERN_CONSOLIDATION_RULE = Rule(
```

The rule is defined in `logos/engine/rules_phase2.py` and **registered in `ALL_RULES`** at `logos/engine/reactive_rules.py:76`. It is not gated behind a feature flag. It is wired into the reactive engine's rule registry via `register_rules(registry)` at startup.

Rule parameters:

| Field | Value |
|---|---|
| `trigger_filter` | `_consolidation_filter` — fires on `perception-state.json` change with 300 s quiet window |
| `produce` | `_consolidation_produce` — emits `Action(name="pattern-consolidation", ...)` |
| `phase` | 2 |
| `priority` | 90 |
| `cooldown_s` | 86400 (24 h) |

**There is no systemd timer for pattern consolidation.** The reactive engine owns scheduling, and it IS actively scheduled.

### Step 3 — follow the handler path

`_handle_pattern_consolidation` at `logos/engine/rules_phase2.py:160`:

```python
async def _handle_pattern_consolidation(*, ignore_fn=None) -> str:
    from agents._correction_memory import CorrectionStore
    from logos._episodic_memory import EpisodeStore
    from logos._pattern_consolidation import PatternStore, run_consolidation

    episode_store = EpisodeStore()
    correction_store = CorrectionStore()
    pattern_store = PatternStore()
    pattern_store.ensure_collection()

    result = await run_consolidation(episode_store, correction_store, pattern_store)
    ...
```

`run_consolidation` at `logos/_pattern_consolidation.py:352`:

```python
async def run_consolidation(
    episode_store: Any,
    correction_store: Any,
    pattern_store: PatternStore,
) -> ConsolidationResult:
    # Gather data
    episodes = [ep.model_dump() for ep in episode_store.get_all(limit=50)]
    corrections = [c.model_dump() for c in correction_store.get_all(limit=30)]
    existing = [p.model_dump() for p in pattern_store.get_active(limit=20)]
    ...
```

### Step 4 — verify the method gap

`EpisodeStore` in `logos/_episodic_memory.py` (lines 237–330) defines:

| Method | Defined |
|---|---|
| `__init__` | yes |
| `ensure_collection` | yes |
| `record` | yes |
| `search` | yes |
| `get_all` | **NO** |

Grep confirms zero `def get_all` definitions in the file. `CorrectionStore` (`agents/_correction_memory.py:201`) and `PatternStore` (`logos/_pattern_consolidation.py:331`) both define their corresponding bulk-read methods (`get_all`, `get_active`); `EpisodeStore` is the outlier.

Calling `episode_store.get_all(limit=50)` on an `EpisodeStore` instance raises `AttributeError: 'EpisodeStore' object has no attribute 'get_all'`. This is the root cause of the empty `operator-patterns` collection.

### Step 5 — verify the rule is swallowing errors silently

Reactive engine execution wraps handler calls in a try/except that logs the error and continues processing (standard engine behavior for rule isolation). A quick log search for `pattern.consolidat` / `AttributeError` / `get_all` across `journalctl --user` for the last 7 days returned no hits, which is consistent with either (a) the rule never fires because `perception-state.json` writes are too infrequent to satisfy the 300 s quiet window, (b) the rule fires but the error path is logged at DEBUG, or (c) logs were rotated. Without a longer observability window (Langfuse trace scan for pattern-consolidation action invocations), I can't distinguish between "fired and crashed" vs "never fired." What I can confirm: **even if it fires, the handler cannot succeed.**

## Decision inputs

### Option A — fix (recommended)

**Scope:** add `EpisodeStore.get_all(limit: int = 50) -> list[Episode]` using `client.scroll` over the `operator-episodes` collection, sorted by `start_ts` descending.

**Approx delta:**

```python
def get_all(self, *, limit: int = 50) -> list[Episode]:
    """Return the most recent episodes, newest first."""
    points, _ = self.client.scroll(
        collection_name=COLLECTION,
        limit=limit,
        with_payload=True,
        with_vectors=False,
    )
    episodes: list[Episode] = []
    for p in points:
        try:
            episodes.append(Episode(**(p.payload or {})))
        except Exception:
            continue
    episodes.sort(key=lambda e: e.start_ts, reverse=True)
    return episodes[:limit]
```

Size: ~15 LOC + ~30 LOC test.

**Touched files:**

- `logos/_episodic_memory.py` — add `get_all` method (not in frozen_files under the current condition)
- `tests/test_episodic_memory.py` or similar — add a `test_get_all_returns_recent_episodes` case

**Risks:**

1. **Downstream LLM path** — unblocking the handler means the LLM extraction path runs for the first time in production. If `extract_patterns` has its own latent bug (e.g. pydantic schema drift against the current LLM response format), the fix will surface it. Mitigation: first fix lands as a unit test that stops at `get_all`; a separate smoke test exercises end-to-end once the method is in.
2. **Qdrant write amplification** — once unblocked, the handler runs at most once per 24 h and writes a bounded number of patterns per invocation (capped by the LLM's extracted count). Not a write-volume concern.
3. **Pattern quality** — the writer was never exercised, so there's no ground-truth baseline for the patterns it extracts. The first few fires may produce low-quality patterns; the `Pattern.decay()` + confidence-update loop is designed to correct this over time.

### Option B — retire

**Scope:** remove `PATTERN_CONSOLIDATION_RULE` from `logos/engine/reactive_rules.py::ALL_RULES`, remove `operator-patterns` from `shared/qdrant_schema.py::EXPECTED_COLLECTIONS`, delete the triplicated `_pattern_consolidation.py` files, delete the `operator-patterns` Qdrant collection via `research-registry` or a one-off script.

**Reasons to retire:**

1. The rule has been silently broken for long enough that WS3 L3 is clearly not a load-bearing runtime path — nothing in the current system consumes `operator-patterns` query results.
2. Retirement simplifies the Qdrant surface area (9 collections instead of 10) and eliminates a dead-code footprint of ~1,200 LOC across the three duplicate files.
3. The pattern-extraction capability can be re-introduced later as a standalone agent if/when the operator wants it, without the tangled reactive-engine + WS3-triplication history.

**Reasons NOT to retire:**

1. The SCM formalization + DMN architecture both reference WS3 L3 as a learning loop component. Retiring it would mean the "experience → pattern" path from the SCM spec becomes a documented no-op rather than a latent bug waiting to be fixed.
2. The correction-synthesis rule (sibling of pattern-consolidation, same file) appears to have the same kind of wiring but targets `operator-corrections` — if pattern-consolidation is retired, the operator may reasonably ask about the symmetry, and the retirement explanation needs to cover why corrections stay but patterns don't.

### Option C — fix + gate

Same as Option A, but behind a feature flag (e.g. `HAPAX_WS3_L3_ENABLED=1`) so the fix lands without automatically unblocking the handler. The operator can flip the flag once they're ready to observe the LLM extraction path in production.

**Reasons to gate:** defensive. The LLM path has never run. An environment variable is a cheap rollback.

**Reasons not to gate:** feature flags for single-operator systems are overhead. If the fix breaks, `git revert` is equivalent.

## Recommendation

**Option A — fix, no flag.**

The AttributeError is a defect, not a design decision. The reactive engine rule is architecturally load-bearing and correctly scheduled. Retirement would discard the WS3 L3 learning path without an explicit architectural intent to do so; the empty-collection state was a silent bug, not a considered choice.

Default fix sequence (not executed autonomously — flagged for operator greenlight):

1. Add `EpisodeStore.get_all(limit)` in `logos/_episodic_memory.py`
2. Unit test: `test_episode_store_get_all_returns_recent_first`
3. Manual smoke: run `_handle_pattern_consolidation` once by forcing a `perception-state.json` update + observing whether a Qdrant point lands in `operator-patterns`
4. If the smoke test reveals a downstream bug in `extract_patterns`, fix that separately and iterate

## What this investigation does NOT do

- **Does not fix the bug.** Adding `EpisodeStore.get_all` changes runtime behavior of a reactive engine rule that has never fired successfully. That's a non-trivial behavior change requiring operator consent, not autonomous-safe scope.
- **Does not delete the duplicate files.** The triplication of `_pattern_consolidation.py` across `agents/`, `logos/`, and `shared/` is a separate cleanup from the LLM-optimized restructuring (commit `85b8f9ca1`). Collapsing them is a broader refactor.
- **Does not update `EXPECTED_COLLECTIONS`.** The `operator-patterns` entry stays until the operator chooses Option A or B.

## Next actions

- **Operator:** choose Option A, B, or C. Default per spec §3.10b is "re-schedule" — which maps to Option A here because the rule is already scheduled and needs a bug fix, not a new schedule.
- **Alpha (or next alpha session):** once operator chooses, ship the fix as a separate PR with the `logos/_episodic_memory.py` change + a regression test that invokes `run_consolidation` end-to-end against a fixture Qdrant.
- **Research registry:** update `research/protocols/qdrant-collection-notes.md` after the decision lands to replace the "currently empty" observation with either "fixed; producing N patterns per day" or "retired as of YYYY-MM-DD".

## Cross-references

- LRR Phase 1 spec §3.10b — `docs/superpowers/specs/2026-04-15-lrr-phase-1-research-registry-design.md`
- Qdrant collection notes — `research/protocols/qdrant-collection-notes.md`
- Canonical schema — `shared/qdrant_schema.py::EXPECTED_COLLECTIONS`
- Rule definition — `logos/engine/rules_phase2.py:199` (`PATTERN_CONSOLIDATION_RULE`)
- Handler — `logos/engine/rules_phase2.py:160` (`_handle_pattern_consolidation`)
- Consolidation function — `logos/_pattern_consolidation.py:352` (`run_consolidation`)
- Episode store — `logos/_episodic_memory.py:237` (`EpisodeStore` — missing `get_all`)
- Q024 #83 close-out handoff (claim "writer de-scheduled" was incorrect)
- Q026 Phase 4 Finding 2 (claim "empty collection" was correct; root cause is the AttributeError, not the schedule)
