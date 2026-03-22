# Voice Observability Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add structured JSONL event logging and Langfuse trace integration to hapax-voice audio-vision layers for debugging and improvement assessment.

**Architecture:** Two new modules — `event_log.py` (JSONL file writer with daily rotation) and `tracing.py` (Langfuse SDK wrapper). Both are instantiated in VoiceDaemon and passed to subsystems via setter methods. SessionManager gets a `session_id` field so events and traces can be correlated. All observability is fail-open — failures never crash the daemon.

**Tech Stack:** Python stdlib (json, pathlib), `langfuse` SDK (already installed via LiteLLM), `uuid` stdlib module.

**Design doc:** `docs/plans/2026-03-09-voice-observability-design.md` in distro-work repo.

**Working repo:** `~/projects/ai-agents` (create worktree for implementation).

---

## Wave 1: Foundation

### Task 1: Add session_id to SessionManager

SessionManager (VoiceLifecycle) needs a unique ID per session so events and traces can be correlated.

**Files:**
- Modify: `agents/hapax_voice/session.py`
- Modify: `tests/hapax_voice/test_session.py`

**Step 1: Write the failing test**

```python
# tests/hapax_voice/test_session.py — append to existing file

def test_session_id_generated_on_open():
    sm = SessionManager(silence_timeout_s=10)
    assert sm.session_id is None
    sm.open(trigger="hotkey")
    assert sm.session_id is not None
    assert isinstance(sm.session_id, str)
    assert len(sm.session_id) > 0


def test_session_id_unique_per_session():
    sm = SessionManager(silence_timeout_s=10)
    sm.open(trigger="test")
    id1 = sm.session_id
    sm.close(reason="test")
    assert sm.session_id is None
    sm.open(trigger="test2")
    id2 = sm.session_id
    assert id1 != id2


def test_session_id_stable_during_session():
    sm = SessionManager(silence_timeout_s=10)
    sm.open(trigger="test")
    id1 = sm.session_id
    sm.mark_activity()
    id2 = sm.session_id
    assert id1 == id2
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/hapax_voice/test_session.py -v -k "session_id"`
Expected: FAIL with `AttributeError: 'VoiceLifecycle' object has no attribute 'session_id'`

**Step 3: Implement session_id**

In `agents/hapax_voice/session.py`:
- Add `import uuid` at top
- Add `self.session_id: str | None = None` in `__init__`
- In `open()`: set `self.session_id = uuid.uuid4().hex[:12]`
- In `close()`: set `self.session_id = None`

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/hapax_voice/test_session.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add agents/hapax_voice/session.py tests/hapax_voice/test_session.py
git commit -m "feat(voice): add session_id to SessionManager for observability correlation"
```

---

### Task 2: EventLog Module

Create the structured event log writer.

**Files:**
- Create: `agents/hapax_voice/event_log.py`
- Create: `tests/hapax_voice/test_event_log.py`

**Step 1: Write the failing tests**

```python
# tests/hapax_voice/test_event_log.py
import json
import time
from pathlib import Path

from agents.hapax_voice.event_log import EventLog


def test_emit_writes_jsonl(tmp_path):
    elog = EventLog(base_dir=tmp_path, retention_days=7)
    elog.emit("test_event", foo="bar", count=42)

    files = list(tmp_path.glob("events-*.jsonl"))
    assert len(files) == 1

    lines = files[0].read_text().strip().split("\n")
    assert len(lines) == 1

    event = json.loads(lines[0])
    assert event["type"] == "test_event"
    assert event["foo"] == "bar"
    assert event["count"] == 42
    assert event["source_service"] == "hapax-voice"
    assert "ts" in event
    assert "session_id" in event


def test_emit_includes_session_id(tmp_path):
    elog = EventLog(base_dir=tmp_path)
    elog.set_session_id("abc123")
    elog.emit("test_event")

    files = list(tmp_path.glob("events-*.jsonl"))
    event = json.loads(files[0].read_text().strip())
    assert event["session_id"] == "abc123"


def test_emit_session_id_none_when_unset(tmp_path):
    elog = EventLog(base_dir=tmp_path)
    elog.emit("test_event")

    files = list(tmp_path.glob("events-*.jsonl"))
    event = json.loads(files[0].read_text().strip())
    assert event["session_id"] is None


def test_emit_multiple_events(tmp_path):
    elog = EventLog(base_dir=tmp_path)
    elog.emit("event_a", x=1)
    elog.emit("event_b", x=2)
    elog.emit("event_c", x=3)

    files = list(tmp_path.glob("events-*.jsonl"))
    lines = files[0].read_text().strip().split("\n")
    assert len(lines) == 3
    types = [json.loads(l)["type"] for l in lines]
    assert types == ["event_a", "event_b", "event_c"]


def test_cleanup_old_files(tmp_path):
    # Create fake old event files
    import datetime
    for i in range(5):
        day = datetime.date.today() - datetime.timedelta(days=i + 20)
        (tmp_path / f"events-{day.isoformat()}.jsonl").write_text("{}\n")

    elog = EventLog(base_dir=tmp_path, retention_days=7)
    elog.cleanup()

    remaining = list(tmp_path.glob("events-*.jsonl"))
    assert len(remaining) == 0  # All are >7 days old


def test_cleanup_keeps_recent_files(tmp_path):
    import datetime
    today = datetime.date.today()
    (tmp_path / f"events-{today.isoformat()}.jsonl").write_text("{}\n")
    yesterday = today - datetime.timedelta(days=1)
    (tmp_path / f"events-{yesterday.isoformat()}.jsonl").write_text("{}\n")
    old = today - datetime.timedelta(days=30)
    (tmp_path / f"events-{old.isoformat()}.jsonl").write_text("{}\n")

    elog = EventLog(base_dir=tmp_path, retention_days=7)
    elog.cleanup()

    remaining = sorted(p.name for p in tmp_path.glob("events-*.jsonl"))
    assert len(remaining) == 2  # today + yesterday kept


def test_disabled_event_log(tmp_path):
    elog = EventLog(base_dir=tmp_path, enabled=False)
    elog.emit("test_event", foo="bar")

    files = list(tmp_path.glob("events-*.jsonl"))
    assert len(files) == 0
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/hapax_voice/test_event_log.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agents.hapax_voice.event_log'`

**Step 3: Implement EventLog**

```python
# agents/hapax_voice/event_log.py
"""Structured JSONL event log for voice daemon observability."""
from __future__ import annotations

import datetime
import json
import logging
import time
from pathlib import Path

log = logging.getLogger(__name__)

_DEFAULT_DIR = Path.home() / ".local" / "share" / "hapax-voice"


class EventLog:
    """Appends structured JSON events to daily-rotated JSONL files.

    Each event includes ts, type, session_id, source_service, plus
    caller-provided fields. Writes are synchronous (append + flush).
    """

    def __init__(
        self,
        base_dir: Path = _DEFAULT_DIR,
        retention_days: int = 14,
        enabled: bool = True,
    ) -> None:
        self._base_dir = Path(base_dir)
        self._retention_days = retention_days
        self._enabled = enabled
        self._session_id: str | None = None
        self._current_date: str = ""
        self._file = None

    def set_session_id(self, session_id: str | None) -> None:
        """Update the current session ID (set to None when session closes)."""
        self._session_id = session_id

    def emit(self, event_type: str, **fields) -> None:
        """Write a single event to the JSONL file."""
        if not self._enabled:
            return
        event = {
            "ts": time.time(),
            "type": event_type,
            "session_id": self._session_id,
            "source_service": "hapax-voice",
            **fields,
        }
        try:
            f = self._get_file()
            f.write(json.dumps(event, default=str) + "\n")
            f.flush()
        except Exception as exc:
            log.debug("Failed to write event: %s", exc)

    def cleanup(self) -> None:
        """Remove event files older than retention_days."""
        cutoff = datetime.date.today() - datetime.timedelta(days=self._retention_days)
        for path in self._base_dir.glob("events-*.jsonl"):
            try:
                date_str = path.stem.replace("events-", "")
                file_date = datetime.date.fromisoformat(date_str)
                if file_date < cutoff:
                    path.unlink()
                    log.debug("Cleaned up old event log: %s", path.name)
            except (ValueError, OSError) as exc:
                log.debug("Cleanup skipped %s: %s", path.name, exc)

    def _get_file(self):
        """Return file handle for today's event log, rotating if needed."""
        today = datetime.date.today().isoformat()
        if today != self._current_date:
            if self._file is not None:
                self._file.close()
            self._base_dir.mkdir(parents=True, exist_ok=True)
            path = self._base_dir / f"events-{today}.jsonl"
            self._file = open(path, "a", encoding="utf-8")
            self._current_date = today
        return self._file

    def close(self) -> None:
        """Close the current file handle."""
        if self._file is not None:
            self._file.close()
            self._file = None
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/hapax_voice/test_event_log.py -v`
Expected: ALL PASS (7 tests)

**Step 5: Commit**

```bash
git add agents/hapax_voice/event_log.py tests/hapax_voice/test_event_log.py
git commit -m "feat(voice): add EventLog structured JSONL event writer"
```

---

### Task 3: VoiceTracer Module (Langfuse)

Create the Langfuse trace wrapper.

**Files:**
- Create: `agents/hapax_voice/tracing.py`
- Create: `tests/hapax_voice/test_tracing.py`

**Step 1: Write the failing tests**

```python
# tests/hapax_voice/test_tracing.py
from unittest.mock import patch, MagicMock

from agents.hapax_voice.tracing import VoiceTracer


def test_disabled_tracer_is_noop():
    tracer = VoiceTracer(enabled=False)
    # Should not raise
    with tracer.trace_analysis(presence_score="likely_present", images_sent=2) as span:
        assert span is not None  # returns a no-op context


def test_enabled_tracer_creates_langfuse_client():
    with patch.dict("os.environ", {
        "LANGFUSE_PUBLIC_KEY": "pk-test",
        "LANGFUSE_SECRET_KEY": "sk-test",
        "LANGFUSE_HOST": "http://localhost:3000",
    }):
        with patch("agents.hapax_voice.tracing.Langfuse") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            tracer = VoiceTracer(enabled=True)
            tracer._get_client()  # force init
            mock_cls.assert_called_once()


def test_trace_analysis_context_manager():
    tracer = VoiceTracer(enabled=False)
    with tracer.trace_analysis(presence_score="uncertain", images_sent=1) as ctx:
        ctx.span("call_vision")
    # No error = success


def test_trace_session_context_manager():
    tracer = VoiceTracer(enabled=False)
    with tracer.trace_session(session_id="abc123", trigger="hotkey") as ctx:
        pass
    # No error = success


def test_trace_delivery_context_manager():
    tracer = VoiceTracer(enabled=False)
    with tracer.trace_delivery(
        session_id=None, presence_score="likely_present",
        gate_reason="", notification_priority="normal",
    ) as ctx:
        pass
    # No error = success
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/hapax_voice/test_tracing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agents.hapax_voice.tracing'`

**Step 3: Implement VoiceTracer**

```python
# agents/hapax_voice/tracing.py
"""Langfuse trace integration for hapax-voice observability."""
from __future__ import annotations

import contextlib
import logging
import os
from dataclasses import dataclass
from typing import Any, Generator

log = logging.getLogger(__name__)

try:
    from langfuse import Langfuse
except ImportError:
    Langfuse = None  # type: ignore[assignment,misc]


@dataclass
class NoOpSpan:
    """No-op span for when tracing is disabled."""

    def span(self, name: str, **kwargs: Any) -> "NoOpSpan":
        return self

    def end(self, **kwargs: Any) -> None:
        pass

    def update(self, **kwargs: Any) -> None:
        pass


class VoiceTracer:
    """Wraps Langfuse SDK for hapax-voice trace creation.

    Fail-open: if Langfuse is unreachable, credentials missing, or SDK
    unavailable, all methods become no-ops. Never crashes the daemon.
    """

    def __init__(self, enabled: bool = True) -> None:
        self._enabled = enabled and Langfuse is not None
        self._client: Any | None = None

    def _get_client(self) -> Any | None:
        """Lazily initialize Langfuse client."""
        if not self._enabled:
            return None
        if self._client is not None:
            return self._client
        try:
            pk = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
            sk = os.environ.get("LANGFUSE_SECRET_KEY", "")
            host = os.environ.get("LANGFUSE_HOST", "http://localhost:3000")
            if not pk or not sk:
                log.debug("Langfuse credentials not set, tracing disabled")
                self._enabled = False
                return None
            self._client = Langfuse(
                public_key=pk,
                secret_key=sk,
                host=host,
            )
            log.info("Langfuse tracing initialized")
            return self._client
        except Exception as exc:
            log.warning("Langfuse initialization failed: %s", exc)
            self._enabled = False
            return None

    @contextlib.contextmanager
    def trace_analysis(
        self,
        *,
        presence_score: str = "unknown",
        images_sent: int = 0,
        session_id: str | None = None,
        activity_mode: str = "unknown",
        session_active: bool = False,
    ) -> Generator[Any, None, None]:
        """Context manager for workspace analysis traces."""
        client = self._get_client()
        if client is None:
            yield NoOpSpan()
            return
        try:
            trace = client.trace(
                name="workspace_analysis",
                session_id=session_id,
                tags=["hapax-voice"],
                metadata={
                    "source_service": "hapax-voice",
                    "presence_score": presence_score,
                    "images_sent": images_sent,
                    "activity_mode": activity_mode,
                    "session_active": session_active,
                },
            )
            yield trace
            trace.update(status_message="completed")
        except Exception as exc:
            log.debug("Trace analysis error: %s", exc)
            yield NoOpSpan()

    @contextlib.contextmanager
    def trace_session(
        self,
        *,
        session_id: str,
        trigger: str,
    ) -> Generator[Any, None, None]:
        """Context manager for voice session traces."""
        client = self._get_client()
        if client is None:
            yield NoOpSpan()
            return
        try:
            trace = client.trace(
                name="voice_session",
                session_id=session_id,
                tags=["hapax-voice"],
                metadata={
                    "source_service": "hapax-voice",
                    "trigger": trigger,
                },
            )
            yield trace
        except Exception as exc:
            log.debug("Trace session error: %s", exc)
            yield NoOpSpan()

    @contextlib.contextmanager
    def trace_delivery(
        self,
        *,
        session_id: str | None,
        presence_score: str,
        gate_reason: str,
        notification_priority: str,
    ) -> Generator[Any, None, None]:
        """Context manager for proactive delivery traces."""
        client = self._get_client()
        if client is None:
            yield NoOpSpan()
            return
        try:
            trace = client.trace(
                name="proactive_delivery",
                session_id=session_id,
                tags=["hapax-voice"],
                metadata={
                    "source_service": "hapax-voice",
                    "presence_score": presence_score,
                    "gate_reason": gate_reason,
                    "notification_priority": notification_priority,
                },
            )
            yield trace
        except Exception as exc:
            log.debug("Trace delivery error: %s", exc)
            yield NoOpSpan()

    def flush(self) -> None:
        """Flush any pending traces to Langfuse."""
        if self._client is not None:
            try:
                self._client.flush()
            except Exception:
                pass
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/hapax_voice/test_tracing.py -v`
Expected: ALL PASS (5 tests)

**Step 5: Commit**

```bash
git add agents/hapax_voice/tracing.py tests/hapax_voice/test_tracing.py
git commit -m "feat(voice): add VoiceTracer Langfuse trace wrapper"
```

---

### Task 4: Config Fields

Add observability config fields to VoiceConfig.

**Files:**
- Modify: `agents/hapax_voice/config.py`
- Modify: `tests/hapax_voice/test_config.py` (if exists, else create)

**Step 1: Write the failing test**

```python
# tests/hapax_voice/test_config.py — append or create

from agents.hapax_voice.config import VoiceConfig


def test_observability_config_defaults():
    cfg = VoiceConfig()
    assert cfg.observability_events_enabled is True
    assert cfg.observability_langfuse_enabled is True
    assert cfg.observability_events_retention_days == 14
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/hapax_voice/test_config.py::test_observability_config_defaults -v`
Expected: FAIL with `ValidationError` (fields don't exist yet)

**Step 3: Add config fields**

In `agents/hapax_voice/config.py`, add after the timelapse fields:

```python
    # Observability
    observability_events_enabled: bool = True
    observability_langfuse_enabled: bool = True
    observability_events_retention_days: int = 14
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/hapax_voice/test_config.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add agents/hapax_voice/config.py tests/hapax_voice/test_config.py
git commit -m "feat(voice): add observability config fields"
```

---

## Wave 2: Event Emission

### Task 5: Wire EventLog into VoiceDaemon

Create EventLog and VoiceTracer in VoiceDaemon, wire session_id updates.

**Files:**
- Modify: `agents/hapax_voice/__main__.py`
- Modify: `tests/hapax_voice/test_daemon_screen_integration.py`

**Step 1: Write the failing test**

```python
# tests/hapax_voice/test_daemon_screen_integration.py — append

def test_daemon_creates_event_log():
    """VoiceDaemon should create EventLog and VoiceTracer."""
    from unittest.mock import patch, MagicMock
    from agents.hapax_voice.config import VoiceConfig

    cfg = VoiceConfig(
        screen_monitor_enabled=False,
        webcam_enabled=False,
    )
    with patch("agents.hapax_voice.__main__.HotkeyServer"), \
         patch("agents.hapax_voice.__main__.WakeWordDetector"), \
         patch("agents.hapax_voice.__main__.TTSManager"):
        from agents.hapax_voice.__main__ import VoiceDaemon
        daemon = VoiceDaemon(cfg=cfg)
        assert hasattr(daemon, "event_log")
        assert hasattr(daemon, "tracer")
        assert daemon.event_log is not None
        assert daemon.tracer is not None
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/hapax_voice/test_daemon_screen_integration.py::test_daemon_creates_event_log -v`
Expected: FAIL with `AssertionError`

**Step 3: Implement**

In `agents/hapax_voice/__main__.py`:

Add imports:
```python
from agents.hapax_voice.event_log import EventLog
from agents.hapax_voice.tracing import VoiceTracer
```

In `VoiceDaemon.__init__()`, after `self._background_tasks` line, add:
```python
        # Observability
        events_dir = Path.home() / ".local" / "share" / "hapax-voice"
        self.event_log = EventLog(
            base_dir=events_dir,
            retention_days=self.cfg.observability_events_retention_days,
            enabled=self.cfg.observability_events_enabled,
        )
        self.tracer = VoiceTracer(enabled=self.cfg.observability_langfuse_enabled)
```

In `_on_wake_word()` and `_handle_hotkey()` where `self.session.open()` is called, add after:
```python
        self.event_log.set_session_id(self.session.session_id)
        self.event_log.emit("session_lifecycle", action="opened", trigger=...)
```

In `_close_session()`, add before `self.session.close()`:
```python
        duration = time.monotonic() - self.session._opened_at if self.session.is_active else 0
        self.event_log.emit("session_lifecycle", action="closed", reason=reason, duration_s=round(duration, 1))
        self.event_log.set_session_id(None)
```

In `run()` finally block, add:
```python
        self.event_log.close()
        self.tracer.flush()
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/hapax_voice/test_daemon_screen_integration.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add agents/hapax_voice/__main__.py tests/hapax_voice/test_daemon_screen_integration.py
git commit -m "feat(voice): wire EventLog and VoiceTracer into VoiceDaemon"
```

---

### Task 6: Presence Transition Events

Emit `presence_transition` events when the composite score changes.

**Files:**
- Modify: `agents/hapax_voice/presence.py`
- Create: `tests/hapax_voice/test_presence_events.py`

**Step 1: Write the failing tests**

```python
# tests/hapax_voice/test_presence_events.py
import time
from unittest.mock import MagicMock

from agents.hapax_voice.presence import PresenceDetector


def test_presence_emits_transition_on_score_change():
    pd = PresenceDetector(window_minutes=5, vad_threshold=0.4)
    mock_log = MagicMock()
    pd.set_event_log(mock_log)

    # Initial score is likely_absent, record enough VAD to become likely_present
    for _ in range(3):
        pd.record_vad_event(0.8)

    # Access score to trigger transition check
    _ = pd.score

    mock_log.emit.assert_called_with(
        "presence_transition",
        **{
            "from": "likely_absent",
            "to": "uncertain",
            "vad_count": 3,
            "face_detected": False,
        },
    )


def test_presence_no_event_when_score_unchanged():
    pd = PresenceDetector(window_minutes=5, vad_threshold=0.4)
    mock_log = MagicMock()
    pd.set_event_log(mock_log)

    # Access score twice without changes
    _ = pd.score
    _ = pd.score

    mock_log.emit.assert_not_called()


def test_presence_no_event_without_event_log():
    pd = PresenceDetector(window_minutes=5, vad_threshold=0.4)
    # No event_log set — should not raise
    for _ in range(5):
        pd.record_vad_event(0.8)
    _ = pd.score  # no error
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/hapax_voice/test_presence_events.py -v`
Expected: FAIL with `AttributeError: 'PresenceDetector' object has no attribute 'set_event_log'`

**Step 3: Implement**

In `agents/hapax_voice/presence.py`:

Add to `__init__`:
```python
        self._event_log = None
        self._last_score: str = "likely_absent"
```

Add method:
```python
    def set_event_log(self, event_log) -> None:
        self._event_log = event_log
```

Modify `score` property to check for transitions:
```python
    @property
    def score(self) -> str:
        """Return composite presence score fusing VAD events and face detection."""
        self._prune_old_events()
        count = len(self._events)
        face = self.face_detected

        if count >= 5:
            new_score = "definitely_present" if face else "likely_present"
        elif count >= 2:
            new_score = "likely_present" if face else "uncertain"
        elif face:
            new_score = "likely_present"
        else:
            new_score = "likely_absent"

        if new_score != self._last_score and self._event_log is not None:
            self._event_log.emit(
                "presence_transition",
                **{"from": self._last_score, "to": new_score, "vad_count": count, "face_detected": face},
            )
        self._last_score = new_score
        return new_score
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/hapax_voice/test_presence_events.py -v && uv run pytest tests/hapax_voice/test_presence_face.py -v`
Expected: ALL PASS (both old and new tests)

**Step 5: Commit**

```bash
git add agents/hapax_voice/presence.py tests/hapax_voice/test_presence_events.py
git commit -m "feat(voice): emit presence_transition events on score changes"
```

---

### Task 7: Gate Decision Events

Emit `gate_decision` events from ContextGate, including `subprocess_failed` for wpctl/aconnect failures.

**Files:**
- Modify: `agents/hapax_voice/context_gate.py`
- Create: `tests/hapax_voice/test_gate_events.py`

**Step 1: Write the failing tests**

```python
# tests/hapax_voice/test_gate_events.py
from unittest.mock import MagicMock, patch

from agents.hapax_voice.context_gate import ContextGate
from agents.hapax_voice.session import SessionManager


def test_gate_emits_decision_event():
    sm = SessionManager(silence_timeout_s=10)
    gate = ContextGate(session=sm, volume_threshold=0.7)
    mock_log = MagicMock()
    gate.set_event_log(mock_log)

    with patch.object(gate, "_check_volume", return_value=(True, "")), \
         patch.object(gate, "_check_studio", return_value=(True, "")), \
         patch.object(gate, "_check_ambient", return_value=(True, "")):
        result = gate.check()

    assert result.eligible is True
    mock_log.emit.assert_called_once()
    call_args = mock_log.emit.call_args
    assert call_args[0][0] == "gate_decision"
    assert call_args[1]["eligible"] is True


def test_gate_emits_blocked_decision():
    sm = SessionManager(silence_timeout_s=10)
    sm.open(trigger="test")  # session active → gate blocks
    gate = ContextGate(session=sm, volume_threshold=0.7)
    mock_log = MagicMock()
    gate.set_event_log(mock_log)

    result = gate.check()

    assert result.eligible is False
    mock_log.emit.assert_called_once()
    call_args = mock_log.emit.call_args
    assert call_args[1]["reason"] == "Session active"


def test_gate_emits_subprocess_failed_on_wpctl_error():
    sm = SessionManager(silence_timeout_s=10)
    gate = ContextGate(session=sm, volume_threshold=0.7)
    mock_log = MagicMock()
    gate.set_event_log(mock_log)

    with patch("subprocess.run", side_effect=FileNotFoundError("wpctl not found")):
        gate._check_volume()

    # Should have emitted subprocess_failed
    calls = [c for c in mock_log.emit.call_args_list if c[0][0] == "subprocess_failed"]
    assert len(calls) == 1
    assert calls[0][1]["command"] == "wpctl"
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/hapax_voice/test_gate_events.py -v`
Expected: FAIL with `AttributeError`

**Step 3: Implement**

In `agents/hapax_voice/context_gate.py`:

Add to `__init__`:
```python
        self._event_log = None
```

Add method:
```python
    def set_event_log(self, event_log) -> None:
        self._event_log = event_log
```

At the end of `check()`, before `return`, add event emission:
```python
        if self._event_log is not None:
            self._event_log.emit(
                "gate_decision",
                eligible=result.eligible,
                reason=result.reason,
                activity_mode=self._activity_mode,
            )
```

Wait — the method returns early in multiple places. The cleanest approach: wrap with a helper. Rename current `check()` to `_check_inner()`, then:

```python
    def check(self) -> GateResult:
        result = self._check_inner()
        if self._event_log is not None:
            self._event_log.emit(
                "gate_decision",
                eligible=result.eligible,
                reason=result.reason,
                activity_mode=self._activity_mode,
            )
        return result
```

In `_get_sink_volume()`, in the except block, add:
```python
            if self._event_log is not None:
                self._event_log.emit("subprocess_failed", command="wpctl", error=str(exc))
```

In `_check_studio()`, in the except block, add:
```python
            if self._event_log is not None:
                self._event_log.emit("subprocess_failed", command="aconnect", error=str(exc))
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/hapax_voice/test_gate_events.py -v && uv run pytest tests/hapax_voice/test_context_gate_activity.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add agents/hapax_voice/context_gate.py tests/hapax_voice/test_gate_events.py
git commit -m "feat(voice): emit gate_decision and subprocess_failed events from ContextGate"
```

---

### Task 8: Face Detection and Analysis Events

Emit `face_result`, `analysis_complete`, `analysis_failed`, and `model_loaded` events from WorkspaceMonitor.

**Files:**
- Modify: `agents/hapax_voice/workspace_monitor.py`
- Create: `tests/hapax_voice/test_monitor_events.py`

**Step 1: Write the failing tests**

```python
# tests/hapax_voice/test_monitor_events.py
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

from agents.hapax_voice.workspace_monitor import WorkspaceMonitor
from agents.hapax_voice.screen_models import WorkspaceAnalysis


def test_monitor_emits_analysis_complete():
    mon = WorkspaceMonitor(enabled=False)
    mock_log = MagicMock()
    mon.set_event_log(mock_log)

    analysis = WorkspaceAnalysis(
        app="VS Code", context="editing", summary="Writing code.",
        operator_present=True,
    )
    mon._latest_analysis = analysis
    mon._emit_analysis_event(analysis, latency_ms=1200, images_sent=3)

    mock_log.emit.assert_called_once()
    call = mock_log.emit.call_args
    assert call[0][0] == "analysis_complete"
    assert call[1]["app"] == "VS Code"
    assert call[1]["latency_ms"] == 1200
    assert call[1]["images_sent"] == 3


def test_monitor_emits_analysis_failed():
    mon = WorkspaceMonitor(enabled=False)
    mock_log = MagicMock()
    mon.set_event_log(mock_log)

    mon._emit_analysis_failed("Connection timeout", latency_ms=5000)

    mock_log.emit.assert_called_once()
    call = mock_log.emit.call_args
    assert call[0][0] == "analysis_failed"
    assert call[1]["error"] == "Connection timeout"


def test_monitor_emits_face_result():
    mon = WorkspaceMonitor(enabled=False)
    mock_log = MagicMock()
    mon.set_event_log(mock_log)

    mon._emit_face_event(detected=True, count=1, latency_ms=4)

    mock_log.emit.assert_called_once()
    call = mock_log.emit.call_args
    assert call[0][0] == "face_result"
    assert call[1]["detected"] is True
    assert call[1]["count"] == 1


def test_monitor_no_event_without_log():
    mon = WorkspaceMonitor(enabled=False)
    # No event_log set — should not raise
    mon._emit_analysis_event(
        WorkspaceAnalysis(app="test", context="", summary=""),
        latency_ms=100, images_sent=1,
    )
    mon._emit_analysis_failed("err", latency_ms=100)
    mon._emit_face_event(detected=False, count=0, latency_ms=3)
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/hapax_voice/test_monitor_events.py -v`
Expected: FAIL with `AttributeError: 'WorkspaceMonitor' object has no attribute 'set_event_log'`

**Step 3: Implement**

In `agents/hapax_voice/workspace_monitor.py`:

Add to `__init__`:
```python
        self._event_log = None
        self._tracer = None
```

Add setter methods:
```python
    def set_event_log(self, event_log) -> None:
        self._event_log = event_log

    def set_tracer(self, tracer) -> None:
        self._tracer = tracer
```

Add event emission helpers:
```python
    def _emit_analysis_event(self, analysis: WorkspaceAnalysis, *, latency_ms: int, images_sent: int) -> None:
        if self._event_log is None:
            return
        self._event_log.emit(
            "analysis_complete",
            app=analysis.app,
            operator_present=analysis.operator_present,
            gear_count=len(analysis.gear_state),
            latency_ms=latency_ms,
            images_sent=images_sent,
        )

    def _emit_analysis_failed(self, error: str, *, latency_ms: int) -> None:
        if self._event_log is None:
            return
        self._event_log.emit("analysis_failed", error=error, latency_ms=latency_ms)

    def _emit_face_event(self, *, detected: bool, count: int, latency_ms: int) -> None:
        if self._event_log is None:
            return
        self._event_log.emit("face_result", detected=detected, count=count, latency_ms=latency_ms)
```

In `_capture_and_analyze()`, wrap the analysis call with timing:
```python
        t0 = time.monotonic()
        analysis = await self._analyzer.analyze(...)
        latency_ms = int((time.monotonic() - t0) * 1000)
        images_sent = 1 + (1 if operator_b64 else 0) + (1 if hardware_b64 else 0)

        if analysis is not None:
            ...  # existing code
            self._emit_analysis_event(analysis, latency_ms=latency_ms, images_sent=images_sent)
        else:
            self._emit_analysis_failed("Analysis returned None", latency_ms=latency_ms)
```

In `_face_detection_loop()`, wrap face detection with timing:
```python
                if frame_b64 is not None:
                    t0 = time.monotonic()
                    result = self._face_detector.detect_from_base64(frame_b64)
                    latency_ms = int((time.monotonic() - t0) * 1000)
                    self._presence.record_face_event(...)
                    self._emit_face_event(detected=result.detected, count=result.count, latency_ms=latency_ms)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/hapax_voice/test_monitor_events.py -v && uv run pytest tests/hapax_voice/test_workspace_monitor.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add agents/hapax_voice/workspace_monitor.py tests/hapax_voice/test_monitor_events.py
git commit -m "feat(voice): emit face_result, analysis_complete/failed events from WorkspaceMonitor"
```

---

### Task 9: Notification Lifecycle Events

Emit `notification_lifecycle` events from NotificationQueue.

**Files:**
- Modify: `agents/hapax_voice/notification_queue.py`
- Create: `tests/hapax_voice/test_notification_events.py`

**Step 1: Write the failing tests**

```python
# tests/hapax_voice/test_notification_events.py
from unittest.mock import MagicMock

from agents.hapax_voice.notification_queue import NotificationQueue, VoiceNotification


def test_notification_emits_queued_event():
    q = NotificationQueue()
    mock_log = MagicMock()
    q.set_event_log(mock_log)

    n = VoiceNotification(title="Test", message="msg", priority="normal", source="test")
    q.enqueue(n)

    mock_log.emit.assert_called_once()
    call = mock_log.emit.call_args
    assert call[0][0] == "notification_lifecycle"
    assert call[1]["action"] == "queued"
    assert call[1]["title"] == "Test"
    assert call[1]["priority"] == "normal"


def test_notification_emits_expired_event():
    import time
    q = NotificationQueue(ttls={"urgent": 0, "normal": 0, "low": 0})
    mock_log = MagicMock()
    q.set_event_log(mock_log)

    # Manually create an expired notification
    n = VoiceNotification(title="Old", message="", priority="normal", source="test")
    # We need TTL > 0 for expiry to happen
    q._ttls["normal"] = 1  # 1 second TTL
    q._items.append(n)
    n.created_at = n.created_at - 100  # make it old

    mock_log.emit.reset_mock()
    q.prune_expired()

    calls = [c for c in mock_log.emit.call_args_list if c[0][0] == "notification_lifecycle"]
    assert len(calls) == 1
    assert calls[0][1]["action"] == "expired"


def test_notification_no_event_without_log():
    q = NotificationQueue()
    n = VoiceNotification(title="Test", message="", priority="normal", source="test")
    q.enqueue(n)  # Should not raise
    q.prune_expired()  # Should not raise
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/hapax_voice/test_notification_events.py -v`
Expected: FAIL with `AttributeError`

**Step 3: Implement**

In `agents/hapax_voice/notification_queue.py`:

Add to `__init__`:
```python
        self._event_log = None
```

Add setter:
```python
    def set_event_log(self, event_log) -> None:
        self._event_log = event_log
```

In `enqueue()`, after the append and sort, add:
```python
        if self._event_log is not None:
            self._event_log.emit(
                "notification_lifecycle",
                action="queued",
                title=notification.title,
                priority=notification.priority,
                source=notification.source,
            )
```

In `prune_expired()`, in the else branch where items are pruned, add:
```python
                if self._event_log is not None:
                    self._event_log.emit(
                        "notification_lifecycle",
                        action="expired",
                        title=item.title,
                        priority=item.priority,
                    )
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/hapax_voice/test_notification_events.py -v`
Expected: ALL PASS (3 tests)

**Step 5: Commit**

```bash
git add agents/hapax_voice/notification_queue.py tests/hapax_voice/test_notification_events.py
git commit -m "feat(voice): emit notification_lifecycle events from NotificationQueue"
```

---

## Wave 3: Langfuse Traces

### Task 10: Trace Workspace Analysis

Wrap workspace analysis calls with Langfuse traces in WorkspaceMonitor.

**Files:**
- Modify: `agents/hapax_voice/workspace_monitor.py`
- Modify: `tests/hapax_voice/test_monitor_events.py`

**Step 1: Write the failing test**

```python
# tests/hapax_voice/test_monitor_events.py — append

def test_monitor_uses_tracer_for_analysis():
    """WorkspaceMonitor should wrap analysis with tracer.trace_analysis."""
    mon = WorkspaceMonitor(enabled=False)
    mock_tracer = MagicMock()
    mock_ctx = MagicMock()
    mock_tracer.trace_analysis.return_value.__enter__ = MagicMock(return_value=mock_ctx)
    mock_tracer.trace_analysis.return_value.__exit__ = MagicMock(return_value=False)
    mon.set_tracer(mock_tracer)

    # Verify tracer is stored
    assert mon._tracer is mock_tracer
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/hapax_voice/test_monitor_events.py::test_monitor_uses_tracer_for_analysis -v`
Expected: PASS (set_tracer already added in Task 8). If so, this test just validates wiring.

**Step 3: Implement trace wrapping**

In `_capture_and_analyze()`, wrap the vision call with the tracer:

```python
    async def _capture_and_analyze(self) -> None:
        if self._screen_capturer is None or self._analyzer is None:
            return

        screen_b64 = self._screen_capturer.capture()
        if screen_b64 is None:
            return

        operator_b64 = None
        hardware_b64 = None
        if self._webcam_capturer is not None:
            operator_b64 = self._webcam_capturer.capture("operator")
            hardware_b64 = self._webcam_capturer.capture("hardware")

        prev_keywords = self._latest_analysis.keywords if self._latest_analysis else []
        rag_context = self._query_rag(prev_keywords)

        images_sent = 1 + (1 if operator_b64 else 0) + (1 if hardware_b64 else 0)

        # Get trace context manager (no-op if tracer not set)
        trace_cm = (
            self._tracer.trace_analysis(
                presence_score=self._presence.score if self._presence else "unknown",
                images_sent=images_sent,
                session_id=self._event_log._session_id if self._event_log else None,
                activity_mode="unknown",
            )
            if self._tracer is not None
            else contextlib.nullcontext(None)
        )

        t0 = time.monotonic()
        with trace_cm as trace:
            analysis = await self._analyzer.analyze(
                screen_b64=screen_b64,
                operator_b64=operator_b64,
                hardware_b64=hardware_b64,
                extra_context=rag_context,
            )
        latency_ms = int((time.monotonic() - t0) * 1000)

        if analysis is not None:
            self._latest_analysis = analysis
            self._last_analysis_time = time.monotonic()
            log.info(...)
            self._route_proactive_issues(analysis)
            self._persist_analysis(analysis)
            self._emit_analysis_event(analysis, latency_ms=latency_ms, images_sent=images_sent)
        else:
            self._emit_analysis_failed("Analysis returned None", latency_ms=latency_ms)
```

Add `import contextlib` at top of file.

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/hapax_voice/ -v -q`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add agents/hapax_voice/workspace_monitor.py tests/hapax_voice/test_monitor_events.py
git commit -m "feat(voice): wrap workspace analysis with Langfuse traces"
```

---

### Task 11: Wire EventLog to All Subsystems in Daemon

Connect event_log to PresenceDetector, ContextGate, WorkspaceMonitor, NotificationQueue from VoiceDaemon.

**Files:**
- Modify: `agents/hapax_voice/__main__.py`
- Modify: `tests/hapax_voice/test_daemon_screen_integration.py`

**Step 1: Write the failing test**

```python
# tests/hapax_voice/test_daemon_screen_integration.py — append

def test_daemon_wires_event_log_to_subsystems():
    from unittest.mock import patch
    from agents.hapax_voice.config import VoiceConfig

    cfg = VoiceConfig(
        screen_monitor_enabled=False,
        webcam_enabled=False,
    )
    with patch("agents.hapax_voice.__main__.HotkeyServer"), \
         patch("agents.hapax_voice.__main__.WakeWordDetector"), \
         patch("agents.hapax_voice.__main__.TTSManager"):
        from agents.hapax_voice.__main__ import VoiceDaemon
        daemon = VoiceDaemon(cfg=cfg)
        assert daemon.presence._event_log is daemon.event_log
        assert daemon.gate._event_log is daemon.event_log
        assert daemon.notifications._event_log is daemon.event_log
        assert daemon.workspace_monitor._event_log is daemon.event_log
        assert daemon.workspace_monitor._tracer is daemon.tracer
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/hapax_voice/test_daemon_screen_integration.py::test_daemon_wires_event_log_to_subsystems -v`
Expected: FAIL

**Step 3: Implement**

In `VoiceDaemon.__init__()`, after creating event_log and tracer, add:

```python
        self.presence.set_event_log(self.event_log)
        self.gate.set_event_log(self.event_log)
        self.notifications.set_event_log(self.event_log)
        self.workspace_monitor.set_event_log(self.event_log)
        self.workspace_monitor.set_tracer(self.tracer)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/hapax_voice/ -v -q`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add agents/hapax_voice/__main__.py tests/hapax_voice/test_daemon_screen_integration.py
git commit -m "feat(voice): wire EventLog and VoiceTracer to all subsystems in daemon"
```

---

## Wave 4: Cleanup and Daily Rotation

### Task 12: Event Log Cleanup in Daemon Loop

Add periodic event log cleanup and event log cleanup on daemon startup.

**Files:**
- Modify: `agents/hapax_voice/__main__.py`

**Step 1: No new test needed**

This is wiring only — cleanup() is already tested in Task 2.

**Step 2: Implement**

In `VoiceDaemon.run()`, after subsystem initialization logging, add:

```python
        # Cleanup old event logs on startup
        self.event_log.cleanup()
```

**Step 3: Run all tests**

Run: `uv run pytest tests/hapax_voice/ -v -q`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add agents/hapax_voice/__main__.py
git commit -m "feat(voice): run event log cleanup on daemon startup"
```

---

### Task 13: Full Integration Test

End-to-end test verifying events flow through the system.

**Files:**
- Create: `tests/hapax_voice/test_observability_integration.py`

**Step 1: Write the integration test**

```python
# tests/hapax_voice/test_observability_integration.py
"""Integration test: verify observability events flow end-to-end."""
import json

from agents.hapax_voice.event_log import EventLog
from agents.hapax_voice.presence import PresenceDetector
from agents.hapax_voice.context_gate import ContextGate
from agents.hapax_voice.notification_queue import NotificationQueue, VoiceNotification
from agents.hapax_voice.session import SessionManager


def test_full_event_flow(tmp_path):
    """Simulate a daemon lifecycle and verify JSONL output."""
    elog = EventLog(base_dir=tmp_path, retention_days=7)
    sm = SessionManager(silence_timeout_s=10)
    pd = PresenceDetector(window_minutes=5, vad_threshold=0.4)
    gate = ContextGate(session=sm, volume_threshold=0.7)
    nq = NotificationQueue()

    pd.set_event_log(elog)
    gate.set_event_log(elog)
    nq.set_event_log(elog)

    # 1. Session opens
    sm.open(trigger="hotkey")
    elog.set_session_id(sm.session_id)
    elog.emit("session_lifecycle", action="opened", trigger="hotkey")

    # 2. VAD events trigger presence transition
    for _ in range(3):
        pd.record_vad_event(0.8)
    _ = pd.score  # triggers transition event

    # 3. Notification enqueued
    nq.enqueue(VoiceNotification(title="Build done", message="OK", priority="normal", source="ci"))

    # 4. Session closes
    elog.emit("session_lifecycle", action="closed", reason="hotkey", duration_s=5.0)
    elog.set_session_id(None)
    sm.close(reason="hotkey")

    # Verify events
    elog.close()
    files = list(tmp_path.glob("events-*.jsonl"))
    assert len(files) == 1

    events = [json.loads(line) for line in files[0].read_text().strip().split("\n")]

    types = [e["type"] for e in events]
    assert "session_lifecycle" in types
    assert "presence_transition" in types
    assert "notification_lifecycle" in types

    # All events have required fields
    for e in events:
        assert "ts" in e
        assert "source_service" in e
        assert e["source_service"] == "hapax-voice"
        assert "session_id" in e

    # Session events have the session_id set
    session_events = [e for e in events if e["type"] == "session_lifecycle"]
    opened = [e for e in session_events if e.get("action") == "opened"]
    assert len(opened) == 1
    assert opened[0]["session_id"] is not None
```

**Step 2: Run test**

Run: `uv run pytest tests/hapax_voice/test_observability_integration.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/hapax_voice/test_observability_integration.py
git commit -m "test(voice): add end-to-end observability integration test"
```

---

### Task 14: Run Full Test Suite

**Step 1: Run all hapax_voice tests**

Run: `uv run pytest tests/hapax_voice/ -v`
Expected: ALL PASS (previous 91 + new tests)

**Step 2: Verify no regressions**

If any test fails, fix before proceeding.

**Step 3: No commit needed** (unless fixes required)

---

That's 14 tasks across 4 waves. The branch will have ~12 commits when complete.
