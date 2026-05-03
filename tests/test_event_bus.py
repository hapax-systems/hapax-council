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
    """MagicMock-based unit tests for the wrapper's event-emission
    semantics. cc-task ``instrumented-qdrant-positional-fix`` adds
    real-client integration tests below to catch signature-dispatch
    bugs the MagicMock tests miss by construction."""

    def test_query_points_emits_event(self):
        from shared.config import InstrumentedQdrantClient

        mock_client = MagicMock()
        mock_client.query_points.return_value = [{"id": 1}]
        bus = EventBus()
        wrapped = InstrumentedQdrantClient(mock_client, bus, agent_name="test-agent")

        result = wrapped.query_points("my-collection", query=[0.1, 0.2])
        assert result == [{"id": 1}]
        mock_client.query_points.assert_called_once_with("my-collection", query=[0.1, 0.2])
        events = bus.recent()
        assert len(events) == 1
        assert events[0].kind == "qdrant.op"
        assert events[0].source == "test-agent"
        assert events[0].label == "query_points/my-collection"

    def test_upsert_emits_event(self):
        from shared.config import InstrumentedQdrantClient

        mock_client = MagicMock()
        bus = EventBus()
        wrapped = InstrumentedQdrantClient(mock_client, bus, agent_name="ingest")
        wrapped.upsert("docs", points=[])
        events = bus.recent()
        assert len(events) == 1
        assert events[0].label == "upsert/docs"

    def test_legacy_search_raises_attribute_error_with_migration_hint(self):
        """Per cc-task ``instrumented-qdrant-positional-fix``: the
        legacy ``search`` method is a deprecation stub that raises
        AttributeError with a clear migration hint. Modern qdrant-client
        has removed ``QdrantClient.search`` in favor of ``query_points``."""
        from shared.config import InstrumentedQdrantClient

        mock_client = MagicMock()
        bus = EventBus()
        wrapped = InstrumentedQdrantClient(mock_client, bus)
        try:
            wrapped.search("collection", query_vector=[0.1, 0.2])
        except AttributeError as exc:
            assert "query_points" in str(exc), "migration hint must name query_points"
            assert "instrumented-qdrant-positional-fix" in str(exc), (
                "error must reference cc-task for context"
            )
        else:
            raise AssertionError("expected AttributeError from legacy search()")

    def test_passthrough_attribute(self):
        from shared.config import InstrumentedQdrantClient

        mock_client = MagicMock()
        mock_client.get_collections.return_value = ["a", "b"]
        bus = EventBus()
        wrapped = InstrumentedQdrantClient(mock_client, bus)
        assert wrapped.get_collections() == ["a", "b"]


class TestInstrumentedQdrantClientPositionalArgs:
    """cc-task ``instrumented-qdrant-positional-fix`` (audit Auditor D B3
    finding #7): the wrapper's "drop-in replacement" claim is FALSE
    when the wrapped methods reject positional args. These tests pin
    the positional+keyword pass-through contract.
    """

    def test_query_points_accepts_positional_args(self):
        """Positional args MUST pass through unchanged. Audit-flagged:
        the prior shape `def search(self, collection_name: str, **kwargs)`
        rejected positional `query_vector` calls; this test would have
        caught that immediately."""
        from shared.config import InstrumentedQdrantClient

        mock_client = MagicMock()
        bus = EventBus()
        wrapped = InstrumentedQdrantClient(mock_client, bus)
        # Underlying QdrantClient.query_points signature accepts
        # (collection_name, query, ...). Test ALL positional.
        wrapped.query_points("my-coll", [0.1, 0.2, 0.3])
        mock_client.query_points.assert_called_once_with("my-coll", [0.1, 0.2, 0.3])

    def test_upsert_accepts_positional_args(self):
        from shared.config import InstrumentedQdrantClient

        mock_client = MagicMock()
        bus = EventBus()
        wrapped = InstrumentedQdrantClient(mock_client, bus)
        wrapped.upsert("docs", [{"id": 1, "vector": [0.0]}])
        mock_client.upsert.assert_called_once_with("docs", [{"id": 1, "vector": [0.0]}])

    def test_query_points_mixed_positional_and_kwargs(self):
        from shared.config import InstrumentedQdrantClient

        mock_client = MagicMock()
        bus = EventBus()
        wrapped = InstrumentedQdrantClient(mock_client, bus)
        wrapped.query_points("my-coll", query=[0.1], limit=5)
        mock_client.query_points.assert_called_once_with("my-coll", query=[0.1], limit=5)

    def test_collection_label_resolution_from_positional(self):
        """The FlowEvent label MUST resolve collection_name from the
        first positional arg (matches QdrantClient API convention)."""
        from shared.config import InstrumentedQdrantClient

        mock_client = MagicMock()
        bus = EventBus()
        wrapped = InstrumentedQdrantClient(mock_client, bus)
        wrapped.query_points("from-positional", [0.1])
        events = bus.recent()
        assert events[0].label == "query_points/from-positional"

    def test_collection_label_resolution_from_kwarg(self):
        """The FlowEvent label MUST also resolve collection_name from
        the kwarg shape — both call shapes are valid on the
        underlying client."""
        from shared.config import InstrumentedQdrantClient

        mock_client = MagicMock()
        bus = EventBus()
        wrapped = InstrumentedQdrantClient(mock_client, bus)
        wrapped.query_points(collection_name="from-kwarg", query=[0.1])
        events = bus.recent()
        assert events[0].label == "query_points/from-kwarg"


class TestInstrumentedQdrantClientRealClientIntegration:
    """**Integration tests with a real QdrantClient** (NOT MagicMock) per
    cc-task ``instrumented-qdrant-positional-fix`` acceptance criterion:
    catches signature-dispatch errors the MagicMock-based tests miss
    by construction.

    Uses ``QdrantClient(":memory:")`` — same surface as the network
    client but no Docker / no network dependency. The audit finding's
    root cause was that MagicMock-based tests can't see
    ``AttributeError`` on a method that doesn't exist on the real
    client; these tests exercise the actual call path.
    """

    @pytest.fixture
    def real_qdrant_in_memory(self):
        """Yield a real in-memory QdrantClient + tear down after test.

        ``:memory:`` mode runs an embedded Qdrant. Same surface as the
        network client; no container required. Skips the whole class
        if qdrant_client doesn't import (would only happen on a
        deliberately-broken environment)."""
        try:
            from qdrant_client import QdrantClient
        except ImportError:
            pytest.skip("qdrant_client not importable")
        client = QdrantClient(":memory:")
        yield client
        client.close()

    def test_real_client_query_points_with_positional_args(self, real_qdrant_in_memory):
        """The audit-flagged failure mode: a caller passes
        ``collection_name`` + ``query`` positionally. With the prior
        wrapper shape this raised TypeError on signature dispatch.
        With the fixed shape it works."""
        from qdrant_client.models import Distance, PointStruct, VectorParams

        from shared.config import InstrumentedQdrantClient

        client = real_qdrant_in_memory
        client.create_collection(
            collection_name="audit-fixture",
            vectors_config=VectorParams(size=4, distance=Distance.COSINE),
        )
        client.upsert(
            collection_name="audit-fixture",
            points=[PointStruct(id=1, vector=[1.0, 0.0, 0.0, 0.0])],
        )

        bus = EventBus()
        wrapped = InstrumentedQdrantClient(client, bus, agent_name="real-test")

        # Call with collection_name positional + query positional —
        # the audit-flagged shape that previously broke.
        result = wrapped.query_points("audit-fixture", [1.0, 0.0, 0.0, 0.0])
        # Real client returns a QueryResponse object with .points list.
        assert hasattr(result, "points")
        assert len(result.points) == 1
        assert result.points[0].id == 1
        # FlowEvent must have fired with the resolved collection label.
        events = bus.recent()
        assert any(e.label == "query_points/audit-fixture" for e in events)

    def test_real_client_upsert_with_positional_points(self, real_qdrant_in_memory):
        """Symmetric test for upsert positional pass-through."""
        from qdrant_client.models import Distance, PointStruct, VectorParams

        from shared.config import InstrumentedQdrantClient

        client = real_qdrant_in_memory
        client.create_collection(
            collection_name="upsert-fixture",
            vectors_config=VectorParams(size=2, distance=Distance.COSINE),
        )
        bus = EventBus()
        wrapped = InstrumentedQdrantClient(client, bus, agent_name="upsert-test")

        # Positional collection_name + positional points.
        wrapped.upsert("upsert-fixture", [PointStruct(id=42, vector=[0.5, 0.5])])
        # Verify the upsert actually landed on the real client.
        retrieved = client.retrieve(collection_name="upsert-fixture", ids=[42])
        assert len(retrieved) == 1
        assert retrieved[0].id == 42
        # FlowEvent fired.
        events = bus.recent()
        assert any(e.label == "upsert/upsert-fixture" for e in events)

    def test_real_client_proxy_passthrough_to_undefined_methods(self, real_qdrant_in_memory):
        """Methods not explicitly wrapped (like ``get_collections``)
        must proxy through ``__getattr__`` to the real client. With a
        real client this catches "method exists on QdrantClient but
        not on the wrapped surface" issues."""
        from shared.config import InstrumentedQdrantClient

        client = real_qdrant_in_memory
        bus = EventBus()
        wrapped = InstrumentedQdrantClient(client, bus, agent_name="proxy-test")
        # get_collections returns a CollectionsResponse on real client.
        result = wrapped.get_collections()
        assert hasattr(result, "collections")


# ── get_qdrant_instrumented factory ──────────────────────────────────────────


class TestGetQdrantInstrumentedFactory:
    """Closes the wire half of cc-task
    ``r16-langfuse-qdrant-microprobe-agentrunner-wire-delete`` for the
    InstrumentedQdrantClient surface. The wrapper class always existed
    (R-16 audit confirmed correctness), but the factory entry point was
    missing — hence zero production callsites for 6 days. This factory
    is the missing wire path.
    """

    def test_no_bus_returns_consent_gated_client_unchanged(self):
        """Without an event_bus, the factory returns the same
        consent-gated client as ``get_qdrant()``. Safe drop-in for
        callers with no bus to wire."""
        from unittest.mock import patch

        # Patch get_qdrant() to return a sentinel so we can identify
        # what the factory hands back.
        sentinel = object()
        with patch("shared.config.get_qdrant", return_value=sentinel):
            from shared.config import get_qdrant_instrumented

            result = get_qdrant_instrumented(agent_name="test-no-bus", event_bus=None)
        assert result is sentinel, (
            "factory must return the consent-gated client unchanged when "
            "event_bus is None — degrades cleanly for bus-less callers"
        )

    def test_with_bus_wraps_in_instrumented_client(self):
        """With an event_bus, the factory composes
        InstrumentedQdrantClient(consent-gated-client, bus). The two
        __getattr__ layers (instrumentation outer, consent gate inner)
        compose: instrumented ops route through the gate.

        Updated per cc-task ``instrumented-qdrant-positional-fix``:
        exercises ``query_points`` (the modern API) instead of the
        deprecated ``search`` method which now raises AttributeError."""
        from unittest.mock import MagicMock, patch

        from shared.config import InstrumentedQdrantClient

        mock_consent_gated = MagicMock()
        mock_consent_gated.query_points.return_value = [{"id": 42}]
        bus = EventBus()
        with patch("shared.config.get_qdrant", return_value=mock_consent_gated):
            from shared.config import get_qdrant_instrumented

            wrapped = get_qdrant_instrumented(agent_name="test-with-bus", event_bus=bus)

        assert isinstance(wrapped, InstrumentedQdrantClient)
        # The instrumented op delegates through the consent-gated client.
        result = wrapped.query_points("col", query=[1.0])
        assert result == [{"id": 42}]
        mock_consent_gated.query_points.assert_called_once_with("col", query=[1.0])
        # And emits the FlowEvent.
        events = bus.recent()
        assert len(events) == 1
        assert events[0].kind == "qdrant.op"
        assert events[0].source == "test-with-bus"
        assert events[0].label == "query_points/col"

    def test_passthrough_attribute_via_factory(self):
        """Non-instrumented attribute access proxies through the
        instrumentation layer's __getattr__ to the consent-gated
        client's __getattr__."""
        from unittest.mock import MagicMock, patch

        mock_consent_gated = MagicMock()
        mock_consent_gated.get_collections.return_value = ["c1", "c2"]
        bus = EventBus()
        with patch("shared.config.get_qdrant", return_value=mock_consent_gated):
            from shared.config import get_qdrant_instrumented

            wrapped = get_qdrant_instrumented(agent_name="passthrough-test", event_bus=bus)
        # get_collections is not in the instrumented op-list, so it
        # passes through both __getattr__ layers.
        assert wrapped.get_collections() == ["c1", "c2"]


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
        # Register so writer_node_map maps "stimmung" → "stimmung_sync"
        obs.register_reader("stimmung_sync", str(state_file))

        # First scan — populates prev_mtimes, no event yet
        obs.scan()
        assert len(bus.recent()) == 0

        # Touch the file to change mtime
        import os

        orig_mtime = state_file.stat().st_mtime
        os.utime(state_file, (orig_mtime + 1, orig_mtime + 1))

        # Second scan — mtime changed → emits to verified consumers only
        # stimmung_sync → hapax_daimonion, reactive_engine, studio_compositor
        obs.scan()
        events = bus.recent()
        assert len(events) == 3
        assert all(e.kind == "shm.write" for e in events)
        assert all(e.source == "stimmung_sync" for e in events)
        targets = {e.target for e in events}
        assert targets == {"hapax_daimonion", "reactive_engine", "studio_compositor"}

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
