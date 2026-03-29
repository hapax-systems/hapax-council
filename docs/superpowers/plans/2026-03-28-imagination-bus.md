# Imagination Bus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an independent imagination loop that reads DMN observations and sensor state, produces structured `ImaginationFragment` objects via a higher-tier LLM, and publishes them to a shm bus. High-salience fragments escalate back to the cascade as impingements.

**Architecture:** Async loop alongside DMN in voice daemon. Variable cadence (4-12s base, accelerates on continuation). LLM produces structured output via pydantic-ai `output_type`. Publishes to `/dev/shm/hapax-imagination/` (filesystem-as-bus). Escalation writes impingements to existing DMN impingement path.

**Tech Stack:** Python 3.12, pydantic-ai (output_type), LiteLLM gateway (qwen3.5:27b via "reasoning" alias), shared/config.py, shared/impingement.py, pytest

---

## File Structure

| File | Responsibility |
|------|---------------|
| `agents/imagination.py` | `ContentReference`, `ImaginationFragment` models, `ImaginationLoop` class (tick, cadence, context assembly, shm publish, escalation) |
| `tests/test_imagination.py` | Unit tests for models, cadence, escalation, shm output, context assembly |

---

### Task 1: Data Models

**Files:**
- Create: `agents/imagination.py`
- Create: `tests/test_imagination.py`

- [ ] **Step 1: Write the failing tests for data models**

```python
# tests/test_imagination.py
"""Tests for the imagination loop — continuous DMN content production."""

from agents.imagination import ContentReference, ImaginationFragment


def test_content_reference_construction():
    ref = ContentReference(
        kind="text",
        source="hello world",
        query=None,
        salience=0.5,
    )
    assert ref.kind == "text"
    assert ref.source == "hello world"
    assert ref.salience == 0.5


def test_content_reference_with_query():
    ref = ContentReference(
        kind="qdrant_query",
        source="profile-facts",
        query="operator work style",
        salience=0.8,
    )
    assert ref.query == "operator work style"


def test_imagination_fragment_construction():
    ref = ContentReference(kind="text", source="test", query=None, salience=0.3)
    frag = ImaginationFragment(
        content_references=[ref],
        dimensions={"intensity": 0.5, "tension": 0.2},
        salience=0.3,
        continuation=False,
        narrative="A quiet moment.",
        parent_id=None,
    )
    assert frag.id  # UUID auto-generated
    assert frag.timestamp > 0
    assert len(frag.content_references) == 1
    assert frag.salience == 0.3
    assert not frag.continuation


def test_fragment_dimension_keys_are_medium_agnostic():
    """Dimensions should NOT have visual_chain. or vocal_chain. prefix."""
    frag = ImaginationFragment(
        content_references=[],
        dimensions={"intensity": 0.5, "coherence": 0.3},
        salience=0.1,
        continuation=False,
        narrative="test",
        parent_id=None,
    )
    for key in frag.dimensions:
        assert "." not in key, f"Dimension key '{key}' should be medium-agnostic"


VALID_DIMENSION_NAMES = {
    "intensity", "tension", "diffusion", "degradation", "depth",
    "pitch_displacement", "temporal_distortion", "spectral_color", "coherence",
}


def test_fragment_serialization_roundtrip():
    ref = ContentReference(kind="camera_frame", source="overhead", query=None, salience=0.7)
    frag = ImaginationFragment(
        content_references=[ref],
        dimensions={"intensity": 0.8},
        salience=0.6,
        continuation=True,
        narrative="The overhead camera shows an empty desk.",
        parent_id="abc123",
    )
    data = frag.model_dump()
    restored = ImaginationFragment.model_validate(data)
    assert restored.id == frag.id
    assert restored.content_references[0].kind == "camera_frame"
    assert restored.continuation is True
    assert restored.parent_id == "abc123"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_imagination.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agents.imagination'`

- [ ] **Step 3: Write the data models**

```python
# agents/imagination.py
"""Imagination loop — continuous DMN content production.

An independent process that reads DMN observations and sensor state,
produces structured ImaginationFragment objects via LLM, and publishes
them to a shm bus. High-salience fragments escalate as impingements.
"""

from __future__ import annotations

import json
import logging
import time as time_mod
import uuid
from pathlib import Path

from pydantic import BaseModel, Field

from shared.impingement import Impingement, ImpingementType

log = logging.getLogger("imagination")

SHM_DIR = Path("/dev/shm/hapax-imagination")
CURRENT_PATH = SHM_DIR / "current.json"
STREAM_PATH = SHM_DIR / "stream.jsonl"
STREAM_MAX_LINES = 50

ESCALATION_THRESHOLD = 0.6


class ContentReference(BaseModel, frozen=True):
    """Pointer to renderable content. Surfaces resolve these."""

    kind: str  # "qdrant_query", "camera_frame", "text", "url", "file", "audio_clip"
    source: str  # collection name, camera ID, URL, file path, or literal text
    query: str | None = None  # for qdrant_query: the search text
    salience: float = Field(ge=0.0, le=1.0)


class ImaginationFragment(BaseModel, frozen=True):
    """A single output of the imagination loop."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: float = Field(default_factory=time_mod.time)
    content_references: list[ContentReference]
    dimensions: dict[str, float]  # 9 expressive dimensions, medium-agnostic keys
    salience: float = Field(ge=0.0, le=1.0)
    continuation: bool
    narrative: str  # 1-2 sentence natural language (logging, not rendering)
    parent_id: str | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_imagination.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add agents/imagination.py tests/test_imagination.py
git commit -m "feat(imagination): ContentReference and ImaginationFragment data models"
```

---

### Task 2: SHM Publisher

**Files:**
- Modify: `agents/imagination.py`
- Modify: `tests/test_imagination.py`

- [ ] **Step 1: Write the failing tests for shm publishing**

Add to `tests/test_imagination.py`:

```python
import json
from pathlib import Path

from agents.imagination import publish_fragment


def _make_fragment(**overrides) -> ImaginationFragment:
    defaults = dict(
        content_references=[ContentReference(kind="text", source="hello", query=None, salience=0.3)],
        dimensions={"intensity": 0.4},
        salience=0.2,
        continuation=False,
        narrative="idle thought",
        parent_id=None,
    )
    defaults.update(overrides)
    return ImaginationFragment(**defaults)


def test_publish_writes_current_json(tmp_path: Path):
    frag = _make_fragment()
    current = tmp_path / "current.json"
    stream = tmp_path / "stream.jsonl"
    publish_fragment(frag, current_path=current, stream_path=stream)

    assert current.exists()
    data = json.loads(current.read_text())
    assert data["id"] == frag.id
    assert data["narrative"] == "idle thought"


def test_publish_appends_to_stream(tmp_path: Path):
    current = tmp_path / "current.json"
    stream = tmp_path / "stream.jsonl"

    for i in range(3):
        frag = _make_fragment(narrative=f"thought {i}")
        publish_fragment(frag, current_path=current, stream_path=stream)

    lines = stream.read_text().strip().split("\n")
    assert len(lines) == 3
    assert json.loads(lines[0])["narrative"] == "thought 0"
    assert json.loads(lines[2])["narrative"] == "thought 2"


def test_publish_caps_stream_at_max(tmp_path: Path):
    current = tmp_path / "current.json"
    stream = tmp_path / "stream.jsonl"

    for i in range(60):
        frag = _make_fragment(narrative=f"thought {i}")
        publish_fragment(frag, current_path=current, stream_path=stream, max_lines=10)

    lines = stream.read_text().strip().split("\n")
    assert len(lines) == 10
    # Most recent should be last
    assert json.loads(lines[-1])["narrative"] == "thought 59"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_imagination.py::test_publish_writes_current_json -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement publish_fragment**

Add to `agents/imagination.py`:

```python
def publish_fragment(
    fragment: ImaginationFragment,
    current_path: Path | None = None,
    stream_path: Path | None = None,
    max_lines: int = STREAM_MAX_LINES,
) -> None:
    """Publish a fragment to the shm bus (atomic current.json + rolling stream.jsonl)."""
    current_path = current_path or CURRENT_PATH
    stream_path = stream_path or STREAM_PATH

    current_path.parent.mkdir(parents=True, exist_ok=True)
    data = fragment.model_dump()
    json_str = json.dumps(data)

    # Atomic write to current.json
    tmp = current_path.with_suffix(".json.tmp")
    tmp.write_text(json_str)
    tmp.rename(current_path)

    # Append to stream.jsonl with rolling cap
    with stream_path.open("a") as f:
        f.write(json_str + "\n")

    # Cap stream file
    if stream_path.exists():
        lines = stream_path.read_text().strip().split("\n")
        if len(lines) > max_lines:
            stream_path.write_text("\n".join(lines[-max_lines:]) + "\n")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_imagination.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add agents/imagination.py tests/test_imagination.py
git commit -m "feat(imagination): shm publisher with atomic current.json and rolling stream.jsonl"
```

---

### Task 3: Escalation (Fragment → Impingement)

**Files:**
- Modify: `agents/imagination.py`
- Modify: `tests/test_imagination.py`

- [ ] **Step 1: Write the failing tests for escalation**

Add to `tests/test_imagination.py`:

```python
from agents.imagination import maybe_escalate, ESCALATION_THRESHOLD
from shared.impingement import Impingement


def test_escalate_above_threshold():
    frag = _make_fragment(salience=0.8, narrative="Something important noticed")
    result = maybe_escalate(frag)
    assert result is not None
    assert isinstance(result, Impingement)
    assert result.source == "imagination"
    assert result.strength == 0.8
    assert result.content["narrative"] == "Something important noticed"


def test_no_escalate_below_threshold():
    frag = _make_fragment(salience=0.3)
    result = maybe_escalate(frag)
    assert result is None


def test_escalate_at_exact_threshold():
    frag = _make_fragment(salience=ESCALATION_THRESHOLD)
    result = maybe_escalate(frag)
    assert result is not None


def test_escalate_preserves_content_references():
    ref = ContentReference(kind="qdrant_query", source="profile-facts", query="stress", salience=0.9)
    frag = _make_fragment(
        content_references=[ref],
        salience=0.7,
    )
    result = maybe_escalate(frag)
    assert result is not None
    refs = result.content["content_references"]
    assert len(refs) == 1
    assert refs[0]["kind"] == "qdrant_query"


def test_escalate_includes_dimensions_in_context():
    frag = _make_fragment(
        dimensions={"intensity": 0.8, "tension": 0.6},
        salience=0.7,
    )
    result = maybe_escalate(frag)
    assert result is not None
    assert result.context["dimensions"]["intensity"] == 0.8
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_imagination.py::test_escalate_above_threshold -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement maybe_escalate**

Add to `agents/imagination.py`:

```python
def maybe_escalate(fragment: ImaginationFragment) -> Impingement | None:
    """If fragment salience exceeds threshold, create an Impingement for the cascade."""
    if fragment.salience < ESCALATION_THRESHOLD:
        return None

    return Impingement(
        id=fragment.id,
        timestamp=fragment.timestamp,
        source="imagination",
        type=ImpingementType.SALIENCE_INTEGRATION,
        strength=fragment.salience,
        content={
            "narrative": fragment.narrative,
            "content_references": [ref.model_dump() for ref in fragment.content_references],
            "continuation": fragment.continuation,
        },
        context={"dimensions": fragment.dimensions},
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_imagination.py -v`
Expected: 13 passed

- [ ] **Step 5: Commit**

```bash
git add agents/imagination.py tests/test_imagination.py
git commit -m "feat(imagination): escalation — high-salience fragments become impingements"
```

---

### Task 4: Cadence Controller

**Files:**
- Modify: `agents/imagination.py`
- Modify: `tests/test_imagination.py`

- [ ] **Step 1: Write the failing tests for cadence logic**

Add to `tests/test_imagination.py`:

```python
from agents.imagination import CadenceController


def test_cadence_starts_at_base():
    cc = CadenceController(base_s=12.0, accelerated_s=4.0)
    assert cc.current_interval() == 12.0


def test_cadence_accelerates_on_continuation_with_salience():
    cc = CadenceController(base_s=12.0, accelerated_s=4.0)
    frag = _make_fragment(continuation=True, salience=0.4)
    cc.update(frag)
    assert cc.current_interval() == 4.0


def test_cadence_does_not_accelerate_on_low_salience():
    cc = CadenceController(base_s=12.0, accelerated_s=4.0, salience_threshold=0.3)
    frag = _make_fragment(continuation=True, salience=0.1)
    cc.update(frag)
    assert cc.current_interval() == 12.0


def test_cadence_does_not_accelerate_without_continuation():
    cc = CadenceController(base_s=12.0, accelerated_s=4.0)
    frag = _make_fragment(continuation=False, salience=0.8)
    cc.update(frag)
    assert cc.current_interval() == 12.0


def test_cadence_decelerates_after_three_non_continuations():
    cc = CadenceController(base_s=12.0, accelerated_s=4.0, decel_count=3)
    # Accelerate first
    cc.update(_make_fragment(continuation=True, salience=0.5))
    assert cc.current_interval() == 4.0
    # Three non-continuations
    cc.update(_make_fragment(continuation=False, salience=0.1))
    cc.update(_make_fragment(continuation=False, salience=0.1))
    assert cc.current_interval() == 4.0  # not yet
    cc.update(_make_fragment(continuation=False, salience=0.1))
    assert cc.current_interval() == 12.0  # now decelerated


def test_cadence_tpn_suppression():
    cc = CadenceController(base_s=12.0, accelerated_s=4.0)
    cc.set_tpn_active(True)
    assert cc.current_interval() == 24.0  # doubled

    cc.update(_make_fragment(continuation=True, salience=0.5))
    assert cc.current_interval() == 8.0  # accelerated but still doubled
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_imagination.py::test_cadence_starts_at_base -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement CadenceController**

Add to `agents/imagination.py`:

```python
class CadenceController:
    """Variable tick cadence for the imagination loop."""

    def __init__(
        self,
        base_s: float = 12.0,
        accelerated_s: float = 4.0,
        salience_threshold: float = 0.3,
        decel_count: int = 3,
    ) -> None:
        self._base_s = base_s
        self._accelerated_s = accelerated_s
        self._salience_threshold = salience_threshold
        self._decel_count = decel_count
        self._accelerated = False
        self._non_continuation_streak = 0
        self._tpn_active = False

    def update(self, fragment: ImaginationFragment) -> None:
        """Update cadence based on the latest fragment."""
        if fragment.continuation and fragment.salience > self._salience_threshold:
            self._accelerated = True
            self._non_continuation_streak = 0
        elif not fragment.continuation:
            self._non_continuation_streak += 1
            if self._non_continuation_streak >= self._decel_count:
                self._accelerated = False
        else:
            self._non_continuation_streak = 0

    def current_interval(self) -> float:
        """Current tick interval in seconds."""
        interval = self._accelerated_s if self._accelerated else self._base_s
        if self._tpn_active:
            interval *= 2.0
        return interval

    def set_tpn_active(self, active: bool) -> None:
        """Signal TPN activity (anti-correlation — slows imagination)."""
        self._tpn_active = active
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_imagination.py -v`
Expected: 19 passed

- [ ] **Step 5: Commit**

```bash
git add agents/imagination.py tests/test_imagination.py
git commit -m "feat(imagination): variable cadence controller with acceleration and TPN suppression"
```

---

### Task 5: Context Assembly

**Files:**
- Modify: `agents/imagination.py`
- Modify: `tests/test_imagination.py`

- [ ] **Step 1: Write the failing tests for context assembly**

Add to `tests/test_imagination.py`:

```python
from agents.imagination import assemble_context


def test_assemble_context_with_empty_sources():
    ctx = assemble_context(
        observations=[],
        recent_fragments=[],
        sensor_snapshot={},
    )
    assert "Current Observations" in ctx
    assert "System State" in ctx
    assert "Recent Imagination" in ctx


def test_assemble_context_includes_observations():
    ctx = assemble_context(
        observations=["Activity: coding. Flow: 0.8.", "Activity: idle. Flow: 0.2."],
        recent_fragments=[],
        sensor_snapshot={},
    )
    assert "coding" in ctx
    assert "idle" in ctx


def test_assemble_context_includes_recent_fragments():
    frag = _make_fragment(narrative="the desk was empty")
    ctx = assemble_context(
        observations=[],
        recent_fragments=[frag],
        sensor_snapshot={},
    )
    assert "the desk was empty" in ctx


def test_assemble_context_includes_sensor_snapshot():
    ctx = assemble_context(
        observations=[],
        recent_fragments=[],
        sensor_snapshot={
            "stimmung": {"stance": "cautious", "operator_stress": 0.6},
            "perception": {"activity": "active", "flow_score": 0.7},
            "watch": {"heart_rate": 85},
            "weather": {"condition": "rain", "temperature": 18},
        },
    )
    assert "cautious" in ctx
    assert "85" in ctx
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_imagination.py::test_assemble_context_with_empty_sources -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement assemble_context**

Add to `agents/imagination.py`:

```python
def assemble_context(
    observations: list[str],
    recent_fragments: list[ImaginationFragment],
    sensor_snapshot: dict,
) -> str:
    """Assemble the LLM prompt context from DMN observations, prior fragments, and sensors."""
    parts = []

    # DMN observations
    parts.append("## Current Observations (from DMN)")
    if observations:
        for obs in observations[-5:]:
            parts.append(f"- {obs}")
    else:
        parts.append("- (no recent observations)")

    # System state from sensors
    parts.append("\n## System State")
    stimmung = sensor_snapshot.get("stimmung", {})
    parts.append(f"Stance: {stimmung.get('stance', 'unknown')}")
    parts.append(f"Stress: {stimmung.get('operator_stress', 0):.2f}")

    perception = sensor_snapshot.get("perception", {})
    parts.append(f"Activity: {perception.get('activity', 'unknown')}")
    parts.append(f"Flow: {perception.get('flow_score', 0):.1f}")

    watch = sensor_snapshot.get("watch", {})
    hr = watch.get("heart_rate", 0)
    if hr > 0:
        parts.append(f"Heart rate: {hr} bpm")

    weather = sensor_snapshot.get("weather", {})
    if weather:
        parts.append(f"Weather: {weather.get('condition', '?')}, {weather.get('temperature', '?')}°C")

    # Recent imagination
    parts.append("\n## Recent Imagination")
    if recent_fragments:
        for frag in recent_fragments[-3:]:
            prefix = "(continuing) " if frag.continuation else ""
            parts.append(f"- {prefix}{frag.narrative}")
    else:
        parts.append("- (mind is quiet)")

    return "\n".join(parts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_imagination.py -v`
Expected: 23 passed

- [ ] **Step 5: Commit**

```bash
git add agents/imagination.py tests/test_imagination.py
git commit -m "feat(imagination): context assembly from DMN observations, sensors, prior fragments"
```

---

### Task 6: ImaginationLoop Class

**Files:**
- Modify: `agents/imagination.py`
- Modify: `tests/test_imagination.py`

- [ ] **Step 1: Write the failing tests for the loop class**

Add to `tests/test_imagination.py`:

```python
import asyncio
from unittest.mock import AsyncMock, patch

from agents.imagination import ImaginationLoop


def test_loop_construction():
    loop = ImaginationLoop()
    assert loop.cadence.current_interval() == 12.0
    assert len(loop.recent_fragments) == 0


def test_loop_stores_recent_fragments():
    loop = ImaginationLoop()
    frag = _make_fragment()
    loop._record_fragment(frag)
    assert len(loop.recent_fragments) == 1
    assert loop.recent_fragments[0].id == frag.id


def test_loop_caps_recent_fragments():
    loop = ImaginationLoop()
    for i in range(10):
        loop._record_fragment(_make_fragment(narrative=f"thought {i}"))
    assert len(loop.recent_fragments) == 5  # capped at 5


def test_loop_drains_impingements():
    loop = ImaginationLoop()
    frag = _make_fragment(salience=0.8)
    loop._process_fragment(frag)
    pending = loop.drain_impingements()
    assert len(pending) == 1
    assert pending[0].source == "imagination"
    # Second drain is empty
    assert len(loop.drain_impingements()) == 0


def test_loop_no_impingement_for_low_salience():
    loop = ImaginationLoop()
    frag = _make_fragment(salience=0.2)
    loop._process_fragment(frag)
    assert len(loop.drain_impingements()) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_imagination.py::test_loop_construction -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement ImaginationLoop**

Add to `agents/imagination.py`:

```python
IMAGINATION_SYSTEM_PROMPT = """You are the imagination process of a personal computing system. You observe
the system's current state and produce spontaneous associations, memories,
projections, and novel connections — the way a human mind wanders during
idle moments.

Your output is a structured fragment describing what you're currently
"imagining." This is not evaluation or analysis — it is free association
grounded in what you observe.

Content sources you can reference:
- camera_frame: overhead, hero, left, right (live camera feeds)
- qdrant_query: profile-facts, documents, operator-episodes, studio-moments (vector knowledge)
- text: any text you want to display
- url: any image URL
- file: any file path

Produce one ImaginationFragment. Be specific in content_references —
point to real things. Set dimensional coloring to match the emotional
tone of what you're imagining. Assess salience honestly — most fragments
are low salience (0.1-0.3). Only mark high salience (>0.6) for genuine
insights or concerns worth escalating.

If your previous fragment had continuation=true, you may continue that
train of thought or let it go. Don't force continuation."""

MAX_RECENT_FRAGMENTS = 5


class ImaginationLoop:
    """Independent imagination process — reads DMN state, produces fragments."""

    def __init__(
        self,
        current_path: Path | None = None,
        stream_path: Path | None = None,
    ) -> None:
        self.cadence = CadenceController()
        self.recent_fragments: list[ImaginationFragment] = []
        self._pending_impingements: list[Impingement] = []
        self._current_path = current_path or CURRENT_PATH
        self._stream_path = stream_path or STREAM_PATH
        self._agent: Any = None  # lazy-init pydantic-ai agent

    def _get_agent(self) -> Any:
        """Lazy-init the pydantic-ai agent for structured output."""
        if self._agent is None:
            from pydantic_ai import Agent

            from shared.config import get_model

            self._agent = Agent(
                get_model("reasoning"),
                output_type=ImaginationFragment,
                system_prompt=IMAGINATION_SYSTEM_PROMPT,
            )
        return self._agent

    def _record_fragment(self, fragment: ImaginationFragment) -> None:
        """Store fragment in recent history (capped)."""
        self.recent_fragments.append(fragment)
        if len(self.recent_fragments) > MAX_RECENT_FRAGMENTS:
            self.recent_fragments = self.recent_fragments[-MAX_RECENT_FRAGMENTS:]

    def _process_fragment(self, fragment: ImaginationFragment) -> None:
        """Record fragment, publish to bus, check escalation."""
        self._record_fragment(fragment)
        publish_fragment(
            fragment,
            current_path=self._current_path,
            stream_path=self._stream_path,
        )
        self.cadence.update(fragment)

        imp = maybe_escalate(fragment)
        if imp is not None:
            self._pending_impingements.append(imp)
            log.info(
                "Imagination escalated: salience=%.2f narrative=%s",
                fragment.salience,
                fragment.narrative[:60],
            )

    def drain_impingements(self) -> list[Impingement]:
        """Return and clear pending impingements. Called by cascade broadcaster."""
        pending = self._pending_impingements[:]
        self._pending_impingements.clear()
        return pending

    def set_tpn_active(self, active: bool) -> None:
        """Signal TPN activity to cadence controller."""
        self.cadence.set_tpn_active(active)

    async def tick(self, observations: list[str], sensor_snapshot: dict) -> None:
        """Run one imagination tick — assemble context, call LLM, process fragment."""
        context = assemble_context(
            observations=observations,
            recent_fragments=self.recent_fragments,
            sensor_snapshot=sensor_snapshot,
        )

        try:
            agent = self._get_agent()
            result = await agent.run(context)
            fragment = result.output
            self._process_fragment(fragment)
            log.debug(
                "Imagination tick: salience=%.2f cont=%s narrative=%s",
                fragment.salience,
                fragment.continuation,
                fragment.narrative[:60],
            )
        except Exception as exc:
            log.warning("Imagination tick failed: %s", exc)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_imagination.py -v`
Expected: 28 passed

- [ ] **Step 5: Commit**

```bash
git add agents/imagination.py tests/test_imagination.py
git commit -m "feat(imagination): ImaginationLoop class with LLM agent, fragment processing, escalation"
```
