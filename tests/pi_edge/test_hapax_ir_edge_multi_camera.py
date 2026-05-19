"""Tests for dual-camera configuration in the Pi IR edge daemon."""

from __future__ import annotations

import base64
import sys
import threading
from pathlib import Path
from unittest.mock import patch

import numpy as np

_PI_EDGE = Path(__file__).resolve().parents[2] / "pi-edge"
if str(_PI_EDGE) not in sys.path:
    sys.path.insert(0, str(_PI_EDGE))

from cbip_calibration import CbipCameraCalibration, RoiRect  # noqa: E402
from hapax_ir_edge import IrEdgeDaemon, build_edge_cameras, parse_camera_map  # noqa: E402
from ir_report import build_report  # noqa: E402


def test_parse_camera_map_defaults_to_single_primary_rpicam() -> None:
    assert parse_camera_map(None)[0].cam_id == "primary"
    assert parse_camera_map(None)[0].backend == "rpicam"
    assert parse_camera_map(None)[0].selector == "0"


def test_parse_camera_map_accepts_rpicam_and_usb_entries() -> None:
    specs = parse_camera_map("primary=rpicam:0,secondary=usb:/dev/video2")

    assert [(spec.cam_id, spec.backend, spec.selector) for spec in specs] == [
        ("primary", "rpicam", "0"),
        ("secondary", "usb", "/dev/video2"),
    ]


def test_build_edge_cameras_uses_role_calibration_for_primary_and_cam_id_for_secondary() -> None:
    calls: list[tuple[str, str | None]] = []

    def fake_load(camera_id: str, *, hostname: str | None = None) -> CbipCameraCalibration:
        calls.append((camera_id, hostname))
        return CbipCameraCalibration(
            camera_id=camera_id,
            roi=RoiRect(1, 2, 300, 200),
            exposure_locked=True,
            exposure_time_us=12000,
            white_balance_locked=True,
            colour_gains=(1.2, 1.9),
        )

    with patch("hapax_ir_edge.load_camera_calibration", side_effect=fake_load):
        cameras = build_edge_cameras(
            "overhead",
            "hapax-pi6",
            "primary=rpicam:0,secondary=usb:/dev/video2",
        )

    assert calls == [("overhead", "hapax-pi6"), ("overhead-secondary", "hapax-pi6-secondary")]
    assert [camera.cam_id for camera in cameras] == ["primary", "secondary"]
    assert cameras[0].rpicam_args == ("--shutter", "12000", "--awbgains", "1.2,1.9")


def test_report_builder_carries_cam_id() -> None:
    report = build_report(
        "hapax-pi6",
        "overhead",
        0.5,
        [],
        [],
        [],
        np.zeros((4, 4), dtype=np.uint8),
        12,
        {},
        cam_id="secondary",
    )

    assert report.cam_id == "secondary"
    assert report.model_dump()["cam_id"] == "secondary"


def test_report_builder_carries_cbip_frame_and_detection_payload() -> None:
    report = build_report(
        "hapax-pi6",
        "overhead",
        0.5,
        [],
        [],
        [],
        np.zeros((10, 20), dtype=np.uint8),
        12,
        {},
        cam_id="primary",
        capture_ts="2026-05-19T01:00:00+00:00",
        grey_jpeg_b64="abc123",
        platter_objects=[{"object_id": "platter-01", "position_index": 1}],
        platter_primary_object={"object_id": "platter-01", "position_index": 1},
    )

    dumped = report.model_dump()
    assert dumped["capture_ts"] == "2026-05-19T01:00:00+00:00"
    assert dumped["frame_width"] == 20
    assert dumped["frame_height"] == 10
    assert dumped["grey_jpeg_b64"] == "abc123"
    assert dumped["platter_objects"][0]["object_id"] == "platter-01"
    assert dumped["platter_primary_object"]["position_index"] == 1


def test_overhead_primary_processing_emits_frame_and_platter_payload() -> None:
    daemon = IrEdgeDaemon.__new__(IrEdgeDaemon)
    daemon._role = "overhead"
    daemon._prev_frames = {}
    daemon._last_detection_time_by_cam = {}
    daemon._latest_jpeg_lock = threading.Lock()
    daemon._latest_jpeg = b""
    daemon._latest_jpegs_by_cam = {}
    daemon._latest_platter_jpeg = b""
    daemon._latest_platter_objects = []
    daemon._latest_album_jpeg = b""
    daemon._latest_album_detection = None
    daemon._save_debug_frame = False
    daemon._save_interval = 0
    daemon._frame_count = 0
    daemon._captures_dir = Path("/tmp")
    daemon._yolo = type("FakeYolo", (), {"detect_persons": lambda _self, _color: []})()
    daemon._face = object()
    daemon._biometrics = type("FakeBiometrics", (), {"face_detected": False})()

    color = np.full((80, 120, 3), 180, dtype=np.uint8)
    grey = np.full((80, 120), 180, dtype=np.uint8)
    detection = {
        "object_id": "platter-01",
        "position_index": 1,
        "area_pct": 0.2,
        "corners": [[10, 10], [60, 10], [60, 60], [10, 60]],
    }

    with (
        patch("hapax_ir_edge.detect_hands_nir", return_value=[]),
        patch("hapax_ir_edge.detect_screens_nir", return_value=[]),
        patch("hapax_ir_edge.detect_platter_objects", return_value=[detection]),
        patch("hapax_ir_edge.extract_platter_crop", return_value=color),
    ):
        processed = daemon._process_captured_frame(
            "primary",
            "2026-05-19T01:00:00+00:00",
            color,
            grey,
        )

    assert processed.capture_ts == "2026-05-19T01:00:00+00:00"
    assert processed.platter_objects == [detection]
    assert processed.platter_primary_object == detection
    assert base64.b64decode(processed.grey_jpeg_b64).startswith(b"\xff\xd8")
    assert daemon._latest_platter_objects == [detection]
    assert daemon._latest_platter_jpeg.startswith(b"\xff\xd8")
