"""Tests for agents.chat_monitor.structural_analyzer (Phase 9 §3.1)."""

from __future__ import annotations


def _msg(author: str, text: str, ts: float = 0.0):
    from agents.chat_monitor.structural_analyzer import ChatMessage

    return ChatMessage(author_id=author, text=text, ts=ts)


class TestParticipantDiversity:
    def test_empty_is_zero(self):
        from agents.chat_monitor.structural_analyzer import analyze

        assert analyze([]).participant_diversity == 0.0

    def test_all_unique_is_one(self):
        from agents.chat_monitor.structural_analyzer import analyze

        msgs = [_msg(f"a{i}", "hi") for i in range(5)]
        assert analyze(msgs).participant_diversity == 1.0

    def test_all_same_author_is_low(self):
        from agents.chat_monitor.structural_analyzer import analyze

        msgs = [_msg("alice", f"m{i}") for i in range(5)]
        assert analyze(msgs).participant_diversity == 1 / 5


class TestNoveltyRate:
    def test_empty_is_zero(self):
        from agents.chat_monitor.structural_analyzer import analyze

        assert analyze([]).novelty_rate == 0.0

    def test_identical_messages_low_novelty(self):
        from agents.chat_monitor.structural_analyzer import analyze

        # Same bigrams repeated → only the first message contributes novelty.
        msgs = [_msg("a", "hello world yes") for _ in range(3)]
        signals = analyze(msgs)
        # 6 total bigrams ("hello world", "world yes" × 3), 2 novel
        assert abs(signals.novelty_rate - 2 / 6) < 1e-9

    def test_all_distinct_messages_full_novelty(self):
        from agents.chat_monitor.structural_analyzer import analyze

        msgs = [
            _msg("a", "alpha beta"),
            _msg("b", "gamma delta"),
            _msg("c", "epsilon zeta"),
        ]
        assert analyze(msgs).novelty_rate == 1.0

    def test_short_messages_skipped(self):
        from agents.chat_monitor.structural_analyzer import analyze

        # Single-word messages contribute no bigrams → novelty stays 0.
        msgs = [_msg("a", "wow"), _msg("b", "nice")]
        assert analyze(msgs).novelty_rate == 0.0


class TestThreadCount:
    def test_no_embedder_returns_zero(self):
        from agents.chat_monitor.structural_analyzer import analyze

        msgs = [_msg("a", "hello")]
        assert analyze(msgs).thread_count == 0

    def test_single_cluster_when_messages_similar(self):
        from agents.chat_monitor.structural_analyzer import analyze

        # All messages get the same embedding vector → one cluster.
        def embed(texts):
            return [[1.0, 0.0, 0.0] for _ in texts]

        msgs = [_msg("a", "one"), _msg("b", "two"), _msg("c", "three")]
        assert analyze(msgs, embedder=embed).thread_count == 1

    def test_two_clusters_when_messages_orthogonal(self):
        from agents.chat_monitor.structural_analyzer import analyze

        vectors = {"m1": [1.0, 0.0], "m2": [0.0, 1.0], "m3": [1.0, 0.0]}

        def embed(texts):
            return [vectors[t] for t in texts]

        msgs = [_msg("a", "m1"), _msg("b", "m2"), _msg("c", "m3")]
        assert analyze(msgs, embedder=embed).thread_count == 2


class TestSemanticCoherence:
    def test_no_embedder_returns_zero(self):
        from agents.chat_monitor.structural_analyzer import analyze

        msgs = [_msg("a", "one"), _msg("b", "two")]
        assert analyze(msgs, embedder=None).semantic_coherence == 0.0

    def test_single_message_is_zero(self):
        from agents.chat_monitor.structural_analyzer import analyze

        msgs = [_msg("a", "hi")]

        def embed(texts):
            return [[1.0]]

        assert analyze(msgs, embedder=embed).semantic_coherence == 0.0

    def test_identical_vectors_give_one(self):
        from agents.chat_monitor.structural_analyzer import analyze

        def embed(texts):
            return [[1.0, 0.0] for _ in texts]

        msgs = [_msg("a", "m1"), _msg("b", "m2"), _msg("c", "m3")]
        assert analyze(msgs, embedder=embed).semantic_coherence == 1.0

    def test_orthogonal_vectors_give_zero(self):
        from agents.chat_monitor.structural_analyzer import analyze

        vectors = [[1.0, 0.0], [0.0, 1.0]]

        def embed(texts):
            return vectors[: len(texts)]

        msgs = [_msg("a", "m1"), _msg("b", "m2")]
        assert analyze(msgs, embedder=embed).semantic_coherence == 0.0


class TestEmbedderFailureIsolation:
    def test_exception_does_not_propagate(self, caplog):
        from agents.chat_monitor.structural_analyzer import analyze

        def boom(_texts):
            raise RuntimeError("embedder exploded")

        msgs = [_msg("a", "hello world"), _msg("b", "goodbye world")]
        signals = analyze(msgs, embedder=boom)

        assert signals.thread_count == 0
        assert signals.semantic_coherence == 0.0
        # Non-embedding metrics still computed.
        assert signals.participant_diversity == 1.0
        assert signals.novelty_rate > 0


class TestAsdict:
    def test_asdict_round_trip(self):
        from agents.chat_monitor.structural_analyzer import analyze

        msgs = [_msg("a", "hello world")]
        d = analyze(msgs).asdict()
        assert set(d.keys()) == {
            "participant_diversity",
            "novelty_rate",
            "thread_count",
            "semantic_coherence",
            "window_size",
        }
        assert d["window_size"] == 1
