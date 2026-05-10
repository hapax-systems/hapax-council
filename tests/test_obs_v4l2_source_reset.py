"""Tests for hapax-obs-v4l2-source-reset monitor logic."""

from __future__ import annotations

import importlib
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


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


class TestMonitorLoop:
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
        monotonic_values = iter([100.0, 110.0])
        monkeypatch.setattr(reset_mod, "_connect", lambda _host, _port: client)
        monkeypatch.setattr(reset_mod, "_send_ntfy", lambda _reason: None)
        monkeypatch.setattr(reset_mod, "STATUS_PATH", status_path)
        monkeypatch.setattr(reset_mod, "STATUS_DIR", tmp_path)
        monkeypatch.setattr(reset_mod, "_shutdown", False)
        monkeypatch.setattr(reset_mod.time, "monotonic", lambda: next(monotonic_values))

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

        monkeypatch.setattr(reset_mod.time, "sleep", stop_after_two_loop_sleeps)

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
