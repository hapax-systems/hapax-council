"""Tests for the backing-mix bidirectional audio-ducking controller (CVS #145)."""

from __future__ import annotations

import json
from unittest.mock import patch

from agents.studio_compositor import audio_ducking
from agents.studio_compositor.audio_ducking import (
    AudioDuckingController,
    DuckingState,
    _compute_state,
    read_yt_audio_active,
    set_yt_audio_active,
)


class _MutableSignal:
    """Trivial mutable-bool holder for injected state readers."""

    def __init__(self, initial: bool | None = False) -> None:
        self.value: bool | None = initial

    def __call__(self) -> bool | None:
        return self.value


class TestComputeState:
    def test_neither_is_normal(self) -> None:
        assert _compute_state(False, False) is DuckingState.NORMAL

    def test_voice_only(self) -> None:
        assert _compute_state(True, False) is DuckingState.VOICE_ACTIVE

    def test_yt_only(self) -> None:
        assert _compute_state(False, True) is DuckingState.YT_ACTIVE

    def test_both_voice_wins_priority(self) -> None:
        # Both active → BOTH_ACTIVE (not VOICE_ACTIVE) so dispatcher can
        # drive the -18 dB deeper-duck target.
        assert _compute_state(True, True) is DuckingState.BOTH_ACTIVE


class TestStateReaders:
    def test_set_and_read_yt_state(self, tmp_path) -> None:
        target = tmp_path / "yt-audio-state.json"
        with patch.object(audio_ducking, "YT_AUDIO_STATE_FILE", target):
            set_yt_audio_active(True)
            assert target.exists()
            payload = json.loads(target.read_text())
            assert payload["yt_audio_active"] is True
            assert read_yt_audio_active() is True

            set_yt_audio_active(False)
            assert read_yt_audio_active() is False

    def test_read_returns_none_when_missing(self, tmp_path) -> None:
        target = tmp_path / "missing.json"
        assert read_yt_audio_active(target) is None

    def test_read_returns_none_on_malformed(self, tmp_path) -> None:
        target = tmp_path / "bad.json"
        target.write_text("not json")
        assert read_yt_audio_active(target) is None


def _make_controller(
    vad_signal: _MutableSignal,
    yt_signal: _MutableSignal,
    dispatched: list[tuple[str, float]],
    *,
    feature_flag: bool = True,
    vad_debounce_s: float = 2.0,
    yt_debounce_s: float = 0.5,
) -> AudioDuckingController:
    return AudioDuckingController(
        vad_state_reader=vad_signal,
        yt_state_reader=yt_signal,
        gain_dispatcher=lambda sink, gain: dispatched.append((sink, gain)),
        poll_interval_s=0.001,
        vad_debounce_s=vad_debounce_s,
        yt_debounce_s=yt_debounce_s,
        feature_flag_reader=lambda: feature_flag,
    )


class TestStateMachine:
    def test_normal_to_voice_active(self) -> None:
        vad = _MutableSignal(False)
        yt = _MutableSignal(False)
        dispatched: list[tuple[str, float]] = []
        c = _make_controller(vad, yt, dispatched)

        # Initial tick at t=10 with everything quiet → NORMAL (already
        # the init state, no transition).
        assert c.tick(now=10.0) is DuckingState.NORMAL
        assert dispatched == []

        # Voice goes active at t=11 → VOICE_ACTIVE.
        vad.value = True
        assert c.tick(now=11.0) is DuckingState.VOICE_ACTIVE
        # Dispatched ducks YT and keeps backing open.
        sinks = {sink for sink, _ in dispatched}
        assert "hapax-ytube-ducked" in sinks
        assert "hapax-backing-ducked" in sinks

    def test_voice_active_back_to_normal_after_debounce(self) -> None:
        vad = _MutableSignal(True)
        yt = _MutableSignal(False)
        dispatched: list[tuple[str, float]] = []
        c = _make_controller(vad, yt, dispatched, vad_debounce_s=2.0)

        c.tick(now=10.0)
        assert c.state is DuckingState.VOICE_ACTIVE

        # Voice drops — inside debounce window, still VOICE_ACTIVE.
        vad.value = False
        c.tick(now=10.5)
        assert c.state is DuckingState.VOICE_ACTIVE

        # Outside debounce window → back to NORMAL.
        c.tick(now=13.0)
        assert c.state is DuckingState.NORMAL

    def test_simultaneous_vad_and_yt_is_both_active(self) -> None:
        vad = _MutableSignal(True)
        yt = _MutableSignal(True)
        dispatched: list[tuple[str, float]] = []
        c = _make_controller(vad, yt, dispatched)
        assert c.tick(now=10.0) is DuckingState.BOTH_ACTIVE

        # YT bed should be ducked deeper (-18 dB) than voice-only case.
        gains_by_sink = {sink: gain for sink, gain in dispatched}
        # -18 dB ≈ 0.126 linear
        assert gains_by_sink["hapax-ytube-ducked"] < 0.15
        # Backing stays open under voice priority.
        assert gains_by_sink["hapax-backing-ducked"] >= 0.99

    def test_yt_only_ducks_backing(self) -> None:
        vad = _MutableSignal(False)
        yt = _MutableSignal(True)
        dispatched: list[tuple[str, float]] = []
        c = _make_controller(vad, yt, dispatched)
        assert c.tick(now=10.0) is DuckingState.YT_ACTIVE

        gains_by_sink = {sink: gain for sink, gain in dispatched}
        # -6 dB ≈ 0.501 linear for backing.
        assert 0.45 < gains_by_sink["hapax-backing-ducked"] < 0.55
        # YT bed itself stays open.
        assert gains_by_sink["hapax-ytube-ducked"] >= 0.99

    def test_vad_debounce_does_not_flip_state(self) -> None:
        """Brief VAD drops (<debounce) should not flip out of VOICE_ACTIVE."""
        vad = _MutableSignal(True)
        yt = _MutableSignal(False)
        dispatched: list[tuple[str, float]] = []
        c = _make_controller(vad, yt, dispatched, vad_debounce_s=2.0)

        c.tick(now=10.0)
        assert c.state is DuckingState.VOICE_ACTIVE

        # Two successive "silent" ticks within 2 s — no transition.
        vad.value = False
        c.tick(now=10.5)
        c.tick(now=11.5)
        assert c.state is DuckingState.VOICE_ACTIVE

        # Capture the dispatch count after debounce starts; no new
        # dispatch should have happened during the debounce window.
        initial_count = len(dispatched)
        c.tick(now=11.9)
        assert len(dispatched) == initial_count


class TestFeatureFlag:
    def test_flag_off_does_not_dispatch(self) -> None:
        vad = _MutableSignal(True)
        yt = _MutableSignal(False)
        dispatched: list[tuple[str, float]] = []
        c = _make_controller(vad, yt, dispatched, feature_flag=False)

        # State still transitions (observable via state property), but
        # no dispatch to PipeWire.
        assert c.tick(now=10.0) is DuckingState.VOICE_ACTIVE
        assert dispatched == []

    def test_flag_on_dispatches(self) -> None:
        vad = _MutableSignal(True)
        yt = _MutableSignal(False)
        dispatched: list[tuple[str, float]] = []
        c = _make_controller(vad, yt, dispatched, feature_flag=True)

        c.tick(now=10.0)
        assert dispatched != []


class TestEnvironmentFlag:
    def test_env_var_false_default(self, monkeypatch) -> None:
        monkeypatch.delenv(audio_ducking.FEATURE_FLAG_ENV, raising=False)
        assert audio_ducking._read_feature_flag() is False

    def test_env_var_accepts_truthy(self, monkeypatch) -> None:
        for val in ("1", "true", "yes", "on"):
            monkeypatch.setenv(audio_ducking.FEATURE_FLAG_ENV, val)
            assert audio_ducking._read_feature_flag() is True

    def test_env_var_falsy_values(self, monkeypatch) -> None:
        for val in ("0", "false", "no", "off", ""):
            monkeypatch.setenv(audio_ducking.FEATURE_FLAG_ENV, val)
            assert audio_ducking._read_feature_flag() is False
