"""Capture pipeline + SHM writer tests.

Avoid GStreamer at the test layer — the capture daemon's GStreamer
calls are lazy-imported, so :class:`SteamDeckCapture` constructs +
exposes the pipeline description without a Gst dependency. We verify
the pipeline string structurally + exercise the SHM writer with
synthetic frames.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.hapax_steamdeck_bridge.capture import (
    DEFAULT_CAPTURE_HEIGHT,
    DEFAULT_CAPTURE_WIDTH,
    SteamDeckCapture,
    build_pipeline_description,
)
from agents.hapax_steamdeck_bridge.redaction import (
    RedactionMode,
    redaction_zones_for_mode,
)


def test_pipeline_description_contains_canonical_elements() -> None:
    description = build_pipeline_description(
        v4l2_device="/dev/video40",
        redaction_zones=(),
    )
    assert "v4l2src device=/dev/video40" in description
    assert "videoconvert" in description
    assert "video/x-raw,format=BGRA" in description
    assert f"width={DEFAULT_CAPTURE_WIDTH}" in description
    assert f"height={DEFAULT_CAPTURE_HEIGHT}" in description
    assert "appsink name=shm_sink" in description
    assert "sync=false" in description


def test_pipeline_description_inserts_videobox_per_zone() -> None:
    zones = redaction_zones_for_mode(RedactionMode.FULL)
    description = build_pipeline_description(
        v4l2_device="/dev/video40",
        redaction_zones=zones,
    )
    # Two videobox elements (notification + friends) under FULL mode.
    assert description.count("videobox") == 2
    assert "mask_steam_notification" in description
    assert "mask_steam_friends" in description


def test_pipeline_description_off_mode_has_no_videobox() -> None:
    description = build_pipeline_description(
        v4l2_device="/dev/video40",
        redaction_zones=redaction_zones_for_mode(RedactionMode.OFF),
    )
    assert "videobox" not in description


def test_pipeline_description_videobox_uses_negative_offsets() -> None:
    """videobox 'fill mode' requires negative crop offsets per element."""
    zones = redaction_zones_for_mode(RedactionMode.PARTIAL)
    description = build_pipeline_description(
        v4l2_device="/dev/video40",
        redaction_zones=zones,
    )
    # Notification zone is anchored at top-right (1700, 0, 220, 80) on
    # a 1920x1080 canvas → left=-1700, top=0, right=0, bottom=-1000.
    assert "left=-1700" in description
    assert "top=0" in description


def test_capture_expected_stride_and_frame_size() -> None:
    cap = SteamDeckCapture(v4l2_device="/dev/video40", width=1920, height=1080)
    assert cap.expected_stride == 1920 * 4
    assert cap.expected_frame_size == 1920 * 1080 * 4


def test_capture_pipeline_description_uses_configured_redaction(monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_STEAMDECK_REDACT", "off")
    cap = SteamDeckCapture(v4l2_device="/dev/video40")
    assert cap.redaction_mode is RedactionMode.OFF
    assert "videobox" not in cap.pipeline_description()


def test_write_to_shm_atomic_tmp_rename(tmp_path: Path) -> None:
    """The write callback must produce an SHM file + sidecar JSON."""
    shm = tmp_path / "steamdeck-display.rgba"
    sidecar = tmp_path / "steamdeck-display.json"
    cap = SteamDeckCapture(
        v4l2_device="/dev/video40",
        shm_path=shm,
        sidecar_path=sidecar,
        width=4,
        height=2,
    )
    payload = bytes(cap.expected_frame_size)  # 4*2*4 = 32 zero bytes
    cap._write_to_shm(payload, ts=12345.0)  # noqa: SLF001 — direct call exercises the callback

    assert shm.exists()
    assert sidecar.exists()
    assert shm.read_bytes() == payload
    meta = json.loads(sidecar.read_text())
    assert meta["width"] == 4
    assert meta["height"] == 2
    assert meta["stride"] == 16
    assert meta["format"] == "BGRA"
    assert meta["ts"] == 12345.0
    assert meta["redaction_mode"] in ("full", "partial", "off")


def test_write_to_shm_rejects_size_mismatch(tmp_path: Path) -> None:
    """A buffer that doesn't match width*height*4 must NOT be written."""
    shm = tmp_path / "out.rgba"
    sidecar = tmp_path / "out.json"
    cap = SteamDeckCapture(
        v4l2_device="/dev/video40",
        shm_path=shm,
        sidecar_path=sidecar,
        width=4,
        height=2,
    )
    cap._write_to_shm(b"too-short", ts=0.0)  # noqa: SLF001
    assert not shm.exists()
    assert not sidecar.exists()


def test_write_callback_can_be_overridden_for_tests() -> None:
    """Inject a fake sample callback so the capture path is testable
    without touching the filesystem at all.
    """
    received: list[tuple[bytes, float]] = []

    def collect(buf: bytes, ts: float) -> None:
        received.append((buf, ts))

    cap = SteamDeckCapture(
        v4l2_device="/dev/video40",
        sample_callback=collect,
    )
    cap._sample_callback(b"abc", 99.0)  # noqa: SLF001 — exercises injected callback
    assert received == [(b"abc", 99.0)]


def test_stop_without_start_does_not_raise(tmp_path: Path) -> None:
    cap = SteamDeckCapture(
        v4l2_device="/dev/video40",
        shm_path=tmp_path / "x.rgba",
        sidecar_path=tmp_path / "x.json",
    )
    # No pipeline running, no SHM files — stop() must be idempotent.
    cap.stop()
    cap.stop()


def test_stop_removes_existing_shm_files(tmp_path: Path) -> None:
    shm = tmp_path / "x.rgba"
    sidecar = tmp_path / "x.json"
    shm.write_bytes(b"stale")
    sidecar.write_text("{}")
    cap = SteamDeckCapture(
        v4l2_device="/dev/video40",
        shm_path=shm,
        sidecar_path=sidecar,
    )
    cap.stop()
    assert not shm.exists()
    assert not sidecar.exists()


def test_start_raises_runtime_error_when_gst_unavailable(monkeypatch) -> None:
    """If GStreamer is not importable, start() must raise RuntimeError.

    Simulated by injecting an ImportError into the lazy import path.
    """
    import builtins

    real_import = builtins.__import__

    def gst_only_block(name, *args, **kwargs):
        if name == "gi":
            raise ImportError("no gi for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", gst_only_block)

    cap = SteamDeckCapture(v4l2_device="/dev/video40")
    with pytest.raises(RuntimeError, match="GStreamer 1.0 unavailable"):
        cap.start()
