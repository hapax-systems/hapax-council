from agents.studio_compositor.camera_pipeline import CameraPipeline
from agents.studio_compositor.models import CameraSpec


def test_frame_cache_sample_stride_defaults_to_full_source_cadence(monkeypatch) -> None:
    monkeypatch.delenv("HAPAX_CAMERA_FRAME_CACHE_TARGET_FPS", raising=False)
    assert CameraPipeline._frame_cache_sample_stride_for_fps(30) == 1
    assert CameraPipeline._frame_cache_sample_stride_for_fps(15) == 1
    assert CameraPipeline._frame_cache_sample_stride_for_fps(10) == 1
    assert CameraPipeline._frame_cache_sample_stride_for_fps(1) == 1


def test_frame_cache_sample_stride_can_be_lowered_when_measured(monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_CAMERA_FRAME_CACHE_TARGET_FPS", "10")
    assert CameraPipeline._frame_cache_sample_stride_for_fps(30) == 3
    assert CameraPipeline._frame_cache_sample_stride_for_fps(15) == 2
    assert CameraPipeline._frame_cache_sample_stride_for_fps(10) == 1


def test_http_jpeg_camera_fps_defaults_to_compositor_cadence(monkeypatch) -> None:
    monkeypatch.delenv("HAPAX_HTTP_JPEG_CAMERA_FPS", raising=False)
    pipeline = object.__new__(CameraPipeline)
    pipeline._fps = 30

    assert pipeline._effective_http_fps() == 30


def test_camera_pipeline_honors_spec_framerate_before_http_env_default(
    monkeypatch,
) -> None:
    monkeypatch.delenv("HAPAX_HTTP_JPEG_CAMERA_FPS", raising=False)
    spec = CameraSpec(
        role="pi-noir-ir",
        device="http://example.invalid/frame.jpg",
        input_format="http_jpeg",
        framerate=5,
    )

    pipeline = CameraPipeline(spec, gst=object(), fps=30)

    assert pipeline._fps == 5
    assert pipeline._effective_http_fps() == 5


def test_camera_pipeline_clamps_spec_framerate_to_compositor_output() -> None:
    spec = CameraSpec(role="overfast", device="/dev/video0", framerate=60)

    pipeline = CameraPipeline(spec, gst=object(), fps=30)

    assert pipeline._fps == 30
