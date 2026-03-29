"""Tests for the temporal band formatter (Phase 4)."""

from __future__ import annotations

from agents.hapax_daimonion.perception_ring import PerceptionRing
from agents.temporal_bands import (
    RetentionEntry,
    TemporalBandFormatter,
    TemporalBands,
)


def _make_ring(n: int = 15, base_ts: float = 1000.0, tick_s: float = 2.5) -> PerceptionRing:
    """Create a ring with n snapshots at regular intervals."""
    ring = PerceptionRing()
    for i in range(n):
        ring.push(
            {
                "ts": base_ts + i * tick_s,
                "flow_score": 0.1 + 0.05 * i,  # gradually rising
                "production_activity": "coding" if i > 5 else "idle",
                "audio_energy_rms": 0.02 + 0.005 * i,
                "music_genre": "lo-fi" if i > 3 else "",
                "heart_rate_bpm": 70 + i,
                "consent_phase": "no_guest",
            }
        )
    return ring


class TestEmptyRing:
    def test_empty_ring_returns_empty_bands(self):
        ring = PerceptionRing()
        fmt = TemporalBandFormatter()
        bands = fmt.format(ring)
        assert bands.retention == []
        assert bands.impression == {}
        assert bands.protention == []


class TestRetention:
    def test_retention_has_entries(self):
        ring = _make_ring(15)
        fmt = TemporalBandFormatter()
        bands = fmt.format(ring)
        assert len(bands.retention) > 0
        assert len(bands.retention) <= 3

    def test_retention_entries_have_age(self):
        ring = _make_ring(15)
        fmt = TemporalBandFormatter()
        bands = fmt.format(ring)
        for entry in bands.retention:
            assert entry.age_s > 0
            assert isinstance(entry, RetentionEntry)

    def test_retention_ordered_by_recency(self):
        ring = _make_ring(15)
        fmt = TemporalBandFormatter()
        bands = fmt.format(ring)
        if len(bands.retention) >= 2:
            ages = [r.age_s for r in bands.retention]
            # First entry should be most recent (smallest age)
            assert ages[0] <= ages[-1]


class TestImpression:
    def test_impression_has_current_data(self):
        ring = _make_ring(15)
        fmt = TemporalBandFormatter()
        bands = fmt.format(ring)
        assert "flow_state" in bands.impression
        assert "flow_score" in bands.impression
        assert "activity" in bands.impression

    def test_impression_flow_state_derived(self):
        ring = PerceptionRing()
        ring.push({"ts": 1.0, "flow_score": 0.8, "production_activity": "coding"})
        fmt = TemporalBandFormatter()
        bands = fmt.format(ring)
        assert bands.impression["flow_state"] == "active"


class TestProtention:
    def test_rising_flow_predicts_deep_work(self):
        ring = PerceptionRing()
        for i in range(10):
            ring.push(
                {
                    "ts": float(i) * 2.5,
                    "flow_score": 0.35 + 0.05 * i,  # 0.35 → 0.80
                    "production_activity": "coding",
                    "audio_energy_rms": 0.02,
                    "heart_rate_bpm": 70,
                }
            )
        fmt = TemporalBandFormatter()
        bands = fmt.format(ring)
        states = [p.predicted_state for p in bands.protention]
        assert "entering_deep_work" in states or "sustained_activity" in states

    def test_stable_activity_predicts_sustained(self):
        ring = PerceptionRing()
        for i in range(8):
            ring.push(
                {
                    "ts": float(i) * 2.5,
                    "flow_score": 0.5,
                    "production_activity": "coding",
                    "audio_energy_rms": 0.02,
                    "heart_rate_bpm": 70,
                }
            )
        fmt = TemporalBandFormatter()
        bands = fmt.format(ring)
        states = [p.predicted_state for p in bands.protention]
        assert "sustained_activity" in states

    def test_no_predictions_from_flat_idle(self):
        ring = PerceptionRing()
        for i in range(5):
            ring.push(
                {
                    "ts": float(i) * 2.5,
                    "flow_score": 0.1,
                    "production_activity": "idle",
                    "audio_energy_rms": 0.0,
                    "heart_rate_bpm": 65,
                }
            )
        fmt = TemporalBandFormatter()
        bands = fmt.format(ring)
        # Should have no dramatic predictions from flat idle state
        for p in bands.protention:
            assert p.predicted_state not in ("entering_deep_work", "flow_breaking", "stress_rising")


class TestXmlFormat:
    def test_xml_has_temporal_context_tags(self):
        ring = _make_ring(10)
        fmt = TemporalBandFormatter()
        bands = fmt.format(ring)
        xml = fmt.format_xml(bands)
        assert "<temporal_context>" in xml
        assert "</temporal_context>" in xml

    def test_xml_has_retention_section(self):
        ring = _make_ring(10)
        fmt = TemporalBandFormatter()
        bands = fmt.format(ring)
        xml = fmt.format_xml(bands)
        assert "<retention>" in xml
        assert "<memory" in xml

    def test_xml_has_impression_section(self):
        ring = _make_ring(10)
        fmt = TemporalBandFormatter()
        bands = fmt.format(ring)
        xml = fmt.format_xml(bands)
        assert "<impression>" in xml

    def test_empty_bands_minimal_xml(self):
        fmt = TemporalBandFormatter()
        bands = TemporalBands()
        xml = fmt.format_xml(bands)
        assert "<temporal_context>" in xml
        assert "</temporal_context>" in xml


class TestProtentionConfidence:
    def test_confidence_bounded(self):
        ring = _make_ring(15)
        fmt = TemporalBandFormatter()
        bands = fmt.format(ring)
        for p in bands.protention:
            assert 0.0 <= p.confidence <= 1.0

    def test_protention_has_basis(self):
        ring = _make_ring(15)
        fmt = TemporalBandFormatter()
        bands = fmt.format(ring)
        for p in bands.protention:
            assert len(p.basis) > 0
