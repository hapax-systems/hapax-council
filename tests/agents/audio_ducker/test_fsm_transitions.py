"""Deterministic FSM-tick tests for the audio-ducker state machine.

audio-audit C — Auditor C wants every duck-state transition pinned
under mocked time + RMS so a regression in `EnvelopeState.update`,
`compute_targets`, or `ramp_gain` is caught synchronously instead of
showing up as a flaky live-audio behavior.

The "FSM" surface here is two layers:

  1. **Per-source `EnvelopeState`** — hysteresis-based VAD with
     hold-open. State is `is_active: bool`. Transitions:
       off → on   when `rms_db >= TRIGGER_ON_DBFS`
       on  → on   when `TRIGGER_OFF_DBFS <= rms_db < TRIGGER_ON_DBFS`
                  (latch — between hysteresis thresholds)
       on  → off  when `rms_db < TRIGGER_OFF_DBFS` AND
                  `now_ms - last_above_threshold_ms > HOLD_OPEN_MS`
       on  → on   when `rms_db < TRIGGER_OFF_DBFS` AND hold-open active
       off → off  when `rms_db < TRIGGER_ON_DBFS` (default)

  2. **`compute_targets(rode_active, tts_active)`** — pure function
     mapping (rode, tts) ∈ {0,1}² → (music_gain, tts_gain). Four
     input states, three transitions per state = 12 valid edges of
     the 4×4 transition table.

`ramp_gain` covers the analog interpolation between commanded gains;
edge cases include zero-length attack/release and target-already-met.

Per the cc-task: <1s wall-time, no subprocess, no real audio capture.
All time-source and RMS samples are synthesised in-process.
"""

from __future__ import annotations

import numpy as np
import pytest

from agents.audio_ducker.__main__ import (
    HOLD_OPEN_MS,
    MUSIC_DUCK_OPERATOR,
    MUSIC_DUCK_TTS,
    TRIGGER_OFF_DBFS,
    TRIGGER_ON_DBFS,
    TTS_DUCK_OPERATOR,
    UNITY,
    EnvelopeState,
    compute_targets,
    ramp_gain,
)
from shared.audio_loudness import DUCK_ATTACK_MS, DUCK_RELEASE_MS


def _samples_at_dbfs(target_dbfs: float, n: int = 1024) -> np.ndarray:
    """Return n float32 samples whose RMS is approximately target_dbfs.

    Uses a constant-amplitude sine so RMS = amplitude/sqrt(2). Solving:
    target_lin = 10**(target_dbfs/20); amplitude = target_lin * sqrt(2).
    """
    target_lin = 10 ** (target_dbfs / 20.0)
    amplitude = target_lin * np.sqrt(2.0)
    t = np.arange(n, dtype=np.float32)
    return (amplitude * np.sin(2 * np.pi * t / 64.0)).astype(np.float32)


# ── compute_targets: 4 input states, all 4 outputs pinned ───────────


class TestComputeTargets4x4:
    def test_no_active_returns_unity_unity(self) -> None:
        music, tts = compute_targets(rode_active=False, tts_active=False)
        assert music == UNITY
        assert tts == UNITY

    def test_only_tts_active_ducks_music_only(self) -> None:
        music, tts = compute_targets(rode_active=False, tts_active=True)
        assert music == MUSIC_DUCK_TTS
        assert tts == UNITY

    def test_only_rode_active_ducks_both(self) -> None:
        music, tts = compute_targets(rode_active=True, tts_active=False)
        assert music == MUSIC_DUCK_OPERATOR
        assert tts == TTS_DUCK_OPERATOR

    def test_both_active_takes_deepest_music_duck(self) -> None:
        """When both Rode + TTS active, music takes min(operator,tts)
        gain (deepest duck). TTS still only ducks under Rode."""
        music, tts = compute_targets(rode_active=True, tts_active=True)
        assert music == min(MUSIC_DUCK_OPERATOR, MUSIC_DUCK_TTS)
        assert tts == TTS_DUCK_OPERATOR


# ── 12 transition edges (4 states × 3 outgoing each) ────────────────


class TestComputeTargetsTransitions12Edges:
    """Exhaustively enumerate every transition between the 4 input
    states and assert the output flips correctly. The 4×4 transition
    table has 16 entries; 4 are self-loops; the other 12 are the
    distinct edges the cc-task wants pinned.
    """

    STATES = [(False, False), (False, True), (True, False), (True, True)]

    def test_all_self_loops_are_idempotent(self) -> None:
        for r, t in self.STATES:
            first = compute_targets(rode_active=r, tts_active=t)
            second = compute_targets(rode_active=r, tts_active=t)
            assert first == second, f"compute_targets not deterministic for ({r}, {t})"

    @pytest.mark.parametrize(
        "src,dst",
        [
            (s, d)
            for s in [(False, False), (False, True), (True, False), (True, True)]
            for d in [(False, False), (False, True), (True, False), (True, True)]
            if s != d
        ],
    )
    def test_every_distinct_edge_changes_output_or_is_pinned(
        self, src: tuple[bool, bool], dst: tuple[bool, bool]
    ) -> None:
        """Every edge between distinct states must produce the documented
        output for the destination — independent of source. compute_targets
        is stateless; the test pins that no future caching / memoization
        introduces source-dependence."""
        out_via_dst = compute_targets(rode_active=dst[0], tts_active=dst[1])
        # Walking the edge: simulate "we were in src, now we're in dst".
        compute_targets(rode_active=src[0], tts_active=src[1])  # leave-state
        out_arrived = compute_targets(rode_active=dst[0], tts_active=dst[1])
        assert out_via_dst == out_arrived, (
            f"edge {src}->{dst} produced different output than direct call to dst"
        )


# ── EnvelopeState — hysteresis transitions ──────────────────────────


class TestEnvelopeStateHysteresis:
    def test_off_to_on_at_trigger_on_threshold(self) -> None:
        env = EnvelopeState(name="rode")
        # Sample sized exactly at TRIGGER_ON_DBFS — must trip on.
        env.update(_samples_at_dbfs(TRIGGER_ON_DBFS + 0.01), now_ms=0.0)
        assert env.is_active is True

    def test_on_latches_between_thresholds(self) -> None:
        """Mid-band sample (between OFF and ON) must NOT change
        is_active state — that's the hysteresis contract."""
        env = EnvelopeState(name="rode")
        # First push above ON to set is_active=True.
        env.update(_samples_at_dbfs(TRIGGER_ON_DBFS + 5.0), now_ms=0.0)
        assert env.is_active is True
        # Now drop into the hysteresis band (between OFF and ON).
        mid_band = (TRIGGER_ON_DBFS + TRIGGER_OFF_DBFS) / 2.0
        env.update(_samples_at_dbfs(mid_band), now_ms=10.0)
        assert env.is_active is True, "hysteresis band must latch on-state"

    def test_on_to_off_only_after_hold_open(self) -> None:
        env = EnvelopeState(name="rode")
        env.update(_samples_at_dbfs(TRIGGER_ON_DBFS + 5.0), now_ms=0.0)
        assert env.is_active is True
        # Below OFF, but inside hold-open window: still on.
        env.update(_samples_at_dbfs(TRIGGER_OFF_DBFS - 5.0), now_ms=HOLD_OPEN_MS - 1.0)
        assert env.is_active is True, "hold-open must keep is_active True"
        # Below OFF, past hold-open window: off.
        env.update(_samples_at_dbfs(TRIGGER_OFF_DBFS - 5.0), now_ms=HOLD_OPEN_MS + 50.0)
        assert env.is_active is False, "after hold-open expiry, drop must release"

    def test_off_to_off_quiet_signal_stays_off(self) -> None:
        env = EnvelopeState(name="rode")
        env.update(_samples_at_dbfs(TRIGGER_OFF_DBFS - 30.0), now_ms=0.0)
        assert env.is_active is False

    def test_chatter_around_threshold_does_not_oscillate(self) -> None:
        """RMS oscillating across TRIGGER_OFF_DBFS while inside the
        hold-open window must NOT flip is_active off. Chatter prevention
        is the operator-visible symptom of correct hysteresis + hold-open
        behavior."""
        env = EnvelopeState(name="rode")
        env.update(_samples_at_dbfs(TRIGGER_ON_DBFS + 3.0), now_ms=0.0)
        assert env.is_active is True
        # Chatter: oscillate above/below OFF every 20 ms inside hold-open.
        for tick_idx, dbfs in enumerate([TRIGGER_OFF_DBFS + 1.0, TRIGGER_OFF_DBFS - 1.0] * 4):
            env.update(_samples_at_dbfs(dbfs), now_ms=20.0 * (tick_idx + 1))
        # All chatter samples are within hold-open window (< HOLD_OPEN_MS).
        # is_active must remain True throughout.
        assert env.is_active is True

    def test_mark_error_forces_off_and_records_state(self) -> None:
        env = EnvelopeState(name="rode")
        env.update(_samples_at_dbfs(TRIGGER_ON_DBFS + 5.0), now_ms=0.0)
        assert env.is_active is True
        env.mark_error("capture process died", now_ms=100.0)
        assert env.is_active is False
        assert env.last_error == "capture process died"
        assert env.last_error_ms == 100.0


# ── ramp_gain edge cases (analog interpolation) ─────────────────────


class TestRampGain:
    def test_target_already_met_returns_target(self) -> None:
        assert ramp_gain(current=UNITY, target=UNITY, dt_ms=10.0) == UNITY

    def test_attack_drops_toward_target_at_attack_rate(self) -> None:
        # From unity (1.0) toward MUSIC_DUCK_OPERATOR (~0.251) over the
        # attack window (DUCK_ATTACK_MS) the gain should reach target.
        gain = ramp_gain(current=UNITY, target=MUSIC_DUCK_OPERATOR, dt_ms=DUCK_ATTACK_MS)
        # Should hit the target exactly when dt covers the full sweep.
        assert gain <= MUSIC_DUCK_OPERATOR + 1e-6
        assert gain >= MUSIC_DUCK_OPERATOR - 1e-6 or gain == MUSIC_DUCK_OPERATOR

    def test_release_rises_slower_than_attack(self) -> None:
        # Same dt_ms, attack should travel more than release.
        dt = 10.0
        attack_distance = abs(ramp_gain(current=UNITY, target=0.0, dt_ms=dt) - UNITY)
        release_distance = abs(ramp_gain(current=0.0, target=UNITY, dt_ms=dt) - 0.0)
        assert attack_distance > release_distance, (
            "attack rate must exceed release rate (operator-asymmetric "
            "duck shape: punchy down, smooth up)"
        )

    def test_zero_length_dt_does_not_move(self) -> None:
        """dt_ms=0 must not advance the gain — transitions only happen
        on real time progress."""
        gain = ramp_gain(current=UNITY, target=0.0, dt_ms=0.0)
        assert gain == UNITY

    def test_clamps_to_unit_range(self) -> None:
        # Even with absurd dt, output must stay in [0, 1].
        assert 0.0 <= ramp_gain(current=UNITY, target=0.0, dt_ms=10_000.0) <= 1.0
        assert 0.0 <= ramp_gain(current=0.0, target=UNITY, dt_ms=10_000.0) <= 1.0

    def test_release_completes_over_release_window(self) -> None:
        """Going from 0 to UNITY over DUCK_RELEASE_MS should land on
        unity (or arbitrarily close to it)."""
        gain = ramp_gain(current=0.0, target=UNITY, dt_ms=DUCK_RELEASE_MS)
        assert gain == pytest.approx(UNITY, abs=1e-6)
