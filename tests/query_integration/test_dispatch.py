"""Integration tests for query dispatch classification accuracy."""
from __future__ import annotations

import pytest

from cockpit.query_dispatch import classify_query


class TestDevStoryClassification:
    """Queries that should route to dev_story."""

    @pytest.mark.parametrize("query,expected", [
        ("show me commit history for the cockpit module", "dev_story"),
        ("what files changed most in the last week", "dev_story"),
        ("how many sessions were there yesterday", "dev_story"),
        ("what's the average session duration", "dev_story"),
        ("show git activity by author", "dev_story"),
        ("what development arc are we on", "dev_story"),
        ("correlate commits with session length", "dev_story"),
        ("what was the longest coding session", "dev_story"),
        ("show me the git timeline", "dev_story"),
        ("how has the codebase pattern changed over time", "dev_story"),
        ("tell me the story of this feature", "dev_story"),
        ("what code churn happened recently", "dev_story"),
        ("how many tokens did we use in sessions", "dev_story"),
    ])
    def test_routes_to_dev_story(self, query, expected):
        assert classify_query(query) == expected


class TestSystemOpsClassification:
    """Queries that should route to system_ops."""

    @pytest.mark.parametrize("query,expected", [
        ("what is the current health status", "system_ops"),
        ("which docker containers are running", "system_ops"),
        ("how much did we spend on LLM costs this week", "system_ops"),
        ("are there any drift items with high severity", "system_ops"),
        ("show me the health trend over the last day", "system_ops"),
        ("what GPU memory is being used", "system_ops"),
        ("which systemd timers are active", "system_ops"),
        ("how many qdrant collections exist", "system_ops"),
        ("what's the infrastructure manifest say about ports", "system_ops"),
        ("show me degraded health checks", "system_ops"),
        ("what services are running", "system_ops"),
        ("show me the status of docker containers", "system_ops"),
        ("how much vram are we using", "system_ops"),
        ("what langfuse metrics do we have", "system_ops"),
        ("is the disk running low", "system_ops"),
        ("what model is ollama running", "system_ops"),
        ("show me failed health checks", "system_ops"),
        ("what uptime do we have", "system_ops"),
        ("show me qdrant collection stats", "system_ops"),
        ("what's the infrastructure status", "system_ops"),
    ])
    def test_routes_to_system_ops(self, query, expected):
        assert classify_query(query) == expected


class TestKnowledgeClassification:
    """Queries that should route to knowledge."""

    @pytest.mark.parametrize("query,expected", [
        ("search for documents about API design", "knowledge"),
        ("what did the briefing say today", "knowledge"),
        ("find emails from last week about the project", "knowledge"),
        ("search my obsidian notes for meeting prep", "knowledge"),
        ("what are my current goals", "knowledge"),
        ("show me the latest digest", "knowledge"),
        ("search my memory for voice pipeline", "knowledge"),
        ("find documents from google drive about architecture", "knowledge"),
        ("what does my profile say about communication style", "knowledge"),
        ("search for facts about the system", "knowledge"),
        ("find calendar events related to the project", "knowledge"),
        ("what knowledge do we have about this topic", "knowledge"),
        ("show me youtube recommendations", "knowledge"),
        ("what gmail messages are relevant", "knowledge"),
        ("search the vault for architecture notes", "knowledge"),
        ("what does the rag system know", "knowledge"),
        ("find notes about recommendations", "knowledge"),
        ("search my context for past decisions", "knowledge"),
    ])
    def test_routes_to_knowledge(self, query, expected):
        assert classify_query(query) == expected


class TestEdgeCases:
    """Ambiguous and edge-case queries."""

    def test_empty_query_defaults_to_dev_story(self):
        assert classify_query("") == "dev_story"

    def test_no_keywords_defaults_to_dev_story(self):
        assert classify_query("tell me everything") == "dev_story"

    def test_no_overlap_defaults_to_dev_story(self):
        assert classify_query("the quick brown fox jumps over the lazy dog") == "dev_story"

    def test_infrastructure_routes_to_system_ops(self):
        assert classify_query("what changed in the infrastructure this week") == "system_ops"

    def test_single_strong_keyword_dev_story(self):
        assert classify_query("show me commits") == "dev_story"

    def test_single_strong_keyword_system_ops(self):
        assert classify_query("what is the health") == "system_ops"

    def test_single_strong_keyword_knowledge(self):
        assert classify_query("search for documents") == "knowledge"

    def test_multiple_system_ops_keywords(self):
        # "health", "docker", "container"
        assert classify_query("health of docker containers") == "system_ops"

    def test_multiple_dev_story_keywords(self):
        # "git", "history", "code", "commit"
        assert classify_query("git history and code commits") == "dev_story"

    def test_multiple_knowledge_keywords(self):
        # "search", "document", "find", "vault"
        assert classify_query("search documents and find notes in vault") == "knowledge"

    def test_tie_defaults_to_first_agent(self):
        # "code" (dev_story=1) + "document" (knowledge=1) = tie
        # First agent in dict order wins
        result = classify_query("code document")
        assert result == "dev_story"  # dev_story comes first in _AGENTS

    def test_system_ops_beat_dev_story(self):
        # "docker", "status", "service" (system_ops=3) vs "code" (dev_story=1)
        assert classify_query("docker status service code") == "system_ops"

    def test_knowledge_beat_dev_story_with_multiple_keywords(self):
        # "search", "document", "find" (knowledge=3) vs "code" (dev_story=1)
        assert classify_query("search documents find code") == "knowledge"

    def test_substring_matching_can_cause_unexpected_routing(self):
        # "history" contains "story" (dev_story keyword)
        # "related" contains "arc" (dev_story keyword)
        # "search" + "chrome" (knowledge=2) vs "story", "arc", "history" (dev_story=3)
        assert classify_query("search my chrome history for related pages") == "dev_story"

    def test_system_ops_beat_knowledge_in_tie(self):
        # "scout" (knowledge=1) and "port" (substring in "report", sys_ops=1)
        # system_ops comes after dev_story in dict, so on tie system_ops wins
        assert classify_query("what did the scout report recommend") == "system_ops"
