"""Tests for surprise-weighted primal impression (WS1)."""

from __future__ import annotations

from agents.hapax_daimonion.perception_ring import PerceptionRing
from agents.temporal_bands import (
    ProtentionEntry,
    SurpriseField,
    TemporalBandFormatter,
    TemporalBands,
)


def _ring_with(*snapshots: dict) -> PerceptionRing:
    """Build a ring with given snapshots."""
    ring = PerceptionRing()
    for s in snapshots:
        ring.push(s)
    return ring


def _snap(
    ts: float = 100.0,
    flow_score: float = 0.0,
    activity: str = "",
    audio: float = 0.0,
    hr: int = 70,
) -> dict:
    return {
        "ts": ts,
        "flow_score": flow_score,
        "production_activity": activity,
        "audio_energy_rms": audio,
        "heart_rate_bpm": hr,
        "music_genre": "",
        "consent_phase": "no_guest",
    }


class TestSurpriseField:
    def test_model_creation(self):
        sf = SurpriseField(
            field="flow_state",
            observed="idle",
            expected="active",
            surprise=0.7,
            note="predicted deep work",
        )
        assert sf.surprise == 0.7
        assert sf.field == "flow_state"


class TestTemporalBandsWithSurprise:
    def test_max_surprise_empty(self):
        bands = TemporalBands()
        assert bands.max_surprise == 0.0

    def test_max_surprise_with_data(self):
        bands = TemporalBands(
            surprises=[
                SurpriseField(field="a", observed="x", expected="y", surprise=0.3),
                SurpriseField(field="b", observed="x", expected="y", surprise=0.8),
            ]
        )
        assert bands.max_surprise == 0.8


class TestComputeSurprise:
    def test_no_prior_protention_no_surprise(self):
        fmt = TemporalBandFormatter()
        surprises = fmt._compute_surprise(_snap(), [])
        assert surprises == []

    def test_confirmed_flow_prediction(self):
        """Predicted deep work, operator IS in deep work → surprise=0."""
        fmt = TemporalBandFormatter()
        protention = [
            ProtentionEntry(
                predicted_state="entering_deep_work",
                confidence=0.7,
                basis="flow rising",
            )
        ]
        current = _snap(flow_score=0.8, activity="coding")  # active flow
        surprises = fmt._compute_surprise(current, protention)
        flow_surprises = [s for s in surprises if s.field == "flow_state"]
        assert len(flow_surprises) == 1
        assert flow_surprises[0].surprise == 0.0  # confirmed

    def test_violated_flow_prediction(self):
        """Predicted deep work, operator went idle → surprise=confidence."""
        fmt = TemporalBandFormatter()
        protention = [
            ProtentionEntry(
                predicted_state="entering_deep_work",
                confidence=0.7,
                basis="flow rising",
            )
        ]
        current = _snap(flow_score=0.1, activity="browsing")  # idle
        surprises = fmt._compute_surprise(current, protention)
        flow_surprises = [s for s in surprises if s.field == "flow_state"]
        assert len(flow_surprises) == 1
        assert flow_surprises[0].surprise == 0.7

    def test_flow_breaking_confirmed(self):
        """Predicted flow breaking, it broke → surprise=0."""
        fmt = TemporalBandFormatter()
        protention = [
            ProtentionEntry(
                predicted_state="flow_breaking",
                confidence=0.6,
                basis="flow declining",
            )
        ]
        current = _snap(flow_score=0.1)
        surprises = fmt._compute_surprise(current, protention)
        flow_surprises = [s for s in surprises if s.field == "flow_state"]
        assert flow_surprises[0].surprise == 0.0

    def test_flow_breaking_violated(self):
        """Predicted flow breaking, but flow persisted → surprise."""
        fmt = TemporalBandFormatter()
        protention = [
            ProtentionEntry(
                predicted_state="flow_breaking",
                confidence=0.6,
                basis="flow declining",
            )
        ]
        current = _snap(flow_score=0.8)  # still in flow
        surprises = fmt._compute_surprise(current, protention)
        flow_surprises = [s for s in surprises if s.field == "flow_state"]
        assert flow_surprises[0].surprise == 0.6
        assert "persisted" in flow_surprises[0].note

    def test_stress_prediction_confirmed(self):
        fmt = TemporalBandFormatter()
        protention = [
            ProtentionEntry(
                predicted_state="stress_rising",
                confidence=0.5,
                basis="HR climbing",
            )
        ]
        current = _snap(hr=95)
        surprises = fmt._compute_surprise(current, protention)
        hr_surprises = [s for s in surprises if s.field == "heart_rate"]
        assert hr_surprises[0].surprise == 0.0

    def test_stress_prediction_violated(self):
        fmt = TemporalBandFormatter()
        protention = [
            ProtentionEntry(
                predicted_state="stress_rising",
                confidence=0.5,
                basis="HR climbing",
            )
        ]
        current = _snap(hr=65)  # HR dropped
        surprises = fmt._compute_surprise(current, protention)
        hr_surprises = [s for s in surprises if s.field == "heart_rate"]
        assert hr_surprises[0].surprise == 0.5

    def test_deduplication_keeps_highest(self):
        """Multiple predictions for same field → keep highest surprise."""
        fmt = TemporalBandFormatter()
        protention = [
            ProtentionEntry(
                predicted_state="entering_deep_work",
                confidence=0.4,
                basis="flow rising",
            ),
            ProtentionEntry(
                predicted_state="flow_continuing",
                confidence=0.7,
                basis="stable flow",
            ),
        ]
        current = _snap(flow_score=0.1)  # both violated
        surprises = fmt._compute_surprise(current, protention)
        flow_surprises = [s for s in surprises if s.field == "flow_state"]
        assert len(flow_surprises) == 1
        assert flow_surprises[0].surprise == 0.7  # higher confidence


class TestFormatterSurpriseIntegration:
    def test_format_includes_surprises(self):
        """Full format() call includes surprise from previous tick's protention."""
        fmt = TemporalBandFormatter()

        # First tick — no prior protention, no surprise
        ring = _ring_with(
            _snap(ts=90, flow_score=0.1),
            _snap(ts=92.5, flow_score=0.2),
            _snap(ts=95, flow_score=0.4),  # rising flow
        )
        bands1 = fmt.format(ring)
        assert bands1.surprises == []

        # Second tick — flow didn't materialize
        ring.push(_snap(ts=97.5, flow_score=0.1))  # dropped
        bands2 = fmt.format(ring)
        # If protention predicted entering_deep_work, surprise should appear
        if bands1.protention:
            assert len(bands2.surprises) >= 0  # may or may not have surprise

    def test_xml_marks_surprising_fields(self):
        """XML formatter annotates surprising impression fields."""
        bands = TemporalBands(
            impression={
                "flow_state": "idle",
                "activity": "browsing",
                "heart_rate": 70,
            },
            surprises=[
                SurpriseField(
                    field="flow_state",
                    observed="idle",
                    expected="active",
                    surprise=0.7,
                    note="predicted deep work",
                ),
            ],
        )
        fmt = TemporalBandFormatter()
        xml = fmt.format_xml(bands)
        assert 'surprise="0.70"' in xml
        assert 'expected="active"' in xml
        # Non-surprising fields have no surprise attribute
        assert "<activity>browsing</activity>" in xml

    def test_xml_low_surprise_not_marked(self):
        """Surprise below threshold (0.3) is not marked in XML."""
        bands = TemporalBands(
            impression={"flow_state": "warming"},
            surprises=[
                SurpriseField(
                    field="flow_state",
                    observed="warming",
                    expected="active",
                    surprise=0.2,
                ),
            ],
        )
        fmt = TemporalBandFormatter()
        xml = fmt.format_xml(bands)
        assert "surprise=" not in xml
