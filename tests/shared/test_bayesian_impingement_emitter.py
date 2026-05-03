"""Tests for shared/bayesian_impingement_emitter.py.

Pins the audit-3 fix #1 contract: state-transition events from the five
Bayesian engines + prediction-miss events from reverie_prediction_monitor
all reach the impingement bus as richly-narrated PATTERN_MATCH events with
narrative diversity sourced from the actual measured values.
"""

from __future__ import annotations

import json
from pathlib import Path

from shared.bayesian_impingement_emitter import (
    emit_prediction_miss_impingement,
    emit_state_transition_impingement,
)
from shared.impingement import ImpingementType


class TestStateTransitionEmitter:
    def test_emits_when_state_changes(self, tmp_path: Path) -> None:
        bus = tmp_path / "impingements.jsonl"
        ok = emit_state_transition_impingement(
            source="presence_engine",
            claim_name="operator-presence",
            from_state="UNCERTAIN",
            to_state="PRESENT",
            posterior=0.85,
            prev_posterior=0.55,
            bus_path=bus,
        )
        assert ok is True
        assert bus.exists()
        line = bus.read_text().strip().splitlines()[0]
        payload = json.loads(line)
        assert payload["source"] == "presence_engine"
        assert payload["type"] == ImpingementType.PATTERN_MATCH.value
        assert payload["content"]["from_state"] == "UNCERTAIN"
        assert payload["content"]["to_state"] == "PRESENT"
        assert payload["content"]["posterior"] == 0.85
        assert payload["content"]["prev_posterior"] == 0.55
        # Δposterior = 0.85 - 0.55 = 0.30 → strength
        assert abs(payload["strength"] - 0.30) < 1e-9
        # Narrative MUST contain the actual measured values (the whole
        # point of the fix is no frozen templates).
        narrative = payload["content"]["narrative"]
        assert "operator-presence" in narrative
        assert "PRESENT" in narrative
        assert "UNCERTAIN" in narrative
        assert "0.85" in narrative

    def test_no_emit_when_state_unchanged(self, tmp_path: Path) -> None:
        bus = tmp_path / "impingements.jsonl"
        ok = emit_state_transition_impingement(
            source="mood_arousal",
            claim_name="mood-arousal-high",
            from_state="UNCERTAIN",
            to_state="UNCERTAIN",
            posterior=0.42,
            prev_posterior=0.40,
            bus_path=bus,
        )
        assert ok is False
        assert not bus.exists()

    def test_narrative_diversity_across_transitions(self, tmp_path: Path) -> None:
        """Two different transitions produce two different narratives.

        The whole point of the fix is breaking the frozen-template pattern.
        Different posteriors → different narratives → cosine recruiter
        sees diverse intent strings.
        """
        bus = tmp_path / "impingements.jsonl"
        emit_state_transition_impingement(
            source="mood_valence",
            claim_name="mood-valence-negative",
            from_state="UNCERTAIN",
            to_state="NEGATIVE",
            posterior=0.71,
            prev_posterior=0.45,
            active_signals={"hrv_below_baseline": True, "sleep_debt_high": True},
            bus_path=bus,
        )
        emit_state_transition_impingement(
            source="mood_valence",
            claim_name="mood-valence-negative",
            from_state="NEGATIVE",
            to_state="UNCERTAIN",
            posterior=0.34,
            prev_posterior=0.62,
            active_signals={"hrv_below_baseline": False},
            bus_path=bus,
        )
        lines = bus.read_text().strip().splitlines()
        assert len(lines) == 2
        narratives = [json.loads(line)["content"]["narrative"] for line in lines]
        assert narratives[0] != narratives[1]
        # First includes signals fingerprint; second has different value
        assert "0.71" in narratives[0]
        assert "0.34" in narratives[1]
        assert "hrv_below_baseline=True" in narratives[0]
        assert "hrv_below_baseline=False" in narratives[1]

    def test_first_transition_omits_delta(self, tmp_path: Path) -> None:
        bus = tmp_path / "impingements.jsonl"
        emit_state_transition_impingement(
            source="mood_coherence",
            claim_name="mood-coherence-low",
            from_state="UNCERTAIN",
            to_state="INCOHERENT",
            posterior=0.72,
            prev_posterior=None,
            bus_path=bus,
        )
        payload = json.loads(bus.read_text().strip())
        assert payload["content"]["prev_posterior"] is None
        assert payload["content"]["delta_posterior"] is None
        # Strength falls back to |posterior| when no prev available
        assert abs(payload["strength"] - 0.72) < 1e-9
        assert "Δ" not in payload["content"]["narrative"]

    def test_strength_clamped_to_unit_interval(self, tmp_path: Path) -> None:
        """The Impingement schema constrains strength ∈ [0, 1]; a 1.5
        delta from a malformed engine call must NOT raise."""
        bus = tmp_path / "impingements.jsonl"
        ok = emit_state_transition_impingement(
            source="presence_engine",
            claim_name="operator-presence",
            from_state="AWAY",
            to_state="PRESENT",
            posterior=2.5,  # Bad input, but emitter must not crash
            prev_posterior=0.0,
            bus_path=bus,
        )
        assert ok is True
        payload = json.loads(bus.read_text().strip())
        assert 0.0 <= payload["strength"] <= 1.0


class TestPredictionMissEmitter:
    def test_emits_on_miss(self, tmp_path: Path) -> None:
        bus = tmp_path / "impingements.jsonl"
        ok = emit_prediction_miss_impingement(
            prediction_name="P1_thompson_convergence",
            expected="≥0.70 (plateau expected)",
            observed=0.42,
            alert="Thompson mean 0.420 — still below 0.70 after 3.5h",
            detail='{"content.imagination_image": 0.42}',
            bus_path=bus,
        )
        assert ok is True
        payload = json.loads(bus.read_text().strip())
        assert payload["source"] == "reverie_prediction"
        assert payload["type"] == ImpingementType.PATTERN_MATCH.value
        assert payload["content"]["prediction"] == "P1_thompson_convergence"
        assert payload["content"]["observed"] == 0.42
        assert payload["strength"] == 1.0
        narrative = payload["content"]["narrative"]
        assert "P1_thompson_convergence" in narrative
        assert "0.420" in narrative
        assert "expected" in narrative
        # Detail clipped at 200 chars but our short detail passes through
        assert payload["content"]["detail"] == '{"content.imagination_image": 0.42}'

    def test_long_detail_clipped(self, tmp_path: Path) -> None:
        bus = tmp_path / "impingements.jsonl"
        big_detail = "x" * 5_000
        emit_prediction_miss_impingement(
            prediction_name="P3_hebbian",
            expected="≥10 distinct pairings",
            observed=2.0,
            alert="Only 2 associations after 26h",
            detail=big_detail,
            bus_path=bus,
        )
        payload = json.loads(bus.read_text().strip())
        assert len(payload["content"]["detail"]) == 200

    def test_diverse_narratives_across_misses(self, tmp_path: Path) -> None:
        """Two prediction misses produce two unique narratives."""
        bus = tmp_path / "impingements.jsonl"
        emit_prediction_miss_impingement(
            prediction_name="P1_thompson_convergence",
            expected="≥0.70",
            observed=0.42,
            alert="below 0.70 after 3.5h",
            bus_path=bus,
        )
        emit_prediction_miss_impingement(
            prediction_name="P5_content_vocabulary_balance",
            expected="0.05–0.5 (active modulation)",
            observed=0.91,
            alert="extreme modulation",
            bus_path=bus,
        )
        lines = bus.read_text().strip().splitlines()
        narratives = [json.loads(line)["content"]["narrative"] for line in lines]
        assert narratives[0] != narratives[1]
        assert "0.420" in narratives[0]
        assert "0.910" in narratives[1]
