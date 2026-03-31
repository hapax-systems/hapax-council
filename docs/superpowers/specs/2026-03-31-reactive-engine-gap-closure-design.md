# Reactive Engine Gap Closure — Design Spec

**Date:** 2026-03-31
**Scope:** `logos/engine/`, `logos/api/routes/stimmung.py`, `tests/`
**Trigger:** Full pipeline audit (epsilon session) identified 4 bugs, 3 dead rules, 6 error-handling gaps, and significant test coverage holes.

## Phase 1: Bug Fixes

### B1 — Fix `generate_rule_description` (unblock affordance pipeline)

**Problem:** `rule_capability.py:39` accesses `rule.subdirectories`, which doesn't exist on `Rule`. `AttributeError` silently caught every event. Affordance pipeline permanently dead.

**Fix:** Replace phantom `rule.subdirectories` with `rule.description` in `generate_rule_description()`. The description string already carries the right semantic signal for vector indexing. No new field on `Rule`.

```python
def generate_rule_description(rule: Rule) -> str:
    phase_label = _PHASE_LABEL.get(rule.phase, "Unknown phase")
    return (
        f"Reactive rule: {rule.description}. "
        f"{phase_label}. "
        f"Produces downstream actions when trigger conditions are met."
    )
```

**Files:** `logos/engine/rule_capability.py`, `tests/test_affordance_migration.py`

### B2 — Fix correction synthesis trigger (dead rule)

**Problem:** `CORRECTION_SYNTHESIS_RULE` watches `activity-correction.json` written to `/dev/shm/hapax-compositor/`, which is not in the engine's watch paths. Rule never fires.

**Fix:** After writing the shm file in the studio endpoint, also write a sentinel `correction-pending.json` to `PROFILES_DIR`. Update the filter to match this sentinel.

**Files:** `logos/api/routes/studio.py`, `logos/engine/rules_phase2.py`

### B3 — Remove dead audio archive sidecar rule

**Problem:** `AUDIO_ARCHIVE_SIDECAR_RULE` watches a path not in the engine's watch list. Handler is a no-op. Archival pipeline disabled.

**Fix:** Remove from `ALL_RULES`. Keep code with comment for re-enablement. Update test expectations.

**Files:** `logos/engine/reactive_rules.py`, `tests/test_audio_reactive_rules.py`

### B4 — Wire ignore_fn into phase-2 actions

**Problem:** `ignore_fn` never passed to phase-2 handlers via `action.args`. Designed but never wired.

**Fix:** In `_handle_change`, after `evaluate_rules` and before `executor.execute`, inject `self.ignore_fn` into `action.args` for actions whose handler accepts the `ignore_fn` keyword.

**Files:** `logos/engine/__init__.py`

## Phase 2: Dead Code & Stale Interfaces

### Stimmung API fix

**Problem:** `_build_dimensions` reads flat keys but state.json has nested `{"value": float, "trend": str, "freshness_s": float}` dicts. Obsidian plugin receives wrong data.

**Fix:** Parse nested dict structure with fallback for flat floats.

**Files:** `logos/api/routes/stimmung.py`

### Phone health profiler bridge

**Problem:** Handler logs only. Rule description says "profiler bridge" but nothing is wired.

**Fix:** Wire `profiler_sources.read_phone_health_summary()` into the handler. Update description.

**Files:** `logos/engine/rules_phase0.py`

## Phase 3: Error Handling Hardening

### 3.1 — Widen evaluate_rules exception tuple
Change `(ValueError, KeyError, TypeError, OSError)` to `except Exception` in both `trigger_filter` and `produce` catch blocks. Prevents rule evaluation abort on `AttributeError` or `RuntimeError`.

**Files:** `logos/engine/rules.py`

### 3.2 — Fix presence/consent TOCTOU
Read file once in filter, stash in module-level var. Produce consumes stashed data. Same pattern for both rules. Eliminates double-read between filter and produce.

**Files:** `logos/engine/rules_phase0.py`

### 3.3 — Add biometric lock
Create `_biometric_lock = threading.Lock()` and guard `_last_stress_elevated` reads/writes.

**Files:** `logos/engine/rules_phase0.py`

### 3.4 — Guard audio CLAP ImportError
Add same `try/except ImportError` pattern as `_handle_rag_ingest`.

**Files:** `logos/engine/rules_phase1.py`

### 3.5 — Guard watcher _fire against stopped loop
Wrap `run_coroutine_threadsafe` in `try/except RuntimeError`.

**Files:** `logos/engine/watcher.py`

### 3.6 — Fix QuietWindowScheduler consume-before-execute
Move `consume()` after successful handler execution. On failure, dirty paths remain for retry.

**Files:** `logos/engine/rules_phase2.py`

## Phase 4: Test Coverage

New test functions for:
1. Phase gating (stimmung + presence → strip phases 1+2)
2. `_handle_change` happy path (counters, history, audit)
3. Presence/consent/biometric/phone handlers
4. `_AuditLog` (write, rotation, cleanup)
5. `/api/engine/audit` endpoint
6. Env var overrides (`_env_int`, `_env_float`)
7. Fix `test_engine_novelty.py` to import from source
8. Fix `test_affordance_migration.py` to use real Rule objects
