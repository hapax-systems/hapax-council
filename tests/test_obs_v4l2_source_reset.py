"""Tests for hapax-obs-v4l2-source-reset monitor logic."""

from __future__ import annotations

import base64
import importlib
import json
import sys
import types
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image, PngImagePlugin


@pytest.fixture()
def reset_mod(tmp_path: Path) -> types.ModuleType:
    """Import the script as a module."""
    script = Path(__file__).resolve().parent.parent / "scripts" / "hapax-obs-v4l2-source-reset"
    loader = importlib.machinery.SourceFileLoader("obs_v4l2_reset", str(script))
    mod = types.ModuleType("obs_v4l2_reset")
    mod.__file__ = str(script)
    sys.modules["obs_v4l2_reset"] = mod
    loader.exec_module(mod)
    return mod


class TestScreenshotHash:
    def _png_data_uri(self, color: tuple[int, int, int], *, metadata: str) -> str:
        image = Image.new("RGB", (32, 18), color)
        pnginfo = PngImagePlugin.PngInfo()
        pnginfo.add_text("metadata", metadata)
        buffer = BytesIO()
        image.save(buffer, format="PNG", pnginfo=pnginfo)
        encoded = base64.b64encode(buffer.getvalue()).decode()
        return f"data:image/png;base64,{encoded}"

    def test_returns_hex_digest(self, reset_mod: types.ModuleType) -> None:
        client = MagicMock()
        client.get_source_screenshot.return_value = MagicMock(image_data="AAAA")
        h = reset_mod._get_screenshot_hash(client, "TestSource")
        assert h is not None
        assert len(h) == 64  # SHA-256 hex

    def test_returns_none_on_error(self, reset_mod: types.ModuleType) -> None:
        client = MagicMock()
        client.get_source_screenshot.side_effect = RuntimeError("no source")
        h = reset_mod._get_screenshot_hash(client, "TestSource")
        assert h is None

    def test_different_data_different_hash(self, reset_mod: types.ModuleType) -> None:
        client = MagicMock()
        client.get_source_screenshot.return_value = MagicMock(image_data="AAAA")
        h1 = reset_mod._get_screenshot_hash(client, "TestSource")
        client.get_source_screenshot.return_value = MagicMock(image_data="BBBB")
        h2 = reset_mod._get_screenshot_hash(client, "TestSource")
        assert h1 != h2

    def test_hashes_decoded_pixels_not_png_container_metadata(
        self, reset_mod: types.ModuleType
    ) -> None:
        client = MagicMock()
        client.get_source_screenshot.return_value = MagicMock(
            image_data=self._png_data_uri((10, 20, 30), metadata="first")
        )
        h1 = reset_mod._get_screenshot_hash(client, "TestSource")
        client.get_source_screenshot.return_value = MagicMock(
            image_data=self._png_data_uri((10, 20, 30), metadata="second")
        )
        h2 = reset_mod._get_screenshot_hash(client, "TestSource")
        client.get_source_screenshot.return_value = MagicMock(
            image_data=self._png_data_uri((10, 21, 30), metadata="second")
        )
        h3 = reset_mod._get_screenshot_hash(client, "TestSource")

        assert h1 == h2
        assert h2 != h3


class TestSourceActive:
    def test_active(self, reset_mod: types.ModuleType) -> None:
        client = MagicMock()
        client.get_source_active.return_value = MagicMock(video_active=True)
        assert reset_mod._is_source_active(client, "TestSource") is True

    def test_inactive(self, reset_mod: types.ModuleType) -> None:
        client = MagicMock()
        client.get_source_active.return_value = MagicMock(video_active=False)
        assert reset_mod._is_source_active(client, "TestSource") is False

    def test_error_returns_false(self, reset_mod: types.ModuleType) -> None:
        client = MagicMock()
        client.get_source_active.side_effect = RuntimeError("gone")
        assert reset_mod._is_source_active(client, "TestSource") is False


class TestTransportErrors:
    def test_broken_pipe_is_disconnected_not_missing_source(
        self, reset_mod: types.ModuleType
    ) -> None:
        client = MagicMock()
        client.get_source_active.side_effect = BrokenPipeError("broken pipe")

        probe = reset_mod._probe_source(
            client,
            "Video Capture Device (V4L2)",
            previous_hash=None,
            hash_stable_since=10.0,
            now=15.0,
        )

        assert probe.state is reset_mod.SourceState.DISCONNECTED
        assert probe.source_active is None
        assert probe.reason == "source_active_failed:BrokenPipeError"

    def test_true_missing_source_remains_source_missing(self, reset_mod: types.ModuleType) -> None:
        client = MagicMock()
        client.get_source_active.side_effect = RuntimeError("No source was found")

        probe = reset_mod._probe_source(
            client,
            "StudioCompositor",
            previous_hash=None,
            hash_stable_since=10.0,
            now=15.0,
        )

        assert probe.state is reset_mod.SourceState.SOURCE_MISSING
        assert probe.source_active is False


class TestFindSceneItem:
    def test_finds_matching_item(self, reset_mod: types.ModuleType) -> None:
        client = MagicMock()
        client.get_current_program_scene.return_value = MagicMock(scene_name="Scene")
        client.get_scene_item_list.return_value = MagicMock(
            scene_items=[
                {"sourceName": "Audio", "sceneItemId": 1},
                {"sourceName": "StudioCompositor", "sceneItemId": 7},
            ]
        )
        result = reset_mod._find_scene_item(client, "StudioCompositor")
        assert result == ("Scene", 7)

    def test_returns_none_when_missing(self, reset_mod: types.ModuleType) -> None:
        client = MagicMock()
        client.get_current_program_scene.return_value = MagicMock(scene_name="Scene")
        client.get_scene_item_list.return_value = MagicMock(
            scene_items=[{"sourceName": "Audio", "sceneItemId": 1}]
        )
        assert reset_mod._find_scene_item(client, "Missing") is None


class TestToggleVisibility:
    def test_toggles_off_then_on(self, reset_mod: types.ModuleType) -> None:
        client = MagicMock()
        with patch.object(reset_mod.time, "sleep"):
            result = reset_mod._toggle_visibility(client, "Scene", 7)
        assert result is True
        calls = client.set_scene_item_enabled.call_args_list
        assert len(calls) == 2
        assert calls[0].kwargs["scene_item_enabled"] is False
        assert calls[1].kwargs["scene_item_enabled"] is True

    def test_returns_false_on_error(self, reset_mod: types.ModuleType) -> None:
        client = MagicMock()
        client.set_scene_item_enabled.side_effect = RuntimeError("nope")
        with patch.object(reset_mod.time, "sleep"):
            result = reset_mod._toggle_visibility(client, "Scene", 7)
        assert result is False


class TestInputSettings:
    def test_builds_obs_v4l2_contract_values(self, reset_mod: types.ModuleType) -> None:
        settings = reset_mod._build_input_settings(
            device_id="/dev/video50",
            resolution="1920x1080",
            framerate=60.0,
            pixelformat="NV12",
            disable_buffering=True,
            auto_reset_input=True,
        )

        assert settings == {
            "device_id": "/dev/video50",
            "resolution": (1920 << 32) | 1080,
            "framerate": (1 << 32) | 60,
            "pixelformat": int.from_bytes(b"NV12", "little"),
            "buffering": False,
            "auto_reset": True,
            "input": 0,
        }

    def test_nonnegative_seconds_rejects_negative_values(self, reset_mod: types.ModuleType) -> None:
        with pytest.raises(reset_mod.argparse.ArgumentTypeError):
            reset_mod._nonnegative_seconds("-1")

        assert reset_mod._nonnegative_seconds("0") == 0.0
        assert reset_mod._nonnegative_seconds("75") == 75.0

    def test_positive_int_rejects_non_positive_values(self, reset_mod: types.ModuleType) -> None:
        with pytest.raises(reset_mod.argparse.ArgumentTypeError):
            reset_mod._positive_int("0")
        with pytest.raises(reset_mod.argparse.ArgumentTypeError):
            reset_mod._positive_int("-1")

        assert reset_mod._positive_int("320") == 320

    def test_apply_input_settings_supports_keyword_obsws_client(
        self, reset_mod: types.ModuleType
    ) -> None:
        client = MagicMock()
        settings = {"device_id": "/dev/video50"}

        assert reset_mod._apply_input_settings(client, "Video Capture Device (V4L2)", settings)
        client.set_input_settings.assert_called_once_with(
            name="Video Capture Device (V4L2)",
            settings=settings,
            overlay=True,
        )

    def test_apply_input_settings_supports_positional_obsws_client(
        self, reset_mod: types.ModuleType
    ) -> None:
        class PositionalClient:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict[str, object], bool]] = []

            def set_input_settings(self, name: str, settings: dict[str, object], overlay: bool):
                self.calls.append((name, settings, overlay))

        client = PositionalClient()
        settings = {"device_id": "/dev/video50"}

        assert reset_mod._apply_input_settings(client, "Video Capture Device (V4L2)", settings)
        assert client.calls == [("Video Capture Device (V4L2)", settings, True)]


class TestPrometheus:
    def test_writes_prom_file(self, reset_mod: types.ModuleType, tmp_path: Path) -> None:
        prom_path = tmp_path / "test.prom"
        reset_mod._emit_prometheus(prom_path, 3)
        content = prom_path.read_text()
        assert "hapax_obs_v4l2_source_resets_total 3" in content
        assert "hapax_obs_v4l2_source_reset_active 1" in content
        assert "# TYPE hapax_obs_v4l2_source_resets_total counter" in content

    def test_none_path_is_noop(self, reset_mod: types.ModuleType) -> None:
        reset_mod._emit_prometheus(None, 5)


class TestWriteStatus:
    def test_writes_json(self, reset_mod: types.ModuleType, tmp_path: Path) -> None:
        status_dir = tmp_path / "status"
        status_file = status_dir / "status.json"
        status = reset_mod.MonitorStatus(
            state=reset_mod.SourceState.HEALTHY,
            connected=True,
            source_active=True,
            screenshot_available=True,
            reset_count=2,
            reset_failures=1,
            consecutive_failures=0,
            last_reset_at="2026-05-08T00:00:00Z",
            last_success_at="2026-05-08T00:01:00Z",
            last_hash="abc123",
            stall_seconds=5.3,
            cooldown_remaining_seconds=0.0,
            reason=None,
        )
        with (
            patch.object(reset_mod, "STATUS_DIR", status_dir),
            patch.object(reset_mod, "STATUS_PATH", status_file),
        ):
            reset_mod._write_status(status)
        data = json.loads(status_file.read_text())
        assert data["state"] == "healthy"
        assert data["connected"] is True
        assert data["source_active"] is True
        assert data["screenshot_available"] is True
        assert data["reset_count"] == 2
        assert data["reset_failures"] == 1
        assert data["stall_seconds"] == 5.3


class TestProbeSource:
    def test_inactive_source_is_remediable_drop(self, reset_mod: types.ModuleType) -> None:
        client = MagicMock()
        client.get_source_active.return_value = MagicMock(video_active=False)

        probe = reset_mod._probe_source(
            client,
            "StudioCompositor",
            previous_hash=None,
            hash_stable_since=10.0,
            now=15.0,
        )

        assert probe.state is reset_mod.SourceState.INACTIVE
        assert probe.source_active is False
        assert probe.screenshot_available is False

    def test_unchanged_hash_becomes_stalled(self, reset_mod: types.ModuleType) -> None:
        client = MagicMock()
        client.get_source_active.return_value = MagicMock(video_active=True)
        image_data = "same-frame"
        digest = reset_mod.hashlib.sha256(image_data.encode()).hexdigest()
        client.get_source_screenshot.return_value = MagicMock(image_data=image_data)

        probe = reset_mod._probe_source(
            client,
            "StudioCompositor",
            previous_hash=digest,
            hash_stable_since=10.0,
            now=45.0,
        )

        assert probe.state is reset_mod.SourceState.STALLED
        assert probe.stall_seconds == 35.0

    def test_screenshot_transport_error_disconnects_client(
        self, reset_mod: types.ModuleType
    ) -> None:
        client = MagicMock()
        client.get_source_active.return_value = MagicMock(video_active=True)
        client.get_source_screenshot.side_effect = TimeoutError("timed out")

        probe = reset_mod._probe_source(
            client,
            "Video Capture Device (V4L2)",
            previous_hash=None,
            hash_stable_since=10.0,
            now=45.0,
        )

        assert probe.state is reset_mod.SourceState.DISCONNECTED
        assert probe.source_active is True
        assert probe.screenshot_available is False


class TestObswsCompatibility:
    def test_keyword_screenshot_client_receives_quality(self, reset_mod: types.ModuleType) -> None:
        client = MagicMock()
        client.get_source_screenshot.return_value = MagicMock(image_data="frame")

        reset_mod._get_source_screenshot_response(
            client,
            "Video Capture Device (V4L2)",
            width=320,
            height=180,
            quality=75,
        )

        client.get_source_screenshot.assert_called_once_with(
            source_name="Video Capture Device (V4L2)",
            image_format="png",
            image_width=320,
            image_height=180,
            image_compression_quality=75,
        )

    def test_probe_supports_positional_obsws_client(self, reset_mod: types.ModuleType) -> None:
        class PositionalClient:
            def get_source_active(self, source_name: str):
                assert source_name == "Video Capture Device (V4L2)"
                return MagicMock(video_active=True)

            def get_source_screenshot(
                self,
                source_name: str,
                image_format: str,
                image_width: int,
                image_height: int,
                quality: int,
            ):
                assert source_name == "Video Capture Device (V4L2)"
                assert image_format == "png"
                assert (image_width, image_height, quality) == (
                    reset_mod.SCREENSHOT_WIDTH,
                    reset_mod.SCREENSHOT_HEIGHT,
                    reset_mod.SCREENSHOT_QUALITY,
                )
                return MagicMock(image_data="frame")

        probe = reset_mod._probe_source(
            PositionalClient(),
            "Video Capture Device (V4L2)",
            previous_hash=None,
            hash_stable_since=10.0,
            now=15.0,
        )

        assert probe.state is reset_mod.SourceState.HEALTHY
        assert probe.source_active is True
        assert probe.screenshot_available is True

    def test_probe_uses_configured_screenshot_dimensions(self, reset_mod: types.ModuleType) -> None:
        calls: list[tuple[int, int, int]] = []

        class PositionalClient:
            def get_source_active(self, source_name: str):
                assert source_name == "Video Capture Device (V4L2)"
                return MagicMock(video_active=True)

            def get_source_screenshot(
                self,
                source_name: str,
                image_format: str,
                image_width: int,
                image_height: int,
                quality: int,
            ):
                assert source_name == "Video Capture Device (V4L2)"
                assert image_format == "png"
                calls.append((image_width, image_height, quality))
                return MagicMock(image_data="frame")

        probe = reset_mod._probe_source(
            PositionalClient(),
            "Video Capture Device (V4L2)",
            previous_hash=None,
            hash_stable_since=10.0,
            now=15.0,
            screenshot_width=320,
            screenshot_height=180,
            screenshot_quality=75,
        )

        assert probe.state is reset_mod.SourceState.HEALTHY
        assert calls == [(320, 180, 75)]

    def test_scene_toggle_supports_positional_obsws_client(
        self, reset_mod: types.ModuleType
    ) -> None:
        class PositionalClient:
            def __init__(self) -> None:
                self.calls: list[tuple[str, int, bool]] = []

            def set_scene_item_enabled(
                self,
                scene_name: str,
                item_id: int,
                enabled: bool,
            ) -> None:
                self.calls.append((scene_name, item_id, enabled))

        client = PositionalClient()
        with patch.object(reset_mod.time, "sleep"):
            assert reset_mod._toggle_visibility(client, "Scene", 7) is True
        assert client.calls == [("Scene", 7, False), ("Scene", 7, True)]


class TestProducerRestart:
    def test_restart_sequence_allows_bridge_darkplaces_bridge_order(
        self, reset_mod: types.ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[str, float]] = []

        def fake_restart(service_name: str, *, timeout: float) -> bool:
            calls.append((service_name, timeout))
            return True

        monkeypatch.setattr(reset_mod, "_restart_producer_service", fake_restart)

        assert reset_mod._restart_producer_services(
            [
                "hapax-obs-video50-yuyv-compat-bridge.service",
                "hapax-darkplaces-v4l2.service",
                "hapax-obs-video50-yuyv-compat-bridge.service",
            ],
            timeout=12.0,
        )
        assert calls == [
            ("hapax-obs-video50-yuyv-compat-bridge.service", 12.0),
            ("hapax-darkplaces-v4l2.service", 12.0),
            ("hapax-obs-video50-yuyv-compat-bridge.service", 12.0),
        ]

    def test_restart_fallback_kills_stale_unit_children(
        self, reset_mod: types.ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[list[str]] = []

        def fake_run(command: list[str], **kwargs: object):
            calls.append(command)
            if command[-2:] == ["restart", "hapax-darkplaces-v4l2.service"]:
                raise reset_mod.subprocess.TimeoutExpired(command, kwargs["timeout"])
            return reset_mod.subprocess.CompletedProcess(command, 0, "", "")

        monkeypatch.setattr(reset_mod.subprocess, "run", fake_run)
        monkeypatch.setattr(reset_mod.time, "sleep", lambda _seconds: None)

        assert reset_mod._restart_producer_service(
            "hapax-darkplaces-v4l2.service",
            timeout=30.0,
        )
        assert calls == [
            ["systemctl", "--user", "restart", "hapax-darkplaces-v4l2.service"],
            [
                "systemctl",
                "--user",
                "kill",
                "--kill-who=all",
                "--signal=KILL",
                "hapax-darkplaces-v4l2.service",
            ],
            ["systemctl", "--user", "reset-failed", "hapax-darkplaces-v4l2.service"],
            ["systemctl", "--user", "start", "hapax-darkplaces-v4l2.service"],
        ]


class TestObsLogV4l2Errors:
    def test_scan_starts_at_eof_then_reports_fresh_device_timeout(
        self, reset_mod: types.ModuleType, tmp_path: Path
    ) -> None:
        log = tmp_path / "obs.txt"
        log.write_text(
            "14:00:00.000: v4l2-input: /dev/video50: select timed out\n",
            encoding="utf-8",
        )

        cursor, reason = reset_mod._scan_obs_log_v4l2_errors(
            reset_mod.ObsLogCursor(),
            log_dir=tmp_path,
            device_id="/dev/video50",
        )
        assert reason is None

        with log.open("a", encoding="utf-8") as fh:
            fh.write("14:00:01.000: v4l2-input: /dev/video50: select timed out\n")

        cursor, reason = reset_mod._scan_obs_log_v4l2_errors(
            cursor,
            log_dir=tmp_path,
            device_id="/dev/video50",
        )
        assert reason == "obs_log_v4l2_timeout:/dev/video50"
        assert cursor.path == log
        assert cursor.offset == log.stat().st_size

    def test_scan_reports_single_self_recovered_timeout(
        self, reset_mod: types.ModuleType, tmp_path: Path
    ) -> None:
        log = tmp_path / "obs.txt"
        log.write_text("", encoding="utf-8")
        cursor, reason = reset_mod._scan_obs_log_v4l2_errors(
            reset_mod.ObsLogCursor(),
            log_dir=tmp_path,
            device_id="/dev/video50",
        )
        assert reason is None

        with log.open("a", encoding="utf-8") as fh:
            fh.write("14:00:01.000: v4l2-input: /dev/video50: select timed out\n")
            fh.write("14:00:01.000: v4l2-input: /dev/video50: stream reset successful\n")

        cursor, reason = reset_mod._scan_obs_log_v4l2_errors(
            cursor,
            log_dir=tmp_path,
            device_id="/dev/video50",
        )
        assert reason == "obs_log_v4l2_timeout_self_recovered:/dev/video50"
        assert cursor.path == log
        assert cursor.offset == log.stat().st_size

    def test_scan_reports_repeated_self_recovered_timeouts(
        self, reset_mod: types.ModuleType, tmp_path: Path
    ) -> None:
        log = tmp_path / "obs.txt"
        log.write_text("", encoding="utf-8")
        cursor, reason = reset_mod._scan_obs_log_v4l2_errors(
            reset_mod.ObsLogCursor(),
            log_dir=tmp_path,
            device_id="/dev/video50",
        )
        assert reason is None

        with log.open("a", encoding="utf-8") as fh:
            fh.write("14:00:01.000: v4l2-input: /dev/video50: select timed out\n")
            fh.write("14:00:01.000: v4l2-input: /dev/video50: stream reset successful\n")
            fh.write("14:00:07.000: v4l2-input: /dev/video50: select timed out\n")
            fh.write("14:00:07.000: v4l2-input: /dev/video50: stream reset successful\n")

        _, reason = reset_mod._scan_obs_log_v4l2_errors(
            cursor,
            log_dir=tmp_path,
            device_id="/dev/video50",
        )
        assert reason == "obs_log_v4l2_timeout:/dev/video50"

    def test_scan_prefers_start_failure_over_self_recovered_timeout(
        self, reset_mod: types.ModuleType, tmp_path: Path
    ) -> None:
        log = tmp_path / "obs.txt"
        log.write_text("", encoding="utf-8")
        cursor, reason = reset_mod._scan_obs_log_v4l2_errors(
            reset_mod.ObsLogCursor(),
            log_dir=tmp_path,
            device_id="/dev/video50",
        )
        assert reason is None

        with log.open("a", encoding="utf-8") as fh:
            fh.write("14:00:01.000: v4l2-input: /dev/video50: select timed out\n")
            fh.write("14:00:01.000: v4l2-input: /dev/video50: stream reset successful\n")
            fh.write("14:00:02.000: v4l2-helpers: unable to start stream\n")

        _, reason = reset_mod._scan_obs_log_v4l2_errors(
            cursor,
            log_dir=tmp_path,
            device_id="/dev/video50",
        )
        assert reason == "obs_log_v4l2_start_failed:/dev/video50"


class TestHealthMetrics:
    def test_prometheus_includes_state_and_health_gauges(
        self,
        reset_mod: types.ModuleType,
        tmp_path: Path,
    ) -> None:
        prom_path = tmp_path / "test.prom"
        status = reset_mod.MonitorStatus(
            state=reset_mod.SourceState.RECONNECT_COOLDOWN,
            connected=True,
            source_active=False,
            screenshot_available=False,
            reset_count=1,
            reset_failures=0,
            consecutive_failures=0,
            last_reset_at="2026-05-08T00:00:00Z",
            last_success_at=None,
            last_hash=None,
            stall_seconds=0.0,
            cooldown_remaining_seconds=42.5,
            reason="source inactive",
        )

        reset_mod._emit_prometheus(prom_path, 1, status)
        content = prom_path.read_text()

        assert 'hapax_obs_v4l2_source_health{state="reconnect_cooldown"} 1' in content
        assert 'hapax_obs_v4l2_source_health{state="healthy"} 0' in content
        assert "hapax_obs_v4l2_source_active 0" in content
        assert "hapax_obs_v4l2_source_reconnect_cooldown_seconds 42.500" in content
        assert "hapax_obs_v4l2_source_producer_restarts_total 0" in content


class TestMonitorLoop:
    def test_input_settings_reacquire_source_on_connect(
        self,
        reset_mod: types.ModuleType,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client = MagicMock()
        client.get_source_active.return_value = MagicMock(video_active=True)
        client.get_source_screenshot.return_value = MagicMock(image_data="frame")
        client.get_current_program_scene.return_value = MagicMock(scene_name="Scene")
        client.get_scene_item_list.return_value = MagicMock(
            scene_items=[{"sourceName": "Video Capture Device (V4L2)", "sceneItemId": 366}]
        )
        prom_path = tmp_path / "reset.prom"
        status_path = tmp_path / "status.json"
        monkeypatch.setattr(reset_mod, "_connect", lambda _host, _port: client)
        monkeypatch.setattr(reset_mod, "STATUS_PATH", status_path)
        monkeypatch.setattr(reset_mod, "STATUS_DIR", tmp_path)
        monkeypatch.setattr(reset_mod, "_shutdown", False)
        monkeypatch.setattr(reset_mod.time, "monotonic", lambda: 100.0)

        def fake_toggle(toggle_client, scene_name: str, item_id: int) -> bool:
            toggle_client.set_scene_item_enabled(
                scene_name=scene_name,
                scene_item_id=item_id,
                scene_item_enabled=False,
            )
            toggle_client.set_scene_item_enabled(
                scene_name=scene_name,
                scene_item_id=item_id,
                scene_item_enabled=True,
            )
            return True

        monkeypatch.setattr(reset_mod, "_toggle_visibility", fake_toggle)

        def stop_after_sleep(_seconds: float) -> None:
            monkeypatch.setattr(reset_mod, "_shutdown", True)

        monkeypatch.setattr(reset_mod.time, "sleep", stop_after_sleep)

        try:
            reset_mod.monitor_loop(
                host="localhost",
                port=4455,
                source_name="Video Capture Device (V4L2)",
                poll_interval=0.01,
                stall_threshold=300.0,
                reset_cooldown=60.0,
                metrics_path=prom_path,
                input_settings={"device_id": "/dev/video50"},
            )
        finally:
            monkeypatch.setattr(reset_mod, "_shutdown", False)

        status = json.loads(status_path.read_text())
        assert status["state"] == "healthy"
        assert status["reset_count"] == 1
        client.set_input_settings.assert_called_once()
        calls = client.set_scene_item_enabled.call_args_list
        assert [call.kwargs["scene_item_enabled"] for call in calls] == [False, True]

    def test_input_settings_reacquire_is_not_repeated_after_transport_reconnect(
        self,
        reset_mod: types.ModuleType,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        first_client = MagicMock()
        first_client.get_source_active.return_value = MagicMock(video_active=True)
        first_client.get_source_screenshot.side_effect = TimeoutError("timed out")
        first_client.get_current_program_scene.return_value = MagicMock(scene_name="Scene")
        first_client.get_scene_item_list.return_value = MagicMock(
            scene_items=[{"sourceName": "Video Capture Device (V4L2)", "sceneItemId": 366}]
        )
        second_client = MagicMock()
        second_client.get_source_active.return_value = MagicMock(video_active=True)
        second_client.get_source_screenshot.return_value = MagicMock(image_data="fresh-frame")
        second_client.get_current_program_scene.return_value = MagicMock(scene_name="Scene")
        second_client.get_scene_item_list.return_value = MagicMock(
            scene_items=[{"sourceName": "Video Capture Device (V4L2)", "sceneItemId": 366}]
        )
        clients = iter([first_client, second_client])
        prom_path = tmp_path / "reset.prom"
        status_path = tmp_path / "status.json"
        sleep_calls = 0
        monkeypatch.setattr(reset_mod, "_connect", lambda _host, _port: next(clients))
        monkeypatch.setattr(reset_mod, "STATUS_PATH", status_path)
        monkeypatch.setattr(reset_mod, "STATUS_DIR", tmp_path)
        monkeypatch.setattr(reset_mod, "_shutdown", False)
        monkeypatch.setattr(reset_mod.time, "monotonic", lambda: 100.0)

        def fake_toggle(toggle_client, scene_name: str, item_id: int) -> bool:
            toggle_client.set_scene_item_enabled(
                scene_name=scene_name,
                scene_item_id=item_id,
                scene_item_enabled=False,
            )
            toggle_client.set_scene_item_enabled(
                scene_name=scene_name,
                scene_item_id=item_id,
                scene_item_enabled=True,
            )
            return True

        monkeypatch.setattr(reset_mod, "_toggle_visibility", fake_toggle)

        def stop_after_second_sleep(_seconds: float) -> None:
            nonlocal sleep_calls
            sleep_calls += 1
            if sleep_calls >= 2:
                monkeypatch.setattr(reset_mod, "_shutdown", True)

        monkeypatch.setattr(reset_mod.time, "sleep", stop_after_second_sleep)

        try:
            reset_mod.monitor_loop(
                host="localhost",
                port=4455,
                source_name="Video Capture Device (V4L2)",
                poll_interval=0.01,
                stall_threshold=300.0,
                reset_cooldown=60.0,
                metrics_path=prom_path,
                input_settings={"device_id": "/dev/video50"},
            )
        finally:
            monkeypatch.setattr(reset_mod, "_shutdown", False)

        status = json.loads(status_path.read_text())
        assert status["state"] == "healthy"
        assert status["reset_count"] == 1
        first_client.set_input_settings.assert_called_once()
        second_client.set_input_settings.assert_not_called()
        assert first_client.set_scene_item_enabled.call_count == 2
        second_client.set_scene_item_enabled.assert_not_called()

    def test_inactive_source_toggles_visibility_and_writes_reconnected_status(
        self,
        reset_mod: types.ModuleType,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client = MagicMock()
        client.get_source_active.return_value = MagicMock(video_active=False)
        client.get_current_program_scene.return_value = MagicMock(scene_name="Scene")
        client.get_scene_item_list.return_value = MagicMock(
            scene_items=[{"sourceName": "StudioCompositor", "sceneItemId": 7}]
        )
        prom_path = tmp_path / "reset.prom"
        status_path = tmp_path / "status.json"
        monkeypatch.setattr(reset_mod, "_connect", lambda _host, _port: client)
        monkeypatch.setattr(reset_mod, "_send_ntfy", lambda _reason: None)
        monkeypatch.setattr(reset_mod, "STATUS_PATH", status_path)
        monkeypatch.setattr(reset_mod, "STATUS_DIR", tmp_path)
        monkeypatch.setattr(reset_mod, "_shutdown", False)
        monkeypatch.setattr(reset_mod.time, "monotonic", lambda: 100.0)

        def fake_toggle(toggle_client, scene_name: str, item_id: int) -> bool:
            toggle_client.set_scene_item_enabled(
                scene_name=scene_name,
                scene_item_id=item_id,
                scene_item_enabled=False,
            )
            toggle_client.set_scene_item_enabled(
                scene_name=scene_name,
                scene_item_id=item_id,
                scene_item_enabled=True,
            )
            return True

        monkeypatch.setattr(reset_mod, "_toggle_visibility", fake_toggle)

        def stop_after_sleep(_seconds: float) -> None:
            monkeypatch.setattr(reset_mod, "_shutdown", True)

        monkeypatch.setattr(reset_mod.time, "sleep", stop_after_sleep)

        try:
            reset_mod.monitor_loop(
                host="localhost",
                port=4455,
                source_name="StudioCompositor",
                poll_interval=0.01,
                stall_threshold=30.0,
                reset_cooldown=60.0,
                metrics_path=prom_path,
            )
        finally:
            monkeypatch.setattr(reset_mod, "_shutdown", False)

        status = json.loads(status_path.read_text())
        assert status["state"] == "reconnected"
        assert status["reset_count"] == 1
        calls = client.set_scene_item_enabled.call_args_list
        assert [call.kwargs["scene_item_enabled"] for call in calls] == [False, True]
        assert 'hapax_obs_v4l2_source_health{state="reconnected"} 1' in prom_path.read_text()

    def test_reset_cooldown_blocks_second_reconnect(
        self,
        reset_mod: types.ModuleType,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client = MagicMock()
        client.get_source_active.return_value = MagicMock(video_active=False)
        client.get_current_program_scene.return_value = MagicMock(scene_name="Scene")
        client.get_scene_item_list.return_value = MagicMock(
            scene_items=[{"sourceName": "StudioCompositor", "sceneItemId": 7}]
        )
        prom_path = tmp_path / "reset.prom"
        status_path = tmp_path / "status.json"
        sleep_calls = 0
        real_time = reset_mod.time
        monotonic_values = iter([100.0, 110.0])
        monkeypatch.setattr(reset_mod, "_connect", lambda _host, _port: client)
        monkeypatch.setattr(reset_mod, "_send_ntfy", lambda _reason: None)
        monkeypatch.setattr(reset_mod, "STATUS_PATH", status_path)
        monkeypatch.setattr(reset_mod, "STATUS_DIR", tmp_path)
        monkeypatch.setattr(reset_mod, "_shutdown", False)

        def fake_monotonic() -> float:
            return next(monotonic_values)

        def fake_toggle(toggle_client, scene_name: str, item_id: int) -> bool:
            toggle_client.set_scene_item_enabled(
                scene_name=scene_name,
                scene_item_id=item_id,
                scene_item_enabled=False,
            )
            toggle_client.set_scene_item_enabled(
                scene_name=scene_name,
                scene_item_id=item_id,
                scene_item_enabled=True,
            )
            return True

        monkeypatch.setattr(reset_mod, "_toggle_visibility", fake_toggle)

        def stop_after_two_loop_sleeps(_seconds: float) -> None:
            nonlocal sleep_calls
            sleep_calls += 1
            if sleep_calls >= 2:
                monkeypatch.setattr(reset_mod, "_shutdown", True)

        monkeypatch.setattr(
            reset_mod,
            "time",
            types.SimpleNamespace(
                monotonic=fake_monotonic,
                sleep=stop_after_two_loop_sleeps,
                strftime=real_time.strftime,
                gmtime=real_time.gmtime,
            ),
        )

        try:
            reset_mod.monitor_loop(
                host="localhost",
                port=4455,
                source_name="StudioCompositor",
                poll_interval=0.01,
                stall_threshold=30.0,
                reset_cooldown=60.0,
                metrics_path=prom_path,
            )
        finally:
            monkeypatch.setattr(reset_mod, "_shutdown", False)

        status = json.loads(status_path.read_text())
        assert status["state"] == "reconnect_cooldown"
        assert status["reset_count"] == 1
        assert status["cooldown_remaining_seconds"] == 50.0
        assert client.set_scene_item_enabled.call_count == 2

    def test_repeated_stall_escalates_to_producer_restart(
        self,
        reset_mod: types.ModuleType,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client = MagicMock()
        client.get_source_active.return_value = MagicMock(video_active=True)
        client.get_source_screenshot.return_value = MagicMock(image_data="same-frame")
        client.get_current_program_scene.return_value = MagicMock(scene_name="Scene")
        client.get_scene_item_list.return_value = MagicMock(
            scene_items=[{"sourceName": "StudioCompositor", "sceneItemId": 7}]
        )
        prom_path = tmp_path / "reset.prom"
        status_path = tmp_path / "status.json"
        restart_calls: list[tuple[str, float]] = []
        sleep_calls = 0
        real_time = reset_mod.time
        monotonic_values = iter([100.0, 170.0, 180.0, 250.0])
        monkeypatch.setattr(reset_mod, "_connect", lambda _host, _port: client)
        monkeypatch.setattr(reset_mod, "_send_ntfy", lambda _reason: None)
        monkeypatch.setattr(reset_mod, "STATUS_PATH", status_path)
        monkeypatch.setattr(reset_mod, "STATUS_DIR", tmp_path)
        monkeypatch.setattr(reset_mod, "_shutdown", False)

        def fake_monotonic() -> float:
            return next(monotonic_values)

        def fake_toggle(toggle_client, scene_name: str, item_id: int) -> bool:
            toggle_client.set_scene_item_enabled(
                scene_name=scene_name,
                scene_item_id=item_id,
                scene_item_enabled=False,
            )
            toggle_client.set_scene_item_enabled(
                scene_name=scene_name,
                scene_item_id=item_id,
                scene_item_enabled=True,
            )
            return True

        def fake_restart(service_name: str, *, timeout: float) -> bool:
            restart_calls.append((service_name, timeout))
            return True

        monkeypatch.setattr(reset_mod, "_toggle_visibility", fake_toggle)
        monkeypatch.setattr(reset_mod, "_restart_producer_service", fake_restart)

        def stop_after_four_loop_sleeps(_seconds: float) -> None:
            nonlocal sleep_calls
            sleep_calls += 1
            if sleep_calls >= 4:
                monkeypatch.setattr(reset_mod, "_shutdown", True)

        monkeypatch.setattr(
            reset_mod,
            "time",
            types.SimpleNamespace(
                monotonic=fake_monotonic,
                sleep=stop_after_four_loop_sleeps,
                strftime=real_time.strftime,
                gmtime=real_time.gmtime,
            ),
        )

        try:
            reset_mod.monitor_loop(
                host="localhost",
                port=4455,
                source_name="StudioCompositor",
                poll_interval=0.01,
                stall_threshold=60.0,
                reset_cooldown=60.0,
                metrics_path=prom_path,
                producer_service="hapax-darkplaces-v4l2.service",
                producer_restart_after_obs_resets=1,
                producer_restart_cooldown=300.0,
                producer_restart_timeout=30.0,
            )
        finally:
            monkeypatch.setattr(reset_mod, "_shutdown", False)

        status = json.loads(status_path.read_text())
        assert status["state"] == "reconnected"
        assert status["reset_count"] == 2
        assert status["producer_restarts"] == 1
        assert status["last_producer_restart_at"] is not None
        assert restart_calls == [("hapax-darkplaces-v4l2.service", 30.0)]
        assert client.set_scene_item_enabled.call_count == 4
        assert "hapax_obs_v4l2_source_producer_restarts_total 1" in prom_path.read_text()

    def test_zero_stall_resets_escalates_to_producer_restart_immediately(
        self,
        reset_mod: types.ModuleType,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client = MagicMock()
        client.get_source_active.return_value = MagicMock(video_active=True)
        client.get_source_screenshot.return_value = MagicMock(image_data="same-frame")
        client.get_current_program_scene.return_value = MagicMock(scene_name="Scene")
        client.get_scene_item_list.return_value = MagicMock(
            scene_items=[{"sourceName": "StudioCompositor", "sceneItemId": 7}]
        )
        prom_path = tmp_path / "reset.prom"
        status_path = tmp_path / "status.json"
        restart_calls: list[tuple[str, float]] = []
        sleep_calls = 0
        real_time = reset_mod.time
        monotonic_values = iter([100.0, 170.0])
        monkeypatch.setattr(reset_mod, "_connect", lambda _host, _port: client)
        monkeypatch.setattr(reset_mod, "_send_ntfy", lambda _reason: None)
        monkeypatch.setattr(reset_mod, "STATUS_PATH", status_path)
        monkeypatch.setattr(reset_mod, "STATUS_DIR", tmp_path)
        monkeypatch.setattr(reset_mod, "_shutdown", False)

        def fake_monotonic() -> float:
            return next(monotonic_values)

        def fake_toggle(toggle_client, scene_name: str, item_id: int) -> bool:
            toggle_client.set_scene_item_enabled(
                scene_name=scene_name,
                scene_item_id=item_id,
                scene_item_enabled=False,
            )
            toggle_client.set_scene_item_enabled(
                scene_name=scene_name,
                scene_item_id=item_id,
                scene_item_enabled=True,
            )
            return True

        def fake_restart(service_name: str, *, timeout: float) -> bool:
            restart_calls.append((service_name, timeout))
            return True

        monkeypatch.setattr(reset_mod, "_toggle_visibility", fake_toggle)
        monkeypatch.setattr(reset_mod, "_restart_producer_service", fake_restart)

        def stop_after_two_loop_sleeps(_seconds: float) -> None:
            nonlocal sleep_calls
            sleep_calls += 1
            if sleep_calls >= 2:
                monkeypatch.setattr(reset_mod, "_shutdown", True)

        monkeypatch.setattr(
            reset_mod,
            "time",
            types.SimpleNamespace(
                monotonic=fake_monotonic,
                sleep=stop_after_two_loop_sleeps,
                strftime=real_time.strftime,
                gmtime=real_time.gmtime,
            ),
        )

        try:
            reset_mod.monitor_loop(
                host="localhost",
                port=4455,
                source_name="StudioCompositor",
                poll_interval=0.01,
                stall_threshold=60.0,
                reset_cooldown=60.0,
                metrics_path=prom_path,
                producer_service="hapax-darkplaces-v4l2.service",
                producer_restart_after_obs_resets=0,
                producer_restart_cooldown=300.0,
                producer_restart_timeout=30.0,
            )
        finally:
            monkeypatch.setattr(reset_mod, "_shutdown", False)

        status = json.loads(status_path.read_text())
        assert status["state"] == "reconnected"
        assert status["reset_count"] == 1
        assert status["producer_restarts"] == 1
        assert restart_calls == [("hapax-darkplaces-v4l2.service", 30.0)]
        assert client.set_scene_item_enabled.call_count == 2

    def test_static_screenshot_can_be_ignored_when_log_errors_are_authority(
        self,
        reset_mod: types.ModuleType,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client = MagicMock()
        client.get_source_active.return_value = MagicMock(video_active=True)
        client.get_source_screenshot.return_value = MagicMock(image_data="same-frame")
        prom_path = tmp_path / "reset.prom"
        status_path = tmp_path / "status.json"
        sleep_calls = 0
        real_time = reset_mod.time
        monotonic_values = iter([100.0, 170.0])
        monkeypatch.setattr(reset_mod, "_connect", lambda _host, _port: client)
        monkeypatch.setattr(reset_mod, "STATUS_PATH", status_path)
        monkeypatch.setattr(reset_mod, "STATUS_DIR", tmp_path)
        monkeypatch.setattr(reset_mod, "_shutdown", False)

        def fake_monotonic() -> float:
            return next(monotonic_values)

        def stop_after_two_loop_sleeps(_seconds: float) -> None:
            nonlocal sleep_calls
            sleep_calls += 1
            if sleep_calls >= 2:
                monkeypatch.setattr(reset_mod, "_shutdown", True)

        monkeypatch.setattr(
            reset_mod,
            "time",
            types.SimpleNamespace(
                monotonic=fake_monotonic,
                sleep=stop_after_two_loop_sleeps,
                strftime=real_time.strftime,
                gmtime=real_time.gmtime,
            ),
        )

        try:
            reset_mod.monitor_loop(
                host="localhost",
                port=4455,
                source_name="Video Capture Device (V4L2)",
                poll_interval=0.01,
                stall_threshold=60.0,
                reset_cooldown=60.0,
                metrics_path=prom_path,
                ignore_static_screenshot_stalls=True,
            )
        finally:
            monkeypatch.setattr(reset_mod, "_shutdown", False)

        status = json.loads(status_path.read_text())
        assert status["state"] == "healthy"
        assert status["reset_count"] == 0
        assert status["reason"] == "static_screenshot_ignored"
        assert status["stall_seconds"] == 70.0
        client.set_scene_item_enabled.assert_not_called()

    def test_static_screenshot_ignore_cap_resets_without_log_errors(
        self,
        reset_mod: types.ModuleType,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client = MagicMock()
        client.get_source_active.return_value = MagicMock(video_active=True)
        client.get_source_screenshot.return_value = MagicMock(image_data="same-frame")
        client.get_current_program_scene.return_value = MagicMock(scene_name="Scene")
        client.get_scene_item_list.return_value = MagicMock(
            scene_items=[{"sourceName": "Video Capture Device (V4L2)", "sceneItemId": 366}]
        )
        prom_path = tmp_path / "reset.prom"
        status_path = tmp_path / "status.json"
        sleep_calls = 0
        real_time = reset_mod.time
        monotonic_values = iter([100.0, 176.0])
        monkeypatch.setattr(reset_mod, "_connect", lambda _host, _port: client)
        monkeypatch.setattr(reset_mod, "_send_ntfy", lambda _reason: None)
        monkeypatch.setattr(reset_mod, "STATUS_PATH", status_path)
        monkeypatch.setattr(reset_mod, "STATUS_DIR", tmp_path)
        monkeypatch.setattr(reset_mod, "_shutdown", False)

        def fake_monotonic() -> float:
            return next(monotonic_values)

        def fake_toggle(toggle_client, scene_name: str, item_id: int) -> bool:
            toggle_client.set_scene_item_enabled(
                scene_name=scene_name,
                scene_item_id=item_id,
                scene_item_enabled=False,
            )
            toggle_client.set_scene_item_enabled(
                scene_name=scene_name,
                scene_item_id=item_id,
                scene_item_enabled=True,
            )
            return True

        monkeypatch.setattr(reset_mod, "_toggle_visibility", fake_toggle)

        def stop_after_two_loop_sleeps(_seconds: float) -> None:
            nonlocal sleep_calls
            sleep_calls += 1
            if sleep_calls >= 2:
                monkeypatch.setattr(reset_mod, "_shutdown", True)

        monkeypatch.setattr(
            reset_mod,
            "time",
            types.SimpleNamespace(
                monotonic=fake_monotonic,
                sleep=stop_after_two_loop_sleeps,
                strftime=real_time.strftime,
                gmtime=real_time.gmtime,
            ),
        )

        try:
            reset_mod.monitor_loop(
                host="localhost",
                port=4455,
                source_name="Video Capture Device (V4L2)",
                poll_interval=0.01,
                stall_threshold=60.0,
                reset_cooldown=60.0,
                metrics_path=prom_path,
                ignore_static_screenshot_stalls=True,
                max_static_ignore_seconds=75.0,
            )
        finally:
            monkeypatch.setattr(reset_mod, "_shutdown", False)

        status = json.loads(status_path.read_text())
        assert status["state"] == "reconnected"
        assert status["reason"] == "static_screenshot_ignore_cap_exceeded:75s"
        assert status["reset_count"] == 1
        calls = client.set_scene_item_enabled.call_args_list
        assert [call.kwargs["scene_item_enabled"] for call in calls] == [False, True]

    def test_static_screenshot_ignore_cap_is_hard_boundary_below_stall_threshold(
        self,
        reset_mod: types.ModuleType,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client = MagicMock()
        client.get_source_active.return_value = MagicMock(video_active=True)
        client.get_source_screenshot.return_value = MagicMock(image_data="same-frame")
        client.get_current_program_scene.return_value = MagicMock(scene_name="Scene")
        client.get_scene_item_list.return_value = MagicMock(
            scene_items=[{"sourceName": "Video Capture Device (V4L2)", "sceneItemId": 366}]
        )
        prom_path = tmp_path / "reset.prom"
        status_path = tmp_path / "status.json"
        sleep_calls = 0
        real_time = reset_mod.time
        monotonic_values = iter([100.0, 130.0])
        monkeypatch.setattr(reset_mod, "_connect", lambda _host, _port: client)
        monkeypatch.setattr(reset_mod, "_send_ntfy", lambda _reason: None)
        monkeypatch.setattr(reset_mod, "STATUS_PATH", status_path)
        monkeypatch.setattr(reset_mod, "STATUS_DIR", tmp_path)
        monkeypatch.setattr(reset_mod, "_shutdown", False)

        def fake_monotonic() -> float:
            return next(monotonic_values)

        def fake_toggle(toggle_client, scene_name: str, item_id: int) -> bool:
            toggle_client.set_scene_item_enabled(
                scene_name=scene_name,
                scene_item_id=item_id,
                scene_item_enabled=False,
            )
            toggle_client.set_scene_item_enabled(
                scene_name=scene_name,
                scene_item_id=item_id,
                scene_item_enabled=True,
            )
            return True

        monkeypatch.setattr(reset_mod, "_toggle_visibility", fake_toggle)

        def stop_after_two_loop_sleeps(_seconds: float) -> None:
            nonlocal sleep_calls
            sleep_calls += 1
            if sleep_calls >= 2:
                monkeypatch.setattr(reset_mod, "_shutdown", True)

        monkeypatch.setattr(
            reset_mod,
            "time",
            types.SimpleNamespace(
                monotonic=fake_monotonic,
                sleep=stop_after_two_loop_sleeps,
                strftime=real_time.strftime,
                gmtime=real_time.gmtime,
            ),
        )

        try:
            reset_mod.monitor_loop(
                host="localhost",
                port=4455,
                source_name="Video Capture Device (V4L2)",
                poll_interval=0.01,
                stall_threshold=60.0,
                reset_cooldown=60.0,
                metrics_path=prom_path,
                ignore_static_screenshot_stalls=True,
                max_static_ignore_seconds=15.0,
            )
        finally:
            monkeypatch.setattr(reset_mod, "_shutdown", False)

        status = json.loads(status_path.read_text())
        assert status["state"] == "reconnected"
        assert status["reason"] == "static_screenshot_ignore_cap_exceeded:15s"
        assert status["reset_count"] == 1
        calls = client.set_scene_item_enabled.call_args_list
        assert [call.kwargs["scene_item_enabled"] for call in calls] == [False, True]

    def test_repeated_self_recovered_log_timeouts_reset_across_polls(
        self,
        reset_mod: types.ModuleType,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client = MagicMock()
        client.get_source_active.return_value = MagicMock(video_active=True)
        client.get_source_screenshot.return_value = MagicMock(image_data="same-frame")
        client.get_current_program_scene.return_value = MagicMock(scene_name="Scene")
        client.get_scene_item_list.return_value = MagicMock(
            scene_items=[{"sourceName": "Video Capture Device (V4L2)", "sceneItemId": 366}]
        )
        prom_path = tmp_path / "reset.prom"
        status_path = tmp_path / "status.json"
        sleep_calls = 0
        real_time = reset_mod.time
        monotonic_values = iter([100.0, 115.0])
        cursor = reset_mod.ObsLogCursor()
        log_reasons = iter(
            [
                "obs_log_v4l2_timeout_self_recovered:/dev/video50",
                "obs_log_v4l2_timeout_self_recovered:/dev/video50",
            ]
        )
        monkeypatch.setattr(reset_mod, "_connect", lambda _host, _port: client)
        monkeypatch.setattr(reset_mod, "_send_ntfy", lambda _reason: None)
        monkeypatch.setattr(reset_mod, "STATUS_PATH", status_path)
        monkeypatch.setattr(reset_mod, "STATUS_DIR", tmp_path)
        monkeypatch.setattr(reset_mod, "_shutdown", False)

        def fake_monotonic() -> float:
            return next(monotonic_values)

        def fake_scan(scan_cursor, *, log_dir: Path, device_id: str):
            assert log_dir == tmp_path
            assert device_id == "/dev/video50"
            return cursor if scan_cursor is None else scan_cursor, next(log_reasons)

        def fake_toggle(toggle_client, scene_name: str, item_id: int) -> bool:
            toggle_client.set_scene_item_enabled(
                scene_name=scene_name,
                scene_item_id=item_id,
                scene_item_enabled=False,
            )
            toggle_client.set_scene_item_enabled(
                scene_name=scene_name,
                scene_item_id=item_id,
                scene_item_enabled=True,
            )
            return True

        monkeypatch.setattr(reset_mod, "_scan_obs_log_v4l2_errors", fake_scan)
        monkeypatch.setattr(reset_mod, "_toggle_visibility", fake_toggle)

        def stop_after_two_loop_sleeps(_seconds: float) -> None:
            nonlocal sleep_calls
            sleep_calls += 1
            if sleep_calls >= 2:
                monkeypatch.setattr(reset_mod, "_shutdown", True)

        monkeypatch.setattr(
            reset_mod,
            "time",
            types.SimpleNamespace(
                monotonic=fake_monotonic,
                sleep=stop_after_two_loop_sleeps,
                strftime=real_time.strftime,
                gmtime=real_time.gmtime,
            ),
        )

        try:
            reset_mod.monitor_loop(
                host="localhost",
                port=4455,
                source_name="Video Capture Device (V4L2)",
                poll_interval=0.01,
                stall_threshold=60.0,
                reset_cooldown=60.0,
                metrics_path=prom_path,
                obs_log_dir=tmp_path,
                obs_log_device_id="/dev/video50",
                ignore_static_screenshot_stalls=True,
            )
        finally:
            monkeypatch.setattr(reset_mod, "_shutdown", False)

        status = json.loads(status_path.read_text())
        assert status["state"] == "reconnected"
        assert status["reason"] == "obs_log_v4l2_timeout:/dev/video50"
        assert status["reset_count"] == 1
        calls = client.set_scene_item_enabled.call_args_list
        assert [call.kwargs["scene_item_enabled"] for call in calls] == [False, True]
