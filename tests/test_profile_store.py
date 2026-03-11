"""Tests for the profile store — Qdrant-backed profile fact search and digest access."""
import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from shared.profile_store import ProfileStore, COLLECTION, VECTOR_DIM


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_profile(facts_per_dim=2):
    """Build a minimal UserProfile-like object for testing."""
    from agents.profiler import ProfileFact, ProfileDimension, UserProfile

    dims = []
    for dim_name in ["work_patterns", "identity"]:
        facts = [
            ProfileFact(
                dimension=dim_name,
                key=f"fact_{i}",
                value=f"value_{i}",
                confidence=0.8,
                source="test",
                evidence="test evidence",
            )
            for i in range(facts_per_dim)
        ]
        dims.append(ProfileDimension(name=dim_name, summary=f"{dim_name} summary", facts=facts))

    return UserProfile(
        name="Test",
        summary="Test profile",
        dimensions=dims,
        sources_processed=["test"],
        version=1,
        updated_at="2026-01-01",
    )


def _mock_store():
    """Create a ProfileStore with a mocked Qdrant client."""
    store = ProfileStore()
    store._client = MagicMock()
    return store


# ── Collection management ────────────────────────────────────────────────────

def test_ensure_collection_creates_when_missing():
    store = _mock_store()
    mock_collections = MagicMock()
    mock_collections.collections = []
    store._client.get_collections.return_value = mock_collections

    store.ensure_collection()
    store._client.create_collection.assert_called_once()
    args = store._client.create_collection.call_args
    assert args[0][0] == COLLECTION


def test_ensure_collection_skips_when_exists():
    store = _mock_store()
    mock_col = MagicMock()
    mock_col.name = COLLECTION
    mock_collections = MagicMock()
    mock_collections.collections = [mock_col]
    store._client.get_collections.return_value = mock_collections

    store.ensure_collection()
    store._client.create_collection.assert_not_called()


# ── Index profile ────────────────────────────────────────────────────────────

@patch("shared.config.embed_batch")
def test_index_profile_upserts_facts(mock_embed):
    store = _mock_store()
    profile = _make_profile(facts_per_dim=3)

    # 2 dims * 3 facts = 6 vectors
    mock_embed.return_value = [[0.1] * VECTOR_DIM] * 6
    store._client.scroll.return_value = ([], None)

    count = store.index_profile(profile)
    assert count == 6
    mock_embed.assert_called_once()
    # Called with search_document prefix
    assert mock_embed.call_args[1]["prefix"] == "search_document"
    store._client.upsert.assert_called()


@patch("shared.config.embed_batch")
def test_index_profile_empty(mock_embed):
    from agents.profiler import UserProfile
    store = _mock_store()
    profile = UserProfile(name="Empty", summary="", dimensions=[], sources_processed=[], version=1, updated_at="")

    count = store.index_profile(profile)
    assert count == 0
    mock_embed.assert_not_called()


@patch("shared.config.embed_batch")
def test_index_profile_deterministic_ids(mock_embed):
    store = _mock_store()
    profile = _make_profile(facts_per_dim=1)

    mock_embed.return_value = [[0.1] * VECTOR_DIM] * 2
    store._client.scroll.return_value = ([], None)

    store.index_profile(profile)

    # Verify deterministic IDs
    call_args = store._client.upsert.call_args
    points = call_args[0][1]  # Second positional arg is the points list
    expected_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, "profile-fact-work_patterns-fact_0"))
    ids = [p.id for p in points]
    assert expected_id in ids


@patch("shared.config.embed_batch")
def test_index_profile_batches_large_profiles(mock_embed):
    """Profiles with >100 facts are upserted in batches."""
    store = _mock_store()
    from agents.profiler import ProfileFact, ProfileDimension, UserProfile

    facts = [
        ProfileFact(
            dimension="work_patterns", key=f"fact_{i}", value=f"v{i}",
            confidence=0.5, source="test", evidence="test",
        )
        for i in range(150)
    ]
    profile = UserProfile(
        name="Big",
        summary="",
        dimensions=[ProfileDimension(name="work_patterns", summary="", facts=facts)],
        sources_processed=[],
        version=1,
        updated_at="",
    )

    mock_embed.return_value = [[0.1] * VECTOR_DIM] * 150
    store._client.scroll.return_value = ([], None)
    store.index_profile(profile)

    # Should be called twice: batch of 100 + batch of 50
    assert store._client.upsert.call_count == 2


# ── Search ───────────────────────────────────────────────────────────────────

@patch("shared.config.embed")
def test_search_returns_results(mock_embed):
    store = _mock_store()
    mock_embed.return_value = [0.1] * VECTOR_DIM

    mock_point = MagicMock()
    mock_point.payload = {
        "dimension": "work_patterns",
        "key": "tool_preference",
        "value": "uses uv",
        "confidence": 0.9,
    }
    mock_point.score = 0.95

    mock_result = MagicMock()
    mock_result.points = [mock_point]
    store._client.query_points.return_value = mock_result

    results = store.search("preferred tools")
    assert len(results) == 1
    assert results[0]["dimension"] == "work_patterns"
    assert results[0]["key"] == "tool_preference"
    assert results[0]["score"] == 0.95
    mock_embed.assert_called_once_with("preferred tools", prefix="search_query")


@patch("shared.config.embed")
def test_search_with_dimension_filter(mock_embed):
    store = _mock_store()
    mock_embed.return_value = [0.1] * VECTOR_DIM
    mock_result = MagicMock()
    mock_result.points = []
    store._client.query_points.return_value = mock_result

    store.search("test", dimension="work_patterns")
    call_kwargs = store._client.query_points.call_args
    assert call_kwargs[1]["query_filter"] is not None


@patch("shared.config.embed")
def test_search_without_dimension_filter(mock_embed):
    store = _mock_store()
    mock_embed.return_value = [0.1] * VECTOR_DIM
    mock_result = MagicMock()
    mock_result.points = []
    store._client.query_points.return_value = mock_result

    store.search("test")
    call_kwargs = store._client.query_points.call_args
    assert call_kwargs[1]["query_filter"] is None


@patch("shared.config.embed")
def test_search_empty_results(mock_embed):
    store = _mock_store()
    mock_embed.return_value = [0.1] * VECTOR_DIM
    mock_result = MagicMock()
    mock_result.points = []
    store._client.query_points.return_value = mock_result

    results = store.search("nonexistent topic")
    assert results == []


# ── Digest access ────────────────────────────────────────────────────────────

def test_get_digest_returns_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("shared.profile_store.PROFILES_DIR", tmp_path)
    store = _mock_store()
    assert store.get_digest() is None


def test_get_digest_loads_valid_file(tmp_path, monkeypatch):
    monkeypatch.setattr("shared.profile_store.PROFILES_DIR", tmp_path)
    digest = {
        "generated_at": "2026-01-01T00:00:00",
        "profile_version": 1,
        "total_facts": 100,
        "overall_summary": "Test summary",
        "dimensions": {
            "work_patterns": {"summary": "Work patterns summary", "fact_count": 50, "avg_confidence": 0.8},
        },
    }
    (tmp_path / "ryan-digest.json").write_text(json.dumps(digest))

    store = _mock_store()
    result = store.get_digest()
    assert result is not None
    assert result["total_facts"] == 100
    assert result["dimensions"]["work_patterns"]["summary"] == "Work patterns summary"


def test_get_digest_handles_corrupt_file(tmp_path, monkeypatch):
    monkeypatch.setattr("shared.profile_store.PROFILES_DIR", tmp_path)
    (tmp_path / "ryan-digest.json").write_text("not valid json")

    store = _mock_store()
    assert store.get_digest() is None


def test_get_dimension_summary_returns_summary(tmp_path, monkeypatch):
    monkeypatch.setattr("shared.profile_store.PROFILES_DIR", tmp_path)
    digest = {
        "dimensions": {
            "work_patterns": {"summary": "Work patterns narrative here", "fact_count": 50},
        },
    }
    (tmp_path / "ryan-digest.json").write_text(json.dumps(digest))

    store = _mock_store()
    summary = store.get_dimension_summary("work_patterns")
    assert summary == "Work patterns narrative here"


def test_get_dimension_summary_returns_none_for_missing_dim(tmp_path, monkeypatch):
    monkeypatch.setattr("shared.profile_store.PROFILES_DIR", tmp_path)
    digest = {"dimensions": {}}
    (tmp_path / "ryan-digest.json").write_text(json.dumps(digest))

    store = _mock_store()
    assert store.get_dimension_summary("nonexistent") is None


def test_get_dimension_summary_returns_none_without_digest(tmp_path, monkeypatch):
    monkeypatch.setattr("shared.profile_store.PROFILES_DIR", tmp_path)
    store = _mock_store()
    assert store.get_dimension_summary("work_patterns") is None


# ── Digest generation ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_digest_structure(tmp_path, monkeypatch):
    """generate_digest produces correct structure."""
    monkeypatch.setattr("agents.profiler.PROFILES_DIR", tmp_path)
    from agents.profiler import generate_digest

    profile = _make_profile(facts_per_dim=5)

    # Mock the Agent to avoid real LLM calls
    mock_result = MagicMock()
    mock_result.output = "Test summary for dimension."

    async def mock_run(*args, **kwargs):
        return mock_result

    with patch("agents.profiler.Agent") as MockAgent:
        mock_agent_instance = MagicMock()
        mock_agent_instance.run = mock_run
        MockAgent.return_value = mock_agent_instance

        digest = await generate_digest(profile)

    assert "generated_at" in digest
    assert digest["profile_version"] == 1
    assert digest["total_facts"] == 10  # 2 dims * 5 facts
    assert "work_patterns" in digest["dimensions"]
    assert "identity" in digest["dimensions"]
    assert digest["dimensions"]["work_patterns"]["fact_count"] == 5

    # Verify file was saved
    saved = json.loads((tmp_path / "ryan-digest.json").read_text())
    assert saved["total_facts"] == 10


# ── Stale point cleanup ────────────────────────────────────────────────────

def test_cleanup_stale_points_removes_orphans():
    store = _mock_store()

    stale_pt = MagicMock()
    stale_pt.id = "stale-id"
    stale_pt.payload = {"dimension": "old_dim", "key": "old_key"}

    current_pt = MagicMock()
    current_pt.id = "current-id"
    current_pt.payload = {"dimension": "work_patterns", "key": "fact_0"}

    store._client.scroll.return_value = ([stale_pt, current_pt], None)

    current_keys = {("work_patterns", "fact_0")}
    removed = store._cleanup_stale_points(current_keys)
    assert removed == 1
    store._client.delete.assert_called_once()


def test_cleanup_stale_points_no_orphans():
    store = _mock_store()

    pt = MagicMock()
    pt.id = "current-id"
    pt.payload = {"dimension": "work_patterns", "key": "fact_0"}

    store._client.scroll.return_value = ([pt], None)

    current_keys = {("work_patterns", "fact_0")}
    removed = store._cleanup_stale_points(current_keys)
    assert removed == 0
    store._client.delete.assert_not_called()


def test_cleanup_stale_points_pagination():
    store = _mock_store()

    pt1 = MagicMock()
    pt1.id = "id1"
    pt1.payload = {"dimension": "stale", "key": "gone"}

    pt2 = MagicMock()
    pt2.id = "id2"
    pt2.payload = {"dimension": "work_patterns", "key": "fact_0"}

    store._client.scroll.side_effect = [
        ([pt1], "offset1"),
        ([pt2], None),
    ]

    current_keys = {("work_patterns", "fact_0")}
    removed = store._cleanup_stale_points(current_keys)
    assert removed == 1
    assert store._client.scroll.call_count == 2


@patch("shared.config.embed_batch")
def test_index_profile_triggers_cleanup(mock_embed):
    store = _mock_store()
    profile = _make_profile(facts_per_dim=1)
    mock_embed.return_value = [[0.1] * VECTOR_DIM] * 2
    store._client.scroll.return_value = ([], None)

    store.index_profile(profile)
    store._client.scroll.assert_called()
