"""Tests for Qdrant retrieval compression — adaptive limits."""

from __future__ import annotations

from shared.knowledge_search import _adaptive_limit


class TestAdaptiveLimit:
    def test_voice_pipeline_reduces_limit(self):
        assert _adaptive_limit(default=10, pipeline="voice") == 3

    def test_local_tier_reduces_limit(self):
        assert _adaptive_limit(default=10, tier="LOCAL") == 3

    def test_capable_tier_keeps_default(self):
        assert _adaptive_limit(default=10, tier="CAPABLE") == 10

    def test_no_context_keeps_default(self):
        assert _adaptive_limit(default=10) == 10

    def test_profile_voice_limit(self):
        assert _adaptive_limit(default=5, pipeline="voice") == 2

    def test_profile_default_limit(self):
        assert _adaptive_limit(default=5) == 5
