"""Tests for chat persona similarity scorer."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np

from agents.hapax_daimonion.chat_persona_scorer import ChatPersonaScorer, _cosine_similarity


class TestCosine:
    def test_identical_vectors(self) -> None:
        a = np.array([1.0, 0.0, 0.0])
        assert _cosine_similarity(a, a) == 1.0

    def test_orthogonal_vectors(self) -> None:
        a = np.array([1.0, 0.0])
        b = np.array([0.0, 1.0])
        assert abs(_cosine_similarity(a, b)) < 1e-6

    def test_zero_vector(self) -> None:
        assert _cosine_similarity(np.zeros(3), np.ones(3)) == 0.0


class TestScorer:
    def test_no_fingerprint_returns_none(self, tmp_path: Path) -> None:
        scorer = ChatPersonaScorer(fingerprint_path=tmp_path / "missing.npy")
        assert scorer.score("hello") is None
        assert not scorer.enrolled

    def test_empty_text_returns_none(self, tmp_path: Path) -> None:
        fp = tmp_path / "fp.npy"
        np.save(fp, np.ones(768))
        scorer = ChatPersonaScorer(fingerprint_path=fp)
        assert scorer.score("") is None
        assert scorer.score("   ") is None

    def test_high_similarity_returns_true(self, tmp_path: Path) -> None:
        fp = tmp_path / "fp.npy"
        fingerprint = np.random.randn(768)
        fingerprint /= np.linalg.norm(fingerprint)
        np.save(fp, fingerprint)
        scorer = ChatPersonaScorer(fingerprint_path=fp)
        with patch("agents._config.embed_safe") as mock:
            mock.return_value = fingerprint.tolist()
            assert scorer.score("operator message") is True

    def test_low_similarity_returns_false(self, tmp_path: Path) -> None:
        fp = tmp_path / "fp.npy"
        fingerprint = np.zeros(768)
        fingerprint[0] = 1.0
        np.save(fp, fingerprint)
        scorer = ChatPersonaScorer(fingerprint_path=fp)
        opposite = np.zeros(768)
        opposite[1] = 1.0
        with patch("agents._config.embed_safe") as mock:
            mock.return_value = opposite.tolist()
            assert scorer.score("stranger message") is False

    def test_embed_failure_returns_none(self, tmp_path: Path) -> None:
        fp = tmp_path / "fp.npy"
        np.save(fp, np.ones(768))
        scorer = ChatPersonaScorer(fingerprint_path=fp)
        with patch("agents._config.embed_safe") as mock:
            mock.return_value = None
            assert scorer.score("hello") is None

    def test_enrolled_property(self, tmp_path: Path) -> None:
        fp = tmp_path / "fp.npy"
        np.save(fp, np.ones(768))
        scorer = ChatPersonaScorer(fingerprint_path=fp)
        assert scorer.enrolled


class TestEnroll:
    def test_enroll_creates_fingerprint(self, tmp_path: Path) -> None:
        out = tmp_path / "fp.npy"
        fake_embeddings = [np.random.randn(768).tolist() for _ in range(5)]
        with patch("agents._config.embed_batch") as mock:
            mock.return_value = fake_embeddings
            ChatPersonaScorer.enroll(["msg1", "msg2", "msg3"], output_path=out)
        assert out.exists()
        loaded = np.load(out)
        assert loaded.shape == (768,)
        assert abs(np.linalg.norm(loaded) - 1.0) < 1e-6

    def test_enroll_empty_raises(self, tmp_path: Path) -> None:
        import pytest

        with pytest.raises(ValueError, match="at least 1"):
            ChatPersonaScorer.enroll([], output_path=tmp_path / "fp.npy")
