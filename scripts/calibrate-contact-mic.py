#!/usr/bin/env python3
"""Interactive contact microphone calibration wizard.

Run from a Claude Code session:
    uv run python scripts/calibrate-contact-mic.py

Walks through each calibration step, records real DSP metrics from the
contact mic, shows distributions, and writes tuned constants to a YAML
file that can be reviewed before applying to contact_mic.py and cameras.py.

Requires: the contact_mic PipeWire virtual source to be active.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# ── DSP functions (copied from contact_mic.py to avoid import chain) ──────────

_FFT_SIZE = 512
_SAMPLE_RATE = 16000


def _compute_rms(frame: bytes) -> float:
    samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
    if len(samples) == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples**2)))


def _compute_spectral_centroid(frame: bytes) -> float:
    samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
    if len(samples) < _FFT_SIZE:
        return 0.0
    window = np.hanning(_FFT_SIZE)
    spec = np.abs(np.fft.rfft(samples[:_FFT_SIZE] * window))
    total = spec.sum()
    if total < 1e-10:
        return 0.0
    freqs = np.fft.rfftfreq(_FFT_SIZE, d=1.0 / _SAMPLE_RATE)
    return float(np.sum(freqs * spec) / total)


def _compute_envelope_autocorrelation(
    energy_buffer: deque[float], min_lag: int = 2, max_lag: int = 16
) -> float:
    if len(energy_buffer) < max_lag + 1:
        return 0.0
    arr = np.array(energy_buffer, dtype=np.float32)
    arr = arr - arr.mean()
    norm = np.dot(arr, arr)
    if norm < 1e-10:
        return 0.0
    peak = 0.0
    for lag in range(min_lag, max_lag + 1):
        corr = np.dot(arr[:-lag], arr[lag:]) / norm
        if corr > peak:
            peak = corr
    return float(peak)


# ── Recording helper ──────────────────────────────────────────────────────────


@dataclass
class RecordingStats:
    """Statistics from a recording session."""

    rms_values: list[float] = field(default_factory=list)
    centroid_values: list[float] = field(default_factory=list)
    onset_times: list[float] = field(default_factory=list)
    autocorr_values: list[float] = field(default_factory=list)
    duration_s: float = 0.0

    @property
    def rms_mean(self) -> float:
        return statistics.mean(self.rms_values) if self.rms_values else 0.0

    @property
    def rms_p95(self) -> float:
        if not self.rms_values:
            return 0.0
        s = sorted(self.rms_values)
        return s[int(len(s) * 0.95)]

    @property
    def rms_max(self) -> float:
        return max(self.rms_values) if self.rms_values else 0.0

    @property
    def centroid_mean(self) -> float:
        return statistics.mean(self.centroid_values) if self.centroid_values else 0.0

    @property
    def onset_rate(self) -> float:
        if self.duration_s <= 0 or len(self.onset_times) < 2:
            return 0.0
        return len(self.onset_times) / self.duration_s

    @property
    def autocorr_mean(self) -> float:
        return statistics.mean(self.autocorr_values) if self.autocorr_values else 0.0

    @property
    def autocorr_p95(self) -> float:
        if not self.autocorr_values:
            return 0.0
        s = sorted(self.autocorr_values)
        return s[int(len(s) * 0.95)]


def record_contact_mic(duration_s: float) -> RecordingStats:
    """Record from the contact mic via PipeWire default source.

    Requires: pactl set-default-source contact_mic
    """
    import subprocess

    import pyaudio

    # Verify contact_mic is the default source
    try:
        result = subprocess.run(
            ["pactl", "get-default-source"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        default_src = result.stdout.strip()
        if "contact_mic" not in default_src:
            print(f"  WARNING: Default source is '{default_src}', not contact_mic.")
            print("  Setting default source to contact_mic...")
            subprocess.run(["pactl", "set-default-source", "contact_mic"], timeout=5)
    except Exception as e:
        print(f"  WARNING: Could not verify default source: {e}")

    pa = pyaudio.PyAudio()

    # Use default device (contact_mic set via pactl)
    stream = pa.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=_SAMPLE_RATE,
        input=True,
        frames_per_buffer=_FFT_SIZE,
    )

    stats = RecordingStats()
    energy_buffer: deque[float] = deque(maxlen=60)
    smoothed_energy = 0.0
    last_onset = 0.0
    frame_count = 0
    # Adaptive onset detection: track a slow-moving baseline and detect
    # transients that exceed it by a ratio. This works at any gain level.
    baseline = 0.0
    _BASELINE_ALPHA = 0.02  # slow follower
    _ONSET_RATIO = 1.5  # transient must be 1.5x baseline
    start = time.monotonic()

    print(f"  Recording for {duration_s:.0f}s...", end="", flush=True)

    while (time.monotonic() - start) < duration_s:
        data = stream.read(_FFT_SIZE, exception_on_overflow=False)
        now = time.monotonic()
        frame_count += 1

        rms = _compute_rms(data)
        stats.rms_values.append(rms)
        energy_buffer.append(rms)

        # Update slow baseline
        baseline = _BASELINE_ALPHA * rms + (1 - _BASELINE_ALPHA) * baseline

        # Adaptive onset detection: transient exceeds baseline by ratio
        onset_floor = max(baseline * _ONSET_RATIO, 0.001)
        if rms > onset_floor and smoothed_energy <= onset_floor and (now - last_onset) > 0.05:
            stats.onset_times.append(now)
            last_onset = now
        smoothed_energy = 0.3 * rms + 0.7 * smoothed_energy

        # Spectral centroid every 4th frame
        if frame_count % 4 == 0:
            centroid = _compute_spectral_centroid(data)
            stats.centroid_values.append(centroid)
            autocorr = _compute_envelope_autocorrelation(energy_buffer)
            stats.autocorr_values.append(autocorr)

    stats.duration_s = time.monotonic() - start
    stream.stop_stream()
    stream.close()
    pa.terminate()
    print(" done.")
    return stats


def show_stats(label: str, stats: RecordingStats) -> None:
    """Print a stats summary."""
    print(f"\n  === {label} ===")
    print(f"  Duration:       {stats.duration_s:.1f}s")
    print(f"  RMS mean:       {stats.rms_mean:.5f}")
    print(f"  RMS p95:        {stats.rms_p95:.5f}")
    print(f"  RMS max:        {stats.rms_max:.5f}")
    print(f"  Centroid mean:  {stats.centroid_mean:.1f} Hz")
    print(f"  Onset rate:     {stats.onset_rate:.1f} /sec")
    print(f"  Autocorr mean:  {stats.autocorr_mean:.3f}")
    print(f"  Autocorr p95:   {stats.autocorr_p95:.3f}")


def midpoint(a: float, b: float) -> float:
    """Midpoint between two values (for threshold setting)."""
    return (a + b) / 2.0


def safe_float(val: str, fallback: float) -> float:
    """Parse a float from user input, returning fallback on empty/invalid."""
    val = val.strip()
    if not val:
        return fallback
    try:
        return float(val)
    except ValueError:
        print(f"  Invalid number '{val}', keeping {fallback}")
        return fallback


# ── Calibration steps ─────────────────────────────────────────────────────────


def prompt(msg: str) -> str:
    """Prompt the user and return their input."""
    return input(f"\n  {msg}\n  > ").strip()


def confirm(msg: str) -> bool:
    """Ask yes/no question."""
    resp = input(f"\n  {msg} [Y/n] ").strip().lower()
    return resp in ("", "y", "yes")


def wait_for_ready(instruction: str) -> None:
    """Show instruction and wait for user to press Enter."""
    input(f"\n  {instruction}\n  Press Enter when ready...")


TUNED: dict[str, float | str | dict] = {}
RECORDINGS: dict[str, RecordingStats] = {}


def step_1_silence():
    """Step 1: Record ambient silence to establish noise floor."""
    print("\n" + "=" * 70)
    print("STEP 1: AMBIENT NOISE FLOOR")
    print("=" * 70)
    print("""
  Goal: Measure the contact mic's noise floor when the desk is completely still.
  This sets _IDLE_THRESHOLD — below this energy, everything is classified as "idle".

  What to do:
    - Don't touch the desk
    - Don't type, tap, or move anything on the desk surface
    - Sit still or step away
    - Background noise (HVAC, fans) is fine — that's what we're measuring
    """)
    wait_for_ready("Sit still, hands off desk.")
    stats = record_contact_mic(15.0)
    RECORDINGS["silence"] = stats
    show_stats("Silence (noise floor)", stats)

    # Idle threshold: set at 2x the p95 noise floor
    idle_threshold = stats.rms_p95 * 2.0
    TUNED["_IDLE_THRESHOLD"] = round(idle_threshold, 6)
    print(f"\n  Recommended _IDLE_THRESHOLD: {idle_threshold:.6f}")
    print(f"  (2x the p95 noise floor of {stats.rms_p95:.6f})")

    if not confirm("Accept this value?"):
        val = prompt("Enter custom _IDLE_THRESHOLD:")
        TUNED["_IDLE_THRESHOLD"] = safe_float(val, TUNED["_IDLE_THRESHOLD"])


def step_2_typing():
    """Step 2: Record normal typing to calibrate typing detection."""
    print("\n" + "=" * 70)
    print("STEP 2: TYPING")
    print("=" * 70)
    print("""
  Goal: Measure what typing looks like to the contact mic.
  This calibrates _TYPING_MIN_ONSET_RATE, and helps set _ONSET_THRESHOLD.

  What to do:
    - Type normally on your keyboard for 20 seconds
    - Use your natural typing speed and force
    - Type actual text (not just mashing keys)
    """)
    wait_for_ready("Start typing when you press Enter.")
    stats = record_contact_mic(20.0)
    RECORDINGS["typing"] = stats
    show_stats("Typing", stats)

    # Onset threshold: midpoint between silence p95 and typing mean
    silence_p95 = RECORDINGS["silence"].rms_p95
    onset_threshold = midpoint(silence_p95, stats.rms_mean)
    TUNED["_ONSET_THRESHOLD"] = round(onset_threshold, 5)
    print(f"\n  Recommended _ONSET_THRESHOLD: {onset_threshold:.5f}")
    print(
        f"  (midpoint between silence p95={silence_p95:.5f} and typing mean={stats.rms_mean:.5f})"
    )

    # Typing onset rate: use p5 of the recorded rate as minimum
    # (so 95% of real typing sessions exceed the threshold)
    typing_rate = stats.onset_rate
    typing_min = typing_rate * 0.6  # 60% of observed rate
    TUNED["_TYPING_MIN_ONSET_RATE"] = round(typing_min, 1)
    print(f"\n  Observed typing onset rate: {typing_rate:.1f} /sec")
    print(f"  Recommended _TYPING_MIN_ONSET_RATE: {typing_min:.1f}")
    print("  (60% of observed, so normal variation still classifies)")

    if not confirm("Accept these values?"):
        val = prompt("Enter custom _ONSET_THRESHOLD (or Enter to keep recommended):")
        TUNED["_ONSET_THRESHOLD"] = safe_float(val, TUNED["_ONSET_THRESHOLD"])
        val = prompt("Enter custom _TYPING_MIN_ONSET_RATE (or Enter to keep recommended):")
        TUNED["_TYPING_MIN_ONSET_RATE"] = safe_float(val, TUNED["_TYPING_MIN_ONSET_RATE"])


def step_3_tapping():
    """Step 3: Record pad tapping to calibrate tapping detection."""
    print("\n" + "=" * 70)
    print("STEP 3: PAD TAPPING (light)")
    print("=" * 70)
    print("""
  Goal: Measure light pad tapping on your SP-404 or MPC.
  This calibrates _TAPPING_MIN_ONSET_RATE and helps separate tapping from typing.

  What to do:
    - Tap pads at a moderate tempo (not fast finger drumming)
    - Use your normal playing force
    - Vary between different pads
    """)
    wait_for_ready("Start tapping pads when you press Enter.")
    stats = record_contact_mic(20.0)
    RECORDINGS["tapping"] = stats
    show_stats("Pad tapping", stats)

    # Tapping onset rate: use 60% of observed
    tapping_rate = stats.onset_rate
    tapping_min = max(0.5, tapping_rate * 0.6)
    TUNED["_TAPPING_MIN_ONSET_RATE"] = round(tapping_min, 1)
    print(f"\n  Observed tapping onset rate: {tapping_rate:.1f} /sec")
    print(f"  Recommended _TAPPING_MIN_ONSET_RATE: {tapping_min:.1f}")

    if not confirm("Accept this value?"):
        val = prompt("Enter custom _TAPPING_MIN_ONSET_RATE:")
        TUNED["_TAPPING_MIN_ONSET_RATE"] = safe_float(val, TUNED["_TAPPING_MIN_ONSET_RATE"])


def step_4_drumming():
    """Step 4: Record hard drumming to calibrate drumming detection."""
    print("\n" + "=" * 70)
    print("STEP 4: HARD DRUMMING")
    print("=" * 70)
    print("""
  Goal: Measure hard finger drumming on pads.
  This calibrates _DRUMMING_MIN_ENERGY and _DRUMMING_MAX_CENTROID.

  What to do:
    - Hit pads HARD — finger drumming, not light tapping
    - Play a beat, vary between kick/snare/hat pads
    - Use your full playing intensity
    """)
    wait_for_ready("Start drumming when you press Enter.")
    stats = record_contact_mic(20.0)
    RECORDINGS["drumming"] = stats
    show_stats("Hard drumming", stats)

    # Drumming energy: midpoint between tapping p95 and drumming mean
    tapping_p95 = RECORDINGS["tapping"].rms_p95
    drumming_energy = midpoint(tapping_p95, stats.rms_mean)
    TUNED["_DRUMMING_MIN_ENERGY"] = round(drumming_energy, 3)
    print(f"\n  Tapping p95 energy: {tapping_p95:.5f}")
    print(f"  Drumming mean energy: {stats.rms_mean:.5f}")
    print(f"  Recommended _DRUMMING_MIN_ENERGY: {drumming_energy:.3f}")

    # Centroid: use drumming p95 as the upper bound
    centroid_max = stats.centroid_mean * 1.5
    TUNED["_DRUMMING_MAX_CENTROID"] = round(centroid_max, 0)
    print(f"\n  Drumming centroid mean: {stats.centroid_mean:.1f} Hz")
    print(f"  Recommended _DRUMMING_MAX_CENTROID: {centroid_max:.0f} Hz")
    print("  (1.5x mean, so most drumming falls within)")

    if not confirm("Accept these values?"):
        val = prompt("Enter custom _DRUMMING_MIN_ENERGY:")
        TUNED["_DRUMMING_MIN_ENERGY"] = safe_float(val, TUNED["_DRUMMING_MIN_ENERGY"])
        val = prompt("Enter custom _DRUMMING_MAX_CENTROID:")
        TUNED["_DRUMMING_MAX_CENTROID"] = safe_float(val, TUNED["_DRUMMING_MAX_CENTROID"])


def step_5_scratching():
    """Step 5: Record vinyl scratching to calibrate scratch detection."""
    print("\n" + "=" * 70)
    print("STEP 5: VINYL SCRATCHING")
    print("=" * 70)
    print("""
  Goal: Measure the autocorrelation signature of vinyl scratching.
  This is the KEY calibration — sets _SCRATCH_AUTOCORR_THRESHOLD.

  What to do:
    - Scratch vinyl on your turntable for 30 seconds
    - Mix techniques: baby scratches, chirps, transforms
    - Vary speed and intensity
    - Include some pauses between scratch phrases

  If you don't have vinyl loaded, skip this step.
    """)
    if not confirm("Ready to scratch? (n to skip)"):
        print("  Skipping scratch calibration — using default threshold 0.4")
        TUNED["_SCRATCH_AUTOCORR_THRESHOLD"] = 0.4
        TUNED["_SCRATCH_MIN_ENERGY"] = 0.02
        return

    wait_for_ready("Start scratching when you press Enter.")
    stats = record_contact_mic(30.0)
    RECORDINGS["scratching"] = stats
    show_stats("Vinyl scratching", stats)

    # Compare autocorrelation during scratching vs all previous activities
    non_scratch_autocorr = []
    for name in ("silence", "typing", "tapping", "drumming"):
        if name in RECORDINGS:
            non_scratch_autocorr.extend(RECORDINGS[name].autocorr_values)

    non_scratch_p95 = 0.0
    if non_scratch_autocorr:
        s = sorted(non_scratch_autocorr)
        non_scratch_p95 = s[int(len(s) * 0.95)]

    scratch_mean = stats.autocorr_mean
    threshold = midpoint(non_scratch_p95, scratch_mean)
    TUNED["_SCRATCH_AUTOCORR_THRESHOLD"] = round(threshold, 3)
    print(f"\n  Non-scratch autocorr p95: {non_scratch_p95:.3f}")
    print(f"  Scratch autocorr mean:    {scratch_mean:.3f}")
    print(f"  Recommended _SCRATCH_AUTOCORR_THRESHOLD: {threshold:.3f}")

    if scratch_mean < non_scratch_p95:
        print(
            "\n  WARNING: Scratch autocorrelation is NOT clearly separated from other activities."
        )
        print("  The threshold may produce false positives. Consider:")
        print("  - Increasing gain on Studio 24c Input 2")
        print("  - Checking the contact mic is firmly attached under the desk")
        print("  - The turntable may need to be closer to the mic mounting point")

    # Scratch min energy: use 50% of scratch mean energy
    scratch_min_energy = stats.rms_mean * 0.5
    TUNED["_SCRATCH_MIN_ENERGY"] = round(scratch_min_energy, 4)
    print(f"\n  Scratch mean energy: {stats.rms_mean:.5f}")
    print(f"  Recommended _SCRATCH_MIN_ENERGY: {scratch_min_energy:.4f}")

    if not confirm("Accept these values?"):
        val = prompt("Enter custom _SCRATCH_AUTOCORR_THRESHOLD:")
        TUNED["_SCRATCH_AUTOCORR_THRESHOLD"] = safe_float(val, TUNED["_SCRATCH_AUTOCORR_THRESHOLD"])
        val = prompt("Enter custom _SCRATCH_MIN_ENERGY:")
        TUNED["_SCRATCH_MIN_ENERGY"] = safe_float(val, TUNED["_SCRATCH_MIN_ENERGY"])


def step_6_gestures():
    """Step 6: Test gesture detection timing."""
    print("\n" + "=" * 70)
    print("STEP 6: GESTURE TIMING")
    print("=" * 70)
    print("""
  Goal: Verify double-tap and triple-tap detection at your natural speed.

  The current gesture windows are:
    Double-tap: two taps within 300ms, IOI between 80-250ms
    Triple-tap: three taps within 500ms, IOI >= 80ms each

  What to do:
    - Double-tap the desk 5 times (with pauses between attempts)
    - Triple-tap the desk 5 times (with pauses between attempts)

  We'll record the onset timing to verify the windows work for you.
    """)
    print("  Double-tap test: tap the desk TWICE, quickly, 5 separate times.")
    print("  Leave ~2 seconds between each double-tap attempt.")
    wait_for_ready("Start double-tapping when you press Enter.")
    stats = record_contact_mic(15.0)
    RECORDINGS["double_tap_test"] = stats

    # Analyze onset timing
    onsets = stats.onset_times
    if len(onsets) < 4:
        print(f"  Only {len(onsets)} onsets detected. Threshold may be too high.")
        print(f"  Current onset threshold: {TUNED.get('_ONSET_THRESHOLD', 0.03)}")
    else:
        # Find pairs that are close together (within 500ms)
        iois = []
        for i in range(1, len(onsets)):
            gap = onsets[i] - onsets[i - 1]
            if gap < 0.5:
                iois.append(gap)
        if iois:
            print(f"\n  Detected {len(iois)} close onset pairs")
            print(f"  IOI range: {min(iois) * 1000:.0f}ms – {max(iois) * 1000:.0f}ms")
            print(f"  IOI mean:  {statistics.mean(iois) * 1000:.0f}ms")

            current_max_ioi = 0.25
            if max(iois) > current_max_ioi:
                new_max = round(max(iois) * 1.2, 2)  # 20% headroom
                print(f"\n  Your slowest double-tap IOI ({max(iois) * 1000:.0f}ms) exceeds")
                print(f"  the current _DOUBLE_TAP_MAX_IOI ({current_max_ioi * 1000:.0f}ms).")
                print(f"  Recommended: {new_max * 1000:.0f}ms")
                TUNED["_DOUBLE_TAP_MAX_IOI"] = new_max
            else:
                print("\n  All IOIs within current window. No change needed.")
                TUNED["_DOUBLE_TAP_MAX_IOI"] = current_max_ioi

    if not confirm("Gesture timing looks good?"):
        val = prompt("Enter custom _DOUBLE_TAP_MAX_IOI (seconds):")
        TUNED["_DOUBLE_TAP_MAX_IOI"] = safe_float(val, TUNED["_DOUBLE_TAP_MAX_IOI"])
        val = prompt("Enter custom _GESTURE_TIMEOUT_S (seconds):")
        TUNED["_GESTURE_TIMEOUT_S"] = safe_float(val, TUNED["_GESTURE_TIMEOUT_S"])


def step_7_zones():
    """Step 7: Calibrate overhead camera instrument zones."""
    print("\n" + "=" * 70)
    print("STEP 7: OVERHEAD CAMERA ZONES")
    print("=" * 70)
    print("""
  Goal: Set bounding boxes for each instrument zone in the overhead camera frame.
  Frame size: 1280 x 720 pixels. Origin (0,0) is top-left.

  Current zones (placeholder estimates):
    turntable:  x1=0,   y1=100, x2=400,  y2=550
    pads:       x1=400, y1=150, x2=800,  y2=500
    mixer:      x1=300, y1=0,   x2=550,  y2=200
    keyboard:   x1=800, y1=300, x2=1280, y2=600

  View the overhead snapshot:
    feh /dev/shm/hapax-compositor/c920-overhead.jpg

  Or open in a browser:
    xdg-open /dev/shm/hapax-compositor/c920-overhead.jpg

  Use an image editor or pixel ruler to identify the bounding box
  coordinates for each instrument. Format: x1,y1,x2,y2

  Tip: In GIMP, hover over each instrument corner and read the
  pixel coordinates from the bottom-left status bar.
    """)
    print("  Opening overhead snapshot...")

    zones: dict[str, tuple[int, int, int, int]] = {}

    for name in ("turntable", "pads", "mixer", "keyboard"):
        current = {
            "turntable": (0, 100, 400, 550),
            "pads": (400, 150, 800, 500),
            "mixer": (300, 0, 550, 200),
            "keyboard": (800, 300, 1280, 600),
        }[name]

        resp = prompt(f"Zone '{name}' — enter x1,y1,x2,y2 (or Enter to keep {current}):")
        if resp:
            parts = [int(x.strip()) for x in resp.split(",")]
            if len(parts) == 4:
                zones[name] = tuple(parts)  # type: ignore[assignment]
            else:
                print(f"  Invalid format. Keeping {current}")
                zones[name] = current
        else:
            zones[name] = current

    TUNED["OVERHEAD_ZONES"] = zones
    print("\n  Zone configuration:")
    for name, coords in zones.items():
        print(f"    {name}: {coords}")


def step_8_summary():
    """Step 8: Show summary and write calibration file."""
    print("\n" + "=" * 70)
    print("CALIBRATION SUMMARY")
    print("=" * 70)

    print("\n  Tuned values:")
    for key, val in TUNED.items():
        if key == "OVERHEAD_ZONES":
            print(f"    {key}:")
            for name, coords in val.items():
                print(f"      {name}: {coords}")
        else:
            print(f"    {key} = {val}")

    # Compare with all activity recordings
    print("\n  Activity separation:")
    activities = ["silence", "typing", "tapping", "drumming", "scratching"]
    print(
        f"  {'Activity':<12} {'RMS mean':>10} {'RMS p95':>10} {'Centroid':>10} {'Onset/s':>10} {'Autocorr':>10}"
    )
    print(f"  {'-' * 12} {'-' * 10} {'-' * 10} {'-' * 10} {'-' * 10} {'-' * 10}")
    for name in activities:
        if name in RECORDINGS:
            s = RECORDINGS[name]
            print(
                f"  {name:<12} {s.rms_mean:>10.5f} {s.rms_p95:>10.5f} "
                f"{s.centroid_mean:>10.1f} {s.onset_rate:>10.1f} {s.autocorr_mean:>10.3f}"
            )

    # Write to YAML
    output_path = Path.home() / ".cache" / "hapax-voice" / "calibration.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Convert OVERHEAD_ZONES to serializable format
    output = {}
    for key, val in TUNED.items():
        if key == "OVERHEAD_ZONES":
            output[key] = {name: list(coords) for name, coords in val.items()}
        else:
            output[key] = val

    output["_calibrated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    output["_recordings"] = {
        name: {
            "rms_mean": s.rms_mean,
            "rms_p95": s.rms_p95,
            "rms_max": s.rms_max,
            "centroid_mean": s.centroid_mean,
            "onset_rate": s.onset_rate,
            "autocorr_mean": s.autocorr_mean,
            "autocorr_p95": s.autocorr_p95,
            "duration_s": s.duration_s,
        }
        for name, s in RECORDINGS.items()
    }

    output_path.write_text(json.dumps(output, indent=2) + "\n")
    print(f"\n  Calibration saved to: {output_path}")

    print("""
  NEXT STEPS:
    1. Review the calibration file
    2. Apply to source code:
       - contact_mic.py constants (lines 37-55)
       - cameras.py OVERHEAD_ZONES
    3. Restart hapax-voice to pick up new values
    4. Monitor perception-state.json during a production session
    5. Re-run this script if classifications feel wrong
    """)


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    print("""
╔══════════════════════════════════════════════════════════════════════╗
║            CONTACT MICROPHONE CALIBRATION WIZARD                   ║
║                                                                    ║
║  This wizard records real data from your contact mic and computes  ║
║  optimal thresholds for activity classification.                   ║
║                                                                    ║
║  Steps:                                                            ║
║    1. Silence (noise floor)           ~15s                         ║
║    2. Typing                          ~20s                         ║
║    3. Pad tapping (light)             ~20s                         ║
║    4. Hard drumming                   ~20s                         ║
║    5. Vinyl scratching                ~30s                         ║
║    6. Gesture timing test             ~15s                         ║
║    7. Overhead camera zones           manual                       ║
║    8. Summary + save                                               ║
║                                                                    ║
║  Total time: ~3-5 minutes                                          ║
╚══════════════════════════════════════════════════════════════════════╝
    """)

    # Check PipeWire source exists
    try:
        import subprocess

        result = subprocess.run(
            ["pw-cli", "ls", "Node"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if "contact_mic" not in result.stdout:
            print("  WARNING: 'contact_mic' PipeWire node not found.")
            print("  The contact mic must be connected and PipeWire configured.")
            if not confirm("Continue anyway?"):
                sys.exit(1)
    except Exception:
        print("  WARNING: Could not check PipeWire nodes.")

    step_1_silence()
    step_2_typing()
    step_3_tapping()
    step_4_drumming()
    step_5_scratching()
    step_6_gestures()
    step_7_zones()
    step_8_summary()

    print("\n  Calibration complete.\n")


if __name__ == "__main__":
    main()
