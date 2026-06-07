"""Tests for IDF-posterior-sourced temporal surprise.

These pin the de-forked surprise SSOT (REQ-20260605-temporal-surprise-idf-posterior):
`compute_surprise` reads the single surprise currency — the
`InformationDensityField` `BayesianSurpriseModel` posterior — for the source a
protention prediction concerns, instead of the deleted hardcoded rule table.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import agents.temporal_surprise as ts
from agents.temporal_models import ProtentionEntry
from agents.temporal_surprise import compute_surprise


def _density(**source_surprise: float) -> dict[str, object]:
    """Build a density-field state dict with the given per-source surprise."""
    return {"sources": {sid: {"surprise": v} for sid, v in source_surprise.items()}}


def _snap(
    flow_score: float = 0.0,
    activity: str = "",
    hr: int = 70,
    pp: float = 1.0,
) -> dict[str, object]:
    return {
        "flow_score": flow_score,
        "production_activity": activity,
        "heart_rate_bpm": hr,
        "presence_probability": pp,
    }


class TestComputeSurpriseFromIDF:
    def test_no_prior_protention_no_surprise(self):
        assert compute_surprise(_snap(), [], density_state=_density()) == []

    def test_heart_rate_reads_biometric_source(self):
        ds = _density(**{"biometric.heart_rate": 0.42})
        out = compute_surprise(
            _snap(hr=95),
            [ProtentionEntry(predicted_state="stress_rising", confidence=0.5, basis="HR")],
            density_state=ds,
        )
        hr = [s for s in out if s.field == "heart_rate"]
        assert len(hr) == 1
        # surprise is the IDF posterior, NOT the prediction confidence (0.5)
        assert hr[0].surprise == 0.42
        assert hr[0].note == "biometric.heart_rate"
        assert hr[0].expected == "stress_rising"

    def test_presence_reads_perception_source(self):
        ds = _density(**{"perception.presence": 0.0})
        out = compute_surprise(
            _snap(pp=0.1),
            [ProtentionEntry(predicted_state="operator_departing", confidence=0.9, basis="x")],
            density_state=ds,
        )
        pres = [s for s in out if s.field == "presence"]
        assert len(pres) == 1
        # reads the source posterior (0.0), ignores the high confidence (0.9)
        assert pres[0].surprise == 0.0

    def test_flow_routes_to_desk_activity_posterior(self):
        ds = _density(**{"desk.activity": 0.81})
        out = compute_surprise(
            _snap(flow_score=0.1),
            [ProtentionEntry(predicted_state="entering_deep_work", confidence=0.7, basis="x")],
            density_state=ds,
        )
        flow = [s for s in out if s.field == "flow_state"]
        assert len(flow) == 1
        assert flow[0].surprise == 0.81
        assert flow[0].expected == "entering_deep_work"

    def test_value_matches_density_field_exactly(self):
        # AC3: temporal surprise == density-field source surprise, by construction.
        ds = _density(**{"biometric.heart_rate": 0.337})
        out = compute_surprise(
            _snap(hr=88),
            [ProtentionEntry(predicted_state="stress_rising", confidence=0.5, basis="x")],
            density_state=ds,
        )
        assert out[0].surprise == ds["sources"]["biometric.heart_rate"]["surprise"]

    def test_missing_source_is_skipped_no_rule_fallback(self):
        # No relevant source in the field -> no surprise emitted (no hidden rules).
        out = compute_surprise(
            _snap(hr=95),
            [ProtentionEntry(predicted_state="stress_rising", confidence=0.5, basis="x")],
            density_state=_density(),
        )
        assert out == []

    def test_none_density_degrades_gracefully(self):
        # Default path reads SHM; if absent, returns [] (no crash, no rule fallback).
        with mock.patch.object(ts.InformationDensityField, "read_shm", return_value=None):
            out = compute_surprise(
                _snap(hr=95),
                [ProtentionEntry(predicted_state="stress_rising", confidence=0.5, basis="x")],
                density_state=None,
            )
        assert out == []

    def test_default_density_reads_shm(self):
        # When density_state is None, the SHM posterior is the source of truth.
        ds = _density(**{"biometric.heart_rate": 0.55})
        with mock.patch.object(ts.InformationDensityField, "read_shm", return_value=ds):
            out = compute_surprise(
                _snap(hr=95),
                [ProtentionEntry(predicted_state="stress_rising", confidence=0.1, basis="x")],
                density_state=None,
            )
        assert out[0].surprise == 0.55

    def test_dedup_keeps_highest_per_field(self):
        # Two predictions for the same field collapse to one entry.
        ds = _density(**{"desk.activity": 0.5})
        out = compute_surprise(
            _snap(flow_score=0.1),
            [
                ProtentionEntry(predicted_state="entering_deep_work", confidence=0.4, basis="a"),
                ProtentionEntry(predicted_state="flow_continuing", confidence=0.7, basis="b"),
            ],
            density_state=ds,
        )
        flow = [s for s in out if s.field == "flow_state"]
        assert len(flow) == 1
        assert flow[0].surprise == 0.5

    def test_surprise_clamped_to_unit_interval(self):
        # Defensive: a malformed >1 source value is clamped (SurpriseField is le=1.0).
        ds = _density(**{"biometric.heart_rate": 1.7})
        out = compute_surprise(
            _snap(hr=95),
            [ProtentionEntry(predicted_state="stress_rising", confidence=0.5, basis="x")],
            density_state=ds,
        )
        assert out[0].surprise == 1.0

    def test_no_rule_table_artifacts_in_source(self):
        # AC1 structural guard: the expert-system rule table is gone — surprise is
        # never derived from prediction confidence or hardcoded expected outcomes.
        src = Path(ts.__file__).read_text(encoding="utf-8")
        assert "_match_prediction" not in src
        assert "pred.confidence" not in src
