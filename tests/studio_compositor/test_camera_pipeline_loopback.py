"""Tests for per-camera v4l2loopback sidecar in CameraPipeline."""

from __future__ import annotations

from unittest.mock import MagicMock

from agents.studio_compositor.camera_pipeline import CameraPipeline
from agents.studio_compositor.models import CameraSpec


def _make_spec(*, loopback_device: str | None = None) -> CameraSpec:
    return CameraSpec(
        role="test-brio",
        device="/dev/video1",
        width=1280,
        height=720,
        input_format="mjpeg",
        loopback_device=loopback_device,
    )


def test_camera_spec_loopback_device_defaults_none() -> None:
    spec = CameraSpec(role="cam", device="/dev/video0")
    assert spec.loopback_device is None


def test_camera_spec_loopback_device_roundtrips() -> None:
    spec = CameraSpec(role="cam", device="/dev/video0", loopback_device="/dev/video70")
    assert spec.loopback_device == "/dev/video70"


class _FakeGst:
    """Minimal mock of GStreamer types needed for CameraPipeline.build()."""

    class PadProbeType:
        BUFFER = 0x10

    class PadLinkReturn:
        OK = 0

    class StateChangeReturn:
        SUCCESS = 1
        FAILURE = 0

    class State:
        NULL = 0
        PLAYING = 4

    class MessageType:
        ERROR = 1 << 1
        WARNING = 1 << 2

    class Pipeline:
        def __init__(self, name: str) -> None:
            self.name = name
            self._elements: list = []

        def add(self, el: MagicMock) -> None:
            self._elements.append(el)

        def get_bus(self) -> MagicMock:
            bus = MagicMock()
            bus.connect.return_value = 1
            return bus

    @staticmethod
    def ElementFactory_make(factory_name: str, element_name: str) -> MagicMock:
        el = MagicMock()
        el.get_name.return_value = element_name
        pad = MagicMock()
        pad.link.return_value = 0  # Gst.PadLinkReturn.OK
        pad.add_probe.return_value = 0
        el.get_static_pad.return_value = pad
        el.request_pad_simple.return_value = pad
        el.link.return_value = True
        return el

    @classmethod
    def make_gst(cls) -> MagicMock:
        gst = MagicMock()
        gst.Pipeline.new = cls.Pipeline
        gst.ElementFactory.make = cls.ElementFactory_make
        gst.Caps.from_string = MagicMock()
        gst.PadProbeType = cls.PadProbeType
        gst.PadLinkReturn = cls.PadLinkReturn
        gst.StateChangeReturn = cls.StateChangeReturn
        gst.State = cls.State
        gst.MessageType = cls.MessageType
        return gst


def _build_with_tracking(spec: CameraSpec) -> dict[str, MagicMock]:
    gst = _FakeGst.make_gst()
    created: dict[str, MagicMock] = {}
    original_make = _FakeGst.ElementFactory_make

    def tracking_make(factory_name: str, element_name: str) -> MagicMock:
        el = original_make(factory_name, element_name)
        created[element_name] = el
        created.setdefault(f"__factory__{factory_name}", [])
        created[f"__factory__{factory_name}"].append(el)
        return el

    gst.ElementFactory.make = tracking_make
    pipeline = CameraPipeline(spec, gst=gst, fps=30)
    pipeline.build()
    return created


def test_build_graph_without_loopback_has_no_tee() -> None:
    created = _build_with_tracking(_make_spec(loopback_device=None))
    assert "__factory__tee" not in created
    assert "__factory__v4l2sink" not in created


def test_build_graph_with_loopback_adds_tee_and_v4l2sink() -> None:
    created = _build_with_tracking(_make_spec(loopback_device="/dev/video70"))
    assert "__factory__tee" in created
    assert "__factory__v4l2sink" in created
    assert "__factory__queue" in created
    assert len(created.get("__factory__videoconvert", [])) >= 2


def test_build_graph_with_loopback_sets_v4l2sink_device() -> None:
    created = _build_with_tracking(_make_spec(loopback_device="/dev/video70"))
    v4l2sink_elements = created.get("__factory__v4l2sink", [])
    assert len(v4l2sink_elements) == 1
    v4l2sink_el = v4l2sink_elements[0]
    v4l2sink_el.set_property.assert_any_call("device", "/dev/video70")


def test_build_graph_with_loopback_queue_is_leaky() -> None:
    created = _build_with_tracking(_make_spec(loopback_device="/dev/video70"))
    queue_el = next(
        (el for name, el in created.items() if name.startswith("lb_queue")),
        None,
    )
    assert queue_el is not None
    queue_el.set_property.assert_any_call("leaky", 2)
    queue_el.set_property.assert_any_call("max-size-buffers", 2)


def test_bus_message_loopback_error_is_non_fatal() -> None:
    spec = _make_spec(loopback_device="/dev/video70")
    gst = _FakeGst.make_gst()
    on_error = MagicMock()
    pipeline = CameraPipeline(spec, gst=gst, fps=30, on_error=on_error)

    msg = MagicMock()
    msg.type = gst.MessageType.ERROR
    msg.src.get_name.return_value = "lb_v4l2sink_test_brio"
    err = MagicMock()
    err.message = "Device busy"
    msg.parse_error.return_value = (err, "debug info")

    result = pipeline._on_bus_message(MagicMock(), msg)

    assert result is True
    on_error.assert_not_called()


def test_bus_message_non_loopback_error_calls_on_error() -> None:
    spec = _make_spec(loopback_device="/dev/video70")
    gst = _FakeGst.make_gst()
    on_error = MagicMock()
    pipeline = CameraPipeline(spec, gst=gst, fps=30, on_error=on_error)

    msg = MagicMock()
    msg.type = gst.MessageType.ERROR
    msg.src.get_name.return_value = "v4l2src_test_brio"
    err = MagicMock()
    err.message = "Device disconnected"
    msg.parse_error.return_value = (err, "debug info")

    pipeline._on_bus_message(MagicMock(), msg)

    on_error.assert_called_once()
