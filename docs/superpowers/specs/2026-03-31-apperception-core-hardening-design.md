# Apperception Core Pipeline Hardening — Design Spec

**Date**: 2026-03-31
**Sub-project**: 1 of 3 (Core Hardening → Event Source Completion → UI + Observability)
**Scope**: Wire ApperceptionStore, tick liveness signal, unify `_read_apperception_block`, fix dead fields, health monitor integration, I/O layer tests.

## Context

Audit of the apperception pipeline (2026-03-31) identified 6 gap categories. This spec addresses the foundational correctness and robustness gaps that must land before event source completion (sub-project 2) or UI expansion (sub-project 3).

The pipeline flows: Event Sources → CascadeEvent → 7-step ApperceptionCascade → SelfModel update → /dev/shm write → consumers. The cascade logic is well-tested (94% coverage, 138 tests). The gaps are in I/O, persistence, observability, and code hygiene.

## A. Wire ApperceptionStore

### Current State

`ApperceptionStore` is defined in `shared/apperception.py` (lines 602–712) with `.add()`, `.flush()`, `.search()`, and `.ensure_collection()`. Nothing instantiates it. Apperceptions produced every 3–5s are never persisted to Qdrant.

### Changes

**`shared/apperception_tick.py`** — `ApperceptionTick`:

1. Import `ApperceptionStore` from `shared.apperception`.
2. In `__init__()`:
   - Create `self._store = ApperceptionStore()`
   - Call `self._store.ensure_collection()` wrapped in try/except (best-effort, logged)
   - Add `self._last_flush: float = 0.0`
3. In `tick()`, after the cascade loop:
   - For each retained result, call `self._store.add(result)` (already inside the for-loop, just add after the action check)
   - After the loop, check `time.monotonic() - self._last_flush >= 60.0`. If true, call `self._store.flush()` and update `_last_flush`.
4. In `save_model()`:
   - Call `self._store.flush()` before persisting the model (drain pending on shutdown).

**`agents/_apperception_tick.py`** — Mirror the same changes, importing from `agents._apperception`.

### Invariants

- Store is best-effort. Embedding or Qdrant failures are logged and skipped — the tick loop never blocks or crashes on store failures.
- Flush cadence (60s) is independent of save cadence (300s).
- Qdrant collection: `hapax-apperceptions`, 768-dim cosine vectors.

## B. Tick Liveness Signal

### Current State

SHM payload: `{self_model, pending_actions, timestamp}`. Consumers check timestamp staleness (>30s → empty). If the tick process freezes, consumers silently degrade — voice LLM trusts last-known coherence.

### Changes

**`shared/apperception_tick.py`** — `ApperceptionTick`:

1. Add `self._tick_seq: int = 0` in `__init__()`.
2. In `tick()`, increment `self._tick_seq` at the start.
3. In `_write_shm()`, add to payload:
   ```python
   "tick_seq": self._tick_seq,
   "events_this_tick": event_count,  # total events processed, not just retained actions
   ```
   Update `_write_shm` signature: `_write_shm(self, pending_actions: list[str], event_count: int) -> None`.
4. In `tick()`, pass `event_count=len(events)` to `_write_shm()`.

**`agents/_apperception_tick.py`** — Mirror.

### Consumer Contract

New fields are additive — existing consumers ignore unknown keys. The health monitor (Section E) uses `tick_seq` for definitive liveness. `_read_apperception_block()` does NOT change for this section (timestamp staleness is sufficient for prompt injection).

## C. Unify `_read_apperception_block`

### Current State

Three identical copies:
- `shared/operator.py` (lines 228–306)
- `logos/_operator.py` (lines 184–247)
- `agents/drift_detector/shm_readers.py` (lines 65–128)

### Changes

1. Create **`shared/apperception_shm.py`** — a zero-dependency module (stdlib only: json, time, pathlib):
   ```python
   """Read apperception state from /dev/shm for prompt injection.

   Zero external dependencies — safe to import from any module
   (shared/, agents/, logos/) without config coupling.
   """

   def read_apperception_block() -> str:
       """Read self-band state from /dev/shm and format for prompt injection."""
       # ... existing logic from drift_detector/shm_readers.py ...
   ```

2. **`shared/operator.py`**: Replace `_read_apperception_block()` with import:
   ```python
   from shared.apperception_shm import read_apperception_block as _read_apperception_block
   ```

3. **`logos/_operator.py`**: Same import replacement.

4. **`agents/drift_detector/shm_readers.py`**: Replace inline function with import:
   ```python
   from shared.apperception_shm import read_apperception_block
   ```

5. **`agents/_operator.py`**: Same import replacement (if it has the function).

### Why Not agents/_apperception_shm.py?

The vendoring separation exists because `shared.config` has Qdrant/embedding coupling. `apperception_shm.py` has zero config imports — it reads a JSON file and formats a string. No vendoring needed.

## D. Fix Dead Fields

### `SelfDimension.current_assessment`

**Problem**: Field defined (line 79), serialized in `to_dict()`, but never written — always empty string.

**Changes**:
1. **`shared/apperception.py`**: Remove `current_assessment` from `SelfDimension`. Remove from `to_dict()` and `from_dict()`. In `from_dict()`, silently ignore the key if present in old cache data (backwards compat).
2. **`agents/_apperception.py`**: Mirror.
3. **`shared/apperception_shm.py`**: Don't read `current_assessment` (already won't be written).
4. **`logos/api/routes/flow.py`**: Remove `assessment` field from dimension metrics dict (line ~327).
5. **`hapax-logos/src-tauri/src/commands/system_flow.rs`**: Remove `current_assessment` parsing (line ~197).
6. **`hapax-logos/src/pages/FlowPage.tsx`**: No change needed (doesn't render assessment).

### Clock Usage Documentation

Add comment in `apperception_tick.py`:
```python
# _last_save and _last_flush use time.monotonic() (interval measurement).
# Event timestamps and SHM payload use time.time() (wall clock for consumers).
# These serve different purposes and should NOT be unified.
```

## E. Health Monitor Integration

### Current State

Health monitor: 25 check modules in `agents/health_monitor/checks/`, registered via `@check_group` decorator, producing `CheckResult` (name, group, status, message, detail, remediation, tier).

### Changes

Create **`agents/health_monitor/checks/apperception.py`**:

```python
@check_group("perception")
async def check_apperception() -> list[CheckResult]:
    results = []

    # 1. Tick liveness
    path = Path("/dev/shm/hapax-apperception/self-band.json")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        age = time.time() - raw.get("timestamp", 0)
        if age < 30:
            results.append(CheckResult(
                name="apperception_tick",
                group="perception",
                status=Status.HEALTHY,
                message=f"Tick alive ({age:.0f}s ago)",
            ))
        elif age < 120:
            results.append(CheckResult(
                name="apperception_tick",
                group="perception",
                status=Status.DEGRADED,
                message=f"Tick stale ({age:.0f}s)",
                remediation="Check visual-layer-aggregator service",
            ))
        else:
            results.append(CheckResult(
                name="apperception_tick",
                group="perception",
                status=Status.FAILED,
                message=f"Tick dead ({age:.0f}s)",
                remediation="Restart visual-layer-aggregator: systemctl --user restart visual-layer-aggregator",
            ))
    except FileNotFoundError:
        results.append(CheckResult(
            name="apperception_tick",
            group="perception",
            status=Status.FAILED,
            message="Self-band file missing",
            remediation="Restart visual-layer-aggregator: systemctl --user restart visual-layer-aggregator",
        ))
    except Exception as e:
        results.append(CheckResult(
            name="apperception_tick",
            group="perception",
            status=Status.DEGRADED,
            message=f"Could not read self-band: {e}",
        ))

    # 2. Coherence check (only if file readable and fresh)
    try:
        if age < 30:
            coherence = raw.get("self_model", {}).get("coherence", 0.7)
            if coherence > 0.3:
                results.append(CheckResult(
                    name="apperception_coherence",
                    group="perception",
                    status=Status.HEALTHY,
                    message=f"Coherence {coherence:.2f}",
                ))
            elif coherence > 0.15:
                results.append(CheckResult(
                    name="apperception_coherence",
                    group="perception",
                    status=Status.DEGRADED,
                    message=f"Coherence low ({coherence:.2f}), near floor",
                    remediation="Review recent corrections and system stability",
                ))
            else:
                results.append(CheckResult(
                    name="apperception_coherence",
                    group="perception",
                    status=Status.FAILED,
                    message=f"Coherence at floor ({coherence:.2f}) — shame spiral guard active",
                    remediation="Self-model collapsed. Check for rapid negative corrections",
                ))
    except NameError:
        pass  # raw/age not defined if file read failed — skip coherence check

    return results
```

Register the import in `agents/health_monitor/checks/__init__.py`.

## F. Test I/O Layer

### New File: `tests/test_apperception_tick_io.py`

19 tests across 5 categories. All use `tmp_path` with monkeypatched paths. Mocks only for Qdrant and embedding (external services).

#### F.1 Tick Loop (5 tests)
- `test_tick_full_cycle` — Synthetic temporal + stimmung SHM → tick() → verify self-band.json written with correct structure
- `test_tick_multi_accumulates` — 3 ticks with different events → dimensions accumulate
- `test_tick_save_interval` — Verify save_model() fires after 300s (mock monotonic)
- `test_tick_store_flush_cadence` — Verify store.flush() fires after 60s
- `test_tick_store_add_on_retain` — Correction event → retained → store.add() called

#### F.2 SHM Write (4 tests)
- `test_shm_payload_structure` — Verify all 5 fields present (self_model, pending_actions, timestamp, tick_seq, events_this_tick)
- `test_shm_atomic_write` — Verify .tmp → rename pattern (no partial reads)
- `test_shm_creates_directory` — Verify mkdir on first write
- `test_shm_oserror_graceful` — Read-only dir → no crash, debug log

#### F.3 Model Persistence (3 tests)
- `test_model_save_load_roundtrip` — Save → new instance loads → dimensions preserved
- `test_model_corrupted_cache` — Garbage in cache file → starts fresh
- `test_model_missing_cache` — No cache file → starts fresh

#### F.4 Event Collection Edge Cases (4 tests)
- `test_corrupted_temporal_json` — Invalid JSON → no crash, no events
- `test_missing_correction_file` — Missing file → no crash, no events
- `test_unknown_stimmung_stance` — Stance "weird" → improving=False
- `test_rapid_tick_no_duplicate` — Same correction timestamp twice → only one event

#### F.5 Store Integration (3 tests)
- `test_retained_apperception_queued` — Mock store, verify add() called with Apperception instance
- `test_flush_drains_pending` — Mock store, verify flush() called and pending_count → 0
- `test_shutdown_flushes` — save_model() calls store.flush() before persisting

## File Change Summary

| File | Action |
|------|--------|
| `shared/apperception.py` | Remove `current_assessment` from SelfDimension, to_dict, from_dict |
| `agents/_apperception.py` | Mirror shared/ changes |
| `shared/apperception_tick.py` | Wire store, add liveness fields, update _write_shm signature |
| `agents/_apperception_tick.py` | Mirror shared/ changes |
| `shared/apperception_shm.py` | **NEW** — unified _read_apperception_block |
| `shared/operator.py` | Replace inline function with import |
| `logos/_operator.py` | Replace inline function with import |
| `agents/_operator.py` | Replace inline function with import |
| `agents/drift_detector/shm_readers.py` | Replace inline function with import |
| `agents/health_monitor/checks/apperception.py` | **NEW** — tick liveness + coherence checks |
| `agents/health_monitor/checks/__init__.py` | Register new check module |
| `logos/api/routes/flow.py` | Remove assessment field from dimensions |
| `hapax-logos/src-tauri/src/commands/system_flow.rs` | Remove current_assessment parsing |
| `tests/test_apperception_tick_io.py` | **NEW** — 19 I/O layer tests |
| `tests/test_apperception.py` | Update for removed current_assessment |

## Dependencies

- Sub-project 2 (event source completion) depends on this landing first — the store wiring and liveness signal are prerequisites for the new event sources to be meaningful.
- Sub-project 3 (UI + observability) can partially parallel but the API changes (assessment removal) should land first.

## Out of Scope

- Wiring `cross_resonance`, `pattern_shift`, `performance` event sources (sub-project 2)
- FlowPage detail panel, staleness alerts, frontend enrichment (sub-project 3)
- Qdrant collection migration or schema versioning
