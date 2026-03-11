# Studio-Aware Unified Perception Layer Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a unified perception layer that fuses audio-visual signals into an EnvironmentState, governs the active Pipecat pipeline via a FrameGate processor, and detects studio conditions (conversation, production) to enforce behavioral constraints.

**Architecture:** A `PerceptionEngine` runs dual-cadence tick loops (fast 2-3s for VAD/face, slow 10-15s for PANNs/LLM) producing frozen `EnvironmentState` snapshots. A `PipelineGovernor` maps each state to a directive (process/pause/withdraw). A `FrameGate` Pipecat FrameProcessor sits before STT and drops audio frames on `pause`. The existing `ContextGate` is simplified to delegate to the perception engine. Session timeout pauses during conversation mode.

**Tech Stack:** Python 3.12, Pipecat 0.0.104 (FrameProcessor, AudioRawFrame), Silero VAD, MTCNN/mediapipe face detection, PANNs CNN14, asyncio, Pydantic, pytest + unittest.mock

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `agents/hapax_voice/perception.py` | `EnvironmentState` frozen dataclass + `PerceptionEngine` class (tick loops, signal fusion, subscriber notification) |
| `agents/hapax_voice/governor.py` | `PipelineGovernor` class (maps EnvironmentState → directive string) |
| `agents/hapax_voice/frame_gate.py` | `FrameGate(FrameProcessor)` for Pipecat pipeline (drops/passes audio frames based on directive) |
| `tests/test_perception.py` | Tests for EnvironmentState and PerceptionEngine |
| `tests/test_governor.py` | Tests for PipelineGovernor directive logic |
| `tests/test_frame_gate.py` | Tests for FrameGate frame filtering |

### Modified Files

| File | Lines | Changes |
|------|-------|---------|
| `agents/hapax_voice/config.py:21-117` | Add 6 perception config fields to `VoiceConfig` |
| `agents/hapax_voice/presence.py:61-82` | Add `latest_vad_confidence` property to `PresenceDetector` |
| `agents/hapax_voice/session.py:14-78` | Add `pause()`, `resume()`, `is_paused` property |
| `agents/hapax_voice/context_gate.py:21-164` | Simplify: add `set_environment_state()`, delegate activity mode check to perception |
| `agents/hapax_voice/pipeline.py:133-194` | Accept optional `FrameGate`, insert before STT in pipeline |
| `agents/hapax_voice/__main__.py:60-610` | Wire PerceptionEngine + Governor into daemon lifecycle |

---

## Chunk 1: Core Data Model + Config

### Task 1: Add perception config fields to VoiceConfig

**Files:**
- Modify: `agents/hapax_voice/config.py:76-84` (after workspace analysis fields)
- Test: `tests/test_hapax_voice_config.py` (existing, add new test)

- [ ] **Step 1: Write the failing test**

In `tests/test_hapax_voice_config.py`, add:

```python
def test_perception_config_defaults():
    """Perception fields have sensible defaults."""
    from agents.hapax_voice.config import VoiceConfig
    cfg = VoiceConfig()
    assert cfg.perception_fast_tick_s == 2.5
    assert cfg.perception_slow_tick_s == 12.0
    assert cfg.conversation_debounce_s == 3.0
    assert cfg.gaze_resume_clear_s == 5.0
    assert cfg.environment_clear_resume_s == 15.0
    assert cfg.operator_absent_withdraw_s == 60.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_config.py::test_perception_config_defaults -v`
Expected: FAIL with `AttributeError: 'VoiceConfig' object has no attribute 'perception_fast_tick_s'`

- [ ] **Step 3: Add config fields**

In `agents/hapax_voice/config.py`, after line 84 (`timelapse_path`), add:

```python
    # Perception layer
    perception_fast_tick_s: float = 2.5
    perception_slow_tick_s: float = 12.0
    conversation_debounce_s: float = 3.0
    gaze_resume_clear_s: float = 5.0
    environment_clear_resume_s: float = 15.0
    operator_absent_withdraw_s: float = 60.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_config.py::test_perception_config_defaults -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agents/hapax_voice/config.py tests/test_hapax_voice_config.py
git commit -m "feat(voice): add perception layer config fields"
```

---

### Task 2: Add latest_vad_confidence to PresenceDetector

`PerceptionEngine` needs to read the latest VAD confidence from `PresenceDetector`, but the class currently only stores events above threshold — it discards the actual probability. We need to expose it.

**Files:**
- Modify: `agents/hapax_voice/presence.py:61-82`
- Modify: `tests/test_hapax_voice_presence.py` (existing)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_hapax_voice_presence.py`:

```python
def test_latest_vad_confidence_stored():
    """PresenceDetector stores the most recent VAD probability."""
    det = PresenceDetector(vad_threshold=0.4)
    assert det.latest_vad_confidence == 0.0  # default

    # Simulate processing with a mock model
    with patch.object(det, "load_model") as mock_load:
        mock_model = MagicMock(return_value=torch.tensor(0.75))
        mock_load.return_value = mock_model
        prob = det.process_audio_frame(b"\x00" * 960)  # 480 samples
        assert prob == pytest.approx(0.75, abs=0.01)
        assert det.latest_vad_confidence == pytest.approx(0.75, abs=0.01)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_presence.py::test_latest_vad_confidence_stored -v`
Expected: FAIL with `AttributeError: 'PresenceDetector' object has no attribute 'latest_vad_confidence'`

- [ ] **Step 3: Add latest_vad_confidence to PresenceDetector**

In `agents/hapax_voice/presence.py`:

Add field in `__init__` (after line 39, `self._last_score`):

```python
        self._latest_vad_confidence: float = 0.0
```

Add property (after the `event_count` property at the end of the class):

```python
    @property
    def latest_vad_confidence(self) -> float:
        """Most recent VAD probability (0.0-1.0), regardless of threshold."""
        return self._latest_vad_confidence
```

In `process_audio_frame` (line 79, after `probability: float = model(tensor, SAMPLE_RATE).item()`), add:

```python
        self._latest_vad_confidence = probability
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_presence.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add agents/hapax_voice/presence.py tests/test_hapax_voice_presence.py
git commit -m "feat(voice): expose latest_vad_confidence on PresenceDetector"
```

---

### Task 3: Create EnvironmentState dataclass

**Files:**
- Create: `agents/hapax_voice/perception.py`
- Create: `tests/test_perception.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_perception.py`:

```python
"""Tests for the perception layer."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from agents.hapax_voice.perception import EnvironmentState


def test_environment_state_is_frozen():
    """EnvironmentState should be immutable."""
    state = EnvironmentState(timestamp=time.monotonic())
    with pytest.raises(AttributeError):
        state.speech_detected = True


def test_environment_state_defaults():
    """Default state: nothing detected, process directive."""
    state = EnvironmentState(timestamp=time.monotonic())
    assert state.speech_detected is False
    assert state.face_count == 0
    assert state.operator_present is False
    assert state.gaze_at_camera is False
    assert state.conversation_detected is False
    assert state.activity_mode == "unknown"
    assert state.ambient_class == "silence"
    assert state.directive == "process"


def test_environment_state_conversation_detected():
    """conversation_detected is True when face_count > 1 AND speech_detected."""
    state = EnvironmentState(
        timestamp=time.monotonic(),
        face_count=2,
        speech_detected=True,
    )
    assert state.conversation_detected is True


def test_environment_state_no_conversation_single_face():
    """Single face + speech is NOT conversation."""
    state = EnvironmentState(
        timestamp=time.monotonic(),
        face_count=1,
        speech_detected=True,
    )
    assert state.conversation_detected is False


def test_environment_state_no_conversation_no_speech():
    """Multiple faces without speech is NOT conversation."""
    state = EnvironmentState(
        timestamp=time.monotonic(),
        face_count=3,
        speech_detected=False,
    )
    assert state.conversation_detected is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_perception.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agents.hapax_voice.perception'`

- [ ] **Step 3: Create perception.py with EnvironmentState**

Create `agents/hapax_voice/perception.py`:

```python
"""Unified perception layer for the Hapax Voice daemon.

Fuses audio and visual signals into a single EnvironmentState snapshot
every fast tick (2-3s). Slow enrichment (10-15s) adds LLM workspace
analysis and PANNs ambient classification.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class EnvironmentState:
    """Immutable snapshot of the fused audio-visual environment.

    Produced by PerceptionEngine every fast tick. Slow-tick fields
    (activity_mode, workspace_context, ambient_detailed) are carried
    forward from the last slow enrichment.
    """

    timestamp: float

    # Audio signals (fast tick)
    speech_detected: bool = False
    speech_volume_db: float = -60.0
    ambient_class: str = "silence"
    vad_confidence: float = 0.0

    # Visual signals (fast tick)
    face_count: int = 0
    operator_present: bool = False
    gaze_at_camera: bool = False

    # Enriched signals (slow tick, carried forward)
    activity_mode: str = "unknown"
    workspace_context: str = ""
    ambient_detailed: str = ""

    # Directive (set by Governor after creation)
    directive: str = "process"

    @property
    def conversation_detected(self) -> bool:
        """True when multiple faces AND speech detected."""
        return self.face_count > 1 and self.speech_detected
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_perception.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add agents/hapax_voice/perception.py tests/test_perception.py
git commit -m "feat(voice): add EnvironmentState dataclass for unified perception"
```

---

### Task 4: Add pause/resume to VoiceLifecycle

**Files:**
- Modify: `agents/hapax_voice/session.py:14-78`
- Modify: `tests/test_hapax_voice_session.py` (existing)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_hapax_voice_session.py`:

```python
def test_pause_stops_timeout_clock():
    """Paused sessions should not time out."""
    session = VoiceLifecycle(silence_timeout_s=1)
    session.open(trigger="wake_word")
    session.pause(reason="conversation")
    assert session.is_paused is True
    time.sleep(1.5)
    assert session.is_timed_out is False  # paused, clock frozen


def test_resume_restarts_timeout_clock():
    """Resuming resets the activity timestamp."""
    session = VoiceLifecycle(silence_timeout_s=1)
    session.open(trigger="wake_word")
    session.pause(reason="conversation")
    time.sleep(0.5)
    session.resume()
    assert session.is_paused is False
    assert session.is_timed_out is False  # just resumed


def test_pause_noop_when_idle():
    """Pausing an idle session does nothing."""
    session = VoiceLifecycle(silence_timeout_s=30)
    session.pause(reason="test")
    assert session.is_paused is False
    assert session.state == "idle"


def test_resume_noop_when_not_paused():
    """Resuming a non-paused session does nothing harmful."""
    session = VoiceLifecycle(silence_timeout_s=30)
    session.open(trigger="wake_word")
    session.resume()  # should not raise
    assert session.is_paused is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_session.py::test_pause_stops_timeout_clock -v`
Expected: FAIL with `AttributeError: 'VoiceLifecycle' object has no attribute 'pause'`

- [ ] **Step 3: Add pause/resume to VoiceLifecycle**

In `agents/hapax_voice/session.py`, add a `_paused` field in `__init__` and new methods:

After line 30 (`self._opened_at: float = 0.0`), add:

```python
        self._paused: bool = False
```

After the `mark_activity` method (after line 74), add:

```python
    @property
    def is_paused(self) -> bool:
        return self.is_active and self._paused

    def pause(self, reason: str = "") -> None:
        """Pause the timeout clock. Session stays active but won't time out."""
        if not self.is_active:
            return
        self._paused = True
        log.info("Session paused (reason=%s)", reason)

    def resume(self) -> None:
        """Resume the timeout clock, resetting activity timestamp."""
        if not self.is_active or not self._paused:
            return
        self._paused = False
        self._last_activity = time.monotonic()
        log.info("Session resumed")
```

Modify the `is_timed_out` property (lines 41-44) to respect pause:

```python
    @property
    def is_timed_out(self) -> bool:
        if not self.is_active or self._paused:
            return False
        return (time.monotonic() - self._last_activity) > self.silence_timeout_s
```

Also reset `_paused` in `close()` — after line 67 (`self.speaker_confidence = 0.0`), add:

```python
        self._paused = False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_session.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add agents/hapax_voice/session.py tests/test_hapax_voice_session.py
git commit -m "feat(voice): add pause/resume to VoiceLifecycle for conversation mode"
```

---

## Chunk 2: PipelineGovernor + FrameGate

### Task 5: Create PipelineGovernor

**Files:**
- Create: `agents/hapax_voice/governor.py`
- Create: `tests/test_governor.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_governor.py`:

```python
"""Tests for PipelineGovernor."""
from __future__ import annotations

import time

import pytest

from agents.hapax_voice.perception import EnvironmentState
from agents.hapax_voice.governor import PipelineGovernor


def _state(**overrides) -> EnvironmentState:
    """Helper to build EnvironmentState with overrides."""
    defaults = dict(timestamp=time.monotonic())
    defaults.update(overrides)
    return EnvironmentState(**defaults)


def test_process_when_operator_present():
    gov = PipelineGovernor()
    state = _state(operator_present=True, face_count=1)
    assert gov.evaluate(state) == "process"


def test_pause_on_conversation():
    """face_count > 1 + speech → pause."""
    gov = PipelineGovernor()
    state = _state(face_count=2, speech_detected=True, operator_present=True)
    assert gov.evaluate(state) == "pause"


def test_pause_on_production_mode():
    gov = PipelineGovernor()
    state = _state(activity_mode="production", operator_present=True)
    assert gov.evaluate(state) == "pause"


def test_pause_on_meeting_mode():
    gov = PipelineGovernor()
    state = _state(activity_mode="meeting", operator_present=True)
    assert gov.evaluate(state) == "pause"


def test_withdraw_on_operator_absent():
    """No face for longer than threshold → withdraw."""
    gov = PipelineGovernor(operator_absent_withdraw_s=5.0)
    # Simulate absence: operator_present=False for >5s
    gov._last_operator_seen = time.monotonic() - 10.0
    state = _state(operator_present=False, face_count=0)
    assert gov.evaluate(state) == "withdraw"


def test_no_withdraw_if_recently_seen():
    """Operator absent but within threshold → pause, not withdraw."""
    gov = PipelineGovernor(operator_absent_withdraw_s=60.0)
    gov._last_operator_seen = time.monotonic() - 5.0
    state = _state(operator_present=False, face_count=0)
    assert gov.evaluate(state) == "process"


def test_wake_word_override():
    """wake_word_active=True forces process regardless of other signals."""
    gov = PipelineGovernor()
    gov.wake_word_active = True
    state = _state(face_count=3, speech_detected=True, activity_mode="production")
    assert gov.evaluate(state) == "process"
    # Clears after evaluation
    assert gov.wake_word_active is False


def test_conversation_debounce():
    """Conversation must persist for debounce_s before triggering pause."""
    gov = PipelineGovernor(conversation_debounce_s=3.0)
    # First detection — not yet debounced
    state = _state(face_count=2, speech_detected=True, operator_present=True)
    assert gov.evaluate(state) == "process"  # within debounce
    # Simulate time passing beyond debounce
    gov._conversation_first_seen = time.monotonic() - 4.0
    assert gov.evaluate(state) == "pause"  # debounce expired


def test_no_conversation_resets_debounce():
    """When conversation signal disappears, debounce timer resets."""
    gov = PipelineGovernor(conversation_debounce_s=3.0)
    # Start conversation
    conv_state = _state(face_count=2, speech_detected=True, operator_present=True)
    gov.evaluate(conv_state)
    assert gov._conversation_first_seen is not None
    # Conversation ends
    clear_state = _state(face_count=1, speech_detected=False, operator_present=True)
    gov.evaluate(clear_state)
    assert gov._conversation_first_seen is None


def test_environment_clear_auto_resume():
    """After conversation ends, auto-resume after environment_clear_resume_s."""
    gov = PipelineGovernor(
        conversation_debounce_s=0,  # instant for test
        environment_clear_resume_s=5.0,
    )
    # Enter conversation pause
    conv_state = _state(face_count=2, speech_detected=True, operator_present=True)
    assert gov.evaluate(conv_state) == "pause"
    assert gov._paused_by_conversation is True

    # Environment clears but within resume delay
    gov._conversation_cleared_at = time.monotonic() - 2.0
    clear_state = _state(face_count=1, speech_detected=False, operator_present=True)
    assert gov.evaluate(clear_state) == "pause"  # still paused, within delay

    # Environment clear long enough
    gov._conversation_cleared_at = time.monotonic() - 6.0
    assert gov.evaluate(clear_state) == "process"  # auto-resumed


def test_environment_clear_resume_resets_on_new_conversation():
    """If conversation resumes during clear delay, timer resets."""
    gov = PipelineGovernor(
        conversation_debounce_s=0,
        environment_clear_resume_s=5.0,
    )
    # Enter conversation
    conv_state = _state(face_count=2, speech_detected=True, operator_present=True)
    gov.evaluate(conv_state)
    # Briefly clear
    gov._conversation_cleared_at = time.monotonic() - 2.0
    clear_state = _state(face_count=1, speech_detected=False, operator_present=True)
    gov.evaluate(clear_state)
    # Conversation returns
    gov.evaluate(conv_state)
    assert gov._conversation_cleared_at is None  # reset
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_governor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agents.hapax_voice.governor'`

- [ ] **Step 3: Create governor.py**

Create `agents/hapax_voice/governor.py`:

```python
"""Pipeline governor — maps EnvironmentState to pipeline directives.

Directives:
  - "process": pipeline runs normally, audio flows to STT
  - "pause": FrameGate drops audio frames, pipeline frozen
  - "withdraw": session should close gracefully
"""
from __future__ import annotations

import logging
import time

from agents.hapax_voice.perception import EnvironmentState

log = logging.getLogger(__name__)


class PipelineGovernor:
    """Evaluates EnvironmentState and returns a directive string.

    The governor maintains minimal state for debouncing and absence
    tracking. It does NOT own the perception engine or the frame gate —
    it's a pure evaluator that the daemon calls each tick.
    """

    def __init__(
        self,
        conversation_debounce_s: float = 3.0,
        operator_absent_withdraw_s: float = 60.0,
        environment_clear_resume_s: float = 15.0,
    ) -> None:
        self.conversation_debounce_s = conversation_debounce_s
        self.operator_absent_withdraw_s = operator_absent_withdraw_s
        self.environment_clear_resume_s = environment_clear_resume_s

        # Internal state
        self._last_operator_seen: float = time.monotonic()
        self._conversation_first_seen: float | None = None
        self._paused_by_conversation: bool = False
        self._conversation_cleared_at: float | None = None
        self.wake_word_active: bool = False

    def evaluate(self, state: EnvironmentState) -> str:
        """Evaluate environment state and return directive.

        Args:
            state: Current EnvironmentState snapshot.

        Returns:
            One of "process", "pause", "withdraw".
        """
        # Wake word always overrides — immediate process
        if self.wake_word_active:
            self.wake_word_active = False
            self._conversation_first_seen = None
            self._paused_by_conversation = False
            self._conversation_cleared_at = None
            return "process"

        # Track operator presence for withdraw detection
        if state.operator_present:
            self._last_operator_seen = time.monotonic()

        # Production/meeting mode → pause
        if state.activity_mode in ("production", "meeting"):
            return "pause"

        # Conversation detection with debounce
        if state.conversation_detected:
            self._conversation_cleared_at = None  # reset clear timer
            now = time.monotonic()
            if self._conversation_first_seen is None:
                self._conversation_first_seen = now
            elapsed = now - self._conversation_first_seen
            if elapsed >= self.conversation_debounce_s:
                self._paused_by_conversation = True
                return "pause"
        else:
            self._conversation_first_seen = None

            # Environment-clear auto-resume (resume signal 3)
            if self._paused_by_conversation:
                now = time.monotonic()
                if self._conversation_cleared_at is None:
                    self._conversation_cleared_at = now
                clear_elapsed = now - self._conversation_cleared_at
                if clear_elapsed < self.environment_clear_resume_s:
                    return "pause"  # still within clear delay
                # Clear delay expired — auto-resume
                self._paused_by_conversation = False
                self._conversation_cleared_at = None

        # Operator absence → withdraw
        if not state.operator_present and state.face_count == 0:
            absent_s = time.monotonic() - self._last_operator_seen
            if absent_s > self.operator_absent_withdraw_s:
                return "withdraw"

        return "process"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_governor.py -v`
Expected: ALL PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add agents/hapax_voice/governor.py tests/test_governor.py
git commit -m "feat(voice): add PipelineGovernor for environment-based pipeline control"
```

---

### Task 6: Create FrameGate Pipecat processor

**Files:**
- Create: `agents/hapax_voice/frame_gate.py`
- Create: `tests/test_frame_gate.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_frame_gate.py`:

```python
"""Tests for FrameGate Pipecat processor."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.hapax_voice.frame_gate import FrameGate


@pytest.mark.asyncio
async def test_passes_audio_on_process():
    """Audio frames pass through when directive is 'process'."""
    from pipecat.frames.frames import AudioRawFrame
    from pipecat.processors.frame_processor import FrameDirection

    gate = FrameGate()
    gate.set_directive("process")
    gate.push_frame = AsyncMock()

    frame = AudioRawFrame(audio=b"\x00" * 960, sample_rate=16000, num_channels=1)
    await gate.process_frame(frame, FrameDirection.DOWNSTREAM)

    gate.push_frame.assert_called_once_with(frame, FrameDirection.DOWNSTREAM)


@pytest.mark.asyncio
async def test_drops_audio_on_pause():
    """Audio frames are dropped when directive is 'pause'."""
    from pipecat.frames.frames import AudioRawFrame
    from pipecat.processors.frame_processor import FrameDirection

    gate = FrameGate()
    gate.set_directive("pause")
    gate.push_frame = AsyncMock()

    frame = AudioRawFrame(audio=b"\x00" * 960, sample_rate=16000, num_channels=1)
    await gate.process_frame(frame, FrameDirection.DOWNSTREAM)

    gate.push_frame.assert_not_called()


@pytest.mark.asyncio
async def test_passes_control_frames_on_pause():
    """Non-audio frames (control frames) pass through even on pause."""
    from pipecat.frames.frames import Frame, StartFrame
    from pipecat.processors.frame_processor import FrameDirection

    gate = FrameGate()
    gate.set_directive("pause")
    gate.push_frame = AsyncMock()

    frame = StartFrame()
    await gate.process_frame(frame, FrameDirection.DOWNSTREAM)

    gate.push_frame.assert_called_once()


@pytest.mark.asyncio
async def test_counts_dropped_frames():
    """Gate tracks how many frames it has dropped."""
    from pipecat.frames.frames import AudioRawFrame
    from pipecat.processors.frame_processor import FrameDirection

    gate = FrameGate()
    gate.set_directive("pause")
    gate.push_frame = AsyncMock()

    frame = AudioRawFrame(audio=b"\x00" * 960, sample_rate=16000, num_channels=1)
    await gate.process_frame(frame, FrameDirection.DOWNSTREAM)
    await gate.process_frame(frame, FrameDirection.DOWNSTREAM)

    assert gate.dropped_count == 2


def test_directive_default_is_process():
    gate = FrameGate()
    assert gate.directive == "process"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_frame_gate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agents.hapax_voice.frame_gate'`

- [ ] **Step 3: Create frame_gate.py**

Create `agents/hapax_voice/frame_gate.py`:

```python
"""FrameGate — Pipecat processor that gates audio based on governor directive.

Inserted before STT in the pipeline:
  transport.input() → FrameGate → STT → ...

On "process": all frames pass through.
On "pause": audio frames are dropped, control frames pass.
On "withdraw": not handled here (daemon closes session externally).
"""
from __future__ import annotations

import logging

from pipecat.frames.frames import AudioRawFrame, Frame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

log = logging.getLogger(__name__)


class FrameGate(FrameProcessor):
    """Gates audio frames based on an external directive.

    The governor sets the directive via set_directive(). When paused,
    audio frames are silently dropped while control frames (start, stop,
    end-of-stream) pass through to keep Pipecat's lifecycle intact.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._directive: str = "process"
        self._dropped_count: int = 0

    @property
    def directive(self) -> str:
        return self._directive

    @property
    def dropped_count(self) -> int:
        return self._dropped_count

    def set_directive(self, directive: str) -> None:
        """Update the gate directive. Called by the daemon on each governor tick."""
        if directive != self._directive:
            log.info("FrameGate directive: %s → %s", self._directive, directive)
            self._directive = directive

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Process or drop frames based on current directive."""
        if self._directive == "pause" and isinstance(frame, AudioRawFrame):
            self._dropped_count += 1
            return  # drop audio frame

        await self.push_frame(frame, direction)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_frame_gate.py -v`
Expected: ALL PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add agents/hapax_voice/frame_gate.py tests/test_frame_gate.py
git commit -m "feat(voice): add FrameGate Pipecat processor for audio gating"
```

---

### Task 7: Insert FrameGate into pipeline construction

**Files:**
- Modify: `agents/hapax_voice/pipeline.py:133-194`
- Modify: `tests/test_hapax_voice_pipeline.py` (existing)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_hapax_voice_pipeline.py`:

```python
def test_frame_gate_inserted_before_stt():
    """When a FrameGate is provided, it appears before STT in pipeline."""
    from unittest.mock import MagicMock, patch
    from agents.hapax_voice.frame_gate import FrameGate

    gate = FrameGate()

    with patch("agents.hapax_voice.pipeline.LocalAudioTransport") as MockTransport, \
         patch("agents.hapax_voice.pipeline.WhisperSTTService") as MockSTT, \
         patch("agents.hapax_voice.pipeline.OpenAILLMService") as MockLLM, \
         patch("agents.hapax_voice.pipeline.KokoroTTSService") as MockTTS, \
         patch("agents.hapax_voice.pipeline.Pipeline") as MockPipeline, \
         patch("agents.hapax_voice.pipeline.PipelineTask") as MockTask, \
         patch("agents.hapax_voice.pipeline.system_prompt", return_value="test"):

        mock_transport = MockTransport.return_value
        mock_transport.input.return_value = MagicMock()
        mock_transport.output.return_value = MagicMock()
        mock_llm = MockLLM.return_value
        mock_llm.create_context_aggregator.return_value = MagicMock(
            user=MagicMock(return_value=MagicMock()),
            assistant=MagicMock(return_value=MagicMock()),
        )

        with patch("agents.hapax_voice.pipeline.get_tool_schemas", return_value=None), \
             patch("agents.hapax_voice.pipeline.register_tool_handlers"):
            from agents.hapax_voice.pipeline import build_pipeline_task
            build_pipeline_task(frame_gate=gate)

        # Check the processors list passed to Pipeline
        call_kwargs = MockPipeline.call_args
        processors = call_kwargs.kwargs.get("processors") or call_kwargs[1].get("processors") or call_kwargs[0][0] if call_kwargs[0] else None
        # FrameGate should be in the processors list
        if call_kwargs.kwargs and "processors" in call_kwargs.kwargs:
            processors = call_kwargs.kwargs["processors"]
        else:
            processors = call_kwargs[1]["processors"]

        # Find positions
        gate_idx = processors.index(gate)
        stt_idx = next(i for i, p in enumerate(processors) if p == MockSTT.return_value)
        assert gate_idx < stt_idx, "FrameGate must be before STT"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_pipeline.py::test_frame_gate_inserted_before_stt -v`
Expected: FAIL with `TypeError: build_pipeline_task() got an unexpected keyword argument 'frame_gate'`

- [ ] **Step 3: Add frame_gate parameter to build_pipeline_task**

In `agents/hapax_voice/pipeline.py`, modify `build_pipeline_task` signature (line 133) to accept `frame_gate`:

Add import at the top of the file (after line 10):

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.hapax_voice.frame_gate import FrameGate
```

Modify function signature (line 133-142) to add `frame_gate` parameter:

```python
def build_pipeline_task(
    *,
    stt_model: str = "large-v3",
    llm_model: str = "claude-sonnet",
    kokoro_voice: str = "af_heart",
    guest_mode: bool = False,
    config=None,
    webcam_capturer=None,
    screen_capturer=None,
    frame_gate: FrameGate | None = None,
) -> tuple[PipelineTask, LocalAudioTransport]:
```

Modify the pipeline processors list (lines 180-190). Replace:

```python
    pipeline = Pipeline(
        processors=[
            transport.input(),
            stt,
            context_aggregator.user(),
            llm,
            tts,
            transport.output(),
            context_aggregator.assistant(),
        ]
    )
```

With:

```python
    # Build processor chain, optionally inserting FrameGate before STT
    processors = [transport.input()]
    if frame_gate is not None:
        processors.append(frame_gate)
    processors.extend([
        stt,
        context_aggregator.user(),
        llm,
        tts,
        transport.output(),
        context_aggregator.assistant(),
    ])

    pipeline = Pipeline(processors=processors)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_pipeline.py -v`
Expected: ALL PASS (existing tests still pass + new test passes)

- [ ] **Step 5: Commit**

```bash
git add agents/hapax_voice/pipeline.py tests/test_hapax_voice_pipeline.py
git commit -m "feat(voice): insert FrameGate before STT in Pipecat pipeline"
```

---

## Chunk 3: PerceptionEngine

### Task 8: Build PerceptionEngine with fast tick

**Files:**
- Modify: `agents/hapax_voice/perception.py` (add PerceptionEngine class)
- Modify: `tests/test_perception.py` (add engine tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_perception.py`:

```python
from agents.hapax_voice.perception import PerceptionEngine


def _make_mock_presence(**overrides):
    """Create a mock PresenceDetector with sensible defaults."""
    defaults = dict(
        score="likely_present",
        face_detected=True,
        face_count=1,
        latest_vad_confidence=0.0,
    )
    defaults.update(overrides)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _make_mock_workspace_monitor():
    m = MagicMock()
    m.latest_analysis = None
    m.has_camera.return_value = True
    return m


def test_engine_produces_state():
    """Engine tick produces an EnvironmentState."""
    presence = _make_mock_presence()
    engine = PerceptionEngine(
        presence=presence,
        workspace_monitor=_make_mock_workspace_monitor(),
    )
    state = engine.tick()
    assert isinstance(state, EnvironmentState)
    assert state.operator_present is True  # face_detected=True
    assert state.face_count == 1


def test_engine_detects_speech():
    """High VAD confidence → speech_detected."""
    presence = _make_mock_presence(latest_vad_confidence=0.85)
    engine = PerceptionEngine(
        presence=presence,
        workspace_monitor=_make_mock_workspace_monitor(),
    )
    state = engine.tick()
    assert state.speech_detected is True
    assert state.vad_confidence == 0.85


def test_engine_carries_forward_slow_fields():
    """Slow-tick fields carry forward between fast ticks."""
    engine = PerceptionEngine(
        presence=_make_mock_presence(),
        workspace_monitor=_make_mock_workspace_monitor(),
    )
    # Simulate slow enrichment setting activity mode
    engine._slow_activity_mode = "coding"
    engine._slow_ambient_detailed = "keyboard_typing"
    state = engine.tick()
    assert state.activity_mode == "coding"
    assert state.ambient_detailed == "keyboard_typing"


def test_engine_notifies_subscribers():
    """Subscribers receive each new state."""
    received = []
    engine = PerceptionEngine(
        presence=_make_mock_presence(),
        workspace_monitor=_make_mock_workspace_monitor(),
    )
    engine.subscribe(received.append)
    engine.tick()
    assert len(received) == 1
    assert isinstance(received[0], EnvironmentState)


def test_engine_gaze_defaults_false():
    """Gaze detection defaults to False (b-path: proper model later)."""
    engine = PerceptionEngine(
        presence=_make_mock_presence(),
        workspace_monitor=_make_mock_workspace_monitor(),
    )
    state = engine.tick()
    assert state.gaze_at_camera is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_perception.py::test_engine_produces_state -v`
Expected: FAIL with `ImportError: cannot import name 'PerceptionEngine'`

- [ ] **Step 3: Add PerceptionEngine to perception.py**

Append to `agents/hapax_voice/perception.py`:

```python
class PerceptionEngine:
    """Produces EnvironmentState snapshots by fusing sensor signals.

    Fast tick (called every ~2.5s): reads VAD, face detection, gaze.
    Slow enrichment (called every ~12s): runs PANNs, workspace analysis.
    Slow fields are carried forward between slow ticks.

    The engine does not own its own async loop — the daemon calls tick()
    on the fast cadence and slow_tick() on the slow cadence.
    """

    def __init__(
        self,
        presence,
        workspace_monitor,
        vad_speech_threshold: float = 0.5,
    ) -> None:
        self._presence = presence
        self._workspace_monitor = workspace_monitor
        self._vad_speech_threshold = vad_speech_threshold

        # Slow-tick carried-forward fields
        self._slow_activity_mode: str = "unknown"
        self._slow_workspace_context: str = ""
        self._slow_ambient_detailed: str = ""
        self._slow_ambient_class: str = "silence"

        # Subscribers
        self._subscribers: list[Callable[[EnvironmentState], None]] = []

        # Latest state
        self.latest: EnvironmentState | None = None

    def subscribe(self, callback: Callable[[EnvironmentState], None]) -> None:
        """Register a callback for each new EnvironmentState."""
        self._subscribers.append(callback)

    def tick(self) -> EnvironmentState:
        """Produce a fast-tick EnvironmentState from current sensor readings.

        Reads from presence detector (VAD + face) and carries forward
        slow-tick enrichment fields.
        """
        vad_conf = getattr(self._presence, "latest_vad_confidence", 0.0)
        face_detected = getattr(self._presence, "face_detected", False)
        face_count = getattr(self._presence, "face_count", 0)

        state = EnvironmentState(
            timestamp=time.monotonic(),
            speech_detected=vad_conf >= self._vad_speech_threshold,
            vad_confidence=vad_conf,
            ambient_class=self._slow_ambient_class,
            face_count=face_count,
            operator_present=face_detected,
            gaze_at_camera=False,  # b-path: proper gaze model
            activity_mode=self._slow_activity_mode,
            workspace_context=self._slow_workspace_context,
            ambient_detailed=self._slow_ambient_detailed,
        )

        self.latest = state

        for cb in self._subscribers:
            try:
                cb(state)
            except Exception:
                log.exception("Perception subscriber error")

        return state

    def update_slow_fields(
        self,
        activity_mode: str | None = None,
        workspace_context: str | None = None,
        ambient_class: str | None = None,
        ambient_detailed: str | None = None,
    ) -> None:
        """Update carried-forward fields from slow-tick enrichment."""
        if activity_mode is not None:
            self._slow_activity_mode = activity_mode
        if workspace_context is not None:
            self._slow_workspace_context = workspace_context
        if ambient_class is not None:
            self._slow_ambient_class = ambient_class
        if ambient_detailed is not None:
            self._slow_ambient_detailed = ambient_detailed
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_perception.py -v`
Expected: ALL PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add agents/hapax_voice/perception.py tests/test_perception.py
git commit -m "feat(voice): add PerceptionEngine with fast-tick signal fusion"
```

---

## Chunk 4: Daemon Integration

### Task 9: Simplify ContextGate to use PerceptionEngine

**Files:**
- Modify: `agents/hapax_voice/context_gate.py`
- Modify: `tests/test_hapax_voice_context_gate.py` (existing)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_hapax_voice_context_gate.py`:

```python
def test_gate_respects_environment_state_conversation():
    """Gate blocks when EnvironmentState shows conversation."""
    from agents.hapax_voice.perception import EnvironmentState
    import time

    session = SessionManager(silence_timeout_s=30)
    gate = ContextGate(session=session)
    state = EnvironmentState(
        timestamp=time.monotonic(),
        activity_mode="conversation",
    )
    gate.set_environment_state(state)
    gate.set_activity_mode("conversation")
    result = gate.check()
    assert not result.eligible
    assert "conversation" in result.reason.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_context_gate.py::test_gate_respects_environment_state_conversation -v`
Expected: FAIL with `AttributeError: 'ContextGate' object has no attribute 'set_environment_state'`

- [ ] **Step 3: Add set_environment_state and conversation blocking**

In `agents/hapax_voice/context_gate.py`, add after `set_event_log` method (line 49):

```python
    def set_environment_state(self, state) -> None:
        """Accept latest EnvironmentState from perception engine."""
        self._environment_state = state
```

Add `self._environment_state = None` to `__init__` (after line 43):

```python
        self._environment_state = None
```

Modify `_check_activity_mode` (lines 87-90) to also block on "conversation":

```python
    def _check_activity_mode(self) -> GateResult:
        if self._activity_mode in ("production", "meeting", "conversation"):
            return GateResult(eligible=False, reason=f"Blocked: {self._activity_mode} mode active")
        return GateResult(eligible=True, reason="")
```

- [ ] **Step 4: Run all context gate tests**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_context_gate.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add agents/hapax_voice/context_gate.py tests/test_hapax_voice_context_gate.py
git commit -m "feat(voice): extend ContextGate with environment state and conversation blocking"
```

---

### Task 10: Wire PerceptionEngine + Governor into VoiceDaemon

This is the integration task. It modifies `__main__.py` to:
1. Create PerceptionEngine and Governor on init
2. Create FrameGate and pass to pipeline builder
3. Run perception tick loops as background tasks
4. Apply governor directives to FrameGate and session

**Files:**
- Modify: `agents/hapax_voice/__main__.py`
- Modify: `tests/test_hapax_voice_daemon_pipeline.py` (existing)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_hapax_voice_daemon_pipeline.py`:

```python
def test_daemon_creates_perception_engine():
    """VoiceDaemon initializes a PerceptionEngine."""
    from agents.hapax_voice.__main__ import VoiceDaemon
    from agents.hapax_voice.config import VoiceConfig
    from unittest.mock import patch, MagicMock

    with patch("agents.hapax_voice.__main__.AudioInputStream"), \
         patch("agents.hapax_voice.__main__.WorkspaceMonitor") as MockWM, \
         patch("agents.hapax_voice.__main__.TTSManager"), \
         patch("agents.hapax_voice.__main__.ChimePlayer"), \
         patch("agents.hapax_voice.__main__.EventLog"), \
         patch("agents.hapax_voice.__main__.VoiceTracer"):
        MockWM.return_value.set_notification_queue = MagicMock()
        MockWM.return_value.set_presence = MagicMock()
        MockWM.return_value.set_event_log = MagicMock()
        MockWM.return_value.set_tracer = MagicMock()
        daemon = VoiceDaemon(cfg=VoiceConfig())
        assert hasattr(daemon, 'perception')
        assert hasattr(daemon, 'governor')
        assert hasattr(daemon, '_frame_gate')


def test_daemon_passes_frame_gate_to_pipeline():
    """Pipeline builder receives the FrameGate."""
    from agents.hapax_voice.__main__ import VoiceDaemon
    from agents.hapax_voice.config import VoiceConfig
    from unittest.mock import patch, MagicMock, AsyncMock

    with patch("agents.hapax_voice.__main__.AudioInputStream") as MockAI, \
         patch("agents.hapax_voice.__main__.WorkspaceMonitor") as MockWM, \
         patch("agents.hapax_voice.__main__.TTSManager"), \
         patch("agents.hapax_voice.__main__.ChimePlayer"), \
         patch("agents.hapax_voice.__main__.EventLog"), \
         patch("agents.hapax_voice.__main__.VoiceTracer"), \
         patch("agents.hapax_voice.__main__.PorcupineWakeWord") as MockWW:
        MockWM.return_value.set_notification_queue = MagicMock()
        MockWM.return_value.set_presence = MagicMock()
        MockWM.return_value.set_event_log = MagicMock()
        MockWM.return_value.set_tracer = MagicMock()
        MockWW.return_value.on_wake_word = None
        MockAI.return_value.is_active = True
        daemon = VoiceDaemon(cfg=VoiceConfig())

    with patch("agents.hapax_voice.pipeline.build_pipeline_task") as mock_build:
        mock_build.return_value = (MagicMock(), MagicMock())
        with patch("pipecat.pipeline.runner.PipelineRunner"):
            import asyncio
            asyncio.get_event_loop().run_until_complete(daemon._start_local_pipeline())
            # Verify frame_gate was passed
            call_kwargs = mock_build.call_args
            assert "frame_gate" in call_kwargs.kwargs
            assert call_kwargs.kwargs["frame_gate"] is daemon._frame_gate
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_daemon_pipeline.py::test_daemon_creates_perception_engine -v`
Expected: FAIL with `AssertionError` (daemon doesn't have `perception` attribute yet)

- [ ] **Step 3: Wire perception into VoiceDaemon**

In `agents/hapax_voice/__main__.py`:

**Add imports** (after line 29):

```python
from agents.hapax_voice.perception import PerceptionEngine
from agents.hapax_voice.governor import PipelineGovernor
from agents.hapax_voice.frame_gate import FrameGate
```

**Add initialization** in `__init__` (after line 126, after workspace_monitor setup):

```python
        # Perception layer
        self.perception = PerceptionEngine(
            presence=self.presence,
            workspace_monitor=self.workspace_monitor,
        )
        self.governor = PipelineGovernor(
            conversation_debounce_s=self.cfg.conversation_debounce_s,
            operator_absent_withdraw_s=self.cfg.operator_absent_withdraw_s,
            environment_clear_resume_s=self.cfg.environment_clear_resume_s,
        )
        self._frame_gate = FrameGate()
```

**Modify `_start_local_pipeline`** (around line 275) to pass frame_gate:

Change:

```python
            task, transport = build_pipeline_task(
                stt_model=self.cfg.local_stt_model,
                llm_model=self.cfg.llm_model,
                kokoro_voice=self.cfg.kokoro_voice,
                guest_mode=guest_mode,
                config=self.cfg,
                webcam_capturer=getattr(self.workspace_monitor, "webcam_capturer", None),
                screen_capturer=getattr(self.workspace_monitor, "screen_capturer", None),
            )
```

To:

```python
            task, transport = build_pipeline_task(
                stt_model=self.cfg.local_stt_model,
                llm_model=self.cfg.llm_model,
                kokoro_voice=self.cfg.kokoro_voice,
                guest_mode=guest_mode,
                config=self.cfg,
                webcam_capturer=getattr(self.workspace_monitor, "webcam_capturer", None),
                screen_capturer=getattr(self.workspace_monitor, "screen_capturer", None),
                frame_gate=self._frame_gate,
            )
```

**Add perception tick loop** as a new method (after `_proactive_delivery_loop`):

```python
    async def _perception_loop(self) -> None:
        """Run perception fast tick + governor evaluation on cadence."""
        while self._running:
            try:
                await asyncio.sleep(self.cfg.perception_fast_tick_s)

                # Fast tick: read sensors, produce EnvironmentState
                state = self.perception.tick()

                # Governor: evaluate state → directive
                directive = self.governor.evaluate(state)

                # Apply directive to FrameGate
                self._frame_gate.set_directive(directive)

                # Apply directive to session
                if directive == "pause" and self.session.is_active and not self.session.is_paused:
                    self.session.pause(reason=f"governor:{state.activity_mode}")
                elif directive == "process" and self.session.is_paused:
                    self.session.resume()
                elif directive == "withdraw" and self.session.is_active:
                    await self._close_session(reason="operator_absent")

                # Update context gate with latest state
                self.gate.set_environment_state(state)

            except asyncio.CancelledError:
                break
            except Exception:
                log.exception("Error in perception loop")
```

**Add slow enrichment to existing workspace analysis update** in `run()` method. Modify the activity mode update block (around line 585-588):

Change:

```python
                # Update activity mode from latest workspace analysis
                analysis = self.workspace_monitor.latest_analysis
                if analysis is not None:
                    mode = classify_activity_mode(analysis)
                    self.gate.set_activity_mode(mode)
```

To:

```python
                # Update activity mode from latest workspace analysis
                analysis = self.workspace_monitor.latest_analysis
                if analysis is not None:
                    mode = classify_activity_mode(analysis)
                    self.gate.set_activity_mode(mode)
                    self.perception.update_slow_fields(activity_mode=mode)
```

**Start perception loop** as a background task in `run()` (after the audio loop task creation, around line 568):

```python
        self._background_tasks.append(
            asyncio.create_task(self._perception_loop())
        )
```

**Wire wake word to governor** in `_on_wake_word` (around line 364):

Add before the session open:

```python
            self.governor.wake_word_active = True
            self._frame_gate.set_directive("process")
```

- [ ] **Step 4: Run all daemon tests**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_daemon_pipeline.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run the full test suite to check for regressions**

Run: `cd ~/projects/ai-agents && uv run pytest tests/ -q --tb=short 2>&1 | tail -20`
Expected: All tests pass (no regressions)

- [ ] **Step 6: Commit**

```bash
git add agents/hapax_voice/__main__.py tests/test_hapax_voice_daemon_pipeline.py
git commit -m "feat(voice): wire PerceptionEngine + Governor + FrameGate into VoiceDaemon"
```

---

### Task 11: Add perception loop integration test

**Files:**
- Create: `tests/test_perception_integration.py`

- [ ] **Step 1: Write integration test**

Create `tests/test_perception_integration.py`:

```python
"""Integration test: perception → governor → frame gate → session."""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from agents.hapax_voice.perception import PerceptionEngine, EnvironmentState
from agents.hapax_voice.governor import PipelineGovernor
from agents.hapax_voice.frame_gate import FrameGate
from agents.hapax_voice.session import VoiceLifecycle


def _mock_presence(**overrides):
    defaults = dict(
        score="likely_present",
        face_detected=True,
        face_count=1,
        latest_vad_confidence=0.0,
    )
    defaults.update(overrides)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def test_full_chain_process():
    """Normal state: perception → governor → process → gate passes."""
    presence = _mock_presence()
    engine = PerceptionEngine(presence=presence, workspace_monitor=MagicMock())
    governor = PipelineGovernor()
    gate = FrameGate()
    session = VoiceLifecycle(silence_timeout_s=30)
    session.open(trigger="test")

    state = engine.tick()
    directive = governor.evaluate(state)
    gate.set_directive(directive)

    assert directive == "process"
    assert gate.directive == "process"
    assert not session.is_paused


def test_full_chain_conversation_pause():
    """Conversation detected → governor pauses → gate blocks."""
    presence = _mock_presence(face_count=2, latest_vad_confidence=0.9)
    engine = PerceptionEngine(presence=presence, workspace_monitor=MagicMock())
    governor = PipelineGovernor(conversation_debounce_s=0)  # instant for test
    gate = FrameGate()
    session = VoiceLifecycle(silence_timeout_s=30)
    session.open(trigger="test")

    state = engine.tick()
    assert state.conversation_detected is True

    directive = governor.evaluate(state)
    gate.set_directive(directive)

    assert directive == "pause"
    assert gate.directive == "pause"


def test_full_chain_wake_word_overrides():
    """Wake word overrides conversation pause."""
    presence = _mock_presence(face_count=2, latest_vad_confidence=0.9)
    engine = PerceptionEngine(presence=presence, workspace_monitor=MagicMock())
    governor = PipelineGovernor(conversation_debounce_s=0)
    gate = FrameGate()

    governor.wake_word_active = True
    state = engine.tick()
    directive = governor.evaluate(state)
    gate.set_directive(directive)

    assert directive == "process"


def test_full_chain_withdraw():
    """Operator absent > threshold → governor withdraws."""
    presence = _mock_presence(face_detected=False, face_count=0)
    engine = PerceptionEngine(presence=presence, workspace_monitor=MagicMock())
    governor = PipelineGovernor(operator_absent_withdraw_s=5.0)
    governor._last_operator_seen = time.monotonic() - 10.0

    state = engine.tick()
    directive = governor.evaluate(state)

    assert directive == "withdraw"


def test_slow_enrichment_updates_state():
    """Slow-tick activity mode update flows through to next fast tick."""
    presence = _mock_presence()
    engine = PerceptionEngine(presence=presence, workspace_monitor=MagicMock())
    governor = PipelineGovernor()

    engine.update_slow_fields(activity_mode="production")
    state = engine.tick()
    directive = governor.evaluate(state)

    assert state.activity_mode == "production"
    assert directive == "pause"
```

- [ ] **Step 2: Run integration tests**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_perception_integration.py -v`
Expected: ALL PASS (5 tests)

- [ ] **Step 3: Commit**

```bash
git add tests/test_perception_integration.py
git commit -m "test(voice): add perception → governor → frame gate integration tests"
```

---

## Chunk 5: Final Verification

### Task 12: Run full test suite and verify no regressions

- [ ] **Step 1: Run full test suite**

Run: `cd ~/projects/ai-agents && uv run pytest tests/ -q --tb=short 2>&1 | tail -30`
Expected: All 1524+ tests pass, plus ~25 new tests from this plan

- [ ] **Step 2: Run just the new perception tests**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_perception.py tests/test_governor.py tests/test_frame_gate.py tests/test_perception_integration.py -v`
Expected: All new tests pass

- [ ] **Step 3: Verify imports are clean**

Run: `cd ~/projects/ai-agents && uv run python -c "from agents.hapax_voice.perception import PerceptionEngine, EnvironmentState; from agents.hapax_voice.governor import PipelineGovernor; from agents.hapax_voice.frame_gate import FrameGate; print('All imports OK')"`
Expected: "All imports OK"

- [ ] **Step 4: Final commit (if any test fixes needed)**

```bash
git add -A
git commit -m "fix(voice): address test regressions from perception layer integration"
```

---

## B-Path Items (tracked, not implemented)

These are documented in the design spec and should be addressed in future iterations:

1. **Speaker isolation via voice enrollment** — audio-only conversation detection
2. **Richer activity mode taxonomy** — monitoring, recording, active_production
3. **Proper gaze estimation** — MediaPipe face mesh for accurate gaze vector (currently returns `False`)
4. **Real-time (<1s) perception** — sub-tick response for high-value signals
5. **PipeWire echo cancellation** — PyAudio can't access virtual nodes
6. **TTSSettings NOT_GIVEN fix** — in pipecat_tts.py
7. **Pipecat LLMContext migration** — OpenAILLMContext → LLMContext
8. **Streaming TTS** — lower latency synthesis
9. **Silero VAD threshold tuning** — optimize for studio environment
