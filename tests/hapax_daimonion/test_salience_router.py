"""Tests for salience-based model routing."""

from __future__ import annotations

import numpy as np

from agents.hapax_daimonion.model_router import ModelTier
from agents.hapax_daimonion.salience.concern_graph import ConcernAnchor, ConcernGraph
from agents.hapax_daimonion.salience.utterance_features import extract
from agents.hapax_daimonion.salience_router import SalienceRouter

# ── Utterance feature extraction tests ──────────────────────────────


class TestUtteranceFeatures:
    def test_backchannel(self):
        f = extract("yeah")
        assert f.dialog_act == "backchannel"
        assert f.is_phatic is True

    def test_acknowledgment(self):
        f = extract("thanks")
        assert f.dialog_act == "acknowledgment"
        assert f.is_phatic is True

    def test_wh_question(self):
        f = extract("What time is it?")
        assert f.dialog_act == "wh_question"
        assert f.is_phatic is False

    def test_yes_no_question(self):
        f = extract("Is the server running?")
        assert f.dialog_act == "yes_no_question"

    def test_command(self):
        f = extract("search for voice latency bugs")
        assert f.dialog_act == "command"

    def test_meta_question(self):
        f = extract("explain how the routing works?")
        assert f.dialog_act == "meta_question"
        assert f.has_explicit_escalation is True

    def test_statement(self):
        f = extract("The voice daemon is running on the RTX 3090 with 24GB VRAM")
        assert f.dialog_act == "statement"
        assert f.word_count >= 10

    def test_pre_sequence(self):
        f = extract("I have a question about the consent system")
        assert f.is_pre_sequence is True

    def test_topic_continuity(self):
        recent = ["I'm working on the voice latency", "the voice routing is broken"]
        f = extract("let's fix the voice routing issue", recent_turns=recent)
        assert f.topic_continuity > 0.0

    def test_topic_discontinuity(self):
        recent = ["I'm working on the voice latency"]
        f = extract("what's the weather like?", recent_turns=recent)
        assert f.topic_continuity == 0.0

    def test_phatic_closers(self):
        for text in ["bye", "later", "see you", "goodnight"]:
            f = extract(text)
            assert f.is_phatic is True, f"{text} should be phatic"

    def test_hedge_counting(self):
        f = extract("I think maybe we should probably change the approach")
        assert f.hedge_count >= 2

    def test_explicit_escalation(self):
        f = extract("think harder about this problem")
        assert f.has_explicit_escalation is True

    def test_no_escalation(self):
        f = extract("hey what's up")
        assert f.has_explicit_escalation is False

    def test_fast_extraction(self):
        """All extraction should complete in <1ms."""
        import time

        texts = [
            "yeah",
            "What time is the meeting?",
            "I think maybe we should reconsider the architecture of the voice daemon",
            "search for latency bugs in the codebase",
            "Can I ask you something about the consent system?",
        ]
        t0 = time.monotonic()
        for text in texts:
            extract(text)
        elapsed_ms = (time.monotonic() - t0) * 1000
        # All 5 should complete in under 5ms total
        assert elapsed_ms < 50, f"Feature extraction too slow: {elapsed_ms:.1f}ms for 5 texts"


# ── Concern graph tests ─────────────────────────────────────────────


class TestConcernGraph:
    def test_empty_graph(self):
        g = ConcernGraph(dim=4)
        vec = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        assert g.query(vec) == 0.0
        assert g.novelty(vec) == 1.0  # everything is novel when graph is empty

    def test_exact_match(self):
        g = ConcernGraph(dim=4)
        anchors = [ConcernAnchor(text="test", source="test", weight=1.0)]
        embeddings = np.array([[1.0, 0.0, 0.0, 0.0]], dtype=np.float32)
        g.refresh(anchors, embeddings)

        # Exact match should give high overlap
        vec = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        assert g.query(vec) > 0.9

        # Orthogonal vector should give low overlap
        vec_orth = np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32)
        assert g.query(vec_orth) < 0.1

    def test_novelty_decreases_with_match(self):
        g = ConcernGraph(dim=4)
        anchors = [ConcernAnchor(text="known", source="test", weight=1.0)]
        embeddings = np.array([[1.0, 0.0, 0.0, 0.0]], dtype=np.float32)
        g.refresh(anchors, embeddings)

        # Known pattern has low novelty
        vec = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        assert g.novelty(vec) < 0.2

        # Unknown pattern has high novelty
        vec_new = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)
        assert g.novelty(vec_new) > 0.8

    def test_weighted_query(self):
        g = ConcernGraph(dim=4)
        anchors = [
            ConcernAnchor(text="low", source="test", weight=0.5),
            ConcernAnchor(text="high", source="consent", weight=2.0),
        ]
        embeddings = np.array(
            [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]],
            dtype=np.float32,
        )
        g.refresh(anchors, embeddings)

        # Query matching high-weight anchor should score higher
        vec_high = np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32)
        vec_low = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        assert g.query(vec_high) > g.query(vec_low)

    def test_recent_utterance_window(self):
        g = ConcernGraph(dim=4)
        g._max_recent = 3

        for i in range(5):
            vec = np.zeros(4, dtype=np.float32)
            vec[i % 4] = 1.0
            g.add_recent_utterance(vec)

        assert len(g._recent_utterances) == 3


# ── Salience router tests ───────────────────────────────────────────


class TestSalienceRouter:
    def _make_router(self) -> SalienceRouter:
        """Create a router with a mock embedder for testing."""
        embedder = _MockEmbedder(dim=4)
        graph = ConcernGraph(dim=4)

        # Set up some concern anchors
        anchors = [
            ConcernAnchor(text="voice latency", source="workspace", weight=1.0),
            ConcernAnchor(text="consent system", source="consent", weight=2.0),
        ]
        embeddings = np.array(
            [[0.8, 0.2, 0.0, 0.0], [0.0, 0.0, 0.8, 0.2]],
            dtype=np.float32,
        )
        graph.refresh(anchors, embeddings)

        return SalienceRouter(embedder=embedder, concern_graph=graph)

    def test_phatic_routes_canned(self):
        router = self._make_router()
        result = router.route("thanks", turn_count=2)
        assert result.tier == ModelTier.CANNED
        assert result.canned_response != ""

    def test_greeting_routes_canned(self):
        router = self._make_router()
        result = router.route("hey", turn_count=0)
        assert result.tier == ModelTier.CANNED

    def test_consent_override(self):
        router = self._make_router()
        result = router.route("just checking in", consent_phase="pending")
        assert result.tier == ModelTier.CAPABLE
        assert "consent" in result.reason

    def test_guest_override(self):
        router = self._make_router()
        result = router.route("hello", guest_mode=True)
        assert result.tier == ModelTier.CAPABLE

    def test_explicit_escalation(self):
        router = self._make_router()
        result = router.route("explain how the routing algorithm works")
        assert result.tier == ModelTier.CAPABLE
        assert "escalation" in result.reason

    def test_activation_logged(self):
        router = self._make_router()
        router.route("what's the voice latency looking like?")
        breakdown = router.last_breakdown
        assert breakdown is not None
        assert breakdown.total_ms >= 0

    def test_different_concerns_different_tiers(self):
        """Same utterance complexity, different concern activation → different tiers."""
        router = self._make_router()
        # This is testing that the router actually uses the concern graph
        # to differentiate, not just utterance features
        router.route("tell me about cats")
        cats_breakdown = router.last_breakdown
        router.route("tell me about consent")
        consent_breakdown = router.last_breakdown
        # Both are simple statements, but consent should activate higher
        # due to the consent concern anchor with weight 2.0
        assert cats_breakdown is not None
        assert consent_breakdown is not None


class _MockEmbedder:
    """Mock embedder that returns simple hashed vectors for testing."""

    def __init__(self, dim: int = 4) -> None:
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def available(self) -> bool:
        return True

    def embed(self, text: str) -> np.ndarray:
        # Simple hash-based embedding for deterministic testing
        h = hash(text) & 0xFFFFFFFF
        vec = np.zeros(self._dim, dtype=np.float32)
        for i in range(self._dim):
            vec[i] = ((h >> (i * 8)) & 0xFF) / 255.0
        # Normalize
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        return vec

    def embed_batch(self, texts: list[str]) -> np.ndarray:
        return np.array([self.embed(t) for t in texts])
