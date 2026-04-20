"""Tests for shared.mix_quality.aggregate — skeleton aggregate formula."""

from __future__ import annotations

import pytest

from shared.mix_quality import MixQuality, SubScore, aggregate_mix_quality
from shared.mix_quality.aggregate import (
    AGGREGATE_INTERVENTION_THRESHOLD,
    AGGREGATE_WARNING_THRESHOLD,
    _dynamic_range_to_band,
    _loudness_to_band,
    empty_mix_quality,
)


class TestSubScoreShape:
    def test_defaults(self) -> None:
        s = SubScore(name="loudness")
        assert s.value is None
        assert s.normalised is None

    def test_fully_populated(self) -> None:
        s = SubScore(
            name="speech_clarity",
            value=0.85,
            normalised=0.85,
            unit="0..1",
            pass_band="≥0.8",
        )
        assert s.value == 0.85


class TestLoudnessToBand:
    @pytest.mark.parametrize(
        ("lufs", "expected"),
        [
            (-15.0, 1.0),  # dead-centre target
            (-14.0, 1.0),  # at upper tolerance
            (-16.0, 1.0),  # at lower tolerance
            (-8.0, 0.0),  # 7 dB above target → past 6 dB falloff → floored
            (-22.0, 0.0),  # 7 dB below target → past 6 dB falloff → floored
        ],
    )
    def test_band_edges(self, lufs: float, expected: float) -> None:
        assert _loudness_to_band(lufs) == pytest.approx(expected)

    def test_none_passes_through(self) -> None:
        assert _loudness_to_band(None) is None

    def test_falloff_linear(self) -> None:
        # 3 dB past tolerance → 0.5 (halfway through 6 dB falloff).
        assert _loudness_to_band(-15.0 + 1.0 + 3.0) == pytest.approx(0.5)


class TestDynamicRangeToBand:
    @pytest.mark.parametrize(
        ("db", "expected"),
        [
            (7.0, 1.0),  # at lower edge
            (14.0, 1.0),  # at upper edge
            (10.0, 1.0),  # mid-window
            (1.0, 0.0),  # 6 dB below lower edge → floored
            (20.0, 0.0),  # 6 dB above upper edge → floored
        ],
    )
    def test_band_edges(self, db: float, expected: float) -> None:
        assert _dynamic_range_to_band(db) == pytest.approx(expected)

    def test_none_passes_through(self) -> None:
        assert _dynamic_range_to_band(None) is None


class TestAggregate:
    def test_empty_aggregate_is_none(self) -> None:
        m = aggregate_mix_quality([])
        assert m.aggregate is None

    def test_all_none_sub_scores(self) -> None:
        scores = [SubScore(name=n) for n in ("loudness", "av_coherence")]
        m = aggregate_mix_quality(scores)
        assert m.aggregate is None

    def test_min_formula(self) -> None:
        """min() is intentional: one bad score sinks the aggregate."""
        scores = [
            SubScore(name="source_balance", value=0.9),
            SubScore(name="speech_clarity", value=0.5),  # worst
            SubScore(name="av_coherence", value=0.95),
        ]
        m = aggregate_mix_quality(scores)
        assert m.aggregate == pytest.approx(0.5)

    def test_partial_meters_still_aggregate(self) -> None:
        """A mid-rollout pipeline with some None meters still produces a gauge."""
        scores = [
            SubScore(name="loudness", value=-15.0),  # 1.0 after band
            SubScore(name="source_balance"),  # None — skipped
            SubScore(name="speech_clarity", value=0.7),
        ]
        m = aggregate_mix_quality(scores)
        assert m.aggregate == pytest.approx(0.7)

    def test_clamp_out_of_range(self) -> None:
        """0..1 meters that overshoot get clamped, not propagated as-is."""
        scores = [
            SubScore(name="source_balance", value=1.5),  # invalid; clamped to 1.0
            SubScore(name="av_coherence", value=-0.1),  # invalid; clamped to 0.0
        ]
        m = aggregate_mix_quality(scores)
        assert m.aggregate == pytest.approx(0.0)

    def test_native_unit_translation(self) -> None:
        """LUFS and dB get translated to 0..1 before aggregation."""
        scores = [
            SubScore(name="loudness", value=-15.0),  # in-band → 1.0
            SubScore(name="dynamic_range", value=10.0),  # in-band → 1.0
            SubScore(name="speech_clarity", value=0.85),
        ]
        m = aggregate_mix_quality(scores)
        assert m.aggregate == pytest.approx(0.85)

    def test_explicit_normalised_wins(self) -> None:
        """When a meter supplies normalised, aggregate uses that directly."""
        s = SubScore(name="loudness", value=-30.0, normalised=0.8)  # weird combo
        m = aggregate_mix_quality([s])
        # normalised wins — not the -30 LUFS (which would be 0.0).
        assert m.aggregate == pytest.approx(0.8)


class TestMixQualityHelpers:
    def test_sub_lookup_by_name(self) -> None:
        m = MixQuality(
            aggregate=0.7,
            sub_scores=[
                SubScore(name="loudness", value=-15.0),
                SubScore(name="speech_clarity", value=0.8),
            ],
        )
        assert m.sub("loudness").value == -15.0
        assert m.sub("missing") is None

    def test_empty_mix_quality(self) -> None:
        m = empty_mix_quality()
        assert m.aggregate is None
        assert len(m.sub_scores) == 6
        names = {s.name for s in m.sub_scores}
        assert names == {
            "loudness",
            "source_balance",
            "speech_clarity",
            "intentionality",
            "dynamic_range",
            "av_coherence",
        }


class TestThresholds:
    def test_warning_ordering(self) -> None:
        assert AGGREGATE_INTERVENTION_THRESHOLD < AGGREGATE_WARNING_THRESHOLD < 1.0

    def test_pass_bands_match_design_doc(self) -> None:
        """Sanity check: pass_band strings in empty skeleton match §2 table."""
        m = empty_mix_quality()
        by_name = {s.name: s for s in m.sub_scores}
        assert by_name["loudness"].pass_band == "-16 to -14"
        assert by_name["source_balance"].pass_band == "≥0.7"
        assert by_name["speech_clarity"].pass_band == "≥0.8"
        assert by_name["intentionality"].pass_band == "≥0.95"
        assert by_name["dynamic_range"].pass_band == "7..14"
        assert by_name["av_coherence"].pass_band == "≥0.6"
