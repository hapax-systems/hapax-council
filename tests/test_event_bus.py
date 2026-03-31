"""Tests for logos.event_bus, flow_external, InstrumentedQdrantClient, and related."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from logos.event_bus import EventBus, FlowEvent, emit_llm_call, set_global_bus

# ── EventBus core ─────────────────────────────────────────────────────────────


class TestEventBusEmitRecent:
    def test_emit_and_recent_roundtrip(self):
        bus = EventBus(maxlen=10)
        ev = FlowEvent(kind="llm.call", source="a", target="b", label="test")
        bus.emit(ev)
        assert bus.recent() == [ev]

    def test_ring_buffer_overflow(self):
        bus = EventBus(maxlen=3)
        events = [
            FlowEvent(kind="llm.call", source="a", target="b", label=str(i)) for i in range(5)
        ]
        for e in events:
            bus.emit(e)
        recent = bus.recent()
        assert len(recent) == 3
        assert recent[0].label == "2"
        assert recent[-1].label == "4"

    def test_recent_since_filtering(self):
        bus = EventBus(maxlen=100)
        old = FlowEvent(kind="llm.call", source="a", target="b", label="old", ts=100.0)
        new = FlowEvent(kind="llm.call", source="a", target="b", label="new", ts=200.0)
        bus.emit(old)
        bus.emit(new)
        filtered = bus.recent(since=150.0)
        assert len(filtered) == 1
        assert filtered[0].label == "new"

    def test_recent_since_none_returns_all(self):
        bus = EventBus(maxlen=100)
        bus.emit(FlowEvent(kind="x", source="a", target="b", label="1"))
        bus.emit(FlowEvent(kind="x", source="a", target="b", label="2"))
        assert len(bus.recent(since=None)) == 2


# ── Subscribe async iteration ────────────────────────────────────────────────


class TestSubscription:
    @pytest.mark.asyncio
    async def test_subscribe_receives_events(self):
        bus = EventBus()
        sub = bus.subscribe()
        ev = FlowEvent(kind="llm.call", source="a", target="b", label="test")
        bus.emit(ev)
        received = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
        assert received == ev
        await sub.aclose()

    @pytest.mark.asyncio
    async def test_subscriber_cleanup_on_aclose(self):
        bus = EventBus()
        sub = bus.subscribe()
        assert len(bus._subscribers) == 1
        await sub.aclose()
        assert len(bus._subscribers) == 0

    @pytest.mark.asyncio
    async def test_full_queue_does_not_block_emit(self):
        bus = EventBus()
        sub = bus.subscribe()
        # Fill the queue (maxsize=50)
        for i in range(60):
            bus.emit(FlowEvent(kind="x", source="a", target="b", label=str(i)))
        # Bus should still work — overflow silently dropped
        assert len(bus.recent()) == 60
        await sub.aclose()


# ── emit_llm_call convenience ─────────────────────────────────────────────────


class TestEmitLlmCall:
    def test_emits_when_global_bus_set(self):
        bus = EventBus()
        set_global_bus(bus)
        try:
            emit_llm_call("test-agent", "claude-sonnet", duration_ms=42.0)
            events = bus.recent()
            assert len(events) == 1
            assert events[0].kind == "llm.call"
            assert events[0].source == "test-agent"
            assert events[0].target == "llm"
            assert events[0].label == "claude-sonnet"
            assert events[0].duration_ms == 42.0
        finally:
            set_global_bus(None)  # type: ignore[arg-type]

    def test_noop_when_no_global_bus(self):
        set_global_bus(None)  # type: ignore[arg-type]
        # Should not raise
        emit_llm_call("agent", "model")


# ── build_external_nodes ──────────────────────────────────────────────────────


class TestBuildExternalNodes:
    def test_creates_nodes_for_active_kinds(self):
        from logos.api.flow_external import build_external_nodes

        bus = EventBus()
        now = time.time()
        bus.emit(FlowEvent(kind="llm.call", source="agent-x", target="llm", label="claude", ts=now))
        bus.emit(
            FlowEvent(
                kind="qdrant.op", source="agent-y", target="qdrant", label="search/coll", ts=now
            )
        )

        nodes, edges = build_external_nodes(bus, since=now - 10)
        node_ids = {n["id"] for n in nodes}
        assert "llm" in node_ids
        assert "qdrant" in node_ids
        assert "pi_fleet" not in node_ids
        assert len(edges) == 2

    def test_skips_nodes_with_no_events(self):
        from logos.api.flow_external import build_external_nodes

        bus = EventBus()
        nodes, edges = build_external_nodes(bus)
        assert nodes == []
        assert edges == []


# ── InstrumentedQdrantClient ─────────────────────────────────────────────────


class TestInstrumentedQdrantClient:
    def test_search_emits_event(self):
        from shared.config import InstrumentedQdrantClient

        mock_client = MagicMock()
        mock_client.search.return_value = [{"id": 1}]
        bus = EventBus()
        wrapped = InstrumentedQdrantClient(mock_client, bus, agent_name="test-agent")

        result = wrapped.search("my-collection", query_vector=[0.1, 0.2])
        assert result == [{"id": 1}]
        mock_client.search.assert_called_once_with(
            collection_name="my-collection", query_vector=[0.1, 0.2]
        )
        events = bus.recent()
        assert len(events) == 1
        assert events[0].kind == "qdrant.op"
        assert events[0].source == "test-agent"
        assert events[0].label == "search/my-collection"

    def test_upsert_emits_event(self):
        from shared.config import InstrumentedQdrantClient

        mock_client = MagicMock()
        bus = EventBus()
        wrapped = InstrumentedQdrantClient(mock_client, bus, agent_name="ingest")
        wrapped.upsert("docs", points=[])
        events = bus.recent()
        assert len(events) == 1
        assert events[0].label == "upsert/docs"

    def test_passthrough_attribute(self):
        from shared.config import InstrumentedQdrantClient

        mock_client = MagicMock()
        mock_client.get_collections.return_value = ["a", "b"]
        bus = EventBus()
        wrapped = InstrumentedQdrantClient(mock_client, bus)
        assert wrapped.get_collections() == ["a", "b"]


# ── ReactiveEngine._agent_from_path ──────────────────────────────────────────


class TestAgentFromPath:
    def test_extracts_hapax_prefix(self):
        from logos.engine import ReactiveEngine

        assert ReactiveEngine._agent_from_path("/data/hapax-council/profiles/foo.md") == "council"

    def test_extracts_first_hapax_part(self):
        from logos.engine import ReactiveEngine

        assert ReactiveEngine._agent_from_path("/dev/shm/hapax-stimmung/state.json") == "stimmung"

    def test_returns_unknown_for_no_match(self):
        from logos.engine import ReactiveEngine

        assert ReactiveEngine._agent_from_path("/tmp/foo/bar.txt") == "unknown"


# ── FlowObserver emits on mtime change ───────────────────────────────────────


class TestFlowObserverEmit:
    def test_emits_shm_write_on_mtime_change(self, tmp_path: Path):
        from logos.api.flow_observer import FlowObserver

        bus = EventBus()
        shm_root = tmp_path
        agent_dir = shm_root / "hapax-stimmung"
        agent_dir.mkdir()
        state_file = agent_dir / "state.json"
        state_file.write_text("{}")

        obs = FlowObserver(shm_root=shm_root, event_bus=bus)
        obs.register_reader("reader-agent", str(state_file))

        # First scan — populates prev_mtimes, no event yet
        obs.scan()
        assert len(bus.recent()) == 0

        # Touch the file to change mtime
        import os

        orig_mtime = state_file.stat().st_mtime
        os.utime(state_file, (orig_mtime + 1, orig_mtime + 1))

        # Second scan — mtime changed → should emit
        obs.scan()
        events = bus.recent()
        assert len(events) == 1
        assert events[0].kind == "shm.write"
        assert events[0].source == "stimmung"
        assert events[0].target == "reader-agent"
        assert events[0].label == "state.json"

    def test_no_emit_without_event_bus(self, tmp_path: Path):
        from logos.api.flow_observer import FlowObserver

        shm_root = tmp_path
        agent_dir = shm_root / "hapax-test"
        agent_dir.mkdir()
        state_file = agent_dir / "state.json"
        state_file.write_text("{}")

        obs = FlowObserver(shm_root=shm_root, event_bus=None)
        obs.register_reader("r", str(state_file))
        obs.scan()

        import os

        orig_mtime = state_file.stat().st_mtime
        os.utime(state_file, (orig_mtime + 1, orig_mtime + 1))
        obs.scan()
        # No crash — works without bus
