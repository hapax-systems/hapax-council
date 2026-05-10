from __future__ import annotations

from agents.studio_compositor.cuda_caps import (
    cuda_input_caps_string,
    cuda_output_caps_string,
)
from agents.studio_compositor.pipeline import _make_cudacompositor, _pin_black_background


class _Element:
    def __init__(self) -> None:
        self.props: dict[str, object] = {}

    def set_property(self, name: str, value: object) -> None:
        self.props[name] = value


class _NoBackgroundElement:
    def set_property(self, name: str, value: object) -> None:
        raise AttributeError(name)


class _FakeGst:
    launched: str | None = None

    @classmethod
    def parse_launch(cls, description: str) -> _Element:
        cls.launched = description
        return _Element()


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
    _FakeGst.launched = None

    element = _make_cudacompositor(_FakeGst)

    assert element is not None
    assert _FakeGst.launched == "cudacompositor name=compositor force-live=true"
