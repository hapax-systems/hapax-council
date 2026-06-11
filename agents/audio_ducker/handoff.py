"""Duck-handoff composition — dB-domain compose + release hysteresis.

cc-task voice-p2-duck-handoff-20260610 (CASE-VOICE-FOUNDATION-20260610).
Interview-bar criterion: "no pumping under rapid turn alternation —
dB-domain compose, hysteresis, pre-wet sidechain, fail-open-to-unity"
(rebuild design §ducking; v2 execution spec §0.2).

This module is the Phase 1 call-site landing of
``shared/audio_duck_compose`` (whose docstring pinned "No call-site
swap; that's Phase 1") plus the duck-layer anti-pump state the swap
needs to be listenable under rapid operator↔TTS alternation:

- ``compose_duck_target_db`` — genuinely concurrent (hot) triggers SUM
  in dB via ``compose_attenuations`` (clamped MAX_TOTAL_ATTEN_DB); a
  trigger latched only by hysteresis/hold-open (a handoff tail or a
  syllable gap) sustains its OWN depth without stacking onto the next
  speaker. Without the hot/latched distinction, naive dB-summing dips
  the bed (tail depth + fresh-speaker depth) at every handoff — the
  downward pumping mode.
- ``HandoffHold`` — release hysteresis on the composed value: deepening
  is always immediate (speech-onset protection); a rise toward unity
  holds the deeper value for DUCK_HANDOFF_HOLD_MS so inter-turn gaps
  never release the bed — the upward pumping mode. ``reset()`` is the
  fail-open hook: a blocker forces unity instantly, never waits out a
  hold window.

Pure logic only — no PipeWire, no subprocess, no clock reads. The
daemon (``__main__.py``) owns the envelopes, the tick loop, and the
gain writes; the scripted rapid-alternation receipt
(``tests/agents/audio_ducker/test_duck_handoff_pumping.py``) drives
this chain deterministically.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from shared.audio_duck_compose import MAX_TOTAL_ATTEN_DB, compose_attenuations
from shared.audio_loudness import (
    DUCK_DEPTH_OPERATOR_VOICE_DB,
    DUCK_DEPTH_TTS_DB,
    DUCK_HANDOFF_HOLD_MS,
)


@dataclass(frozen=True)
class DuckTrigger:
    """One sidechain trigger's contribution to the music-bed duck.

    ``active`` is the hysteresis-latched VAD state (including hold-open);
    ``hot`` is the instantaneous view — at/above the release threshold
    right now. Hysteresis decides WHETHER a trigger ducks; hotness only
    decides whether concurrent triggers STACK (sum in dB) or merely
    sustain (deepest single depth).
    """

    name: str
    depth_db: float
    active: bool
    hot: bool


def compose_duck_target_db(
    triggers: Iterable[DuckTrigger],
    *,
    max_db: float = MAX_TOTAL_ATTEN_DB,
) -> float:
    """Compose the music-bed duck target in dB (0.0 or negative).

    Genuine concurrency (all hot) sums attenuations in dB; latched-only
    triggers (handoff tails, syllable gaps) sustain the deepest single
    active depth without stacking. The deeper of the two views wins, so
    a sustained duck can never be released by the other view going
    quiet, and a phantom overlap can never dip below the deepest single
    engaged depth.
    """
    active = [t for t in triggers if t.active]
    hot_sum = compose_attenuations((t.depth_db for t in active if t.hot), max_db=max_db)
    latched_floor = min((t.depth_db for t in active), default=0.0)
    return max(min(hot_sum, latched_floor), max_db)


def music_duck_triggers(
    rode_active: bool,
    rode_hot: bool,
    tts_active: bool,
    tts_hot: bool,
    *,
    segment_active: bool,
    allow_tts_into_broadcast: bool,
) -> tuple[DuckTrigger, ...]:
    """Build the music-bed trigger set from envelope/subscription states.

    Mirrors the legacy ``compute_targets`` semantics exactly:

    - operator voice (pre-wet Rode) always engages at its depth — the
      operator IS the broadcast voice and is never fortress-gated;
    - TTS-on-broadcast and a live hosting segment are ONE trigger (the
      TTS content class, same depth — no-presets rule): the chain RMS
      envelope and the producer file subscription are two WITNESSES of
      the same spoken content, never two stacking sources — composing
      them would double-duck a single voice. Both ride the
      ``duck_role_assistant_into_broadcast`` working-mode coupling. The
      segment subscription is producer-driven file freshness, not an RMS
      envelope, so it counts as hot whenever engaged.
    """
    triggers = [
        DuckTrigger(
            name="rode",
            depth_db=DUCK_DEPTH_OPERATOR_VOICE_DB,
            active=rode_active,
            hot=rode_hot,
        )
    ]
    if allow_tts_into_broadcast:
        triggers.append(
            DuckTrigger(
                name="tts_class",
                depth_db=DUCK_DEPTH_TTS_DB,
                active=tts_active or segment_active,
                hot=tts_hot or segment_active,
            )
        )
    return tuple(triggers)


@dataclass
class HandoffHold:
    """Release hysteresis on the composed duck target (anti-pump).

    Deepening (more negative) is followed immediately. A rise toward
    unity returns the held deeper value until ``hold_ms`` has elapsed
    since the LAST tick at that depth (or deeper); then the shallower
    composed value is followed and the release ramp takes over.

    ``reset()`` drops the hold state for the fail-open path: when the
    daemon loses a capture source or a gain write, the bed must go to
    unity NOW, not after a hold window.
    """

    hold_ms: float = DUCK_HANDOFF_HOLD_MS
    held_db: float = 0.0
    last_at_depth_ms: float | None = None
    is_holding: bool = False

    def apply(self, composed_db: float, now_ms: float) -> float:
        if composed_db <= self.held_db:
            # At depth or deepening — follow immediately, refresh window.
            self.held_db = composed_db
            self.last_at_depth_ms = now_ms
            self.is_holding = False
            return composed_db
        if self.last_at_depth_ms is not None and (now_ms - self.last_at_depth_ms) <= self.hold_ms:
            self.is_holding = True
            return self.held_db
        self.held_db = composed_db
        self.last_at_depth_ms = now_ms
        self.is_holding = False
        return composed_db

    def reset(self) -> None:
        self.held_db = 0.0
        self.last_at_depth_ms = None
        self.is_holding = False
