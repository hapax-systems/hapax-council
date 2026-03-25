# Perceptual System Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 20 verified bugs and robustness issues across the perception–stimmung–apperception–visual-layer–GQI stack.

**Architecture:** Six batches ordered by dependency and blast radius. Each batch is one commit. Pure-function fixes first, safety/robustness second, interconnected cascade changes third, visual behavior fourth, highest-blast-radius stimmung thresholds fifth, voice context sixth.

**Tech Stack:** Python 3.12+, Pydantic v2, pytest, unittest.mock, asyncio. Project conventions: `uv run pytest tests/ -q`, `uv run ruff check .`, `uv run ruff format .`.

**Spec:** `docs/superpowers/specs/2026-03-24-perceptual-system-hardening.md`

**Baseline:** 239 tests passing. Run `uv run pytest tests/test_stimmung.py tests/test_apperception.py tests/test_visual_layer_state.py tests/test_visual_layer_aggregator.py tests/test_perception_ring.py -q` to verify before starting.

---

## Batch 1: Pure Functions (no state, no I/O)

### Task 1: Fix `trend()` catastrophic cancellation (C3)

**Files:**
- Modify: `agents/hapax_voice/perception_ring.py:81-92`
- Test: `tests/test_perception_ring.py` (existing file, add tests)

- [ ] **Step 1: Write failing tests**

Add to `tests/test_perception_ring.py`:

```python
class TestTrendNumericalStability:
    """C3: trend() must be numerically stable with POSIX timestamps."""

    def test_trend_with_posix_timestamps_rising(self):
        """20 points at t~1.7e9 with known rising linear trend."""
        ring = PerceptionRing(maxlen=20)
        base_ts = 1_711_324_800.0  # 2024-03-25 00:00:00 UTC
        for i in range(20):
            ring.push({"ts": base_ts + i * 2.5, "flow_score": 0.3 + i * 0.01})
        slope = ring.trend("flow_score", window_s=60.0)
        # 0.01 per 2.5s = 0.004 per second
        assert 0.003 < slope < 0.005, f"Expected ~0.004, got {slope}"

    def test_trend_with_posix_timestamps_falling(self):
        ring = PerceptionRing(maxlen=20)
        base_ts = 1_711_324_800.0
        for i in range(20):
            ring.push({"ts": base_ts + i * 2.5, "flow_score": 0.8 - i * 0.02})
        slope = ring.trend("flow_score", window_s=60.0)
        assert -0.009 < slope < -0.007, f"Expected ~-0.008, got {slope}"

    def test_trend_with_posix_timestamps_flat(self):
        ring = PerceptionRing(maxlen=20)
        base_ts = 1_711_324_800.0
        for i in range(20):
            ring.push({"ts": base_ts + i * 2.5, "flow_score": 0.5})
        slope = ring.trend("flow_score", window_s=60.0)
        assert abs(slope) < 1e-10, f"Expected ~0, got {slope}"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_perception_ring.py::TestTrendNumericalStability -v`
Expected: `_rising` and `_falling` fail with incorrect slopes.

- [ ] **Step 3: Fix trend() — center timestamps**

In `agents/hapax_voice/perception_ring.py`, replace lines 81-92:

```python
        # Simple linear regression (slope) with centered timestamps
        # to avoid catastrophic cancellation with large POSIX values.
        n = len(values)
        ts = [t for t, _ in values]
        vs = [v for _, v in values]
        t_mean = sum(ts) / n

        centered = [t - t_mean for t in ts]
        sum_ct = sum(centered)
        sum_cv = sum(c * v for c, v in zip(centered, vs))
        sum_cc = sum(c * c for c in centered)

        denom = n * sum_cc - sum_ct * sum_ct
        if abs(denom) < 1e-12:
            return 0.0

        return (n * sum_cv - sum_ct * sum(vs)) / denom
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_perception_ring.py -v`
Expected: All pass.

---

### Task 2: Fix `Event[T].emit()` subscriber snapshot (H5)

**Files:**
- Modify: `agents/hapax_voice/primitives.py:127`
- Test: `tests/hapax_voice/test_primitives.py` (create)

- [ ] **Step 1: Create test file**

Check where voice tests live: `ls tests/hapax_voice/ 2>/dev/null || mkdir -p tests/hapax_voice`

Create `tests/hapax_voice/test_primitives.py`:

```python
"""Tests for hapax_voice.primitives — Behavior, Event, Stamped."""

from agents.hapax_voice.primitives import Event


class TestEventEmit:
    def test_self_unsubscribe_does_not_skip_subsequent(self):
        """H5: self-unsubscribing during emit must not skip later subscribers."""
        event: Event[str] = Event()
        calls: list[str] = []

        def sub_a(ts: float, val: str) -> None:
            calls.append("a")
            unsub_a()

        unsub_a = event.subscribe(sub_a)
        event.subscribe(lambda ts, val: calls.append("b"))
        event.subscribe(lambda ts, val: calls.append("c"))

        event.emit(1.0, "test")
        assert calls == ["a", "b", "c"], f"Expected all three, got {calls}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/hapax_voice/test_primitives.py -v`
Expected: FAIL.

- [ ] **Step 3: Fix emit()**

In `agents/hapax_voice/primitives.py`, line 127, change `for cb in self._subscribers:` to `for cb in list(self._subscribers):`.

- [ ] **Step 4: Run test**

Run: `uv run pytest tests/hapax_voice/test_primitives.py -v`
Expected: PASS.

---

### Task 3: Simplify IGNORE branch (H7) + fix effort hold counter (M5)

**Files:**
- Modify: `agents/hapax_voice/grounding_ledger.py:170-180,274-275`
- Test: `tests/hapax_voice/test_grounding_ledger.py` (create)

- [ ] **Step 1: Write failing tests**

Create `tests/hapax_voice/test_grounding_ledger.py`:

```python
"""Tests for grounding ledger — H7 (IGNORE) and M5 (effort hold)."""

from agents.hapax_voice.grounding_ledger import GroundingLedger


class TestIgnoreBranch:
    def test_low_concern_ignore_grounds(self):
        ledger = GroundingLedger()
        ledger.add_du(1, "test statement", concern_overlap=0.1)
        result = ledger.update_from_acceptance("IGNORE", concern_overlap=0.1)
        assert result == "advance"

    def test_high_concern_ignore_ungrounds(self):
        ledger = GroundingLedger()
        ledger.add_du(1, "test statement", concern_overlap=0.8)
        result = ledger.update_from_acceptance("IGNORE", concern_overlap=0.8)
        assert result == "ungrounded_caution"

    def test_medium_concern_ignore_ungrounds(self):
        ledger = GroundingLedger()
        ledger.add_du(1, "test statement", concern_overlap=0.5)
        result = ledger.update_from_acceptance("IGNORE", concern_overlap=0.5)
        assert result == "ungrounded_caution"


class TestEffortHoldCounter:
    def test_same_rank_preserves_hold_counter(self):
        ledger = GroundingLedger()
        ledger.effort_calibration(activation=0.5)  # BASELINE
        ledger.effort_calibration(activation=0.9)  # ELABORATIVE
        ledger.effort_calibration(activation=0.2)  # held (attempt 1)
        e4 = ledger.effort_calibration(activation=0.2)  # should de-escalate
        assert e4.level_name == "EFFICIENT"

    def test_escalation_resets_hold_counter(self):
        ledger = GroundingLedger()
        ledger.effort_calibration(activation=0.9)  # ELABORATIVE
        ledger.effort_calibration(activation=0.2)  # held (attempt 1)
        ledger.effort_calibration(activation=0.9)  # escalation resets
        e = ledger.effort_calibration(activation=0.2)  # held again (attempt 1)
        assert e.level_name == "ELABORATIVE"
```

- [ ] **Step 2: Run tests to verify failures**

Run: `uv run pytest tests/hapax_voice/test_grounding_ledger.py -v`
Expected: `test_same_rank_preserves_hold_counter` fails.

- [ ] **Step 3: Fix IGNORE branch**

In `agents/hapax_voice/grounding_ledger.py`, replace lines 170-180:

```python
        # IGNORE: grounding depends on concern overlap only
        if acceptance == "IGNORE":
            if concern_overlap < 0.3:
                du.state = DUState.GROUNDED
                return "advance"
            du.state = DUState.UNGROUNDED
            return "ungrounded_caution"
```

- [ ] **Step 4: Fix effort hold counter**

In `agents/hapax_voice/grounding_ledger.py`, replace lines 274-275 (`else: self._effort_hold_turns = 0`) with:

```python
        else:
            # Same rank: preserve hold counter for in-progress de-escalation
            pass
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/hapax_voice/test_grounding_ledger.py -v`
Expected: All pass.

---

### Task 4: Type-safe behavior value access (N3)

**Files:**
- Modify: `agents/hapax_voice/perception.py:270-273` and all `_bval` callers

- [ ] **Step 1: Replace `_bval` with typed accessors**

Replace lines 270-273 with four methods: `_fval`, `_sval`, `_boolval`, `_optval` (see spec section 3.21 for exact signatures).

- [ ] **Step 2: Update all callers**

Use `grep -n '_bval' agents/hapax_voice/perception.py` to find all sites. Replace each with the appropriate typed accessor:
- `bool(self._bval(...))` → `self._boolval(...)`
- `str(self._bval(...))` → `self._sval(...)`
- `int(self._bval(...))` → `int(self._fval(...))`
- `self._bval("presence_state", None)` → `self._optval("presence_state")`

- [ ] **Step 3: Run ruff + tests**

Run: `uv run ruff check agents/hapax_voice/perception.py && uv run pytest tests/ -q --tb=short -x`
Expected: Clean.

- [ ] **Step 4: Commit Batch 1**

```bash
git add agents/hapax_voice/perception_ring.py agents/hapax_voice/primitives.py \
  agents/hapax_voice/grounding_ledger.py agents/hapax_voice/perception.py \
  tests/test_perception_ring.py tests/hapax_voice/test_primitives.py \
  tests/hapax_voice/test_grounding_ledger.py
git commit -m "fix: batch 1 — pure function fixes (C3, H5, H7, M5, N3)"
```

---

## Batch 2: Safety and Robustness

### Task 5: Safe casts + fallback write + deque + circadian (H1, H4, N1)

**Files:**
- Modify: `agents/hapax_voice/_perception_state_writer.py:32,302-306,366-370`

- [ ] **Step 1: Add `_safe_int` and `_safe_float` helpers** after imports.
- [ ] **Step 2: Replace `int()`/`float()` casts** at lines 302, 304, 305, 366, 368 with safe versions.
- [ ] **Step 3: Add outer try/except** around state dict construction with minimal fallback write.
- [ ] **Step 4: Add `circadian_alignment`** to state dict (N1).
- [ ] **Step 5: Replace `list` with `deque(maxlen=5)`** at line 32 (H4). Update `_get_live_content` to not mutate the deque.
- [ ] **Step 6: Run ruff + tests.**

### Task 6: Fix `replace_backend` availability check (H2)

**Files:**
- Modify: `agents/hapax_voice/perception.py:300-313`

- [ ] **Step 1: Check availability before stopping old backend** (see spec 3.8).
- [ ] **Step 2: Run tests.**

### Task 7: WS3 retry on Qdrant failure (C2)

**Files:**
- Modify: `agents/visual_layer_aggregator.py:1096-1117`

- [ ] **Step 1: Add retry attributes** (`_ws3_retries`, `_ws3_last_attempt`) to `__init__`.
- [ ] **Step 2: Rewrite `_init_ws3`** with 60s interval, max 5 retries, flag set only on success (see spec 3.2).
- [ ] **Step 3: Run tests.**

### Task 8: Wall-clock time for stimmung timestamp (N2)

**Files:**
- Modify: `shared/stimmung.py:344`
- Test: `tests/test_stimmung.py` (add test)

- [ ] **Step 1: Add test** verifying `snapshot().timestamp > 1_000_000_000`.
- [ ] **Step 2: Change line 344** from `timestamp=now` to `timestamp=time.time()`.
- [ ] **Step 3: Run tests.**

- [ ] **Step 4: Commit Batch 2**

```bash
git add agents/hapax_voice/_perception_state_writer.py agents/hapax_voice/perception.py \
  agents/visual_layer_aggregator.py shared/stimmung.py tests/test_stimmung.py
git commit -m "fix: batch 2 — safety and robustness (H1, H2, H4, C2, N1, N2)"
```

---

## Batch 3: Apperception Cascade

### Task 9: Rumination valence (C5) + retention gate (C4) + temporal dedup (C6)

**Files:**
- Modify: `shared/apperception.py:537-548,469-486`
- Modify: `shared/apperception_tick.py:82-151`
- Test: `tests/test_apperception.py` (add tests)

- [ ] **Step 1: Write rumination test (C5)** — verify positive-valence `performance` events don't trigger gate.
- [ ] **Step 2: Write retention test (C4)** — high-signal depth-4 retained, low-signal filtered.
- [ ] **Step 3: Run tests to verify failures.**
- [ ] **Step 4: Fix C5** — move `_step_valence` before `_check_rumination`, single call for all sources (lines 537-548).
- [ ] **Step 5: Fix C4** — add depth-4 escape: `relevance > 0.5 and abs(valence) > 0.3` (lines 469-486).
- [ ] **Step 6: Fix C6** — read `TEMPORAL_FILE` once in `_collect_events`, reuse for both surprise and staleness (lines 82-151).
- [ ] **Step 7: Run all apperception tests.**
- [ ] **Step 8: Run full baseline.**

- [ ] **Step 9: Commit Batch 3**

```bash
git add shared/apperception.py shared/apperception_tick.py tests/test_apperception.py
git commit -m "fix: batch 3 — apperception cascade (C5, C4, C6)"
```

---

## Batch 4: State Machine and Display

### Task 10: De-escalation timer (M4) + PERFORMATIVE hysteresis (M6)

**Files:**
- Modify: `agents/visual_layer_state.py:458-476`
- Test: `tests/test_visual_layer_state.py` (add tests)

- [ ] **Step 1: Write timer test (M4)** — same-state ticks do NOT reset de-escalation timer.
- [ ] **Step 2: Write PERFORMATIVE tests (M6)** — holds 3s against ALERT, exits after sustained ALERT.
- [ ] **Step 3: Run tests to verify failures.**
- [ ] **Step 4: Fix M4** — remove `self._deescalation_timer = now` from same-state branch (line 460).
- [ ] **Step 5: Fix M6** — add `_performative_enter_time`, hold PERFORMATIVE for 3s against ALERT (lines 474-476).
- [ ] **Step 6: Run tests.**

### Task 11: Readiness (H6) + cached perception (M2) + epoch counter (M1)

**Files:**
- Modify: `agents/visual_layer_aggregator.py:817-818,1884-1888,2089-2097`

- [ ] **Step 1: Fix H6** — `_ambient_fetch_done: bool` flag instead of `== 0.0` check.
- [ ] **Step 2: Fix M2** — `_infer_activity` uses `self._last_perception_data` instead of re-reading disk.
- [ ] **Step 3: Fix M1** — add `_epoch: int` counter, include in state + stimmung JSON writes.
- [ ] **Step 4: Run tests.**

- [ ] **Step 5: Commit Batch 4**

```bash
git add agents/visual_layer_state.py agents/visual_layer_aggregator.py \
  tests/test_visual_layer_state.py
git commit -m "fix: batch 4 — state machine and display (M4, M6, H6, M2, M1)"
```

---

## Batch 5: Stimmung Thresholds

### Task 12: Separate stance thresholds per dimension class (C1)

**Files:**
- Modify: `shared/stimmung.py:130-134,366-390`
- Test: `tests/test_stimmung.py` (add tests)

- [ ] **Step 1: Write threshold tests** — biometric raw=1.0 → DEGRADED (not CRITICAL), cognitive raw=1.0 → CAUTIOUS (not DEGRADED), infra unchanged.
- [ ] **Step 2: Run tests to verify failures.**
- [ ] **Step 3: Add per-class threshold tuples** after line 134: `_INFRA_THRESHOLDS = (0.30, 0.60, 0.85)`, `_BIOMETRIC_THRESHOLDS = (0.15, 0.40, 1.01)`, `_COGNITIVE_THRESHOLDS = (0.15, 1.01, 1.01)`.
- [ ] **Step 4: Rewrite `_compute_stance`** — look up thresholds by dimension class, compare effective values against class-specific thresholds. Use `_STANCE_ORDER` dict for stance comparison since `Stance` is a `StrEnum`.
- [ ] **Step 5: Run tests.**
- [ ] **Step 6: Run full baseline.**

- [ ] **Step 7: Commit Batch 5**

```bash
git add shared/stimmung.py tests/test_stimmung.py
git commit -m "fix: batch 5 — separate stance thresholds per dimension class (C1)"
```

---

## Batch 6: Context Rendering

### Task 13: Snapshot isolation for phenomenal context render (M3)

**Files:**
- Modify: `agents/hapax_voice/phenomenal_context.py:50-102,348-350`

- [ ] **Step 1: Remove module-level cache globals** (lines 348-350).
- [ ] **Step 2: Add `_read_json(path)` helper.**
- [ ] **Step 3: Refactor `render()`** — read stimmung/temporal/apperception files once at top, pass data to each `_render_*` function.
- [ ] **Step 4: Update `_render_*` functions** to accept data as parameter instead of reading from disk.
- [ ] **Step 5: Run ruff + tests.**

- [ ] **Step 6: Commit Batch 6**

```bash
git add agents/hapax_voice/phenomenal_context.py
git commit -m "fix: batch 6 — snapshot isolation for phenomenal context (M3)"
```

---

## Final Verification

- [ ] **Run full test suite:** `uv run pytest tests/ -q --tb=short`
- [ ] **Run ruff:** `uv run ruff check . && uv run ruff format --check .`
- [ ] **Run pyright** on all modified files.
