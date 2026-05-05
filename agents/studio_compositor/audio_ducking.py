"""Backing-mix ducking around YouTube/React audio (CVS #145).

A bidirectional audio ducking controller for the broadcast backing mix
(DAW returns, synth strips, MPC pads — historically the PreSonus Studio
24c hardware before its 2026-05 retirement). Complements the
operator-voice-over-YouTube sidechain compressor shipped via
``config/pipewire/hapax-voice-over-ytube-duck.conf`` (VAD + VAD-driven ramp)
with a state machine that couples:

* **Voice activity** — operator speaking (from ``vad_ducking.VOICE_STATE_FILE``).
* **YouTube/React audio activity** — the React audio player / browser
  music bed producing audio (from ``/dev/shm/hapax-compositor/yt-audio-state.json``;
  written by the compositor's audio-level monitor).

State machine (4 states):

    NORMAL        — both idle; no duck applied.
    VOICE_ACTIVE  — operator speaks but YT is silent; duck YT to -12 dB.
    YT_ACTIVE     — YT audible but operator silent; duck backing sources
                    to -6 dB so the YT audio sits forward.
    BOTH_ACTIVE   — both fire; voice takes priority, YT further to -18 dB.

Gains are applied via PipeWire. Preferred transport: ``pw-cli set-param``
on the ``hapax-ytube-ducked`` and ``hapax-backing-ducked`` filter-chain
sink input-gain controls. Fallback: ``wpctl set-volume`` on the sink
itself (coarser but portable).

**Feature flag:** ``HAPAX_AUDIO_DUCKING_ACTIVE`` (default ``0``). When
off, the controller runs but dispatches no PipeWire changes — useful for
measuring VAD/YT-activity correlation without risking audio artefacts
during the operator's livestream.

**Hysteresis:** VAD can drop for up to ``_VAD_DEBOUNCE_S`` seconds
without flipping the state machine out of VOICE_ACTIVE. This prevents
the ``ducking → restoring → ducking`` oscillation that short VAD pauses
would otherwise cause.

**Observability:** ``hapax_audio_ducking_state{state}`` gauge (label per
state, set to 1 for the current state and 0 for the others). See
``metrics.set_audio_ducking_state``.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from agents.studio_compositor import metrics

log = logging.getLogger(__name__)

__all__ = [
    "DuckingState",
    "AudioDuckingController",
    "YT_AUDIO_STATE_FILE",
    "FEATURE_FLAG_ENV",
    "set_yt_audio_active",
    "read_yt_audio_active",
]


# Feature flag: controller runs but only dispatches PipeWire changes when
# this env var is "1" / "true". Default off.
FEATURE_FLAG_ENV: str = "HAPAX_AUDIO_DUCKING_ACTIVE"

# Where the React audio player / browser writes its "audio is flowing"
# bool. Written by a level-monitor tap on the ``hapax-ytube-ducked`` sink
# monitor; see compositor-side integration (out of scope for this PR —
# the file is read defensively here so the ducker is no-op until the
# publisher ships).
YT_AUDIO_STATE_FILE: Path = Path("/dev/shm/hapax-compositor/yt-audio-state.json")

# Poll cadence (matches vad_ducking's 30 ms so VAD and YT observations
# stay aligned).
_POLL_INTERVAL_S: float = 0.03

# VAD debounce — brief pauses <2 s shouldn't flip us out of VOICE_ACTIVE.
_VAD_DEBOUNCE_S: float = 2.0

# YT debounce — YT audio with a momentary silence shouldn't flip us out
# of YT_ACTIVE. Tuned shorter than VAD since YT gaps are usually track
# boundaries that we DO want to react to.
_YT_DEBOUNCE_S: float = 0.5

# Target gains per state (linear, where 1.0 is unity). The PipeWire
# filter-chain preset's input gain node is driven with these values.
# Defaults chosen to match the task's spec:
#   VOICE_ACTIVE → YT bed at -12 dB ≈ 0.251 linear
#   YT_ACTIVE    → backing sources at -6 dB ≈ 0.501 linear
#   BOTH_ACTIVE  → YT bed at -18 dB ≈ 0.126 linear
_DB_TO_LINEAR = lambda db: 10.0 ** (db / 20.0)  # noqa: E731


class DuckingState(StrEnum):
    NORMAL = "normal"
    VOICE_ACTIVE = "voice_active"
    YT_ACTIVE = "yt_active"
    BOTH_ACTIVE = "both_active"


@dataclass
class _GainTargets:
    """Per-state target gains for the YT bed + 24c backing mix."""

    yt_bed_linear: float = 1.0
    backing_linear: float = 1.0


@dataclass
class AudioDuckingController:
    """State machine + dispatcher for the bidirectional backing-mix duck.

    Runs on its own background thread. Reads VAD + YT-audio state at
    30 ms cadence; on state transitions, dispatches the target gains to
    PipeWire via the configured ``gain_dispatcher`` callable.

    The default dispatcher routes through ``pw-cli set-param`` on the
    ``hapax-ytube-ducked`` and ``hapax-backing-ducked`` filter-chain
    inputs. Tests override ``gain_dispatcher`` to a capturing stub.
    """

    vad_state_reader: Callable[[], bool | None] = field(default=None)  # type: ignore[assignment]
    yt_state_reader: Callable[[], bool | None] = field(default=None)  # type: ignore[assignment]
    gain_dispatcher: Callable[[str, float], None] | None = None
    poll_interval_s: float = _POLL_INTERVAL_S
    vad_debounce_s: float = _VAD_DEBOUNCE_S
    yt_debounce_s: float = _YT_DEBOUNCE_S
    feature_flag_reader: Callable[[], bool] | None = None

    _state: DuckingState = field(default=DuckingState.NORMAL, init=False)
    _last_vad_true_ts: float = field(default=0.0, init=False)
    _last_yt_true_ts: float = field(default=0.0, init=False)
    _stop_event: threading.Event = field(default_factory=threading.Event, init=False)
    _thread: threading.Thread | None = field(default=None, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    # Per-state gain targets. Exposed as a class attr so callers can
    # tune without subclassing.
    STATE_TARGETS: dict[DuckingState, _GainTargets] = field(
        default_factory=lambda: {
            DuckingState.NORMAL: _GainTargets(yt_bed_linear=1.0, backing_linear=1.0),
            DuckingState.VOICE_ACTIVE: _GainTargets(
                yt_bed_linear=_DB_TO_LINEAR(-12.0), backing_linear=1.0
            ),
            DuckingState.YT_ACTIVE: _GainTargets(
                yt_bed_linear=1.0, backing_linear=_DB_TO_LINEAR(-6.0)
            ),
            DuckingState.BOTH_ACTIVE: _GainTargets(
                yt_bed_linear=_DB_TO_LINEAR(-18.0), backing_linear=1.0
            ),
        },
        init=False,
    )

    # ── lifecycle ─────────────────────────────────────────────────

    def __post_init__(self) -> None:
        if self.vad_state_reader is None:
            self.vad_state_reader = _default_read_vad
        if self.yt_state_reader is None:
            self.yt_state_reader = read_yt_audio_active
        if self.gain_dispatcher is None:
            self.gain_dispatcher = _pw_cli_set_gain
        if self.feature_flag_reader is None:
            self.feature_flag_reader = _read_feature_flag

    def start(self) -> None:
        """Start the polling thread. Idempotent."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="AudioDuckingController", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the polling thread. Idempotent."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self._thread = None

    # ── state inspection ─────────────────────────────────────────

    @property
    def state(self) -> DuckingState:
        with self._lock:
            return self._state

    # ── core logic ───────────────────────────────────────────────

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception:
                log.debug("AudioDuckingController tick failed", exc_info=True)
            time.sleep(self.poll_interval_s)

    def tick(self, now: float | None = None) -> DuckingState:
        """One evaluation of the state machine. Returns the new state.

        Extracted from ``_run`` so tests can drive the FSM
        deterministically without spawning threads.
        """
        now_t = now if now is not None else time.monotonic()

        raw_vad = self.vad_state_reader() if self.vad_state_reader else None
        raw_yt = self.yt_state_reader() if self.yt_state_reader else None

        # Update "last-seen-True" timestamps. Hysteresis is driven off
        # these: voice is considered "active" while now - last_true <
        # debounce.
        if raw_vad:
            self._last_vad_true_ts = now_t
        if raw_yt:
            self._last_yt_true_ts = now_t

        voice_active = (now_t - self._last_vad_true_ts) < self.vad_debounce_s and (
            self._last_vad_true_ts > 0.0
        )
        yt_active = (now_t - self._last_yt_true_ts) < self.yt_debounce_s and (
            self._last_yt_true_ts > 0.0
        )

        new_state = _compute_state(voice_active, yt_active)

        with self._lock:
            old = self._state
            if new_state == old:
                return old
            self._state = new_state

        log.info("audio_ducking: %s → %s", old.value, new_state.value)
        metrics.set_audio_ducking_state(new_state.value)
        self._apply_state(new_state)
        return new_state

    def _apply_state(self, state: DuckingState) -> None:
        """Dispatch the per-state gains to PipeWire (feature-flag gated)."""
        enabled = bool(self.feature_flag_reader()) if self.feature_flag_reader else False
        if not enabled:
            log.debug("audio_ducking: feature flag OFF; would apply state=%s", state.value)
            return
        targets = self.STATE_TARGETS[state]
        dispatcher = self.gain_dispatcher
        if dispatcher is None:
            return
        try:
            dispatcher("hapax-ytube-ducked", targets.yt_bed_linear)
            dispatcher("hapax-backing-ducked", targets.backing_linear)
        except Exception:
            log.debug("audio_ducking: dispatcher failed", exc_info=True)


# --- state transition table -----------------------------------------


def _compute_state(voice_active: bool, yt_active: bool) -> DuckingState:
    if voice_active and yt_active:
        return DuckingState.BOTH_ACTIVE
    if voice_active:
        return DuckingState.VOICE_ACTIVE
    if yt_active:
        return DuckingState.YT_ACTIVE
    return DuckingState.NORMAL


# --- state readers / writers ----------------------------------------


def _default_read_vad() -> bool | None:
    """Default VAD reader — mirrors vad_ducking._read_vad_state."""
    from agents.studio_compositor import vad_ducking

    return vad_ducking._read_vad_state()


def set_yt_audio_active(active: bool, *, path: Path | None = None) -> None:
    """Atomically publish the YouTube/React audio-activity state.

    Called by the compositor's audio-level monitor on the
    ``hapax-ytube-ducked`` sink. Uses the same tmp+rename pattern as
    ``vad_ducking.publish_vad_state``.
    """
    target = path if path is not None else YT_AUDIO_STATE_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    payload = {"yt_audio_active": bool(active)}
    tmp.write_text(json.dumps(payload))
    tmp.replace(target)


def read_yt_audio_active(path: Path | None = None) -> bool | None:
    """Read the current YT audio-activity state, or None if unavailable."""
    target = path if path is not None else YT_AUDIO_STATE_FILE
    if not target.exists():
        return None
    try:
        data = json.loads(target.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    val = data.get("yt_audio_active")
    return bool(val) if isinstance(val, bool) else None


def _read_feature_flag() -> bool:
    """Read ``HAPAX_AUDIO_DUCKING_ACTIVE`` and coerce to bool."""
    raw = os.environ.get(FEATURE_FLAG_ENV, "").strip().lower()
    return raw in ("1", "true", "yes", "on")


# --- PipeWire dispatcher --------------------------------------------


def _pw_cli_set_gain(sink_name: str, linear_gain: float) -> None:
    """Set the named filter-chain sink's input gain via pw-cli.

    Falls back silently when pw-cli / the sink is unavailable — the
    controller must not crash a test / CI environment that has no
    PipeWire. Real failures are debug-logged.

    The filter-chain preset defines a ``gain`` control node;
    ``pw-cli set-param`` on the sink's ``Props`` surfaces it.
    """
    gain = max(0.0, min(1.0, float(linear_gain)))
    try:
        subprocess.run(
            [
                "wpctl",
                "set-volume",
                "@" + sink_name + "@",
                f"{gain:.3f}",
            ],
            timeout=2.0,
            check=False,
            capture_output=True,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        log.debug("pw-cli / wpctl unavailable; skipping gain set")
