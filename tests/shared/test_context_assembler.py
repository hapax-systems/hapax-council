"""Tests for ContextAssembler cached fragment assembly."""

from __future__ import annotations

from shared.context import ContextAssembler


class TestCachedAssembly:
    def test_goals_cached_within_ttl(self):
        call_count = 0

        def goals_fn():
            nonlocal call_count
            call_count += 1
            return [{"name": "Ship v2", "category": "primary"}]

        assembler = ContextAssembler(goals_fn=goals_fn)
        snap1 = assembler.snapshot()
        snap2 = assembler.snapshot()
        assert snap1.active_goals == snap2.active_goals
        assert call_count == 1  # Second call served from cache

    def test_goals_refreshed_after_ttl(self):
        call_count = 0

        def goals_fn():
            nonlocal call_count
            call_count += 1
            return [{"name": f"Goal {call_count}"}]

        assembler = ContextAssembler(goals_fn=goals_fn, goals_ttl=0.0)
        assembler.snapshot()
        assembler.snapshot()
        assert call_count == 2

    def test_health_cached_within_ttl(self):
        call_count = 0

        def health_fn():
            nonlocal call_count
            call_count += 1
            return {"status": "healthy"}

        assembler = ContextAssembler(health_fn=health_fn)
        assembler.snapshot()
        assembler.snapshot()
        assert call_count == 1

    def test_flush_clears_cache(self):
        call_count = 0

        def goals_fn():
            nonlocal call_count
            call_count += 1
            return []

        assembler = ContextAssembler(goals_fn=goals_fn)
        assembler.snapshot()
        assembler.flush()
        assembler.snapshot()
        assert call_count == 2
