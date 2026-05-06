"""Tests for fixed CBIP ROI and capture calibration on the Pi edge daemon."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

_PI_EDGE = Path(__file__).resolve().parents[2] / "pi-edge"
if str(_PI_EDGE) not in sys.path:
    sys.path.insert(0, str(_PI_EDGE))

from cbip_calibration import (  # noqa: E402
    RoiRect,
    crop_to_roi,
    load_camera_calibration,
    write_local_calibration,
)


def test_loads_versioned_yaml_and_builds_rpicam_args(tmp_path: Path) -> None:
    config = tmp_path / "cbip-calibration.yaml"
    config.write_text(
        """
version: 1
cameras:
  overhead:
    frame_width: 1920
    frame_height: 1080
    roi_x: 10
    roi_y: 20
    roi_width: 300
    roi_height: 400
    exposure_locked: true
    exposure_time_us: 11000
    analogue_gain: 1.25
    white_balance_locked: true
    colour_gain_red: 1.4
    colour_gain_blue: 1.8
"""
    )

    cal = load_camera_calibration("overhead", config_path=config, local_dir=tmp_path)

    assert cal.roi == RoiRect(10, 20, 300, 400)
    assert cal.rpicam_still_args() == [
        "--shutter",
        "11000",
        "--gain",
        "1.25",
        "--awbgains",
        "1.4,1.8",
    ]


def test_local_json_override_wins_for_roi_and_capture_controls(tmp_path: Path) -> None:
    config = tmp_path / "cbip-calibration.yaml"
    config.write_text(
        """
version: 1
cameras:
  overhead:
    frame_width: 1920
    frame_height: 1080
    roi_x: 0
    roi_y: 0
    roi_width: 1920
    roi_height: 1080
    exposure_locked: true
    exposure_time_us: 9000
"""
    )
    write_local_calibration(
        tmp_path / "cbip-roi-overhead.json",
        camera_id="overhead",
        roi=RoiRect(100, 120, 640, 480),
        frame_size=(1920, 1080),
        corners=[(100, 120), (740, 120), (740, 600), (100, 600)],
        exposure_time_us=13000,
        analogue_gain=1.5,
        colour_gains=(1.2, 1.9),
    )

    cal = load_camera_calibration("overhead", config_path=config, local_dir=tmp_path)

    assert cal.roi == RoiRect(100, 120, 640, 480)
    assert cal.exposure_time_us == 13000
    assert cal.colour_gains == (1.2, 1.9)
    assert str(config) in cal.source_paths
    assert str(tmp_path / "cbip-roi-overhead.json") in cal.source_paths


def test_crop_to_roi_returns_clamped_copy() -> None:
    frame = np.arange(5 * 6 * 3, dtype=np.uint8).reshape(5, 6, 3)
    config = type(
        "Calibration",
        (),
        {"roi": RoiRect(4, 3, 99, 99)},
    )()

    cropped = crop_to_roi(frame, config)

    assert cropped.shape == (2, 2, 3)
    assert np.array_equal(cropped, frame[3:5, 4:6])
    cropped[0, 0, 0] = 0
    assert not np.shares_memory(cropped, frame)


def test_cli_writes_noninteractive_roi_json(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[2] / "scripts" / "cbip-calibrate-roi.py"
    output = tmp_path / "roi.json"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--cam-id",
            "overhead",
            "--corners",
            "10,20",
            "90,20",
            "90,70",
            "10,70",
            "--frame-size",
            "100x80",
            "--output",
            str(output),
            "--exposure-time-us",
            "14000",
            "--analogue-gain",
            "1.25",
            "--red-gain",
            "1.1",
            "--blue-gain",
            "1.9",
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert str(output) in result.stdout
    body = json.loads(output.read_text())
    assert body["camera_id"] == "overhead"
    assert body["roi"] == {"x": 10, "y": 20, "width": 80, "height": 50}
    assert body["exposure_locked"] is True
    assert body["white_balance_locked"] is True
    assert body["colour_gains"] == [1.1, 1.9]
