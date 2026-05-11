"""Tests for the perception fusion layer."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from agents.perception_fusion import (
    _derive_activity,
    _fuse,
    _read_audio,
    _read_cameras,
    _read_ir,
    _write_fused,
    format_perception_context,
)


class TestReadAudio:
    def test_missing_file(self, tmp_path: Path):
        with patch("agents.perception_fusion.AUDIO_PATH", tmp_path / "missing.json"):
            result = _read_audio()
        assert result["available"] is False
        assert result["stale"] is True

    def test_valid_file(self, tmp_path: Path):
        audio_file = tmp_path / "audio.json"
        audio_file.write_text(
            json.dumps(
                {
                    "is_speech": True,
                    "music_playing": False,
                    "scene": "speech",
                    "confidence": 0.85,
                    "genre": None,
                    "bpm": None,
                    "key": None,
                    "speech_ratio": 0.6,
                    "vad_available": True,
                }
            )
        )
        with patch("agents.perception_fusion.AUDIO_PATH", audio_file):
            result = _read_audio()
        assert result["available"] is True
        assert result["is_speech"] is True
        assert result["scene"] == "speech"
        assert result["confidence"] == 0.85


class TestReadIR:
    def test_missing_file(self, tmp_path: Path):
        with patch("agents.perception_fusion.IR_HEALTH_PATH", tmp_path / "missing.json"):
            result = _read_ir()
        assert result["available"] is False

    def test_healthy_fleet(self, tmp_path: Path):
        ir_file = tmp_path / "health.json"
        ir_file.write_text(json.dumps({"error": 0.0, "reference": 1.0, "perception": 1.0}))
        with patch("agents.perception_fusion.IR_HEALTH_PATH", ir_file):
            result = _read_ir()
        assert result["available"] is True
        assert result["fleet_healthy"] is True


class TestReadCameras:
    def test_missing_file(self, tmp_path: Path):
        with patch("agents.perception_fusion.CAMERA_PATH", tmp_path / "missing.json"):
            result = _read_cameras()
        assert result["available"] is False

    def test_valid_classifications(self, tmp_path: Path):
        cam_file = tmp_path / "camera-classifications.json"
        cam_file.write_text(
            json.dumps(
                {
                    "brio-operator": {
                        "semantic_role": "operator-face",
                        "operator_visible": True,
                        "ambient_priority": 7,
                    },
                    "c920-desk": {
                        "semantic_role": "operator-hands",
                        "operator_visible": False,
                        "ambient_priority": 5,
                    },
                }
            )
        )
        layout_file = tmp_path / "layout-mode.txt"
        layout_file.write_text("balanced\n")
        with (
            patch("agents.perception_fusion.CAMERA_PATH", cam_file),
            patch("agents.perception_fusion.LAYOUT_MODE_PATH", layout_file),
        ):
            result = _read_cameras()
        assert result["available"] is True
        assert result["camera_count"] == 2
        assert result["operator_visible"] is True
        assert result["layout_mode"] == "balanced"


class TestDeriveActivity:
    def test_speaking_on_camera(self):
        audio = {"scene": "speech", "music_playing": False}
        cameras = {"operator_visible": True}
        assert _derive_activity(audio, cameras) == "speaking"

    def test_speaking_off_camera(self):
        audio = {"scene": "speech", "music_playing": False}
        cameras = {"operator_visible": False}
        assert _derive_activity(audio, cameras) == "speaking_off_camera"

    def test_music(self):
        audio = {"scene": "music", "music_playing": True}
        cameras = {"operator_visible": True}
        assert _derive_activity(audio, cameras) == "music"

    def test_coding(self):
        audio = {"scene": "typing", "music_playing": False}
        cameras = {"operator_visible": True}
        assert _derive_activity(audio, cameras) == "coding"

    def test_idle_present(self):
        audio = {"scene": "silence", "music_playing": False}
        cameras = {"operator_visible": True}
        assert _derive_activity(audio, cameras) == "present_idle"

    def test_away(self):
        audio = {"scene": "silence", "music_playing": False}
        cameras = {"operator_visible": False}
        assert _derive_activity(audio, cameras) == "away"


class TestWriteFused:
    def test_atomic_write(self, tmp_path: Path):
        out_dir = tmp_path / "hapax-perception"
        out_file = out_dir / "fused.json"
        with (
            patch("agents.perception_fusion.SHM_OUT_DIR", out_dir),
            patch("agents.perception_fusion.SHM_OUT_FILE", out_file),
        ):
            _write_fused({"timestamp": 123.0, "sources_available": 3})
        assert out_file.exists()
        data = json.loads(out_file.read_text())
        assert data["sources_available"] == 3
        assert not (out_dir / "fused.json.tmp").exists()


class TestFuse:
    def test_all_sources_missing(self, tmp_path: Path):
        with (
            patch("agents.perception_fusion.AUDIO_PATH", tmp_path / "a.json"),
            patch("agents.perception_fusion.IR_HEALTH_PATH", tmp_path / "b.json"),
            patch("agents.perception_fusion.CAMERA_PATH", tmp_path / "c.json"),
        ):
            result = _fuse()
        assert result["sources_available"] == 0
        assert result["sources_total"] == 3
        assert result["any_stale"] is True
        assert "timestamp" in result

    def test_output_structure(self, tmp_path: Path):
        audio_file = tmp_path / "audio.json"
        audio_file.write_text(json.dumps({"scene": "speech", "is_speech": True}))
        with (
            patch("agents.perception_fusion.AUDIO_PATH", audio_file),
            patch("agents.perception_fusion.IR_HEALTH_PATH", tmp_path / "b.json"),
            patch("agents.perception_fusion.CAMERA_PATH", tmp_path / "c.json"),
        ):
            result = _fuse()
        assert result["sources_available"] == 1
        assert "audio" in result
        assert "ir" in result
        assert "cameras" in result
        assert "derived_activity" in result


class TestFormatPerceptionContext:
    def test_none_returns_empty(self):
        assert format_perception_context(None) == ""

    def test_full_context(self):
        fused = {
            "derived_activity": "speaking",
            "audio": {
                "available": True,
                "scene": "speech",
                "music_playing": False,
                "genre": None,
                "bpm": None,
            },
            "cameras": {
                "available": True,
                "camera_count": 3,
                "operator_visible": True,
            },
            "ir": {
                "available": True,
                "fleet_healthy": True,
            },
        }
        result = format_perception_context(fused)
        assert result.startswith("Perception: ")
        assert "activity=speaking" in result
        assert "audio=speech" in result
        assert "operator_visible" in result
        assert "ir_fleet=ok" in result

    def test_music_with_bpm(self):
        fused = {
            "derived_activity": "music",
            "audio": {
                "available": True,
                "scene": "music",
                "music_playing": True,
                "genre": "electronic music",
                "bpm": 128,
            },
            "cameras": {"available": False},
            "ir": {"available": False},
        }
        result = format_perception_context(fused)
        assert "genre=electronic music" in result
        assert "bpm=128" in result
