"""Epic 2 music directives — vinyl decoupling, curated-playlist pin, half-speed.

Operator directives 2026-04-17:
  1. Music featuring must work regardless of whether vinyl is playing.
  2. All music sources must come from Oudepode's curated taste (the
     hardcoded YouTube playlist), not from algorithmic recommendations.
  3. YouTube playback must default to 1/2 speed for DMCA evasion.

Each test pins one invariant so a regression surfaces here rather than
weeks later on the livestream.

Phase 2 / 2b note (#1431, #1433): vinyl-spinning detection is now a
Bayesian posterior with slow-enter / fast-exit hysteresis (k_enter=6).
Tests that previously asserted single-tick Boolean truth now settle the
engine through enough ticks to cross the ASSERTED threshold. The
operator-directive invariants still hold — the *evidence shape* (cover
+ hand, or operator override) is unchanged.
"""

from __future__ import annotations

import json

import pytest

from agents.studio_compositor import director_loop

# k_enter=6 + a margin; covers the ASSERTED transition for both the
# vinyl and music engines under sustained positive evidence.
_SETTLE_TICKS = 10


@pytest.fixture(autouse=True)
def _reset_engine_singletons():
    """Each test gets a clean Bayesian engine so monkeypatched paths /
    callables actually take effect. Without this, the lazy singleton
    persists across tests with stale construction-time state."""
    director_loop._reset_engines_for_testing()
    yield
    director_loop._reset_engines_for_testing()


def _settle_vinyl_to_asserted() -> None:
    """Tick the vinyl engine through k_enter ticks to reach ASSERTED."""
    engine = director_loop._vinyl_engine()
    if engine is None:
        return
    for _ in range(_SETTLE_TICKS):
        engine.tick()


class TestVinylDecoupling:
    """Prompt framing must adapt to whether vinyl is actually playing.

    Task #185 (2026-04-20): ``_vinyl_is_playing`` now requires a
    second signal beyond cover-identification. Either:
      1. Operator override flag present, OR
      2. Cover identified AND recent hand-on-turntable activity.
    Cover alone is insufficient — the LLM's cover-ID confidence does
    not prove the platter is spinning.
    """

    def _set_override(self, tmp_path, monkeypatch, active: bool) -> None:
        """Redirect the operator-override flag to a tmp location."""
        flag = tmp_path / "vinyl-operator-active.flag"
        if active:
            flag.touch()
        monkeypatch.setattr(director_loop, "_VINYL_OPERATOR_OVERRIDE_FLAG", flag)

    def test_vinyl_not_playing_when_state_missing(self, tmp_path, monkeypatch):
        missing = tmp_path / "absent-album-state.json"
        monkeypatch.setattr(director_loop, "ALBUM_STATE_FILE", missing)
        self._set_override(tmp_path, monkeypatch, active=False)
        monkeypatch.setattr(director_loop, "_hand_on_turntable_recent", lambda: False)
        assert director_loop._vinyl_is_playing() is False

    def test_vinyl_not_playing_when_confidence_low(self, tmp_path, monkeypatch):
        state = tmp_path / "album-state.json"
        state.write_text(json.dumps({"artist": "X", "title": "Y", "confidence": 0.1}))
        monkeypatch.setattr(director_loop, "ALBUM_STATE_FILE", state)
        self._set_override(tmp_path, monkeypatch, active=False)
        monkeypatch.setattr(director_loop, "_hand_on_turntable_recent", lambda: True)
        assert director_loop._vinyl_is_playing() is False

    def test_vinyl_not_playing_when_state_stale(self, tmp_path, monkeypatch):
        state = tmp_path / "album-state.json"
        state.write_text(json.dumps({"artist": "X", "title": "Y", "confidence": 0.9}))
        import os

        old = state.stat().st_mtime - 600
        os.utime(state, (old, old))
        monkeypatch.setattr(director_loop, "ALBUM_STATE_FILE", state)
        self._set_override(tmp_path, monkeypatch, active=False)
        monkeypatch.setattr(director_loop, "_hand_on_turntable_recent", lambda: True)
        assert director_loop._vinyl_is_playing() is False

    def test_vinyl_NOT_playing_cover_alone_no_hand_activity(self, tmp_path, monkeypatch):
        """Task #185 regression: cover identified + fresh, but no hand-on-turntable.
        Prior implementation returned True; new impl returns False."""
        state = tmp_path / "album-state.json"
        state.write_text(json.dumps({"artist": "Bobby Konders", "title": "M1", "confidence": 0.9}))
        monkeypatch.setattr(director_loop, "ALBUM_STATE_FILE", state)
        self._set_override(tmp_path, monkeypatch, active=False)
        monkeypatch.setattr(director_loop, "_hand_on_turntable_recent", lambda: False)
        assert director_loop._vinyl_is_playing() is False

    def test_vinyl_playing_when_cover_AND_recent_hand_activity(self, tmp_path, monkeypatch):
        state = tmp_path / "album-state.json"
        state.write_text(
            json.dumps({"artist": "Bobby Konders", "title": "Massive Sounds", "confidence": 0.82})
        )
        monkeypatch.setattr(director_loop, "ALBUM_STATE_FILE", state)
        self._set_override(tmp_path, monkeypatch, active=False)
        monkeypatch.setattr(director_loop, "_hand_on_turntable_recent", lambda: True)
        monkeypatch.setattr(director_loop, "_vinyl_engine", lambda: None)
        assert director_loop._vinyl_is_playing() is True

    def test_vinyl_playing_via_operator_override_flag(self, tmp_path, monkeypatch):
        """Operator-override short-circuits — no cover, no hand activity needed."""
        missing = tmp_path / "absent-album-state.json"
        monkeypatch.setattr(director_loop, "ALBUM_STATE_FILE", missing)
        self._set_override(tmp_path, monkeypatch, active=True)
        monkeypatch.setattr(director_loop, "_hand_on_turntable_recent", lambda: False)
        monkeypatch.setattr(director_loop, "_vinyl_engine", lambda: None)
        assert director_loop._vinyl_is_playing() is True

    def test_framing_when_vinyl_playing(self, tmp_path, monkeypatch):
        # `playing: True` is required for `_read_album_info` to surface
        # the artist/title — without it the function returns "unknown
        # (no music playing)" per PR #1933's playing-flag guard. The
        # test scenario explicitly models a spinning record, so the
        # album-state must reflect that.
        state = tmp_path / "album-state.json"
        state.write_text(
            json.dumps(
                {
                    "artist": "Bobby Konders",
                    "title": "M1",
                    "confidence": 0.9,
                    "playing": True,
                }
            )
        )
        monkeypatch.setattr(director_loop, "ALBUM_STATE_FILE", state)
        self._set_override(tmp_path, monkeypatch, active=False)
        monkeypatch.setattr(director_loop, "_hand_on_turntable_recent", lambda: True)
        monkeypatch.setattr(director_loop, "_vinyl_engine", lambda: None)
        framing = director_loop._curated_music_framing("yt-title", "yt-channel", "Oudepode")
        assert "spinning vinyl" in framing
        assert "Bobby Konders" in framing
        assert "Oudepode" in framing

    def test_framing_when_no_vinyl_but_youtube_slot_active(self, tmp_path, monkeypatch):
        missing = tmp_path / "absent-album-state.json"
        monkeypatch.setattr(director_loop, "ALBUM_STATE_FILE", missing)
        monkeypatch.setattr(director_loop, "_vinyl_engine", lambda: None)
        # Phase 2b: framing requires audio-evidence; mock PANNs ASSERTED.
        monkeypatch.setattr(director_loop, "_music_is_playing_in_broadcast", lambda: True)
        framing = director_loop._curated_music_framing("Some Track", "Some Channel", "OTO")
        assert "curated queue" in framing
        assert "Some Track" in framing
        assert "vinyl" not in framing.lower()
        assert "OTO" in framing

    def test_framing_when_no_music_at_all(self, tmp_path, monkeypatch):
        missing = tmp_path / "absent-album-state.json"
        monkeypatch.setattr(director_loop, "ALBUM_STATE_FILE", missing)
        framing = director_loop._curated_music_framing("", "", "The Operator")
        assert "No music" in framing

    def test_framing_accepts_each_of_the_four_referents(self, tmp_path, monkeypatch):
        """su-non-formal-referent-001: all four ratified referents must
        flow through _curated_music_framing without error."""
        state = tmp_path / "album-state.json"
        state.write_text(json.dumps({"artist": "A", "title": "T", "confidence": 0.9}))
        monkeypatch.setattr(director_loop, "ALBUM_STATE_FILE", state)
        self._set_override(tmp_path, monkeypatch, active=False)
        monkeypatch.setattr(director_loop, "_hand_on_turntable_recent", lambda: True)
        monkeypatch.setattr(director_loop, "_vinyl_engine", lambda: None)
        for referent in ("The Operator", "Oudepode", "Oudepode The Operator", "OTO"):
            framing = director_loop._curated_music_framing("yt-t", "yt-c", referent)
            assert referent in framing


class TestOperatorTaste:
    """The director must pull music only from Oudepode's curated playlist."""

    def test_curated_playlist_constant_points_at_operator_list(self):
        assert "PL-4nvD1KwuH--sViEAFY2cHVmS6_B4CQ5" in director_loop.PLAYLIST_URL

    def test_curated_playlist_tuple_is_single_sourced(self):
        assert director_loop.OPERATOR_CURATED_PLAYLIST_URLS == (director_loop.PLAYLIST_URL,)

    def test_no_external_playlist_extension(self):
        """No non-PLAYLIST_URL YouTube playlist URL should appear in the module."""
        import inspect

        source = inspect.getsource(director_loop)
        # Permit exactly one playlist literal.
        import re

        matches = re.findall(r"list=[A-Za-z0-9_-]{20,}", source)
        assert matches, "expected at least one YouTube playlist reference"
        distinct = set(matches)
        assert distinct == {"list=PL-4nvD1KwuH--sViEAFY2cHVmS6_B4CQ5"}, (
            f"found non-curated playlist(s) in director_loop: {distinct}"
        )


class TestPlaybackRate:
    """HAPAX_YOUTUBE_PLAYBACK_RATE controls the ffmpeg tempo filter."""

    def _load_playback_rate(self):
        import importlib.util
        from pathlib import Path

        path = Path(__file__).resolve().parents[2] / "scripts" / "youtube-player.py"
        spec = importlib.util.spec_from_file_location("youtube_player_under_test", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module._playback_rate

    def test_default_is_half_speed(self, monkeypatch):
        monkeypatch.delenv("HAPAX_YOUTUBE_PLAYBACK_RATE", raising=False)
        rate = self._load_playback_rate()
        assert rate() == 0.5

    def test_override_accepted(self, monkeypatch):
        monkeypatch.setenv("HAPAX_YOUTUBE_PLAYBACK_RATE", "1.0")
        rate = self._load_playback_rate()
        assert rate() == 1.0

    def test_clamp_low(self, monkeypatch):
        monkeypatch.setenv("HAPAX_YOUTUBE_PLAYBACK_RATE", "0.01")
        rate = self._load_playback_rate()
        assert rate() == 0.25

    def test_clamp_high(self, monkeypatch):
        monkeypatch.setenv("HAPAX_YOUTUBE_PLAYBACK_RATE", "10")
        rate = self._load_playback_rate()
        assert rate() == 2.0

    def test_invalid_falls_back_to_half_speed(self, monkeypatch):
        monkeypatch.setenv("HAPAX_YOUTUBE_PLAYBACK_RATE", "not-a-number")
        rate = self._load_playback_rate()
        assert rate() == 0.5


class TestActivityVocabulary:
    """``music`` is an accepted director-intent activity alongside ``vinyl``."""

    def test_music_in_activity_vocabulary(self):
        from typing import get_args

        from shared.director_intent import ActivityVocabulary

        activities = get_args(ActivityVocabulary)
        assert "music" in activities
        # vinyl retained for back-compat so prior intents parse.
        assert "vinyl" in activities

    def test_music_in_candidate_activities(self):
        from agents.studio_compositor.activity_scoring import CANDIDATE_ACTIVITIES

        assert "music" in CANDIDATE_ACTIVITIES

    def test_music_activity_constructs_director_intent(self):
        from shared.director_intent import CompositionalImpingement, DirectorIntent
        from shared.stimmung import Stance

        intent = DirectorIntent(
            activity="music",
            stance=Stance.NOMINAL,
            narrative_text="",
            compositional_impingements=[
                CompositionalImpingement(
                    narrative="music-led surface hold", intent_family="preset.bias"
                )
            ],
        )
        assert intent.activity == "music"
