"""Tests for `agents.studio_compositor.face_obscure_pipeline` + integration.

Covers the Stage 2 contract:

* detection cadence (5 Hz ≈ every 200 ms at 30 fps)
* Kalman carry-forward across intermediate frames
* staleness drop after >500 ms since the last real detection
* multi-face detection + tracking
* empty-bbox frame (no faces at all) → pass-through
* feature flag OFF → pass-through byte-identical to input
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from agents.studio_compositor.face_obscure import BBox, FaceObscurer
from agents.studio_compositor.face_obscure_integration import (
    obscure_frame_for_camera,
    reset_pipeline_cache,
)
from agents.studio_compositor.face_obscure_pipeline import (
    CadencedBboxPipeline,
    FaceBboxSource,
    KalmanCarryForward,
)


@dataclass
class _StubSource:
    """FaceBboxSource stub that records calls and serves scripted responses."""

    responses: list[list[BBox]] = field(default_factory=list)
    calls: list[np.ndarray] = field(default_factory=list)

    def detect(self, frame: np.ndarray) -> list[BBox]:
        self.calls.append(frame)
        if not self.responses:
            return []
        return self.responses.pop(0)


def _make_frame(h: int = 480, w: int = 640, fill: int = 200) -> np.ndarray:
    return np.full((h, w, 3), fill, dtype=np.uint8)


# ---------------------------------------------------------------------------
# Cadence
# ---------------------------------------------------------------------------


class TestDetectionCadence:
    def test_protocol_runtime_check(self):
        # Runtime Protocol check: stub satisfies FaceBboxSource.
        source = _StubSource()
        assert isinstance(source, FaceBboxSource)

    def test_detect_called_once_per_200ms_batch_at_30fps(self):
        """At 30 fps over ~200 ms we render 6 frames; detect fires once."""
        source = _StubSource(
            responses=[
                [BBox(100, 100, 180, 180)],
                [BBox(110, 100, 190, 180)],
            ]
        )
        pipe = CadencedBboxPipeline(source=source, detect_interval_ms=200.0)
        frame = _make_frame()

        # Tick 1: t=0 → forces detect (first call, last_detect_ts_ms < 0).
        pipe.step(frame, now_ms=0.0)
        # Frames 2..6 at 33 ms intervals — all within the 200 ms window.
        for i in range(1, 6):
            pipe.step(frame, now_ms=i * 33.0)
        assert len(source.calls) == 1, "Only one detect in the first 200 ms window"

        # Cross the 200 ms boundary → second detect triggers.
        pipe.step(frame, now_ms=200.0)
        assert len(source.calls) == 2

    def test_detect_runs_once_per_window_even_across_many_frames(self):
        source = _StubSource(responses=[[BBox(0, 0, 10, 10)]] * 10)
        pipe = CadencedBboxPipeline(source=source, detect_interval_ms=200.0)
        frame = _make_frame()

        # 18 frames at 30 fps → ~600 ms → expect 3 detections (t=0, ~200, ~400).
        for i in range(18):
            pipe.step(frame, now_ms=i * 33.0)
        assert len(source.calls) == 3


# ---------------------------------------------------------------------------
# Carry-forward + staleness
# ---------------------------------------------------------------------------


class TestKalmanCarryForward:
    def test_carry_across_four_intermediate_frames(self):
        """Bbox persists across frames 2-5 via Kalman without re-detecting."""
        bbox = BBox(100, 100, 180, 180)
        source = _StubSource(responses=[[bbox]])
        pipe = CadencedBboxPipeline(source=source, detect_interval_ms=200.0)
        frame = _make_frame()

        seen: list[list[BBox]] = []
        for i in range(5):  # 5 frames at 30 fps → ~132 ms
            seen.append(pipe.step(frame, now_ms=i * 33.0))

        assert len(source.calls) == 1, "Detection only fires once in this window"
        for i, batch in enumerate(seen):
            assert len(batch) == 1, f"Frame {i}: lost the bbox during carry-forward"

    def test_carry_forward_drops_after_500ms_stale(self):
        """Without fresh detections, tracks die at >500 ms since last detect."""
        carry = KalmanCarryForward(max_staleness_ms=500.0)
        carry.update([BBox(100, 100, 180, 180)], now_ms=0.0)

        # At 500 ms: still inside the window (>, not >=).
        assert len(carry.predict(now_ms=500.0)) == 1
        # At 500.01 ms: carry-forward drops.
        assert carry.predict(now_ms=500.01) == []
        # And the internal state is cleared.
        assert carry.predict(now_ms=501.0) == []

    def test_carry_forward_velocity_tracks_motion(self):
        """Two sequential detections establish velocity; prediction extrapolates."""
        carry = KalmanCarryForward()
        # First detection at t=0.
        carry.update([BBox(100, 100, 180, 180)], now_ms=0.0)
        # 200 ms later, bbox has moved +20 px on x.
        carry.update([BBox(120, 100, 200, 180)], now_ms=200.0)

        # Predict 100 ms after the latest detection — expect ~+10 px further.
        predicted = carry.predict(now_ms=300.0)
        assert len(predicted) == 1
        assert 128.0 <= predicted[0].x1 <= 132.0, (
            f"Expected linear extrapolation to ~130, got x1={predicted[0].x1}"
        )

    def test_empty_detection_clears_tracks(self):
        """Explicit 'no faces' update wipes carry-forward — it is authoritative."""
        carry = KalmanCarryForward()
        carry.update([BBox(0, 0, 50, 50)], now_ms=0.0)
        assert len(carry.predict(now_ms=0.0)) == 1
        carry.update([], now_ms=50.0)
        assert carry.predict(now_ms=50.0) == []


# ---------------------------------------------------------------------------
# Multi-face + empty-frame
# ---------------------------------------------------------------------------


class TestMultiFaceAndEmpty:
    def test_multi_face_detection_tracked_independently(self):
        source = _StubSource(
            responses=[
                [BBox(50, 50, 120, 120), BBox(400, 300, 500, 400)],
            ]
        )
        pipe = CadencedBboxPipeline(source=source, detect_interval_ms=200.0)
        frame = _make_frame()

        bboxes = pipe.step(frame, now_ms=0.0)
        assert len(bboxes) == 2
        centroids = sorted((b.x1 + b.x2) / 2 for b in bboxes)
        assert centroids[0] < 100 < centroids[1], "Both faces preserved"

        # Carry-forward round.
        bboxes = pipe.step(frame, now_ms=33.0)
        assert len(bboxes) == 2

    def test_empty_bbox_frame_returns_nothing(self):
        """Source returns [] → pipeline yields [] (pass-through at obscure layer)."""
        source = _StubSource(responses=[[]])
        pipe = CadencedBboxPipeline(source=source, detect_interval_ms=200.0)
        frame = _make_frame()

        assert pipe.step(frame, now_ms=0.0) == []
        # And subsequent frames continue to report empty.
        assert pipe.step(frame, now_ms=33.0) == []


# ---------------------------------------------------------------------------
# Integration helper (flag + policy)
# ---------------------------------------------------------------------------


class TestIntegrationHelper:
    def setup_method(self) -> None:
        reset_pipeline_cache()

    def teardown_method(self) -> None:
        reset_pipeline_cache()

    def test_flag_off_is_byte_identical_passthrough(self):
        """HAPAX_FACE_OBSCURE_ACTIVE=0 → DISABLED → frame returned as-is."""
        frame = np.random.randint(0, 255, (240, 320, 3), dtype=np.uint8)
        out = obscure_frame_for_camera(
            frame,
            camera_role="unit-test",
            env={"HAPAX_FACE_OBSCURE_ACTIVE": "0"},
        )
        # Spec §11: pass-through must be byte-identical (same object, same bytes).
        assert out is frame
        assert np.array_equal(out, frame)

    def test_flag_on_with_faces_obscures_region(self):
        """Flag ON + policy ALWAYS_OBSCURE + bbox present → gruvbox-dark mask."""
        bbox = BBox(50, 50, 150, 150)

        def factory(_role: str) -> FaceBboxSource:
            return _StubSource(responses=[[bbox]])

        frame = np.full((240, 320, 3), 200, dtype=np.uint8)
        out = obscure_frame_for_camera(
            frame,
            camera_role="unit-test-faces",
            env={"HAPAX_FACE_OBSCURE_ACTIVE": "1"},
            source_factory=factory,
        )

        # Inside the (margin-expanded) bbox: pixels are obscured, not 200.
        assert out is not frame
        # A sample pixel clearly inside the original bbox must no longer be 200.
        assert tuple(out[100, 100]) != (200, 200, 200)
        # A sample pixel far outside stays untouched.
        assert tuple(out[10, 10]) == (200, 200, 200)

    def test_flag_on_no_faces_returns_frame_unchanged(self):
        """Empty bbox list short-circuits to the pass-through contract."""

        def factory(_role: str) -> FaceBboxSource:
            return _StubSource(responses=[[]])

        frame = np.full((240, 320, 3), 128, dtype=np.uint8)
        out = obscure_frame_for_camera(
            frame,
            camera_role="unit-test-empty",
            env={"HAPAX_FACE_OBSCURE_ACTIVE": "1"},
            source_factory=factory,
        )
        # FaceObscurer pass-through returns identity on empty bboxes.
        assert out is frame

    def test_source_exception_degrades_to_passthrough(self):
        """A detector crash must never take down the capture pipeline."""

        class _Boom:
            def detect(self, _frame: np.ndarray) -> list[BBox]:
                raise RuntimeError("onnxruntime exploded")

        frame = np.full((120, 160, 3), 77, dtype=np.uint8)
        out = obscure_frame_for_camera(
            frame,
            camera_role="unit-test-boom",
            env={"HAPAX_FACE_OBSCURE_ACTIVE": "1"},
            source_factory=lambda _role: _Boom(),
        )
        assert out is frame

    def test_pipeline_cached_per_camera_role(self):
        """Repeated calls for a role must reuse the same pipeline instance."""
        call_counter = {"n": 0}

        def factory(_role: str) -> FaceBboxSource:
            call_counter["n"] += 1
            return _StubSource(responses=[[BBox(0, 0, 10, 10)]] * 10)

        frame = _make_frame()
        obscure_frame_for_camera(
            frame,
            camera_role="shared-role",
            env={"HAPAX_FACE_OBSCURE_ACTIVE": "1"},
            source_factory=factory,
        )
        obscure_frame_for_camera(
            frame,
            camera_role="shared-role",
            env={"HAPAX_FACE_OBSCURE_ACTIVE": "1"},
            source_factory=factory,
        )
        assert call_counter["n"] == 1, "Factory should be invoked once per role"


# ---------------------------------------------------------------------------
# Sanity: FaceObscurer still paints the predicted bboxes
# ---------------------------------------------------------------------------


def test_pipeline_bboxes_feed_face_obscurer_cleanly():
    """The pipeline's BBox output must drop straight into FaceObscurer."""
    source = _StubSource(responses=[[BBox(20, 20, 80, 80)]])
    pipe = CadencedBboxPipeline(source=source, detect_interval_ms=200.0)
    frame = np.full((120, 160, 3), 200, dtype=np.uint8)

    bboxes = pipe.step(frame, now_ms=0.0)
    assert len(bboxes) == 1

    out = FaceObscurer().obscure(frame, bboxes)
    assert out is not frame
    # Interior pixel is masked (not the original 200 fill).
    assert tuple(out[50, 50]) != (200, 200, 200)
