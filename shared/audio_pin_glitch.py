"""Ryzen HDA codec pin-routing-stale detector — unified-audio Phase 5.

The Ryzen codec's pin multiplexer silently desynchronises from
PipeWire after a PipeWire restart that also enumerates a new USB
audio device (operator report: S-4 plug-in 2026-04-20). ``pactl``
reports the sink as RUNNING + unmuted but physical output stays
silent until the card profile is toggled off and back on. The
auto-fix subcommand at ``scripts/hapax-audio-topology watchdog``
runs the known-good recovery; this module owns DETECTION so the
recovery can be triggered automatically rather than waiting for
operator intervention.

Detection signature (per plan §lines 73-75):

    sink RUNNING + sink-input active + > 5 s elapsed + zero RMS on
    monitor port → PIN_GLITCH

The reader callable is injected so tests can pass deterministic RMS
samples without spinning up pactl. The default reader runs
``pactl get-sink-volume / monitor`` and parses the RMS field.

References:
- Plan: docs/superpowers/plans/2026-04-20-unified-audio-architecture-plan.md §Phase 5
- Memory: reference_ryzen_codec_pin_glitch
- CLI auto-fix: scripts/hapax-audio-topology watchdog
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

log = logging.getLogger(__name__)


# Diagnostic discriminant the CLI's verify subcommand (and Phase 5
# tests) check against. Stable string — operator scripts may grep
# for it, so renaming is a contract break.
DIAGNOSTIC_PIN_GLITCH: Literal["PIN_GLITCH"] = "PIN_GLITCH"

# A sink reporting RMS below this floor for the elapsed window is
# considered silent. -50 dB RMS is well below the noise floor of any
# real audio source; matches the spec example threshold.
DEFAULT_SILENCE_RMS_DB: float = -50.0

# How long the silence must persist before we call it a glitch. Per
# plan: > 5 s elapsed. Shorter windows would false-positive on
# normal short pauses between sink-input bursts.
DEFAULT_MIN_SILENCE_S: float = 5.0


@dataclass(frozen=True)
class SinkProbe:
    """One observation of a sink's runtime state.

    ``state`` is the pactl sink state ("RUNNING", "IDLE", "SUSPENDED").
    ``has_active_input`` is True iff at least one sink-input is bound
    (a real consumer is feeding the sink). ``monitor_rms_db`` is the
    instantaneous RMS reading from the sink's monitor port; -inf or
    NaN signals "no signal at all".
    """

    state: str
    has_active_input: bool
    monitor_rms_db: float


SinkProbeReader = Callable[[str], SinkProbe]


def is_silent(rms_db: float, *, threshold: float = DEFAULT_SILENCE_RMS_DB) -> bool:
    """A sample is silent when its RMS is below the threshold OR when
    the reader returned a sentinel (NaN / -inf) meaning "no signal".
    """
    # -inf compares correctly against the threshold; NaN does not, so
    # treat NaN explicitly as silent.
    if rms_db != rms_db:  # NaN check (NaN != NaN by IEEE 754)
        return True
    return rms_db < threshold


@dataclass(frozen=True)
class PinGlitchDetection:
    """Result of one detection cycle.

    ``diagnostic`` is None when the sink is healthy; ``DIAGNOSTIC_PIN_GLITCH``
    when the silent-running pattern is observed for >= ``min_silence_s``.
    ``elapsed_silent_s`` reports how long silence has persisted (zero
    when the most recent probe broke silence).
    """

    diagnostic: str | None
    elapsed_silent_s: float
    last_probe: SinkProbe


class PinGlitchDetector:
    """Stateful RMS-on-monitor watchdog.

    Construct one per sink. Each call to ``detect(probe)`` returns a
    PinGlitchDetection; callers (the CLI verify subcommand, a future
    systemd watchdog daemon) decide whether to invoke the auto-fix.

    Detection state machine:

        IDLE/SUSPENDED → silence_started_at = None (clear)
        RUNNING + active input + silent → silence_started_at = now
        RUNNING + active input + non-silent → silence_started_at = None (clear)
        RUNNING + no active input → silence_started_at = None (no consumer)

    The diagnostic fires when ``now - silence_started_at >= min_silence_s``
    and the RUNNING+active+silent triple still holds.
    """

    def __init__(
        self,
        *,
        silence_threshold_db: float = DEFAULT_SILENCE_RMS_DB,
        min_silence_s: float = DEFAULT_MIN_SILENCE_S,
        now_fn: Callable[[], float] = time.time,
    ) -> None:
        self._silence_threshold_db = silence_threshold_db
        self._min_silence_s = min_silence_s
        self._now_fn = now_fn
        self._silence_started_at: float | None = None

    @property
    def silence_started_at(self) -> float | None:
        """Wall-clock when silence began, or None if not currently silent."""
        return self._silence_started_at

    def detect(self, probe: SinkProbe) -> PinGlitchDetection:
        """One detection cycle. Returns the diagnostic + elapsed silent time."""
        now = self._now_fn()
        running = probe.state.upper() == "RUNNING"
        silent = is_silent(probe.monitor_rms_db, threshold=self._silence_threshold_db)
        symptom_active = running and probe.has_active_input and silent
        if not symptom_active:
            self._silence_started_at = None
            return PinGlitchDetection(diagnostic=None, elapsed_silent_s=0.0, last_probe=probe)
        if self._silence_started_at is None:
            self._silence_started_at = now
        elapsed = now - self._silence_started_at
        diagnostic: str | None
        if elapsed >= self._min_silence_s:
            diagnostic = DIAGNOSTIC_PIN_GLITCH
        else:
            diagnostic = None
        return PinGlitchDetection(
            diagnostic=diagnostic,
            elapsed_silent_s=elapsed,
            last_probe=probe,
        )


__all__ = [
    "DEFAULT_MIN_SILENCE_S",
    "DEFAULT_SILENCE_RMS_DB",
    "DIAGNOSTIC_PIN_GLITCH",
    "PinGlitchDetection",
    "PinGlitchDetector",
    "SinkProbe",
    "SinkProbeReader",
    "is_silent",
]
