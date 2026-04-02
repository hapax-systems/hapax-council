"""Tests for agents.studio_compositor — all mocked, no GStreamer/hardware needed."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agents.studio_compositor import (
    CameraSpec,
    CompositorConfig,
    HlsConfig,
    OverlayData,
    OverlayState,
    RecordingConfig,
    compute_tile_layout,
    load_config,
)

# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


class TestCameraSpec:
    def test_defaults(self) -> None:
        cam = CameraSpec(role="test", device="/dev/video0")
        assert cam.width == 1280
        assert cam.height == 720
        assert cam.input_format == "mjpeg"
        assert cam.pixel_format is None
        assert cam.hero is False

    def test_ir_camera(self) -> None:
        cam = CameraSpec(role="ir", device="/dev/video5", input_format="raw", pixel_format="gray")
        assert cam.input_format == "raw"
        assert cam.pixel_format == "gray"

    def test_hero_camera(self) -> None:
        cam = CameraSpec(role="brio", device="/dev/video0", hero=True)
        assert cam.hero is True


class TestRecordingConfig:
    def test_defaults(self) -> None:
        cfg = RecordingConfig()
        assert cfg.enabled is True
        assert cfg.segment_seconds == 300
        assert cfg.qp == 23
        assert str(cfg.output_dir).endswith("video-recording")

    def test_custom(self) -> None:
        cfg = RecordingConfig(enabled=False, segment_seconds=600, qp=18)
        assert cfg.enabled is False
        assert cfg.segment_seconds == 600
        assert cfg.qp == 18


class TestHlsConfig:
    def test_defaults(self) -> None:
        cfg = HlsConfig()
        assert cfg.enabled is True
        assert cfg.target_duration == 2
        assert cfg.playlist_length == 10
        assert cfg.max_files == 15
        assert cfg.bitrate == 4000
        assert "hls" in str(cfg.output_dir)

    def test_custom(self) -> None:
        cfg = HlsConfig(enabled=False, bitrate=2000, target_duration=4)
        assert cfg.enabled is False
        assert cfg.bitrate == 2000
        assert cfg.target_duration == 4


class TestCompositorConfig:
    def test_defaults(self) -> None:
        cfg = CompositorConfig()
        assert cfg.output_device == "/dev/video42"
        assert cfg.output_width == 1920
        assert cfg.output_height == 1080
        assert cfg.framerate == 10
        assert cfg.cameras == []
        assert cfg.overlay_enabled is True
        assert cfg.recording.enabled is True
        assert cfg.hls.enabled is True

    def test_custom_config(self) -> None:
        cfg = CompositorConfig(
            cameras=[CameraSpec(role="test", device="/dev/video0")],
            framerate=15,
            bitrate=4_000_000,
        )
        assert len(cfg.cameras) == 1
        assert cfg.framerate == 15
        assert cfg.bitrate == 4_000_000

    def test_recording_disabled(self) -> None:
        cfg = CompositorConfig(recording=RecordingConfig(enabled=False))
        assert cfg.recording.enabled is False

    def test_hls_disabled(self) -> None:
        cfg = CompositorConfig(hls=HlsConfig(enabled=False))
        assert cfg.hls.enabled is False

    def test_config_serialization_roundtrip(self) -> None:
        cfg = CompositorConfig(
            cameras=[CameraSpec(role="test", device="/dev/video0")],
            recording=RecordingConfig(segment_seconds=600),
            hls=HlsConfig(bitrate=2000),
        )
        data = json.loads(cfg.model_dump_json())
        restored = CompositorConfig(**data)
        assert restored.recording.segment_seconds == 600
        assert restored.hls.bitrate == 2000
        assert len(restored.cameras) == 1


class TestLoadConfig:
    def test_missing_file_returns_default(self, tmp_path: Path) -> None:
        cfg = load_config(path=tmp_path / "nonexistent.yaml")
        assert len(cfg.cameras) == 6  # default has 4 cameras

    def test_valid_yaml(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            """
cameras:
  - role: test-cam
    device: /dev/video0
    width: 640
    height: 480
framerate: 15
"""
        )
        cfg = load_config(path=config_path)
        assert len(cfg.cameras) == 1
        assert cfg.cameras[0].role == "test-cam"
        assert cfg.framerate == 15

    def test_invalid_yaml_falls_back(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.yaml"
        config_path.write_text("cameras: [[[invalid")
        cfg = load_config(path=config_path)
        assert len(cfg.cameras) == 6  # fell back to default


# ---------------------------------------------------------------------------
# Tile layout tests
# ---------------------------------------------------------------------------


class TestTileLayout:
    def test_empty_cameras(self) -> None:
        layout = compute_tile_layout([])
        assert layout == {}

    def test_single_camera_no_hero(self) -> None:
        cams = [CameraSpec(role="solo", device="/dev/video0")]
        layout = compute_tile_layout(cams, 1920, 1080)
        assert "solo" in layout
        tile = layout["solo"]
        assert tile.x == 0
        assert tile.y == 0
        assert tile.w == 1920
        assert tile.h == 1080

    def test_hero_with_others(self) -> None:
        cams = [
            CameraSpec(role="hero", device="/dev/video0", hero=True),
            CameraSpec(role="cam1", device="/dev/video1"),
            CameraSpec(role="cam2", device="/dev/video2"),
            CameraSpec(role="cam3", device="/dev/video3"),
        ]
        layout = compute_tile_layout(cams, 1920, 1080)

        # Hero: 16:9 fitted in left 2/3, centered vertically
        hero = layout["hero"]
        assert hero.w == 1280
        assert hero.h == 720
        assert hero.x == 0
        assert hero.y == 180  # centered: (1080-720)/2

        # Others: 16:9 fitted, stacked on right
        assert layout["cam1"].x == 1280
        assert layout["cam1"].y == 0
        assert layout["cam1"].w == 640
        assert layout["cam1"].h == 360
        assert layout["cam2"].y == 360
        assert layout["cam3"].y == 720

    def test_no_hero_grid(self) -> None:
        cams = [CameraSpec(role=f"cam{i}", device=f"/dev/video{i}") for i in range(4)]
        layout = compute_tile_layout(cams, 1920, 1080)
        assert len(layout) == 4
        # 2x2 grid
        assert layout["cam0"].x == 0
        assert layout["cam0"].y == 0
        assert layout["cam1"].x == 960
        assert layout["cam1"].y == 0
        assert layout["cam2"].x == 0
        assert layout["cam2"].y == 540
        assert layout["cam3"].x == 960
        assert layout["cam3"].y == 540

    def test_tiles_cover_canvas(self) -> None:
        """All tile areas should sum to at most the canvas area."""
        cams = [
            CameraSpec(role="hero", device="/dev/video0", hero=True),
            CameraSpec(role="cam1", device="/dev/video1"),
            CameraSpec(role="cam2", device="/dev/video2"),
        ]
        layout = compute_tile_layout(cams, 1920, 1080)
        total = sum(t.w * t.h for t in layout.values())
        assert total <= 1920 * 1080

    def test_hero_with_many_others(self) -> None:
        """With >4 non-hero cameras, hero gets 1/2 width, others stack right."""
        cams = [
            CameraSpec(role="hero", device="/dev/video0", hero=True),
        ] + [CameraSpec(role=f"cam{i}", device=f"/dev/video{i}") for i in range(6)]
        layout = compute_tile_layout(cams, 1920, 1080)
        assert len(layout) == 7
        # Hero: 16:9 fitted in left half
        assert layout["hero"].w == 960
        assert layout["hero"].h == 540
        # All others on the right
        for i in range(6):
            assert layout[f"cam{i}"].x >= 960

    def test_all_tiles_positive_dimensions(self) -> None:
        cams = [CameraSpec(role=f"cam{i}", device=f"/dev/video{i}") for i in range(8)]
        layout = compute_tile_layout(cams, 1920, 1080)
        for role, tile in layout.items():
            assert tile.w > 0, f"{role} has zero width"
            assert tile.h > 0, f"{role} has zero height"


# ---------------------------------------------------------------------------
# Overlay state tests
# ---------------------------------------------------------------------------


class TestOverlayData:
    def test_defaults(self) -> None:
        data = OverlayData()
        assert data.production_activity == ""
        assert data.flow_state == ""
        assert data.flow_score == 0.0
        assert data.audio_energy_rms == 0.0
        assert data.active_contracts == []

    def test_from_dict(self) -> None:
        raw = {
            "production_activity": "production",
            "music_genre": "boom bap",
            "flow_state": "active",
            "flow_score": 0.65,
            "audio_energy_rms": 0.042,
            "active_contracts": ["contract-guest1"],
            "timestamp": 1710505200.0,
        }
        data = OverlayData(**raw)
        assert data.production_activity == "production"
        assert data.flow_score == 0.65
        assert len(data.active_contracts) == 1


class TestOverlayState:
    def test_initial_stale(self) -> None:
        state = OverlayState()
        assert state.stale is True
        assert state.data.production_activity == ""

    def test_update_clears_stale(self) -> None:
        state = OverlayState()
        state.update(OverlayData(flow_state="active", flow_score=0.7))
        assert state.stale is False
        assert state.data.flow_state == "active"

    def test_mark_stale(self) -> None:
        state = OverlayState()
        state.update(OverlayData(flow_state="active"))
        state.mark_stale()
        assert state.stale is True
        # Data should still be accessible
        assert state.data.flow_state == "active"

    def test_thread_safety(self) -> None:
        """Concurrent reads and writes should not crash."""
        state = OverlayState()
        errors: list[Exception] = []

        def writer() -> None:
            try:
                for i in range(100):
                    state.update(OverlayData(flow_score=i / 100.0))
            except Exception as e:
                errors.append(e)

        def reader() -> None:
            try:
                for _ in range(100):
                    _ = state.data
                    _ = state.stale
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []


# ---------------------------------------------------------------------------
# State reader tests
# ---------------------------------------------------------------------------


class TestStateReader:
    def test_reads_valid_file(self, tmp_path: Path) -> None:
        """State reader should parse a valid perception-state.json."""
        state_file = tmp_path / "perception-state.json"
        state_file.write_text(
            json.dumps(
                {
                    "production_activity": "production",
                    "flow_state": "active",
                    "flow_score": 0.8,
                    "audio_energy_rms": 0.05,
                    "timestamp": time.time(),
                }
            )
        )
        data = OverlayData(**json.loads(state_file.read_text()))
        assert data.production_activity == "production"
        assert data.flow_score == 0.8

    def test_tolerates_missing_fields(self) -> None:
        """Extra/missing fields should not crash."""
        data = OverlayData(**{"production_activity": "idle", "timestamp": 0.0})
        assert data.flow_state == ""

    def test_tolerates_corrupt_json(self, tmp_path: Path) -> None:
        """Corrupt JSON should not crash."""
        state_file = tmp_path / "perception-state.json"
        state_file.write_text("{invalid json")
        with pytest.raises(json.JSONDecodeError):
            json.loads(state_file.read_text())


# ---------------------------------------------------------------------------
# Logos integration tests
# ---------------------------------------------------------------------------


class TestCompositorLogosStatus:
    def test_reads_status_file(self, tmp_path: Path) -> None:
        """CompositorStatus should be populated from status.json."""
        from logos.data.studio import CompositorStatus

        status_data = {
            "state": "running",
            "cameras": {"brio": "active", "c920": "offline"},
            "active_cameras": 1,
            "total_cameras": 2,
            "output_device": "/dev/video42",
            "resolution": "1920x1080",
            "recording_enabled": True,
            "recording_cameras": {"brio": "active"},
            "hls_enabled": True,
            "hls_url": "/api/studio/hls/stream.m3u8",
        }

        status = CompositorStatus(**status_data)
        assert status.state == "running"
        assert status.active_cameras == 1
        assert status.cameras["brio"] == "active"
        assert status.recording_enabled is True
        assert status.recording_cameras["brio"] == "active"
        assert status.hls_enabled is True
        assert status.hls_url == "/api/studio/hls/stream.m3u8"

    def test_default_status(self) -> None:
        from logos.data.studio import CompositorStatus

        status = CompositorStatus()
        assert status.state == "unknown"
        assert status.cameras == {}
        assert status.recording_enabled is False
        assert status.hls_enabled is False

    def test_studio_snapshot_includes_compositor(self) -> None:
        from logos.data.studio import StudioSnapshot

        snap = StudioSnapshot()
        assert hasattr(snap, "compositor")
        assert snap.compositor.state == "unknown"


# ---------------------------------------------------------------------------
# Perception state writer tests
# ---------------------------------------------------------------------------


class TestPerceptionStateWriter:
    def test_writes_valid_json(self, tmp_path: Path) -> None:
        """Writer should produce valid JSON with all expected fields."""
        from agents.hapax_daimonion._perception_state_writer import (
            write_perception_state,
        )

        # Mock perception engine with behaviors
        perception = MagicMock()
        behavior_mock = MagicMock()
        behavior_mock.value = "production"

        def mock_get(name: str) -> MagicMock | None:
            values = {
                "production_activity": MagicMock(value="production"),
                "music_genre": MagicMock(value="boom bap"),
                "flow_state_score": MagicMock(value=0.7),
                "emotion_valence": MagicMock(value=0.3),
                "emotion_arousal": MagicMock(value=0.5),
                "audio_energy_rms": MagicMock(value=0.04),
            }
            return values.get(name)

        perception.behaviors = MagicMock()
        perception.behaviors.get = mock_get

        # Mock consent registry
        consent = MagicMock()
        consent.active_contracts.return_value = []

        with (
            patch(
                "agents.hapax_daimonion._perception_state_writer.PERCEPTION_STATE_DIR",
                tmp_path,
            ),
            patch(
                "agents.hapax_daimonion._perception_state_writer.PERCEPTION_STATE_FILE",
                tmp_path / "perception-state.json",
            ),
        ):
            write_perception_state(perception, consent)

        state_file = tmp_path / "perception-state.json"
        assert state_file.exists()
        data = json.loads(state_file.read_text())
        assert data["production_activity"] == "production"
        assert data["music_genre"] == "boom bap"
        assert data["flow_state"] == "active"  # score 0.7 >= 0.6
        assert data["flow_score"] == 0.7
        assert data["audio_energy_rms"] == 0.04
        assert "timestamp" in data

    def test_flow_state_thresholds(self, tmp_path: Path) -> None:
        """Flow state should be derived from flow_score."""
        from agents.hapax_daimonion._perception_state_writer import write_perception_state

        perception = MagicMock()
        consent = MagicMock()
        consent.active_contracts.return_value = []

        for score, expected_state in [
            (0.8, "active"),
            (0.6, "active"),
            (0.5, "warming"),
            (0.3, "warming"),
            (0.2, "idle"),
            (0.0, "idle"),
        ]:

            def mock_get(name: str, _score: float = score) -> MagicMock | None:
                if name == "flow_state_score":
                    return MagicMock(value=_score)
                return None

            perception.behaviors = MagicMock()
            perception.behaviors.get = mock_get

            with (
                patch(
                    "agents.hapax_daimonion._perception_state_writer.PERCEPTION_STATE_DIR",
                    tmp_path,
                ),
                patch(
                    "agents.hapax_daimonion._perception_state_writer.PERCEPTION_STATE_FILE",
                    tmp_path / "perception-state.json",
                ),
            ):
                write_perception_state(perception, consent)

            data = json.loads((tmp_path / "perception-state.json").read_text())
            assert data["flow_state"] == expected_state, (
                f"score={score} should give state={expected_state}, got {data['flow_state']}"
            )
