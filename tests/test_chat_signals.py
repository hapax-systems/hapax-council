"""Tests for agents/studio_compositor/chat_signals.py — LRR Phase 9 item 3."""

from __future__ import annotations

import json
from pathlib import Path

import pytest  # noqa: TC002 — runtime dep for fixtures

from agents.studio_compositor.chat_classifier import ChatTier, Classification
from agents.studio_compositor.chat_queues import (
    ChatMessage,
    StructuralSignalQueue,
    fake_embedder,
)
from agents.studio_compositor.chat_signals import (
    DEFAULT_CHAT_SIGNALS_PATH,
    ChatSignalsAggregator,
    compute_audience_engagement,
)


def _t4(
    text: str, *, ts: float = 1000.0, handle: str = "user", with_embedding: bool = False
) -> ChatMessage:
    embedding = tuple(fake_embedder(text)) if with_embedding else None
    return ChatMessage(
        text=text,
        author_handle=handle,
        ts=ts,
        classification=Classification(
            tier=ChatTier.T4_STRUCTURAL_SIGNAL, reason="test", confidence=0.5
        ),
        embedding=embedding,
    )


class TestComputeAudienceEngagement:
    def test_zero_traffic_is_low(self) -> None:
        result = compute_audience_engagement(
            message_rate_per_min=0.0,
            chat_entropy=0.0,
            chat_novelty=0.0,
            unique_authors_60s=0,
            high_value_queue_depth=0,
        )
        assert 0.0 <= result <= 0.2

    def test_high_traffic_high_diversity_is_high(self) -> None:
        result = compute_audience_engagement(
            message_rate_per_min=50.0,
            chat_entropy=3.0,
            chat_novelty=0.9,
            unique_authors_60s=30,
            high_value_queue_depth=2,
        )
        assert result >= 0.9

    def test_high_value_bonus_fires(self) -> None:
        without = compute_audience_engagement(
            message_rate_per_min=5.0,
            chat_entropy=1.0,
            chat_novelty=0.2,
            unique_authors_60s=3,
            high_value_queue_depth=0,
        )
        with_hv = compute_audience_engagement(
            message_rate_per_min=5.0,
            chat_entropy=1.0,
            chat_novelty=0.2,
            unique_authors_60s=3,
            high_value_queue_depth=1,
        )
        assert with_hv > without

    def test_result_clamped_to_unit_interval(self) -> None:
        # Intentionally out-of-range novelty still produces [0,1] output
        result = compute_audience_engagement(
            message_rate_per_min=10000.0,
            chat_entropy=10.0,
            chat_novelty=5.0,  # should clamp to 1.0
            unique_authors_60s=100,
            high_value_queue_depth=1,
        )
        assert 0.0 <= result <= 1.0


class TestChatSignalsAggregator:
    def test_empty_queue_zero_signals(self, tmp_path: Path) -> None:
        queue = StructuralSignalQueue()
        agg = ChatSignalsAggregator(queue, output_path=tmp_path / "signals.json")
        signals = agg.compute_signals(now=1000.0)
        assert signals.message_count_60s == 0
        assert signals.message_rate_per_min == 0.0
        assert signals.unique_authors_60s == 0
        assert signals.chat_entropy == 0.0
        assert signals.chat_novelty == 0.0
        assert 0.0 <= signals.audience_engagement <= 1.0

    def test_message_count_and_rate(self, tmp_path: Path) -> None:
        queue = StructuralSignalQueue(window_seconds=60.0)
        for i in range(30):
            queue.push(_t4(f"msg {i}", ts=1000.0 + i))
        agg = ChatSignalsAggregator(queue, output_path=tmp_path / "signals.json")
        signals = agg.compute_signals(now=1030.0)
        assert signals.message_count_60s == 30
        # 30 messages in a 60s window → 30/min
        assert signals.message_rate_per_min == pytest.approx(30.0, abs=0.01)

    def test_unique_authors_counted(self, tmp_path: Path) -> None:
        queue = StructuralSignalQueue()
        for handle in ["alice", "bob", "alice", "carol", "bob"]:
            queue.push(_t4("msg", handle=handle, ts=1000.0))
        agg = ChatSignalsAggregator(queue, output_path=tmp_path / "signals.json")
        signals = agg.compute_signals(now=1001.0)
        assert signals.unique_authors_60s == 3

    def test_write_shm_atomic(self, tmp_path: Path) -> None:
        queue = StructuralSignalQueue()
        queue.push(_t4("hello", ts=1000.0))
        out = tmp_path / "signals.json"
        agg = ChatSignalsAggregator(queue, output_path=out)
        signals = agg.compute_signals(now=1001.0)
        agg.write_shm(signals)
        assert out.exists()
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["message_count_60s"] == 1
        assert "audience_engagement" in payload

    def test_write_shm_overwrites(self, tmp_path: Path) -> None:
        queue = StructuralSignalQueue()
        out = tmp_path / "signals.json"
        agg = ChatSignalsAggregator(queue, output_path=out)
        agg.write_shm(agg.compute_signals(now=1000.0))
        original = out.read_text(encoding="utf-8")

        queue.push(_t4("new", ts=1010.0))
        agg.write_shm(agg.compute_signals(now=1015.0))
        updated = out.read_text(encoding="utf-8")
        assert original != updated

    def test_signals_includes_high_value_depth(self, tmp_path: Path) -> None:
        queue = StructuralSignalQueue()
        agg = ChatSignalsAggregator(queue, output_path=tmp_path / "signals.json")
        signals = agg.compute_signals(now=1000.0, high_value_queue_depth=3)
        assert signals.high_value_queue_depth == 3

    def test_entropy_with_embeddings(self, tmp_path: Path) -> None:
        queue = StructuralSignalQueue()
        # 10 distinct texts → diverse vectors → positive entropy
        for i in range(10):
            queue.push(_t4(f"different text {i}", ts=1000.0 + i, with_embedding=True))
        agg = ChatSignalsAggregator(queue, output_path=tmp_path / "signals.json")
        signals = agg.compute_signals(now=1010.0)
        assert signals.chat_entropy > 0.0


class TestDefaultPath:
    def test_default_shm_path(self) -> None:
        assert str(DEFAULT_CHAT_SIGNALS_PATH).startswith("/dev/shm/")
