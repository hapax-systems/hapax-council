"""Epic 2 music directives — vinyl decoupling, curated-playlist pin, half-speed.

Operator directives 2026-04-17:
  1. Music featuring must work regardless of whether vinyl is playing.
  2. All music sources must come from Oudepode's curated taste (the
     hardcoded YouTube playlist), not from algorithmic recommendations.
  3. YouTube playback must default to 1/2 speed for DMCA evasion.

Each test pins one invariant so a regression surfaces here rather than
weeks later on the livestream.
"""

from __future__ import annotations

import json

from agents.studio_compositor import director_loop


class TestVinylDecoupling:
    """Prompt framing must adapt to whether vinyl is actually playing."""

    def test_vinyl_not_playing_when_state_missing(self, tmp_path, monkeypatch):
        missing = tmp_path / "absent-album-state.json"
        monkeypatch.setattr(director_loop, "ALBUM_STATE_FILE", missing)
        assert director_loop._vinyl_is_playing() is False

    def test_vinyl_not_playing_when_confidence_low(self, tmp_path, monkeypatch):
        state = tmp_path / "album-state.json"
        state.write_text(json.dumps({"artist": "X", "title": "Y", "confidence": 0.1}))
        monkeypatch.setattr(director_loop, "ALBUM_STATE_FILE", state)
        assert director_loop._vinyl_is_playing() is False

    def test_vinyl_not_playing_when_state_stale(self, tmp_path, monkeypatch):
        state = tmp_path / "album-state.json"
        state.write_text(json.dumps({"artist": "X", "title": "Y", "confidence": 0.9}))
        # Force mtime to 10 minutes ago — past the 5-min staleness cutoff.
        import os

        old = state.stat().st_mtime - 600
        os.utime(state, (old, old))
        monkeypatch.setattr(director_loop, "ALBUM_STATE_FILE", state)
        assert director_loop._vinyl_is_playing() is False

    def test_vinyl_playing_when_confident_and_fresh(self, tmp_path, monkeypatch):
        state = tmp_path / "album-state.json"
        state.write_text(
            json.dumps({"artist": "Bobby Konders", "title": "Massive Sounds", "confidence": 0.82})
        )
        monkeypatch.setattr(director_loop, "ALBUM_STATE_FILE", state)
        assert director_loop._vinyl_is_playing() is True

    def test_framing_when_vinyl_playing(self, tmp_path, monkeypatch):
        state = tmp_path / "album-state.json"
        state.write_text(json.dumps({"artist": "Bobby Konders", "title": "M1", "confidence": 0.9}))
        monkeypatch.setattr(director_loop, "ALBUM_STATE_FILE", state)
        framing = director_loop._curated_music_framing("yt-title", "yt-channel")
        assert "spinning vinyl" in framing
        assert "Bobby Konders" in framing

    def test_framing_when_no_vinyl_but_youtube_slot_active(self, tmp_path, monkeypatch):
        missing = tmp_path / "absent-album-state.json"
        monkeypatch.setattr(director_loop, "ALBUM_STATE_FILE", missing)
        framing = director_loop._curated_music_framing("Some Track", "Some Channel")
        assert "curated queue" in framing
        assert "Some Track" in framing
        assert "vinyl" not in framing.lower()

    def test_framing_when_no_music_at_all(self, tmp_path, monkeypatch):
        missing = tmp_path / "absent-album-state.json"
        monkeypatch.setattr(director_loop, "ALBUM_STATE_FILE", missing)
        framing = director_loop._curated_music_framing("", "")
        assert "No music" in framing


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
        from shared.director_intent import DirectorIntent
        from shared.stimmung import Stance

        intent = DirectorIntent(activity="music", stance=Stance.NOMINAL, narrative_text="")
        assert intent.activity == "music"
