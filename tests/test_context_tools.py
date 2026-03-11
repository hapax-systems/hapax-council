"""Tests for the context tools — on-demand operator context for agents."""

from unittest.mock import MagicMock, patch

import pytest

from shared.context_tools import (
    get_context_tools,
    get_profile_summary,
    lookup_constraints,
    lookup_patterns,
    lookup_sufficiency_requirements,
    search_profile,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _mock_ctx():
    """Create a mock RunContext."""
    ctx = MagicMock()
    ctx.deps = MagicMock()
    return ctx


# ── Tool list ────────────────────────────────────────────────────────────────


def test_get_context_tools_returns_five():
    tools = get_context_tools()
    assert len(tools) == 5
    names = [t.__name__ for t in tools]
    assert "lookup_constraints" in names
    assert "lookup_patterns" in names
    assert "search_profile" in names
    assert "get_profile_summary" in names
    assert "lookup_sufficiency_requirements" in names


def test_all_tools_have_docstrings():
    """Pydantic AI uses docstrings as tool descriptions — all must exist."""
    for tool_fn in get_context_tools():
        assert tool_fn.__doc__, f"{tool_fn.__name__} missing docstring"
        assert len(tool_fn.__doc__) > 20, f"{tool_fn.__name__} docstring too short"


def test_all_tools_are_async():
    """All context tools must be async for Pydantic AI compatibility."""
    import asyncio

    for tool_fn in get_context_tools():
        assert asyncio.iscoroutinefunction(tool_fn), f"{tool_fn.__name__} is not async"


# ── lookup_constraints ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_lookup_constraints_all():
    ctx = _mock_ctx()
    result = await lookup_constraints(ctx)
    assert "Operator constraints" in result
    assert "rules)" in result


@pytest.mark.asyncio
async def test_lookup_constraints_filtered():
    ctx = _mock_ctx()
    result = await lookup_constraints(ctx, categories="python")
    assert "uv" in result.lower() or "type hints" in result.lower()


@pytest.mark.asyncio
async def test_lookup_constraints_empty_category():
    ctx = _mock_ctx()
    result = await lookup_constraints(ctx, categories="nonexistent_category")
    assert "No constraints found" in result


@pytest.mark.asyncio
async def test_lookup_constraints_multiple_categories():
    ctx = _mock_ctx()
    result = await lookup_constraints(ctx, categories="python,docker")
    assert "Operator constraints" in result


# ── lookup_patterns ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_lookup_patterns_all():
    ctx = _mock_ctx()
    result = await lookup_patterns(ctx)
    assert "Operator patterns" in result
    assert "items)" in result


@pytest.mark.asyncio
async def test_lookup_patterns_filtered():
    ctx = _mock_ctx()
    result = await lookup_patterns(ctx, categories="development")
    # Should have some development patterns
    assert "Operator patterns" in result or "No patterns found" in result


@pytest.mark.asyncio
async def test_lookup_patterns_empty_category():
    ctx = _mock_ctx()
    result = await lookup_patterns(ctx, categories="nonexistent_category")
    assert "No patterns found" in result


# ── search_profile ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_profile_returns_results():
    ctx = _mock_ctx()
    mock_results = [
        {
            "dimension": "tool_usage",
            "key": "tool_pref",
            "value": "uses uv",
            "confidence": 0.9,
            "score": 0.95,
        },
    ]
    with patch("shared.profile_store.ProfileStore") as MockStore:
        MockStore.return_value.search.return_value = mock_results
        result = await search_profile(ctx, query="preferred tools")

    assert "Profile facts" in result
    assert "tool_pref" in result
    assert "uses uv" in result


@pytest.mark.asyncio
async def test_search_profile_no_results():
    ctx = _mock_ctx()
    with patch("shared.profile_store.ProfileStore") as MockStore:
        MockStore.return_value.search.return_value = []
        result = await search_profile(ctx, query="nonexistent thing")

    assert "No profile facts found" in result


@pytest.mark.asyncio
async def test_search_profile_with_dimension():
    ctx = _mock_ctx()
    with patch("shared.profile_store.ProfileStore") as MockStore:
        MockStore.return_value.search.return_value = []
        await search_profile(ctx, query="test", dimension="workflow")

    call_kwargs = MockStore.return_value.search.call_args[1]
    assert call_kwargs["dimension"] == "workflow"


@pytest.mark.asyncio
async def test_search_profile_handles_error():
    ctx = _mock_ctx()
    with patch("shared.profile_store.ProfileStore", side_effect=Exception("connection refused")):
        result = await search_profile(ctx, query="test")

    assert "unavailable" in result.lower()


# ── get_profile_summary ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_profile_summary_overall():
    ctx = _mock_ctx()
    digest = {
        "total_facts": 100,
        "overall_summary": "Operator is a developer and musician.",
        "dimensions": {
            "workflow": {"fact_count": 50, "avg_confidence": 0.8, "summary": "Workflow summary"},
            "identity": {"fact_count": 30, "avg_confidence": 0.9, "summary": "Identity summary"},
        },
    }
    with patch("shared.profile_store.ProfileStore") as MockStore:
        MockStore.return_value.get_digest.return_value = digest
        result = await get_profile_summary(ctx)

    assert "100 facts" in result
    assert "Operator is a developer" in result
    assert "workflow: 50 facts" in result


@pytest.mark.asyncio
async def test_get_profile_summary_dimension():
    ctx = _mock_ctx()
    digest = {
        "dimensions": {
            "workflow": {
                "fact_count": 50,
                "avg_confidence": 0.8,
                "summary": "Detailed workflow narrative",
            },
        },
    }
    with patch("shared.profile_store.ProfileStore") as MockStore:
        MockStore.return_value.get_digest.return_value = digest
        result = await get_profile_summary(ctx, dimension="workflow")

    assert "Detailed workflow narrative" in result
    assert "50" in result


@pytest.mark.asyncio
async def test_get_profile_summary_missing_dimension():
    ctx = _mock_ctx()
    digest = {"dimensions": {"workflow": {"summary": "test"}}}
    with patch("shared.profile_store.ProfileStore") as MockStore:
        MockStore.return_value.get_digest.return_value = digest
        result = await get_profile_summary(ctx, dimension="nonexistent")

    assert "not found" in result.lower()
    assert "workflow" in result  # lists available dims


@pytest.mark.asyncio
async def test_get_profile_summary_no_digest():
    ctx = _mock_ctx()
    with patch("shared.profile_store.ProfileStore") as MockStore:
        MockStore.return_value.get_digest.return_value = None
        result = await get_profile_summary(ctx)

    assert "No profile digest available" in result
    assert "profiler --digest" in result


# ── lookup_sufficiency_requirements ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_lookup_sufficiency_requirements_returns_results():
    ctx = _mock_ctx()
    result = await lookup_sufficiency_requirements(ctx, axiom_id="executive_function")
    assert "sufficiency requirement" in result
    assert "executive_function" in result


@pytest.mark.asyncio
async def test_lookup_sufficiency_requirements_filter_by_level():
    ctx = _mock_ctx()
    result = await lookup_sufficiency_requirements(
        ctx, axiom_id="executive_function", level="system"
    )
    assert "system" in result
    # Should not contain component-only items
    assert "/component]" not in result


@pytest.mark.asyncio
async def test_lookup_sufficiency_requirements_no_axiom():
    ctx = _mock_ctx()
    result = await lookup_sufficiency_requirements(ctx, axiom_id="nonexistent_axiom")
    assert "not found" in result.lower()


@pytest.mark.asyncio
async def test_lookup_sufficiency_requirements_all_axioms():
    ctx = _mock_ctx()
    result = await lookup_sufficiency_requirements(ctx)
    # Should return results from at least executive_function
    assert "sufficiency requirement" in result
