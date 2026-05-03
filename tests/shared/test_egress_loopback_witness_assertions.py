"""Tests for shared.egress_loopback_witness_assertions (cc-task tier-4 Phase 0).

Pin the playback-present derivation, freshness gate, and the 4 distinct
assertion paths.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from shared.broadcast_audio_health import EgressLoopbackWitness
from shared.egress_loopback_witness_assertions import (
    DEFAULT_WITNESS_MAX_AGE_S,
    PLAYBACK_PRESENT_MAX_SILENCE_RATIO,
    PLAYBACK_PRESENT_RMS_DBFS_THRESHOLD,
    StaleWitnessError,
    WitnessIndicatesProducerErrorError,
    WitnessIndicatesSilenceError,
    assert_witness_fresh,
    assert_witness_indicates_no_playback,
    assert_witness_indicates_playback,
    is_playback_present,
    witness_age_s,
)


def _witness(
    *,
    rms_dbfs: float = -10.0,
    peak_dbfs: float = -5.0,
    silence_ratio: float = 0.1,
    target_sink: str = "hapax-broadcast-normalized",
    error: str | None = None,
    checked_at: datetime | None = None,
) -> EgressLoopbackWitness:
    if checked_at is None:
        checked_at = datetime.now(UTC)
    return EgressLoopbackWitness(
        checked_at=checked_at.isoformat(),
        rms_dbfs=rms_dbfs,
        peak_dbfs=peak_dbfs,
        silence_ratio=silence_ratio,
        window_seconds=5.0,
        target_sink=target_sink,
        error=error,
    )


class TestThresholdsPinned:
    def test_rms_threshold_is_documented(self) -> None:
        """Tier-4 spec: rms_dbfs > -40 dBFS = playback present."""
        assert PLAYBACK_PRESENT_RMS_DBFS_THRESHOLD == -40.0

    def test_silence_ratio_threshold_is_documented(self) -> None:
        assert PLAYBACK_PRESENT_MAX_SILENCE_RATIO == 0.95

    def test_default_max_age_is_documented(self) -> None:
        assert DEFAULT_WITNESS_MAX_AGE_S == 30.0


class TestIsPlaybackPresent:
    def test_audible_witness_is_present(self) -> None:
        assert is_playback_present(_witness(rms_dbfs=-15.0, silence_ratio=0.1))

    def test_silent_witness_is_not_present(self) -> None:
        assert not is_playback_present(_witness(rms_dbfs=-50.0))

    def test_at_threshold_is_present(self) -> None:
        """-40 dBFS is at the threshold (inclusive)."""
        assert is_playback_present(_witness(rms_dbfs=-40.0, silence_ratio=0.1))

    def test_just_below_threshold_is_not_present(self) -> None:
        assert not is_playback_present(_witness(rms_dbfs=-40.001, silence_ratio=0.1))

    def test_high_silence_ratio_overrides_audible_rms(self) -> None:
        """RMS straddling the threshold is meaningless if 95%+ of the window
        is silence — the audio is bursty, not playing."""
        assert not is_playback_present(_witness(rms_dbfs=-15.0, silence_ratio=0.96))

    def test_at_silence_ratio_threshold_is_present(self) -> None:
        assert is_playback_present(_witness(rms_dbfs=-15.0, silence_ratio=0.95))

    def test_producer_error_is_not_present(self) -> None:
        """Even with audible RMS, a producer error means we don't trust the
        witness — treat as not present."""
        assert not is_playback_present(_witness(rms_dbfs=-15.0, error="parec timeout"))


class TestWitnessAgeS:
    def test_fresh_witness_age_near_zero(self) -> None:
        age = witness_age_s(_witness())
        assert 0.0 <= age < 1.0

    def test_old_witness_age_correct(self) -> None:
        old_time = datetime.now(UTC) - timedelta(seconds=120)
        age = witness_age_s(_witness(checked_at=old_time))
        assert 119.0 <= age <= 121.0

    def test_explicit_now_used(self) -> None:
        cutoff = datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC)
        old_time = cutoff - timedelta(seconds=45)
        age = witness_age_s(_witness(checked_at=old_time), now=cutoff)
        assert age == pytest.approx(45.0)

    def test_naive_timestamp_rejected(self) -> None:
        """Producer must emit tz-aware UTC; naive timestamps are a producer
        bug we want to surface, not silently treat as UTC."""
        naive = datetime(2026, 5, 3, 12, 0, 0)
        # Building the witness with a naive ISO works (Pydantic accepts it),
        # but witness_age_s rejects.
        witness = EgressLoopbackWitness(
            checked_at=naive.isoformat(),
            rms_dbfs=-10.0,
            peak_dbfs=-5.0,
            silence_ratio=0.1,
            window_seconds=5.0,
            target_sink="x",
        )
        with pytest.raises(ValueError, match="no timezone"):
            witness_age_s(witness)

    def test_unparseable_timestamp_rejected(self) -> None:
        witness = EgressLoopbackWitness(
            checked_at="not-an-iso-timestamp",
            rms_dbfs=-10.0,
            peak_dbfs=-5.0,
            silence_ratio=0.1,
            window_seconds=5.0,
            target_sink="x",
        )
        with pytest.raises(ValueError, match="not parseable"):
            witness_age_s(witness)


class TestAssertWitnessFresh:
    def test_fresh_witness_passes(self) -> None:
        assert_witness_fresh(_witness())

    def test_stale_witness_raises(self) -> None:
        old_time = datetime.now(UTC) - timedelta(seconds=120)
        with pytest.raises(StaleWitnessError, match="120"):
            assert_witness_fresh(_witness(checked_at=old_time), max_age_s=30.0)

    def test_just_inside_max_age_passes(self) -> None:
        cutoff = datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC)
        age_29s = cutoff - timedelta(seconds=29)
        assert_witness_fresh(_witness(checked_at=age_29s), now=cutoff, max_age_s=30.0)

    def test_just_past_max_age_raises(self) -> None:
        cutoff = datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC)
        age_31s = cutoff - timedelta(seconds=31)
        with pytest.raises(StaleWitnessError):
            assert_witness_fresh(_witness(checked_at=age_31s), now=cutoff, max_age_s=30.0)


class TestAssertWitnessIndicatesPlayback:
    """Tier-4 acceptance: this is the canonical 'broadcast egress is alive'
    assertion the integration tests will use."""

    def test_fresh_audible_passes(self) -> None:
        assert_witness_indicates_playback(_witness(rms_dbfs=-15.0, silence_ratio=0.1))

    def test_stale_witness_raises_stale_error(self) -> None:
        """Producer-pipeline failure: witness is too old to trust."""
        old_time = datetime.now(UTC) - timedelta(seconds=120)
        with pytest.raises(StaleWitnessError):
            assert_witness_indicates_playback(_witness(checked_at=old_time))

    def test_silent_fresh_witness_raises_silence_error(self) -> None:
        """Audio-chain failure: producer is alive but the egress is silent."""
        with pytest.raises(WitnessIndicatesSilenceError, match="rms_dbfs"):
            assert_witness_indicates_playback(_witness(rms_dbfs=-50.0))

    def test_producer_error_witness_raises_producer_error_error(self) -> None:
        """Distinct error class so the integration test can differentiate
        sampling fault from audio-chain silence."""
        with pytest.raises(WitnessIndicatesProducerErrorError, match="parec"):
            assert_witness_indicates_playback(_witness(rms_dbfs=-15.0, error="parec timeout"))


class TestAssertWitnessIndicatesNoPlayback:
    """Inverse assertion — used after the 'stop playback' step."""

    def test_silent_fresh_witness_passes(self) -> None:
        assert_witness_indicates_no_playback(_witness(rms_dbfs=-50.0))

    def test_audible_fresh_witness_raises(self) -> None:
        with pytest.raises(WitnessIndicatesSilenceError, match="expected silence"):
            assert_witness_indicates_no_playback(_witness(rms_dbfs=-15.0))

    def test_stale_witness_raises_stale_error(self) -> None:
        old_time = datetime.now(UTC) - timedelta(seconds=120)
        with pytest.raises(StaleWitnessError):
            assert_witness_indicates_no_playback(_witness(checked_at=old_time))


class TestExceptionHierarchy:
    def test_all_subclass_assertion_error(self) -> None:
        from shared.egress_loopback_witness_assertions import WitnessAssertionError

        assert issubclass(StaleWitnessError, WitnessAssertionError)
        assert issubclass(WitnessIndicatesSilenceError, WitnessAssertionError)
        assert issubclass(WitnessIndicatesProducerErrorError, WitnessAssertionError)
        assert issubclass(WitnessAssertionError, AssertionError)

    def test_distinct_classes_for_targeted_catch(self) -> None:
        """Integration test must be able to catch 'producer pipeline broke'
        separately from 'audio chain went silent'."""
        old_time = datetime.now(UTC) - timedelta(seconds=120)
        try:
            assert_witness_indicates_playback(_witness(checked_at=old_time))
        except StaleWitnessError:
            pass
        except (WitnessIndicatesSilenceError, WitnessIndicatesProducerErrorError):
            pytest.fail("Should have caught StaleWitnessError specifically")
