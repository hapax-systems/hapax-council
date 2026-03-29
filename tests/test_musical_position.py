"""Tests for MusicalPosition and related functions."""

from __future__ import annotations

import unittest

from agents.hapax_daimonion.musical_position import (
    MusicalPosition,
    create_musical_position_behavior,
    musical_position,
    update_musical_position,
)
from agents.hapax_daimonion.primitives import Behavior
from agents.hapax_daimonion.timeline import TimelineMapping, TransportState


class TestMusicalPosition(unittest.TestCase):
    def test_frozen(self):
        pos = musical_position(0.0)
        with self.assertRaises(AttributeError):
            pos.beat = 1.0  # type: ignore[misc]


class TestMusicalPositionArithmetic(unittest.TestCase):
    def test_beat_zero(self):
        pos = musical_position(0.0)
        self.assertAlmostEqual(pos.beat, 0.0)
        self.assertEqual(pos.bar, 0)
        self.assertAlmostEqual(pos.beat_in_bar, 0.0)
        self.assertEqual(pos.phrase, 0)
        self.assertEqual(pos.bar_in_phrase, 0)
        self.assertEqual(pos.section, 0)
        self.assertEqual(pos.phrase_in_section, 0)

    def test_beat_3_5(self):
        pos = musical_position(3.5)
        self.assertAlmostEqual(pos.beat, 3.5)
        self.assertEqual(pos.bar, 0)  # still in first bar
        self.assertAlmostEqual(pos.beat_in_bar, 3.5)

    def test_beat_16(self):
        """Beat 16 = bar 4, phrase 1, section 0."""
        pos = musical_position(16.0)
        self.assertEqual(pos.bar, 4)
        self.assertAlmostEqual(pos.beat_in_bar, 0.0)
        self.assertEqual(pos.phrase, 1)
        self.assertEqual(pos.bar_in_phrase, 0)
        self.assertEqual(pos.section, 0)

    def test_beat_64(self):
        """Beat 64 = bar 16, phrase 4, section 1."""
        pos = musical_position(64.0)
        self.assertEqual(pos.bar, 16)
        self.assertEqual(pos.phrase, 4)
        self.assertEqual(pos.section, 1)
        self.assertEqual(pos.phrase_in_section, 0)

    def test_custom_meter_3_4(self):
        """3/4 time: 3 beats per bar."""
        pos = musical_position(9.0, beats_per_bar=3)
        self.assertEqual(pos.bar, 3)
        self.assertAlmostEqual(pos.beat_in_bar, 0.0)

    def test_custom_bars_per_phrase(self):
        pos = musical_position(32.0, beats_per_bar=4, bars_per_phrase=8)
        self.assertEqual(pos.bar, 8)
        self.assertEqual(pos.phrase, 1)
        self.assertEqual(pos.bar_in_phrase, 0)

    def test_custom_phrases_per_section(self):
        pos = musical_position(64.0, beats_per_bar=4, bars_per_phrase=4, phrases_per_section=2)
        self.assertEqual(pos.phrase, 4)
        self.assertEqual(pos.section, 2)
        self.assertEqual(pos.phrase_in_section, 0)

    def test_fractional_beat(self):
        pos = musical_position(4.75)
        self.assertEqual(pos.bar, 1)
        self.assertAlmostEqual(pos.beat_in_bar, 0.75)

    def test_large_beat_number(self):
        pos = musical_position(256.0)
        self.assertEqual(pos.bar, 64)
        self.assertEqual(pos.phrase, 16)
        self.assertEqual(pos.section, 4)


class TestCreateMusicalPositionBehavior(unittest.TestCase):
    def test_sentinel_at_beat_zero(self):
        b = create_musical_position_behavior(watermark=0.0)
        self.assertIsInstance(b, Behavior)
        self.assertAlmostEqual(b.value.beat, 0.0)
        self.assertEqual(b.value.bar, 0)

    def test_sampleable_immediately(self):
        b = create_musical_position_behavior(watermark=0.0)
        stamped = b.sample()
        self.assertIsInstance(stamped.value, MusicalPosition)


class TestUpdateMusicalPosition(unittest.TestCase):
    def test_update_from_playing_timeline(self):
        b = create_musical_position_behavior(watermark=0.0)
        mapping = TimelineMapping(
            reference_time=0.0,
            reference_beat=0.0,
            tempo=120.0,
            transport=TransportState.PLAYING,
        )
        # At t=2.0 with 120 BPM: beat = 0 + 2.0 * (120/60) = 4.0
        pos = update_musical_position(b, mapping, now=2.0)
        self.assertAlmostEqual(pos.beat, 4.0)
        self.assertEqual(pos.bar, 1)

    def test_stopped_transport_no_update(self):
        b = create_musical_position_behavior(watermark=0.0)
        mapping = TimelineMapping(
            reference_time=0.0,
            reference_beat=0.0,
            tempo=120.0,
            transport=TransportState.STOPPED,
        )
        pos = update_musical_position(b, mapping, now=10.0)
        self.assertAlmostEqual(pos.beat, 0.0)  # sentinel unchanged

    def test_watermark_advances(self):
        b = create_musical_position_behavior(watermark=0.0)
        mapping = TimelineMapping(
            reference_time=0.0,
            reference_beat=0.0,
            tempo=120.0,
            transport=TransportState.PLAYING,
        )
        update_musical_position(b, mapping, now=1.0)
        wm1 = b.watermark
        update_musical_position(b, mapping, now=2.0)
        wm2 = b.watermark
        self.assertGreater(wm2, wm1)

    def test_custom_meter_in_update(self):
        b = create_musical_position_behavior(watermark=0.0)
        mapping = TimelineMapping(
            reference_time=0.0,
            reference_beat=0.0,
            tempo=120.0,
            transport=TransportState.PLAYING,
        )
        # 9 beats in 3/4 time = 3 bars
        pos = update_musical_position(b, mapping, now=4.5, beats_per_bar=3)
        self.assertAlmostEqual(pos.beat, 9.0)
        self.assertEqual(pos.bar, 3)


if __name__ == "__main__":
    unittest.main()
