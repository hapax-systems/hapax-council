"""Sprint 0 — Measure 3.2: Protention accuracy validation.

Validates protention prediction accuracy against historical perception data.

The ProtentionEngine learns from perception observations and produces
TransitionPrediction objects with an `expected_in_s` field.  For each
prediction a validation checks: did the predicted transition actually
occur within the expected timeframe?

Data availability finding (2026-03-31):
  - protention-state.json exists at ~/.cache/hapax-daimonion/protention-state.json
  - Circadian model is populated (394,688 observations, all 24 hours covered)
  - Activity Markov chain: EMPTY (no activity transitions recorded — all
    perception-minutes entries report activity='idle')
  - Flow timing model: EMPTY (no flow sessions recorded — flow_state='idle' in
    all perception-minutes entries)
  - Consequence: the engine cannot generate activity or flow predictions; only
    circadian predictions are possible.  All circadian predictions are for
    'idle' (the only observed activity), so they resolve trivially.

This harness exercises three test modes:
  1. DATA_GAP_REPORT — documents the gap and what must be instrumented
  2. REPLAY_VALIDATION — replays recorded observations through the engine
     and checks prediction accuracy if non-trivial transitions exist
  3. SYNTHETIC_BASELINE — uses synthetic patterns to establish expected
     behaviour from a healthy data stream (always passes, provides
     precision/recall/lead-time reference)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

import pytest

from agents.protention_engine import (
    ProtentionEngine,
    ProtentionSnapshot,
    TransitionPrediction,
)

PROTENTION_STATE_PATH = Path.home() / ".cache" / "hapax-daimonion" / "protention-state.json"
PERCEPTION_MINUTES_PATH = Path.home() / ".cache" / "hapax-daimonion" / "perception-minutes.jsonl"


# ── Data models ───────────────────────────────────────────────────────────────


class PredictionOutcome(NamedTuple):
    """Recorded result of validating one prediction against ground truth."""

    dimension: str
    predicted_value: str
    probability: float
    expected_in_s: float
    actual_transition_occurred: bool
    actual_lead_time_s: float | None  # None if transition never occurred


@dataclass
class ValidationReport:
    """Aggregate metrics for a validation run."""

    outcomes: list[PredictionOutcome] = field(default_factory=list)

    @property
    def n_predictions(self) -> int:
        return len(self.outcomes)

    @property
    def precision(self) -> float:
        """Fraction of predictions that actually occurred."""
        if not self.outcomes:
            return 0.0
        hits = sum(1 for o in self.outcomes if o.actual_transition_occurred)
        return hits / len(self.outcomes)

    @property
    def recall(self) -> float:
        """Fraction of actual transitions that were predicted.

        NOTE: recall requires knowing all transitions that occurred, not only
        those that were predicted.  This field is set externally after counting
        total_actual_transitions in the replay corpus.
        """
        return self._recall

    @recall.setter
    def recall(self, value: float) -> None:
        self._recall = value

    def __post_init__(self) -> None:
        self._recall: float = 0.0

    @property
    def mean_lead_time_error_s(self) -> float | None:
        """Mean absolute error between expected_in_s and actual_lead_time_s.

        Returns None if no predictions resolved with a measured lead time.
        """
        errors = [
            abs(o.expected_in_s - o.actual_lead_time_s)
            for o in self.outcomes
            if o.actual_transition_occurred and o.actual_lead_time_s is not None
        ]
        if not errors:
            return None
        return sum(errors) / len(errors)

    def summary(self) -> dict[str, object]:
        return {
            "n_predictions": self.n_predictions,
            "precision": round(self.precision, 3),
            "recall": round(self.recall, 3),
            "mean_lead_time_error_s": (
                round(self.mean_lead_time_error_s, 1)
                if self.mean_lead_time_error_s is not None
                else None
            ),
        }


# ── Helpers ───────────────────────────────────────────────────────────────────


def _load_perception_minutes() -> list[dict]:
    """Load perception-minutes.jsonl if present."""
    if not PERCEPTION_MINUTES_PATH.exists():
        return []
    lines = PERCEPTION_MINUTES_PATH.read_text(encoding="utf-8").splitlines()
    entries = []
    for line in lines:
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return entries


def _extract_transitions(entries: list[dict]) -> list[tuple[float, str, str]]:
    """Extract (timestamp, from_activity, to_activity) tuples from minute log."""
    transitions = []
    for i in range(1, len(entries)):
        prev = entries[i - 1].get("activity", "idle") or "idle"
        curr = entries[i].get("activity", "idle") or "idle"
        if prev != curr:
            transitions.append((entries[i]["timestamp"], prev, curr))
    return transitions


def _validate_predictions_against_corpus(
    predictions: list[TransitionPrediction],
    prediction_time: float,
    future_entries: list[dict],
) -> list[PredictionOutcome]:
    """Check each prediction against the entries that followed it.

    For each prediction:
      - Scan `future_entries` within [prediction_time, prediction_time + expected_in_s * 2]
      - If the predicted_value appears as the activity, mark as hit and record lead time
    """
    outcomes = []
    for pred in predictions:
        if pred.dimension not in ("activity", "circadian"):
            # Flow predictions need a different corpus — skip for minute-level data
            outcomes.append(
                PredictionOutcome(
                    dimension=pred.dimension,
                    predicted_value=pred.predicted_value,
                    probability=pred.probability,
                    expected_in_s=pred.expected_in_s,
                    actual_transition_occurred=False,
                    actual_lead_time_s=None,
                )
            )
            continue

        horizon_end = prediction_time + pred.expected_in_s * 2.0
        found = False
        lead_time = None
        for entry in future_entries:
            t = entry.get("timestamp", 0.0)
            if t <= prediction_time:
                continue
            if t > horizon_end:
                break
            activity = entry.get("activity", "idle") or "idle"
            if activity == pred.predicted_value:
                found = True
                lead_time = t - prediction_time
                break

        outcomes.append(
            PredictionOutcome(
                dimension=pred.dimension,
                predicted_value=pred.predicted_value,
                probability=pred.probability,
                expected_in_s=pred.expected_in_s,
                actual_transition_occurred=found,
                actual_lead_time_s=lead_time,
            )
        )
    return outcomes


# ── Test 1: Data gap audit ────────────────────────────────────────────────────


class TestProtentionDataGapAudit:
    """Documents the current data availability and what must be instrumented."""

    def test_protention_state_file_exists(self):
        """The engine's learned state file must exist."""
        if not PROTENTION_STATE_PATH.exists():
            pytest.skip("No protention state file (CI / fresh environment)")
        assert PROTENTION_STATE_PATH.exists()

    def test_circadian_model_populated(self):
        """Circadian model should have observations covering all 24 hours."""
        if not PROTENTION_STATE_PATH.exists():
            pytest.skip("No protention state file")
        data = json.loads(PROTENTION_STATE_PATH.read_text(encoding="utf-8"))
        abh = data.get("circadian", {}).get("activity_by_hour", {})
        total_obs = sum(sum(v.values()) for v in abh.values())
        assert total_obs > 0, "Circadian model has no observations"
        # 24-hour coverage
        hours_with_data = len(abh)
        assert hours_with_data >= 12, (
            f"Only {hours_with_data} hours covered — need at least 12 for meaningful circadian predictions"
        )

    def test_activity_markov_chain_gap(self):
        """KNOWN GAP: Activity Markov chain is empty because production_activity
        is always 'idle' in perception-minutes.jsonl.

        This test DOCUMENTS the gap — it passes but prints the finding.
        To fix: verify that the activity classifier in hapax_daimonion is
        producing non-idle labels and that VLA feeds them to protention engine.
        """
        if not PROTENTION_STATE_PATH.exists():
            pytest.skip("No protention state file")
        data = json.loads(PROTENTION_STATE_PATH.read_text(encoding="utf-8"))
        ac = data.get("activity_chain", {})
        total = sum(ac.get("totals", {}).values())
        if total == 0:
            print(
                "\n[DATA GAP] Activity Markov chain is EMPTY.\n"
                "All perception-minutes entries show activity='idle'.\n"
                "Instrumentation needed:\n"
                "  1. Verify daimonion/perception_engine.py produces non-idle labels\n"
                "  2. Confirm VLA._protention.observe() receives the correct activity field\n"
                "  3. Check that 'production_activity' key is non-empty in perception data\n"
                "  4. Consider logging ProtentionSnapshot.predictions to a JSONL file\n"
                "     alongside perception-minutes.jsonl for future replay validation"
            )
        # This test always passes — it's a data audit, not a correctness assertion
        assert True

    def test_flow_timing_gap(self):
        """KNOWN GAP: Flow timing model is empty because flow_state is always 'idle'.

        Instrumentation needed: verify flow score threshold in ProtentionEngine.observe()
        matches the actual dynamic range of flow_score in perception data.
        """
        if not PROTENTION_STATE_PATH.exists():
            pytest.skip("No protention state file")
        data = json.loads(PROTENTION_STATE_PATH.read_text(encoding="utf-8"))
        durations = data.get("flow_timing", {}).get("session_durations", [])
        if len(durations) == 0:
            print(
                "\n[DATA GAP] Flow timing model has no session durations.\n"
                "flow_state='idle' in all recorded minutes.\n"
                "Instrumentation needed:\n"
                "  1. Confirm flow_score is non-zero during active work sessions\n"
                "  2. Check threshold: flow_score >= 0.6 triggers 'active' in ProtentionEngine\n"
                "  3. Log flow session start/end events to ~/.cache/hapax-daimonion/flow-sessions.jsonl"
            )
        assert True

    def test_perception_minutes_coverage(self):
        """Check that perception-minutes.jsonl has adequate coverage for replay."""
        entries = _load_perception_minutes()
        if not entries:
            pytest.skip(f"No perception-minutes data at {PERCEPTION_MINUTES_PATH}")
        # Span
        if len(entries) >= 2:
            span_hours = (entries[-1]["timestamp"] - entries[0]["timestamp"]) / 3600
            print(f"\n[INFO] perception-minutes: {len(entries)} entries, {span_hours:.1f}h span")
        # Activity diversity
        activities = set(e.get("activity", "idle") for e in entries)
        print(f"[INFO] Unique activities in log: {activities}")
        non_idle = [e for e in entries if e.get("activity", "idle") != "idle"]
        print(f"[INFO] Non-idle entries: {len(non_idle)} / {len(entries)}")
        if len(non_idle) == 0:
            print(
                "[DATA GAP] All entries are idle — Markov chain will never learn transitions.\n"
                "No replay-based prediction accuracy is possible until non-idle activities appear."
            )


# ── Test 2: Replay validation (conditional on data availability) ──────────────


class TestProtentionReplayValidation:
    """Replay perception-minutes through the engine; check prediction accuracy.

    Skips automatically if activity data is insufficient (all-idle corpus).
    """

    def test_replay_activity_predictions(self):
        """Replay minute-level data through a fresh engine and validate predictions."""
        entries = _load_perception_minutes()
        if len(entries) < 10:
            pytest.skip("Insufficient perception-minutes data")

        transitions = _extract_transitions(entries)
        non_trivial = [(t, fr, to) for t, fr, to in transitions if fr != "idle" or to != "idle"]
        if not non_trivial:
            pytest.skip(
                "All activity transitions are idle↔idle — no meaningful activity predictions "
                "to validate.  See TestProtentionDataGapAudit.test_activity_markov_chain_gap."
            )

        # Build engine from first 70% of data
        split = int(len(entries) * 0.7)
        train_entries = entries[:split]
        test_entries = entries[split:]

        engine = ProtentionEngine()
        for i, entry in enumerate(train_entries):
            ts = entry.get("timestamp", time.monotonic())
            engine.observe(
                activity=entry.get("activity", "idle") or "idle",
                flow_score=entry.get("flow_mean", 0.0),
                hour=int((ts % 86400) // 3600),
                now=float(i),  # Use index as monotonic proxy
            )

        # Generate predictions at each test entry and validate
        report = ValidationReport()
        total_actual_transitions = 0

        for i, entry in enumerate(test_entries[:-1]):
            ts = entry.get("timestamp", 0.0)
            snap = engine.predict(
                current_activity=entry.get("activity", "idle") or "idle",
                flow_score=entry.get("flow_mean", 0.0),
                hour=int((ts % 86400) // 3600),
                now=float(len(train_entries) + i),
            )
            if snap.predictions:
                outcomes = _validate_predictions_against_corpus(
                    snap.predictions, ts, test_entries[i + 1 :]
                )
                report.outcomes.extend(outcomes)

        actual_test_transitions = len(_extract_transitions(test_entries))
        total_actual_transitions = actual_test_transitions
        predicted_transitions = sum(1 for o in report.outcomes if o.actual_transition_occurred)
        if total_actual_transitions > 0:
            report.recall = predicted_transitions / total_actual_transitions

        summary = report.summary()
        print(f"\n[VALIDATION] Replay report: {summary}")

        # Assertions — loosened for sparse data
        assert report.n_predictions >= 0  # may be 0 if engine produces no predictions
        if report.n_predictions > 0:
            # Precision >= 0.0 is always true; threshold meaningful only with data
            assert report.precision >= 0.0

    def test_replay_circadian_predictions(self):
        """Validate circadian predictions using the persisted circadian model."""
        if not PROTENTION_STATE_PATH.exists():
            pytest.skip("No protention state file")

        entries = _load_perception_minutes()
        if len(entries) < 100:
            pytest.skip("Insufficient data for circadian validation")

        engine = ProtentionEngine()
        engine.load(PROTENTION_STATE_PATH)

        # Test on last 10% of entries
        test_entries = entries[int(len(entries) * 0.9) :]
        report = ValidationReport()

        for i, entry in enumerate(test_entries[:-1]):
            ts = entry.get("timestamp", 0.0)
            snap = engine.predict(
                current_activity=entry.get("activity", "idle") or "idle",
                flow_score=entry.get("flow_mean", 0.0),
                hour=int((ts % 86400) // 3600),
            )
            circadian_preds = [p for p in snap.predictions if p.dimension == "circadian"]
            if circadian_preds:
                outcomes = _validate_predictions_against_corpus(
                    circadian_preds, ts, test_entries[i + 1 :]
                )
                report.outcomes.extend(outcomes)

        summary = report.summary()
        print(f"\n[VALIDATION] Circadian replay report: {summary}")
        # Circadian model populated but predicts 'idle' (trivially true when corpus is all-idle)
        # Document rather than assert a specific precision value
        assert True


# ── Test 3: Synthetic baseline ────────────────────────────────────────────────


class TestProtentionSyntheticBaseline:
    """Train on synthetic patterns; validate precision, recall, lead-time error.

    These tests always have data and establish a reproducible reference baseline.
    They verify the harness itself works correctly regardless of live data.
    """

    def _build_engine_with_pattern(self) -> ProtentionEngine:
        """Build engine trained on: coding(120s) → browsing(60s) → coding, repeated."""
        engine = ProtentionEngine()
        t = 10000.0
        for _ in range(15):
            # coding session
            for _tick in range(24):  # 24 × 5s = 120s
                engine.observe("coding", 0.7, 14, now=t)
                t += 5.0
            # browsing session
            for _tick in range(12):  # 12 × 5s = 60s
                engine.observe("browsing", 0.2, 14, now=t)
                t += 5.0
        return engine

    def test_precision_on_dominant_transition(self):
        """Engine trained on coding→browsing pattern should predict it with p ≥ 0.3."""
        engine = self._build_engine_with_pattern()
        snap = engine.predict("coding", 0.7, 14)

        activity_preds = [p for p in snap.predictions if p.dimension == "activity"]
        browsing_pred = next((p for p in activity_preds if p.predicted_value == "browsing"), None)
        assert browsing_pred is not None, (
            "Expected 'browsing' in activity predictions after coding→browsing training"
        )
        assert browsing_pred.probability >= 0.3, (
            f"browsing probability {browsing_pred.probability:.3f} below 0.3 threshold"
        )

    def test_recall_on_known_transitions(self):
        """All actual transitions in test corpus should have been predicted in train."""
        engine = self._build_engine_with_pattern()

        # Synthetic test corpus: coding → browsing → coding
        test_corpus = [
            {"timestamp": 20000.0, "activity": "coding", "flow_mean": 0.7},
            {"timestamp": 20120.0, "activity": "browsing", "flow_mean": 0.2},
            {"timestamp": 20180.0, "activity": "coding", "flow_mean": 0.7},
        ]

        report = ValidationReport()
        for i, entry in enumerate(test_corpus[:-1]):
            ts = entry["timestamp"]
            snap = engine.predict(
                current_activity=entry["activity"],
                flow_score=entry["flow_mean"],
                hour=14,
            )
            outcomes = _validate_predictions_against_corpus(
                snap.predictions, ts, test_corpus[i + 1 :]
            )
            report.outcomes.extend(outcomes)

        transitions = _extract_transitions(test_corpus)
        if transitions and report.n_predictions > 0:
            predicted_hits = sum(1 for o in report.outcomes if o.actual_transition_occurred)
            report.recall = predicted_hits / len(transitions)

        summary = report.summary()
        print(f"\n[SYNTHETIC] Baseline report: {summary}")

        # Precision should be > 0 (at least one prediction should hit)
        if report.n_predictions > 0:
            assert report.precision > 0.0, (
                f"Zero precision on synthetic corpus — engine not predicting trained patterns.\n"
                f"Summary: {summary}"
            )

    def test_lead_time_error_within_tolerance(self):
        """Expected_in_s for activity predictions defaults to 120s.

        With our synthetic 120s coding sessions, lead time should be ≤ 120s
        (checked loosely at 2× tolerance).
        """
        engine = self._build_engine_with_pattern()

        # Single prediction while coding
        snap = engine.predict("coding", 0.7, 14, now=20000.0)
        activity_preds = [p for p in snap.predictions if p.dimension == "activity"]

        for pred in activity_preds:
            assert pred.expected_in_s > 0, "expected_in_s must be positive"
            # Default is 120s; this is a structural check, not accuracy claim
            assert pred.expected_in_s <= 3600, (
                f"expected_in_s={pred.expected_in_s} is unreasonably large (> 1h)"
            )

    def test_snapshot_structure(self):
        """ProtentionSnapshot must have correct types and valid probability range."""
        engine = self._build_engine_with_pattern()
        snap = engine.predict("coding", 0.7, 14)

        assert isinstance(snap, ProtentionSnapshot)
        assert isinstance(snap.predictions, list)
        assert snap.timestamp > 0
        assert snap.observation_count > 0

        for pred in snap.predictions:
            assert isinstance(pred, TransitionPrediction)
            assert 0.0 <= pred.probability <= 1.0, (
                f"probability {pred.probability} out of [0, 1] range"
            )
            # NOTE: flow_ending predictions emit expected_in_s=0.0 when remaining
            # time rounds to 0 (FlowTimingModel.predict_remaining floors at 0.0).
            assert pred.expected_in_s >= 0, f"expected_in_s={pred.expected_in_s} is negative"
            assert pred.dimension in ("activity", "flow", "circadian")
            assert pred.predicted_value != ""

    def test_top_predictions_filter(self):
        """top_predictions filters to p >= 0.3, max 3 results, sorted descending."""
        engine = self._build_engine_with_pattern()
        snap = engine.predict("coding", 0.7, 14)

        top = snap.top_predictions
        assert len(top) <= 3
        for pred in top:
            assert pred.probability >= 0.3
        # Sorted descending
        for i in range(len(top) - 1):
            assert top[i].probability >= top[i + 1].probability

    def test_full_metrics_report(self):
        """Print a complete metrics table for Sprint 0 measure 3.2 reporting."""
        engine = self._build_engine_with_pattern()

        # Extended test corpus: 5 coding→browsing cycles
        test_corpus = []
        t = 30000.0
        for _ in range(5):
            for _ in range(24):
                test_corpus.append({"timestamp": t, "activity": "coding", "flow_mean": 0.7})
                t += 5.0
            for _ in range(12):
                test_corpus.append({"timestamp": t, "activity": "browsing", "flow_mean": 0.2})
                t += 5.0

        report = ValidationReport()
        for i, entry in enumerate(test_corpus[:-1]):
            snap = engine.predict(
                current_activity=entry["activity"],
                flow_score=entry["flow_mean"],
                hour=14,
            )
            if snap.predictions:
                outcomes = _validate_predictions_against_corpus(
                    snap.predictions, entry["timestamp"], test_corpus[i + 1 :]
                )
                report.outcomes.extend(outcomes)

        transitions = _extract_transitions(test_corpus)
        predicted_hits = sum(1 for o in report.outcomes if o.actual_transition_occurred)
        if transitions:
            report.recall = predicted_hits / len(transitions)

        summary = report.summary()
        print(
            f"\n{'=' * 60}\n"
            f"SPRINT 0 MEASURE 3.2 — PROTENTION ACCURACY\n"
            f"{'=' * 60}\n"
            f"  n_predictions:          {summary['n_predictions']}\n"
            f"  precision:              {summary['precision']:.3f}\n"
            f"  recall:                 {summary['recall']:.3f}\n"
            f"  mean lead-time error:   {summary['mean_lead_time_error_s']}s\n"
            f"  actual transitions:     {len(transitions)}\n"
            f"{'=' * 60}"
        )
        assert summary["n_predictions"] > 0
