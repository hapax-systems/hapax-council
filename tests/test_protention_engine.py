"""Tests for the protention engine — statistical transition probability model."""

from __future__ import annotations

import time
from pathlib import Path

from agents.protention_engine import (
    CircadianModel,
    FlowTimingModel,
    MarkovChain,
    ProtentionEngine,
    ProtentionSnapshot,
    TransitionPrediction,
)


class TestMarkovChain:
    def test_empty_chain_no_predictions(self):
        chain = MarkovChain()
        assert chain.predict("coding") == []

    def test_single_transition(self):
        chain = MarkovChain()
        chain.observe("coding", "browsing")
        preds = chain.predict("coding")
        assert len(preds) >= 1
        assert any(s == "browsing" for s, _ in preds)

    def test_multiple_transitions(self):
        chain = MarkovChain()
        for _ in range(8):
            chain.observe("coding", "browsing")
        for _ in range(2):
            chain.observe("coding", "break")
        preds = chain.predict("coding")
        # browsing should be higher probability than break
        browsing_prob = next((p for s, p in preds if s == "browsing"), 0)
        break_prob = next((p for s, p in preds if s == "break"), 0)
        assert browsing_prob > break_prob

    def test_laplace_smoothing(self):
        chain = MarkovChain(smoothing=0.1)
        chain.observe("coding", "browsing")
        preds = chain.predict("coding")
        # Even unseen transitions should have small probability
        browsing_prob = next((p for s, p in preds if s == "browsing"), 0)
        assert browsing_prob < 1.0  # not 100% due to smoothing

    def test_total_observations(self):
        chain = MarkovChain()
        chain.observe("a", "b")
        chain.observe("b", "c")
        assert chain.total_observations == 2

    def test_serialization_roundtrip(self):
        chain = MarkovChain()
        chain.observe("coding", "browsing")
        chain.observe("coding", "browsing")
        chain.observe("browsing", "coding")
        data = chain.to_dict()
        restored = MarkovChain.from_dict(data)
        assert restored.total_observations == 3
        assert restored.predict("coding") == chain.predict("coding")


class TestFlowTimingModel:
    def test_no_data_returns_none(self):
        model = FlowTimingModel()
        assert model.predict_remaining("active", 100) is None

    def test_records_and_predicts(self):
        model = FlowTimingModel()
        now = time.monotonic()
        # Simulate 5 flow sessions of ~30 min each
        for i in range(5):
            model.observe("active", now + i * 3600)
            model.observe("idle", now + i * 3600 + 1800)  # 30 min later
        remaining = model.predict_remaining("active", 1500)  # 25 min into session
        assert remaining is not None
        assert remaining < 600  # should predict < 10 min remaining

    def test_short_blips_ignored(self):
        model = FlowTimingModel()
        now = time.monotonic()
        model.observe("active", now)
        model.observe("idle", now + 3)  # 3s blip, should be ignored
        assert len(model._session_durations) == 0

    def test_median_duration(self):
        model = FlowTimingModel()
        now = time.monotonic()
        for i, dur in enumerate([600, 1200, 1800, 2400, 3000]):
            model.observe("active", now + i * 5000)
            model.observe("idle", now + i * 5000 + dur)
        assert abs(model.median_duration - 1800) < 1.0

    def test_serialization_roundtrip(self):
        model = FlowTimingModel()
        model._session_durations = [600, 1200, 1800]
        data = model.to_dict()
        restored = FlowTimingModel.from_dict(data)
        assert restored._session_durations == [600, 1200, 1800]


class TestCircadianModel:
    def test_no_data_returns_none(self):
        model = CircadianModel()
        assert model.typical_activity(14) is None
        assert model.typical_flow(14) is None

    def test_records_and_predicts_activity(self):
        model = CircadianModel()
        for _ in range(10):
            model.observe(14, "coding", 0.7)
        for _ in range(3):
            model.observe(14, "browsing", 0.2)
        assert model.typical_activity(14) == "coding"

    def test_records_and_predicts_flow(self):
        model = CircadianModel()
        for _ in range(10):
            model.observe(10, "coding", 0.6)
        flow = model.typical_flow(10)
        assert flow is not None
        assert flow == 0.6

    def test_serialization_roundtrip(self):
        model = CircadianModel()
        for _ in range(8):
            model.observe(9, "coding", 0.5)
        data = model.to_dict()
        restored = CircadianModel.from_dict(data)
        assert restored.typical_activity(9) == "coding"


class TestProtentionEngine:
    def test_empty_engine_produces_empty_predictions(self):
        engine = ProtentionEngine()
        snap = engine.predict("coding", 0.5, 14)
        assert isinstance(snap, ProtentionSnapshot)
        assert snap.observation_count == 0

    def test_learns_activity_transitions(self):
        engine = ProtentionEngine()
        now = time.monotonic()
        # Feed a pattern: coding → browsing (8x), coding → break (2x)
        for i in range(8):
            engine.observe("coding", 0.5, 14, now=now + i * 10)
            engine.observe("browsing", 0.2, 14, now=now + i * 10 + 5)
        for i in range(2):
            engine.observe("coding", 0.5, 14, now=now + 100 + i * 10)
            engine.observe("break", 0.0, 14, now=now + 100 + i * 10 + 5)
        snap = engine.predict("coding", 0.5, 14)
        assert snap.observation_count > 0
        activity_preds = [p for p in snap.predictions if p.dimension == "activity"]
        assert len(activity_preds) >= 1

    def test_flow_timing_prediction(self):
        engine = ProtentionEngine()
        now = time.monotonic()
        # Teach it 5 flow sessions of ~30 min
        for i in range(5):
            base = now + i * 5000
            engine._flow_timing.observe("active", base)
            engine._flow_timing.observe("idle", base + 1800)
        # Now predict while in active flow for 25 min
        engine._last_flow_state = "active"
        engine._flow_session_start = now - 1500
        snap = engine.predict("coding", 0.7, 14, now=now)
        flow_preds = [p for p in snap.predictions if p.dimension == "flow"]
        assert len(flow_preds) >= 1

    def test_circadian_prediction(self):
        engine = ProtentionEngine()
        now = time.monotonic()
        # Teach it: at 9am, usually coding
        for _ in range(10):
            engine._circadian.observe(9, "coding", 0.6)
        # Predict when doing something else at 9am
        snap = engine.predict("browsing", 0.2, 9, now=now)
        circadian_preds = [p for p in snap.predictions if p.dimension == "circadian"]
        assert any(p.predicted_value == "coding" for p in circadian_preds)

    def test_save_and_load(self, tmp_path: Path):
        engine = ProtentionEngine()
        now = time.monotonic()
        for i in range(5):
            engine.observe("coding", 0.5, 14, now=now + i * 10)
            engine.observe("browsing", 0.2, 14, now=now + i * 10 + 5)
        path = tmp_path / "protention.json"
        engine.save(path)
        assert path.exists()

        engine2 = ProtentionEngine()
        assert engine2.load(path)
        assert engine2._activity_chain.total_observations > 0

    def test_load_missing_file(self, tmp_path: Path):
        engine = ProtentionEngine()
        assert not engine.load(tmp_path / "nonexistent.json")

    def test_top_predictions_filtered(self):
        snap = ProtentionSnapshot(
            predictions=[
                TransitionPrediction(
                    dimension="activity",
                    predicted_value="browsing",
                    probability=0.6,
                    expected_in_s=120,
                    basis="test",
                ),
                TransitionPrediction(
                    dimension="activity",
                    predicted_value="break",
                    probability=0.1,
                    expected_in_s=120,
                    basis="test",
                ),
                TransitionPrediction(
                    dimension="flow",
                    predicted_value="flow_ending",
                    probability=0.5,
                    expected_in_s=300,
                    basis="test",
                ),
            ]
        )
        top = snap.top_predictions
        assert len(top) == 2  # break filtered out (p=0.1 < 0.3)
        assert top[0].probability >= top[1].probability
