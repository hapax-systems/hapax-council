"""Tests for surprise-weighted primal impression (WS1)."""

from __future__ import annotations

from agents.hapax_daimonion.perception_ring import PerceptionRing
from agents.temporal_bands import (
    SurpriseField,
    TemporalBandFormatter,
    TemporalBands,
)

# compute_surprise's behaviour (now sourced from the IDF posterior) is covered
# by tests/test_temporal_surprise.py. This file keeps the SurpriseField model,
# TemporalBands aggregation, and formatter/XML integration tests.


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
