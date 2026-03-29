"""Tests for enrollment validation functions.

Tests pairwise similarity, outlier detection, threshold testing,
and stability report generation.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np
import pytest

from agents.hapax_daimonion.enrollment import (
    compute_pairwise_similarity,
    detect_outliers,
    threshold_test,
    write_stability_report,
)


def _random_unit_vector(dim: int = 512, rng: np.random.Generator | None = None) -> np.ndarray:
    """Return a random unit vector of given dimension."""
    if rng is None:
        rng = np.random.default_rng()
    v = rng.standard_normal(dim)
    return v / np.linalg.norm(v)


def _similar_vectors(base: np.ndarray, n: int, noise_scale: float = 0.1) -> list[np.ndarray]:
    """Return n vectors near base with additive noise, each normalized."""
    rng = np.random.default_rng(42)
    results = []
    for _ in range(n):
        noisy = base + rng.standard_normal(base.shape) * noise_scale
        noisy = noisy / np.linalg.norm(noisy)
        results.append(noisy)
    return results


class TestPairwiseSimilarity:
    """Tests for compute_pairwise_similarity."""

    def test_identical_vectors(self) -> None:
        """Identical vectors should have mean ~1.0 and stddev ~0.0."""
        v = _random_unit_vector(512, rng=np.random.default_rng(0))
        embeddings = [v.copy() for _ in range(5)]
        result = compute_pairwise_similarity(embeddings)
        assert result["mean"] == pytest.approx(1.0, abs=1e-6)
        assert result["stddev"] == pytest.approx(0.0, abs=1e-6)

    def test_orthogonal_vectors(self) -> None:
        """Orthogonal vectors should have low mean similarity."""
        dim = 512
        embeddings = []
        for i in range(5):
            v = np.zeros(dim)
            v[i] = 1.0
            embeddings.append(v)
        result = compute_pairwise_similarity(embeddings)
        assert result["mean"] < 0.01

    def test_similar_vectors(self) -> None:
        """Similar vectors (low noise) should have mean >0.7, stddev <0.15."""
        base = _random_unit_vector(512, rng=np.random.default_rng(1))
        embeddings = _similar_vectors(base, 8, noise_scale=0.01)
        result = compute_pairwise_similarity(embeddings)
        assert result["mean"] > 0.7
        assert result["stddev"] < 0.15

    def test_returns_correct_keys(self) -> None:
        """Result dict should have exactly {min, max, mean, stddev}."""
        base = _random_unit_vector(512, rng=np.random.default_rng(2))
        embeddings = _similar_vectors(base, 4)
        result = compute_pairwise_similarity(embeddings)
        assert set(result.keys()) == {"min", "max", "mean", "stddev"}

    def test_two_embeddings_min_equals_max(self) -> None:
        """With exactly two embeddings, min==max and stddev==0."""
        rng = np.random.default_rng(3)
        embeddings = [_random_unit_vector(512, rng=rng) for _ in range(2)]
        result = compute_pairwise_similarity(embeddings)
        assert result["min"] == pytest.approx(result["max"], abs=1e-9)
        assert result["stddev"] == pytest.approx(0.0, abs=1e-9)


class TestOutlierDetection:
    """Tests for detect_outliers."""

    def test_clean_set_no_outliers(self) -> None:
        """A clean set of similar vectors should have no outliers."""
        base = _random_unit_vector(512, rng=np.random.default_rng(10))
        embeddings = _similar_vectors(base, 8, noise_scale=0.01)
        outliers = detect_outliers(embeddings, threshold=0.50)
        assert outliers == []

    def test_detects_orthogonal_outlier(self) -> None:
        """An orthogonal vector among similar vectors should be detected."""
        base = _random_unit_vector(512, rng=np.random.default_rng(20))
        embeddings = _similar_vectors(base, 7, noise_scale=0.01)
        outlier = np.zeros(512)
        outlier[0] = 1.0
        embeddings.append(outlier)
        outliers = detect_outliers(embeddings, threshold=0.50)
        assert len(embeddings) - 1 in outliers


class TestThresholdTest:
    """Tests for threshold_test."""

    def test_all_above_threshold(self) -> None:
        """When all embeddings are similar to average, samples_below_threshold==0."""
        base = _random_unit_vector(512, rng=np.random.default_rng(30))
        embeddings = _similar_vectors(base, 8, noise_scale=0.01)
        averaged = np.mean(embeddings, axis=0)
        averaged = averaged / np.linalg.norm(averaged)
        result = threshold_test(embeddings, averaged, accept_threshold=0.60)
        assert result["samples_below_threshold"] == 0

    def test_returns_correct_keys(self) -> None:
        """Result dict should have the expected keys."""
        base = _random_unit_vector(512, rng=np.random.default_rng(31))
        embeddings = _similar_vectors(base, 4, noise_scale=0.01)
        averaged = np.mean(embeddings, axis=0)
        averaged = averaged / np.linalg.norm(averaged)
        result = threshold_test(embeddings, averaged, accept_threshold=0.60)
        assert set(result.keys()) == {
            "accept_threshold",
            "samples_below_threshold",
            "min_similarity_to_average",
        }


class TestStabilityReport:
    """Tests for write_stability_report."""

    def test_writes_valid_json(self) -> None:
        """Should write a valid JSON file with the expected keys."""
        base = _random_unit_vector(512, rng=np.random.default_rng(40))
        embeddings = _similar_vectors(base, 6, noise_scale=0.01)
        averaged = np.mean(embeddings, axis=0)
        averaged = averaged / np.linalg.norm(averaged)

        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "enrollment_report.json"
            write_stability_report(embeddings, averaged, report_path=report_path, dropped_count=1)
            assert report_path.exists()
            data = json.loads(report_path.read_text())
            assert "pairwise" in data
            assert "threshold" in data
            assert "dropped_count" in data
            assert "sample_count" in data
            assert "timestamp" in data
            assert data["dropped_count"] == 1
            assert data["sample_count"] == 6
