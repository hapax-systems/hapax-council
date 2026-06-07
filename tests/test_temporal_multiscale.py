"""Tests for multi-scale temporal integration and surprise-weighted XML ordering."""

from __future__ import annotations

from agents.hapax_daimonion.perception_ring import PerceptionRing
from agents.temporal_bands import TemporalBandFormatter
from agents.temporal_models import (
    CircadianContext,
    SurpriseField,
    TemporalBands,
)
from agents.temporal_scales import (
    DaySummary,
    MinuteSummary,
    MultiScaleAggregator,
    MultiScaleContext,
    SessionSummary,
)
from agents.temporal_xml import format_temporal_xml


def _ring_with(*snapshots: dict) -> PerceptionRing:
    ring = PerceptionRing()
    for s in snapshots:
        ring.push(s)
    return ring


def _snap(ts: float = 100.0, flow: float = 0.5, activity: str = "coding") -> dict:
    return {
        "ts": ts,
        "flow_score": flow,
        "production_activity": activity,
        "audio_energy_rms": 0.01,
        "heart_rate_bpm": 72,
        "music_genre": "",
        "presence_probability": 0.9,
        "consent_phase": "no_guest",
    }


class TestMultiScaleIntegration:
    """Formatter accepts and renders multi-scale context."""

    def test_format_without_multiscale_unchanged(self):
        """Calling format(ring) without multi_scale still works."""
        ring = _ring_with(_snap(10), _snap(15), _snap(20))
        fmt = TemporalBandFormatter()
        bands = fmt.format(ring)
        assert bands.minute_summaries == []
        assert bands.current_session is None
        assert bands.day_context is None

    def test_format_with_multiscale_attaches_data(self):
        """Multi-scale context populates new TemporalBands fields."""
        ring = _ring_with(_snap(10), _snap(15), _snap(20))
        ctx = MultiScaleContext(
            recent_minutes=[
                MinuteSummary(timestamp=0, activity="coding", flow_state="active", flow_mean=0.7),
            ],
            current_session=SessionSummary(
                start_ts=0,
                end_ts=60,
                duration_s=60,
                activity="coding",
                flow_state="active",
            ),
            recent_sessions=[
                SessionSummary(
                    start_ts=0,
                    end_ts=300,
                    duration_s=300,
                    activity="email",
                    flow_state="warming",
                ),
            ],
            day=DaySummary(
                session_count=3,
                total_minutes=45,
                dominant_activity="coding",
                total_flow_minutes=30,
                activities={"coding": 30, "email": 15},
            ),
        )
        fmt = TemporalBandFormatter()
        bands = fmt.format(ring, multi_scale=ctx)

        assert len(bands.minute_summaries) == 1
        assert bands.current_session is not None
        assert bands.current_session["activity"] == "coding"
        assert len(bands.recent_sessions) == 1
        assert bands.day_context is not None
        assert bands.day_context.total_flow_minutes == 30

    def test_xml_contains_minute_scale(self):
        """format_xml includes minute retention when present."""
        bands = TemporalBands(
            minute_summaries=[{"activity": "coding", "flow_state": "active", "hr_mean": 72}],
        )
        xml = format_temporal_xml(bands)
        assert '<retention scale="minute">' in xml
        assert 'activity="coding"' in xml

    def test_xml_contains_session_context(self):
        """format_xml includes session context."""
        bands = TemporalBands(
            current_session={"activity": "coding", "flow_state": "active", "duration_s": 600},
        )
        xml = format_temporal_xml(bands)
        assert "<session_context>" in xml
        assert '<current activity="coding"' in xml
        assert 'duration_m="10"' in xml

    def test_xml_contains_circadian(self):
        """format_xml includes circadian context."""
        bands = TemporalBands(
            day_context=CircadianContext(
                session_count=5,
                total_minutes=120,
                total_flow_minutes=80,
                dominant_activity="coding",
                activities={"coding": 80, "email": 40},
            ),
        )
        xml = format_temporal_xml(bands)
        assert "<circadian" in xml
        assert 'dominant="coding"' in xml
        assert 'flow_m="80"' in xml

    def test_xml_empty_multiscale_no_crash(self):
        """Empty multi-scale fields don't produce empty sections."""
        bands = TemporalBands()
        xml = format_temporal_xml(bands)
        assert '<retention scale="minute">' not in xml
        assert "<session_context>" not in xml
        assert "<circadian" not in xml

    def test_xml_tick_retention_has_scale_attr(self):
        """Tick-level retention now has scale='tick' attribute."""
        from agents.temporal_models import RetentionEntry

        bands = TemporalBands(
            retention=[RetentionEntry(timestamp=10, age_s=5, summary="coding")],
        )
        xml = format_temporal_xml(bands)
        assert '<retention scale="tick">' in xml


class TestSurpriseReordering:
    """Impression fields ordered by surprise for RoPE geometry."""

    def test_high_surprise_field_appears_last(self):
        """Fields with higher surprise appear later in XML."""
        bands = TemporalBands(
            impression={
                "flow_state": "idle",
                "activity": "browsing",
                "heart_rate": 72,
            },
            surprises=[
                SurpriseField(
                    field="flow_state",
                    observed="idle",
                    expected="active",
                    surprise=0.8,
                ),
            ],
        )
        xml = format_temporal_xml(bands)
        # flow_state has surprise=0.8, should appear after activity and heart_rate
        flow_pos = xml.index("<flow_state")
        activity_pos = xml.index("<activity>")
        hr_pos = xml.index("<heart_rate>")
        assert flow_pos > activity_pos
        assert flow_pos > hr_pos

    def test_no_surprise_preserves_order(self):
        """Without surprises, impression order is stable."""
        bands = TemporalBands(
            impression={"a": 1, "b": 2, "c": 3},
        )
        xml = format_temporal_xml(bands)
        assert xml.index("<a>") < xml.index("<b>") < xml.index("<c>")

    def test_multiple_surprised_fields_ordered(self):
        """Multiple surprised fields: higher surprise appears later."""
        bands = TemporalBands(
            impression={"alpha": "x", "beta": "y", "gamma": "z"},
            surprises=[
                SurpriseField(field="alpha", observed="x", expected="a", surprise=0.9),
                SurpriseField(field="beta", observed="y", expected="b", surprise=0.4),
            ],
        )
        xml = format_temporal_xml(bands)
        gamma_pos = xml.index("<gamma>")  # no surprise = 0.0
        beta_pos = xml.index("<beta")  # surprise 0.4
        alpha_pos = xml.index("<alpha")  # surprise 0.9
        assert gamma_pos < beta_pos < alpha_pos


class TestMultiScaleAggregatorIntegration:
    """End-to-end: aggregator → formatter → XML."""

    def test_aggregator_context_flows_to_xml(self):
        """Feed aggregator with ticks, pass context to formatter, get XML."""
        agg = MultiScaleAggregator()
        # Feed 2 minutes of data (48 ticks × 2.5s = 120s)
        for i in range(48):
            agg.tick(
                {
                    "ts": 1000 + i * 2.5,
                    "timestamp": 1000 + i * 2.5,
                    "production_activity": "coding",
                    "flow_score": 0.7,
                    "audio_energy_rms": 0.01,
                    "heart_rate_bpm": 72,
                    "consent_phase": "no_guest",
                }
            )

        ctx = agg.context()
        ring = _ring_with(*[_snap(1000 + i * 2.5) for i in range(44, 48)])
        fmt = TemporalBandFormatter()
        bands = fmt.format(ring, multi_scale=ctx)
        xml = fmt.format_xml(bands)

        # Should have tick retention + at least minute data
        assert '<retention scale="tick">' in xml
        assert '<impression scale="tick">' in xml
