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


# ── Defensive readers — non-dict JSON root ─────────────────────────────


import pytest


@pytest.mark.parametrize(
    "payload,kind",
    [("null", "null"), ('"a"', "string"), ("[1,2]", "list"), ("42", "int")],
)
def test_read_stimmung_raw_non_dict_returns_empty(tmp_path, payload, kind):
    """Pin _read_stimmung_raw against non-dict JSON. snapshot() and
    assemble() immediately call stimmung_raw.get('overall_stance') —
    a non-dict root previously raised AttributeError out of the
    enrichment-context assembly path."""
    stimmung_path = tmp_path / "stimmung.json"
    stimmung_path.write_text(payload)
    assembler = ContextAssembler(stimmung_path=stimmung_path)
    snap = assembler.snapshot()
    # Default stance is "nominal" when stimmung_raw is empty.
    assert snap.stimmung_stance == "nominal", f"non-dict root={kind} must yield default"
    assert snap.stimmung_raw == {}


@pytest.mark.parametrize(
    "payload,kind",
    [("null", "null"), ('"a"', "string"), ("[1,2]", "list"), ("42", "int")],
)
def test_read_imagination_non_dict_yields_empty_list(tmp_path, payload, kind):
    """Pin _read_imagination: non-dict imagination payload should yield
    an empty list, not [non-dict] which would crash downstream
    fragment.get(...) consumers."""
    imagination_path = tmp_path / "imagination.json"
    imagination_path.write_text(payload)
    assembler = ContextAssembler(imagination_path=imagination_path)
    snap = assembler.snapshot()
    assert snap.imagination_fragments == [], (
        f"non-dict root={kind} must yield empty list (not [non-dict])"
    )
