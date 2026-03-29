# Vocal Imagination Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Imagination bus fragments influence conversation in two ways: context injection (salience-graded "Current Thoughts" in LLM prompt) and proactive utterance (system speaks unprompted when gate conditions pass).

**Architecture:** Two independent modules. `imagination_context.py` reads `stream.jsonl` and formats a prompt section. `proactive_gate.py` checks operator presence, VAD, conversational gap, TPN, and cooldown. Both are pure functions/classes with no daemon dependencies — integration into the voice daemon is a separate task.

**Tech Stack:** Python 3.12, pydantic (ImaginationFragment), pytest

---

## File Structure

| File | Responsibility |
|------|---------------|
| `agents/imagination_context.py` | `format_imagination_context(stream_path) -> str` — read stream.jsonl, format salience-graded prompt section |
| `agents/proactive_gate.py` | `ProactiveGate` class — gate checks for proactive utterance (salience, presence, VAD, gap, TPN, cooldown) |
| `tests/test_imagination_context.py` | Tests for context formatting |
| `tests/test_proactive_gate.py` | Tests for gate conditions |

---

### Task 1: Imagination Context Formatter

**Files:**
- Create: `agents/imagination_context.py`
- Create: `tests/test_imagination_context.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_imagination_context.py
"""Tests for imagination context injection into conversation LLM prompt."""

import json
from pathlib import Path

from agents.imagination_context import format_imagination_context


def _write_stream(path: Path, fragments: list[dict]) -> None:
    with path.open("w") as f:
        for frag in fragments:
            f.write(json.dumps(frag) + "\n")


def test_empty_stream(tmp_path: Path):
    stream = tmp_path / "stream.jsonl"
    result = format_imagination_context(stream)
    assert "Current Thoughts" in result
    assert "(mind is quiet)" in result


def test_missing_stream_file(tmp_path: Path):
    stream = tmp_path / "nonexistent.jsonl"
    result = format_imagination_context(stream)
    assert "Current Thoughts" in result
    assert "(mind is quiet)" in result


def test_single_low_salience_fragment(tmp_path: Path):
    stream = tmp_path / "stream.jsonl"
    _write_stream(stream, [
        {"narrative": "The desk is quiet.", "salience": 0.2, "continuation": False},
    ])
    result = format_imagination_context(stream)
    assert "(background)" in result
    assert "The desk is quiet." in result


def test_active_thought_salience(tmp_path: Path):
    stream = tmp_path / "stream.jsonl"
    _write_stream(stream, [
        {"narrative": "A connection between drift and scout.", "salience": 0.5, "continuation": False},
    ])
    result = format_imagination_context(stream)
    assert "(active thought)" in result
    assert "A connection between drift and scout." in result


def test_high_salience_still_active_thought(tmp_path: Path):
    stream = tmp_path / "stream.jsonl"
    _write_stream(stream, [
        {"narrative": "Critical insight about inference.", "salience": 0.8, "continuation": False},
    ])
    result = format_imagination_context(stream)
    assert "(active thought)" in result


def test_only_last_five_fragments(tmp_path: Path):
    stream = tmp_path / "stream.jsonl"
    frags = [{"narrative": f"thought {i}", "salience": 0.2, "continuation": False} for i in range(8)]
    _write_stream(stream, frags)
    result = format_imagination_context(stream)
    assert "thought 3" in result  # 4th from end (index 3 of last 5)
    assert "thought 7" in result  # last
    assert "thought 2" not in result  # too old


def test_continuation_prefix(tmp_path: Path):
    stream = tmp_path / "stream.jsonl"
    _write_stream(stream, [
        {"narrative": "Continuing that thought.", "salience": 0.3, "continuation": True},
    ])
    result = format_imagination_context(stream)
    assert "(continuing)" in result


def test_malformed_lines_skipped(tmp_path: Path):
    stream = tmp_path / "stream.jsonl"
    with stream.open("w") as f:
        f.write("not valid json\n")
        f.write(json.dumps({"narrative": "valid", "salience": 0.3, "continuation": False}) + "\n")
        f.write("{broken\n")
    result = format_imagination_context(stream)
    assert "valid" in result
    # Should not crash on malformed lines
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_imagination_context.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement imagination_context.py**

```python
# agents/imagination_context.py
"""Imagination context injection — formats recent imagination fragments for LLM prompt.

Reads /dev/shm/hapax-imagination/stream.jsonl and produces a salience-graded
"Current Thoughts" section for the conversation LLM's system prompt.

Salience grading:
  < 0.4  → "(background)" — passive context, subtle influence
  ≥ 0.4  → "(active thought)" — system may reference if relevant
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("imagination.context")

STREAM_PATH = Path("/dev/shm/hapax-imagination/stream.jsonl")
MAX_FRAGMENTS = 5
ACTIVE_THRESHOLD = 0.4


def format_imagination_context(stream_path: Path | None = None) -> str:
    """Read recent imagination fragments and format as a conversation prompt section."""
    path = stream_path or STREAM_PATH
    fragments = _read_recent_fragments(path)

    lines = ["## Current Thoughts", "These are things you've been thinking about recently.", ""]

    if not fragments:
        lines.append("- (mind is quiet)")
    else:
        for frag in fragments:
            narrative = frag.get("narrative", "")
            salience = frag.get("salience", 0.0)
            continuation = frag.get("continuation", False)

            if salience >= ACTIVE_THRESHOLD:
                prefix = "(active thought)"
            else:
                prefix = "(background)"

            cont_marker = "(continuing) " if continuation else ""
            lines.append(f"- {prefix} {cont_marker}{narrative}")

    if fragments:
        lines.append("")
        lines.append(
            "You may reference active thoughts if relevant to conversation. "
            "If asked what you're thinking about, draw from these."
        )

    return "\n".join(lines)


def _read_recent_fragments(path: Path) -> list[dict]:
    """Read last N fragments from stream.jsonl, skipping malformed lines."""
    if not path.exists():
        return []

    fragments = []
    try:
        text = path.read_text().strip()
        if not text:
            return []
        for line in text.split("\n"):
            try:
                frag = json.loads(line)
                if "narrative" in frag:
                    fragments.append(frag)
            except (json.JSONDecodeError, ValueError):
                continue
    except OSError:
        return []

    return fragments[-MAX_FRAGMENTS:]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_imagination_context.py -v`
Expected: 8 passed

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check agents/imagination_context.py tests/test_imagination_context.py && uv run ruff format agents/imagination_context.py tests/test_imagination_context.py
git add agents/imagination_context.py tests/test_imagination_context.py
git commit -m "feat(imagination): context formatter — salience-graded Current Thoughts for conversation LLM"
```

---

### Task 2: Proactive Gate

**Files:**
- Create: `agents/proactive_gate.py`
- Create: `tests/test_proactive_gate.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_proactive_gate.py
"""Tests for proactive utterance gate — conditions for system-initiated speech."""

import time

from agents.imagination import ContentReference, ImaginationFragment
from agents.proactive_gate import ProactiveGate


def _make_fragment(salience: float = 0.9) -> ImaginationFragment:
    return ImaginationFragment(
        content_references=[ContentReference(kind="text", source="insight", query=None, salience=0.8)],
        dimensions={"intensity": 0.7},
        salience=salience,
        continuation=False,
        narrative="An important realization.",
    )


def _passing_state() -> dict:
    """State dict where all gate conditions pass."""
    return {
        "perception_activity": "active",
        "vad_active": False,
        "last_utterance_time": time.monotonic() - 60.0,  # 60s ago
        "tpn_active": False,
    }


def test_gate_passes_when_all_conditions_met():
    gate = ProactiveGate()
    frag = _make_fragment(salience=0.9)
    state = _passing_state()
    assert gate.should_speak(frag, state) is True


def test_gate_fails_low_salience():
    gate = ProactiveGate()
    frag = _make_fragment(salience=0.7)  # below 0.8
    state = _passing_state()
    assert gate.should_speak(frag, state) is False


def test_gate_fails_operator_not_present():
    gate = ProactiveGate()
    frag = _make_fragment()
    state = _passing_state()
    state["perception_activity"] = "idle"
    assert gate.should_speak(frag, state) is False


def test_gate_fails_operator_away():
    gate = ProactiveGate()
    frag = _make_fragment()
    state = _passing_state()
    state["perception_activity"] = "away"
    assert gate.should_speak(frag, state) is False


def test_gate_fails_vad_active():
    gate = ProactiveGate()
    frag = _make_fragment()
    state = _passing_state()
    state["vad_active"] = True
    assert gate.should_speak(frag, state) is False


def test_gate_fails_recent_utterance():
    gate = ProactiveGate()
    frag = _make_fragment()
    state = _passing_state()
    state["last_utterance_time"] = time.monotonic() - 10.0  # only 10s ago
    assert gate.should_speak(frag, state) is False


def test_gate_fails_tpn_active():
    gate = ProactiveGate()
    frag = _make_fragment()
    state = _passing_state()
    state["tpn_active"] = True
    assert gate.should_speak(frag, state) is False


def test_gate_fails_during_cooldown():
    gate = ProactiveGate()
    frag = _make_fragment()
    state = _passing_state()

    # First call passes
    assert gate.should_speak(frag, state) is True
    gate.record_utterance()

    # Immediate second call fails (cooldown)
    assert gate.should_speak(frag, state) is False


def test_cooldown_expires():
    gate = ProactiveGate(cooldown_s=0.0)  # instant cooldown for test
    frag = _make_fragment()
    state = _passing_state()

    gate.record_utterance()
    assert gate.should_speak(frag, state) is True  # cooldown already expired


def test_cooldown_resets_on_operator_speech():
    gate = ProactiveGate(cooldown_s=999.0)  # very long cooldown
    frag = _make_fragment()
    state = _passing_state()

    gate.record_utterance()
    assert gate.should_speak(frag, state) is False  # in cooldown

    gate.on_operator_speech()
    assert gate.should_speak(frag, state) is True  # cooldown cleared


def test_gate_fails_unknown_activity():
    gate = ProactiveGate()
    frag = _make_fragment()
    state = _passing_state()
    state["perception_activity"] = "unknown"
    assert gate.should_speak(frag, state) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_proactive_gate.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement proactive_gate.py**

```python
# agents/proactive_gate.py
"""Proactive utterance gate — conditions for system-initiated speech.

When imagination produces a high-salience fragment, this gate checks whether
the system should speak unprompted. All conditions must pass:
  - Fragment salience ≥ 0.8
  - Operator is present (activity not idle/away/unknown)
  - Operator is not speaking (no active VAD)
  - Conversational gap > 30s since last utterance
  - TPN not active (no ongoing deliberative processing)
  - Cooldown elapsed (120s since last proactive utterance)
"""

from __future__ import annotations

import logging
import time

from agents.imagination import ImaginationFragment

log = logging.getLogger("imagination.proactive")

SALIENCE_THRESHOLD = 0.8
GAP_THRESHOLD_S = 30.0
DEFAULT_COOLDOWN_S = 120.0
ABSENT_ACTIVITIES = {"idle", "away", "unknown"}


class ProactiveGate:
    """Gate that determines whether the system should speak unprompted."""

    def __init__(self, cooldown_s: float = DEFAULT_COOLDOWN_S) -> None:
        self._cooldown_s = cooldown_s
        self._last_proactive: float = 0.0  # monotonic time of last proactive utterance

    def should_speak(self, fragment: ImaginationFragment, state: dict) -> bool:
        """Check all gate conditions. Returns True only if ALL pass."""
        if fragment.salience < SALIENCE_THRESHOLD:
            return False

        activity = state.get("perception_activity", "unknown")
        if activity in ABSENT_ACTIVITIES:
            return False

        if state.get("vad_active", False):
            return False

        last_utterance = state.get("last_utterance_time", 0.0)
        if (time.monotonic() - last_utterance) < GAP_THRESHOLD_S:
            return False

        if state.get("tpn_active", False):
            return False

        if (time.monotonic() - self._last_proactive) < self._cooldown_s:
            return False

        return True

    def record_utterance(self) -> None:
        """Record that a proactive utterance was made (starts cooldown)."""
        self._last_proactive = time.monotonic()

    def on_operator_speech(self) -> None:
        """Operator started talking — clear cooldown."""
        self._last_proactive = 0.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_proactive_gate.py -v`
Expected: 11 passed

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check agents/proactive_gate.py tests/test_proactive_gate.py && uv run ruff format agents/proactive_gate.py tests/test_proactive_gate.py
git add agents/proactive_gate.py tests/test_proactive_gate.py
git commit -m "feat(imagination): proactive gate — conditions for system-initiated speech"
```
