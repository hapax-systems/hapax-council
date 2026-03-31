# Apperception Core Pipeline Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire ApperceptionStore to Qdrant, add tick liveness signal, unify triplicated `_read_apperception_block`, remove dead `current_assessment` field, add health monitor checks, and cover the I/O layer with 19 tests.

**Architecture:** The apperception tick loop (3–5s cadence) runs inside the VLA. Changes touch the tick class (`ApperceptionTick`), a new shared SHM reader module, health monitor checks, and the agents/ vendored mirror. All SHM I/O uses atomic `.tmp` → rename. Store persistence is best-effort (embedding/Qdrant failures logged, never crash the tick loop).

**Tech Stack:** Python 3.12, Pydantic, Qdrant (768-dim cosine), pytest + unittest.mock, fish shell.

**Spec:** `docs/superpowers/specs/2026-03-31-apperception-core-hardening-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `shared/apperception.py` | Modify | Remove `current_assessment` from SelfDimension, to_dict, from_dict |
| `shared/apperception_tick.py` | Modify | Wire store, add liveness fields, update `_write_shm` signature |
| `shared/apperception_shm.py` | **Create** | Unified `read_apperception_block()` — stdlib only |
| `shared/operator.py` | Modify | Replace inline `_read_apperception_block` with import |
| `logos/_operator.py` | Modify | Replace inline `_read_apperception_block` with import |
| `agents/_operator.py` | Modify | Replace inline `_read_apperception_block` with import |
| `agents/drift_detector/shm_readers.py` | Modify | Replace inline `read_apperception_block` with import |
| `agents/_apperception.py` | Modify | Mirror shared/apperception.py changes |
| `agents/_apperception_tick.py` | Modify | Mirror shared/apperception_tick.py changes |
| `agents/health_monitor/checks/apperception.py` | **Create** | Tick liveness + coherence health checks |
| `agents/health_monitor/checks/__init__.py` | Modify | Register apperception check module |
| `logos/api/routes/flow.py` | Modify | Remove `assessment` field from dimension metrics |
| `hapax-logos/src-tauri/src/commands/system_flow.rs` | Modify | Remove `current_assessment` parsing |
| `tests/test_apperception_tick_io.py` | **Create** | 19 I/O layer tests |
| `tests/test_apperception.py` | Modify | Update for removed `current_assessment` |

---

### Task 1: Remove `current_assessment` Dead Field

**Files:**
- Modify: `shared/apperception.py:70-186`
- Modify: `tests/test_apperception.py`

- [ ] **Step 1: Update SelfDimension — remove field**

In `shared/apperception.py`, remove `current_assessment` from class and serialization:

```python
# Line 70-82: Remove current_assessment field
class SelfDimension(BaseModel):
    """Accumulated evidence about one aspect of self-knowledge.

    Dimensions emerge from processing, not predefined. Names are discovered
    through the cascade (e.g. "activity_recognition", "temporal_prediction").
    """

    name: str
    confidence: float = Field(ge=0.05, le=0.95, default=0.5)
    affirming_count: int = 0
    problematizing_count: int = 0
    last_shift_time: float = Field(default_factory=time.time)
```

In `to_dict()` (line 156-173), remove `"current_assessment": d.current_assessment`:

```python
    def to_dict(self) -> dict:
        """Serialize for JSON storage (shm, cache)."""
        return {
            "dimensions": {
                name: {
                    "name": d.name,
                    "confidence": d.confidence,
                    "affirming_count": d.affirming_count,
                    "problematizing_count": d.problematizing_count,
                    "last_shift_time": d.last_shift_time,
                }
                for name, d in self.dimensions.items()
            },
            "recent_observations": list(self.recent_observations),
            "recent_reflections": list(self.recent_reflections),
            "coherence": self.coherence,
        }
```

In `from_dict()` (line 175-186), filter out `current_assessment` from dimension kwargs for backwards compat:

```python
    @classmethod
    def from_dict(cls, data: dict) -> SelfModel:
        """Deserialize from JSON storage."""
        model = cls()
        for name, d in data.get("dimensions", {}).items():
            # Filter unknown keys for backwards compat with old cache
            known_fields = {"name", "confidence", "affirming_count", "problematizing_count", "last_shift_time"}
            filtered = {k: v for k, v in d.items() if k in known_fields}
            model.dimensions[name] = SelfDimension(**filtered)
        for obs in data.get("recent_observations", []):
            model.recent_observations.append(obs)
        for ref in data.get("recent_reflections", []):
            model.recent_reflections.append(ref)
        model.coherence = max(COHERENCE_FLOOR, min(COHERENCE_CEILING, data.get("coherence", 0.7)))
        return model
```

- [ ] **Step 2: Update tests**

Run: `cd hapax-council && uv run pytest tests/test_apperception.py -v -x 2>&1 | head -40`

Fix any test that references `current_assessment`. The serialization roundtrip test should still pass because `from_dict` now filters unknown keys.

- [ ] **Step 3: Run full apperception test suite**

Run: `cd hapax-council && uv run pytest tests/test_apperception*.py -v -x`
Expected: All pass.

- [ ] **Step 4: Mirror to agents/_apperception.py**

Apply the exact same three changes (SelfDimension field removal, to_dict, from_dict) to `agents/_apperception.py`. The only difference: this file imports from `agents._config` instead of `shared.config` — don't change those imports.

- [ ] **Step 5: Remove assessment from flow.py**

In `logos/api/routes/flow.py`, find the dimension metrics dict construction (search for `"assessment"`). Remove the `"assessment"` key:

```python
# Before:
"confidence": dim.get("confidence", 0.0),
"assessment": dim.get("current_assessment", "")[:60],
"affirming": dim.get("affirming_count", 0),

# After:
"confidence": dim.get("confidence", 0.0),
"affirming": dim.get("affirming_count", 0),
```

- [ ] **Step 6: Remove current_assessment from Rust**

In `hapax-logos/src-tauri/src/commands/system_flow.rs`, find the `current_assessment` parsing in the apperception section. Remove the `"assessment"` line from the JSON construction:

```rust
// Before:
apper_dims.insert(name.clone(), serde_json::json!({
    "confidence": d.get("confidence").and_then(|v| v.as_f64()).unwrap_or(0.0),
    "assessment": d.get("current_assessment")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .chars().take(60).collect::<String>(),
    "affirming": d.get("affirming_count").and_then(|v| v.as_u64()).unwrap_or(0),
    "problematizing": d.get("problematizing_count").and_then(|v| v.as_u64()).unwrap_or(0),
}));

// After:
apper_dims.insert(name.clone(), serde_json::json!({
    "confidence": d.get("confidence").and_then(|v| v.as_f64()).unwrap_or(0.0),
    "affirming": d.get("affirming_count").and_then(|v| v.as_u64()).unwrap_or(0),
    "problematizing": d.get("problematizing_count").and_then(|v| v.as_u64()).unwrap_or(0),
}));
```

- [ ] **Step 7: Commit**

```bash
cd hapax-council
git add shared/apperception.py agents/_apperception.py logos/api/routes/flow.py hapax-logos/src-tauri/src/commands/system_flow.rs tests/test_apperception.py
git commit -m "fix(apperception): remove dead current_assessment field from SelfDimension

Field was defined but never written — always empty string. Removed from
model, serialization, API, and Rust command. from_dict filters unknown
keys for backwards compat with old cache files."
```

---

### Task 2: Create Unified `shared/apperception_shm.py`

**Files:**
- Create: `shared/apperception_shm.py`
- Modify: `shared/operator.py:228-306`
- Modify: `logos/_operator.py:184-247`
- Modify: `agents/_operator.py:184-247`
- Modify: `agents/drift_detector/shm_readers.py:65-128`

- [ ] **Step 1: Create the unified module**

Create `shared/apperception_shm.py`:

```python
"""Read apperception state from /dev/shm for prompt injection.

Zero external dependencies — stdlib only (json, time, pathlib).
Safe to import from any module (shared/, agents/, logos/) without
config coupling. This is the canonical implementation; do not duplicate.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

APPERCEPTION_SHM_PATH = Path("/dev/shm/hapax-apperception/self-band.json")
_STALENESS_THRESHOLD = 30  # seconds


def read_apperception_block(path: Path = APPERCEPTION_SHM_PATH) -> str:
    """Read self-band state from /dev/shm and format for prompt injection.

    Returns formatted text block for LLM system prompts. Returns empty
    string if data is missing, stale (>30s), or has no meaningful content.

    Args:
        path: Override for testing. Defaults to /dev/shm path.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        ts = raw.get("timestamp", 0)
        if ts > 0 and (time.time() - ts) > _STALENESS_THRESHOLD:
            return ""

        model = raw.get("self_model", {})
        dimensions = model.get("dimensions", {})
        observations = model.get("recent_observations", [])
        reflections = model.get("recent_reflections", [])
        coherence = model.get("coherence", 0.7)
        pending_actions = raw.get("pending_actions", [])

        if not dimensions and not observations:
            return ""

        lines: list[str] = [
            "Self-awareness (apperceptive self-observations \u2014 "
            "what I notice about my own processing):"
        ]

        if coherence < 0.4:
            lines.append(
                f"  \u26a0 Self-coherence low ({coherence:.2f}) \u2014 "
                "rebuilding self-model, expect uncertainty"
            )

        if dimensions:
            lines.append("  Self-dimensions:")
            for name, dim in sorted(dimensions.items()):
                conf = dim.get("confidence", 0.5)
                affirm = dim.get("affirming_count", 0)
                prob = dim.get("problematizing_count", 0)
                desc = f"    {name}: confidence={conf:.2f} (+{affirm}/-{prob})"
                lines.append(desc)

        if observations:
            recent = observations[-5:]
            lines.append("  Recent self-observations:")
            for obs in recent:
                lines.append(f"    - {obs}")

        if reflections:
            recent_ref = reflections[-3:]
            lines.append("  Reflections:")
            for ref in recent_ref:
                lines.append(f"    - {ref}")

        if pending_actions:
            lines.append("  Pending self-actions:")
            for action in pending_actions[:3]:
                lines.append(f"    - {action}")

        return "\n".join(lines)
    except Exception:
        return ""
```

- [ ] **Step 2: Replace in shared/operator.py**

In `shared/operator.py`, replace the entire `_read_apperception_block` function (lines 228-306) with an import:

```python
from shared.apperception_shm import read_apperception_block as _read_apperception_block
```

Remove the deleted function body entirely (lines 228-306). Keep the call site at line 445 unchanged — it already calls `_read_apperception_block()`.

- [ ] **Step 3: Replace in logos/_operator.py**

In `logos/_operator.py`, replace the entire `_read_apperception_block` function (lines 184-247) with:

```python
from shared.apperception_shm import read_apperception_block as _read_apperception_block
```

Remove the deleted function body. Keep the call site at line 365 unchanged.

- [ ] **Step 4: Replace in agents/_operator.py**

In `agents/_operator.py`, replace the entire `_read_apperception_block` function (lines 184-247) with:

```python
from shared.apperception_shm import read_apperception_block as _read_apperception_block
```

Remove the deleted function body. Keep the call site at line 365 unchanged.

- [ ] **Step 5: Replace in agents/drift_detector/shm_readers.py**

In `agents/drift_detector/shm_readers.py`, replace the entire `read_apperception_block` function (lines 65-128) with:

```python
from shared.apperception_shm import read_apperception_block  # noqa: F401
```

This re-exports the function so existing callers don't break.

- [ ] **Step 6: Run existing tests**

Run: `cd hapax-council && uv run pytest tests/test_apperception_prompt.py -v -x`
Expected: All pass (tests mock at the module level, import path unchanged).

- [ ] **Step 7: Commit**

```bash
cd hapax-council
git add shared/apperception_shm.py shared/operator.py logos/_operator.py agents/_operator.py agents/drift_detector/shm_readers.py
git commit -m "refactor(apperception): unify _read_apperception_block into shared/apperception_shm.py

Eliminates triple-copy of the same SHM reading + formatting logic.
New module has zero external dependencies (stdlib only) — safe to
import from shared/, agents/, or logos/ without config coupling."
```

---

### Task 3: Wire ApperceptionStore in Tick Loop

**Files:**
- Modify: `shared/apperception_tick.py`

- [ ] **Step 1: Add store initialization**

In `shared/apperception_tick.py`, update the import at the top:

```python
from shared.apperception import ApperceptionCascade, ApperceptionStore, CascadeEvent, SelfModel
```

Replace the entire `ApperceptionTick` class body with updated `__init__`, `tick`, `save_model`, and `_write_shm`. Here is the full updated class (everything from `class ApperceptionTick:` through `_load_model`):

```python
class ApperceptionTick:
    """Standalone apperception tick — reads shm, runs cascade, writes shm.

    All inputs from the filesystem. No in-process state dependencies.
    Can be driven by any tick loop (aggregator, daemon, or standalone).
    """

    def __init__(self) -> None:
        self._cascade = self._load_model()
        self._prev_stimmung_stance: str = "nominal"
        # _last_save and _last_flush use time.monotonic() (interval measurement).
        # Event timestamps and SHM payload use time.time() (wall clock for consumers).
        # These serve different purposes and should NOT be unified.
        self._last_save: float = 0.0
        self._last_flush: float = 0.0
        self._last_correction_ts: float = 0.0  # dedup corrections
        self._tick_seq: int = 0
        self._store = ApperceptionStore()
        try:
            self._store.ensure_collection()
        except Exception:
            log.debug("Failed to ensure apperception collection", exc_info=True)

    def tick(self) -> None:
        """Run one apperception cycle. Call this every 3-5 seconds."""
        self._tick_seq += 1
        stance = self._read_stimmung_stance()
        events = self._collect_events(stance)

        pending_actions: list[str] = []
        for event in events:
            result = self._cascade.process(event, stimmung_stance=stance)
            if result:
                self._store.add(result)
                if result.action:
                    pending_actions.append(result.action)

        self._write_shm(pending_actions, event_count=len(events))

        now = time.monotonic()
        if now - self._last_flush >= 60.0:
            try:
                self._store.flush()
            except Exception:
                log.debug("Failed to flush apperception store", exc_info=True)
            self._last_flush = now

        if now - self._last_save >= 300.0:
            self.save_model()
            self._last_save = now

    def save_model(self) -> None:
        """Persist self-model to cache. Call on shutdown."""
        try:
            self._store.flush()
        except Exception:
            log.debug("Failed to flush store on save", exc_info=True)
        try:
            APPERCEPTION_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            data = self._cascade.model.to_dict()
            tmp = APPERCEPTION_CACHE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            tmp.rename(APPERCEPTION_CACHE_FILE)
        except OSError:
            log.debug("Failed to persist self-model", exc_info=True)

    @property
    def model(self) -> SelfModel:
        return self._cascade.model
```

Update `_write_shm` to accept event_count and include liveness fields:

```python
    def _write_shm(self, pending_actions: list[str], event_count: int = 0) -> None:
        try:
            payload = {
                "self_model": self._cascade.model.to_dict(),
                "pending_actions": pending_actions,
                "timestamp": time.time(),
                "tick_seq": self._tick_seq,
                "events_this_tick": event_count,
            }
            APPERCEPTION_DIR.mkdir(parents=True, exist_ok=True)
            tmp = APPERCEPTION_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            tmp.rename(APPERCEPTION_FILE)
        except OSError:
            log.debug("Failed to write apperception state", exc_info=True)
```

The `_collect_events`, `_read_stimmung_stance`, and `_load_model` methods remain unchanged.

- [ ] **Step 2: Run existing tests**

Run: `cd hapax-council && uv run pytest tests/test_apperception*.py -v -x`
Expected: All pass.

- [ ] **Step 3: Mirror to agents/_apperception_tick.py**

Apply the same changes to `agents/_apperception_tick.py`. The only difference: the import line uses `agents._apperception`:

```python
from agents._apperception import ApperceptionCascade, ApperceptionStore, CascadeEvent, SelfModel
```

All other code is identical.

- [ ] **Step 4: Commit**

```bash
cd hapax-council
git add shared/apperception_tick.py agents/_apperception_tick.py
git commit -m "feat(apperception): wire ApperceptionStore + tick liveness signal

Store: retained apperceptions queued via .add(), flushed to Qdrant
every 60s (best-effort). Collection: hapax-apperceptions (768-dim cosine).
Liveness: tick_seq (monotonic counter) and events_this_tick added to
SHM payload for consumer staleness detection."
```

---

### Task 4: Health Monitor Integration

**Files:**
- Create: `agents/health_monitor/checks/apperception.py`
- Modify: `agents/health_monitor/checks/__init__.py`

- [ ] **Step 1: Create the check module**

Create `agents/health_monitor/checks/apperception.py`:

```python
"""Apperception pipeline health checks."""

from __future__ import annotations

import json
import time
from pathlib import Path

from ..models import CheckResult, Status
from ..registry import check_group

_SELF_BAND_PATH = Path("/dev/shm/hapax-apperception/self-band.json")
_COHERENCE_FLOOR = 0.15  # from shared.apperception — hardcoded to avoid import coupling


@check_group("perception")
async def check_apperception() -> list[CheckResult]:
    """Check apperception tick liveness and self-model coherence."""
    results: list[CheckResult] = []
    raw: dict | None = None
    age: float = 999.0

    # 1. Tick liveness
    try:
        raw = json.loads(_SELF_BAND_PATH.read_text(encoding="utf-8"))
        age = time.time() - raw.get("timestamp", 0)
        if age < 30:
            results.append(
                CheckResult(
                    name="apperception_tick",
                    group="perception",
                    status=Status.HEALTHY,
                    message=f"Tick alive ({age:.0f}s ago)",
                )
            )
        elif age < 120:
            results.append(
                CheckResult(
                    name="apperception_tick",
                    group="perception",
                    status=Status.DEGRADED,
                    message=f"Tick stale ({age:.0f}s)",
                    remediation="Check visual-layer-aggregator service",
                )
            )
        else:
            results.append(
                CheckResult(
                    name="apperception_tick",
                    group="perception",
                    status=Status.FAILED,
                    message=f"Tick dead ({age:.0f}s)",
                    remediation=(
                        "Restart visual-layer-aggregator: "
                        "systemctl --user restart visual-layer-aggregator"
                    ),
                )
            )
    except FileNotFoundError:
        results.append(
            CheckResult(
                name="apperception_tick",
                group="perception",
                status=Status.FAILED,
                message="Self-band file missing",
                remediation=(
                    "Restart visual-layer-aggregator: "
                    "systemctl --user restart visual-layer-aggregator"
                ),
            )
        )
    except Exception as exc:
        results.append(
            CheckResult(
                name="apperception_tick",
                group="perception",
                status=Status.DEGRADED,
                message=f"Could not read self-band: {exc}",
            )
        )

    # 2. Coherence check (only if file was readable and fresh)
    if raw is not None and age < 30:
        coherence = raw.get("self_model", {}).get("coherence", 0.7)
        if coherence > 0.3:
            results.append(
                CheckResult(
                    name="apperception_coherence",
                    group="perception",
                    status=Status.HEALTHY,
                    message=f"Coherence {coherence:.2f}",
                )
            )
        elif coherence > _COHERENCE_FLOOR:
            results.append(
                CheckResult(
                    name="apperception_coherence",
                    group="perception",
                    status=Status.DEGRADED,
                    message=f"Coherence low ({coherence:.2f}), near floor",
                    remediation="Review recent corrections and system stability",
                )
            )
        else:
            results.append(
                CheckResult(
                    name="apperception_coherence",
                    group="perception",
                    status=Status.FAILED,
                    message=f"Coherence at floor ({coherence:.2f}) — shame spiral guard active",
                    remediation="Self-model collapsed. Check for rapid negative corrections",
                )
            )

    return results
```

- [ ] **Step 2: Register in __init__.py**

In `agents/health_monitor/checks/__init__.py`, add `apperception` to the import list (alphabetically first):

```python
from . import (  # noqa: F401
    apperception,
    auth,
    axioms,
    axioms_ef,
    backup,
    ...
```

- [ ] **Step 3: Run health monitor tests**

Run: `cd hapax-council && uv run pytest tests/test_health_monitor.py -v -x`
Expected: All pass.

- [ ] **Step 4: Commit**

```bash
cd hapax-council
git add agents/health_monitor/checks/apperception.py agents/health_monitor/checks/__init__.py
git commit -m "feat(health): add apperception tick liveness + coherence checks

Two checks in 'perception' group:
- apperception_tick: healthy (<30s), degraded (30-120s), failed (>120s/missing)
- apperception_coherence: healthy (>0.3), degraded (0.15-0.3), failed (at floor)"
```

---

### Task 5: I/O Layer Tests — SHM Write + Model Persistence

**Files:**
- Create: `tests/test_apperception_tick_io.py`

- [ ] **Step 1: Create test file with fixtures and SHM write tests**

Create `tests/test_apperception_tick_io.py`:

```python
"""Tests for apperception tick I/O layer — SHM writes, model persistence, store integration.

All tests use tmp_path with monkeypatched paths. Mocks only for Qdrant
and embedding (external services). No real /dev/shm access.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from shared.apperception import ApperceptionCascade, CascadeEvent, SelfModel
from shared.apperception_tick import ApperceptionTick


@pytest.fixture()
def tick_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Set up a tick environment with all paths in tmp_path."""
    temporal_dir = tmp_path / "temporal"
    temporal_dir.mkdir()
    stimmung_dir = tmp_path / "stimmung"
    stimmung_dir.mkdir()
    correction_dir = tmp_path / "correction"
    correction_dir.mkdir()
    apperception_dir = tmp_path / "apperception"
    apperception_dir.mkdir()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    monkeypatch.setattr("shared.apperception_tick.TEMPORAL_FILE", temporal_dir / "bands.json")
    monkeypatch.setattr("shared.apperception_tick.STIMMUNG_FILE", stimmung_dir / "state.json")
    monkeypatch.setattr(
        "shared.apperception_tick.CORRECTION_FILE",
        correction_dir / "activity-correction.json",
    )
    monkeypatch.setattr("shared.apperception_tick.APPERCEPTION_DIR", apperception_dir)
    monkeypatch.setattr(
        "shared.apperception_tick.APPERCEPTION_FILE", apperception_dir / "self-band.json"
    )
    monkeypatch.setattr("shared.apperception_tick.APPERCEPTION_CACHE_DIR", cache_dir)
    monkeypatch.setattr(
        "shared.apperception_tick.APPERCEPTION_CACHE_FILE", cache_dir / "self-model.json"
    )

    # Write default stimmung
    (stimmung_dir / "state.json").write_text(
        json.dumps({"overall_stance": "nominal", "timestamp": time.time()})
    )

    # Mock store to avoid Qdrant
    mock_store = MagicMock()
    mock_store.pending_count = 0
    mock_store.flush.return_value = 0

    return {
        "tmp_path": tmp_path,
        "temporal_dir": temporal_dir,
        "stimmung_dir": stimmung_dir,
        "correction_dir": correction_dir,
        "apperception_dir": apperception_dir,
        "cache_dir": cache_dir,
        "mock_store": mock_store,
    }


def _make_tick(tick_env: dict) -> ApperceptionTick:
    """Create a tick instance with mocked store."""
    with patch.object(ApperceptionTick, "__init__", lambda self: None):
        tick = ApperceptionTick()
    tick._cascade = ApperceptionCascade(self_model=SelfModel())
    tick._prev_stimmung_stance = "nominal"
    tick._last_save = 0.0
    tick._last_flush = 0.0
    tick._last_correction_ts = 0.0
    tick._tick_seq = 0
    tick._store = tick_env["mock_store"]
    return tick


# ── SHM Write Tests ──────────────────────────────────────────────────────────


class TestShmWrite:
    def test_payload_structure(self, tick_env: dict):
        """Written payload contains all 5 expected fields."""
        tick = _make_tick(tick_env)
        tick.tick()
        path = tick_env["apperception_dir"] / "self-band.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert "self_model" in data
        assert "pending_actions" in data
        assert "timestamp" in data
        assert "tick_seq" in data
        assert "events_this_tick" in data
        assert data["tick_seq"] == 1
        assert isinstance(data["events_this_tick"], int)

    def test_atomic_write_no_tmp_leftover(self, tick_env: dict):
        """After write, no .tmp file remains (atomic rename succeeded)."""
        tick = _make_tick(tick_env)
        tick.tick()
        tmp_path = tick_env["apperception_dir"] / "self-band.tmp"
        assert not tmp_path.exists()

    def test_creates_directory(self, tick_env: dict):
        """_write_shm creates the directory if missing."""
        import shutil

        shutil.rmtree(tick_env["apperception_dir"])
        tick = _make_tick(tick_env)
        tick._write_shm([], event_count=0)
        assert (tick_env["apperception_dir"] / "self-band.json").exists()

    def test_oserror_graceful(self, tick_env: dict, monkeypatch: pytest.MonkeyPatch):
        """OSError during write doesn't crash — logs and continues."""
        tick = _make_tick(tick_env)
        monkeypatch.setattr(
            "shared.apperception_tick.APPERCEPTION_DIR",
            Path("/nonexistent/readonly/dir"),
        )
        monkeypatch.setattr(
            "shared.apperception_tick.APPERCEPTION_FILE",
            Path("/nonexistent/readonly/dir/self-band.json"),
        )
        tick._write_shm([], event_count=0)  # should not raise


# ── Model Persistence Tests ──────────────────────────────────────────────────


class TestModelPersistence:
    def test_save_load_roundtrip(self, tick_env: dict):
        """Save model, create new instance, verify dimensions preserved."""
        tick = _make_tick(tick_env)
        tick._cascade.model.get_or_create_dimension("test_dim")
        tick._cascade.model.dimensions["test_dim"].confidence = 0.8
        tick._cascade.model.dimensions["test_dim"].affirming_count = 5
        tick.save_model()

        cache_file = tick_env["cache_dir"] / "self-model.json"
        assert cache_file.exists()
        data = json.loads(cache_file.read_text())
        assert "test_dim" in data["dimensions"]
        assert data["dimensions"]["test_dim"]["confidence"] == 0.8

    def test_corrupted_cache_starts_fresh(self, tick_env: dict, monkeypatch: pytest.MonkeyPatch):
        """Garbage in cache file -> starts fresh with empty SelfModel."""
        cache_file = tick_env["cache_dir"] / "self-model.json"
        cache_file.write_text("NOT VALID JSON {{{")
        monkeypatch.setattr("shared.apperception_tick.APPERCEPTION_CACHE_FILE", cache_file)
        tick = _make_tick(tick_env)
        cascade = tick._load_model()
        assert len(cascade.model.dimensions) == 0

    def test_missing_cache_starts_fresh(self, tick_env: dict, monkeypatch: pytest.MonkeyPatch):
        """No cache file -> starts fresh."""
        monkeypatch.setattr(
            "shared.apperception_tick.APPERCEPTION_CACHE_FILE",
            tick_env["cache_dir"] / "nonexistent.json",
        )
        tick = _make_tick(tick_env)
        cascade = tick._load_model()
        assert len(cascade.model.dimensions) == 0
```

- [ ] **Step 2: Run the tests**

Run: `cd hapax-council && uv run pytest tests/test_apperception_tick_io.py -v -x`
Expected: All 7 pass.

- [ ] **Step 3: Commit**

```bash
cd hapax-council
git add tests/test_apperception_tick_io.py
git commit -m "test(apperception): add SHM write + model persistence I/O tests (7 tests)"
```

---

### Task 6: I/O Layer Tests — Tick Loop + Event Collection

**Files:**
- Modify: `tests/test_apperception_tick_io.py`

- [ ] **Step 1: Add tick loop and event edge case tests**

Append to `tests/test_apperception_tick_io.py`:

```python
# ── Tick Loop Tests ───────────────────────────────────────────────────────────


class TestTickLoop:
    def test_full_cycle(self, tick_env: dict):
        """Synthetic temporal surprise -> tick() -> self-band.json written."""
        (tick_env["temporal_dir"] / "bands.json").write_text(
            json.dumps({"max_surprise": 0.6, "timestamp": time.time()})
        )
        tick = _make_tick(tick_env)
        tick.tick()

        path = tick_env["apperception_dir"] / "self-band.json"
        data = json.loads(path.read_text())
        assert data["tick_seq"] == 1
        assert data["events_this_tick"] >= 1

    def test_multi_tick_accumulates(self, tick_env: dict):
        """Three ticks with different events -> dimensions accumulate."""
        (tick_env["temporal_dir"] / "bands.json").write_text(
            json.dumps({"max_surprise": 0.6, "timestamp": time.time()})
        )
        tick = _make_tick(tick_env)
        tick.tick()
        tick.tick()
        tick.tick()

        path = tick_env["apperception_dir"] / "self-band.json"
        data = json.loads(path.read_text())
        assert data["tick_seq"] == 3

    def test_save_interval(self, tick_env: dict, monkeypatch: pytest.MonkeyPatch):
        """save_model() fires after 300s (mocked monotonic)."""
        tick = _make_tick(tick_env)
        tick._last_save = 0.0
        mock_time = MagicMock(return_value=301.0)
        monkeypatch.setattr("shared.apperception_tick.time.monotonic", mock_time)
        tick.tick()

        cache_file = tick_env["cache_dir"] / "self-model.json"
        assert cache_file.exists()

    def test_store_flush_cadence(self, tick_env: dict, monkeypatch: pytest.MonkeyPatch):
        """store.flush() fires after 60s."""
        tick = _make_tick(tick_env)
        tick._last_flush = 0.0
        mock_time = MagicMock(return_value=61.0)
        monkeypatch.setattr("shared.apperception_tick.time.monotonic", mock_time)
        tick.tick()

        tick_env["mock_store"].flush.assert_called_once()

    def test_store_add_on_retain(self, tick_env: dict):
        """Correction event -> retained -> store.add() called."""
        (tick_env["correction_dir"] / "activity-correction.json").write_text(
            json.dumps({"label": "test_correction", "timestamp": time.time()})
        )
        tick = _make_tick(tick_env)
        tick.tick()

        assert tick_env["mock_store"].add.called


# ── Event Collection Edge Cases ───────────────────────────────────────────────


class TestEventCollectionEdgeCases:
    def test_corrupted_temporal_json(self, tick_env: dict):
        """Invalid JSON in temporal file -> no crash, no events."""
        (tick_env["temporal_dir"] / "bands.json").write_text("NOT JSON {{{")
        tick = _make_tick(tick_env)
        tick.tick()
        assert (tick_env["apperception_dir"] / "self-band.json").exists()

    def test_missing_correction_file(self, tick_env: dict):
        """Missing correction file -> no crash, no events."""
        tick = _make_tick(tick_env)
        tick.tick()
        assert (tick_env["apperception_dir"] / "self-band.json").exists()

    def test_unknown_stimmung_stance(self, tick_env: dict):
        """Unknown stance -> treated as degrading transition."""
        (tick_env["stimmung_dir"] / "state.json").write_text(
            json.dumps({"overall_stance": "weird_stance", "timestamp": time.time()})
        )
        tick = _make_tick(tick_env)
        tick.tick()
        path = tick_env["apperception_dir"] / "self-band.json"
        data = json.loads(path.read_text())
        assert data["events_this_tick"] >= 1

    def test_rapid_tick_no_duplicate(self, tick_env: dict):
        """Same correction timestamp twice -> only one event."""
        corr_ts = time.time()
        (tick_env["correction_dir"] / "activity-correction.json").write_text(
            json.dumps({"label": "same", "timestamp": corr_ts})
        )
        tick = _make_tick(tick_env)
        tick.tick()
        first_add_count = tick_env["mock_store"].add.call_count

        tick.tick()
        second_add_count = tick_env["mock_store"].add.call_count

        assert second_add_count == first_add_count
```

- [ ] **Step 2: Run all I/O tests**

Run: `cd hapax-council && uv run pytest tests/test_apperception_tick_io.py -v -x`
Expected: All 16 pass.

- [ ] **Step 3: Commit**

```bash
cd hapax-council
git add tests/test_apperception_tick_io.py
git commit -m "test(apperception): add tick loop + event collection I/O tests (9 more, 16 total)"
```

---

### Task 7: I/O Layer Tests — Store Integration + Final Verification

**Files:**
- Modify: `tests/test_apperception_tick_io.py`

- [ ] **Step 1: Add store integration tests**

Append to `tests/test_apperception_tick_io.py`:

```python
# ── Store Integration Tests ───────────────────────────────────────────────────


class TestStoreIntegration:
    def test_retained_apperception_queued(self, tick_env: dict):
        """Retained apperception is queued to store.add()."""
        (tick_env["correction_dir"] / "activity-correction.json").write_text(
            json.dumps({"label": "verify_add", "timestamp": time.time()})
        )
        tick = _make_tick(tick_env)
        tick.tick()

        assert tick_env["mock_store"].add.call_count >= 1
        from shared.apperception import Apperception

        call_args = tick_env["mock_store"].add.call_args_list
        for call in call_args:
            assert isinstance(call[0][0], Apperception)

    def test_flush_called_on_cadence(self, tick_env: dict, monkeypatch: pytest.MonkeyPatch):
        """flush() called when 60s elapsed since last flush."""
        tick = _make_tick(tick_env)
        tick._last_flush = 0.0
        mock_mono = MagicMock(return_value=61.0)
        monkeypatch.setattr("shared.apperception_tick.time.monotonic", mock_mono)
        tick.tick()
        tick_env["mock_store"].flush.assert_called_once()

    def test_shutdown_flushes(self, tick_env: dict):
        """save_model() calls store.flush() before persisting."""
        tick = _make_tick(tick_env)
        tick.save_model()
        tick_env["mock_store"].flush.assert_called_once()
        cache_file = tick_env["cache_dir"] / "self-model.json"
        assert cache_file.exists()
```

- [ ] **Step 2: Run full I/O test suite**

Run: `cd hapax-council && uv run pytest tests/test_apperception_tick_io.py -v`
Expected: All 19 pass.

- [ ] **Step 3: Run complete apperception test suite**

Run: `cd hapax-council && uv run pytest tests/test_apperception*.py -v`
Expected: All tests pass (existing + 19 new).

- [ ] **Step 4: Lint**

Run: `cd hapax-council && uv run ruff check shared/apperception.py shared/apperception_tick.py shared/apperception_shm.py agents/_apperception.py agents/_apperception_tick.py agents/health_monitor/checks/apperception.py tests/test_apperception_tick_io.py`
Expected: Clean.

- [ ] **Step 5: Commit**

```bash
cd hapax-council
git add tests/test_apperception_tick_io.py
git commit -m "test(apperception): add store integration tests (3 more, 19 total I/O tests)"
```

---

### Task 8: Final Verification + PR

- [ ] **Step 1: Run full test suite**

```bash
cd hapax-council && uv run pytest tests/ -q --tb=short 2>&1 | tail -20
```

Expected: No regressions.

- [ ] **Step 2: Typecheck**

```bash
cd hapax-council && uv run pyright shared/apperception.py shared/apperception_tick.py shared/apperception_shm.py
```

- [ ] **Step 3: Create PR**

Branch: `apperception-core-hardening`

PR body should reference:
- Spec: `docs/superpowers/specs/2026-03-31-apperception-core-hardening-design.md`
- Audit findings resolved: ApperceptionStore unwired, triple `_read_apperception_block`, dead `current_assessment`, no health checks, 0% I/O test coverage
- Changes: 6 sections (A–F) from spec, 15 files touched, 19 new tests
