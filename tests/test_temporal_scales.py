"""Tests for multi-scale temporal hierarchy (WS1)."""

from __future__ import annotations

from agents.temporal_scales import (
    MinuteBuffer,
    MinuteSummary,
    MultiScaleAggregator,
    SessionBuffer,
    SessionSummary,
    compute_day_summary,
)


def _snap(
    ts: float = 100.0,
    activity: str = "coding",
    flow_score: float = 0.5,
    audio: float = 0.01,
    hr: int = 70,
) -> dict:
    return {
        "timestamp": ts,
        "ts": ts,
        "production_activity": activity,
        "flow_score": flow_score,
        "audio_energy_rms": audio,
        "heart_rate_bpm": hr,
        "voice_session": {"active": False},
    }


# ── MinuteBuffer Tests ───────────────────────────────────────────────────────


class TestMinuteBuffer:
    def test_first_tick_no_summary(self):
        buf = MinuteBuffer()
        assert buf.tick(_snap(ts=100)) is None

    def test_within_minute_accumulates(self):
        buf = MinuteBuffer()
        buf.tick(_snap(ts=100))
        buf.tick(_snap(ts=130))
        assert buf.tick(_snap(ts=155)) is None  # still < 60s
        assert len(buf) == 0

    def test_minute_boundary_produces_summary(self):
        buf = MinuteBuffer()
        buf.tick(_snap(ts=100, activity="coding", flow_score=0.7))
        buf.tick(_snap(ts=130, activity="coding", flow_score=0.8))
        result = buf.tick(_snap(ts=165, activity="coding"))  # 65s elapsed
        assert result is not None
        assert result.activity == "coding"
        assert result.flow_state == "active"  # mean of 0.7, 0.8 = 0.75
        assert result.snapshot_count == 2

    def test_multiple_minutes(self):
        buf = MinuteBuffer()
        for i in range(50):  # 50 ticks at 2.5s = 125s = ~2 minutes
            buf.tick(_snap(ts=100 + i * 2.5, activity="coding"))
        assert len(buf) >= 1

    def test_flush(self):
        buf = MinuteBuffer()
        buf.tick(_snap(ts=100))
        buf.tick(_snap(ts=130))
        result = buf.flush()
        assert result is not None

    def test_maxlen(self):
        buf = MinuteBuffer(maxlen=3)
        for i in range(5):
            buf.tick(_snap(ts=100 + i * 65))
        assert len(buf) <= 3

    def test_voice_active_detection(self):
        buf = MinuteBuffer()
        snap = _snap(ts=100)
        snap["voice_session"] = {"active": True}
        buf.tick(snap)
        buf.tick(_snap(ts=130))
        result = buf.tick(_snap(ts=165))
        assert result is not None
        assert result.voice_active is True


# ── SessionBuffer Tests ──────────────────────────────────────────────────────


class TestSessionBuffer:
    def test_first_minute_no_session(self):
        buf = SessionBuffer()
        m = MinuteSummary(timestamp=100, activity="coding")
        assert buf.observe(m) is None

    def test_same_activity_accumulates(self):
        buf = SessionBuffer()
        buf.observe(MinuteSummary(timestamp=100, activity="coding"))
        assert buf.observe(MinuteSummary(timestamp=160, activity="coding")) is None

    def test_activity_change_closes_session(self):
        buf = SessionBuffer()
        buf.observe(MinuteSummary(timestamp=100, activity="coding", flow_mean=0.7))
        buf.observe(MinuteSummary(timestamp=160, activity="coding", flow_mean=0.8))
        result = buf.observe(MinuteSummary(timestamp=220, activity="browsing"))
        assert result is not None
        assert result.activity == "coding"
        assert result.minute_count == 2
        assert result.duration_s > 0

    def test_session_flow_peak(self):
        buf = SessionBuffer()
        buf.observe(MinuteSummary(timestamp=100, activity="coding", flow_mean=0.3))
        buf.observe(MinuteSummary(timestamp=160, activity="coding", flow_mean=0.9))
        result = buf.observe(MinuteSummary(timestamp=220, activity="browsing"))
        assert result is not None
        assert result.flow_peak == 0.9

    def test_flush(self):
        buf = SessionBuffer()
        buf.observe(MinuteSummary(timestamp=100, activity="coding"))
        result = buf.flush()
        assert result is not None


# ── DaySummary Tests ─────────────────────────────────────────────────────────


class TestDaySummary:
    def test_empty(self):
        day = compute_day_summary([], [])
        assert day.session_count == 0
        assert day.total_minutes == 0

    def test_with_data(self):
        minutes = [
            MinuteSummary(timestamp=100, activity="coding", flow_state="active"),
            MinuteSummary(timestamp=160, activity="coding", flow_state="active"),
            MinuteSummary(timestamp=220, activity="browsing", flow_state="idle"),
        ]
        sessions = [
            SessionSummary(
                start_ts=100,
                end_ts=220,
                duration_s=120,
                activity="coding",
                minute_count=2,
            ),
        ]
        day = compute_day_summary(sessions, minutes)
        assert day.session_count == 1
        assert day.total_minutes == 3
        assert day.dominant_activity == "coding"
        assert day.total_flow_minutes == 2
        assert day.activities["coding"] == 2
        assert day.activities["browsing"] == 1


# ── MultiScaleAggregator Tests ───────────────────────────────────────────────


class TestMultiScaleAggregator:
    def test_tick_accumulates(self):
        agg = MultiScaleAggregator()
        agg.tick(_snap(ts=100))
        agg.tick(_snap(ts=130))
        ctx = agg.context()
        assert ctx.day.total_minutes == 0  # no minutes closed yet

    def test_minute_closes_after_60s(self):
        agg = MultiScaleAggregator()
        for i in range(30):
            agg.tick(_snap(ts=100 + i * 2.5, activity="coding"))
        ctx = agg.context()
        assert len(ctx.recent_minutes) >= 1

    def test_context_has_current_session(self):
        agg = MultiScaleAggregator()
        # Feed enough ticks to close 2 minutes of coding
        for i in range(60):
            agg.tick(_snap(ts=100 + i * 2.5, activity="coding", flow_score=0.7))
        ctx = agg.context()
        assert ctx.current_session is not None
        assert ctx.current_session.activity == "coding"

    def test_format_xml(self):
        agg = MultiScaleAggregator()
        for i in range(60):
            agg.tick(_snap(ts=100 + i * 2.5, activity="coding"))
        ctx = agg.context()
        xml = agg.format_xml(ctx)
        assert "<temporal_scales>" in xml
        assert "</temporal_scales>" in xml
        assert "coding" in xml

    def test_format_xml_empty(self):
        agg = MultiScaleAggregator()
        ctx = agg.context()
        xml = agg.format_xml(ctx)
        assert "<temporal_scales>" in xml
