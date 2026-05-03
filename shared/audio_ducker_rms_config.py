"""RMS-window configuration for the ducker (cc-task audio-audit-C-rms-window-50-to-20-ms Phase 0).

Auditor C: the current 50 ms RMS window means the ducker reacts ~50 ms late
to operator-speech onset, clipping the first phoneme. Drop to 20 ms and
validate that false-positive triggers (hand-clap, chair-creak, mouse-click)
don't increase materially.

Phase 0 (this module): pin BOTH the legacy and the target window values so
Phase 1's swap is a one-symbol-rename diff. Add the onset-detection-latency
histogram metric so Phase 1 has the measurement surface ready before
flipping the constant.

The actual constant swap in ``agents/audio_ducker/__main__.py:112`` is
deliberately Phase 1 — flipping it on the live ducker requires
hand-clap / chair-creak / mouse-click false-positive validation per the
audit acceptance criteria, which can't be done at CI time.
"""

from __future__ import annotations

from prometheus_client import Histogram

# Current (Phase 0) RMS window — what __main__.py:112 ships today.
# Kept here as a pinned constant so a Phase 1 PR that swaps the import
# can leave a verbatim record of the value being replaced.
RMS_WINDOW_MS_LEGACY: int = 50

# Target (Phase 1) RMS window — the audit-requested value.
# Empirically: 20 ms is the smallest window that still produces stable
# RMS on speech-band signals (200-3 kHz). Going lower starts amplifying
# transient noise (mouse clicks register as onsets) without further latency
# gains since the ducker FSM tick is itself 50 ms.
RMS_WINDOW_MS_TARGET: int = 20

# Onset-detection latency histogram (Phase 0): registered now so Phase 1's
# A/B comparison is a Grafana panel diff, not a schema change. The ducker
# observes the time between operator-speech-onset (per VAD trigger) and the
# first below-target RMS reading on the duck node. Buckets target the
# operator's "snappier" perception: p50 < 30 ms, p99 < 80 ms.
HAPAX_DUCKER_ONSET_DETECTION_LATENCY_MS: Histogram = Histogram(
    "hapax_ducker_onset_detection_latency_ms",
    "Latency between operator VAD onset and first below-target ducker RMS, in milliseconds",
    labelnames=("rms_window_ms",),
    buckets=(5, 10, 20, 30, 50, 75, 100, 150, 250, 500, 1000),
)


def expected_rms_samples(window_ms: int, sample_rate_hz: int = 48000) -> int:
    """Compute RMS sample count from window width + sample rate.

    Pinned as a public helper so the Phase 1 swap in ``__main__.py`` can
    delegate to a tested function rather than re-derive the formula at
    each call site. Matches the existing inline ``int(SAMPLE_RATE *
    RMS_WINDOW_MS / 1000)`` derivation.
    """
    if window_ms <= 0:
        raise ValueError(f"window_ms must be positive, got {window_ms}")
    if sample_rate_hz <= 0:
        raise ValueError(f"sample_rate_hz must be positive, got {sample_rate_hz}")
    return int(sample_rate_hz * window_ms / 1000)
