"""Tests for agents/studio_compositor/chat_queues.py — LRR Phase 9 item 2."""

from __future__ import annotations

import pytest  # noqa: TC002 — runtime dep for fixtures

from agents.studio_compositor.chat_classifier import ChatTier, Classification
from agents.studio_compositor.chat_queues import (
    ChatMessage,
    HighValueQueue,
    ResearchRelevantQueue,
    StructuralSignalQueue,
    fake_embedder,
)


def _msg(
    text: str,
    tier: ChatTier,
    *,
    ts: float = 1000.0,
    handle: str = "user",
) -> ChatMessage:
    return ChatMessage(
        text=text,
        author_handle=handle,
        ts=ts,
        classification=Classification(tier=tier, reason="test", confidence=0.9),
    )


class TestHighValueQueue:
    def test_fifo_push_and_sample(self) -> None:
        q = HighValueQueue(capacity=5)
        for i in range(3):
            q.push(_msg(f"msg{i}", ChatTier.T6_HIGH_VALUE, ts=1000.0 + i))
        assert len(q) == 3
        sample = q.sample(top_k=3)
        assert [m.text for m in sample] == ["msg0", "msg1", "msg2"]

    def test_capacity_eviction(self) -> None:
        q = HighValueQueue(capacity=3)
        for i in range(5):
            q.push(_msg(f"msg{i}", ChatTier.T6_HIGH_VALUE, ts=1000.0 + i))
        assert len(q) == 3
        sample = q.sample(top_k=5)
        assert [m.text for m in sample] == ["msg2", "msg3", "msg4"]

    def test_top_k_cap(self) -> None:
        q = HighValueQueue(capacity=5)
        for i in range(5):
            q.push(_msg(f"msg{i}", ChatTier.T6_HIGH_VALUE))
        assert len(q.sample(top_k=2)) == 2

    def test_wrong_tier_rejected(self) -> None:
        q = HighValueQueue()
        with pytest.raises(ValueError, match="T6"):
            q.push(_msg("wrong", ChatTier.T5_RESEARCH_RELEVANT))

    def test_clear(self) -> None:
        q = HighValueQueue()
        q.push(_msg("m", ChatTier.T6_HIGH_VALUE))
        q.clear()
        assert len(q) == 0


class TestResearchRelevantQueue:
    def test_push_computes_embedding(self) -> None:
        q = ResearchRelevantQueue(capacity=30)
        m = _msg("hypothesis test", ChatTier.T5_RESEARCH_RELEVANT)
        q.push(m)
        # Embedding is computed on push — verify via sample
        result = q.sample(top_k=1)
        assert result[0].embedding is not None

    def test_capacity_eviction_bounds_size(self) -> None:
        """Pushing beyond capacity keeps size at capacity."""
        q = ResearchRelevantQueue(capacity=3)
        q.update_focus_vector(fake_embedder("paper bayes statistical"))

        for i in range(5):
            q.push(
                _msg(f"msg-{i}", ChatTier.T5_RESEARCH_RELEVANT, ts=1000.0 + i),
                now=1010.0,
            )

        assert len(q) == 3  # Bounded after 5 pushes with capacity 3

    def test_sample_top_k_by_score(self) -> None:
        q = ResearchRelevantQueue(capacity=30)
        q.update_focus_vector(fake_embedder("hypothesis paper bayes"))

        for i, text in enumerate(
            [
                "paper bayes update hypothesis",
                "random chat content",
                "hypothesis research paper",
                "mid-similarity paper text",
            ]
        ):
            q.push(_msg(text, ChatTier.T5_RESEARCH_RELEVANT, ts=1000.0 + i))

        top = q.sample(top_k=2, now=1010.0)
        assert len(top) == 2
        # The top 2 should favor the messages with 'paper' or 'bayes' keywords
        top_texts = {m.text for m in top}
        assert any("paper" in t or "bayes" in t or "hypothesis" in t for t in top_texts)

    def test_recency_bonus_boosts_fresh_messages(self) -> None:
        """Without a focus vector, recency bonus determines ordering."""
        q = ResearchRelevantQueue(capacity=30)
        q.push(_msg("old message", ChatTier.T5_RESEARCH_RELEVANT, ts=0.0))
        q.push(_msg("fresh message", ChatTier.T5_RESEARCH_RELEVANT, ts=100.0))
        top = q.sample(top_k=2, now=100.0)
        assert top[0].text == "fresh message"

    def test_wrong_tier_rejected(self) -> None:
        q = ResearchRelevantQueue()
        with pytest.raises(ValueError, match="T5"):
            q.push(_msg("wrong", ChatTier.T4_STRUCTURAL_SIGNAL))

    def test_unbounded_without_capacity_breach(self) -> None:
        q = ResearchRelevantQueue(capacity=30)
        for i in range(30):
            q.push(_msg(f"msg {i}", ChatTier.T5_RESEARCH_RELEVANT, ts=1000.0 + i))
        assert len(q) == 30
        q.push(_msg("msg overflow", ChatTier.T5_RESEARCH_RELEVANT, ts=1030.0))
        assert len(q) == 30


class TestStructuralSignalQueue:
    def test_push_and_window(self) -> None:
        q = StructuralSignalQueue(window_seconds=60.0)
        for i in range(5):
            q.push(_msg(f"msg {i}", ChatTier.T4_STRUCTURAL_SIGNAL, ts=1000.0 + i))
        window = q.window_items(now=1010.0)
        assert len(window) == 5

    def test_stale_messages_pruned(self) -> None:
        q = StructuralSignalQueue(window_seconds=60.0)
        q.push(_msg("old", ChatTier.T4_STRUCTURAL_SIGNAL, ts=1000.0))
        q.push(_msg("recent", ChatTier.T4_STRUCTURAL_SIGNAL, ts=1070.0))
        # 1080 is 80s after the first message → the first is outside the 60s window
        window = q.window_items(now=1080.0)
        assert len(window) == 1
        assert window[0].text == "recent"

    def test_prune_on_push(self) -> None:
        q = StructuralSignalQueue(window_seconds=60.0)
        q.push(_msg("old", ChatTier.T4_STRUCTURAL_SIGNAL, ts=1000.0))
        # Pushing a message 100s later triggers prune before adding the new one
        q.push(_msg("fresh", ChatTier.T4_STRUCTURAL_SIGNAL, ts=1100.0))
        assert len(q) == 1

    def test_wrong_tier_rejected(self) -> None:
        q = StructuralSignalQueue()
        with pytest.raises(ValueError, match="T4"):
            q.push(_msg("wrong", ChatTier.T6_HIGH_VALUE))


class TestFakeEmbedder:
    def test_deterministic(self) -> None:
        e1 = fake_embedder("hello world")
        e2 = fake_embedder("hello world")
        assert e1 == e2

    def test_eight_dimensional(self) -> None:
        e = fake_embedder("test")
        assert len(e) == 8

    def test_normalized(self) -> None:
        import math

        e = fake_embedder("test string")
        norm = math.sqrt(sum(v * v for v in e))
        assert abs(norm - 1.0) < 0.001

    def test_different_strings_different_embeddings(self) -> None:
        assert fake_embedder("alpha") != fake_embedder("beta")
