"""Tests for parec-RMS signal-flow measurement (task 3).

``pw-top`` false-negatives on the broadcast filter-chain nodes — it reports
``quantum=0 rate=0`` ("NO DATA FLOWING") even while audio flows, which actively
misled a live incident. ``node_rms`` replaces that advisory: it decodes the raw
s16le PCM that ``parec --raw --format=s16le`` writes and computes RMS dBFS,
classifying a node as flowing when RMS clears a silence floor.
"""

from __future__ import annotations

import struct

from agents.audio_health.node_rms import classify_flow, rms_dbfs_s16le


def _s16le(samples: list[int]) -> bytes:
    return struct.pack("<" + "h" * len(samples), *samples)


def test_rms_dbfs_near_full_scale_is_near_zero() -> None:
    assert rms_dbfs_s16le(_s16le([32000, -32000] * 1000)) > -2.0


def test_rms_dbfs_silence_is_floor() -> None:
    assert rms_dbfs_s16le(_s16le([0] * 2000)) <= -120.0


def test_rms_dbfs_empty_capture_is_floor() -> None:
    assert rms_dbfs_s16le(b"") <= -120.0


def test_rms_dbfs_odd_byte_tail_is_tolerated() -> None:
    # A capture truncated mid-sample must not raise.
    pcm = _s16le([8000, -8000] * 100) + b"\x01"
    assert rms_dbfs_s16le(pcm) > -120.0


def test_classify_flow_signal_above_floor_is_flowing() -> None:
    rms, flowing = classify_flow(_s16le([8000, -8000] * 1000), floor_dbfs=-60.0)
    assert flowing is True
    assert rms > -60.0


def test_classify_flow_silence_below_floor_is_not_flowing() -> None:
    _rms, flowing = classify_flow(_s16le([0] * 2000), floor_dbfs=-60.0)
    assert flowing is False
