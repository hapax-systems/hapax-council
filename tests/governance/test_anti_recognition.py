"""Tests for shared.governance.scrim_invariants.anti_recognition.

OQ-02 bound 1 oracle. The fail-CLOSED-on-everything-uncertain semantics
is the regression pin: cost asymmetry means a false-negative (identity
LEAK) is a constitutional violation; a false-positive (effect rejected)
is a nuisance. Tests verify every fail-CLOSED branch.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest  # noqa: TC002

from shared.governance.scrim_invariants.anti_recognition import (
    DEFAULT_IDENTIFIABILITY_THRESHOLD,
    SCHEMA_VERSION,
    AntiRecognitionThresholds,
    RecognitionScore,
    cosine_similarity,
    evaluate_frame,
    load_operator_embedding,
)


@dataclass
class _StubFaceResult:
    detected: bool = False
    count: int = 0
    embeddings: list[np.ndarray] | None = None


class _StubDetector:
    """Test stub matching FaceEmbeddingProvider Protocol."""

    def __init__(
        self,
        result: _StubFaceResult | None = None,
        raises: Exception | None = None,
    ) -> None:
        self._result = result or _StubFaceResult()
        self._raises = raises

    def detect(self, image, *, camera_role="unknown"):
        if self._raises is not None:
            raise self._raises
        return self._result


def _frame() -> np.ndarray:
    return np.zeros((360, 640, 3), dtype=np.uint8)


def _operator_embedding() -> np.ndarray:
    rng = np.random.default_rng(seed=42)
    return rng.standard_normal(512).astype(np.float32)


def _thresholds() -> AntiRecognitionThresholds:
    return AntiRecognitionThresholds(
        identifiability_max=DEFAULT_IDENTIFIABILITY_THRESHOLD,
    )


class TestCosineSimilarity:
    def test_identical_vectors_return_one(self) -> None:
        v = np.array([1.0, 0.0, 0.0])
        assert cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors_return_zero(self) -> None:
        a = np.array([1.0, 0.0, 0.0])
        b = np.array([0.0, 1.0, 0.0])
        assert cosine_similarity(a, b) == pytest.approx(0.0)

    def test_opposite_vectors_return_neg_one(self) -> None:
        v = np.array([1.0, 0.0, 0.0])
        assert cosine_similarity(v, -v) == pytest.approx(-1.0)

    def test_zero_norm_returns_zero(self) -> None:
        zero = np.zeros(3)
        nonzero = np.array([1.0, 0.0, 0.0])
        assert cosine_similarity(zero, nonzero) == 0.0
        assert cosine_similarity(nonzero, zero) == 0.0


class TestEvaluateFrameFailClosedBranches:
    def test_no_operator_embedding_fails_closed(self) -> None:
        score = evaluate_frame(_frame(), _StubDetector(), None, _thresholds())
        assert not score.passed
        assert score.fail_reason == "operator_embedding_unavailable"

    def test_detector_exception_fails_closed(self) -> None:
        score = evaluate_frame(
            _frame(),
            _StubDetector(raises=RuntimeError("model unavailable")),
            _operator_embedding(),
            _thresholds(),
        )
        assert not score.passed
        assert score.fail_reason == "detector_exception_fail_closed"

    def test_faces_detected_without_embeddings_fails_closed(self) -> None:
        """Detector said faces are present but produced no embedding —
        we can't compare; treat as identifiable until proven otherwise."""
        score = evaluate_frame(
            _frame(),
            _StubDetector(_StubFaceResult(detected=True, count=1, embeddings=[])),
            _operator_embedding(),
            _thresholds(),
        )
        assert not score.passed
        assert score.fail_reason == "faces_detected_without_embeddings_fail_closed"


class TestEvaluateFramePassBranches:
    def test_no_faces_detected_passes(self) -> None:
        """A frame with no faces has no identity to leak — pass."""
        score = evaluate_frame(
            _frame(),
            _StubDetector(_StubFaceResult(detected=False)),
            _operator_embedding(),
            _thresholds(),
        )
        assert score.passed
        assert score.face_count == 0

    def test_face_below_threshold_passes(self) -> None:
        """Embedding orthogonal to operator → similarity ~ 0 → pass."""
        op_emb = _operator_embedding()
        # Orthogonal embedding (random with no projection onto op_emb).
        rng = np.random.default_rng(seed=99)
        other_emb = rng.standard_normal(512).astype(np.float32)
        # Project out the op_emb component to guarantee orthogonality.
        other_emb -= (np.dot(other_emb, op_emb) / np.dot(op_emb, op_emb)) * op_emb
        score = evaluate_frame(
            _frame(),
            _StubDetector(_StubFaceResult(detected=True, count=1, embeddings=[other_emb])),
            op_emb,
            _thresholds(),
        )
        assert score.passed
        assert abs(score.max_similarity) < 0.01  # noqa: PLR2004
        assert score.face_count == 1


class TestEvaluateFrameFailBranches:
    def test_face_above_threshold_fails(self) -> None:
        """Embedding identical to operator → similarity = 1 → fail."""
        op_emb = _operator_embedding()
        score = evaluate_frame(
            _frame(),
            _StubDetector(_StubFaceResult(detected=True, count=1, embeddings=[op_emb])),
            op_emb,
            _thresholds(),
        )
        assert not score.passed
        assert score.max_similarity == pytest.approx(1.0)
        assert score.fail_reason == "operator_face_identifiable"

    def test_one_high_similarity_face_among_many_fails(self) -> None:
        """ANY face crossing threshold fails the whole frame — max-pool."""
        op_emb = _operator_embedding()
        rng = np.random.default_rng(seed=7)
        random_emb = rng.standard_normal(512).astype(np.float32)
        # Project out op_emb so it's near-orthogonal.
        random_emb -= (np.dot(random_emb, op_emb) / np.dot(op_emb, op_emb)) * op_emb
        score = evaluate_frame(
            _frame(),
            _StubDetector(
                _StubFaceResult(
                    detected=True,
                    count=2,
                    embeddings=[random_emb, op_emb],  # one orthogonal + one matching
                )
            ),
            op_emb,
            _thresholds(),
        )
        assert not score.passed
        assert score.max_similarity == pytest.approx(1.0)
        assert score.face_count == 2


class TestAntiRecognitionThresholds:
    def test_load_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="thresholds missing"):
            AntiRecognitionThresholds.load(tmp_path / "missing.json")

    def test_load_schema_mismatch_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "wrong.json"
        path.write_text(json.dumps({"schema_version": 999, "identifiability_max": 0.28}))
        with pytest.raises(ValueError, match="schema mismatch"):
            AntiRecognitionThresholds.load(path)

    def test_load_threshold_above_safety_ceiling_raises(self, tmp_path: Path) -> None:
        """Sanity invariant: τ_anti_recognition ≤ τ_present − 0.05.
        Catches misconfiguration where bound-1 stops flagging leaks
        before they become recognizable."""
        path = tmp_path / "too_loose.json"
        # 0.40 (τ_present) is the absolute ceiling; 0.36 is above the
        # safety-margined ceiling of 0.35.
        path.write_text(json.dumps({"schema_version": SCHEMA_VERSION, "identifiability_max": 0.36}))
        with pytest.raises(ValueError, match="exceeds safety ceiling"):
            AntiRecognitionThresholds.load(path)

    def test_load_valid_threshold(self, tmp_path: Path) -> None:
        path = tmp_path / "ok.json"
        path.write_text(json.dumps({"schema_version": SCHEMA_VERSION, "identifiability_max": 0.28}))
        thresholds = AntiRecognitionThresholds.load(path)
        assert thresholds.identifiability_max == 0.28


class TestOperatorEmbeddingLoad:
    def test_missing_returns_none(self, tmp_path: Path) -> None:
        result = load_operator_embedding(tmp_path / "missing.npy")
        assert result is None

    def test_valid_loads(self, tmp_path: Path) -> None:
        path = tmp_path / "op.npy"
        emb = _operator_embedding()
        np.save(path, emb)
        loaded = load_operator_embedding(path)
        assert loaded is not None
        np.testing.assert_array_equal(loaded, emb)


class TestRecognitionScoreShape:
    def test_score_dataclass_is_frozen(self) -> None:
        score = RecognitionScore(
            max_similarity=0.1,
            face_count=1,
            passed=True,
            threshold=0.28,
        )
        with pytest.raises(Exception):  # noqa: B017 — frozen dataclass
            score.passed = False  # type: ignore[misc]


class TestSafetyCeilingConstants:
    def test_default_threshold_within_safety_ceiling(self) -> None:
        """The shipped default must satisfy the load-time invariant."""
        from shared.governance.scrim_invariants.anti_recognition import (
            TAU_PRESENT_REFERENCE,
            TAU_PRESENT_SAFETY_MARGIN,
        )

        ceiling = TAU_PRESENT_REFERENCE - TAU_PRESENT_SAFETY_MARGIN
        assert ceiling >= DEFAULT_IDENTIFIABILITY_THRESHOLD
