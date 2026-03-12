"""Tests for TimelineMapping — bijective affine map between wall-clock and beat time."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from agents.hapax_voice.primitives import Behavior
from agents.hapax_voice.timeline import TimelineMapping, TransportState


class TestTimelineMapping:
    def test_beat_at_time_playing_120bpm(self):
        """At 120 BPM, 1 second = 2 beats."""
        m = TimelineMapping(
            reference_time=100.0,
            reference_beat=0.0,
            tempo=120.0,
            transport=TransportState.PLAYING,
        )
        assert m.beat_at_time(101.0) == pytest.approx(2.0)

    def test_time_at_beat_playing_120bpm(self):
        """At 120 BPM, 2 beats = 1 second."""
        m = TimelineMapping(
            reference_time=100.0,
            reference_beat=0.0,
            tempo=120.0,
            transport=TransportState.PLAYING,
        )
        assert m.time_at_beat(2.0) == pytest.approx(101.0)

    def test_bijection_round_trip_time_to_beat(self):
        """time_at_beat(beat_at_time(t)) ≈ t when playing."""
        m = TimelineMapping(
            reference_time=50.0,
            reference_beat=8.0,
            tempo=140.0,
            transport=TransportState.PLAYING,
        )
        t = 73.456
        assert m.time_at_beat(m.beat_at_time(t)) == pytest.approx(t, abs=1e-9)

    def test_bijection_round_trip_beat_to_time(self):
        """beat_at_time(time_at_beat(b)) ≈ b when playing."""
        m = TimelineMapping(
            reference_time=50.0,
            reference_beat=8.0,
            tempo=140.0,
            transport=TransportState.PLAYING,
        )
        b = 32.789
        assert m.beat_at_time(m.time_at_beat(b)) == pytest.approx(b, abs=1e-9)

    def test_stopped_freezes_beat(self):
        """When stopped, any time → reference_beat."""
        m = TimelineMapping(
            reference_time=100.0,
            reference_beat=16.0,
            tempo=120.0,
            transport=TransportState.STOPPED,
        )
        assert m.beat_at_time(0.0) == 16.0
        assert m.beat_at_time(100.0) == 16.0
        assert m.beat_at_time(999.0) == 16.0

    def test_stopped_freezes_time(self):
        """When stopped, any beat → reference_time."""
        m = TimelineMapping(
            reference_time=100.0,
            reference_beat=16.0,
            tempo=120.0,
            transport=TransportState.STOPPED,
        )
        assert m.time_at_beat(0.0) == 100.0
        assert m.time_at_beat(16.0) == 100.0
        assert m.time_at_beat(999.0) == 100.0

    def test_tempo_change_continuity(self):
        """New mapping anchored at transition point is continuous."""
        m1 = TimelineMapping(
            reference_time=100.0,
            reference_beat=0.0,
            tempo=120.0,
            transport=TransportState.PLAYING,
        )
        transition_time = 105.0
        transition_beat = m1.beat_at_time(transition_time)

        m2 = TimelineMapping(
            reference_time=transition_time,
            reference_beat=transition_beat,
            tempo=140.0,
            transport=TransportState.PLAYING,
        )
        # At the transition point, both mappings agree
        assert m2.beat_at_time(transition_time) == pytest.approx(transition_beat)
        # After transition, m2 runs at the new tempo
        assert m2.beat_at_time(transition_time + 1.0) == pytest.approx(
            transition_beat + 140.0 / 60.0
        )

    def test_transport_start_anchors_correctly(self):
        """STOPPED→PLAYING preserves beat position."""
        stopped = TimelineMapping(
            reference_time=100.0,
            reference_beat=8.0,
            tempo=120.0,
            transport=TransportState.STOPPED,
        )
        # "Press play" at t=110 — anchor at current frozen beat
        playing = TimelineMapping(
            reference_time=110.0,
            reference_beat=stopped.beat_at_time(110.0),
            tempo=120.0,
            transport=TransportState.PLAYING,
        )
        assert playing.beat_at_time(110.0) == pytest.approx(8.0)
        assert playing.beat_at_time(111.0) == pytest.approx(10.0)

    def test_negative_tempo_raises(self):
        with pytest.raises(ValueError, match="positive"):
            TimelineMapping(reference_time=0.0, reference_beat=0.0, tempo=-120.0)

    def test_zero_tempo_raises(self):
        with pytest.raises(ValueError, match="positive"):
            TimelineMapping(reference_time=0.0, reference_beat=0.0, tempo=0.0)

    def test_frozen_immutable(self):
        m = TimelineMapping(reference_time=0.0, reference_beat=0.0, tempo=120.0)
        with pytest.raises(AttributeError):
            m.tempo = 140.0  # type: ignore[misc]

    def test_high_tempo_precision(self):
        """At 200 BPM over 60s, sub-ms precision is maintained."""
        m = TimelineMapping(
            reference_time=0.0,
            reference_beat=0.0,
            tempo=200.0,
            transport=TransportState.PLAYING,
        )
        t = 60.0
        beat = m.beat_at_time(t)
        assert beat == pytest.approx(200.0, abs=1e-6)
        assert m.time_at_beat(beat) == pytest.approx(t, abs=1e-6)


class TestTimelineMappingAsBehavior:
    def test_behavior_holds_mapping(self):
        """Behavior[TimelineMapping].sample() returns Stamped[TimelineMapping]."""
        m = TimelineMapping(
            reference_time=0.0,
            reference_beat=0.0,
            tempo=120.0,
            transport=TransportState.PLAYING,
        )
        b: Behavior[TimelineMapping] = Behavior(m, watermark=1000.0)
        stamped = b.sample()
        assert stamped.value is m
        assert stamped.watermark == 1000.0
        assert stamped.value.beat_at_time(1.0) == pytest.approx(2.0)

    def test_behavior_update_replaces_mapping(self):
        """Behavior.update() with new tempo replaces the mapping."""
        m1 = TimelineMapping(
            reference_time=0.0, reference_beat=0.0, tempo=120.0, transport=TransportState.PLAYING
        )
        b: Behavior[TimelineMapping] = Behavior(m1, watermark=1000.0)

        m2 = TimelineMapping(
            reference_time=5.0, reference_beat=10.0, tempo=140.0, transport=TransportState.PLAYING
        )
        b.update(m2, 1005.0)

        assert b.value is m2
        assert b.watermark == 1005.0
