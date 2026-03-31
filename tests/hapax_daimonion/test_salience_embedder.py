"""Tests for the salience embedder."""

from __future__ import annotations

import numpy as np


class TestEmbedder:
    def test_unavailable_returns_zero_vector(self) -> None:
        from agents.hapax_daimonion.salience.embedder import Embedder

        embedder = Embedder.__new__(Embedder)
        embedder._model = None
        embedder._dim = 256
        embedder._model_name = "test"

        result = embedder.embed("hello world")
        assert result.shape == (256,)
        assert result.dtype == np.float32

    def test_embed_batch_empty(self) -> None:
        from agents.hapax_daimonion.salience.embedder import Embedder

        embedder = Embedder.__new__(Embedder)
        embedder._model = None
        embedder._dim = 256
        embedder._model_name = "test"

        result = embedder.embed_batch([])
        assert result.shape == (0, 256)

    def test_available_false_when_no_model(self) -> None:
        from agents.hapax_daimonion.salience.embedder import Embedder

        embedder = Embedder.__new__(Embedder)
        embedder._model = None
        embedder._dim = 256
        embedder._model_name = "test"

        assert not embedder.available

    def test_unavailable_zero_dim_defaults_to_256(self) -> None:
        from agents.hapax_daimonion.salience.embedder import Embedder

        embedder = Embedder.__new__(Embedder)
        embedder._model = None
        embedder._dim = 0
        embedder._model_name = "test"

        result = embedder.embed("hello")
        assert result.shape == (256,)

    def test_embed_batch_unavailable_returns_zeros(self) -> None:
        from agents.hapax_daimonion.salience.embedder import Embedder

        embedder = Embedder.__new__(Embedder)
        embedder._model = None
        embedder._dim = 256
        embedder._model_name = "test"

        result = embedder.embed_batch(["a", "b", "c"])
        assert result.shape == (3, 256)
        assert np.all(result == 0.0)
