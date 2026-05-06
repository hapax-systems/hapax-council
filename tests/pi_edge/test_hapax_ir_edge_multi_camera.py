"""Tests for dual-camera configuration in the Pi IR edge daemon."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np

_PI_EDGE = Path(__file__).resolve().parents[2] / "pi-edge"
if str(_PI_EDGE) not in sys.path:
    sys.path.insert(0, str(_PI_EDGE))

from cbip_calibration import CbipCameraCalibration, RoiRect  # noqa: E402
from hapax_ir_edge import build_edge_cameras, parse_camera_map  # noqa: E402
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
