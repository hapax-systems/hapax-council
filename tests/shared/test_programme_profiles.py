"""Tests for programme runtime profiles."""

from __future__ import annotations

import json
from pathlib import Path

from shared.programme_profiles import (
    _load_profile_from_file,
    get_programme_profile,
)


class TestLoadProfileFromFile:
    def test_loads_interview_profile(self, tmp_path: Path) -> None:
        profile_data = {
            "programme_role": "interview",
            "target_duration_s": 3600,
            "wind_down_at_s": 3000,
            "reverie": {"intensity": "subdued", "drift_gain": 0.2},
            "audio": {"music_bed_gain_db": -30, "speech_priority": "maximum"},
            "compositor": {"layout_mode": "interview", "wards": ["question_card"]},
            "conversation": {"max_turns": 120, "silence_timeout_s": 180},
        }
        f = tmp_path / "programme-interview-profile.json"
        f.write_text(json.dumps(profile_data))

        profile = _load_profile_from_file(f)
        assert profile is not None
        assert profile.programme_role == "interview"
        assert profile.target_duration_s == 3600
        assert profile.wind_down_at_s == 3000
        assert profile.reverie.intensity == "subdued"
        assert profile.reverie.drift_gain == 0.2
        assert profile.audio.music_bed_gain_db == -30
        assert profile.audio.speech_priority == "maximum"
        assert profile.compositor.layout_mode == "interview"
        assert "question_card" in profile.compositor.wards
        assert profile.conversation.max_turns == 120
        assert profile.conversation.silence_timeout_s == 180

    def test_returns_none_on_missing_file(self, tmp_path: Path) -> None:
        assert _load_profile_from_file(tmp_path / "nope.json") is None

    def test_returns_none_on_invalid_json(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.json"
        f.write_text("not json {{{")
        assert _load_profile_from_file(f) is None


class TestGetProgrammeProfile:
    def test_loads_real_interview_config(self) -> None:
        profile = get_programme_profile("interview")
        assert profile is not None
        assert profile.programme_role == "interview"
        assert profile.conversation.max_turns == 120
        assert profile.conversation.silence_timeout_s == 180
        assert profile.reverie.intensity == "subdued"
        assert profile.audio.speech_priority == "maximum"

    def test_returns_none_for_unknown_role(self) -> None:
        assert get_programme_profile("nonexistent_role_xyz") is None

    def test_caches_result(self) -> None:
        from shared.programme_profiles import _CACHE

        _CACHE.pop("interview", None)
        p1 = get_programme_profile("interview")
        p2 = get_programme_profile("interview")
        assert p1 is p2
