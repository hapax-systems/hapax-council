"""Live LLM spot checks for query agents.

These tests make real LLM API calls and are SLOW (~10-30s each).
Skipped by default. Run with: uv run pytest -m llm -v

Requires:
- LiteLLM running at localhost:4000
- Test data in test-data/ (run scripts/extract-test-data.py first)
"""
from __future__ import annotations

import shutil
from unittest.mock import patch

import pytest

from cockpit.query_dispatch import run_query
from tests.query_integration._helpers import (
    POPULATED_PROFILES,
    POPULATED_DEV_STORY_DB,
    EMPTY_PROFILES,
    EMPTY_DEV_STORY_DB,
    skip_if_missing,
)

pytestmark = pytest.mark.llm


# ── Populated state ──────────────────────────────────────────────────────────


class TestDevStoryLLM:
    def setup_method(self):
        skip_if_missing(POPULATED_DEV_STORY_DB)

    async def test_commit_query_returns_markdown(self):
        result = await run_query("dev_story", "what files changed most recently?")
        assert len(result.markdown) > 50
        assert result.agent_type == "dev_story"

    async def test_session_query_returns_content(self):
        result = await run_query("dev_story", "show me recent session patterns")
        assert len(result.markdown) > 50


class TestSystemOpsLLM:
    def setup_method(self):
        skip_if_missing(POPULATED_PROFILES)

    async def test_health_query(self):
        result = await run_query("system_ops", "what is the health trend?")
        assert len(result.markdown) > 50
        assert result.agent_type == "system_ops"

    async def test_drift_query(self):
        result = await run_query("system_ops", "are there any drift items?")
        assert len(result.markdown) > 50


class TestKnowledgeLLM:
    def setup_method(self):
        skip_if_missing(POPULATED_PROFILES)

    async def test_briefing_query(self):
        result = await run_query("knowledge", "what did the briefing say?")
        assert len(result.markdown) > 50
        assert result.agent_type == "knowledge"

    async def test_goals_query(self):
        result = await run_query("knowledge", "what are my current goals?")
        assert len(result.markdown) > 50
        assert result.agent_type == "knowledge"


# ── Empty state ──────────────────────────────────────────────────────────────


class TestEmptyStateLLM:
    """Verify agents explicitly surface data limitations on empty state.

    Patches PROFILES_DIR to point at the empty test data directory.
    For dev_story, also copies the empty DB into the empty profiles dir
    so the factory function finds dev-story.db at the expected path.
    """

    def setup_method(self):
        skip_if_missing(EMPTY_PROFILES, allow_empty=True)
        skip_if_missing(EMPTY_DEV_STORY_DB)
        # Copy empty dev-story.db into the empty profiles dir so the factory finds it
        self._db_copy = EMPTY_PROFILES / "dev-story.db"
        if not self._db_copy.exists():
            shutil.copy2(EMPTY_DEV_STORY_DB, self._db_copy)
        # Patch PROFILES_DIR in both modules
        self._patches = [
            patch("shared.config.PROFILES_DIR", EMPTY_PROFILES),
            patch("cockpit.query_dispatch.PROFILES_DIR", EMPTY_PROFILES),
        ]
        for p in self._patches:
            p.start()

    def teardown_method(self):
        for p in self._patches:
            p.stop()
        # Clean up the copied db
        if hasattr(self, "_db_copy") and self._db_copy.exists():
            self._db_copy.unlink()

    async def test_dev_story_empty_surfaces_limitation(self):
        result = await run_query("dev_story", "show me the development timeline")
        md = result.markdown.lower()
        assert any(
            phrase in md
            for phrase in ["no data", "not populated", "no sessions", "no commits", "empty", "unavailable"]
        ), f"Expected empty-state message, got: {result.markdown[:200]}"

    async def test_system_ops_empty_surfaces_limitation(self):
        result = await run_query("system_ops", "what is the health status?")
        md = result.markdown.lower()
        assert any(
            phrase in md
            for phrase in ["no data", "no results", "empty", "not available", "no health"]
        ), f"Expected empty-state message, got: {result.markdown[:200]}"
