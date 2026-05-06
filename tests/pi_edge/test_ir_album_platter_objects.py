"""Tests for multi-object CBIP/platter detection in ``pi-edge/ir_album.py``."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest


def _load_ir_album():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "pi-edge" / "ir_album.py"
    spec = importlib.util.spec_from_file_location("pi_edge_ir_album", module_path)
    if spec is None or spec.loader is None:
        pytest.fail(f"could not load module spec at {module_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pi_edge_ir_album"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ir_album():
    return _load_ir_album()


def _blank_frame(width: int = 900, height: int = 600) -> np.ndarray:
    return np.zeros((height, width), dtype=np.uint8)


def _draw_card(frame: np.ndarray, x: int, y: int, w: int = 90, h: int = 140) -> None:
    cv2.rectangle(frame, (x, y), (x + w, y + h), 220, thickness=-1)


def test_no_platter_objects_returns_empty_list(ir_album) -> None:
    assert ir_album.detect_platter_objects(_blank_frame()) == []


def test_detects_six_lenormand_cards_with_stable_slots(ir_album) -> None:
    frame = _blank_frame()
    for x, y in [(70, 70), (390, 70), (720, 70), (70, 360), (390, 360), (720, 360)]:
        _draw_card(frame, x, y)

    objects = ir_album.detect_platter_objects(frame, min_area_pct=0.001)

    assert [obj.stable_id for obj in objects] == [
        "row1-col1",
        "row1-col2",
        "row1-col3",
        "row2-col1",
        "row2-col2",
        "row2-col3",
    ]
    assert [obj.position_index for obj in objects] == [1, 2, 3, 4, 5, 6]
    assert all(obj.confidence >= 0.75 for obj in objects)
    assert all(0.55 <= obj.aspect_ratio <= 0.7 for obj in objects)


def test_missing_card_does_not_renumber_existing_slots(ir_album) -> None:
    full = _blank_frame()
    missing = _blank_frame()
    positions = {
        "row1-col1": (70, 70),
        "row1-col2": (390, 70),
        "row1-col3": (720, 70),
        "row2-col1": (70, 360),
        "row2-col2": (390, 360),
        "row2-col3": (720, 360),
    }
    for x, y in positions.values():
        _draw_card(full, x, y)
    for stable_id, (x, y) in positions.items():
        if stable_id != "row1-col2":
            _draw_card(missing, x, y)

    full_ids = {obj.stable_id for obj in ir_album.detect_platter_objects(full, min_area_pct=0.001)}
    missing_ids = {
        obj.stable_id for obj in ir_album.detect_platter_objects(missing, min_area_pct=0.001)
    }

    assert missing_ids == full_ids - {"row1-col2"}


def test_area_and_aspect_filters_are_tunable(ir_album) -> None:
    frame = _blank_frame()
    _draw_card(frame, 70, 70)
    cv2.rectangle(frame, (500, 100), (880, 118), 220, thickness=-1)

    objects = ir_album.detect_platter_objects(
        frame,
        min_area_pct=0.001,
        min_aspect_ratio=0.45,
    )

    assert [obj.stable_id for obj in objects] == ["row1-col1"]


def test_payload_is_json_serializable_for_report_writers(ir_album) -> None:
    frame = _blank_frame()
    _draw_card(frame, 390, 360)

    objects = ir_album.detect_platter_objects(frame, min_area_pct=0.001)
    payload = ir_album.platter_objects_payload(objects)

    assert payload == [objects[0].to_dict()]
    assert payload[0]["stable_id"] == "row2-col2"
    assert payload[0]["bbox"][0] <= 390


def test_legacy_single_album_detector_still_returns_largest_quad(ir_album) -> None:
    frame = _blank_frame()
    _draw_card(frame, 80, 80)
    cv2.rectangle(frame, (300, 180), (620, 500), 220, thickness=-1)

    detection = ir_album.detect_album_cover(frame)

    assert detection is not None
    assert detection["center"][0] > 400
    assert detection["area_pct"] > 0.15
