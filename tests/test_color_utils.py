"""Tests for shared/color_utils.py — color normalization."""

from __future__ import annotations

import numpy as np

from shared.color_utils import normalize_color


def test_normalize_neutral_image():
    """Neutral lighting image is unchanged."""
    img = np.full((100, 100, 3), 128, dtype=np.uint8)
    result = normalize_color(img)
    np.testing.assert_array_equal(result, img)


def test_normalize_red_tint():
    """Red-tinted image is corrected toward neutral."""
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    img[:, :, 2] = 200  # Heavy red (BGR: B=0, G=0, R=200)
    img[:, :, 1] = 50
    img[:, :, 0] = 50

    result = normalize_color(img)
    # Red channel should be reduced, blue/green boosted
    assert result[:, :, 2].mean() < 200
    assert result[:, :, 0].mean() > 50


def test_normalize_dark_image():
    """Very dark image (avg < 1.0) is returned unchanged."""
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    result = normalize_color(img)
    np.testing.assert_array_equal(result, img)


def test_normalize_clamps_to_255():
    """Output is clamped to [0, 255]."""
    img = np.full((10, 10, 3), 250, dtype=np.uint8)
    img[:, :, 0] = 10  # Very low blue, high red/green
    result = normalize_color(img)
    assert result.max() <= 255
    assert result.min() >= 0
