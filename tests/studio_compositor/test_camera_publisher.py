import importlib
import json

from agents.studio_compositor import camera_publisher, frame_cache
from agents.studio_compositor.camera_publisher import CameraSourcePublisher


def test_frame_cache_sequences_are_monotonic_and_reset() -> None:
    frame_cache.clear()

    frame_cache.update("brio-operator", b"\x10\x10\x10\x10\x80\x80", 2, 2)
    first = frame_cache.get("brio-operator")
    assert first is not None
    assert first.sequence == 1

    frame_cache.update("brio-operator", b"\x11\x11\x11\x11\x80\x80", 2, 2)
    second = frame_cache.get("brio-operator")
    assert second is not None
    assert second.sequence == 2

    frame_cache.clear("brio-operator")
    frame_cache.update("brio-operator", b"\x12\x12\x12\x12\x80\x80", 2, 2)
    reset = frame_cache.get("brio-operator")
    assert reset is not None
    assert reset.sequence == 1


def test_3d_publisher_uses_frame_sequence_for_change_detection(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_3D_COMPOSITOR", "1")
    frame_cache.clear()
    publisher = CameraSourcePublisher(interval_s=1.0, sources_dir=tmp_path)

    frame_cache.update("brio-operator", b"\x10\x10\x10\x10\x80\x80", 2, 2)
    publisher._tick_3d()

    manifest_path = tmp_path / "camera-brio-operator" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    assert manifest["frame_sequence"] == 1

    first_mtime = manifest_path.stat().st_mtime_ns
    publisher._tick_3d()
    assert manifest_path.stat().st_mtime_ns == first_mtime

    frame_cache.update("brio-operator", b"\x12\x12\x12\x12\x80\x80", 2, 2)
    publisher._tick_3d()

    manifest = json.loads(manifest_path.read_text())
    assert manifest["frame_sequence"] == 2
    assert (tmp_path / "camera-brio-operator" / "frame.rgba").stat().st_size == 16


def test_nv12_to_rgba_returns_camera_sized_rgba() -> None:
    data = b"\x40\x50\x60\x70\x80\x80"
    rgba = CameraSourcePublisher._nv12_to_rgba(data, 2, 2)

    assert rgba.shape == (2, 2, 4)
    assert rgba.dtype.name == "uint8"


def test_default_camera_source_publish_cadence_is_thirty_hz(monkeypatch) -> None:
    monkeypatch.delenv("HAPAX_CAMERA_SOURCE_PUBLISH_INTERVAL_S", raising=False)
    monkeypatch.delenv("HAPAX_CAMERA_SOURCE_PUBLISH_FPS", raising=False)
    reloaded = importlib.reload(camera_publisher)

    assert abs(reloaded._DEFAULT_INTERVAL_S - (1.0 / 30.0)) < 0.0001
