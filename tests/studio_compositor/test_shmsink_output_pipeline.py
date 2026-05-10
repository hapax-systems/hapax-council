"""Tests for the shmsink output pipeline sidecar architecture.

Validates the bridge-enabled gate, pipeline construction, and the
shmsink/v4l2sink selection logic.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agents.studio_compositor.shmsink_output_pipeline import (
    BRIDGE_ENABLED_ENV,
    DEFAULT_SOCKET,
    ShmsinkOutputPipeline,
    is_bridge_enabled,
)


class TestBridgeEnabledGate:
    def test_disabled_by_default(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            assert not is_bridge_enabled()

    def test_enabled_when_set(self) -> None:
        with patch.dict("os.environ", {BRIDGE_ENABLED_ENV: "1"}):
            assert is_bridge_enabled()

    def test_disabled_when_empty(self) -> None:
        with patch.dict("os.environ", {BRIDGE_ENABLED_ENV: ""}):
            assert not is_bridge_enabled()

    def test_disabled_when_zero(self) -> None:
        with patch.dict("os.environ", {BRIDGE_ENABLED_ENV: "0"}):
            assert not is_bridge_enabled()


class TestShmsinkPipelineConstruction:
    def _make_gst_mock(self) -> MagicMock:
        gst = MagicMock()
        gst.Pipeline.new.return_value = MagicMock()
        gst.ElementFactory.make.return_value = MagicMock()
        gst.Caps.from_string.return_value = MagicMock()
        gst.PadProbeType.BUFFER = 0x10
        gst.State.PLAYING = 4
        gst.State.NULL = 1
        gst.StateChangeReturn.FAILURE = 0
        gst.StateChangeReturn.SUCCESS = 1
        gst.PadProbeReturn.OK = 0
        return gst

    def test_build_creates_pipeline(self) -> None:
        gst = self._make_gst_mock()
        pipe = ShmsinkOutputPipeline(gst=gst, width=1280, height=720, fps=30)
        pipe.build()
        gst.Pipeline.new.assert_called_once_with("shmsink_output_pipeline")

    def test_build_sets_shmsink_properties(self) -> None:
        gst = self._make_gst_mock()
        elements = {}

        def make_element(factory: str, name: str) -> MagicMock:
            el = MagicMock()
            elements[factory] = el
            return el

        gst.ElementFactory.make.side_effect = make_element
        pipe = ShmsinkOutputPipeline(
            gst=gst, width=1280, height=720, fps=30, socket_path="/tmp/test.sock"
        )
        pipe.build()

        shmsink = elements.get("shmsink")
        assert shmsink is not None
        shmsink.set_property.assert_any_call("socket-path", "/tmp/test.sock")
        shmsink.set_property.assert_any_call("wait-for-connection", False)
        shmsink.set_property.assert_any_call("sync", False)

    def test_default_socket_path(self) -> None:
        assert DEFAULT_SOCKET == "/dev/shm/hapax-compositor/v4l2-bridge.sock"

    def test_shm_size_calculation(self) -> None:
        gst = self._make_gst_mock()
        elements = {}

        def make_element(factory: str, name: str) -> MagicMock:
            el = MagicMock()
            elements[factory] = el
            return el

        gst.ElementFactory.make.side_effect = make_element
        pipe = ShmsinkOutputPipeline(gst=gst, width=1280, height=720, fps=30)
        pipe.build()

        shmsink = elements.get("shmsink")
        frame_bytes = 1280 * 720 * 3 // 2
        expected_shm = frame_bytes * 8
        shmsink.set_property.assert_any_call("shm-size", expected_shm)

    def test_start_sets_playing(self) -> None:
        gst = self._make_gst_mock()
        pipeline_mock = MagicMock()
        pipeline_mock.set_state.return_value = gst.StateChangeReturn.SUCCESS
        gst.Pipeline.new.return_value = pipeline_mock

        pipe = ShmsinkOutputPipeline(gst=gst, width=1280, height=720, fps=30)
        pipe.build()
        assert pipe.start()
        pipeline_mock.set_state.assert_called_with(gst.State.PLAYING)

    def test_stop_sets_null(self) -> None:
        gst = self._make_gst_mock()
        pipeline_mock = MagicMock()
        pipeline_mock.set_state.return_value = gst.StateChangeReturn.SUCCESS
        gst.Pipeline.new.return_value = pipeline_mock

        pipe = ShmsinkOutputPipeline(gst=gst, width=1280, height=720, fps=30)
        pipe.build()
        pipe.start()
        pipe.stop()
        pipeline_mock.set_state.assert_called_with(gst.State.NULL)

    def test_last_frame_age_infinite_before_frames(self) -> None:
        gst = self._make_gst_mock()
        pipe = ShmsinkOutputPipeline(gst=gst, width=1280, height=720, fps=30)
        assert pipe.last_frame_age_seconds == float("inf")
