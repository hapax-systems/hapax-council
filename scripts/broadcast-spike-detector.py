#!/usr/bin/env python3
"""Broadcast audio spike detector — captures from hapax-broadcast-normalized
and logs any transient amplitude spike (>= threshold_db above running RMS).

Designed to catch the recurring +6dB crackle reported on the livestream.
Outputs timestamp, spike amplitude, running RMS, and delta for each event.
"""

import array
import math
import subprocess
import sys
import time
from datetime import UTC, datetime

SOURCE = "hapax-broadcast-normalized"
SAMPLE_RATE = 48000
CHANNELS = 2
CHUNK_MS = 10  # 10ms chunks — matches the reported spike duration
CHUNK_SAMPLES = SAMPLE_RATE * CHUNK_MS // 1000  # 480 samples per chunk
CHUNK_BYTES = CHUNK_SAMPLES * CHANNELS * 2  # int16 stereo

# Detection thresholds
SPIKE_THRESHOLD_DB = 4.0  # flag anything +4dB above running RMS
RMS_WINDOW_CHUNKS = 100  # ~1 second of RMS history
MIN_ABSOLUTE_DBFS = -40.0  # ignore spikes during silence

FULL_SCALE = 32767.0


def dbfs(amp: float) -> float:
    if amp <= 0:
        return -120.0
    return max(-120.0, 20.0 * math.log10(amp / FULL_SCALE))


def chunk_rms(samples: array.array) -> float:
    if not samples:
        return 0.0
    sum_sq = sum(float(s) * float(s) for s in samples)
    return math.sqrt(sum_sq / len(samples))


def chunk_peak(samples: array.array) -> int:
    if not samples:
        return 0
    return max(abs(s) for s in samples)


def main():
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 300  # default 5 min
    print(f"[spike-detector] Monitoring {SOURCE} for {duration}s")
    print(f"[spike-detector] Spike threshold: +{SPIKE_THRESHOLD_DB}dB above running RMS")
    print(f"[spike-detector] Chunk size: {CHUNK_MS}ms ({CHUNK_SAMPLES} samples)")
    print()

    cmd = [
        "parec",
        "--device",
        SOURCE,
        "--rate",
        str(SAMPLE_RATE),
        "--channels",
        str(CHANNELS),
        "--format",
        "s16le",
        "--raw",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    assert proc.stdout is not None

    rms_history: list[float] = []
    spike_count = 0
    chunk_count = 0
    start = time.monotonic()

    try:
        while time.monotonic() - start < duration:
            raw = proc.stdout.read(CHUNK_BYTES)
            if len(raw) < CHUNK_BYTES:
                break

            # Parse stereo int16, downmix to mono
            stereo = array.array("h")
            stereo.frombytes(raw)
            mono = array.array(
                "h", [(stereo[i] + stereo[i + 1]) // 2 for i in range(0, len(stereo), 2)]
            )

            rms = chunk_rms(mono)
            peak = chunk_peak(mono)
            _ = dbfs(rms)  # rms_db reserved for future per-window logging
            peak_db = dbfs(float(peak))

            # Maintain running RMS
            rms_history.append(rms)
            if len(rms_history) > RMS_WINDOW_CHUNKS:
                rms_history.pop(0)

            # Running average RMS
            if len(rms_history) >= 10:
                avg_rms = sum(rms_history) / len(rms_history)
                avg_rms_db = dbfs(avg_rms)

                # Detect spike: peak significantly above running RMS
                delta = peak_db - avg_rms_db

                if delta >= SPIKE_THRESHOLD_DB and peak_db > MIN_ABSOLUTE_DBFS:
                    spike_count += 1
                    ts = datetime.now(UTC).strftime("%H:%M:%S.%f")[:-3]
                    elapsed = time.monotonic() - start
                    print(
                        f"[SPIKE #{spike_count}] {ts} "
                        f"t={elapsed:.1f}s "
                        f"peak={peak_db:+.1f}dBFS "
                        f"rms_avg={avg_rms_db:+.1f}dBFS "
                        f"delta={delta:+.1f}dB "
                        f"peak_sample={peak}"
                    )

            chunk_count += 1
            # Periodic status every 30 seconds
            elapsed = time.monotonic() - start
            if chunk_count % 3000 == 0:  # every 30s
                avg_rms = sum(rms_history) / len(rms_history) if rms_history else 0
                print(
                    f"[status] t={elapsed:.0f}s "
                    f"chunks={chunk_count} "
                    f"spikes={spike_count} "
                    f"rms_avg={dbfs(avg_rms):+.1f}dBFS"
                )

    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()

    elapsed = time.monotonic() - start
    print(f"\n[done] Monitored {elapsed:.0f}s, detected {spike_count} spike(s)")


if __name__ == "__main__":
    main()
