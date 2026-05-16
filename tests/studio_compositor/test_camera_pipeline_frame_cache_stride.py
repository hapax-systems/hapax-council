from agents.studio_compositor.camera_pipeline import CameraPipeline


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
