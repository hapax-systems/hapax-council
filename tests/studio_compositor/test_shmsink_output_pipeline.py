"""Tests for the shmsink output pipeline sidecar architecture.

Validates the bridge-enabled gate, pipeline construction, and the
shmsink/v4l2sink selection logic.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from agents.studio_compositor.shmsink_output_pipeline import (
    BRIDGE_ENABLED_ENV,
    DEFAULT_SOCKET,
    V4L2_OUTPUT_DISABLED_ENV,
    ShmsinkOutputPipeline,
    is_bridge_enabled,
    is_v4l2_output_disabled,
)
from agents.studio_compositor.v4l2_output_pipeline import V4l2OutputPipeline


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

    def test_v4l2_output_disable_gate_is_independent_and_stronger(self) -> None:
        with patch.dict(
            "os.environ",
            {
                BRIDGE_ENABLED_ENV: "1",
                V4L2_OUTPUT_DISABLED_ENV: "1",
            },
            clear=True,
        ):
            assert is_bridge_enabled()
            assert is_v4l2_output_disabled()


class TestShmsinkPipelineConstruction:
    def _make_gst_mock(self) -> MagicMock:
        gst = MagicMock()
        gst.Pipeline.new.return_value = MagicMock()
        gst.ElementFactory.make.return_value = MagicMock()
        gst.Caps.from_string.return_value = MagicMock()
        gst.PadProbeType.BUFFER = 0x10
        gst.Format.TIME = object()
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

    def test_build_sets_interpipe_live_restart_properties(self) -> None:
        gst = self._make_gst_mock()
        elements = {}

        def make_element(factory: str, name: str) -> MagicMock:
            el = MagicMock()
            elements[factory] = el
            return el

        gst.ElementFactory.make.side_effect = make_element
        pipe = ShmsinkOutputPipeline(gst=gst, width=1280, height=720, fps=30)
        pipe.build()

        src = elements.get("interpipesrc")
        assert src is not None
        src.set_property.assert_any_call("stream-sync", "restart-ts")
        src.set_property.assert_any_call("is-live", True)
        src.set_property.assert_any_call("format", gst.Format.TIME)
        src.set_property.assert_any_call("automatic-eos", False)
        src.set_property.assert_any_call("accept-eos-event", False)

    def test_build_retimestamps_bridge_output_to_target_framerate(self) -> None:
        gst = self._make_gst_mock()
        elements = {}

        def make_element(factory: str, name: str) -> MagicMock:
            el = MagicMock()
            elements[name] = el
            return el

        gst.ElementFactory.make.side_effect = make_element
        pipe = ShmsinkOutputPipeline(gst=gst, width=1280, height=720, fps=30)
        pipe.build()

        rate = elements.get("shm_out_videorate")
        rate_caps = elements.get("shm_out_rate_caps")
        convert = elements.get("shm_out_convert")
        assert rate is not None
        assert rate_caps is not None
        assert convert is not None
        rate.set_property.assert_any_call("skip-to-first", True)
        rate.set_property.assert_any_call("max-closing-segment-duplication-duration", 0)
        gst.Caps.from_string.assert_any_call("video/x-raw,width=1280,height=720,framerate=30/1")
        rate.link.assert_called_with(rate_caps)
        rate_caps.link.assert_called_with(convert)

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

    def test_is_alive_false_before_frames(self) -> None:
        gst = self._make_gst_mock()
        pipe = ShmsinkOutputPipeline(gst=gst, width=1280, height=720, fps=30)
        assert not pipe.is_alive(threshold_s=45.0)

    def test_is_alive_true_after_probe(self) -> None:
        gst = self._make_gst_mock()
        pipe = ShmsinkOutputPipeline(gst=gst, width=1280, height=720, fps=30)
        pipe._buffer_probe(None, None, None)
        assert pipe.is_alive(threshold_s=2.0)


class TestPipelineSelection:
    """Verifies that build_pipeline selects the correct output pipeline type."""

    def _make_compositor_mock(self) -> MagicMock:
        compositor = MagicMock()
        compositor.config.output_device = "/dev/video42"
        compositor.config.output_width = 1280
        compositor.config.output_height = 720
        compositor.config.cameras = []
        compositor.config.hls.enabled = False
        return compositor

    @patch.dict("os.environ", {BRIDGE_ENABLED_ENV: "1"})
    @patch("agents.studio_compositor.shmsink_output_pipeline.ShmsinkOutputPipeline.build")
    @patch(
        "agents.studio_compositor.shmsink_output_pipeline.is_bridge_enabled",
        return_value=True,
    )
    def test_bridge_enabled_creates_shmsink(
        self, _mock_enabled: MagicMock, _mock_build: MagicMock
    ) -> None:
        pipe = ShmsinkOutputPipeline(gst=MagicMock(), width=1280, height=720, fps=30)
        assert isinstance(pipe, ShmsinkOutputPipeline)
        assert not isinstance(pipe, V4l2OutputPipeline)

    def test_bridge_disabled_creates_v4l2(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            assert not is_bridge_enabled()
            pipe = V4l2OutputPipeline(
                gst=MagicMock(),
                device="/dev/video42",
                width=1280,
                height=720,
                fps=30,
            )
            assert isinstance(pipe, V4l2OutputPipeline)


class TestSystemdBridgeActivation:
    """Verifies the systemd unit enables the shmsink bridge path."""

    def test_compositor_service_enables_bridge(self) -> None:
        service = (Path(__file__).parents[2] / "systemd/units/studio-compositor.service").read_text(
            encoding="utf-8"
        )
        assert "HAPAX_V4L2_BRIDGE_ENABLED=1" in service

    def test_compositor_dropin_enables_bridge(self) -> None:
        dropin = (
            Path(__file__).parents[2] / "systemd/units/studio-compositor.service.d/v4l2-bridge.conf"
        ).read_text(encoding="utf-8")
        assert "HAPAX_V4L2_BRIDGE_ENABLED=1" in dropin

    def test_compositor_service_creates_shm_directory(self) -> None:
        service = (Path(__file__).parents[2] / "systemd/units/studio-compositor.service").read_text(
            encoding="utf-8"
        )
        assert "/dev/shm/hapax-compositor" in service
        assert "mkdir -p" in service

    def test_compositor_service_cleans_stale_sockets(self) -> None:
        service = (Path(__file__).parents[2] / "systemd/units/studio-compositor.service").read_text(
            encoding="utf-8"
        )
        assert "v4l2-bridge.sock" in service
        assert "find /dev/shm/hapax-compositor" in service

    def test_bridge_service_binds_to_compositor(self) -> None:
        bridge = (Path(__file__).parents[2] / "systemd/units/hapax-v4l2-bridge.service").read_text(
            encoding="utf-8"
        )
        assert "BindsTo=studio-compositor.service" in bridge

    def test_compositor_wants_bridge_service(self) -> None:
        service = (Path(__file__).parents[2] / "systemd/units/studio-compositor.service").read_text(
            encoding="utf-8"
        )
        assert "hapax-v4l2-bridge.service" in service
