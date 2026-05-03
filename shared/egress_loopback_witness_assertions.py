"""Egress-loopback witness assertions (cc-task jr-broadcast-chain-integration-tier4-loopback-witness Phase 0).

Tier-4 of the broadcast-chain integration test matrix: replace ad-hoc
``audio-measure.sh`` invocations with assertions against the
``EgressLoopbackWitness`` written by the loopback producer (PR #2235,
already merged).

Phase 0 (this module): pure-function derivations + assertion helpers
that pytest fixtures + adjacent tests can call without any audio
hardware. Phase 1 ships a reusable pytest fixture that actually starts
``pw-cat`` playback against ``hapax-broadcast-normalized`` and waits for
the witness to update.

Why factor it this way:
- ``is_playback_present`` is the canonical derivation of "broadcast
  egress is alive" from the witness's existing fields. Pinning it once
  here keeps every adjacent test using the same threshold semantics
  rather than each rolling its own ``rms_dbfs > X`` check.
- The freshness assertion is a load-bearing safety: a stale witness
  reading a healthy snapshot from 5 minutes ago can falsely pass any
  "is playback live?" check. Phase 0 puts this gate in the Pythonic
  layer before any test sees the witness.
- Distinct exception classes (``StaleWitnessError`` vs
  ``WitnessIndicatesSilenceError``) let test consumers handle the two
  failure modes separately — staleness is a producer-pipeline failure,
  silence is an audio-chain failure.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

from shared.broadcast_audio_health import EgressLoopbackWitness

# Threshold above which we consider the witness "playback present".
# The producer already uses ``-55 dBFS`` as its blocking-condition floor
# (``BroadcastAudioHealthThresholds.rms_dbfs_floor``); -40 dBFS is a
# higher threshold appropriate for "is something actually playing"
# (vs. "is the broadcast not catastrophically silent"). Tier-4 task
# spec calls -40 dBFS specifically; pinned as a constant so the pytest
# fixture and operator runbook share the same value.
PLAYBACK_PRESENT_RMS_DBFS_THRESHOLD: Final[float] = -40.0

# Maximum silence ratio a "playback present" witness may carry. > 0.95 means
# 95%+ of the captured window was below the silence floor — even if RMS
# straddles the threshold, the signal is intermittent and not "playing".
PLAYBACK_PRESENT_MAX_SILENCE_RATIO: Final[float] = 0.95

# Default freshness window for "is the witness recent enough to trust".
# Producer writes every ~5s; 30s gives 6x freshness headroom.
DEFAULT_WITNESS_MAX_AGE_S: Final[float] = 30.0


class WitnessAssertionError(AssertionError):
    """Base class for witness-derived assertion failures."""


class StaleWitnessError(WitnessAssertionError):
    """Witness is older than ``max_age_s``; producer may be down."""


class WitnessIndicatesSilenceError(WitnessAssertionError):
    """Witness is fresh but indicates the broadcast is silent."""


class WitnessIndicatesProducerErrorError(WitnessAssertionError):
    """Witness ``error`` field is populated; producer hit a sampling fault."""


def is_playback_present(witness: EgressLoopbackWitness) -> bool:
    """Derive ``playback_present`` from witness fields.

    Returns ``True`` iff:
    - ``error`` is ``None`` (producer sampled cleanly)
    - ``rms_dbfs`` >= ``PLAYBACK_PRESENT_RMS_DBFS_THRESHOLD`` (audible signal)
    - ``silence_ratio`` <= ``PLAYBACK_PRESENT_MAX_SILENCE_RATIO`` (signal
      is sustained, not bursty silence)

    This is the single source-of-truth derivation; tests that need a
    different threshold call ``is_playback_present_with(...)``.
    """
    return is_playback_present_with(
        witness,
        rms_threshold_dbfs=PLAYBACK_PRESENT_RMS_DBFS_THRESHOLD,
        max_silence_ratio=PLAYBACK_PRESENT_MAX_SILENCE_RATIO,
    )


def is_playback_present_with(
    witness: EgressLoopbackWitness,
    *,
    rms_threshold_dbfs: float,
    max_silence_ratio: float,
) -> bool:
    """``is_playback_present`` with caller-supplied thresholds."""
    if witness.error is not None:
        return False
    if witness.rms_dbfs < rms_threshold_dbfs:
        return False
    return witness.silence_ratio <= max_silence_ratio


def witness_age_s(witness: EgressLoopbackWitness, *, now: datetime | None = None) -> float:
    """Compute witness age in seconds vs ``now`` (UTC; default = now()).

    Raises ``ValueError`` if ``checked_at`` cannot be parsed (witness was
    written by a producer not honouring the canonical ISO-8601 format).
    """
    now = now or datetime.now(UTC)
    try:
        checked_at = datetime.fromisoformat(witness.checked_at)
    except ValueError as exc:
        raise ValueError(
            f"witness.checked_at {witness.checked_at!r} is not parseable ISO-8601"
        ) from exc
    if checked_at.tzinfo is None:
        # Producer must always emit tz-aware UTC; reject naive timestamps.
        raise ValueError(
            f"witness.checked_at {witness.checked_at!r} has no timezone "
            f"(producer must emit tz-aware UTC)"
        )
    return (now - checked_at).total_seconds()


def assert_witness_fresh(
    witness: EgressLoopbackWitness,
    *,
    now: datetime | None = None,
    max_age_s: float = DEFAULT_WITNESS_MAX_AGE_S,
) -> None:
    """Raise StaleWitnessError if witness is older than ``max_age_s``."""
    age = witness_age_s(witness, now=now)
    if age > max_age_s:
        raise StaleWitnessError(
            f"witness is {age:.1f}s old (max {max_age_s}s); producer may be down"
        )


def assert_witness_indicates_playback(
    witness: EgressLoopbackWitness,
    *,
    now: datetime | None = None,
    max_age_s: float = DEFAULT_WITNESS_MAX_AGE_S,
    rms_threshold_dbfs: float = PLAYBACK_PRESENT_RMS_DBFS_THRESHOLD,
    max_silence_ratio: float = PLAYBACK_PRESENT_MAX_SILENCE_RATIO,
) -> None:
    """Composite assertion: witness is fresh AND indicates playback.

    Decomposed into distinct error classes so a calling test can
    differentiate producer-pipeline failure (StaleWitnessError) from
    audio-chain failure (WitnessIndicatesSilenceError or
    WitnessIndicatesProducerErrorError).
    """
    assert_witness_fresh(witness, now=now, max_age_s=max_age_s)

    if witness.error is not None:
        raise WitnessIndicatesProducerErrorError(
            f"producer reported sampling error: {witness.error!r}"
        )

    if not is_playback_present_with(
        witness,
        rms_threshold_dbfs=rms_threshold_dbfs,
        max_silence_ratio=max_silence_ratio,
    ):
        raise WitnessIndicatesSilenceError(
            f"witness fresh but indicates silence: rms_dbfs={witness.rms_dbfs}, "
            f"silence_ratio={witness.silence_ratio}, "
            f"target_sink={witness.target_sink!r}"
        )


def assert_witness_indicates_no_playback(
    witness: EgressLoopbackWitness,
    *,
    now: datetime | None = None,
    max_age_s: float = DEFAULT_WITNESS_MAX_AGE_S,
) -> None:
    """Inverse assertion: witness is fresh AND indicates no playback.

    Used after a "stop playback" step in the integration test fixture to
    verify the witness actually saw silence within the freshness window.
    """
    assert_witness_fresh(witness, now=now, max_age_s=max_age_s)

    if is_playback_present(witness):
        raise WitnessIndicatesSilenceError(
            f"expected silence but witness shows playback: rms_dbfs={witness.rms_dbfs}, "
            f"silence_ratio={witness.silence_ratio}"
        )
