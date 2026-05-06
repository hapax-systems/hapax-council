"""Tests for the Pi-edge interpretative-platter detector."""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import cv2
import numpy as np

PI_EDGE_DIR = Path(__file__).resolve().parents[2] / "pi-edge"
if str(PI_EDGE_DIR) not in sys.path:
    sys.path.insert(0, str(PI_EDGE_DIR))

from ir_platter import (  # noqa: E402
    detect_album_cover,
    detect_platter_objects,
    extract_platter_crop,
)


def _blank_frame(width: int = 800, height: int = 600) -> np.ndarray:
    return np.zeros((height, width), dtype=np.uint8)


def _draw_rect(
    frame: np.ndarray,
    *,
    x: int,
    y: int,
    w: int,
    h: int,
    value: int = 220,
) -> None:
    cv2.rectangle(frame, (x, y), (x + w, y + h), value, thickness=-1)


def test_no_objects_returns_empty_list() -> None:
    assert detect_platter_objects(_blank_frame()) == []


def test_single_platter_object_has_geometry_and_position_id() -> None:
    frame = _blank_frame()
    _draw_rect(frame, x=250, y=180, w=220, h=220)

    detections = detect_platter_objects(frame)

    assert len(detections) == 1
    detection = detections[0]
    assert detection["object_id"] == "platter-01"
    assert detection["position_index"] == 1
    assert detection["bbox"][0] <= 250
    assert detection["bbox"][2] >= 470
    assert len(detection["corners"]) == 4
    assert detection["area_pct"] > 0.05


def test_multiple_cards_return_position_ordered_objects() -> None:
    frame = _blank_frame()
    positions = [
        (80, 80),
        (280, 80),
        (480, 80),
        (80, 330),
        (280, 330),
        (480, 330),
    ]
    for x, y in positions:
        _draw_rect(frame, x=x, y=y, w=90, h=140)

    detections = detect_platter_objects(frame, min_area_pct=0.001)

    assert [d["object_id"] for d in detections] == [
        "platter-01",
        "platter-02",
        "platter-03",
        "platter-04",
        "platter-05",
        "platter-06",
    ]
    centers = [tuple(d["center"]) for d in detections]
    assert centers[0][1] < centers[3][1]
    assert centers[:3] == sorted(centers[:3], key=lambda c: c[0])
    assert centers[3:] == sorted(centers[3:], key=lambda c: c[0])


def test_detect_album_cover_alias_returns_largest_platter_object() -> None:
    frame = _blank_frame()
    _draw_rect(frame, x=50, y=50, w=90, h=140)
    _draw_rect(frame, x=260, y=180, w=260, h=260)

    detection = detect_album_cover(frame)

    assert detection is not None
    assert detection["center"][0] > 300
    assert detection["area_pct"] > 0.1


def test_extract_platter_crop_warps_to_requested_size() -> None:
    frame = _blank_frame()
    _draw_rect(frame, x=120, y=100, w=180, h=240)
    detection = detect_platter_objects(frame)[0]
    color = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)

    crop = extract_platter_crop(color, detection, output_size=(90, 120))

    assert crop is not None
    assert crop.shape == (120, 90, 3)
    assert int(np.mean(crop)) > 150


def test_ir_album_shim_exposes_platter_detector() -> None:
    import ir_album

    assert ir_album.detect_platter_objects is detect_platter_objects


def test_frame_handler_serves_platter_json_contract() -> None:
    import hapax_ir_edge

    class FakeDaemon:
        _latest_jpeg_lock = threading.Lock()
        _latest_platter_jpeg = b"jpeg"
        _latest_album_jpeg = b"jpeg"
        _latest_album_detection = {"object_id": "platter-01"}
        _latest_platter_objects = [
            {"object_id": "platter-01", "position_index": 1},
            {"object_id": "platter-02", "position_index": 2},
        ]

    captured: dict[str, object] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status
        captured["headers"] = headers

    handler = hapax_ir_edge._FrameHandler(FakeDaemon())

    body = b"".join(handler({"PATH_INFO": "/platter.json"}, start_response))

    assert captured["status"] == "200 OK"
    payload = json.loads(body)
    assert payload["count"] == 2
    assert [obj["object_id"] for obj in payload["objects"]] == ["platter-01", "platter-02"]
