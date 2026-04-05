"""Tests for content resolution diversity — recency penalty prevents monotonic lock-on."""

from collections import deque
from unittest.mock import MagicMock, patch


class TestRecencyPenalty:
    def test_fresh_query_returns_top_result(self):
        """With no recent history, resolver returns the highest-scoring document."""
        from agents.reverie._content_resolvers import resolve_knowledge_recall

        mock_points = [
            _make_point("doc-a", 0.9, "Alpha content text here"),
            _make_point("doc-b", 0.85, "Beta content text here"),
            _make_point("doc-c", 0.8, "Gamma content text here"),
        ]
        recent: deque[str] = deque(maxlen=10)

        with _patch_qdrant(mock_points), _patch_embed(), _patch_inject() as injected:
            result = resolve_knowledge_recall("test narrative", 0.5, recent_ids=recent)

        assert result is True
        assert "Alpha content" in injected[0]
        assert len(recent) == 1

    def test_repeated_query_avoids_recent_document(self):
        """When top result was recently returned, resolver picks the next-best."""
        from agents.reverie._content_resolvers import resolve_knowledge_recall

        mock_points = [
            _make_point("doc-a", 0.9, "Alpha content text here"),
            _make_point("doc-b", 0.85, "Beta content text here"),
            _make_point("doc-c", 0.8, "Gamma content text here"),
        ]
        recent: deque[str] = deque(["doc-a"], maxlen=10)

        with _patch_qdrant(mock_points), _patch_embed(), _patch_inject() as injected:
            result = resolve_knowledge_recall("test narrative", 0.5, recent_ids=recent)

        assert result is True
        assert "Beta content" in injected[0]

    def test_all_recent_falls_through_to_best(self):
        """When all results are recent, still returns best (don't return nothing)."""
        from agents.reverie._content_resolvers import resolve_knowledge_recall

        mock_points = [
            _make_point("doc-a", 0.9, "Alpha content text here"),
            _make_point("doc-b", 0.85, "Beta content text here"),
        ]
        recent: deque[str] = deque(["doc-a", "doc-b"], maxlen=10)

        with _patch_qdrant(mock_points), _patch_embed(), _patch_inject() as injected:
            result = resolve_knowledge_recall("test narrative", 0.5, recent_ids=recent)

        assert result is True
        assert "Alpha content" in injected[0]

    def test_dedup_by_source_filename(self):
        """Multiple chunks from same file should be deduped before scoring."""
        from agents.reverie._content_resolvers import resolve_knowledge_recall

        mock_points = [
            _make_point("doc-a", 0.9, "Alpha chunk 0", filename="notes.md"),
            _make_point("doc-a2", 0.88, "Alpha chunk 1", filename="notes.md"),
            _make_point("doc-b", 0.85, "Beta content", filename="other.md"),
        ]
        recent: deque[str] = deque(maxlen=10)

        with _patch_qdrant(mock_points), _patch_embed(), _patch_inject() as injected:
            result = resolve_knowledge_recall("test narrative", 0.5, recent_ids=recent)

        assert result is True
        assert "Alpha chunk 0" in injected[0]

    def test_recent_ids_updated_after_resolution(self):
        """Resolver appends selected document ID to recent deque."""
        from agents.reverie._content_resolvers import resolve_knowledge_recall

        mock_points = [_make_point("doc-x", 0.9, "X content")]
        recent: deque[str] = deque(maxlen=10)

        with _patch_qdrant(mock_points), _patch_embed(), _patch_inject():
            resolve_knowledge_recall("test narrative", 0.5, recent_ids=recent)

        assert "doc-x" in recent


# ── Test helpers ──────────────────────────────────────────────────────────


def _make_point(point_id, score, text, filename=None):
    """Create a mock Qdrant ScoredPoint."""
    pt = MagicMock()
    pt.id = point_id
    pt.score = score
    pt.payload = {"text": text}
    if filename:
        pt.payload["filename"] = filename
    return pt


def _patch_qdrant(points):
    """Patch get_qdrant to return mock points."""
    mock_client = MagicMock()
    mock_result = MagicMock()
    mock_result.points = points
    mock_client.query_points.return_value = mock_result
    return patch("agents.reverie._content_resolvers.get_qdrant", return_value=mock_client)


def _patch_embed():
    """Patch embed_safe to return a dummy vector."""
    return patch("agents.reverie._content_resolvers.embed_safe", return_value=[0.1] * 768)


def _patch_inject():
    """Patch _inject_recalled_text and capture what was injected."""
    captured = []

    def side_effect(source_suffix, text, level):
        captured.append(text)
        return True

    p = patch(
        "agents.reverie._content_resolvers._inject_recalled_text",
        side_effect=side_effect,
    )
    captured_ref = captured

    class PatchContext:
        def __enter__(self_inner):
            p.__enter__()
            return captured_ref

        def __exit__(self_inner, *args):
            p.__exit__(*args)

    return PatchContext()
