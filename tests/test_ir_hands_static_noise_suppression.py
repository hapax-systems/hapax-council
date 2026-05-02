"""Tests for IR hand-detection static-noise suppression — cc-task
ir-hand-detection-static-noise-suppression.

Layered matrix:
  L0: detect_hands_nir behavior with no motion_delta arg (legacy / backward compat)
  L1: detect_hands_nir behavior when motion_delta is below HAND_MOTION_FLOOR
  L2: detect_hands_nir behavior when motion_delta is above HAND_MOTION_FLOOR
  L3: regression pin against the empirical noise-floor value (0.014) observed
      across all 3 Pis during the 2026-05-02 IR fleet revival when the operator
      was absent

L0 must remain the legacy single-frame behavior; callers that don't know about
the suppression continue to work.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

# pi-edge code is not a Python package; add it to sys.path explicitly.
PI_EDGE_DIR = Path(__file__).resolve().parent.parent / "pi-edge"
sys.path.insert(0, str(PI_EDGE_DIR))

from ir_hands import HAND_MOTION_FLOOR, detect_hands_nir  # noqa: E402


def _frame_with_hand_like_blobs() -> np.ndarray:
    """Build a synthetic NIR frame containing several blob shapes that pass
    the adaptive-threshold + area + aspect-ratio gates of detect_hands_nir.

    The frame is 1080x1920 portrait (matches captured Pi frame shape) with a
    bright background (mean ≈ 200) and several DARK rectangular blobs that
    survive the inverted adaptive threshold + close/open + min-area gate. We
    don't care that these are anatomically plausible hands — we just need
    the contour pipeline to find ≥1 contour so we can verify the gate behavior.
    """
    h, w = 1920, 1080
    frame = np.full((h, w), 200, dtype=np.uint8)

    # Several dark rectangular regions large enough to pass min_area=2000.
    # Aspect ratios in [0.3, 3.0] band so the shape gate accepts them.
    blobs = [
        ((100, 1700), (200, 200)),
        ((400, 1700), (180, 220)),
        ((700, 1700), (220, 200)),
        ((900, 1500), (150, 200)),
    ]
    for (x, y), (bw, bh) in blobs:
        frame[y : y + bh, x : x + bw] = 30  # dark blob

    return frame


class TestLegacyBackwardCompat:
    """L0: callers that omit motion_delta see the legacy behavior unchanged."""

    def test_no_motion_arg_returns_hands_when_present(self) -> None:
        frame = _frame_with_hand_like_blobs()
        hands = detect_hands_nir(frame)
        assert len(hands) >= 1, (
            "synthetic blob frame should produce ≥1 hand detection in legacy mode"
        )

    def test_motion_delta_none_explicit_is_legacy(self) -> None:
        frame = _frame_with_hand_like_blobs()
        hands = detect_hands_nir(frame, motion_delta=None)
        legacy = detect_hands_nir(frame)
        assert len(hands) == len(legacy), (
            "passing motion_delta=None must be identical to omitting the arg"
        )


class TestMotionGateMatrix:
    """L1 + L2: the motion-delta floor splits the gate into two halves."""

    @pytest.mark.parametrize("motion_delta", [0.0, 0.005, 0.014, HAND_MOTION_FLOOR - 0.001])
    def test_below_floor_returns_empty(self, motion_delta: float) -> None:
        """Static or near-static frames produce no hands regardless of contours."""
        frame = _frame_with_hand_like_blobs()
        hands = detect_hands_nir(frame, motion_delta=motion_delta)
        assert hands == [], (
            f"motion_delta={motion_delta} below floor={HAND_MOTION_FLOOR} "
            f"must return [] (got {len(hands)} hands — static-noise FPs not suppressed)"
        )

    @pytest.mark.parametrize("motion_delta", [HAND_MOTION_FLOOR, 0.05, 0.10, 0.5])
    def test_above_floor_runs_pipeline(self, motion_delta: float) -> None:
        """Frames with real motion above the floor run the full contour pipeline."""
        frame = _frame_with_hand_like_blobs()
        hands = detect_hands_nir(frame, motion_delta=motion_delta)
        assert len(hands) >= 1, (
            f"motion_delta={motion_delta} above floor={HAND_MOTION_FLOOR} "
            f"must run the contour pipeline and return ≥1 hand"
        )


class TestEmpiricalNoiseFloorRegressionPin:
    """L3: the floor must reject the empirical 2026-05-02 fleet-revival values.

    All 3 Pis (desk/room/overhead) reported motion_delta in the 0.013-0.015
    band when the operator was absent. The floor must reject this entire
    band so the false-positive ir_hand_active signal stops driving wrong
    PRESENT inferences in the BayesianPresenceEngine.
    """

    @pytest.mark.parametrize("noise_value", [0.013, 0.014, 0.0143, 0.015])
    def test_observed_noise_floor_band_rejected(self, noise_value: float) -> None:
        frame = _frame_with_hand_like_blobs()
        hands = detect_hands_nir(frame, motion_delta=noise_value)
        assert hands == [], (
            f"motion_delta={noise_value} (within observed noise band 0.013-0.015) "
            f"must produce no hand detections; HAND_MOTION_FLOOR={HAND_MOTION_FLOOR} "
            f"must remain above this band."
        )

    def test_floor_value_is_above_observed_noise(self) -> None:
        """Defensive: if anyone ever lowers HAND_MOTION_FLOOR below 0.015, the
        empirical noise band would once again pass and the false-positive class
        returns. This test pins the relationship explicitly."""
        OBSERVED_MAX_NOISE = 0.015
        assert HAND_MOTION_FLOOR > OBSERVED_MAX_NOISE, (
            f"HAND_MOTION_FLOOR={HAND_MOTION_FLOOR} must remain above observed "
            f"sensor-noise band ({OBSERVED_MAX_NOISE}) or false-positive hands return"
        )
