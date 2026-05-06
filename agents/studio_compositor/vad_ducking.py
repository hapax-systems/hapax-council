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


def _read_existing_state() -> dict:
    """Read the current voice-state file, return ``{}`` on any error.

    Existence-tolerant + JSON-tolerant: corrupt or missing files
    yield an empty dict so the merge-and-write step always succeeds.
    """
    if not VOICE_STATE_FILE.exists():
        return {}
    try:
        data = json.loads(VOICE_STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def publish_vad_state(speech_active: bool) -> None:
    """Atomically publish the current VAD speech-active state.

    Audio normalization PR-1: read-modify-write so any other key in
    the file (notably ``tts_active`` from the TtsStatePublisher) is
    preserved across the publish.
    """
    VOICE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = _read_existing_state()
    payload["operator_speech_active"] = bool(speech_active)
    tmp = VOICE_STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload))
    tmp.replace(VOICE_STATE_FILE)


def publish_tts_state(tts_active: bool) -> None:
    """Atomically publish TTS-active state into the voice-state file.

    Audio normalization PR-1 — companion to ``publish_vad_state``.
    Read-modify-write so the existing ``operator_speech_active`` key
    is preserved when only the TTS key flips. The compositor-side
    broadcast-bound ducker (PR-2) reads this key.
    """
    VOICE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = _read_existing_state()
    payload["tts_active"] = bool(tts_active)
    tmp = VOICE_STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload))
    tmp.replace(VOICE_STATE_FILE)


def _read_vad_state() -> bool | None:
    """Read the current VAD state, or None if file missing/unreadable.

    Validates the JSON root is a mapping. The DuckController thread
    polls this every 30 ms; a writer producing valid JSON whose root
    is null, a list, a string, or a number previously raised
    AttributeError out of ``data.get(...)``, killing the duck
    controller thread. Same corruption-class as the other recent
    SHM-read fixes (#2627, #2631, #2632, #2636 merged; queue open).
    """
    if not VOICE_STATE_FILE.exists():
        return None
    try:
        data = json.loads(VOICE_STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
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


# ── Audio normalization PR-3 — TTS-driven broadcast ducker ────────────


def _read_tts_state() -> bool | None:
    """Read tts_active from voice-state.json, or None if unreadable.

    Validates the JSON root is a mapping (same shape as
    :func:`_read_vad_state`). The TTS-driven broadcast ducker polls
    this on a 30 ms cadence; non-dict JSON would raise AttributeError
    on ``data.get(...)`` and tear down the ducker.
    """
    if not VOICE_STATE_FILE.exists():
        return None
    try:
        data = json.loads(VOICE_STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    val = data.get("tts_active")
    return bool(val) if isinstance(val, bool) else None


def _voice_state_age_s() -> float | None:
    """Seconds since voice-state.json was last modified, or None if missing."""
    if not VOICE_STATE_FILE.exists():
        return None
    try:
        return time.time() - VOICE_STATE_FILE.stat().st_mtime
    except OSError:
        return None


# Stale threshold for fail-open: if voice-state.json hasn't been touched
# in this long, force gain to 1.0 (broadcast continues at full level
# rather than going silent on a wedged publisher).
DEFAULT_STALE_THRESHOLD_S = 2.0


class FilterChainGain(Protocol):
    """Capability the TtsDuckController calls. Decouples controller
    from how the gain reaches PipeWire (control-interface socket /
    pactl / mock). ``set_gain(value)`` writes the new gain; the
    underlying transport handles atomicity + ordering.
    """

    def set_gain(self, gain: float) -> None: ...


class TtsDuckController:
    """Polls voice-state.json + drives a filter-chain gain on
    ``tts_active`` transitions. Audio normalization PR-3.

    Default behaviour: emit ``duck_gain`` (0.316 ≈ -10 dB) on
    transition to tts_active=true; emit ``default_gain`` (1.0) on
    transition to tts_active=false. Transition-only emission so the
    underlying gain ramp doesn't re-trigger on every poll.

    Fail-open posture: missing / corrupt / stale (> ``stale_threshold_s``)
    voice-state.json forces gain to default. Broadcast must keep
    playing at full level rather than going silent on a wedged
    publisher.
    """

    def __init__(
        self,
        gain_control: FilterChainGain,
        *,
        poll_interval_s: float = 0.03,
        default_gain: float = 1.0,
        duck_gain: float = 0.316,
        stale_threshold_s: float = DEFAULT_STALE_THRESHOLD_S,
    ):
        self._gain = gain_control
        self._poll_interval = poll_interval_s
        self._default_gain = default_gain
        self._duck_gain = duck_gain
        self._stale_threshold_s = stale_threshold_s
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_state: bool | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="TtsDuckController", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    def tick_once(self) -> None:
        """One iteration of the poll loop — testable in isolation."""
        new = _read_tts_state()
        age = _voice_state_age_s()
        if new is None or (age is not None and age > self._stale_threshold_s):
            if self._last_state is not False:
                self._safe_set_gain(self._default_gain)
                self._last_state = False
            return
        if new == self._last_state:
            return
        target = self._duck_gain if new else self._default_gain
        self._safe_set_gain(target)
        self._last_state = new

    def _safe_set_gain(self, gain: float) -> None:
        try:
            self._gain.set_gain(gain)
        except Exception as exc:
            log.warning("tts_ducking: set_gain(%.3f) failed: %s", gain, exc)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self.tick_once()
            time.sleep(self._poll_interval)
