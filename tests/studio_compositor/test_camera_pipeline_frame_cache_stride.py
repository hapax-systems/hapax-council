from agents.studio_compositor.camera_pipeline import CameraPipeline
from agents.studio_compositor.models import CameraSpec


def test_frame_cache_target_defaults_to_full_source_cadence_outside_3d(monkeypatch) -> None:
    monkeypatch.delenv("HAPAX_3D_COMPOSITOR", raising=False)
    monkeypatch.delenv("HAPAX_CAMERA_FRAME_CACHE_TARGET_FPS", raising=False)
    assert CameraPipeline._frame_cache_target_fps_for_source(30) == 30
    assert CameraPipeline._frame_cache_target_fps_for_source(15) == 15
    assert CameraPipeline._frame_cache_target_fps_for_source(10) == 10
    assert CameraPipeline._frame_cache_target_fps_for_source(1) == 1


def test_frame_cache_target_defaults_to_source_publish_cadence_in_3d(monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_3D_COMPOSITOR", "1")
    monkeypatch.delenv("HAPAX_CAMERA_FRAME_CACHE_TARGET_FPS", raising=False)
    monkeypatch.setenv("HAPAX_CAMERA_SOURCE_PUBLISH_FPS", "6")
    assert CameraPipeline._frame_cache_target_fps_for_source(30) == 6
    assert CameraPipeline._frame_cache_target_fps_for_source(15) == 6
    assert CameraPipeline._frame_cache_target_fps_for_source(5) == 5


def test_frame_cache_target_can_be_lowered_when_measured(monkeypatch) -> None:
    monkeypatch.delenv("HAPAX_3D_COMPOSITOR", raising=False)
    monkeypatch.setenv("HAPAX_CAMERA_FRAME_CACHE_TARGET_FPS", "10")
    assert CameraPipeline._frame_cache_target_fps_for_source(30) == 10
    assert CameraPipeline._frame_cache_target_fps_for_source(15) == 10
    assert CameraPipeline._frame_cache_target_fps_for_source(10) == 10


def test_predecode_rate_cap_disabled_outside_3d(monkeypatch) -> None:
    monkeypatch.delenv("HAPAX_3D_COMPOSITOR", raising=False)
    monkeypatch.setenv("HAPAX_CAMERA_FRAME_CACHE_TARGET_FPS", "6")

    assert CameraPipeline._predecode_target_fps_for_source(30) is None


def test_predecode_rate_cap_follows_3d_frame_cache_target(monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_3D_COMPOSITOR", "1")
    monkeypatch.setenv("HAPAX_CAMERA_FRAME_CACHE_TARGET_FPS", "6")

    assert CameraPipeline._predecode_target_fps_for_source(30) == 6
    assert CameraPipeline._predecode_target_fps_for_source(6) is None


def test_predecode_drop_probability_preserves_compressed_caps(monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_3D_COMPOSITOR", "1")
    monkeypatch.setenv("HAPAX_CAMERA_FRAME_CACHE_TARGET_FPS", "6")

    assert round(CameraPipeline._predecode_drop_probability_for_source(30) or 0.0, 6) == 0.8
    assert round(CameraPipeline._predecode_drop_probability_for_source(15) or 0.0, 6) == 0.6
    assert CameraPipeline._predecode_drop_probability_for_source(6) is None


def test_frame_cache_snapshot_gate_uses_monotonic_time() -> None:
    pipeline = object.__new__(CameraPipeline)
    pipeline._frame_cache_sample_interval_s = 0.5
    pipeline._next_frame_cache_sample_at = 0.0

    assert pipeline._should_snapshot_frame_cache(10.0) is True
    assert pipeline._should_snapshot_frame_cache(10.2) is False
    assert pipeline._should_snapshot_frame_cache(10.5) is True


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
