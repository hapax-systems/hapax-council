"""parec-RMS signal-flow measurement for ``scripts/hapax-audio-routing-check`` (task 3).

``pw-top`` reports ``quantum=0 rate=0`` on the broadcast filter-chain nodes even
while audio flows — a documented false-negative (``config/pipewire/hapax-broadcast-master.conf``)
that actively misled a live incident by reporting "NO DATA FLOWING" on a healthy
chain. This module measures the *real* signal instead: decode the raw s16le PCM
that ``parec --raw --format=s16le`` writes and compute RMS dBFS, classifying a
node as flowing when RMS clears a silence floor.

CLI (invoked by the routing-check script)::

    parec -d <node>.monitor --raw --format=s16le --rate=48000 --channels=2 \\
        | python3 -m agents.audio_health.node_rms --floor -60

Prints ``FLOWING <rms_dbfs>`` / ``SILENT <rms_dbfs>`` and exits 0 (flowing) / 1 (silent).
"""

from __future__ import annotations

import argparse
import sys

import numpy as np

# Returned for an empty or pure-zero capture — well below any real signal floor.
SILENCE_DBFS: float = -120.0


def rms_dbfs_s16le(pcm: bytes) -> float:
    """RMS level (dBFS) of interleaved little-endian s16 PCM.

    Empty or pure-silence input returns :data:`SILENCE_DBFS`. A capture truncated
    mid-sample (odd byte count) is tolerated by dropping the trailing partial byte
    rather than raising — ``parec`` windows can end mid-frame.
    """
    usable = len(pcm) - (len(pcm) % 2)
    if usable <= 0:
        return SILENCE_DBFS
    samples = np.frombuffer(pcm[:usable], dtype="<i2").astype(np.float64) / 32768.0
    if samples.size == 0:
        return SILENCE_DBFS
    rms = float(np.sqrt(np.mean(samples**2)))
    if rms <= 0.0:
        return SILENCE_DBFS
    return 20.0 * float(np.log10(rms))


def classify_flow(pcm: bytes, *, floor_dbfs: float) -> tuple[float, bool]:
    """Return ``(rms_dbfs, flowing)`` — flowing iff RMS strictly exceeds the floor."""
    rms = rms_dbfs_s16le(pcm)
    return rms, rms > floor_dbfs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Classify node signal flow from raw s16le PCM on stdin.",
    )
    parser.add_argument("--floor", type=float, default=-60.0, help="silence floor in dBFS")
    args = parser.parse_args(argv)
    rms, flowing = classify_flow(sys.stdin.buffer.read(), floor_dbfs=args.floor)
    print(f"{'FLOWING' if flowing else 'SILENT'} {rms:.1f}")
    return 0 if flowing else 1


if __name__ == "__main__":
    raise SystemExit(main())
