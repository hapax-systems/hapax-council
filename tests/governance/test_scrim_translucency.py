"""Tests for shared.governance.scrim_invariants.scrim_translucency.

OQ-02 bound 2 oracle. The conjunctive aggregate-by-min semantics is the
core regression pin: every B2 failure mode must independently fail the
score.

Fixtures cover the three documented B2 failure modes (research §4):
  - white-saturation (D-25 reference; brightness-ceiling avoided this)
  - dark crush (vignette + noise to floor)
  - single-hue field (material→single-hue)

Plus the positive: a synthetic "studio with structure" reference that
must pass.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest  # noqa: TC002

from shared.governance.scrim_invariants.scrim_translucency import (
    DEFAULT_REFERENCE_EDGE_DENSITY,
    SCHEMA_VERSION,
    TranslucencyScore,
    TranslucencyThresholds,
    compute_edge_density_ratio,
    compute_entropy_floor_score,
    compute_luminance_variance_score,
    evaluate,
)


def _white_frame(h: int = 360, w: int = 640) -> np.ndarray:
    return np.full((h, w, 3), 255, dtype=np.uint8)


def _black_frame(h: int = 360, w: int = 640) -> np.ndarray:
    return np.zeros((h, w, 3), dtype=np.uint8)


def _single_hue_frame(h: int = 360, w: int = 640, hue=(120, 80, 200)) -> np.ndarray:
    """Solid color (default purple-magenta) — entropy collapses on all channels."""
    f = np.zeros((h, w, 3), dtype=np.uint8)
    f[..., 0] = hue[0]
    f[..., 1] = hue[1]
    f[..., 2] = hue[2]
    return f


def _structured_studio_frame(h: int = 360, w: int = 640, seed: int = 42) -> np.ndarray:
    """Synthetic reference: random noise + grid lines + variable patches.

    Stands in for "studio with gear + people + content" until a calibration
    fixture exists. Has edges, regional variance, full-spectrum channel use.
    """
    rng = np.random.default_rng(seed)
    f = rng.integers(0, 256, size=(h, w, 3), dtype=np.uint8)
    # Add hard horizontal and vertical lines to guarantee edges.
    f[h // 4 :: h // 8, :, :] = 255
    f[:, w // 4 :: w // 8, :] = 0
    return f


def _default_thresholds() -> TranslucencyThresholds:
    """Permissive thresholds for tests so the structured-studio frame passes
    but the all-white / single-hue frames fail."""
    return TranslucencyThresholds(
        edge_density_min=0.3,
        luminance_variance_min=0.05,
        entropy_floor_min=0.4,
    )


class TestEdgeDensityRatio:
    def test_white_frame_yields_zero(self) -> None:
        assert compute_edge_density_ratio(_white_frame()) == 0.0

    def test_black_frame_yields_zero(self) -> None:
        assert compute_edge_density_ratio(_black_frame()) == 0.0

    def test_single_hue_yields_zero(self) -> None:
        assert compute_edge_density_ratio(_single_hue_frame()) == 0.0

    def test_structured_frame_yields_positive(self) -> None:
        score = compute_edge_density_ratio(_structured_studio_frame())
        assert score > 0.5

    def test_clipped_to_unit_interval(self) -> None:
        score = compute_edge_density_ratio(_structured_studio_frame())
        assert 0.0 <= score <= 1.0

    def test_invalid_reference_raises(self) -> None:
        with pytest.raises(ValueError, match="reference_density"):
            compute_edge_density_ratio(_white_frame(), reference_density=0.0)


class TestLuminanceVarianceScore:
    def test_white_frame_yields_zero(self) -> None:
        # All cells are flat → min variance = 0.
        assert compute_luminance_variance_score(_white_frame()) == 0.0

    def test_black_frame_yields_zero(self) -> None:
        assert compute_luminance_variance_score(_black_frame()) == 0.0

    def test_structured_frame_yields_positive(self) -> None:
        score = compute_luminance_variance_score(_structured_studio_frame())
        assert score > 0.05  # noisy fixture has high per-cell variance

    def test_grid_arg_subdivides(self) -> None:
        # 1x1 grid → whole-frame variance; 8x8 → finer granularity.
        # On the structured frame, finer grid should not yield HIGHER min
        # variance (more cells = more chance of low-variance corner).
        coarse = compute_luminance_variance_score(_structured_studio_frame(), grid=(1, 1))
        fine = compute_luminance_variance_score(_structured_studio_frame(), grid=(8, 8))
        assert fine <= coarse + 0.001  # tolerance for randomness

    def test_invalid_grid_raises(self) -> None:
        with pytest.raises(ValueError, match="grid"):
            compute_luminance_variance_score(_white_frame(), grid=(0, 4))


class TestEntropyFloorScore:
    def test_white_frame_yields_zero(self) -> None:
        assert compute_entropy_floor_score(_white_frame()) == 0.0

    def test_single_hue_yields_zero(self) -> None:
        # Each channel collapsed to a single value → entropy ≈ 0.
        assert compute_entropy_floor_score(_single_hue_frame()) == 0.0

    def test_structured_frame_yields_high(self) -> None:
        score = compute_entropy_floor_score(_structured_studio_frame())
        assert score > 0.7  # uniform random covers histogram densely

    def test_grayscale_frame_supported(self) -> None:
        # 2D frame should still work via the single-channel branch.
        gray = _structured_studio_frame()[..., 0]
        score = compute_entropy_floor_score(gray)
        assert 0.0 < score <= 1.0


class TestEvaluateAggregate:
    def test_white_frame_fails_all_components(self) -> None:
        score = evaluate(_white_frame(), _default_thresholds())
        assert not score.passed
        assert score.aggregate == 0.0
        # All three components score 0 — failing_component returns one of them.
        assert score.failing_component in (
            "edge_density_ratio",
            "luminance_variance_score",
            "entropy_floor_score",
        )

    def test_single_hue_fails_entropy_first(self) -> None:
        """Single-hue field collapses entropy below threshold; aggregate
        is min so entropy_floor_score is the failing axis."""
        score = evaluate(_single_hue_frame(), _default_thresholds())
        assert not score.passed
        assert score.entropy_floor_score == 0.0

    def test_structured_studio_frame_passes(self) -> None:
        score = evaluate(_structured_studio_frame(), _default_thresholds())
        assert score.passed, (
            f"structured studio frame should pass; got {score} (failing={score.failing_component})"
        )
        assert score.aggregate > 0.05

    def test_aggregate_is_min_of_components(self) -> None:
        """Conjunctive guarantee: aggregate = min(...) so weakest axis dominates."""
        score = evaluate(_structured_studio_frame(), _default_thresholds())
        assert score.aggregate == min(
            score.edge_density_ratio,
            score.luminance_variance_score,
            score.entropy_floor_score,
        )

    def test_failing_component_is_none_when_passed(self) -> None:
        score = evaluate(_structured_studio_frame(), _default_thresholds())
        assert score.failing_component is None


class TestTranslucencyThresholds:
    def test_load_missing_file_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "missing.json"
        with pytest.raises(FileNotFoundError, match="thresholds missing"):
            TranslucencyThresholds.load(path)

    def test_load_schema_mismatch_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "wrong_schema.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 999,
                    "edge_density_min": 0.3,
                    "luminance_variance_min": 0.05,
                    "entropy_floor_min": 0.4,
                }
            )
        )
        with pytest.raises(ValueError, match="schema mismatch"):
            TranslucencyThresholds.load(path)

    def test_load_valid_file(self, tmp_path: Path) -> None:
        path = tmp_path / "thresholds.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "edge_density_min": 0.3,
                    "luminance_variance_min": 0.05,
                    "entropy_floor_min": 0.4,
                }
            )
        )
        thresholds = TranslucencyThresholds.load(path)
        assert thresholds.edge_density_min == 0.3
        assert thresholds.luminance_variance_min == 0.05
        assert thresholds.entropy_floor_min == 0.4
        assert thresholds.schema_version == SCHEMA_VERSION


class TestTranslucencyScoreShape:
    def test_score_dataclass_is_frozen(self) -> None:
        score = TranslucencyScore(
            edge_density_ratio=0.5,
            luminance_variance_score=0.3,
            entropy_floor_score=0.7,
            aggregate=0.3,
            passed=True,
        )
        with pytest.raises(Exception):  # noqa: B017 — frozen dataclass raises FrozenInstanceError
            score.aggregate = 0.99  # type: ignore[misc]


class TestDefaultReferenceEdgeDensity:
    def test_default_reference_within_documented_range(self) -> None:
        """Math-only fallback per module — should be in the 0.05–0.15 range
        for typical livestream frames."""
        assert 0.05 <= DEFAULT_REFERENCE_EDGE_DENSITY <= 0.15
