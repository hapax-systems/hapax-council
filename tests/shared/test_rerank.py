"""Unit tests for shared.rerank — self-contained, mocked cross-encoder."""

from __future__ import annotations

from unittest.mock import patch

from shared import rerank as rerank_mod
from shared.rerank import rerank


class _Point:
    """Minimal stand-in for a Qdrant ScoredPoint."""

    def __init__(self, pid: int, text: str) -> None:
        self.id = pid
        self.payload = {"text": text}


def _points() -> list[_Point]:
    return [_Point(0, "alpha"), _Point(1, "bravo"), _Point(2, "charlie")]


def test_disabled_returns_original_order_truncated() -> None:
    pts = _points()
    with patch.object(rerank_mod.config, "RERANK_ENABLED", False):
        out = rerank("q", pts, top_k=2)
    assert [p.id for p in out] == [0, 1]  # original cosine order, top_k


def test_empty_input_returns_empty() -> None:
    with patch.object(rerank_mod.config, "RERANK_ENABLED", True):
        assert rerank("q", [], top_k=5) == []


def test_enabled_reorders_by_score_and_truncates() -> None:
    pts = _points()

    class _FakeModel:
        # charlie (idx 2) highest, alpha (idx 0) lowest
        def predict(self, pairs):
            return [0.1, 0.5, 0.9]

    with (
        patch.object(rerank_mod.config, "RERANK_ENABLED", True),
        patch.object(rerank_mod, "_get_model", return_value=_FakeModel()),
    ):
        out = rerank("q", pts, top_k=2)
    assert [p.id for p in out] == [2, 1]  # reranked top_k


def test_model_unavailable_fails_open() -> None:
    pts = _points()
    with (
        patch.object(rerank_mod.config, "RERANK_ENABLED", True),
        patch.object(rerank_mod, "_get_model", return_value=None),
    ):
        out = rerank("q", pts, top_k=3)
    assert [p.id for p in out] == [0, 1, 2]  # original order


def test_scoring_error_fails_open() -> None:
    pts = _points()

    class _BoomModel:
        def predict(self, pairs):
            raise RuntimeError("cuda oom")

    with (
        patch.object(rerank_mod.config, "RERANK_ENABLED", True),
        patch.object(rerank_mod, "_get_model", return_value=_BoomModel()),
    ):
        out = rerank("q", pts, top_k=2)
    assert [p.id for p in out] == [0, 1]  # original order on fault


def test_no_candidate_text_fails_open() -> None:
    pts = [_Point(0, ""), _Point(1, "")]

    class _FakeModel:
        def predict(self, pairs):  # pragma: no cover — must not be reached
            raise AssertionError("should not score textless candidates")

    with (
        patch.object(rerank_mod.config, "RERANK_ENABLED", True),
        patch.object(rerank_mod, "_get_model", return_value=_FakeModel()),
    ):
        out = rerank("q", pts, top_k=2)
    assert [p.id for p in out] == [0, 1]
