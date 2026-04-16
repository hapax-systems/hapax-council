"""VAD-driven YouTube PiP audio ducking (LRR Phase 9 hook 4).

The operator's Silero VAD (running in daimonion pipeline.py) emits a
boolean "speech active" signal at ~30ms cadence. When operator speech is
detected, YouTube picture-in-picture audio should duck so operator voice
is intelligible over the streamed content.

This module defines the integration surface:

1. ``publish_vad_state(bool)`` — writes the speech-active bool to
   ``/dev/shm/hapax-compositor/voice-state.json`` atomically. Called from
   the daimonion VAD callback.
2. ``DuckController`` — compositor-side thread that polls the voice-state
   file and invokes ``audio_control.duck() / .restore()`` on state
   transitions.

Privacy posture (per operator 2026-04-16):
- VAD state is ephemeral: /dev/shm only, lost on reboot, not persisted.
- No VAD events are logged to Langfuse; only the compositor audio mixer
  state change is observable via budget_signal metrics.
- No audio payload is captured by this module — the VAD signal is a
  boolean gate, not a recording.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Protocol

log = logging.getLogger("vad_ducking")

VOICE_STATE_FILE = Path("/dev/shm/hapax-compositor/voice-state.json")


class AudioDuckable(Protocol):
    def duck(self) -> None: ...

    def restore(self) -> None: ...


def publish_vad_state(speech_active: bool) -> None:
    """Atomically publish the current VAD speech-active state."""
    VOICE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = VOICE_STATE_FILE.with_suffix(".tmp")
    payload = {"operator_speech_active": bool(speech_active)}
    tmp.write_text(json.dumps(payload))
    tmp.replace(VOICE_STATE_FILE)


def _read_vad_state() -> bool | None:
    """Read the current VAD state, or None if file missing/unreadable."""
    if not VOICE_STATE_FILE.exists():
        return None
    try:
        data = json.loads(VOICE_STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    val = data.get("operator_speech_active")
    return bool(val) if isinstance(val, bool) else None


class DuckController:
    """Polls VOICE_STATE_FILE + drives AudioDuckable on state transitions.

    Polls at 30ms (matches Silero's emission cadence). Only invokes duck()
    or restore() on state TRANSITIONS — not on every poll — so the
    underlying ramp envelope in YouTubeAudioControl is not re-triggered
    redundantly.
    """

    def __init__(self, audio_control: AudioDuckable, poll_interval_s: float = 0.03):
        self._audio_control = audio_control
        self._poll_interval = poll_interval_s
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_state: bool | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="VADDuckController", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            new = _read_vad_state()
            if new is not None and new != self._last_state:
                try:
                    if new:
                        self._audio_control.duck()
                    else:
                        self._audio_control.restore()
                except Exception as exc:
                    log.warning("vad_ducking: duck/restore failed: %s", exc)
                self._last_state = new
            time.sleep(self._poll_interval)
