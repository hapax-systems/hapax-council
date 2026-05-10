from __future__ import annotations

import sys
import threading
from types import SimpleNamespace

from agents.studio_compositor import cameras
from agents.studio_compositor import pipeline as pipeline_module
from agents.studio_compositor.cuda_caps import (
    cuda_input_caps_string,
    cuda_output_caps_string,
)
from agents.studio_compositor.models import CameraSpec, CompositorConfig, HlsConfig, TileRect
from agents.studio_compositor.pipeline import _make_cudacompositor, _pin_black_background


class _Pad:
    def __init__(self, owner: _Element, name: str) -> None:
        self.owner = owner
        self.name = name
        self.props: dict[str, object] = {}
        self.linked_to: _Pad | None = None
        self.probes: list[tuple[object, object]] = []

    def set_property(self, name: str, value: object) -> None:
        self.props[name] = value

    def link(self, other: _Pad) -> str:
        self.linked_to = other
        return _FakeGst.PadLinkReturn.OK

    def add_probe(self, probe_type: object, callback: object, *_args: object) -> int:
        self.probes.append((probe_type, callback))
        return len(self.probes)


class _Element:
    def __init__(self, name: str = "element", factory: str = "test") -> None:
        self.name = name
        self.factory = factory
        self.props: dict[str, object] = {}
        self.links: list[str] = []
        self.static_pads: dict[str, _Pad] = {}
        self.requested_pads: list[_Pad] = []

    def set_property(self, name: str, value: object) -> None:
        self.props[name] = value

    def get_name(self) -> str:
        return self.name

    def link(self, other: _Element) -> bool:
        self.links.append(other.name)
        return True

    def get_static_pad(self, name: str) -> _Pad:
        return self.static_pads.setdefault(name, _Pad(self, name))

    def get_pad_template(self, name: str) -> str:
        return name

    def request_pad(self, template: str, _name: object, _caps: object) -> _Pad:
        pad = _Pad(self, f"{template}_{len(self.requested_pads)}")
        self.requested_pads.append(pad)
        return pad


class _NoBackgroundElement:
    def set_property(self, name: str, value: object) -> None:
        raise AttributeError(name)


class _Caps:
    @staticmethod
    def from_string(description: str) -> str:
        return description


class _ElementFactory:
    created: list[_Element] = []

    @classmethod
    def make(cls, factory: str, name: str) -> _Element:
        element = _Element(name, factory)
        cls.created.append(element)
        return element


class _Pipeline:
    def __init__(self, name: str) -> None:
        self.name = name
        self.elements: list[_Element] = []

    def add(self, element: _Element) -> None:
        self.elements.append(element)


class _PipelineFactory:
    created: list[_Pipeline] = []

    @classmethod
    def new(cls, name: str) -> _Pipeline:
        pipeline = _Pipeline(name)
        cls.created.append(pipeline)
        return pipeline


class _FakeGst:
    launched: str | None = None
    Caps = _Caps
    ElementFactory = _ElementFactory
    Pipeline = _PipelineFactory
    Format = SimpleNamespace(TIME="time")
    PadLinkReturn = SimpleNamespace(OK="ok")
    PadProbeReturn = SimpleNamespace(OK="ok")
    PadProbeType = SimpleNamespace(BUFFER="buffer")

    @classmethod
    def parse_launch(cls, description: str) -> _Element:
        cls.launched = description
        return _Element("compositor", "cudacompositor")


class _ParseLaunchFailsGst(_FakeGst):
    @classmethod
    def parse_launch(cls, description: str) -> _Element:
        cls.launched = description
        raise RuntimeError("force-live unsupported in parse-launch")


class _PipelineManager:
    def __init__(self, **_kwargs: object) -> None:
        pass

    def build(self) -> None:
        pass

    def status_all(self) -> dict[str, str]:
        return {}


class _OutputBin:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    def build(self) -> None:
        pass


def _reset_fake_gst() -> None:
    _FakeGst.launched = None
    _ElementFactory.created = []
    _PipelineFactory.created = []


def _element_named(elements: list[_Element], name: str) -> _Element:
    for element in elements:
        if element.name == name:
            return element
    raise AssertionError(f"missing fake element {name}")


def _patch_build_pipeline_edges(monkeypatch: object) -> None:
    monkeypatch.setattr(pipeline_module, "PipelineManager", _PipelineManager)
    monkeypatch.setattr(pipeline_module, "add_snapshot_branch", lambda *_args: None)
    monkeypatch.setattr(pipeline_module, "add_llm_frame_snapshot_branch", lambda *_args: None)
    monkeypatch.setattr(pipeline_module, "add_smooth_delay_branch", lambda *_args: None)
    monkeypatch.setattr(pipeline_module, "add_hls_branch", lambda *_args: None)
    monkeypatch.setattr(pipeline_module, "_publish_runtime_features", lambda **_kwargs: None)
    monkeypatch.setattr(pipeline_module, "_publish_runtime_feature", lambda *_args: None)
    monkeypatch.setitem(
        sys.modules,
        "agents.studio_compositor.fx_chain",
        SimpleNamespace(build_inline_fx_chain=lambda *_args: True),
    )
    monkeypatch.setitem(
        sys.modules,
        "agents.studio_compositor.rtmp_output",
        SimpleNamespace(RtmpOutputBin=_OutputBin, MobileRtmpOutputBin=_OutputBin),
    )
    monkeypatch.setitem(
        sys.modules,
        "agents.studio_compositor.v4l2_output_pipeline",
        SimpleNamespace(V4l2OutputPipeline=_OutputBin),
    )
    monkeypatch.setenv("HAPAX_COMPOSITOR_DISABLE_V4L2_OUTPUT", "1")


def _fake_compositor_config(*, hls_enabled: bool = False) -> CompositorConfig:
    return CompositorConfig(
        cameras=[],
        output_width=1280,
        output_height=720,
        framerate=30,
        hls=HlsConfig(enabled=hls_enabled),
    )


def _fake_compositor() -> SimpleNamespace:
    return SimpleNamespace(
        _Gst=_FakeGst,
        _GLib=object(),
        config=_fake_compositor_config(),
        _element_to_role={},
        _camera_status={},
        _camera_status_lock=threading.RLock(),
        _on_shmsink_frame_pushed=lambda: None,
        _on_v4l2_frame_pushed=lambda: None,
    )


def test_pin_black_background_sets_compositor_fill() -> None:
    element = _Element()

    _pin_black_background(element)

    assert element.props["background"] == 1


def test_pin_black_background_is_tolerant_of_elements_without_property() -> None:
    _pin_black_background(_NoBackgroundElement())


def test_cuda_caps_pin_memory_format_and_framerate() -> None:
    assert cuda_input_caps_string(640, 360, 30) == (
        "video/x-raw(memory:CUDAMemory),format=NV12,width=640,height=360,framerate=30/1"
    )
    assert cuda_output_caps_string(1920, 1080, 30) == (
        "video/x-raw(memory:CUDAMemory),format=NV12,width=1920,height=1080,framerate=30/1"
    )


def test_make_cudacompositor_constructs_force_live() -> None:
    _reset_fake_gst()

    element = _make_cudacompositor(_FakeGst)

    assert element is not None
    assert _FakeGst.launched == "cudacompositor name=compositor force-live=true"


def test_make_cudacompositor_fallback_still_requests_force_live() -> None:
    _reset_fake_gst()

    element = _make_cudacompositor(_ParseLaunchFailsGst)

    assert element is not None
    assert _ParseLaunchFailsGst.launched == "cudacompositor name=compositor force-live=true"
    assert element.props["force-live"] is True


def test_cuda_camera_branch_pins_cuda_memory_caps(monkeypatch: object) -> None:
    _reset_fake_gst()
    monkeypatch.setattr(cameras, "add_camera_snapshot_branch", lambda *_args: None)
    compositor = SimpleNamespace(
        _Gst=_FakeGst,
        _use_cuda=True,
        _element_to_role={},
        config=SimpleNamespace(recording=SimpleNamespace(enabled=False)),
    )
    pipeline = _Pipeline("test")
    comp_element = _Element("compositor", "cudacompositor")

    cameras.add_camera_branch(
        compositor,
        pipeline,
        comp_element,
        CameraSpec(role="operator", device="/dev/null", width=1280, height=720),
        TileRect(x=10, y=20, w=640, h=360),
        30,
    )

    scale_caps = _element_named(_ElementFactory.created, "scalecaps_operator")
    assert scale_caps.props["caps"] == (
        "video/x-raw(memory:CUDAMemory),format=NV12,width=640,height=360,framerate=30/1"
    )
    assert _element_named(_ElementFactory.created, "upload_operator").factory == "cudaupload"
    assert _element_named(_ElementFactory.created, "cudaconv_operator").factory == "cudaconvert"
    assert _element_named(_ElementFactory.created, "scale_operator").factory == "cudascale"
    assert comp_element.requested_pads[0].props == {
        "xpos": 10,
        "ypos": 20,
        "width": 640,
        "height": 360,
    }


def test_build_pipeline_caps_cuda_output_before_cudadownload(monkeypatch: object) -> None:
    _reset_fake_gst()
    _patch_build_pipeline_edges(monkeypatch)
    monkeypatch.delenv("HAPAX_COMPOSITOR_FORCE_CPU", raising=False)

    built = pipeline_module.build_pipeline(_fake_compositor())

    compositor = _element_named(built.elements, "compositor")
    cuda_output_caps = _element_named(built.elements, "cuda-output-caps")
    download = _element_named(built.elements, "download")
    assert compositor.links == ["cuda-output-caps"]
    assert cuda_output_caps.links == ["download"]
    assert download.links == ["convert-bgra"]
    assert cuda_output_caps.props["caps"] == (
        "video/x-raw(memory:CUDAMemory),format=NV12,width=1280,height=720,framerate=30/1"
    )


def test_build_pipeline_force_cpu_skips_cuda_canary_path(monkeypatch: object) -> None:
    _reset_fake_gst()
    _patch_build_pipeline_edges(monkeypatch)
    monkeypatch.setenv("HAPAX_COMPOSITOR_FORCE_CPU", "1")

    compositor = _fake_compositor()
    built = pipeline_module.build_pipeline(compositor)

    names = {element.name for element in built.elements}
    assert compositor._use_cuda is False
    assert _FakeGst.launched is None
    assert "cuda-output-caps" not in names
    assert "download" not in names


def test_build_pipeline_isolates_v4l2_output_tee_branch_with_queue(
    monkeypatch: object,
) -> None:
    _reset_fake_gst()
    _patch_build_pipeline_edges(monkeypatch)
    monkeypatch.setenv("HAPAX_COMPOSITOR_DISABLE_V4L2_OUTPUT", "0")
    monkeypatch.setenv("HAPAX_V4L2_BRIDGE_ENABLED", "0")
    monkeypatch.setenv("HAPAX_COMPOSITOR_FORCE_CPU", "1")

    built = pipeline_module.build_pipeline(_fake_compositor())

    output_tee = _element_named(built.elements, "output-tee")
    v4l2_queue = _element_named(built.elements, "queue-v4l2-egress")
    v4l2_interpipe = _element_named(built.elements, "compositor_v4l2_out")
    assert v4l2_queue.props["leaky"] == 2
    assert v4l2_queue.links == ["compositor_v4l2_out"]
    assert output_tee.requested_pads[0].linked_to is v4l2_queue.static_pads["sink"]
    assert v4l2_queue.static_pads["sink"].probes
    assert v4l2_interpipe.static_pads["sink"].probes
