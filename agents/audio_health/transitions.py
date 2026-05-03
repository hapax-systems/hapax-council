"""Hysteresis state machine for stage classifications.

The source research §1 H1 calls for two specific hysteresis windows:

- **Clipping**: ``crest < 5 + RMS > -10dBFS`` sustained 2s.
- **Silence**: ``RMS < -60dBFS`` sustained 5s during livestream
  (note: classifier defaults to -55 dBFS for the silence floor; the
  livestream-specific 5s sustain window is enforced here).

This module records a small ring of recent classifications per-stage,
detects sustained transitions into bad steady-states, and emits one
:class:`TransitionEvent` per actual transition (debounced by hysteresis
windows). False-positive auto-mute would be as bad as silence-on-stream
per the operator framing, so the detector never returns more than one
event per stage per transition — caller is free to ntfy at most once
per state change.

The brief-gaps-during-restart caveat is honoured by the dual-window
shape: a transient blip narrower than the sustain window cannot fire
the transition, and the silence detector specifically gates on a
``livestream_active`` flag that the daemon defaults to ``False``
(callers wire it from a livestream state file).
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Final

from agents.audio_health.classifier import (
    BAD_STEADY_STATES,
    Classification,
)

# Sustain-window defaults from source research §1 H1.
DEFAULT_CLIPPING_SUSTAIN_S: Final[float] = 2.0
DEFAULT_NOISE_SUSTAIN_S: Final[float] = 2.0
DEFAULT_SILENCE_SUSTAIN_S: Final[float] = 5.0

# Recovery sustain — once a stage transitions into a bad state, require
# this much continuous "good" history before we declare it recovered
# and re-arm the detector. Prevents flap-flap-flap notifications across
# borderline samples.
DEFAULT_RECOVERY_SUSTAIN_S: Final[float] = 10.0

# Bound on the history ring per stage. At 30s probe cycle that's
# 30 minutes of history retained, more than enough for the runbook
# anchor to pull "last 30s of upstream classifications" context.
_HISTORY_MAXLEN: Final[int] = 64


@dataclass(frozen=True)
class StageObservation:
    """One probe outcome stored on the per-stage history ring."""

    classification: Classification
    captured_at: float
    duration_s: float


@dataclass
class StageState:
    """Mutable per-stage detector state. Owned by :class:`TransitionDetector`."""

    name: str
    history: deque[StageObservation] = field(default_factory=lambda: deque(maxlen=_HISTORY_MAXLEN))
    current_state: Classification = Classification.MUSIC_VOICE
    bad_since: float | None = None
    last_event_at: float | None = None
    # _pending_class is internal: tracks the in-progress bad
    # classification while the sustain window is accruing. We can't
    # use current_state for this because current_state is the last
    # fired classification (operator-visible "what we last paged on")
    # and may legitimately differ from the in-progress class.
    _pending_class: Classification = Classification.MUSIC_VOICE

    def record(self, observation: StageObservation) -> None:
        self.history.append(observation)


@dataclass(frozen=True)
class TransitionEvent:
    """One transition into a bad steady-state at a stage.

    ``upstream_context`` is a tuple of ``(stage_name, classification)``
    tuples capturing the last classification at every other stage at
    the moment of detection. Per the source research §1 H1: "Include
    last 30s of upstream-stage classifications in the ntfy body so
    operator can see where the bad signal entered."
    """

    stage: str
    new_state: Classification
    previous_state: Classification
    detected_at: float
    sustained_for_s: float
    upstream_context: tuple[tuple[str, Classification], ...] = ()


class TransitionDetector:
    """Per-stage hysteresis detector + bad-steady-state alerter.

    Construct one instance per daemon run; feed it observations via
    :meth:`record_probe`; collect any returned events. Events are
    de-duplicated per-stage so caller can blindly forward each event
    to ntfy without bookkeeping.

    Time is injected (``now_fn``) so tests don't have to monkeypatch
    ``time.time``.
    """

    def __init__(
        self,
        *,
        stage_names: Iterable[str],
        clipping_sustain_s: float = DEFAULT_CLIPPING_SUSTAIN_S,
        noise_sustain_s: float = DEFAULT_NOISE_SUSTAIN_S,
        silence_sustain_s: float = DEFAULT_SILENCE_SUSTAIN_S,
        recovery_sustain_s: float = DEFAULT_RECOVERY_SUSTAIN_S,
    ) -> None:
        self._stages: dict[str, StageState] = {name: StageState(name=name) for name in stage_names}
        self._clipping_sustain_s = clipping_sustain_s
        self._noise_sustain_s = noise_sustain_s
        self._silence_sustain_s = silence_sustain_s
        self._recovery_sustain_s = recovery_sustain_s

    @property
    def stages(self) -> tuple[StageState, ...]:
        """Tuple of per-stage state, ordered by insertion."""
        return tuple(self._stages.values())

    def stage(self, name: str) -> StageState:
        return self._stages[name]

    def record_probe(
        self,
        stage_name: str,
        classification: Classification,
        captured_at: float,
        *,
        duration_s: float = 0.0,
        livestream_active: bool = False,
    ) -> list[TransitionEvent]:
        """Record one probe; return any new transition events.

        ``livestream_active`` gates the silence detector: silence on
        the OBS-bound stage during livestream is a P0; silence at any
        time off-air is expected (no broadcast intent → no signal).

        Returns a list because a single probe can in principle close a
        prior bad state (no event) and then immediately open a new one
        of a different class (1 event). Return type is always a list
        for caller iteration symmetry, even when length is 0 or 1.
        """

        if stage_name not in self._stages:
            # Stage joined dynamically — register on first sight.
            self._stages[stage_name] = StageState(name=stage_name)

        state = self._stages[stage_name]
        observation = StageObservation(
            classification=classification,
            captured_at=captured_at,
            duration_s=duration_s,
        )
        state.record(observation)

        events: list[TransitionEvent] = []
        is_bad = classification in BAD_STEADY_STATES

        # Silence at non-livestream is nominal (no broadcast intent),
        # so only count it as bad when livestream is active.
        if classification == Classification.SILENT and not livestream_active:
            is_bad = False

        sustain_required = self._sustain_for(classification, livestream_active)

        if is_bad:
            # Track the start of this bad-class run. Reset if either
            # we have no run open OR the classification changed
            # (different bad class → new sustain window).
            #
            # ``_pending_class`` is the class we're accruing time for;
            # ``current_state`` is the last *fired* class. They diverge
            # when we're inside the sustain window before firing.
            if state.bad_since is None or state._pending_class != classification:
                state.bad_since = captured_at
                state._pending_class = classification
            sustained_for = captured_at - state.bad_since
            if sustained_for >= sustain_required and state.current_state != classification:
                event = TransitionEvent(
                    stage=stage_name,
                    new_state=classification,
                    previous_state=state.current_state,
                    detected_at=captured_at,
                    sustained_for_s=sustained_for,
                    upstream_context=self._snapshot_upstream(stage_name),
                )
                state.current_state = classification
                state.last_event_at = captured_at
                events.append(event)
        else:
            if state.bad_since is not None:
                # Recovery: require a sustained "good" window before
                # we re-arm. We don't emit a recovery TransitionEvent
                # in this design — the daemon ntfys on entry to bad
                # only, recovery is implicit via the metric flipping
                # back. (Operator-loaded preference: notification
                # spam is worse than silent recovery.)
                recovery_window_seen = self._continuous_good_window(state, captured_at)
                if recovery_window_seen >= self._recovery_sustain_s:
                    state.bad_since = None
                    state.current_state = classification
                    state._pending_class = classification
            else:
                # Clean state continuing — keep current_state in sync.
                state.current_state = classification
                state._pending_class = classification

        return events

    def _sustain_for(
        self,
        classification: Classification,
        livestream_active: bool,
    ) -> float:
        if classification == Classification.CLIPPING:
            return self._clipping_sustain_s
        if classification == Classification.NOISE:
            return self._noise_sustain_s
        if classification == Classification.SILENT and livestream_active:
            return self._silence_sustain_s
        return self._noise_sustain_s

    def _continuous_good_window(self, state: StageState, now: float) -> float:
        # Walk history backwards. Stop at the first bad observation.
        # Window length = now - first_good_obs_after_last_bad.
        if not state.history:
            return 0.0
        oldest_good_after_bad: float | None = None
        for obs in reversed(state.history):
            if obs.classification in BAD_STEADY_STATES:
                break
            if obs.classification == Classification.SILENT:
                # Silence-without-livestream is treated as good upstream;
                # this method is only consulted when bad_since is set,
                # which only happens for genuine bad states, so silence
                # entries here are fine.
                pass
            oldest_good_after_bad = obs.captured_at
        if oldest_good_after_bad is None:
            return 0.0
        return max(0.0, now - oldest_good_after_bad)

    def _snapshot_upstream(
        self,
        focal_stage: str,
    ) -> tuple[tuple[str, Classification], ...]:
        """Capture each non-focal stage's most-recent classification."""
        snapshot: list[tuple[str, Classification]] = []
        for name, state in self._stages.items():
            if name == focal_stage:
                continue
            if not state.history:
                continue
            snapshot.append((name, state.history[-1].classification))
        return tuple(snapshot)


def now_seconds() -> float:
    """Indirection for tests — production callers can use this directly."""
    return time.time()


__all__ = [
    "DEFAULT_CLIPPING_SUSTAIN_S",
    "DEFAULT_NOISE_SUSTAIN_S",
    "DEFAULT_RECOVERY_SUSTAIN_S",
    "DEFAULT_SILENCE_SUSTAIN_S",
    "StageObservation",
    "StageState",
    "TransitionDetector",
    "TransitionEvent",
    "now_seconds",
]
