"""Tests for chunk compressor."""

from __future__ import annotations

from agents.fortress.chunks import ChunkCompressor, Severity
from agents.fortress.schema import FastFortressState


def _state(**kw) -> FastFortressState:
    defaults = dict(
        timestamp=0,
        game_tick=100000,
        year=1,
        season=0,
        month=0,
        day=0,
        fortress_name="Test",
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


class TestChunkCompressor:
    def test_returns_4_chunks(self):
        c = ChunkCompressor()
        chunks = c.compress(_state())
        assert len(chunks) == 4

    def test_chunks_are_strings(self):
        c = ChunkCompressor()
        for chunk in c.compress(_state()):
            assert isinstance(chunk, str)
            assert len(chunk) > 0

    def test_food_chunk_nominal(self):
        c = ChunkCompressor()
        chunks = c.compress(_state(food_count=200, drink_count=100, population=20))
        assert "Food:" in chunks[0]
        assert "CRITICAL" not in chunks[0]

    def test_food_chunk_critical(self):
        c = ChunkCompressor()
        chunks = c.compress(_state(food_count=10, drink_count=5, population=20))
        assert "CRITICAL" in chunks[0]

    def test_population_chunk_content(self):
        c = ChunkCompressor()
        chunks = c.compress(_state(population=20, idle_dwarf_count=5, most_stressed_value=0))
        assert "Pop: 20" in chunks[1]
        assert "content" in chunks[1]

    def test_population_chunk_stressed(self):
        c = ChunkCompressor()
        chunks = c.compress(_state(most_stressed_value=60000))
        assert "stressed" in chunks[1]

    def test_safety_chunk_threats(self):
        c = ChunkCompressor()
        chunks = c.compress(_state(active_threats=30))
        assert "CRITICAL" in chunks[3]
        assert "30" in chunks[3]

    def test_safety_chunk_clear(self):
        c = ChunkCompressor()
        chunks = c.compress(_state(active_threats=0))
        assert "clear" in chunks[3]

    def test_delta_computation(self):
        c = ChunkCompressor()
        prev = _state(food_count=200)
        curr = _state(food_count=180)
        chunks = c.compress(curr, prev)
        assert "-20" in chunks[0]

    def test_delta_rising(self):
        c = ChunkCompressor()
        prev = _state(food_count=100)
        curr = _state(food_count=130)
        chunks = c.compress(curr, prev)
        assert "+30" in chunks[0]


class TestSeverity:
    def test_nominal(self):
        c = ChunkCompressor()
        sev = c.severity(_state())
        assert sev["food"] == Severity.NOMINAL
        assert sev["safety"] == Severity.NOMINAL

    def test_food_critical(self):
        c = ChunkCompressor()
        sev = c.severity(_state(drink_count=10, population=20))
        assert sev["food"] == Severity.CRITICAL

    def test_safety_warning(self):
        c = ChunkCompressor()
        sev = c.severity(_state(active_threats=5))
        assert sev["safety"] == Severity.WARNING

    def test_population_critical(self):
        c = ChunkCompressor()
        sev = c.severity(_state(most_stressed_value=150_000))
        assert sev["population"] == Severity.CRITICAL
