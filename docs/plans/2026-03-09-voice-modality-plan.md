# Hapax Voice Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a persistent voice daemon that enables speech-in/speech-out interaction with the Hapax system, including proactive notifications, presence detection, and speaker identification.

**Architecture:** Pipecat-orchestrated daemon with dual backends (Gemini Live primary, local STT→LLM→TTS fallback), presence detection via Silero VAD, context-gated proactive speech, OpenWakeWord activation, and pyannote speaker identification. Runs as systemd user service.

**Tech Stack:** Pipecat, Gemini Live API, NVIDIA Parakeet TDT (STT), Kokoro (TTS), Piper (lightweight TTS), Silero VAD, OpenWakeWord, pyannote (speaker ID), PipeWire echo cancellation.

**Design doc:** `docs/plans/2026-03-09-voice-modality-design.md`

**Codebase context:**
- Project root: `~/projects/ai-agents/`
- New module: `agents/hapax_voice/`
- Tests: `tests/test_hapax_voice_*.py`
- Systemd units: `systemd/units/hapax-voice.service`
- Config: `~/.config/hapax-voice/config.yaml`
- Shared utilities: `shared/config.py` (model aliases, Qdrant), `shared/notify.py` (ntfy dispatch)
- Existing audio: `agents/audio_processor.py` (VAD, classification, diarization patterns)
- Existing TTS: `agents/demo_pipeline/voice.py` (Chatterbox HTTP API)
- Existing persona: `cockpit/voice.py` (greeting, operator_name)
- Run tests: `cd ~/projects/ai-agents && uv run pytest tests/ -v`
- Run single test: `uv run pytest tests/test_hapax_voice_config.py -v`

---

### Task 1: Add dependencies and create module skeleton

**Files:**
- Modify: `~/projects/ai-agents/pyproject.toml`
- Create: `~/projects/ai-agents/agents/hapax_voice/__init__.py`
- Create: `~/projects/ai-agents/agents/hapax_voice/__main__.py`
- Create: `~/projects/ai-agents/agents/hapax_voice/config.py`
- Test: `~/projects/ai-agents/tests/test_hapax_voice_config.py`

**Step 1: Add new dependencies to pyproject.toml**

Add these to the `dependencies` list in `pyproject.toml`:

```toml
    "pipecat-ai[silero,openai]>=0.0.50",
    "openwakeword>=0.6.0",
    "kokoro>=0.9.0",
    "piper-tts>=1.2.0",
    "pyaudio>=0.2.14",
```

Note: Parakeet (NVIDIA NeMo) is large — install separately via `uv pip install nemo_toolkit[asr]` when needed. Don't add to pyproject.toml to avoid bloating the venv for all agents.

**Step 2: Create module directory and __init__.py**

```bash
mkdir -p ~/projects/ai-agents/agents/hapax_voice
```

```python
# agents/hapax_voice/__init__.py
"""Hapax Voice — persistent voice interaction daemon."""
```

**Step 3: Write the config module with test**

Write test first:

```python
# tests/test_hapax_voice_config.py
"""Tests for hapax_voice configuration loading."""
import tempfile
from pathlib import Path

import yaml


def test_default_config_values():
    from agents.hapax_voice.config import VoiceConfig

    cfg = VoiceConfig()
    assert cfg.silence_timeout_s == 30
    assert cfg.wake_phrases == ["hapax", "hey hapax"]
    assert cfg.hotkey_socket == "/run/user/1000/hapax-voice.sock"
    assert cfg.presence_window_minutes == 5
    assert cfg.presence_vad_threshold == 0.4
    assert cfg.context_gate_volume_threshold == 0.7
    assert cfg.gemini_model == "gemini-2.5-flash-preview-native-audio"
    assert cfg.local_stt_model == "nvidia/parakeet-tdt-0.6b-v2"
    assert cfg.kokoro_voice == "af_heart"
    assert cfg.notification_priority_ttls == {
        "urgent": 1800,
        "normal": 14400,
        "low": 0,
    }


def test_config_from_yaml():
    from agents.hapax_voice.config import VoiceConfig, load_config

    data = {"silence_timeout_s": 45, "presence_window_minutes": 10}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(data, f)
        f.flush()
        cfg = load_config(Path(f.name))
    assert cfg.silence_timeout_s == 45
    assert cfg.presence_window_minutes == 10
    # defaults preserved
    assert cfg.wake_phrases == ["hapax", "hey hapax"]


def test_config_missing_file_returns_defaults():
    from agents.hapax_voice.config import load_config

    cfg = load_config(Path("/nonexistent/config.yaml"))
    assert cfg.silence_timeout_s == 30
```

**Step 4: Run test to verify it fails**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agents.hapax_voice.config'`

**Step 5: Implement config module**

```python
# agents/hapax_voice/config.py
"""Configuration for hapax-voice daemon."""
from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import BaseModel

log = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "hapax-voice" / "config.yaml"


class VoiceConfig(BaseModel):
    """All tunables for the voice daemon."""

    # Session
    silence_timeout_s: int = 30
    wake_phrases: list[str] = ["hapax", "hey hapax"]
    hotkey_socket: str = "/run/user/1000/hapax-voice.sock"

    # Presence detection
    presence_window_minutes: int = 5
    presence_vad_threshold: float = 0.4

    # Context gate
    context_gate_volume_threshold: float = 0.7

    # Backends
    gemini_model: str = "gemini-2.5-flash-preview-native-audio"
    local_stt_model: str = "nvidia/parakeet-tdt-0.6b-v2"
    kokoro_voice: str = "af_heart"

    # Notification queue
    notification_priority_ttls: dict[str, int] = {
        "urgent": 1800,
        "normal": 14400,
        "low": 0,
    }


def load_config(path: Path | None = None) -> VoiceConfig:
    """Load config from YAML, falling back to defaults."""
    config_path = path or DEFAULT_CONFIG_PATH
    if config_path.exists():
        try:
            data = yaml.safe_load(config_path.read_text()) or {}
            return VoiceConfig(**data)
        except Exception as exc:
            log.warning("Failed to load config from %s: %s", config_path, exc)
    return VoiceConfig()
```

**Step 6: Run tests to verify they pass**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_config.py -v`
Expected: 3 passed

**Step 7: Create minimal __main__.py**

```python
# agents/hapax_voice/__main__.py
"""Entry point for hapax-voice daemon."""
from __future__ import annotations

import argparse
import logging

from agents.hapax_voice.config import load_config

log = logging.getLogger("hapax_voice")


def main() -> None:
    parser = argparse.ArgumentParser(description="Hapax Voice daemon")
    parser.add_argument("--config", type=str, help="Path to config YAML")
    parser.add_argument("--check", action="store_true", help="Verify config and exit")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")

    cfg = load_config(args.config)
    if args.check:
        print(cfg.model_dump_json(indent=2))
        return

    log.info("Hapax Voice starting (config loaded)")
    # Daemon loop will be added in later tasks


if __name__ == "__main__":
    main()
```

**Step 8: Verify module runs**

Run: `cd ~/projects/ai-agents && uv run python -m agents.hapax_voice --check`
Expected: JSON config output printed

**Step 9: Commit**

```bash
cd ~/projects/ai-agents
git add agents/hapax_voice/ tests/test_hapax_voice_config.py pyproject.toml
git commit -m "feat(voice): add hapax_voice module skeleton and config"
```

---

### Task 2: PipeWire echo cancellation configuration

**Files:**
- Create: `~/.config/pipewire/pipewire.conf.d/60-echo-cancel.conf`
- Modify: `~/.config/systemd/user/audio-recorder.service` (update source name)

**Step 1: Create the PipeWire echo cancellation config**

```bash
mkdir -p ~/.config/pipewire/pipewire.conf.d
```

```
# ~/.config/pipewire/pipewire.conf.d/60-echo-cancel.conf
# Echo cancellation using WebRTC AEC for Hapax Voice
context.modules = [
    {
        name = libpipewire-module-echo-cancel
        args = {
            library.name = aec/libspa-aec-webrtc
            node.name = "Echo Cancelled Yeti"
            node.description = "Echo Cancelled Blue Yeti"
            monitor.mode = true
            capture.props = {
                node.name = "echo_cancel_capture"
                node.description = "Echo Cancelled Capture"
                media.class = "Audio/Source"
            }
            playback.props = {
                node.name = "echo_cancel_playback"
                node.description = "Echo Cancel Playback Sink"
                media.class = "Audio/Sink"
            }
            # WebRTC AEC settings
            aec.args = {
                webrtc.gain_control = true
                webrtc.extended_filter = true
            }
        }
    }
]
```

**Step 2: Restart PipeWire and verify the virtual source exists**

Run: `systemctl --user restart pipewire.service`
Run: `wpctl status | grep -i echo`
Expected: Shows "Echo Cancelled Capture" as an available source

If the echo cancel source doesn't appear, check: `journalctl --user -u pipewire -n 50 --no-pager`

**Step 3: Test that the echo-cancelled source captures audio**

Run: `pw-record --target echo_cancel_capture /tmp/echo-test.wav & sleep 3 && kill %1 && ls -la /tmp/echo-test.wav`
Expected: WAV file created with non-zero size

**Step 4: Update audio-recorder.service to use echo-cancelled source**

Back up first:
```bash
cp ~/.config/systemd/user/audio-recorder.service ~/.config/systemd/user/audio-recorder.service.bak
```

Change the `-i` argument from:
```
alsa_input.usb-Blue_Microphones_Yeti_Stereo_Microphone_REV8-00.analog-stereo
```
to:
```
echo_cancel_capture
```

**Step 5: Reload and restart audio recorder**

```bash
systemctl --user daemon-reload
systemctl --user restart audio-recorder.service
systemctl --user status audio-recorder.service
```
Expected: Active (running), no errors

**Step 6: Commit config (distro-work repo)**

```bash
cd ~/projects/distro-work
# Save a copy of the echo cancel config for reference
cp ~/.config/pipewire/pipewire.conf.d/60-echo-cancel.conf ./pipewire-echo-cancel.conf
git add pipewire-echo-cancel.conf
git commit -m "feat(voice): PipeWire echo cancellation config for Hapax Voice"
```

---

### Task 3: Session lifecycle and state machine

**Files:**
- Create: `~/projects/ai-agents/agents/hapax_voice/session.py`
- Test: `~/projects/ai-agents/tests/test_hapax_voice_session.py`

**Step 1: Write the failing test**

```python
# tests/test_hapax_voice_session.py
"""Tests for voice session state machine."""
import time


def test_session_starts_idle():
    from agents.hapax_voice.session import SessionManager

    sm = SessionManager(silence_timeout_s=30)
    assert sm.state == "idle"
    assert not sm.is_active


def test_session_open_close():
    from agents.hapax_voice.session import SessionManager

    sm = SessionManager(silence_timeout_s=30)
    sm.open(trigger="wake_word")
    assert sm.state == "active"
    assert sm.is_active
    assert sm.trigger == "wake_word"

    sm.close(reason="explicit")
    assert sm.state == "idle"
    assert not sm.is_active


def test_session_tracks_speaker():
    from agents.hapax_voice.session import SessionManager

    sm = SessionManager(silence_timeout_s=30)
    sm.open(trigger="hotkey")
    sm.set_speaker("ryan", confidence=0.92)
    assert sm.speaker == "ryan"
    assert sm.speaker_confidence == 0.92


def test_session_guest_mode():
    from agents.hapax_voice.session import SessionManager

    sm = SessionManager(silence_timeout_s=30)
    sm.open(trigger="wake_word")
    sm.set_speaker("unknown", confidence=0.3)
    assert sm.is_guest_mode


def test_session_silence_timeout():
    from agents.hapax_voice.session import SessionManager

    sm = SessionManager(silence_timeout_s=1)
    sm.open(trigger="hotkey")
    sm.mark_activity()
    time.sleep(1.1)
    assert sm.is_timed_out


def test_session_activity_resets_timeout():
    from agents.hapax_voice.session import SessionManager

    sm = SessionManager(silence_timeout_s=2)
    sm.open(trigger="hotkey")
    time.sleep(1)
    sm.mark_activity()
    time.sleep(1)
    assert not sm.is_timed_out


def test_open_while_active_is_noop():
    from agents.hapax_voice.session import SessionManager

    sm = SessionManager(silence_timeout_s=30)
    sm.open(trigger="wake_word")
    sm.open(trigger="hotkey")  # should not crash or change trigger
    assert sm.state == "active"


def test_close_while_idle_is_noop():
    from agents.hapax_voice.session import SessionManager

    sm = SessionManager(silence_timeout_s=30)
    sm.close(reason="explicit")  # should not crash
    assert sm.state == "idle"
```

**Step 2: Run test to verify it fails**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_session.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement session module**

```python
# agents/hapax_voice/session.py
"""Session lifecycle state machine for Hapax Voice."""
from __future__ import annotations

import logging
import time

log = logging.getLogger(__name__)


class VoiceSessionManager:
    """Manages voice conversation session state."""

    def __init__(self, silence_timeout_s: int = 30) -> None:
        self.silence_timeout_s = silence_timeout_s
        self.state: str = "idle"
        self.trigger: str | None = None
        self.speaker: str | None = None
        self.speaker_confidence: float = 0.0
        self._last_activity: float = 0.0
        self._opened_at: float = 0.0

    @property
    def is_active(self) -> bool:
        return self.state == "active"

    @property
    def is_guest_mode(self) -> bool:
        return self.is_active and self.speaker not in ("ryan", None)

    @property
    def is_timed_out(self) -> bool:
        if not self.is_active:
            return False
        return (time.monotonic() - self._last_activity) > self.silence_timeout_s

    def open(self, trigger: str) -> None:
        """Open a conversation session."""
        if self.is_active:
            return
        self.state = "active"
        self.trigger = trigger
        self.speaker = None
        self.speaker_confidence = 0.0
        self._opened_at = time.monotonic()
        self._last_activity = self._opened_at
        log.info("Session opened (trigger=%s)", trigger)

    def close(self, reason: str = "explicit") -> None:
        """Close the current session."""
        if not self.is_active:
            return
        duration = time.monotonic() - self._opened_at
        log.info("Session closed (reason=%s, duration=%.1fs)", reason, duration)
        self.state = "idle"
        self.trigger = None
        self.speaker = None
        self.speaker_confidence = 0.0

    def set_speaker(self, speaker: str, confidence: float) -> None:
        """Update identified speaker."""
        self.speaker = speaker
        self.speaker_confidence = confidence

    def mark_activity(self) -> None:
        """Reset silence timer (called on any speech/audio input)."""
        self._last_activity = time.monotonic()
```

**Step 4: Run tests to verify they pass**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_session.py -v`
Expected: 8 passed

**Step 5: Commit**

```bash
cd ~/projects/ai-agents
git add agents/hapax_voice/session.py tests/test_hapax_voice_session.py
git commit -m "feat(voice): session lifecycle state machine"
```

---

### Task 4: Presence detector

**Files:**
- Create: `~/projects/ai-agents/agents/hapax_voice/presence.py`
- Test: `~/projects/ai-agents/tests/test_hapax_voice_presence.py`

**Step 1: Write the failing test**

```python
# tests/test_hapax_voice_presence.py
"""Tests for presence detection scoring."""
import time


def test_presence_starts_absent():
    from agents.hapax_voice.presence import PresenceDetector

    pd = PresenceDetector(window_minutes=5, vad_threshold=0.4)
    assert pd.score == "likely_absent"


def test_presence_updates_on_vad():
    from agents.hapax_voice.presence import PresenceDetector

    pd = PresenceDetector(window_minutes=5, vad_threshold=0.4)
    # Simulate 10 VAD hits in quick succession
    for _ in range(10):
        pd.record_vad_event(confidence=0.8)
    assert pd.score == "likely_present"


def test_presence_uncertain_with_few_events():
    from agents.hapax_voice.presence import PresenceDetector

    pd = PresenceDetector(window_minutes=5, vad_threshold=0.4)
    pd.record_vad_event(confidence=0.5)
    pd.record_vad_event(confidence=0.6)
    assert pd.score in ("uncertain", "likely_present")


def test_presence_decays_over_time():
    from agents.hapax_voice.presence import PresenceDetector

    pd = PresenceDetector(window_minutes=0.01, vad_threshold=0.4)  # ~0.6s window
    for _ in range(10):
        pd.record_vad_event(confidence=0.9)
    assert pd.score == "likely_present"
    time.sleep(1)
    pd._prune_old_events()
    assert pd.score == "likely_absent"


def test_low_confidence_vad_ignored():
    from agents.hapax_voice.presence import PresenceDetector

    pd = PresenceDetector(window_minutes=5, vad_threshold=0.4)
    for _ in range(20):
        pd.record_vad_event(confidence=0.2)  # below threshold
    assert pd.score == "likely_absent"
```

**Step 2: Run test to verify it fails**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_presence.py -v`
Expected: FAIL

**Step 3: Implement presence detector**

```python
# agents/hapax_voice/presence.py
"""Presence detection via audio VAD events."""
from __future__ import annotations

import logging
import time
from collections import deque

log = logging.getLogger(__name__)

# Thresholds: events per window to determine presence
_LIKELY_PRESENT_MIN_EVENTS = 5
_UNCERTAIN_MIN_EVENTS = 2


class PresenceDetector:
    """Sliding-window presence scoring from VAD events."""

    def __init__(self, window_minutes: float = 5, vad_threshold: float = 0.4) -> None:
        self.window_seconds = window_minutes * 60
        self.vad_threshold = vad_threshold
        self._events: deque[float] = deque()

    def record_vad_event(self, confidence: float) -> None:
        """Record a VAD speech detection event if above threshold."""
        if confidence < self.vad_threshold:
            return
        self._events.append(time.monotonic())
        self._prune_old_events()

    def _prune_old_events(self) -> None:
        """Remove events outside the sliding window."""
        cutoff = time.monotonic() - self.window_seconds
        while self._events and self._events[0] < cutoff:
            self._events.popleft()

    @property
    def score(self) -> str:
        """Current presence assessment."""
        self._prune_old_events()
        count = len(self._events)
        if count >= _LIKELY_PRESENT_MIN_EVENTS:
            return "likely_present"
        if count >= _UNCERTAIN_MIN_EVENTS:
            return "uncertain"
        return "likely_absent"

    @property
    def event_count(self) -> int:
        """Number of VAD events in current window."""
        self._prune_old_events()
        return len(self._events)
```

**Step 4: Run tests to verify they pass**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_presence.py -v`
Expected: 5 passed

**Step 5: Commit**

```bash
cd ~/projects/ai-agents
git add agents/hapax_voice/presence.py tests/test_hapax_voice_presence.py
git commit -m "feat(voice): presence detector with sliding-window VAD scoring"
```

---

### Task 5: Context gate

**Files:**
- Create: `~/projects/ai-agents/agents/hapax_voice/context_gate.py`
- Test: `~/projects/ai-agents/tests/test_hapax_voice_context_gate.py`

**Step 1: Write the failing test**

```python
# tests/test_hapax_voice_context_gate.py
"""Tests for context gate — interrupt eligibility checks."""
from unittest.mock import patch


def test_gate_blocks_during_active_session():
    from agents.hapax_voice.context_gate import ContextGate
    from agents.hapax_voice.session import SessionManager

    sm = SessionManager(silence_timeout_s=30)
    sm.open(trigger="wake_word")
    gate = ContextGate(session=sm)
    result = gate.check()
    assert not result.eligible
    assert "active_session" in result.reason


def test_gate_allows_when_idle():
    from agents.hapax_voice.context_gate import ContextGate
    from agents.hapax_voice.session import SessionManager

    sm = SessionManager(silence_timeout_s=30)
    gate = ContextGate(session=sm)
    with patch.object(gate, "_check_volume", return_value=(True, "")):
        with patch.object(gate, "_check_studio", return_value=(True, "")):
            result = gate.check()
    assert result.eligible


def test_gate_blocks_high_volume():
    from agents.hapax_voice.context_gate import ContextGate
    from agents.hapax_voice.session import SessionManager

    sm = SessionManager(silence_timeout_s=30)
    gate = ContextGate(session=sm, volume_threshold=0.7)
    with patch.object(gate, "_get_sink_volume", return_value=0.85):
        with patch.object(gate, "_check_studio", return_value=(True, "")):
            result = gate.check()
    assert not result.eligible
    assert "volume" in result.reason


def test_gate_blocks_studio_active():
    from agents.hapax_voice.context_gate import ContextGate
    from agents.hapax_voice.session import SessionManager

    sm = SessionManager(silence_timeout_s=30)
    gate = ContextGate(session=sm)
    with patch.object(gate, "_check_volume", return_value=(True, "")):
        with patch.object(gate, "_check_studio", return_value=(False, "midi_active")):
            result = gate.check()
    assert not result.eligible
    assert "midi_active" in result.reason
```

**Step 2: Run test to verify it fails**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_context_gate.py -v`
Expected: FAIL

**Step 3: Implement context gate**

```python
# agents/hapax_voice/context_gate.py
"""Context gate — determines if this is a good moment to interrupt."""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass

from agents.hapax_voice.session import SessionManager

log = logging.getLogger(__name__)


@dataclass
class GateResult:
    eligible: bool
    reason: str = ""


class ContextGate:
    """Layered checks for interrupt eligibility."""

    def __init__(
        self,
        session: SessionManager,
        volume_threshold: float = 0.7,
    ) -> None:
        self.session = session
        self.volume_threshold = volume_threshold

    def check(self) -> GateResult:
        """Run all gate checks, cheapest first."""
        # 1. Active voice session?
        if self.session.is_active:
            return GateResult(eligible=False, reason="active_session")

        # 2. Speaker volume too high?
        vol_ok, vol_reason = self._check_volume()
        if not vol_ok:
            return GateResult(eligible=False, reason=vol_reason)

        # 3. Studio/MIDI active?
        studio_ok, studio_reason = self._check_studio()
        if not studio_ok:
            return GateResult(eligible=False, reason=studio_reason)

        return GateResult(eligible=True)

    def _check_volume(self) -> tuple[bool, str]:
        """Check if PipeWire output volume is below threshold."""
        vol = self._get_sink_volume()
        if vol > self.volume_threshold:
            return False, f"volume_high ({vol:.0%})"
        return True, ""

    def _get_sink_volume(self) -> float:
        """Get default sink volume via wpctl. Returns 0.0-1.0+."""
        try:
            result = subprocess.run(
                ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
                capture_output=True, text=True, timeout=2,
            )
            # Output: "Volume: 0.50"
            if result.returncode == 0:
                parts = result.stdout.strip().split()
                if len(parts) >= 2:
                    return float(parts[-1])
        except Exception as exc:
            log.debug("Failed to get sink volume: %s", exc)
        return 0.0

    def _check_studio(self) -> tuple[bool, str]:
        """Check if studio processes or MIDI devices are active."""
        try:
            result = subprocess.run(
                ["aconnect", "-l"], capture_output=True, text=True, timeout=2,
            )
            if result.returncode == 0:
                lines = result.stdout
                # Check for active MIDI connections (not just listed ports)
                # Connected ports have "Connected From" or "Connecting To" lines
                if "Connecting To:" in lines or "Connected From:" in lines:
                    return False, "midi_active"
        except Exception as exc:
            log.debug("Failed to check MIDI: %s", exc)
        return True, ""
```

**Step 4: Run tests to verify they pass**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_context_gate.py -v`
Expected: 4 passed

**Step 5: Commit**

```bash
cd ~/projects/ai-agents
git add agents/hapax_voice/context_gate.py tests/test_hapax_voice_context_gate.py
git commit -m "feat(voice): context gate for interrupt eligibility"
```

---

### Task 6: Speaker identification

**Files:**
- Create: `~/projects/ai-agents/agents/hapax_voice/speaker_id.py`
- Test: `~/projects/ai-agents/tests/test_hapax_voice_speaker_id.py`

**Step 1: Write the failing test**

```python
# tests/test_hapax_voice_speaker_id.py
"""Tests for speaker identification via pyannote embeddings."""
import numpy as np


def test_speaker_id_no_enrollment_returns_uncertain():
    from agents.hapax_voice.speaker_id import SpeakerIdentifier

    si = SpeakerIdentifier(enrollment_path=None)
    result = si.identify(np.random.randn(256).astype(np.float32))
    assert result.label == "uncertain"
    assert result.confidence == 0.0


def test_speaker_id_high_similarity_returns_ryan():
    from agents.hapax_voice.speaker_id import SpeakerIdentifier, SpeakerResult

    si = SpeakerIdentifier(enrollment_path=None)
    # Manually set enrollment embedding
    embedding = np.random.randn(256).astype(np.float32)
    embedding = embedding / np.linalg.norm(embedding)
    si._enrolled_embedding = embedding

    # Same embedding + small noise = high similarity
    noisy = embedding + np.random.randn(256).astype(np.float32) * 0.05
    result = si.identify(noisy)
    assert result.label == "ryan"
    assert result.confidence > 0.8


def test_speaker_id_low_similarity_returns_not_ryan():
    from agents.hapax_voice.speaker_id import SpeakerIdentifier

    si = SpeakerIdentifier(enrollment_path=None)
    embedding = np.random.randn(256).astype(np.float32)
    embedding = embedding / np.linalg.norm(embedding)
    si._enrolled_embedding = embedding

    # Completely different embedding
    different = np.random.randn(256).astype(np.float32)
    different = different / np.linalg.norm(different)
    # Force orthogonal
    different = different - np.dot(different, embedding) * embedding
    different = different / np.linalg.norm(different)

    result = si.identify(different)
    assert result.label == "not_ryan"


def test_cosine_similarity():
    from agents.hapax_voice.speaker_id import _cosine_similarity

    a = np.array([1.0, 0.0, 0.0])
    b = np.array([1.0, 0.0, 0.0])
    assert abs(_cosine_similarity(a, b) - 1.0) < 1e-6

    c = np.array([0.0, 1.0, 0.0])
    assert abs(_cosine_similarity(a, c)) < 1e-6
```

**Step 2: Run test to verify it fails**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_speaker_id.py -v`
Expected: FAIL

**Step 3: Implement speaker identification**

```python
# agents/hapax_voice/speaker_id.py
"""Speaker identification using pyannote embeddings."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

_RYAN_THRESHOLD = 0.75
_NOT_RYAN_THRESHOLD = 0.4


@dataclass
class SpeakerResult:
    label: str  # "ryan", "not_ryan", "uncertain"
    confidence: float


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


class SpeakerIdentifier:
    """Compare audio embeddings against enrolled speaker."""

    def __init__(self, enrollment_path: Path | None = None) -> None:
        self._enrolled_embedding: np.ndarray | None = None
        self._model = None
        if enrollment_path and enrollment_path.exists():
            self._enrolled_embedding = np.load(enrollment_path)
            log.info("Loaded speaker enrollment from %s", enrollment_path)

    def identify(self, embedding: np.ndarray) -> SpeakerResult:
        """Compare embedding against enrolled speaker."""
        if self._enrolled_embedding is None:
            return SpeakerResult(label="uncertain", confidence=0.0)

        sim = _cosine_similarity(embedding, self._enrolled_embedding)
        if sim >= _RYAN_THRESHOLD:
            return SpeakerResult(label="ryan", confidence=sim)
        if sim < _NOT_RYAN_THRESHOLD:
            return SpeakerResult(label="not_ryan", confidence=1.0 - sim)
        return SpeakerResult(label="uncertain", confidence=sim)

    def enroll(self, embedding: np.ndarray, save_path: Path) -> None:
        """Save a speaker embedding as the enrolled reference."""
        normalized = embedding / np.linalg.norm(embedding)
        np.save(save_path, normalized)
        self._enrolled_embedding = normalized
        log.info("Speaker enrollment saved to %s", save_path)
```

**Step 4: Run tests to verify they pass**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_speaker_id.py -v`
Expected: 4 passed

**Step 5: Commit**

```bash
cd ~/projects/ai-agents
git add agents/hapax_voice/speaker_id.py tests/test_hapax_voice_speaker_id.py
git commit -m "feat(voice): speaker identification via embedding comparison"
```

---

### Task 7: Intent router

**Files:**
- Create: `~/projects/ai-agents/agents/hapax_voice/intent_router.py`
- Test: `~/projects/ai-agents/tests/test_hapax_voice_intent.py`

**Step 1: Write the failing test**

```python
# tests/test_hapax_voice_intent.py
"""Tests for intent routing — conversational vs system-directed."""


def test_system_intent_briefing():
    from agents.hapax_voice.intent_router import classify_intent

    result = classify_intent("what's my briefing")
    assert result.backend == "local"
    assert "briefing" in result.matched_pattern


def test_system_intent_calendar():
    from agents.hapax_voice.intent_router import classify_intent

    result = classify_intent("pull up my calendar")
    assert result.backend == "local"


def test_system_intent_system_status():
    from agents.hapax_voice.intent_router import classify_intent

    result = classify_intent("how's the system doing")
    assert result.backend == "local"


def test_conversational_intent():
    from agents.hapax_voice.intent_router import classify_intent

    result = classify_intent("tell me about the history of jazz")
    assert result.backend == "gemini"


def test_conversational_generic():
    from agents.hapax_voice.intent_router import classify_intent

    result = classify_intent("what do you think about that")
    assert result.backend == "gemini"


def test_system_intent_meeting_prep():
    from agents.hapax_voice.intent_router import classify_intent

    result = classify_intent("give me the meeting prep for alex")
    assert result.backend == "local"


def test_hapax_prefix_forces_local():
    from agents.hapax_voice.intent_router import classify_intent

    result = classify_intent("hapax check my notifications")
    assert result.backend == "local"


def test_guest_mode_always_gemini():
    from agents.hapax_voice.intent_router import classify_intent

    result = classify_intent("what's my briefing", guest_mode=True)
    assert result.backend == "gemini"
```

**Step 2: Run test to verify it fails**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_intent.py -v`
Expected: FAIL

**Step 3: Implement intent router**

```python
# agents/hapax_voice/intent_router.py
"""Intent routing — classify utterances as system-directed or conversational."""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

# Patterns that indicate system-directed intent (case-insensitive)
_SYSTEM_PATTERNS: list[tuple[str, str]] = [
    (r"\bbriefing\b", "briefing"),
    (r"\bdigest\b", "digest"),
    (r"\bcalendar\b", "calendar"),
    (r"\bschedule\b", "calendar"),
    (r"\bmeeting\s*prep\b", "meeting_prep"),
    (r"\b1[:\s]*on[:\s]*1\b", "meeting_prep"),
    (r"\bsystem\s*(status|health|check)\b", "system_status"),
    (r"\bnotification", "notifications"),
    (r"\bhealth\s*(check|monitor|status)\b", "health"),
    (r"\bvram\b", "system_status"),
    (r"\bgpu\b", "system_status"),
    (r"\bdocker\b", "system_status"),
    (r"\bcontainer", "system_status"),
    (r"\btimer", "system_status"),
    (r"\bservice", "system_status"),
    (r"\brun\s+(the\s+)?agent\b", "agent_run"),
    (r"\bsearch\s+(my\s+)?(docs|documents|notes|rag)\b", "rag_search"),
]

# Prefix that forces local routing
_HAPAX_PREFIX = re.compile(r"^\s*(?:hey\s+)?hapax\b[,:]?\s*", re.IGNORECASE)


@dataclass
class IntentResult:
    backend: str  # "gemini" or "local"
    matched_pattern: str


def classify_intent(text: str, guest_mode: bool = False) -> IntentResult:
    """Classify an utterance for backend routing.

    Args:
        text: Transcribed utterance text.
        guest_mode: If True, always route to Gemini (no system access).

    Returns:
        IntentResult with backend selection and matched pattern.
    """
    if guest_mode:
        return IntentResult(backend="gemini", matched_pattern="guest_mode")

    # Strip "Hapax" prefix — its presence already implies system intent
    cleaned = text
    hapax_match = _HAPAX_PREFIX.match(text)
    if hapax_match:
        cleaned = text[hapax_match.end():]
        # If there's remaining text after "hapax", check patterns
        # If nothing remains, still route local (they addressed Hapax directly)
        if not cleaned.strip():
            return IntentResult(backend="local", matched_pattern="hapax_direct")

    lower = cleaned.lower()

    # Check system patterns
    for pattern, name in _SYSTEM_PATTERNS:
        if re.search(pattern, lower):
            return IntentResult(backend="local", matched_pattern=name)

    # Hapax prefix without matching pattern still routes local
    if hapax_match:
        return IntentResult(backend="local", matched_pattern="hapax_prefix")

    return IntentResult(backend="gemini", matched_pattern="conversational")
```

**Step 4: Run tests to verify they pass**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_intent.py -v`
Expected: 8 passed

**Step 5: Commit**

```bash
cd ~/projects/ai-agents
git add agents/hapax_voice/intent_router.py tests/test_hapax_voice_intent.py
git commit -m "feat(voice): intent router for backend selection"
```

---

### Task 8: Notification queue with TTL

**Files:**
- Create: `~/projects/ai-agents/agents/hapax_voice/notification_queue.py`
- Test: `~/projects/ai-agents/tests/test_hapax_voice_notifications.py`

**Step 1: Write the failing test**

```python
# tests/test_hapax_voice_notifications.py
"""Tests for notification queue with priority and TTL."""
import time


def test_enqueue_and_dequeue():
    from agents.hapax_voice.notification_queue import NotificationQueue, VoiceNotification

    q = NotificationQueue()
    n = VoiceNotification(title="Test", message="Hello", priority="normal", source="ntfy")
    q.enqueue(n)
    assert q.pending_count == 1
    item = q.next()
    assert item is not None
    assert item.title == "Test"
    assert q.pending_count == 0


def test_urgent_dequeues_first():
    from agents.hapax_voice.notification_queue import NotificationQueue, VoiceNotification

    q = NotificationQueue()
    q.enqueue(VoiceNotification(title="Low", message="x", priority="low", source="test"))
    q.enqueue(VoiceNotification(title="Urgent", message="x", priority="urgent", source="test"))
    q.enqueue(VoiceNotification(title="Normal", message="x", priority="normal", source="test"))
    item = q.next()
    assert item.title == "Urgent"


def test_ttl_expiry():
    from agents.hapax_voice.notification_queue import NotificationQueue, VoiceNotification

    q = NotificationQueue(ttls={"low": 0, "normal": 14400, "urgent": 1800})
    # Low priority with TTL 0 means deliver-or-discard
    q.enqueue(VoiceNotification(title="Low", message="x", priority="low", source="test"))
    # It should still be available immediately
    item = q.next()
    assert item is not None


def test_expired_items_pruned():
    from agents.hapax_voice.notification_queue import NotificationQueue, VoiceNotification

    q = NotificationQueue(ttls={"low": 0, "normal": 1, "urgent": 1800})
    q.enqueue(VoiceNotification(title="Normal", message="x", priority="normal", source="test"))
    time.sleep(1.1)
    q.prune_expired()
    assert q.pending_count == 0


def test_requeue():
    from agents.hapax_voice.notification_queue import NotificationQueue, VoiceNotification

    q = NotificationQueue()
    n = VoiceNotification(title="Test", message="Hello", priority="normal", source="test")
    q.enqueue(n)
    item = q.next()
    q.requeue(item)
    assert q.pending_count == 1
```

**Step 2: Run test to verify it fails**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_notifications.py -v`
Expected: FAIL

**Step 3: Implement notification queue**

```python
# agents/hapax_voice/notification_queue.py
"""Priority notification queue with TTL for proactive speech."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

_PRIORITY_ORDER = {"urgent": 0, "normal": 1, "low": 2}
_DEFAULT_TTLS = {"urgent": 1800, "normal": 14400, "low": 0}


@dataclass
class VoiceNotification:
    title: str
    message: str
    priority: str  # urgent, normal, low
    source: str  # ntfy, timer, calendar, system
    created_at: float = field(default_factory=time.monotonic)


class NotificationQueue:
    """Priority queue with TTL-based expiry."""

    def __init__(self, ttls: dict[str, int] | None = None) -> None:
        self._items: list[VoiceNotification] = []
        self._ttls = ttls or _DEFAULT_TTLS

    @property
    def pending_count(self) -> int:
        return len(self._items)

    def enqueue(self, notification: VoiceNotification) -> None:
        """Add a notification to the queue."""
        self._items.append(notification)
        self._items.sort(key=lambda n: _PRIORITY_ORDER.get(n.priority, 1))
        log.info("Queued notification: %s (priority=%s)", notification.title, notification.priority)

    def next(self) -> VoiceNotification | None:
        """Pop the highest-priority non-expired notification."""
        self.prune_expired()
        if not self._items:
            return None
        return self._items.pop(0)

    def requeue(self, notification: VoiceNotification) -> None:
        """Put a notification back (e.g., user said 'later')."""
        self.enqueue(notification)

    def prune_expired(self) -> None:
        """Remove notifications past their TTL."""
        now = time.monotonic()
        before = len(self._items)
        self._items = [
            n for n in self._items
            if self._ttls.get(n.priority, 14400) == 0
            or (now - n.created_at) < self._ttls.get(n.priority, 14400)
        ]
        pruned = before - len(self._items)
        if pruned:
            log.info("Pruned %d expired notifications", pruned)
```

**Step 4: Run tests to verify they pass**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_notifications.py -v`
Expected: 5 passed

**Step 5: Commit**

```bash
cd ~/projects/ai-agents
git add agents/hapax_voice/notification_queue.py tests/test_hapax_voice_notifications.py
git commit -m "feat(voice): notification queue with priority and TTL"
```

---

### Task 9: Hapax persona and notification formatter

**Files:**
- Create: `~/projects/ai-agents/agents/hapax_voice/persona.py`
- Test: `~/projects/ai-agents/tests/test_hapax_voice_persona.py`

**Step 1: Write the failing test**

```python
# tests/test_hapax_voice_persona.py
"""Tests for Hapax persona — system prompts and notification formatting."""


def test_system_prompt_contains_name():
    from agents.hapax_voice.persona import system_prompt

    prompt = system_prompt()
    assert "Hapax" in prompt
    assert "the operator" in prompt


def test_system_prompt_guest_mode():
    from agents.hapax_voice.persona import system_prompt

    prompt = system_prompt(guest_mode=True)
    assert "Hapax" in prompt
    assert "system" not in prompt.lower() or "cannot" in prompt.lower()


def test_greeting_uses_cockpit_voice():
    from agents.hapax_voice.persona import voice_greeting

    g = voice_greeting()
    assert isinstance(g, str)
    assert len(g) > 0


def test_format_notification_for_speech():
    from agents.hapax_voice.persona import format_notification

    text = format_notification("Health Alert", "Qdrant unreachable on port 6333")
    assert isinstance(text, str)
    assert len(text) > 0
    # Should not just be the raw message
    assert "Qdrant" in text


def test_session_end_with_queued():
    from agents.hapax_voice.persona import session_end_message

    msg = session_end_message(queued_count=2)
    assert "2" in msg or "two" in msg.lower()


def test_session_end_no_queued():
    from agents.hapax_voice.persona import session_end_message

    msg = session_end_message(queued_count=0)
    assert msg  # should still say something
```

**Step 2: Run test to verify it fails**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_persona.py -v`
Expected: FAIL

**Step 3: Implement persona**

```python
# agents/hapax_voice/persona.py
"""Hapax persona — voice personality, system prompts, speech formatting."""
from __future__ import annotations

from cockpit.voice import greeting, operator_name

_SYSTEM_PROMPT = """\
You are Hapax, a voice assistant for {name}. You are warm but concise — \
friendly without being chatty. You have full access to {name}'s system: \
briefings, calendar, meeting prep, notifications, and infrastructure status. \
Keep responses spoken-natural and brief. When reading data, summarize — \
don't dump raw output. If asked to go deeper, elaborate. \
You know {name} well — use first name, skip formalities."""

_GUEST_PROMPT = """\
You are Hapax, a voice assistant. You're chatting with someone who isn't \
your primary operator. Be friendly and helpful for general conversation, \
but you cannot access system information, briefings, or personal data. \
If asked about those, explain that you'll need the operator for that."""

_NOTIFICATION_TEMPLATE = "Hey {name} — {summary}"


def system_prompt(guest_mode: bool = False) -> str:
    """System prompt for the LLM backend."""
    name = operator_name()
    if guest_mode:
        return _GUEST_PROMPT
    return _SYSTEM_PROMPT.format(name=name)


def voice_greeting() -> str:
    """Generate a spoken greeting using cockpit voice personality."""
    return greeting()


def format_notification(title: str, message: str) -> str:
    """Format a notification for spoken delivery.

    For now, simple template. Later tasks may add LLM reformatting.
    """
    name = operator_name()
    # Combine title and message into natural speech
    summary = f"{title.rstrip('.')}. {message}" if title != message else message
    return _NOTIFICATION_TEMPLATE.format(name=name, summary=summary)


def session_end_message(queued_count: int = 0) -> str:
    """Message to speak when closing a session."""
    if queued_count > 0:
        return f"Before you go — I have {queued_count} notification{'s' if queued_count != 1 else ''} queued. Want to hear {'them' if queued_count != 1 else 'it'}?"
    return "Catch you later."
```

**Step 4: Run tests to verify they pass**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_persona.py -v`
Expected: 6 passed

**Step 5: Commit**

```bash
cd ~/projects/ai-agents
git add agents/hapax_voice/persona.py tests/test_hapax_voice_persona.py
git commit -m "feat(voice): Hapax persona, system prompts, notification formatting"
```

---

### Task 10: TTS tier abstraction (Piper + Kokoro)

**Files:**
- Create: `~/projects/ai-agents/agents/hapax_voice/tts.py`
- Test: `~/projects/ai-agents/tests/test_hapax_voice_tts.py`

**Step 1: Write the failing test**

```python
# tests/test_hapax_voice_tts.py
"""Tests for TTS tier abstraction."""
from unittest.mock import patch, MagicMock
import numpy as np


def test_tier_selection_chime():
    from agents.hapax_voice.tts import select_tier

    tier = select_tier("chime")
    assert tier == "piper"


def test_tier_selection_confirmation():
    from agents.hapax_voice.tts import select_tier

    tier = select_tier("confirmation")
    assert tier == "piper"


def test_tier_selection_conversation():
    from agents.hapax_voice.tts import select_tier

    tier = select_tier("conversation")
    assert tier == "kokoro"


def test_tier_selection_notification():
    from agents.hapax_voice.tts import select_tier

    tier = select_tier("notification")
    assert tier == "kokoro"


def test_tts_manager_init():
    from agents.hapax_voice.tts import TTSManager

    mgr = TTSManager(kokoro_voice="af_heart")
    assert mgr.kokoro_voice == "af_heart"
```

**Step 2: Run test to verify it fails**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_tts.py -v`
Expected: FAIL

**Step 3: Implement TTS abstraction**

```python
# agents/hapax_voice/tts.py
"""Tiered TTS — Piper (CPU/instant) and Kokoro (GPU/quality)."""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

# Map use-case to tier
_TIER_MAP = {
    "chime": "piper",
    "confirmation": "piper",
    "short_ack": "piper",
    "conversation": "kokoro",
    "notification": "kokoro",
    "briefing": "kokoro",
    "proactive": "kokoro",
}


def select_tier(use_case: str) -> str:
    """Select TTS tier based on use case."""
    return _TIER_MAP.get(use_case, "kokoro")


class TTSManager:
    """Manages TTS synthesis across tiers."""

    def __init__(self, kokoro_voice: str = "af_heart") -> None:
        self.kokoro_voice = kokoro_voice
        self._piper_model = None
        self._kokoro_model = None

    def synthesize(self, text: str, use_case: str = "conversation") -> bytes:
        """Synthesize speech, selecting tier automatically.

        Returns raw PCM audio bytes (16-bit, 24kHz mono).
        """
        tier = select_tier(use_case)
        if tier == "piper":
            return self._synthesize_piper(text)
        return self._synthesize_kokoro(text)

    def _synthesize_piper(self, text: str) -> bytes:
        """Tier 1: Piper TTS (CPU, instant)."""
        if self._piper_model is None:
            try:
                import piper
                # Uses default English voice — downloads on first run
                self._piper_model = piper.PiperVoice.load(
                    str(Path.home() / ".local" / "share" / "piper" / "en_US-lessac-medium.onnx")
                )
            except Exception as exc:
                log.warning("Piper unavailable, falling back to Kokoro: %s", exc)
                return self._synthesize_kokoro(text)

        import io
        import wave
        audio_bytes = io.BytesIO()
        with wave.open(audio_bytes, "wb") as wf:
            self._piper_model.synthesize(text, wf)
        return audio_bytes.getvalue()

    def _synthesize_kokoro(self, text: str) -> bytes:
        """Tier 2: Kokoro TTS (GPU, quality)."""
        if self._kokoro_model is None:
            try:
                from kokoro import KPipeline
                self._kokoro_model = KPipeline(lang_code="a")
                log.info("Kokoro TTS loaded (voice=%s)", self.kokoro_voice)
            except Exception as exc:
                log.error("Kokoro TTS failed to load: %s", exc)
                raise

        import numpy as np
        import io
        import wave

        generator = self._kokoro_model(text, voice=self.kokoro_voice)
        chunks = []
        for _, _, audio in generator:
            chunks.append(audio)

        if not chunks:
            return b""

        audio = np.concatenate(chunks)
        # Kokoro outputs float32 at 24kHz — convert to int16
        audio_int16 = (audio * 32767).astype(np.int16)

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(audio_int16.tobytes())
        return buf.getvalue()
```

**Step 4: Run tests to verify they pass**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_tts.py -v`
Expected: 5 passed

**Step 5: Commit**

```bash
cd ~/projects/ai-agents
git add agents/hapax_voice/tts.py tests/test_hapax_voice_tts.py
git commit -m "feat(voice): tiered TTS abstraction (Piper + Kokoro)"
```

---

### Task 11: Hotkey activation via Unix socket

**Files:**
- Create: `~/projects/ai-agents/agents/hapax_voice/hotkey.py`
- Create: `~/.local/bin/llm-hotkeys/hapax-voice-toggle.sh`
- Test: `~/projects/ai-agents/tests/test_hapax_voice_hotkey.py`

**Step 1: Write the failing test**

```python
# tests/test_hapax_voice_hotkey.py
"""Tests for hotkey socket server."""
import asyncio
import tempfile
from pathlib import Path


async def test_socket_receives_toggle():
    from agents.hapax_voice.hotkey import HotkeyServer

    sock_path = Path(tempfile.mktemp(suffix=".sock"))
    commands: list[str] = []

    async def handler(cmd: str):
        commands.append(cmd)

    server = HotkeyServer(sock_path, handler)
    await server.start()

    # Send a toggle command
    reader, writer = await asyncio.open_unix_connection(str(sock_path))
    writer.write(b"toggle\n")
    await writer.drain()
    writer.close()
    await writer.wait_closed()

    await asyncio.sleep(0.1)
    await server.stop()
    sock_path.unlink(missing_ok=True)

    assert commands == ["toggle"]


async def test_socket_ignores_invalid():
    from agents.hapax_voice.hotkey import HotkeyServer

    sock_path = Path(tempfile.mktemp(suffix=".sock"))
    commands: list[str] = []

    async def handler(cmd: str):
        commands.append(cmd)

    server = HotkeyServer(sock_path, handler)
    await server.start()

    reader, writer = await asyncio.open_unix_connection(str(sock_path))
    writer.write(b"invalid_command\n")
    await writer.drain()
    writer.close()
    await writer.wait_closed()

    await asyncio.sleep(0.1)
    await server.stop()
    sock_path.unlink(missing_ok=True)

    assert commands == []
```

**Step 2: Run test to verify it fails**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_hotkey.py -v`
Expected: FAIL

**Step 3: Implement hotkey server**

```python
# agents/hapax_voice/hotkey.py
"""Unix socket server for hotkey activation."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_VALID_COMMANDS = {"toggle", "open", "close", "status"}


class HotkeyServer:
    """Listen on a Unix socket for hotkey commands."""

    def __init__(
        self,
        socket_path: Path,
        on_command: Callable[[str], Coroutine[Any, Any, None]],
    ) -> None:
        self.socket_path = socket_path
        self.on_command = on_command
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        """Start listening on the Unix socket."""
        self.socket_path.unlink(missing_ok=True)
        self._server = await asyncio.start_unix_server(
            self._handle_client, path=str(self.socket_path),
        )
        self.socket_path.chmod(0o600)
        log.info("Hotkey socket listening at %s", self.socket_path)

    async def stop(self) -> None:
        """Stop the socket server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        self.socket_path.unlink(missing_ok=True)

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
    ) -> None:
        try:
            data = await asyncio.wait_for(reader.readline(), timeout=2.0)
            cmd = data.decode().strip()
            if cmd in _VALID_COMMANDS:
                await self.on_command(cmd)
            else:
                log.debug("Ignoring invalid command: %s", cmd)
        except asyncio.TimeoutError:
            pass
        finally:
            writer.close()
            await writer.wait_closed()
```

**Step 4: Run tests to verify they pass**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_hotkey.py -v`
Expected: 2 passed

**Step 5: Create the hotkey shell script**

```bash
# ~/.local/bin/llm-hotkeys/hapax-voice-toggle.sh
#!/usr/bin/env bash
# Toggle Hapax Voice session via Unix socket
# Bind to Super+Shift+V in COSMIC keyboard settings
echo "toggle" | socat - UNIX-CONNECT:/run/user/$(id -u)/hapax-voice.sock
```

```bash
chmod +x ~/.local/bin/llm-hotkeys/hapax-voice-toggle.sh
```

**Step 6: Commit**

```bash
cd ~/projects/ai-agents
git add agents/hapax_voice/hotkey.py tests/test_hapax_voice_hotkey.py
git commit -m "feat(voice): hotkey activation via Unix socket"
```

---

### Task 12: ntfy listener for proactive notifications

**Files:**
- Create: `~/projects/ai-agents/agents/hapax_voice/ntfy_listener.py`
- Test: `~/projects/ai-agents/tests/test_hapax_voice_ntfy.py`

**Step 1: Write the failing test**

```python
# tests/test_hapax_voice_ntfy.py
"""Tests for ntfy event listener."""
import json


def test_parse_ntfy_message():
    from agents.hapax_voice.ntfy_listener import parse_ntfy_event

    raw = json.dumps({
        "id": "abc123",
        "event": "message",
        "topic": "cockpit",
        "title": "Health Alert",
        "message": "Qdrant unreachable",
        "priority": 4,
    })
    notif = parse_ntfy_event(raw)
    assert notif is not None
    assert notif.title == "Health Alert"
    assert notif.message == "Qdrant unreachable"
    assert notif.priority == "high"
    assert notif.source == "ntfy"


def test_parse_ntfy_keepalive_ignored():
    from agents.hapax_voice.ntfy_listener import parse_ntfy_event

    raw = json.dumps({"event": "keepalive"})
    assert parse_ntfy_event(raw) is None


def test_parse_ntfy_open_ignored():
    from agents.hapax_voice.ntfy_listener import parse_ntfy_event

    raw = json.dumps({"event": "open"})
    assert parse_ntfy_event(raw) is None


def test_priority_mapping():
    from agents.hapax_voice.ntfy_listener import _ntfy_priority_to_str

    assert _ntfy_priority_to_str(5) == "urgent"
    assert _ntfy_priority_to_str(4) == "high"
    assert _ntfy_priority_to_str(3) == "normal"
    assert _ntfy_priority_to_str(2) == "low"
    assert _ntfy_priority_to_str(1) == "low"
```

**Step 2: Run test to verify it fails**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_ntfy.py -v`
Expected: FAIL

**Step 3: Implement ntfy listener**

```python
# agents/hapax_voice/ntfy_listener.py
"""Subscribe to ntfy topics and convert to VoiceNotifications."""
from __future__ import annotations

import asyncio
import json
import logging
from urllib.request import urlopen, Request

from agents.hapax_voice.notification_queue import VoiceNotification

log = logging.getLogger(__name__)

_NTFY_PRIORITY_MAP = {5: "urgent", 4: "high", 3: "normal", 2: "low", 1: "low"}


def _ntfy_priority_to_str(priority: int) -> str:
    return _NTFY_PRIORITY_MAP.get(priority, "normal")


def parse_ntfy_event(raw: str) -> VoiceNotification | None:
    """Parse a single ntfy SSE event line into a VoiceNotification."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None

    if data.get("event") != "message":
        return None

    title = data.get("title", data.get("topic", "Notification"))
    message = data.get("message", "")
    priority = _ntfy_priority_to_str(data.get("priority", 3))

    # Map ntfy "high" to our queue's "urgent" for voice delivery
    if priority == "high":
        priority = "urgent"

    return VoiceNotification(
        title=title,
        message=message,
        priority=priority,
        source="ntfy",
    )


async def subscribe_ntfy(
    base_url: str,
    topics: list[str],
    on_notification: asyncio.coroutines,
) -> None:
    """Subscribe to ntfy topics via SSE stream.

    This runs in a loop, reconnecting on failure.
    """
    topic_str = ",".join(topics)
    url = f"{base_url}/{topic_str}/sse"
    log.info("Subscribing to ntfy: %s", url)

    while True:
        try:
            req = Request(url)
            with urlopen(req, timeout=300) as resp:
                for line_bytes in resp:
                    line = line_bytes.decode().strip()
                    if not line:
                        continue
                    notif = parse_ntfy_event(line)
                    if notif:
                        await on_notification(notif)
        except Exception as exc:
            log.warning("ntfy connection lost: %s, reconnecting in 5s", exc)
            await asyncio.sleep(5)
```

**Step 4: Run tests to verify they pass**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_ntfy.py -v`
Expected: 4 passed

**Step 5: Commit**

```bash
cd ~/projects/ai-agents
git add agents/hapax_voice/ntfy_listener.py tests/test_hapax_voice_ntfy.py
git commit -m "feat(voice): ntfy listener for proactive voice notifications"
```

---

### Task 13: VRAM coordinator

**Files:**
- Create: `~/projects/ai-agents/agents/hapax_voice/vram.py`
- Test: `~/projects/ai-agents/tests/test_hapax_voice_vram.py`

**Step 1: Write the failing test**

```python
# tests/test_hapax_voice_vram.py
"""Tests for VRAM lockfile coordination."""
import tempfile
from pathlib import Path


def test_acquire_lock():
    from agents.hapax_voice.vram import VRAMLock

    lock_path = Path(tempfile.mktemp(suffix=".lock"))
    lock = VRAMLock(lock_path)
    assert lock.acquire()
    assert lock_path.exists()
    lock.release()
    assert not lock_path.exists()


def test_lock_is_exclusive():
    from agents.hapax_voice.vram import VRAMLock

    lock_path = Path(tempfile.mktemp(suffix=".lock"))
    lock1 = VRAMLock(lock_path)
    lock2 = VRAMLock(lock_path)
    assert lock1.acquire()
    assert not lock2.acquire()
    lock1.release()
    assert lock2.acquire()
    lock2.release()


def test_lock_context_manager():
    from agents.hapax_voice.vram import VRAMLock

    lock_path = Path(tempfile.mktemp(suffix=".lock"))
    lock = VRAMLock(lock_path)
    with lock:
        assert lock_path.exists()
    assert not lock_path.exists()


def test_stale_lock_broken():
    from agents.hapax_voice.vram import VRAMLock

    lock_path = Path(tempfile.mktemp(suffix=".lock"))
    # Create a stale lock with a non-existent PID
    lock_path.write_text("999999999")
    lock = VRAMLock(lock_path)
    assert lock.acquire()  # should break stale lock
    lock.release()
```

**Step 2: Run test to verify it fails**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_vram.py -v`
Expected: FAIL

**Step 3: Implement VRAM lock**

```python
# agents/hapax_voice/vram.py
"""VRAM lockfile coordination between voice daemon and audio processor."""
from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_LOCK_PATH = Path.home() / ".cache" / "hapax-voice" / "vram.lock"


class VRAMLock:
    """PID-based lockfile for VRAM-intensive operations."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DEFAULT_LOCK_PATH
        self._held = False

    def acquire(self) -> bool:
        """Try to acquire the lock. Returns True if successful."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:
                pid = int(self.path.read_text().strip())
                # Check if the PID is still alive
                os.kill(pid, 0)
                return False  # Lock held by live process
            except (ValueError, ProcessLookupError, PermissionError):
                log.info("Breaking stale lock (pid file: %s)", self.path)
                self.path.unlink(missing_ok=True)

        try:
            self.path.write_text(str(os.getpid()))
            self._held = True
            return True
        except OSError:
            return False

    def release(self) -> None:
        """Release the lock."""
        if self._held:
            self.path.unlink(missing_ok=True)
            self._held = False

    def __enter__(self) -> VRAMLock:
        if not self.acquire():
            raise RuntimeError(f"Could not acquire VRAM lock at {self.path}")
        return self

    def __exit__(self, *args) -> None:
        self.release()
```

**Step 4: Run tests to verify they pass**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_vram.py -v`
Expected: 4 passed

**Step 5: Commit**

```bash
cd ~/projects/ai-agents
git add agents/hapax_voice/vram.py tests/test_hapax_voice_vram.py
git commit -m "feat(voice): VRAM lockfile coordination with audio processor"
```

---

### Task 14: Systemd service and health monitor integration

**Files:**
- Create: `~/projects/ai-agents/systemd/units/hapax-voice.service`
- Modify: `~/projects/ai-agents/agents/hapax_voice/__main__.py` (add daemon loop)

**Step 1: Create the systemd service unit**

```ini
# systemd/units/hapax-voice.service
[Unit]
Description=Hapax Voice — persistent voice interaction daemon
After=pipewire.service pipewire-pulse.service
Wants=pipewire-pulse.service
StartLimitBurst=5
StartLimitIntervalSec=300
OnFailure=notify-failure@%n.service

[Service]
Type=simple
WorkingDirectory=/home/hapaxlegomenon/projects/ai-agents
ExecStart=/home/hapaxlegomenon/.local/bin/uv run python -m agents.hapax_voice
Restart=always
RestartSec=10
Environment=PATH=/home/hapaxlegomenon/.local/bin:/usr/local/bin:/usr/bin:/bin
Environment=HOME=/home/hapaxlegomenon
MemoryMax=8G
SyslogIdentifier=hapax-voice

[Install]
WantedBy=default.target
```

**Step 2: Update __main__.py with daemon loop skeleton**

```python
# agents/hapax_voice/__main__.py
"""Entry point for hapax-voice daemon."""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal

from agents.hapax_voice.config import load_config
from agents.hapax_voice.session import SessionManager
from agents.hapax_voice.presence import PresenceDetector
from agents.hapax_voice.context_gate import ContextGate
from agents.hapax_voice.hotkey import HotkeyServer
from agents.hapax_voice.notification_queue import NotificationQueue

log = logging.getLogger("hapax_voice")


class VoiceDaemon:
    """Main daemon coordinating all voice subsystems."""

    def __init__(self) -> None:
        self.cfg = load_config()
        self.session = SessionManager(silence_timeout_s=self.cfg.silence_timeout_s)
        self.presence = PresenceDetector(
            window_minutes=self.cfg.presence_window_minutes,
            vad_threshold=self.cfg.presence_vad_threshold,
        )
        self.gate = ContextGate(
            session=self.session,
            volume_threshold=self.cfg.context_gate_volume_threshold,
        )
        self.notifications = NotificationQueue(
            ttls=self.cfg.notification_priority_ttls,
        )
        self.hotkey = HotkeyServer(
            socket_path=__import__("pathlib").Path(self.cfg.hotkey_socket),
            on_command=self._handle_hotkey,
        )
        self._running = True

    async def _handle_hotkey(self, cmd: str) -> None:
        """Handle hotkey commands."""
        if cmd == "toggle":
            if self.session.is_active:
                self.session.close(reason="hotkey")
            else:
                self.session.open(trigger="hotkey")
        elif cmd == "open":
            self.session.open(trigger="hotkey")
        elif cmd == "close":
            self.session.close(reason="hotkey")
        elif cmd == "status":
            log.info("Status: session=%s presence=%s queue=%d",
                     self.session.state, self.presence.score,
                     self.notifications.pending_count)

    async def run(self) -> None:
        """Main daemon loop."""
        log.info("Hapax Voice daemon starting")

        # Start hotkey listener
        await self.hotkey.start()

        # TODO: Start wake word listener (Task 15)
        # TODO: Start Pipecat audio pipeline (Task 16)
        # TODO: Start ntfy subscription (Task 12 integration)
        # TODO: Start presence monitoring loop

        # Main loop — check timeouts, process queue
        try:
            while self._running:
                # Check session timeout
                if self.session.is_active and self.session.is_timed_out:
                    self.session.close(reason="silence_timeout")

                # Prune expired notifications
                self.notifications.prune_expired()

                await asyncio.sleep(1)
        finally:
            await self.hotkey.stop()
            log.info("Hapax Voice daemon stopped")

    def stop(self) -> None:
        self._running = False


def main() -> None:
    parser = argparse.ArgumentParser(description="Hapax Voice daemon")
    parser.add_argument("--config", type=str, help="Path to config YAML")
    parser.add_argument("--check", action="store_true", help="Verify config and exit")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    cfg = load_config(args.config)
    if args.check:
        print(cfg.model_dump_json(indent=2))
        return

    daemon = VoiceDaemon()

    loop = asyncio.new_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, daemon.stop)

    try:
        loop.run_until_complete(daemon.run())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
```

**Step 3: Test the daemon starts and responds to hotkey**

Run: `cd ~/projects/ai-agents && timeout 5 uv run python -m agents.hapax_voice --check`
Expected: JSON config printed

Run: `cd ~/projects/ai-agents && timeout 3 uv run python -m agents.hapax_voice || true`
Expected: "Hapax Voice daemon starting" in output, exits on timeout

**Step 4: Install the service**

```bash
cp ~/projects/ai-agents/systemd/units/hapax-voice.service ~/.config/systemd/user/
systemctl --user daemon-reload
# Don't enable yet — will enable after audio pipeline integration
```

**Step 5: Commit**

```bash
cd ~/projects/ai-agents
git add systemd/units/hapax-voice.service agents/hapax_voice/__main__.py
git commit -m "feat(voice): daemon loop, systemd service, hotkey integration"
```

---

### Task 15: OpenWakeWord custom model training and integration

**Files:**
- Create: `~/projects/ai-agents/agents/hapax_voice/wake_word.py`
- Create: `~/projects/ai-agents/scripts/train-hapax-wake-word.py`
- Test: `~/projects/ai-agents/tests/test_hapax_voice_wake_word.py`

**Step 1: Write the failing test**

```python
# tests/test_hapax_voice_wake_word.py
"""Tests for wake word detection wrapper."""
from unittest.mock import patch, MagicMock
import numpy as np


def test_wake_word_detector_init():
    from agents.hapax_voice.wake_word import WakeWordDetector

    # Should init without crashing even without model
    wd = WakeWordDetector(model_path=None, threshold=0.5)
    assert wd.threshold == 0.5


def test_wake_word_callback_fires():
    from agents.hapax_voice.wake_word import WakeWordDetector

    detected = []
    wd = WakeWordDetector(model_path=None, threshold=0.5)
    wd.on_wake_word = lambda: detected.append(True)

    # Simulate detection by calling the callback directly
    wd._handle_detection(score=0.8)
    assert len(detected) == 1


def test_wake_word_below_threshold_ignored():
    from agents.hapax_voice.wake_word import WakeWordDetector

    detected = []
    wd = WakeWordDetector(model_path=None, threshold=0.5)
    wd.on_wake_word = lambda: detected.append(True)

    wd._handle_detection(score=0.3)
    assert len(detected) == 0
```

**Step 2: Run test to verify it fails**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_wake_word.py -v`
Expected: FAIL

**Step 3: Implement wake word wrapper**

```python
# agents/hapax_voice/wake_word.py
"""OpenWakeWord integration for 'Hapax' wake word detection."""
from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

DEFAULT_MODEL_PATH = Path.home() / ".local" / "share" / "hapax-voice" / "hapax_wake_word.onnx"


class WakeWordDetector:
    """Wraps OpenWakeWord for custom 'Hapax' detection."""

    def __init__(
        self,
        model_path: Path | None = None,
        threshold: float = 0.5,
    ) -> None:
        self.model_path = model_path or DEFAULT_MODEL_PATH
        self.threshold = threshold
        self.on_wake_word: Callable[[], None] | None = None
        self._oww_model = None

    def load(self) -> None:
        """Load the OpenWakeWord model."""
        try:
            import openwakeword
            from openwakeword.model import Model

            if self.model_path.exists():
                self._oww_model = Model(
                    wakeword_models=[str(self.model_path)],
                    inference_framework="onnx",
                )
                log.info("Wake word model loaded: %s", self.model_path)
            else:
                log.warning("Wake word model not found at %s — wake word disabled", self.model_path)
        except ImportError:
            log.warning("openwakeword not installed — wake word disabled")

    def process_audio(self, audio_chunk: np.ndarray) -> None:
        """Process a 16kHz int16 audio chunk for wake word detection.

        Args:
            audio_chunk: numpy array of int16 audio samples at 16kHz.
        """
        if self._oww_model is None:
            return

        prediction = self._oww_model.predict(audio_chunk)
        for model_name, score in prediction.items():
            self._handle_detection(score)

    def _handle_detection(self, score: float) -> None:
        """Handle a potential wake word detection."""
        if score >= self.threshold:
            log.info("Wake word detected (score=%.2f)", score)
            if self.on_wake_word:
                self.on_wake_word()
```

**Step 4: Run tests to verify they pass**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_wake_word.py -v`
Expected: 3 passed

**Step 5: Create wake word training script**

```python
# scripts/train-hapax-wake-word.py
"""Train a custom OpenWakeWord model for 'Hapax' using synthetic speech.

Prerequisites:
    pip install openwakeword piper-tts

Usage:
    uv run python scripts/train-hapax-wake-word.py

This generates synthetic training data using Piper TTS, then trains
a custom ONNX model. The trained model is saved to:
    ~/.local/share/hapax-voice/hapax_wake_word.onnx
"""
from pathlib import Path
import subprocess
import sys


def main():
    output_dir = Path.home() / ".local" / "share" / "hapax-voice"
    output_dir.mkdir(parents=True, exist_ok=True)

    print("Wake word training script placeholder.")
    print("Full implementation requires:")
    print("  1. Generate 200+ 'hapax' and 'hey hapax' samples via Piper TTS")
    print("  2. Collect negative samples from ambient audio")
    print("  3. Train using openwakeword.train_custom_model()")
    print(f"  4. Save model to {output_dir / 'hapax_wake_word.onnx'}")
    print()
    print("For now, use openwakeword's built-in 'hey_jarvis' model as a stand-in.")
    print("See: https://github.com/dscripka/openWakeWord#training-new-models")


if __name__ == "__main__":
    main()
```

**Step 6: Commit**

```bash
cd ~/projects/ai-agents
git add agents/hapax_voice/wake_word.py tests/test_hapax_voice_wake_word.py scripts/train-hapax-wake-word.py
git commit -m "feat(voice): wake word detection wrapper + training script"
```

---

### Task 16: Pipecat audio pipeline with local cascade

**Files:**
- Create: `~/projects/ai-agents/agents/hapax_voice/pipeline.py`
- Test: `~/projects/ai-agents/tests/test_hapax_voice_pipeline.py`

This is the largest task — wiring Pipecat's `LocalAudioTransport` with STT, LLM, and TTS processors into a functioning voice pipeline.

**Step 1: Write the failing test**

```python
# tests/test_hapax_voice_pipeline.py
"""Tests for Pipecat pipeline configuration."""
from unittest.mock import patch, MagicMock, AsyncMock


def test_pipeline_config_local():
    from agents.hapax_voice.pipeline import PipelineConfig

    cfg = PipelineConfig(
        backend="local",
        stt_model="nvidia/parakeet-tdt-0.6b-v2",
        llm_model="claude-sonnet",
        kokoro_voice="af_heart",
    )
    assert cfg.backend == "local"
    assert cfg.stt_model == "nvidia/parakeet-tdt-0.6b-v2"


def test_pipeline_config_gemini():
    from agents.hapax_voice.pipeline import PipelineConfig

    cfg = PipelineConfig(
        backend="gemini",
        gemini_model="gemini-2.5-flash-preview-native-audio",
    )
    assert cfg.backend == "gemini"


async def test_build_local_pipeline_returns_processors():
    from agents.hapax_voice.pipeline import build_local_processors

    # Mock heavy dependencies
    with patch("agents.hapax_voice.pipeline._create_stt_processor") as mock_stt, \
         patch("agents.hapax_voice.pipeline._create_llm_processor") as mock_llm, \
         patch("agents.hapax_voice.pipeline._create_tts_processor") as mock_tts:
        mock_stt.return_value = MagicMock()
        mock_llm.return_value = MagicMock()
        mock_tts.return_value = MagicMock()

        processors = build_local_processors(
            stt_model="test", llm_model="test", kokoro_voice="af_heart",
            system_prompt="test prompt",
        )
        assert "stt" in processors
        assert "llm" in processors
        assert "tts" in processors
```

**Step 2: Run test to verify it fails**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_pipeline.py -v`
Expected: FAIL

**Step 3: Implement pipeline module**

```python
# agents/hapax_voice/pipeline.py
"""Pipecat pipeline configuration and construction."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    """Configuration for a voice pipeline instance."""
    backend: str = "local"  # "local" or "gemini"
    stt_model: str = "nvidia/parakeet-tdt-0.6b-v2"
    llm_model: str = "claude-sonnet"
    gemini_model: str = "gemini-2.5-flash-preview-native-audio"
    kokoro_voice: str = "af_heart"
    system_prompt: str = ""
    sample_rate: int = 16000


def _create_stt_processor(model: str):
    """Create STT processor (Parakeet or faster-whisper)."""
    # Lazy import to avoid loading heavy deps at module level
    log.info("Creating STT processor: %s", model)
    # Placeholder — actual Pipecat processor creation depends on
    # available STT service. Will use faster-whisper as initial fallback.
    try:
        from faster_whisper import WhisperModel
        return WhisperModel(
            "large-v3-turbo",
            device="cuda",
            compute_type="int8",
        )
    except Exception as exc:
        log.error("Failed to load STT model: %s", exc)
        raise


def _create_llm_processor(model: str, system_prompt: str):
    """Create LLM processor via LiteLLM/OpenAI compatible endpoint."""
    import os
    log.info("Creating LLM processor: %s", model)
    return {
        "model": model,
        "base_url": os.environ.get("LITELLM_BASE_URL", "http://localhost:4000/v1"),
        "api_key": os.environ.get("LITELLM_API_KEY", "changeme"),
        "system_prompt": system_prompt,
    }


def _create_tts_processor(voice: str):
    """Create TTS processor (Kokoro)."""
    log.info("Creating TTS processor: Kokoro (voice=%s)", voice)
    from agents.hapax_voice.tts import TTSManager
    return TTSManager(kokoro_voice=voice)


def build_local_processors(
    stt_model: str,
    llm_model: str,
    kokoro_voice: str,
    system_prompt: str,
) -> dict:
    """Build the local cascade pipeline processors.

    Returns dict of named processors for Pipecat pipeline assembly.
    Full Pipecat pipeline wiring happens in the daemon's run() method
    once LocalAudioTransport is available.
    """
    return {
        "stt": _create_stt_processor(stt_model),
        "llm": _create_llm_processor(llm_model, system_prompt),
        "tts": _create_tts_processor(kokoro_voice),
    }
```

**Step 4: Run tests to verify they pass**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_pipeline.py -v`
Expected: 3 passed

**Step 5: Commit**

```bash
cd ~/projects/ai-agents
git add agents/hapax_voice/pipeline.py tests/test_hapax_voice_pipeline.py
git commit -m "feat(voice): Pipecat pipeline config and processor construction"
```

---

### Task 17: Gemini Live backend

**Files:**
- Create: `~/projects/ai-agents/agents/hapax_voice/gemini_live.py`
- Test: `~/projects/ai-agents/tests/test_hapax_voice_gemini.py`

**Step 1: Write the failing test**

```python
# tests/test_hapax_voice_gemini.py
"""Tests for Gemini Live API client."""
from unittest.mock import patch


def test_gemini_config():
    from agents.hapax_voice.gemini_live import GeminiLiveConfig

    cfg = GeminiLiveConfig(
        model="gemini-2.5-flash-preview-native-audio",
        system_prompt="You are Hapax.",
    )
    assert cfg.model == "gemini-2.5-flash-preview-native-audio"


def test_gemini_session_lifecycle():
    from agents.hapax_voice.gemini_live import GeminiLiveSession

    session = GeminiLiveSession(
        model="test-model",
        system_prompt="test",
    )
    assert not session.is_connected
    # Can't test actual connection without API — but verify state management
    assert session.model == "test-model"
```

**Step 2: Run test to verify it fails**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_gemini.py -v`
Expected: FAIL

**Step 3: Implement Gemini Live client**

```python
# agents/hapax_voice/gemini_live.py
"""Gemini Live API client for speech-to-speech conversation."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class GeminiLiveConfig:
    model: str = "gemini-2.5-flash-preview-native-audio"
    system_prompt: str = ""


class GeminiLiveSession:
    """Manages a Gemini Live WebSocket session.

    Gemini Live provides speech-to-speech with native interruption support.
    Audio is sent/received as raw PCM over WebSocket.
    """

    def __init__(self, model: str, system_prompt: str) -> None:
        self.model = model
        self.system_prompt = system_prompt
        self._ws = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        """Open WebSocket connection to Gemini Live API."""
        api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            raise RuntimeError("GOOGLE_API_KEY or GEMINI_API_KEY required for Gemini Live")

        try:
            from google import genai

            client = genai.Client(api_key=api_key)
            config = genai.types.LiveConnectConfig(
                response_modalities=["AUDIO"],
                system_instruction=genai.types.Content(
                    parts=[genai.types.Part(text=self.system_prompt)]
                ),
            )
            self._session = client.aio.live.connect(
                model=self.model,
                config=config,
            )
            self._connected = True
            log.info("Gemini Live connected (model=%s)", self.model)
        except Exception as exc:
            log.error("Gemini Live connection failed: %s", exc)
            self._connected = False
            raise

    async def disconnect(self) -> None:
        """Close the WebSocket connection."""
        if self._session:
            try:
                await self._session.__aexit__(None, None, None)
            except Exception:
                pass
        self._connected = False
        log.info("Gemini Live disconnected")

    async def send_audio(self, audio_chunk: bytes) -> None:
        """Send audio chunk to Gemini Live."""
        if not self._connected:
            return
        # Implementation depends on google-genai SDK live session API
        pass

    async def receive_audio(self) -> bytes | None:
        """Receive audio response from Gemini Live."""
        if not self._connected:
            return None
        # Implementation depends on google-genai SDK live session API
        return None
```

**Step 4: Run tests to verify they pass**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_gemini.py -v`
Expected: 2 passed

**Step 5: Add google-genai dependency**

Add to pyproject.toml dependencies:
```toml
    "google-genai>=1.0.0",
```

**Step 6: Commit**

```bash
cd ~/projects/ai-agents
git add agents/hapax_voice/gemini_live.py tests/test_hapax_voice_gemini.py pyproject.toml
git commit -m "feat(voice): Gemini Live API client for S2S conversation"
```

---

### Task 18: End-to-end daemon integration and smoke test

**Files:**
- Modify: `~/projects/ai-agents/agents/hapax_voice/__main__.py` (wire all subsystems)
- Create: `~/projects/ai-agents/tests/test_hapax_voice_integration.py`

**Step 1: Write integration test**

```python
# tests/test_hapax_voice_integration.py
"""Integration tests for VoiceDaemon — verifies subsystem wiring."""
import asyncio
from unittest.mock import patch, MagicMock
from pathlib import Path


async def test_daemon_starts_and_stops():
    from agents.hapax_voice.__main__ import VoiceDaemon

    daemon = VoiceDaemon()
    # Run for 0.5s then stop
    async def stop_after_delay():
        await asyncio.sleep(0.5)
        daemon.stop()

    task = asyncio.create_task(stop_after_delay())
    await daemon.run()
    assert daemon.session.state == "idle"


async def test_daemon_hotkey_toggle():
    from agents.hapax_voice.__main__ import VoiceDaemon

    daemon = VoiceDaemon()
    await daemon._handle_hotkey("toggle")
    assert daemon.session.is_active
    await daemon._handle_hotkey("toggle")
    assert not daemon.session.is_active


def test_daemon_subsystem_init():
    from agents.hapax_voice.__main__ import VoiceDaemon

    daemon = VoiceDaemon()
    assert daemon.session is not None
    assert daemon.presence is not None
    assert daemon.gate is not None
    assert daemon.notifications is not None
    assert daemon.hotkey is not None


async def test_daemon_session_timeout():
    from agents.hapax_voice.__main__ import VoiceDaemon
    from agents.hapax_voice.config import VoiceConfig

    with patch("agents.hapax_voice.__main__.load_config") as mock_cfg:
        mock_cfg.return_value = VoiceConfig(silence_timeout_s=1)
        daemon = VoiceDaemon()

    daemon.session.open(trigger="test")
    assert daemon.session.is_active

    # Simulate timeout check
    import time
    time.sleep(1.1)
    if daemon.session.is_timed_out:
        daemon.session.close(reason="silence_timeout")
    assert not daemon.session.is_active
```

**Step 2: Run test to verify it fails**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_integration.py -v`
Expected: Depends on current __main__.py state

**Step 3: Wire subsystems in __main__.py**

The __main__.py from Task 14 already has the core wiring. Update it to include wake word and presence monitoring stubs:

In the `run()` method, add after hotkey start:

```python
        # Log subsystem status
        log.info("Subsystems initialized:")
        log.info("  Session: silence_timeout=%ds", self.cfg.silence_timeout_s)
        log.info("  Presence: window=%dmin, threshold=%.1f",
                 self.cfg.presence_window_minutes, self.cfg.presence_vad_threshold)
        log.info("  Context gate: volume_threshold=%.0f%%",
                 self.cfg.context_gate_volume_threshold * 100)
        log.info("  Notifications: %d pending", self.notifications.pending_count)
```

**Step 4: Run all hapax_voice tests**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hapax_voice_*.py -v`
Expected: All tests pass

**Step 5: Smoke test the daemon**

```bash
cd ~/projects/ai-agents
timeout 5 uv run python -m agents.hapax_voice 2>&1 || true
```

Expected output should show:
- "Hapax Voice daemon starting"
- Subsystem initialization logs
- Clean exit on timeout

**Step 6: Commit**

```bash
cd ~/projects/ai-agents
git add tests/test_hapax_voice_integration.py agents/hapax_voice/__main__.py
git commit -m "feat(voice): end-to-end daemon integration and smoke tests"
```

---

## Post-Implementation Tasks (Future Work)

These are explicitly deferred — do not implement now:

1. **Wake word model training** — Run the training script with real audio data after the daemon is stable
2. **Speaker enrollment** — Record the operator's voice, generate pyannote embedding, save to profiles/
3. **Gemini Live full integration** — Wire send_audio/receive_audio once google-genai SDK live API is tested
4. **Pipecat LocalAudioTransport** — Full audio I/O wiring with PipeWire echo-cancelled source
5. **Audio ducking** — Configure PipeWire module-role-duck for Hapax TTS output
6. **LLM notification reformatting** — Add Haiku call to format raw ntfy messages as natural speech
7. **Calendar event integration** — Subscribe to gcalendar-sync events for proactive meeting reminders
8. **Health monitor check group** — Add hapax-voice health checks to the health monitor agent
9. **First-week tuning** — Calibrate presence detection thresholds, wake word false positive rate
10. **Kokoro voice selection** — Test available Kokoro voices and pick one tonally similar to Gemini
