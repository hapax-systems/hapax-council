"""Context system smoke tests — integration across all 3 loops.

Tests chunk compression, deliberation loop, observation tools,
spatial memory maintenance, configuration consistency, and
error recovery. All tests use mocks (no live LLM calls).

Batches:
  A: Chunk generation edge cases (5)
  B: Deliberation loop state transitions (5)
  C: ReAct tool-use cycle (6)
  D: Observation tools & budget (4)
  E: Spatial memory maintenance (3)
  F: Configuration consistency (2)
  G: Concurrent loop safety (3)
  H: LLM unavailability (2)
  I: Daemon lifecycle (2)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from agents.fortress.chunks import ChunkCompressor, Severity
from agents.fortress.config import DeliberationConfig, FortressConfig
from agents.fortress.deliberation import (
    _dispatch_tool,
    _parse_text_actions,
    _to_openai_tools,
    build_deliberation_prompt,
    run_deliberation,
)
from agents.fortress.observation import (
    check_announcements,
    check_military,
    check_nobles,
    check_work_orders,
    get_situation_chunks,
    recall_memory,
    scan_threats,
)
from agents.fortress.schema import (
    DwarfUnit,
    FastFortressState,
    FullFortressState,
    StockpileSummary,
    WealthSummary,
    Workshop,
)
from agents.fortress.spatial_memory import EntityMobility, SpatialMemoryStore
from agents.fortress.tools_registry import FORTRESS_TOOLS

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _fast(**kw) -> FastFortressState:
    defaults = dict(
        timestamp=0.0,
        game_tick=100000,
        year=1,
        season=0,
        month=0,
        day=5,
        fortress_name="SmokeTest",
        paused=False,
        population=20,
        food_count=200,
        drink_count=100,
        active_threats=0,
        job_queue_length=5,
        idle_dwarf_count=2,
        most_stressed_value=5000,
    )
    defaults.update(kw)
    return FastFortressState(**defaults)


def _full(**kw) -> FullFortressState:
    defaults = dict(
        timestamp=0.0,
        game_tick=100000,
        year=1,
        season=0,
        month=0,
        day=5,
        fortress_name="SmokeTest",
        paused=False,
        population=20,
        food_count=200,
        drink_count=100,
        active_threats=0,
        job_queue_length=5,
        idle_dwarf_count=2,
        most_stressed_value=5000,
        units=tuple(
            DwarfUnit(
                id=i,
                name=f"Dwarf {i}",
                profession="Peasant",
                skills=(),
                stress=5000,
                mood="normal",
                current_job="idle",
            )
            for i in range(20)
        ),
        stockpiles=StockpileSummary(food=200, drink=100, weapons=10),
        workshops=(
            Workshop(type="Still", x=60, y=100, z=178, is_active=True, current_job="Brewing"),
        ),
        wealth=WealthSummary(created=50000),
    )
    defaults.update(kw)
    return FullFortressState(**defaults)


# ===========================================================================
# Batch A: Chunk generation edge cases
# ===========================================================================


class TestBatchA:
    def test_a1_pop_zero(self):
        """ChunkCompressor handles population=0 without division error."""
        c = ChunkCompressor()
        chunks = c.compress(_fast(population=0, food_count=50, drink_count=25))
        assert len(chunks) == 4
        for chunk in chunks:
            assert isinstance(chunk, str)
            assert len(chunk) > 0

    def test_a2_famine_critical(self):
        """Zero food/drink triggers CRITICAL in chunks."""
        c = ChunkCompressor()
        chunks = c.compress(_fast(food_count=0, drink_count=0, population=10))
        assert "CRITICAL" in chunks[0]

    def test_a3_severity_boundaries(self):
        """Severity transitions at exact thresholds."""
        c = ChunkCompressor()
        # Food: pop*10 = warning, pop*5 = critical
        assert (
            c.severity(_fast(food_count=201, drink_count=101, population=20))["food"]
            == Severity.NOMINAL
        )
        assert (
            c.severity(_fast(food_count=199, drink_count=100, population=20))["food"]
            == Severity.WARNING
        )
        assert (
            c.severity(_fast(food_count=50, drink_count=39, population=20))["food"]
            == Severity.CRITICAL
        )
        # Safety
        assert c.severity(_fast(active_threats=0))["safety"] == Severity.NOMINAL
        assert c.severity(_fast(active_threats=1))["safety"] == Severity.WARNING
        assert c.severity(_fast(active_threats=21))["safety"] == Severity.CRITICAL
        # Population stress
        assert c.severity(_fast(most_stressed_value=49999))["population"] == Severity.NOMINAL
        assert c.severity(_fast(most_stressed_value=50001))["population"] == Severity.WARNING
        assert c.severity(_fast(most_stressed_value=100001))["population"] == Severity.CRITICAL

    def test_a4_delta_first_run(self):
        """First run (prev=None) produces no delta strings."""
        c = ChunkCompressor()
        chunks = c.compress(_fast(food_count=200), prev=None)
        # Should not contain "+N" or "-N" or "stable"
        assert "+200" not in chunks[0]
        assert "stable" not in chunks[0]

    def test_a5_delta_large_swings(self):
        """Large deltas appear in chunk text."""
        c = ChunkCompressor()
        prev = _fast(food_count=500)
        curr = _fast(food_count=50)
        chunks = c.compress(curr, prev)
        assert "-450" in chunks[0]

        prev2 = _fast(food_count=50)
        curr2 = _fast(food_count=500)
        chunks2 = c.compress(curr2, prev2)
        assert "+450" in chunks2[0]


# ===========================================================================
# Batch B: Deliberation loop state transitions
# ===========================================================================


class TestBatchB:
    def test_b1_prompt_has_system_and_user(self):
        """Prompt has exactly 2 messages: system + user."""
        msgs = build_deliberation_prompt("Fort", 5, 0, 1, ["a", "b", "c", "d"])
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"

    def test_b2_alerts_at_top(self):
        """CRITICAL chunks appear as alerts at top of user prompt."""
        chunks = ["[CRITICAL] Food: 0.", "Pop ok.", "Industry ok.", "Safety ok."]
        msgs = build_deliberation_prompt("Fort", 5, 0, 1, chunks)
        content = msgs[1]["content"]
        alert_pos = content.find("CRITICAL ALERTS")
        situation_pos = content.find("CURRENT SITUATION")
        assert alert_pos >= 0
        assert situation_pos >= 0
        assert alert_pos < situation_pos

    def test_b3_no_alerts_when_nominal(self):
        """No CRITICAL ALERTS section when all chunks nominal."""
        chunks = ["Food ok.", "Pop ok.", "Industry ok.", "Safety ok."]
        msgs = build_deliberation_prompt("Fort", 5, 0, 1, chunks)
        assert "CRITICAL ALERTS" not in msgs[1]["content"]

    def test_b4_recent_events_in_middle(self):
        """Recent events appear in the middle section."""
        msgs = build_deliberation_prompt(
            "Fort", 5, 0, 1, ["a", "b", "c", "d"], recent_events=["Siege arrived", "Migrant wave"]
        )
        content = msgs[1]["content"]
        assert "Siege arrived" in content
        assert "Migrant wave" in content

    def test_b5_season_names(self):
        """Season numbers map to names."""
        for season, name in [(0, "Spring"), (1, "Summer"), (2, "Autumn"), (3, "Winter")]:
            msgs = build_deliberation_prompt("Fort", 1, season, 1, ["a", "b", "c", "d"])
            assert name in msgs[1]["content"]


# ===========================================================================
# Batch C: ReAct tool-use cycle
# ===========================================================================


class TestBatchC:
    def test_c1_tool_conversion_all_12(self):
        """_to_openai_tools converts all 12 Anthropic tool definitions."""
        tools = _to_openai_tools(FORTRESS_TOOLS)
        assert len(tools) == 12
        for t in tools:
            assert t["type"] == "function"
            assert "name" in t["function"]
            assert "description" in t["function"]
            assert "parameters" in t["function"]

    def test_c2_dispatch_known_tool(self):
        """Known tools dispatch correctly."""
        table = {"check_stockpile": lambda category="food": f"Stock: {category}"}
        result = _dispatch_tool("check_stockpile", {"category": "drink"}, table)
        assert "drink" in result

    def test_c3_dispatch_unknown_tool(self):
        """Unknown tools return 'not available'."""
        result = _dispatch_tool("nonexistent", {}, {})
        assert "not available" in result

    def test_c4_dispatch_error_recovery(self):
        """Tool errors are caught and returned as strings."""
        table = {"bad": lambda: 1 / 0}
        result = _dispatch_tool("bad", {}, table)
        assert "Tool error" in result

    def test_c5_parse_actions(self):
        """ACTION: lines parsed from text."""
        text = "I think we should brew.\nACTION: import_orders library/basic\nDone."
        actions = _parse_text_actions(text)
        assert len(actions) == 1
        assert actions[0]["action"] == "import_orders"

    def test_c6_parse_no_actions(self):
        """No ACTION: lines produces empty list."""
        actions = _parse_text_actions("Everything looks fine.")
        assert len(actions) == 0


# ===========================================================================
# Batch D: Observation tools & budget
# ===========================================================================


class TestBatchD:
    def test_d1_free_tools_no_budget(self):
        """Free tools don't consume attention budget."""
        from agents.fortress.attention import AttentionBudget

        budget = AttentionBudget()
        budget.reset(20, 1)
        initial = budget.total_remaining

        state = _fast()
        memory = SpatialMemoryStore()
        scan_threats(state, memory, budget)
        check_announcements(state, memory, budget)

        assert budget.total_remaining == initial  # unchanged

    def test_d2_new_tools_edge_cases(self):
        """New observation tools handle edge cases."""
        from agents.fortress.attention import AttentionBudget

        budget = AttentionBudget()
        budget.reset(20, 1)
        state = _full(squads=(), nobles=(), job_queue_length=0)
        memory = SpatialMemoryStore()

        mil = check_military(state, memory, budget)
        assert "no squads" in mil.lower()

        nob = check_nobles(state, memory, budget)
        assert "no positions" in nob.lower()

        wk = check_work_orders(state, memory, budget)
        assert "0" in wk

    def test_d3_recall_unknown_patch(self):
        """Recalling unknown patch returns 'No memory'."""
        memory = SpatialMemoryStore()
        result = recall_memory(memory, "nonexistent", 100000)
        assert "No memory" in result

    def test_d4_situation_chunks_returns_4_lines(self):
        """get_situation_chunks returns exactly 4 numbered lines."""
        c = ChunkCompressor()
        result = get_situation_chunks(c, _fast())
        lines = result.strip().split("\n")
        assert len(lines) == 4
        assert lines[0].startswith("1.")


# ===========================================================================
# Batch E: Spatial memory maintenance
# ===========================================================================


class TestBatchE:
    def test_e1_empty_store_consolidate(self):
        """Consolidate on empty store produces no errors."""
        memory = SpatialMemoryStore()
        # Should not raise
        memory.consolidate(100000)

    def test_e2_empty_store_prune(self):
        """Prune on empty store produces no errors."""
        memory = SpatialMemoryStore()
        memory.prune(100000)

    def test_e3_observe_then_recall(self):
        """Observed patches can be recalled."""
        memory = SpatialMemoryStore()
        memory.observe(
            "workshop-1", "Still workshop, active, brewing", 100000, EntityMobility.STATIC
        )
        state, desc = memory.recall("workshop-1", 100001)
        assert desc is not None
        assert "Still" in desc


# ===========================================================================
# Batch F: Configuration consistency
# ===========================================================================


class TestBatchF:
    def test_f1_model_daily_routes_to_grounded(self):
        """Daily deliberation routes to local grounded model per grounding-act policy.

        Fortress deliberation is Hapax's governance act over its own world
        (T1 common-ground update, T4 Jemeinigkeit) — grounding-act per
        docs/research/2026-04-24-grounding-acts-operative-definition.md.
        Seasonal deliberation remains a strong route, but not a provider-prefixed
        escape path.
        """
        config = DeliberationConfig()
        assert config.model_daily == "local-fast"
        assert config.model_seasonal == "gemini-pro"

    def test_f2_severity_thresholds_match_chunks(self):
        """Config thresholds match chunk compressor logic."""
        config = DeliberationConfig()
        c = ChunkCompressor()
        # Food critical: config says pop*5, chunks.py checks pop*5
        state = _fast(food_count=99, drink_count=39, population=20)
        sev = c.severity(state)
        assert sev["food"] == Severity.CRITICAL
        # Verify config alignment
        assert config.food_critical_per_capita == 5
        assert state.food_count < state.population * config.food_critical_per_capita


# ===========================================================================
# Batch G: Concurrent loop safety
# ===========================================================================


class TestBatchG:
    def test_g1_chunk_compressor_stateless(self):
        """ChunkCompressor has no mutable state — safe for concurrent use."""
        c = ChunkCompressor()
        s1 = _fast(food_count=100)
        s2 = _fast(food_count=500)
        chunks1 = c.compress(s1)
        chunks2 = c.compress(s2)
        # Different inputs produce different outputs
        assert chunks1[0] != chunks2[0]

    def test_g2_memory_store_concurrent_observe_recall(self):
        """Memory store handles interleaved observe/recall."""
        memory = SpatialMemoryStore()
        memory.observe("p1", "desc1", 1000, EntityMobility.STATIC)
        memory.observe("p2", "desc2", 1001, EntityMobility.FAST)
        s1, d1 = memory.recall("p1", 1002)
        s2, d2 = memory.recall("p2", 1002)
        assert d1 is not None
        assert d2 is not None

    def test_g3_deliberation_config_frozen(self):
        """DeliberationConfig is frozen dataclass — immutable during runtime."""
        config = DeliberationConfig()
        with pytest.raises(Exception):
            config.max_iterations = 99  # type: ignore


# ===========================================================================
# Batch H: LLM unavailability
# ===========================================================================


class TestBatchH:
    @pytest.mark.asyncio
    async def test_h1_llm_import_error(self):
        """Deliberation handles LLM call failure gracefully."""
        with patch(
            "litellm.acompletion",
            new_callable=AsyncMock,
            side_effect=RuntimeError("model not available"),
        ):
            actions = await run_deliberation(
                state=_fast(),
                compressor=ChunkCompressor(),
                prev_state=None,
                config=DeliberationConfig(timeout_s=2.0),
            )
            assert actions == []

    @pytest.mark.asyncio
    async def test_h2_timeout_recovery(self):
        """Deliberation recovers from timeout."""

        async def slow_completion(*a, **kw):
            await asyncio.sleep(10)

        with patch("litellm.acompletion", new=slow_completion):
            actions = await run_deliberation(
                state=_fast(),
                compressor=ChunkCompressor(),
                prev_state=None,
                config=DeliberationConfig(timeout_s=0.1),
            )
            assert actions == []


# ===========================================================================
# Batch I: Daemon lifecycle
# ===========================================================================


class TestBatchI:
    def test_i1_fortress_config_has_deliberation(self):
        """FortressConfig includes DeliberationConfig."""
        config = FortressConfig()
        assert hasattr(config, "deliberation")
        assert isinstance(config.deliberation, DeliberationConfig)
        assert config.deliberation.max_iterations == 3

    def test_i2_death_detection(self):
        """is_fortress_dead correctly identifies dead fortress."""
        from agents.fortress.metrics import FortressSessionTracker

        tracker = FortressSessionTracker()
        assert tracker.is_fortress_dead(_fast(population=0))
        assert tracker.is_fortress_dead(_fast(food_count=0, drink_count=0))
        assert not tracker.is_fortress_dead(_fast(population=20, food_count=100, drink_count=50))
