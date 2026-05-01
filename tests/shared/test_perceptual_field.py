"""Phase-2 PerceptualField reader tests."""

from __future__ import annotations

import json

import pytest

import shared.perceptual_field as pf
from shared.perceptual_field import PerceptualField, build_perceptual_field
from shared.stimmung import Stance


class TestEmptyState:
    def test_empty_state_gives_mostly_none(self, monkeypatch, tmp_path):
        _redirect_paths_to_empty(monkeypatch, tmp_path)
        field = build_perceptual_field()
        assert field.audio.contact_mic.desk_activity is None
        assert field.visual.detected_action is None
        assert field.ir.ir_heart_rate_bpm is None
        assert field.album.artist is None
        assert field.chat.recent_message_count == 0
        assert field.stimmung.overall_stance is None
        assert field.presence.state is None
        assert field.context.stream_live is False


class TestFullState:
    def test_full_state_populates_visual_and_audio(self, monkeypatch, tmp_path):
        _redirect_paths_to_empty(monkeypatch, tmp_path)
        _write_perception_state(
            tmp_path,
            {
                "desk_activity": "drumming",
                "desk_energy": 0.4,
                "detected_action": "scratching",
                "overhead_hand_zones": ["turntable"],
                "operator_confirmed": True,
                "top_emotion": "focused",
                "music_genre": "ambient",
                "ir_hand_zone": "turntable",
                "ir_hand_activity": 0.7,
                "ir_heart_rate_bpm": 72,
                "ir_heart_rate_conf": 0.82,
                "per_camera_scenes": {"overhead": "music production studio"},
                "per_camera_person_count": {"desk-c920": 1},
            },
        )
        field = build_perceptual_field()
        assert field.audio.contact_mic.desk_activity == "drumming"
        assert field.audio.contact_mic.fused_activity == "scratching"
        assert field.visual.detected_action == "scratching"
        assert field.visual.overhead_hand_zones == ["turntable"]
        assert field.visual.operator_confirmed is True
        assert field.visual.per_camera_scenes == {"overhead": "music production studio"}
        assert field.visual.per_camera_person_count == {"desk-c920": 1}
        assert field.ir.ir_hand_zone == "turntable"
        assert field.ir.ir_heart_rate_bpm == 72
        assert field.audio.studio_ingestion.music_genre == "ambient"


class TestStimmung:
    def test_stance_parses_to_enum(self, monkeypatch, tmp_path):
        _redirect_paths_to_empty(monkeypatch, tmp_path)
        _write_stimmung(
            tmp_path,
            {
                "overall_stance": "seeking",
                "dimensions": {"exploration_deficit": 0.4, "audience_engagement": 0.2},
            },
        )
        field = build_perceptual_field()
        assert field.stimmung.overall_stance == Stance.SEEKING
        assert field.stimmung.dimensions["exploration_deficit"] == 0.4

    def test_unknown_stance_becomes_none(self, monkeypatch, tmp_path):
        _redirect_paths_to_empty(monkeypatch, tmp_path)
        _write_stimmung(tmp_path, {"overall_stance": "euphoric"})
        field = build_perceptual_field()
        assert field.stimmung.overall_stance is None

    def test_dimensions_dict_with_reading_unpacks(self, monkeypatch, tmp_path):
        _redirect_paths_to_empty(monkeypatch, tmp_path)
        _write_stimmung(
            tmp_path,
            {
                "overall_stance": "nominal",
                "dimensions": {
                    "exploration_deficit": {"reading": 0.35, "_source": "vla"},
                    "audience_engagement": {"reading": 0.1},
                },
            },
        )
        field = build_perceptual_field()
        assert field.stimmung.dimensions["exploration_deficit"] == 0.35
        assert field.stimmung.dimensions["audience_engagement"] == 0.1


class TestChatNoAuthorLeakage:
    def test_chat_field_excludes_author_names(self, monkeypatch, tmp_path):
        _redirect_paths_to_empty(monkeypatch, tmp_path)
        chat_state = tmp_path / "chat-state.json"
        chat_recent = tmp_path / "chat-recent.json"
        chat_state.write_text(
            json.dumps(
                {
                    "unique_authors": 3,
                    "tier_counts": {"research_relevant": 2, "structural_signal": 1},
                    "authors": ["alice", "bob", "carol"],  # MUST NOT surface
                }
            )
        )
        chat_recent.write_text(
            json.dumps(
                [
                    {"author": "alice", "text": "hi"},  # MUST NOT surface
                    {"author": "bob", "text": "bye"},
                ]
            )
        )
        monkeypatch.setattr(pf, "_CHAT_STATE", chat_state)
        monkeypatch.setattr(pf, "_CHAT_RECENT", chat_recent)
        field = build_perceptual_field()
        dumped = field.model_dump_json()
        assert "alice" not in dumped
        assert "bob" not in dumped
        assert "carol" not in dumped
        assert "hi" not in dumped
        assert field.chat.recent_message_count == 2
        assert field.chat.unique_authors == 3
        assert field.chat.tier_counts == {
            "research_relevant": 2,
            "structural_signal": 1,
        }


class TestAlbum:
    def test_album_populates(self, monkeypatch, tmp_path):
        # `playing: True` is required for `build_perceptual_field` to
        # populate AlbumField.artist/title/current_track/year — without
        # it the populator suppresses those fields per PR #1936's
        # playing-flag guard. The test asserts that fields surface
        # under live-playing conditions, so the fixture must mark
        # playing=True explicitly.
        _redirect_paths_to_empty(monkeypatch, tmp_path)
        album = tmp_path / "album-state.json"
        album.write_text(
            json.dumps(
                {
                    "artist": "marciology",
                    "title": "side a",
                    "current_track": "track 3",
                    "year": 2023,
                    "confidence": 0.88,
                    "playing": True,
                }
            )
        )
        monkeypatch.setattr(pf, "_ALBUM_STATE", album)
        field = build_perceptual_field()
        assert field.album.artist == "marciology"
        assert field.album.year == 2023


class TestStreamLiveMarker:
    def test_stream_live_marker_detected(self, monkeypatch, tmp_path):
        _redirect_paths_to_empty(monkeypatch, tmp_path)
        live = tmp_path / "stream-live"
        live.write_text("on")
        monkeypatch.setattr(pf, "_STREAM_LIVE", live)
        field = build_perceptual_field()
        assert field.context.stream_live is True


class TestRoundtrip:
    def test_model_dump_json_roundtrip(self, monkeypatch, tmp_path):
        _redirect_paths_to_empty(monkeypatch, tmp_path)
        _write_perception_state(tmp_path, {"desk_activity": "typing"})
        _write_stimmung(tmp_path, {"overall_stance": "nominal"})
        field = build_perceptual_field()
        text = field.model_dump_json(exclude_none=True)
        restored = PerceptualField.model_validate_json(text)
        assert restored.audio.contact_mic.desk_activity == "typing"
        assert restored.stimmung.overall_stance == Stance.NOMINAL


class TestTimeOfDay:
    @pytest.mark.parametrize(
        "hour,expected",
        [
            (0, "night"),
            (6, "morning"),
            (13, "afternoon"),
            (19, "evening"),
            (23, "night"),
        ],
    )
    def test_time_of_day_buckets(self, hour, expected):
        # Build a specific timestamp at the requested hour
        from datetime import datetime

        dt = datetime(2026, 4, 17, hour, 30, 0).timestamp()
        assert pf._time_of_day(dt) == expected


# ── Fixtures helpers ──────────────────────────────────────────────────────


def _redirect_paths_to_empty(monkeypatch, tmp_path):
    """Point every module-level Path at a tmp location that doesn't exist."""
    monkeypatch.setattr(pf, "_PERCEPTION_STATE", tmp_path / "perception-state.json")
    monkeypatch.setattr(pf, "_STIMMUNG_STATE", tmp_path / "stimmung-state.json")
    monkeypatch.setattr(pf, "_ALBUM_STATE", tmp_path / "album-state.json")
    monkeypatch.setattr(pf, "_CHAT_STATE", tmp_path / "chat-state.json")
    monkeypatch.setattr(pf, "_CHAT_RECENT", tmp_path / "chat-recent.json")
    monkeypatch.setattr(pf, "_STREAM_LIVE", tmp_path / "stream-live")
    monkeypatch.setattr(pf, "_PRESENCE_STATE", tmp_path / "presence-state.json")
    monkeypatch.setattr(pf, "_WORKING_MODE", tmp_path / "working-mode")
    monkeypatch.setattr(pf, "_CONSENT_CONTRACTS_DIR", tmp_path / "contracts")
    monkeypatch.setattr(pf, "_OBJECTIVES_DIR", tmp_path / "objectives")
    monkeypatch.setattr(pf, "_read_stream_mode", lambda: None)


def _write_perception_state(tmp_path, data: dict) -> None:
    path = tmp_path / "perception-state.json"
    path.write_text(json.dumps(data))
    # The monkeypatch already aims at this path; the builder reads it via _read_perception_state.


def _write_stimmung(tmp_path, data: dict) -> None:
    path = tmp_path / "stimmung-state.json"
    path.write_text(json.dumps(data))
