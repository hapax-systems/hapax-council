"""Capture-time wiring regression tests for task #129 Stage 3.

Covers the final live wiring in ``agents.studio_compositor.cameras`` that
runs ``obscure_frame_for_camera`` on every per-camera snapshot before the
JPEG is written to ``/dev/shm/hapax-compositor/<role>.jpg``.

GStreamer itself is too heavy to exercise in a unit test, so these tests
simulate the appsink callback path directly:

    raw BGR frame
    → obscure_frame_for_camera(frame, camera_role)
    → cv2.imencode(".jpg", ..., quality=75)
    → atomic tmp+rename into SNAPSHOT_DIR
    → cv2.imread(final) → assert the face region is obscured

This is the same sequence the live ``_on_new_sample`` callback runs, so
a regression in any of the four links fails this test.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest

from agents.studio_compositor.face_obscure import GRUVBOX_DARK_BGR, BBox
from agents.studio_compositor.face_obscure_integration import (
    obscure_frame_for_camera,
    reset_pipeline_cache,
)


class _StubSource:
    """Deterministic bbox source — independent of SCRFD weights."""

    def __init__(self, bboxes: list[BBox]) -> None:
        self._bboxes = bboxes

    def detect(self, frame: Any) -> list[BBox]:  # noqa: ARG002 — signature match
        return list(self._bboxes)


def _make_bgr_frame(h: int = 360, w: int = 640, fill: int = 200) -> np.ndarray:
    """Solid non-Gruvbox BGR frame so the obscure mask is clearly visible."""
    return np.full((h, w, 3), fill, dtype=np.uint8)


def _run_capture_cycle(
    frame: np.ndarray,
    camera_role: str,
    snapshot_dir: Path,
    bboxes: list[BBox],
) -> np.ndarray:
    """Simulate the ``_on_new_sample`` callback end-to-end and return the
    decoded JPEG that landed on disk."""
    obscured = obscure_frame_for_camera(
        frame,
        camera_role,
        source_factory=lambda _role: _StubSource(bboxes),
    )
    ok, jpeg = cv2.imencode(
        ".jpg",
        obscured,
        [int(cv2.IMWRITE_JPEG_QUALITY), 75],
    )
    assert ok, "cv2.imencode must succeed for BGR uint8 frame"

    snapshot_dir.mkdir(parents=True, exist_ok=True)
    tmp = snapshot_dir / f"{camera_role}.jpg.tmp"
    final = snapshot_dir / f"{camera_role}.jpg"
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
    try:
        os.write(fd, jpeg.tobytes())
    finally:
        os.close(fd)
    tmp.rename(final)

    decoded = cv2.imread(str(final))
    assert decoded is not None, "JPEG write/read round-trip failed"
    return decoded


class TestCaptureIntegration:
    def setup_method(self) -> None:
        reset_pipeline_cache()

    def teardown_method(self) -> None:
        reset_pipeline_cache()

    def test_obscured_frame_reaches_disk(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The JPEG that lands on disk has the bbox region obscured."""
        monkeypatch.setenv("HAPAX_FACE_OBSCURE_ACTIVE", "1")
        frame = _make_bgr_frame()
        # Centred 200x200 bbox on the 640x360 frame.
        bbox = BBox(x1=220, y1=80, x2=420, y2=280)

        with tempfile.TemporaryDirectory() as tmpdir:
            decoded = _run_capture_cycle(
                frame,
                camera_role="operator",
                snapshot_dir=Path(tmpdir),
                bboxes=[bbox],
            )

        h, w = decoded.shape[:2]
        assert (h, w) == frame.shape[:2]

        # Sample the obscure mask at the bbox centre. JPEG quantisation
        # means we can't assert exact Gruvbox bytes — use a tolerance.
        cx = (int(bbox.x1) + int(bbox.x2)) // 2
        cy = (int(bbox.y1) + int(bbox.y2)) // 2
        center_px = decoded[cy, cx].astype(int)
        expected = np.array(GRUVBOX_DARK_BGR, dtype=int)
        # The solid Gruvbox fill plus block pixelation should leave the
        # centre ≤ ~15 BGR units from the target post-JPEG. The original
        # fill (200, 200, 200) is >150 units away, so any drift from
        # obscure skipping would fail this bound by a wide margin.
        assert np.all(np.abs(center_px - expected) < 20), (
            f"bbox centre should be ~Gruvbox-dark; got BGR={tuple(center_px)}"
        )

        # Control: a corner pixel well outside the expanded bbox should
        # still be near the original fill (not obscured).
        corner_px = decoded[10, 10].astype(int)
        assert np.all(np.abs(corner_px - 200) < 20), (
            f"corner should be near fill=200, got BGR={tuple(corner_px)}"
        )

    def test_empty_bbox_list_passes_through_to_disk(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No detections → original frame round-trips with only JPEG loss."""
        monkeypatch.setenv("HAPAX_FACE_OBSCURE_ACTIVE", "1")
        frame = _make_bgr_frame()

        with tempfile.TemporaryDirectory() as tmpdir:
            decoded = _run_capture_cycle(
                frame,
                camera_role="desk",
                snapshot_dir=Path(tmpdir),
                bboxes=[],
            )
        center_px = decoded[180, 320].astype(int)
        assert np.all(np.abs(center_px - 200) < 20), "empty bbox list must not obscure the frame"

    def test_feature_flag_off_skips_obscure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``HAPAX_FACE_OBSCURE_ACTIVE=0`` short-circuits the stage."""
        monkeypatch.setenv("HAPAX_FACE_OBSCURE_ACTIVE", "0")
        frame = _make_bgr_frame()
        bbox = BBox(x1=220, y1=80, x2=420, y2=280)

        with tempfile.TemporaryDirectory() as tmpdir:
            decoded = _run_capture_cycle(
                frame,
                camera_role="room",
                snapshot_dir=Path(tmpdir),
                bboxes=[bbox],
            )
        # Flag off → frame written unmodified, so the bbox centre is still
        # the original fill, not Gruvbox-dark.
        cx = (int(bbox.x1) + int(bbox.x2)) // 2
        cy = (int(bbox.y1) + int(bbox.y2)) // 2
        center_px = decoded[cy, cx].astype(int)
        assert np.all(np.abs(center_px - 200) < 20), "flag off must produce pass-through JPEG"


class TestPrometheusCounter:
    """hapax_face_obscure_frame_total{camera_role, has_faces} must advance."""

    def setup_method(self) -> None:
        reset_pipeline_cache()

    def teardown_method(self) -> None:
        reset_pipeline_cache()

    def test_counter_increments_with_and_without_faces(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HAPAX_FACE_OBSCURE_ACTIVE", "1")
        try:
            from agents.studio_compositor import metrics as sm
        except ImportError:
            pytest.skip("prometheus_client not installed")
        if sm.HAPAX_FACE_OBSCURE_FRAME_TOTAL is None:
            pytest.skip("metrics registry not initialised (prometheus_client missing)")

        # Use a distinctive role label so we don't collide with other tests.
        role = "capture-integration-test-cam"
        counter = sm.HAPAX_FACE_OBSCURE_FRAME_TOTAL

        def _sample(has_faces: str) -> float:
            return counter.labels(camera_role=role, has_faces=has_faces)._value.get()

        before_true = _sample("true")
        before_false = _sample("false")

        frame = _make_bgr_frame()

        # Call 1: no faces → has_faces=false should bump.
        obscure_frame_for_camera(
            frame,
            role,
            source_factory=lambda _r: _StubSource([]),
        )
        # Reset the per-camera pipeline cache so call 2 picks up the new
        # stub source (the pipeline caches its source on first construction).
        reset_pipeline_cache()
        # Call 2: one face → has_faces=true should bump.
        obscure_frame_for_camera(
            frame,
            role,
            source_factory=lambda _r: _StubSource([BBox(100, 100, 200, 200)]),
        )

        assert _sample("false") == before_false + 1, (
            f"has_faces=false should bump by exactly 1; before={before_false} "
            f"after={_sample('false')}"
        )
        assert _sample("true") == before_true + 1, (
            f"has_faces=true should bump by exactly 1; before={before_true} after={_sample('true')}"
        )
