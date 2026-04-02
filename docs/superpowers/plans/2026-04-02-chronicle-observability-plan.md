# Chronicle Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unified event store with causal trace propagation, enabling arbitrary retrospective queries about system behavior over a 12-hour window.

**Architecture:** Single JSONL stream on `/dev/shm/hapax-chronicle/events.jsonl` with a common envelope schema. OTel trace IDs threaded through three existing break points (Impingement, FlowEvent, stimmung→engine). 30-second state snapshots interleaved with domain events. Logos API endpoints for structured + LLM-narrated queries. MCP tool for Claude Code access.

**Tech Stack:** Python 3.12, Pydantic, FastAPI, OpenTelemetry, pydantic-ai (LiteLLM), existing shared infrastructure.

**Spec:** `docs/superpowers/specs/2026-04-02-chronicle-observability-design.md`

---

## File Structure

### New files
| File | Responsibility |
|------|---------------|
| `shared/chronicle.py` | ChronicleEvent model, writer (append JSONL), reader (filter/query), retention (12h trim) |
| `shared/chronicle_sampler.py` | 30s snapshot coroutine: reads stimmung, eigenform, signal bus, reverie state |
| `logos/api/routes/chronicle.py` | `GET /api/chronicle` (structured) + `GET /api/chronicle/narrate` (LLM synthesis) |
| `tests/test_chronicle.py` | Tests for writer, reader, retention, OTel extraction |
| `tests/test_chronicle_sampler.py` | Tests for snapshot assembly |
| `tests/logos/test_chronicle_routes.py` | Tests for API endpoints |

### Modified files
| File | Change |
|------|--------|
| `shared/impingement.py:36-53` | Add `trace_id`, `span_id` optional fields to frozen Impingement |
| `logos/event_bus.py:13-22` | Add `trace_id`, `span_id` optional fields to FlowEvent |
| `logos/engine/__init__.py:460,541-552` | Extract OTel context into Impingement; attach trace IDs to FlowEvents; record chronicle events |
| `shared/stimmung.py:413-414` | Record `stance.changed` and `dimension.spike` to chronicle after hysteresis |
| `agents/reverie/mixer.py:180-189,354-366` | Record `technique.activated`, `params.shifted` to chronicle |
| `logos/api/app.py:71-77,137-192` | Register chronicle routes, start sampler coroutine in lifespan |
| `hapax-mcp/src/hapax_mcp/server.py` | Add `chronicle` and `chronicle_narrate` tools |

---

## Task 1: ChronicleEvent Model + Writer

**Files:**
- Create: `shared/chronicle.py`
- Test: `tests/test_chronicle.py`

- [ ] **Step 1: Write failing test for ChronicleEvent serialization**

```python
# tests/test_chronicle.py
"""Tests for the Chronicle unified event store."""

from __future__ import annotations

import json

from shared.chronicle import ChronicleEvent


def test_chronicle_event_to_json():
    event = ChronicleEvent(
        ts=1712000000.0,
        trace_id="a" * 32,
        span_id="b" * 16,
        parent_span_id="c" * 16,
        source="engine",
        event_type="rule.matched",
        payload={"rule_name": "stimmung_update", "event_path": "/dev/shm/stimmung"},
    )
    line = event.to_json()
    parsed = json.loads(line)
    assert parsed["ts"] == 1712000000.0
    assert parsed["trace_id"] == "a" * 32
    assert parsed["source"] == "engine"
    assert parsed["payload"]["rule_name"] == "stimmung_update"


def test_chronicle_event_from_json():
    raw = json.dumps({
        "ts": 1712000000.0,
        "trace_id": "a" * 32,
        "span_id": "b" * 16,
        "parent_span_id": None,
        "source": "stimmung",
        "event_type": "stance.changed",
        "payload": {"from_stance": "nominal", "to_stance": "cautious"},
    })
    event = ChronicleEvent.from_json(raw)
    assert event.source == "stimmung"
    assert event.event_type == "stance.changed"
    assert event.parent_span_id is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_chronicle.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'shared.chronicle'`

- [ ] **Step 3: Write ChronicleEvent model**

```python
# shared/chronicle.py
"""Chronicle — unified system event store.

Single JSONL stream on /dev/shm carrying all system events in a common
envelope with OTel trace propagation for causal chain reconstruction.
12-hour strict retention.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

CHRONICLE_DIR = Path("/dev/shm/hapax-chronicle")
CHRONICLE_FILE = CHRONICLE_DIR / "events.jsonl"
RETENTION_S = 12 * 3600  # 12 hours


@dataclass(frozen=True)
class ChronicleEvent:
    """Single event in the chronicle stream."""

    ts: float
    trace_id: str
    span_id: str
    parent_span_id: str | None
    source: str
    event_type: str
    payload: dict = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(
            {
                "ts": self.ts,
                "trace_id": self.trace_id,
                "span_id": self.span_id,
                "parent_span_id": self.parent_span_id,
                "source": self.source,
                "event_type": self.event_type,
                "payload": self.payload,
            },
            default=str,
        )

    @classmethod
    def from_json(cls, line: str) -> ChronicleEvent:
        d = json.loads(line)
        return cls(
            ts=d["ts"],
            trace_id=d["trace_id"],
            span_id=d["span_id"],
            parent_span_id=d.get("parent_span_id"),
            source=d["source"],
            event_type=d["event_type"],
            payload=d.get("payload", {}),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_chronicle.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add shared/chronicle.py tests/test_chronicle.py && git commit -m "feat: add ChronicleEvent model with JSON serialization"
```

---

## Task 2: Chronicle Writer (append + OTel extraction)

**Files:**
- Modify: `shared/chronicle.py`
- Test: `tests/test_chronicle.py`

- [ ] **Step 1: Write failing tests for writer and OTel helper**

Append to `tests/test_chronicle.py`:

```python
import os

from shared.chronicle import ChronicleEvent, record, current_otel_ids


def test_current_otel_ids_no_span():
    """When no OTel span is active, returns zero-filled IDs."""
    trace_id, span_id = current_otel_ids()
    assert len(trace_id) == 32
    assert len(span_id) == 16


def test_record_appends_to_file(tmp_path):
    path = tmp_path / "events.jsonl"
    event = ChronicleEvent(
        ts=1712000000.0,
        trace_id="a" * 32,
        span_id="b" * 16,
        parent_span_id=None,
        source="engine",
        event_type="rule.matched",
        payload={"rule_name": "test"},
    )
    record(event, path=path)
    record(event, path=path)

    lines = path.read_text().strip().split("\n")
    assert len(lines) == 2
    parsed = json.loads(lines[0])
    assert parsed["source"] == "engine"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_chronicle.py::test_record_appends_to_file -v`
Expected: FAIL — `ImportError: cannot import name 'record'`

- [ ] **Step 3: Implement record() and current_otel_ids()**

Add to `shared/chronicle.py` after the `ChronicleEvent` class:

```python
def current_otel_ids() -> tuple[str, str]:
    """Extract trace_id and span_id from the active OTel span, or return zeros."""
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx and ctx.trace_id:
            return format(ctx.trace_id, "032x"), format(ctx.span_id, "016x")
    except Exception:
        pass
    return "0" * 32, "0" * 16


def record(event: ChronicleEvent, *, path: Path = CHRONICLE_FILE) -> None:
    """Append a ChronicleEvent to the chronicle JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(event.to_json() + "\n")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_chronicle.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add shared/chronicle.py tests/test_chronicle.py && git commit -m "feat: add chronicle record() writer and OTel context extraction"
```

---

## Task 3: Chronicle Reader (query with filters)

**Files:**
- Modify: `shared/chronicle.py`
- Test: `tests/test_chronicle.py`

- [ ] **Step 1: Write failing tests for query()**

Append to `tests/test_chronicle.py`:

```python
from shared.chronicle import query


def _write_events(path, events):
    """Helper: write a list of ChronicleEvents to a file."""
    for e in events:
        record(e, path=path)


def test_query_filters_by_time_range(tmp_path):
    path = tmp_path / "events.jsonl"
    events = [
        ChronicleEvent(ts=100.0, trace_id="a" * 32, span_id="b" * 16, parent_span_id=None, source="engine", event_type="rule.matched", payload={}),
        ChronicleEvent(ts=200.0, trace_id="a" * 32, span_id="c" * 16, parent_span_id=None, source="stimmung", event_type="stance.changed", payload={}),
        ChronicleEvent(ts=300.0, trace_id="a" * 32, span_id="d" * 16, parent_span_id=None, source="visual", event_type="technique.activated", payload={}),
    ]
    _write_events(path, events)

    result = query(since=150.0, path=path)
    assert len(result) == 2
    assert result[0].ts == 300.0  # newest first
    assert result[1].ts == 200.0

    result = query(since=150.0, until=250.0, path=path)
    assert len(result) == 1
    assert result[0].source == "stimmung"


def test_query_filters_by_source(tmp_path):
    path = tmp_path / "events.jsonl"
    events = [
        ChronicleEvent(ts=100.0, trace_id="a" * 32, span_id="b" * 16, parent_span_id=None, source="engine", event_type="rule.matched", payload={}),
        ChronicleEvent(ts=200.0, trace_id="a" * 32, span_id="c" * 16, parent_span_id=None, source="visual", event_type="technique.activated", payload={}),
    ]
    _write_events(path, events)

    result = query(since=0.0, source="visual", path=path)
    assert len(result) == 1
    assert result[0].source == "visual"


def test_query_filters_by_event_type(tmp_path):
    path = tmp_path / "events.jsonl"
    events = [
        ChronicleEvent(ts=100.0, trace_id="a" * 32, span_id="b" * 16, parent_span_id=None, source="engine", event_type="rule.matched", payload={}),
        ChronicleEvent(ts=200.0, trace_id="a" * 32, span_id="c" * 16, parent_span_id=None, source="engine", event_type="action.executed", payload={}),
    ]
    _write_events(path, events)

    result = query(since=0.0, event_type="rule.matched", path=path)
    assert len(result) == 1


def test_query_filters_by_trace_id(tmp_path):
    path = tmp_path / "events.jsonl"
    events = [
        ChronicleEvent(ts=100.0, trace_id="a" * 32, span_id="b" * 16, parent_span_id=None, source="engine", event_type="rule.matched", payload={}),
        ChronicleEvent(ts=200.0, trace_id="f" * 32, span_id="c" * 16, parent_span_id=None, source="engine", event_type="action.executed", payload={}),
    ]
    _write_events(path, events)

    result = query(since=0.0, trace_id="a" * 32, path=path)
    assert len(result) == 1
    assert result[0].event_type == "rule.matched"


def test_query_respects_limit(tmp_path):
    path = tmp_path / "events.jsonl"
    events = [
        ChronicleEvent(ts=float(i), trace_id="a" * 32, span_id="b" * 16, parent_span_id=None, source="engine", event_type="rule.matched", payload={})
        for i in range(10)
    ]
    _write_events(path, events)

    result = query(since=0.0, limit=3, path=path)
    assert len(result) == 3
    assert result[0].ts == 9.0  # newest first


def test_query_empty_file(tmp_path):
    path = tmp_path / "events.jsonl"
    result = query(since=0.0, path=path)
    assert result == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_chronicle.py::test_query_filters_by_time_range -v`
Expected: FAIL — `ImportError: cannot import name 'query'`

- [ ] **Step 3: Implement query()**

Add to `shared/chronicle.py`:

```python
def query(
    *,
    since: float,
    until: float | None = None,
    source: str | None = None,
    event_type: str | None = None,
    trace_id: str | None = None,
    limit: int = 500,
    path: Path = CHRONICLE_FILE,
) -> list[ChronicleEvent]:
    """Query chronicle events with filters. Returns newest-first."""
    if not path.exists():
        return []

    results: list[ChronicleEvent] = []
    for line in path.read_text(encoding="utf-8").strip().split("\n"):
        if not line:
            continue
        try:
            event = ChronicleEvent.from_json(line)
        except (json.JSONDecodeError, KeyError):
            continue
        if event.ts < since:
            continue
        if until is not None and event.ts > until:
            continue
        if source is not None and event.source != source:
            continue
        if event_type is not None and event.event_type != event_type:
            continue
        if trace_id is not None and event.trace_id != trace_id:
            continue
        results.append(event)

    results.sort(key=lambda e: e.ts, reverse=True)
    return results[:limit]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_chronicle.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add shared/chronicle.py tests/test_chronicle.py && git commit -m "feat: add chronicle query() with time/source/type/trace filters"
```

---

## Task 4: Chronicle Retention (12-hour trim)

**Files:**
- Modify: `shared/chronicle.py`
- Test: `tests/test_chronicle.py`

- [ ] **Step 1: Write failing test for trim()**

Append to `tests/test_chronicle.py`:

```python
import time

from shared.chronicle import trim


def test_trim_removes_old_events(tmp_path):
    path = tmp_path / "events.jsonl"
    now = time.time()
    events = [
        ChronicleEvent(ts=now - 50000, trace_id="a" * 32, span_id="b" * 16, parent_span_id=None, source="engine", event_type="old", payload={}),
        ChronicleEvent(ts=now - 100, trace_id="a" * 32, span_id="c" * 16, parent_span_id=None, source="engine", event_type="recent", payload={}),
    ]
    _write_events(path, events)

    trim(retention_s=43200, path=path)

    remaining = query(since=0.0, path=path)
    assert len(remaining) == 1
    assert remaining[0].event_type == "recent"


def test_trim_no_file(tmp_path):
    """trim() on nonexistent file is a no-op."""
    path = tmp_path / "events.jsonl"
    trim(path=path)  # should not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_chronicle.py::test_trim_removes_old_events -v`
Expected: FAIL — `ImportError: cannot import name 'trim'`

- [ ] **Step 3: Implement trim()**

Add to `shared/chronicle.py`:

```python
def trim(*, retention_s: float = RETENTION_S, path: Path = CHRONICLE_FILE) -> None:
    """Remove events older than retention_s. Atomic rewrite."""
    if not path.exists():
        return
    cutoff = time.time() - retention_s
    kept: list[str] = []
    for line in path.read_text(encoding="utf-8").strip().split("\n"):
        if not line:
            continue
        try:
            ts = json.loads(line)["ts"]
        except (json.JSONDecodeError, KeyError):
            continue
        if ts >= cutoff:
            kept.append(line)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(kept) + "\n" if kept else "", encoding="utf-8")
    tmp.rename(path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_chronicle.py -v`
Expected: PASS (12 tests)

- [ ] **Step 5: Commit**

```bash
git add shared/chronicle.py tests/test_chronicle.py && git commit -m "feat: add chronicle trim() with 12-hour retention"
```

---

## Task 5: Trace Propagation — Impingement + FlowEvent

**Files:**
- Modify: `shared/impingement.py:36-53`
- Modify: `logos/event_bus.py:13-22`
- Test: `tests/test_chronicle.py`

- [ ] **Step 1: Write failing tests for trace fields**

Append to `tests/test_chronicle.py`:

```python
def test_impingement_has_trace_fields():
    from shared.impingement import Impingement, ImpingementType

    imp = Impingement(
        source="engine",
        type=ImpingementType.PATTERN_MATCH,
        strength=0.5,
        content={"test": True},
        context={},
        trace_id="a" * 32,
        span_id="b" * 16,
    )
    assert imp.trace_id == "a" * 32
    assert imp.span_id == "b" * 16


def test_impingement_trace_fields_default_none():
    from shared.impingement import Impingement, ImpingementType

    imp = Impingement(
        source="engine",
        type=ImpingementType.PATTERN_MATCH,
        strength=0.5,
        content={},
        context={},
    )
    assert imp.trace_id is None
    assert imp.span_id is None


def test_flow_event_has_trace_fields():
    from logos.event_bus import FlowEvent

    fe = FlowEvent(
        kind="engine.action",
        source="engine",
        target="reverie",
        label="test",
        trace_id="a" * 32,
        span_id="b" * 16,
    )
    assert fe.trace_id == "a" * 32
    assert fe.span_id == "b" * 16


def test_flow_event_trace_fields_default_none():
    from logos.event_bus import FlowEvent

    fe = FlowEvent(kind="engine.action", source="engine", target="reverie", label="test")
    assert fe.trace_id is None
    assert fe.span_id is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_chronicle.py::test_impingement_has_trace_fields -v`
Expected: FAIL — `TypeError: unexpected keyword argument 'trace_id'`

- [ ] **Step 3: Add trace fields to Impingement**

In `shared/impingement.py`, add two fields to the `Impingement` dataclass after the `parent_id` field (which already has a default of `None`), before `embedding`:

```python
    trace_id: str | None = None
    span_id: str | None = None
```

The full field order should be: `id`, `timestamp`, `source`, `type`, `strength`, `content`, `context`, `interrupt_token`, `parent_id`, `trace_id`, `span_id`, `embedding`.

- [ ] **Step 4: Add trace fields to FlowEvent**

In `logos/event_bus.py`, add two fields to the `FlowEvent` dataclass after the existing fields:

```python
    trace_id: str | None = None
    span_id: str | None = None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_chronicle.py -v`
Expected: PASS (16 tests)

- [ ] **Step 6: Run full test suite to check for regressions**

Run: `uv run pytest tests/ -q --timeout=30 2>&1 | tail -20`
Expected: No new failures

- [ ] **Step 7: Commit**

```bash
git add shared/impingement.py logos/event_bus.py tests/test_chronicle.py && git commit -m "feat: add trace_id/span_id to Impingement and FlowEvent"
```

---

## Task 6: Engine Trace Threading

**Files:**
- Modify: `logos/engine/__init__.py`

This task wires the engine to: (1) attach OTel trace context to Impingements it creates, (2) attach trace IDs to FlowEvents it emits, and (3) record chronicle events for rule matches and action executions.

- [ ] **Step 1: Read the current engine code**

Read `logos/engine/__init__.py` fully to find the exact locations of:
- `_convert_event()` or the impingement creation call (~line 460)
- The FlowEvent emission loop (~lines 541-552)
- Where `hapax_trace("engine", "event", ...)` wraps the handler (~line 427)

- [ ] **Step 2: Add chronicle import and trace context extraction at impingement creation**

At the top of the engine module, add:

```python
from shared.chronicle import ChronicleEvent, current_otel_ids, record as chronicle_record
```

At the impingement creation site (where `_convert_event(event)` is called), inject trace context. After the impingement is created, replace it with one carrying trace IDs:

```python
impingement = self._convert_event(event)
if impingement is not None:
    trace_id, span_id = current_otel_ids()
    # Rebuild with trace context (frozen dataclass)
    impingement = Impingement(
        id=impingement.id,
        timestamp=impingement.timestamp,
        source=impingement.source,
        type=impingement.type,
        strength=impingement.strength,
        content=impingement.content,
        context=impingement.context,
        interrupt_token=impingement.interrupt_token,
        parent_id=impingement.parent_id,
        trace_id=trace_id,
        span_id=span_id,
        embedding=impingement.embedding,
    )
```

- [ ] **Step 3: Record chronicle events for rule matches and action execution**

Inside the `hapax_trace("engine", "event", ...)` context manager, after rule evaluation:

```python
# After plan = evaluate_rules(event, self._registry)
if plan.actions:
    trace_id, span_id = current_otel_ids()
    chronicle_record(ChronicleEvent(
        ts=time.time(),
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=None,
        source="engine",
        event_type="rule.matched",
        payload={
            "rules": [a.name for a in plan.actions],
            "event_path": str(event.path),
            "doc_type": event.doc_type or "",
        },
    ))
```

After action execution completes (inside the execution span):

```python
for action_name in plan.results:
    trace_id, span_id = current_otel_ids()
    chronicle_record(ChronicleEvent(
        ts=time.time(),
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=None,
        source="engine",
        event_type="action.executed",
        payload={
            "action_name": action_name,
            "event_path": str(event.path),
        },
    ))
```

- [ ] **Step 4: Attach trace IDs to FlowEvent emissions**

Replace the existing FlowEvent emission loop (~lines 541-552) with trace-aware version:

```python
if self._event_bus:
    trace_id, span_id = current_otel_ids()
    for action_name in plan.results:
        from logos.event_bus import FlowEvent

        self._event_bus.emit(
            FlowEvent(
                kind="engine.action",
                source=self._agent_from_path(str(event.path)),
                target=action_name,
                label=action_name,
                trace_id=trace_id,
                span_id=span_id,
            )
        )
```

- [ ] **Step 5: Run engine-related tests**

Run: `uv run pytest tests/ -k "engine" -q --timeout=30 2>&1 | tail -20`
Expected: No regressions

- [ ] **Step 6: Commit**

```bash
git add logos/engine/__init__.py && git commit -m "feat: thread OTel trace context through engine, record to chronicle"
```

---

## Task 7: Stimmung Chronicle Integration

**Files:**
- Modify: `shared/stimmung.py`

- [ ] **Step 1: Read stimmung.py to find exact integration points**

Read `shared/stimmung.py` around:
- The `snapshot()` method where stance is computed and hysteresis applied (~lines 389-469)
- The `_apply_hysteresis()` method where stance transitions are detected

- [ ] **Step 2: Add chronicle recording after stance changes**

Add import at top of `shared/stimmung.py`:

```python
from shared.chronicle import ChronicleEvent, current_otel_ids, record as chronicle_record
```

After hysteresis is applied and a stance change is detected (where `prev_stance != stance`), record to chronicle:

```python
if prev_stance and prev_stance != stance:
    trace_id, span_id = current_otel_ids()
    chronicle_record(ChronicleEvent(
        ts=time.time(),
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=None,
        source="stimmung",
        event_type="stance.changed",
        payload={
            "from_stance": prev_stance,
            "to_stance": stance,
            "trigger_dimension": worst_dim_name if worst_dim_name else "",
            "dimension_values": {
                name: round(reading.value, 3)
                for name, reading in dimensions.items()
            },
        },
    ))
```

- [ ] **Step 3: Add dimension spike detection**

In the same `snapshot()` method, after dimensions are assembled but before stance computation, check for spikes:

```python
for name, reading in dimensions.items():
    prev = self._prev_dimensions.get(name)
    if reading.value > 0.7 or reading.value < 0.3:
        if prev is None or abs(reading.value - prev) > 0.15:
            trace_id, span_id = current_otel_ids()
            chronicle_record(ChronicleEvent(
                ts=time.time(),
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=None,
                source="stimmung",
                event_type="dimension.spike",
                payload={
                    "dimension_name": name,
                    "value": round(reading.value, 3),
                    "trend": reading.trend,
                    "previous_value": round(prev, 3) if prev is not None else None,
                },
            ))
self._prev_dimensions = {name: reading.value for name, reading in dimensions.items()}
```

Add `self._prev_dimensions: dict[str, float] = {}` in `StimmungCollector.__init__()`.

- [ ] **Step 4: Run stimmung tests**

Run: `uv run pytest tests/ -k "stimmung" -q --timeout=30 2>&1 | tail -20`
Expected: No regressions

- [ ] **Step 5: Commit**

```bash
git add shared/stimmung.py && git commit -m "feat: record stimmung stance.changed and dimension.spike to chronicle"
```

---

## Task 8: Reverie Chronicle Integration

**Files:**
- Modify: `agents/reverie/mixer.py`

- [ ] **Step 1: Read mixer.py to find exact integration points**

Read `agents/reverie/mixer.py` to find:
- Where technique activation happens (satellite recruitment, ~lines 234-246)
- Where shader params are written to uniforms.json (~lines 180-189)
- Where the visual chain dimensions are activated (~lines 354-366)

- [ ] **Step 2: Add chronicle recording for technique activation**

Add import at top of `agents/reverie/mixer.py`:

```python
from shared.chronicle import ChronicleEvent, current_otel_ids, record as chronicle_record
```

At the technique activation site (where satellites are recruited or visual chain dimensions activated), add:

```python
trace_id, span_id = current_otel_ids()
chronicle_record(ChronicleEvent(
    ts=time.time(),
    trace_id=trace_id,
    span_id=span_id,
    parent_span_id=None,
    source="visual",
    event_type="technique.activated",
    payload={
        "technique_name": node_id,
        "confidence": round(confidence, 3),
    },
))
```

- [ ] **Step 3: Add chronicle recording for param shifts**

At the `write_uniforms()` call site, compare current uniforms to previous and record significant changes. Add a `_prev_uniforms: dict = {}` attribute to the mixer class, then before writing:

```python
# Detect significant param changes
changed = {}
for key, val in uniforms.items():
    if isinstance(val, (int, float)):
        prev = self._prev_uniforms.get(key, 0.0)
        if abs(val - prev) > 0.05:  # dead zone
            changed[key] = round(val, 4)
if changed:
    trace_id, span_id = current_otel_ids()
    chronicle_record(ChronicleEvent(
        ts=time.time(),
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=None,
        source="visual",
        event_type="params.shifted",
        payload={"changed_params": changed},
    ))
self._prev_uniforms = {k: v for k, v in uniforms.items() if isinstance(v, (int, float))}
```

- [ ] **Step 4: Run reverie tests**

Run: `uv run pytest tests/ -k "reverie or mixer" -q --timeout=30 2>&1 | tail -20`
Expected: No regressions

- [ ] **Step 5: Commit**

```bash
git add agents/reverie/mixer.py && git commit -m "feat: record technique.activated and params.shifted to chronicle"
```

---

## Task 9: Chronicle Sampler (30-second snapshots)

**Files:**
- Create: `shared/chronicle_sampler.py`
- Test: `tests/test_chronicle_sampler.py`

- [ ] **Step 1: Write failing test for snapshot assembly**

```python
# tests/test_chronicle_sampler.py
"""Tests for the Chronicle snapshot sampler."""

from __future__ import annotations

import json

from shared.chronicle_sampler import assemble_snapshot


def test_assemble_snapshot_returns_dict(tmp_path):
    """assemble_snapshot returns a dict with expected keys even when sources are missing."""
    snapshot = assemble_snapshot(
        stimmung_path=tmp_path / "nonexistent.json",
        eigenform_path=tmp_path / "nonexistent.jsonl",
    )
    assert isinstance(snapshot, dict)
    assert "stimmung" in snapshot
    assert "eigenform" in snapshot
    assert "signals" in snapshot


def test_assemble_snapshot_reads_stimmung(tmp_path):
    stimmung_file = tmp_path / "state.json"
    stimmung_file.write_text(json.dumps({
        "stance": "nominal",
        "dimensions": {"health": 0.1, "resource_pressure": 0.2},
    }))
    snapshot = assemble_snapshot(stimmung_path=stimmung_file, eigenform_path=tmp_path / "x.jsonl")
    assert snapshot["stimmung"]["stance"] == "nominal"
    assert snapshot["stimmung"]["dimensions"]["health"] == 0.1


def test_assemble_snapshot_reads_eigenform_latest(tmp_path):
    ef_file = tmp_path / "state-log.jsonl"
    ef_file.write_text(
        json.dumps({"t": 100.0, "presence": 0.5, "flow_score": 0.8}) + "\n"
        + json.dumps({"t": 200.0, "presence": 0.9, "flow_score": 0.3}) + "\n"
    )
    snapshot = assemble_snapshot(stimmung_path=tmp_path / "x.json", eigenform_path=ef_file)
    assert snapshot["eigenform"]["presence"] == 0.9
    assert snapshot["eigenform"]["t"] == 200.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_chronicle_sampler.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement assemble_snapshot() and run_sampler()**

```python
# shared/chronicle_sampler.py
"""Chronicle sampler — periodic state snapshots for the unified event store."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from shared.chronicle import (
    ChronicleEvent,
    current_otel_ids,
    record as chronicle_record,
)

log = logging.getLogger(__name__)

STIMMUNG_STATE = Path("/dev/shm/hapax-stimmung/state.json")
EIGENFORM_LOG = Path("/dev/shm/hapax-eigenform/state-log.jsonl")
SNAPSHOT_INTERVAL_S = 30


def assemble_snapshot(
    *,
    stimmung_path: Path = STIMMUNG_STATE,
    eigenform_path: Path = EIGENFORM_LOG,
    signal_bus_snapshot: dict[str, float] | None = None,
) -> dict:
    """Assemble a full system state snapshot from available sources."""
    snapshot: dict = {
        "stimmung": {},
        "eigenform": {},
        "signals": signal_bus_snapshot or {},
    }

    # Stimmung
    try:
        if stimmung_path.exists():
            data = json.loads(stimmung_path.read_text(encoding="utf-8"))
            snapshot["stimmung"] = {
                "stance": data.get("stance", "unknown"),
                "dimensions": data.get("dimensions", {}),
            }
    except (json.JSONDecodeError, OSError) as exc:
        log.debug("Failed to read stimmung state: %s", exc)

    # Eigenform (latest entry)
    try:
        if eigenform_path.exists():
            text = eigenform_path.read_text(encoding="utf-8").strip()
            if text:
                last_line = text.split("\n")[-1]
                snapshot["eigenform"] = json.loads(last_line)
    except (json.JSONDecodeError, OSError) as exc:
        log.debug("Failed to read eigenform log: %s", exc)

    return snapshot


async def run_sampler(
    *,
    interval_s: float = SNAPSHOT_INTERVAL_S,
    signal_bus: object | None = None,
) -> None:
    """Run the snapshot sampler as a long-lived coroutine. Call from lifespan."""
    while True:
        try:
            bus_snapshot = None
            if signal_bus is not None and hasattr(signal_bus, "snapshot"):
                bus_snapshot = signal_bus.snapshot()

            payload = assemble_snapshot(signal_bus_snapshot=bus_snapshot)
            trace_id, span_id = current_otel_ids()
            chronicle_record(ChronicleEvent(
                ts=time.time(),
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=None,
                source="*",
                event_type="snapshot",
                payload=payload,
            ))
        except Exception:
            log.exception("Chronicle snapshot failed")

        await asyncio.sleep(interval_s)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_chronicle_sampler.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add shared/chronicle_sampler.py tests/test_chronicle_sampler.py && git commit -m "feat: add chronicle sampler with 30s state snapshots"
```

---

## Task 10: Chronicle API Endpoints

**Files:**
- Create: `logos/api/routes/chronicle.py`
- Test: `tests/logos/test_chronicle_routes.py`

- [ ] **Step 1: Write failing test for structured query endpoint**

```python
# tests/logos/test_chronicle_routes.py
"""Tests for Chronicle API routes."""

from __future__ import annotations

import json
import time
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from logos.api.routes.chronicle import router


def _app():
    app = FastAPI()
    app.include_router(router)
    return app


def test_chronicle_query_returns_events(tmp_path):
    from shared.chronicle import ChronicleEvent, record

    path = tmp_path / "events.jsonl"
    now = time.time()
    record(
        ChronicleEvent(
            ts=now - 60,
            trace_id="a" * 32,
            span_id="b" * 16,
            parent_span_id=None,
            source="engine",
            event_type="rule.matched",
            payload={"rule_name": "test"},
        ),
        path=path,
    )

    with patch("logos.api.routes.chronicle.CHRONICLE_FILE", path):
        client = TestClient(_app())
        resp = client.get("/api/chronicle", params={"since": "-1h"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["source"] == "engine"


def test_chronicle_query_empty(tmp_path):
    path = tmp_path / "events.jsonl"
    with patch("logos.api.routes.chronicle.CHRONICLE_FILE", path):
        client = TestClient(_app())
        resp = client.get("/api/chronicle", params={"since": "-1h"})
        assert resp.status_code == 200
        assert resp.json() == []


def test_chronicle_query_filters_source(tmp_path):
    from shared.chronicle import ChronicleEvent, record

    path = tmp_path / "events.jsonl"
    now = time.time()
    record(ChronicleEvent(ts=now, trace_id="a" * 32, span_id="b" * 16, parent_span_id=None, source="engine", event_type="rule.matched", payload={}), path=path)
    record(ChronicleEvent(ts=now, trace_id="a" * 32, span_id="c" * 16, parent_span_id=None, source="visual", event_type="technique.activated", payload={}), path=path)

    with patch("logos.api.routes.chronicle.CHRONICLE_FILE", path):
        client = TestClient(_app())
        resp = client.get("/api/chronicle", params={"since": "-1h", "source": "visual"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["source"] == "visual"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/logos/test_chronicle_routes.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement chronicle routes**

```python
# logos/api/routes/chronicle.py
"""Chronicle API — structured and narrated queries over the unified event store."""

from __future__ import annotations

import json
import logging
import time

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from shared.chronicle import CHRONICLE_FILE, query as chronicle_query

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chronicle", tags=["chronicle"])


def _parse_since(since: str) -> float:
    """Parse relative time strings like '-1h', '-30m' or absolute ISO timestamps."""
    since = since.strip()
    if since.startswith("-"):
        unit = since[-1]
        value = float(since[1:-1])
        multipliers = {"s": 1, "m": 60, "h": 3600}
        if unit not in multipliers:
            raise ValueError(f"Unknown time unit: {unit}")
        return time.time() - value * multipliers[unit]
    # Attempt ISO parse
    from datetime import datetime, timezone

    dt = datetime.fromisoformat(since)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


@router.get("")
async def get_chronicle(
    since: str = Query(..., description="Start time: relative (-1h, -30m) or ISO 8601"),
    until: str | None = Query(None, description="End time: relative or ISO 8601"),
    source: str | None = Query(None, description="Filter by source (engine, stimmung, visual, perception, voice)"),
    event_type: str | None = Query(None, description="Filter by event type"),
    trace_id: str | None = Query(None, description="Filter by trace ID (causal chain)"),
    limit: int = Query(500, ge=1, le=5000),
) -> JSONResponse:
    """Query chronicle events with filters. Returns newest-first."""
    try:
        since_ts = _parse_since(since)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid 'since': {exc}") from exc

    until_ts = None
    if until is not None:
        try:
            until_ts = _parse_since(until)
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=f"Invalid 'until': {exc}") from exc

    events = chronicle_query(
        since=since_ts,
        until=until_ts,
        source=source,
        event_type=event_type,
        trace_id=trace_id,
        limit=limit,
        path=CHRONICLE_FILE,
    )
    return JSONResponse([
        {
            "ts": e.ts,
            "trace_id": e.trace_id,
            "span_id": e.span_id,
            "parent_span_id": e.parent_span_id,
            "source": e.source,
            "event_type": e.event_type,
            "payload": e.payload,
        }
        for e in events
    ])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/logos/test_chronicle_routes.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add logos/api/routes/chronicle.py tests/logos/test_chronicle_routes.py && git commit -m "feat: add GET /api/chronicle structured query endpoint"
```

---

## Task 11: Narrate Endpoint (LLM Synthesis)

**Files:**
- Modify: `logos/api/routes/chronicle.py`
- Test: `tests/logos/test_chronicle_routes.py`

- [ ] **Step 1: Write failing test for narrate endpoint**

Append to `tests/logos/test_chronicle_routes.py`:

```python
from unittest.mock import MagicMock


def test_narrate_returns_narrative(tmp_path):
    from shared.chronicle import ChronicleEvent, record

    path = tmp_path / "events.jsonl"
    now = time.time()
    record(ChronicleEvent(ts=now - 60, trace_id="a" * 32, span_id="b" * 16, parent_span_id=None, source="visual", event_type="technique.activated", payload={"technique_name": "rd"}), path=path)

    mock_agent = MagicMock()
    mock_result = MagicMock()
    mock_result.output = "At 10:14pm, the reaction-diffusion technique activated on the visual surface."
    mock_agent.run_sync = MagicMock(return_value=mock_result)

    with (
        patch("logos.api.routes.chronicle.CHRONICLE_FILE", path),
        patch("logos.api.routes.chronicle._get_narration_agent", return_value=mock_agent),
    ):
        client = TestClient(_app())
        resp = client.get("/api/chronicle/narrate", params={"since": "-1h", "question": "what happened on the visual surface?"})
        assert resp.status_code == 200
        data = resp.json()
        assert "narrative" in data
        assert "reaction-diffusion" in data["narrative"]


def test_narrate_requires_question(tmp_path):
    path = tmp_path / "events.jsonl"
    with patch("logos.api.routes.chronicle.CHRONICLE_FILE", path):
        client = TestClient(_app())
        resp = client.get("/api/chronicle/narrate", params={"since": "-1h"})
        assert resp.status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/logos/test_chronicle_routes.py::test_narrate_returns_narrative -v`
Expected: FAIL — route not found or `AttributeError`

- [ ] **Step 3: Implement narrate endpoint**

Add to `logos/api/routes/chronicle.py`:

```python
from pydantic_ai import Agent

_NARRATE_SYSTEM_PROMPT = """\
You are the Chronicle narrator for Hapax, a personal cognitive infrastructure system.
You receive structured event data from the system's unified event store and synthesize
natural language narratives explaining what happened and why.

Events come from these circulatory systems:
- engine: reactive rule matching and action execution
- stimmung: system emotional/health state (11 dimensions, 5 stances: nominal/seeking/cautious/degraded/critical)
- visual: Hapax Reverie shader pipeline (techniques, param shifts, frame evaluations)
- perception: IR presence, contact mic, biometric signals
- voice: operator utterances and daimonion responses

Trace IDs link causal chains: a stimmung stance change may trigger an engine rule,
which recruits an affordance, which activates a reverie visual technique.
Events sharing a trace_id are causally related. Follow parent_span_id for ordering.

Snapshots (event_type="snapshot") capture full system state every 30 seconds.

Be specific about times, values, and causal relationships. Use the operator's timezone (US Central).
"""


def _get_narration_agent() -> Agent:
    from shared.config import get_model

    return Agent(
        get_model("balanced"),
        system_prompt=_NARRATE_SYSTEM_PROMPT,
        output_type=str,
    )


@router.get("/narrate")
async def narrate_chronicle(
    question: str = Query(..., description="Natural language question about system behavior"),
    since: str = Query(..., description="Start time: relative (-1h, -30m) or ISO 8601"),
    until: str | None = Query(None),
    source: str | None = Query(None),
    event_type: str | None = Query(None),
    trace_id: str | None = Query(None),
    limit: int = Query(500, ge=1, le=5000),
) -> JSONResponse:
    """Answer a natural language question about system behavior using chronicle data."""
    try:
        since_ts = _parse_since(since)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid 'since': {exc}") from exc

    until_ts = None
    if until is not None:
        try:
            until_ts = _parse_since(until)
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=f"Invalid 'until': {exc}") from exc

    events = chronicle_query(
        since=since_ts,
        until=until_ts,
        source=source,
        event_type=event_type,
        trace_id=trace_id,
        limit=limit,
        path=CHRONICLE_FILE,
    )

    if not events:
        return JSONResponse({"narrative": "No events found in the specified time range.", "event_count": 0})

    # Format events for LLM
    event_lines = []
    for e in events:
        from datetime import datetime, timezone

        dt = datetime.fromtimestamp(e.ts, tz=timezone.utc)
        event_lines.append(f"[{dt.isoformat()}] {e.source}/{e.event_type} trace={e.trace_id[:8]}... {json.dumps(e.payload)}")
    event_text = "\n".join(event_lines)

    agent = _get_narration_agent()
    prompt = f"Question: {question}\n\nChronicle events ({len(events)} total):\n{event_text}"
    result = agent.run_sync(prompt)

    return JSONResponse({"narrative": result.output, "event_count": len(events)})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/logos/test_chronicle_routes.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add logos/api/routes/chronicle.py tests/logos/test_chronicle_routes.py && git commit -m "feat: add GET /api/chronicle/narrate LLM synthesis endpoint"
```

---

## Task 12: Wire Chronicle into Logos API Lifespan

**Files:**
- Modify: `logos/api/app.py`

- [ ] **Step 1: Read current app.py lifespan**

Read `logos/api/app.py` lines 26-101 (the lifespan context manager) and lines 137-192 (router registration).

- [ ] **Step 2: Register chronicle router**

Add import near the other router imports (~line 137):

```python
from logos.api.routes.chronicle import router as chronicle_router
```

Add `app.include_router(chronicle_router)` alongside the other router registrations.

- [ ] **Step 3: Start sampler and trim task in lifespan**

Inside the lifespan context manager, after the event bus is initialized (~line 77), add:

```python
# Chronicle: start sampler and periodic trim
from shared.chronicle_sampler import run_sampler
from shared.chronicle import trim as chronicle_trim

async def _chronicle_trim_loop():
    while True:
        try:
            chronicle_trim()
        except Exception:
            log.exception("Chronicle trim failed")
        await asyncio.sleep(60)

sampler_task = asyncio.create_task(run_sampler(signal_bus=getattr(app.state, "signal_bus", None)))
trim_task = asyncio.create_task(_chronicle_trim_loop())
```

In the yield/cleanup section, cancel both tasks:

```python
sampler_task.cancel()
trim_task.cancel()
```

- [ ] **Step 4: Verify API starts**

Run: `timeout 10 uv run python -c "from logos.api.app import app; print('import OK')" 2>&1`
Expected: `import OK` (no import errors)

- [ ] **Step 5: Commit**

```bash
git add logos/api/app.py && git commit -m "feat: register chronicle routes and start sampler/trim in API lifespan"
```

---

## Task 13: MCP Tool

**Files:**
- Modify: `hapax-mcp/src/hapax_mcp/server.py`

- [ ] **Step 1: Read current server.py to find the right insertion point**

Read `hapax-mcp/src/hapax_mcp/server.py` to find where read-only tools are defined (~line 59 onwards).

- [ ] **Step 2: Add chronicle tool (structured query)**

Add after the existing read-only tools:

```python
@mcp.tool()
async def chronicle(
    since: str = "-1h",
    until: str | None = None,
    source: str | None = None,
    event_type: str | None = None,
    trace_id: str | None = None,
    limit: int = 500,
) -> str:
    """Query the unified system chronicle — all events (engine rules, stimmung changes, visual techniques, perception signals) in a 12-hour window.

    Args:
        since: Start time, relative (-1h, -30m, -6h) or ISO 8601. Default: -1h
        until: End time, same format. Default: now
        source: Filter by system: engine, stimmung, visual, perception, voice
        event_type: Filter by type: rule.matched, stance.changed, technique.activated, params.shifted, snapshot, etc.
        trace_id: Follow a single causal chain (32-hex OTel trace ID)
        limit: Max events to return (1-5000, default 500)
    """
    logger.debug("tool: chronicle since=%s source=%s", since, source)
    try:
        params: dict[str, str | int] = {"since": since, "limit": limit}
        if until:
            params["until"] = until
        if source:
            params["source"] = source
        if event_type:
            params["event_type"] = event_type
        if trace_id:
            params["trace_id"] = trace_id
        return _sanitize_response(await client.get("/chronicle", **params))
    except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as e:
        logger.error("chronicle failed: %s", e)
        return _fmt_error(e)
```

- [ ] **Step 3: Add chronicle_narrate tool (LLM synthesis)**

```python
@mcp.tool()
async def chronicle_narrate(
    question: str,
    since: str = "-1h",
    source: str | None = None,
) -> str:
    """Ask a natural language question about what happened in the system. Uses the chronicle event store + LLM synthesis.

    Examples: "What manifested on the reverie visual surface?", "Why did stimmung go cautious?", "What triggered the engine rules in the last 30 minutes?"

    Args:
        question: Natural language question about system behavior
        since: How far back to look. Default: -1h
        source: Optionally focus on one system: engine, stimmung, visual, perception, voice
    """
    logger.debug("tool: chronicle_narrate question=%s", question[:80])
    try:
        params: dict[str, str] = {"question": question, "since": since}
        if source:
            params["source"] = source
        return _sanitize_response(await client.get("/chronicle/narrate", **params))
    except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException, TimeoutError) as e:
        logger.error("chronicle_narrate failed: %s", e)
        return _fmt_error(e)
```

- [ ] **Step 4: Verify MCP server imports**

Run: `cd ../hapax-mcp && uv run python -c "from hapax_mcp.server import mcp; print('import OK')" 2>&1`
Expected: `import OK`

- [ ] **Step 5: Commit**

```bash
cd ../hapax-mcp && git add src/hapax_mcp/server.py && git commit -m "feat: add chronicle and chronicle_narrate MCP tools"
```

---

## Task 14: Integration Test + Smoke Test

**Files:**
- Test: `tests/test_chronicle.py`

- [ ] **Step 1: Write integration test for full record-query-trim roundtrip**

Append to `tests/test_chronicle.py`:

```python
def test_full_roundtrip_record_query_trim(tmp_path):
    """Integration: record events, query them, trim old ones."""
    path = tmp_path / "events.jsonl"
    now = time.time()

    # Record a mix of events
    events = [
        ChronicleEvent(ts=now - 50000, trace_id="old" + "0" * 29, span_id="a" * 16, parent_span_id=None, source="engine", event_type="rule.matched", payload={"rule_name": "ancient"}),
        ChronicleEvent(ts=now - 100, trace_id="new" + "0" * 29, span_id="b" * 16, parent_span_id=None, source="stimmung", event_type="stance.changed", payload={"from": "nominal", "to": "cautious"}),
        ChronicleEvent(ts=now - 50, trace_id="new" + "0" * 29, span_id="c" * 16, parent_span_id="b" * 16, source="engine", event_type="rule.matched", payload={"rule_name": "stimmung_response"}),
        ChronicleEvent(ts=now - 30, trace_id="new" + "0" * 29, span_id="d" * 16, parent_span_id="c" * 16, source="visual", event_type="technique.activated", payload={"technique_name": "rd"}),
        ChronicleEvent(ts=now - 10, trace_id="x" * 32, span_id="e" * 16, parent_span_id=None, source="*", event_type="snapshot", payload={"stimmung": {"stance": "cautious"}}),
    ]
    for e in events:
        record(e, path=path)

    # Query all recent (excludes the 50000s-old event)
    result = query(since=now - 200, path=path)
    assert len(result) == 4
    assert result[0].event_type == "snapshot"

    # Query by trace (causal chain)
    chain = query(since=0.0, trace_id="new" + "0" * 29, path=path)
    assert len(chain) == 3
    assert chain[0].event_type == "technique.activated"
    assert chain[2].event_type == "stance.changed"

    # Trim removes old
    trim(retention_s=43200, path=path)
    remaining = query(since=0.0, path=path)
    assert all(e.ts > now - 43200 for e in remaining)
    assert len(remaining) == 4  # the 50000s-old one is gone
```

- [ ] **Step 2: Run integration test**

Run: `uv run pytest tests/test_chronicle.py::test_full_roundtrip_record_query_trim -v`
Expected: PASS

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest tests/ -q --timeout=30 2>&1 | tail -20`
Expected: No new failures from chronicle changes

- [ ] **Step 4: Commit**

```bash
git add tests/test_chronicle.py && git commit -m "test: add chronicle integration roundtrip test"
```

---

## Task 15: Lint and Final Verification

- [ ] **Step 1: Run ruff check across all changed files**

```bash
uv run ruff check shared/chronicle.py shared/chronicle_sampler.py logos/api/routes/chronicle.py shared/impingement.py logos/event_bus.py shared/stimmung.py agents/reverie/mixer.py logos/api/app.py logos/engine/__init__.py
```

Expected: No errors (or fix any that appear)

- [ ] **Step 2: Run ruff format**

```bash
uv run ruff format shared/chronicle.py shared/chronicle_sampler.py logos/api/routes/chronicle.py
```

- [ ] **Step 3: Run pyright on new files**

```bash
uv run pyright shared/chronicle.py shared/chronicle_sampler.py logos/api/routes/chronicle.py
```

- [ ] **Step 4: Fix any issues and commit**

```bash
git add -u && git commit -m "chore: lint and type-check chronicle files"
```

- [ ] **Step 5: Run ruff/format on MCP changes**

```bash
cd ../hapax-mcp && uv run ruff check src/hapax_mcp/server.py && uv run ruff format src/hapax_mcp/server.py
```
