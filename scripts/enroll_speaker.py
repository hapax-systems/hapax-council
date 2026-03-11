#!/usr/bin/env python3
"""Enroll operator voice for the Hapax Voice speaker identification system.

Records audio samples via PipeWire (parecord), extracts speaker embeddings
using pyannote.audio, and saves a reference embedding for runtime speaker ID.

Usage:
    cd ~/projects/ai-agents
    uv run python scripts/enroll_speaker.py [--samples N] [--duration S] [--output PATH]

Requires HF_TOKEN in environment (for pyannote model access).
"""
from __future__ import annotations

import argparse
import io
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

# Ensure the agents package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.hapax_voice.speaker_id import SpeakerIdentifier

DEFAULT_OUTPUT = Path.home() / ".local" / "share" / "hapax-voice" / "speaker_embedding.npy"
SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit


def record_audio(duration_s: int) -> np.ndarray:
    """Record audio via parecord and return as float32 numpy array.

    Uses parecord (PulseAudio compat layer over PipeWire) to capture
    mono 16kHz 16-bit audio from the default source.
    """
    cmd = [
        "parecord",
        "--rate", str(SAMPLE_RATE),
        "--channels", str(CHANNELS),
        "--format", "s16le",
        "--raw",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=duration_s + 2,  # small grace period
            check=False,
        )
    except FileNotFoundError:
        print("ERROR: parecord not found. Install pulseaudio-utils:")
        print("  sudo apt install pulseaudio-utils")
        sys.exit(1)
    except subprocess.TimeoutExpired as exc:
        # TimeoutExpired still captures partial stdout
        raw_bytes = exc.stdout or b""
        if not raw_bytes:
            print("ERROR: parecord timed out with no audio data.")
            sys.exit(1)
        return _raw_to_float32(raw_bytes)

    if proc.returncode != 0 and not proc.stdout:
        print(f"ERROR: parecord failed (exit {proc.returncode})")
        if proc.stderr:
            print(proc.stderr.decode(errors="replace"))
        sys.exit(1)

    return _raw_to_float32(proc.stdout)


def _raw_to_float32(raw_bytes: bytes) -> np.ndarray:
    """Convert raw s16le bytes to float32 numpy array."""
    audio_i16 = np.frombuffer(raw_bytes, dtype=np.int16)
    return audio_i16.astype(np.float32) / 32768.0


def check_audio_quality(audio: np.ndarray, sample_rate: int) -> tuple[bool, str]:
    """Basic sanity checks on recorded audio."""
    duration = len(audio) / sample_rate
    if duration < 1.0:
        return False, f"Too short ({duration:.1f}s). Need at least 1 second of audio."

    rms = float(np.sqrt(np.mean(audio**2)))
    if rms < 0.005:
        return False, f"Audio is nearly silent (RMS={rms:.4f}). Check your microphone."

    peak = float(np.max(np.abs(audio)))
    if peak > 0.99:
        return False, "Audio is clipping. Move further from the mic or lower gain."

    return True, f"OK (duration={duration:.1f}s, RMS={rms:.3f}, peak={peak:.3f})"


def prompt_yn(question: str) -> bool:
    """Prompt yes/no and return bool."""
    while True:
        ans = input(f"{question} [y/n]: ").strip().lower()
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enroll operator voice for Hapax Voice speaker identification."
    )
    parser.add_argument(
        "--samples", type=int, default=3,
        help="Number of voice samples to record and average (default: 3)",
    )
    parser.add_argument(
        "--duration", type=int, default=5,
        help="Duration of each recording in seconds (default: 5)",
    )
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT,
        help=f"Path to save the embedding (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  Hapax Voice — Speaker Enrollment")
    print("=" * 60)
    print()
    print(f"  Samples to record : {args.samples}")
    print(f"  Duration each     : {args.duration}s")
    print(f"  Output            : {args.output}")
    print()

    # Pre-flight: check HF_TOKEN
    import os
    if not os.environ.get("HF_TOKEN"):
        print("WARNING: HF_TOKEN not set. The pyannote embedding model requires a")
        print("Hugging Face token with access to pyannote/embedding.")
        print("Set it with: export HF_TOKEN=$(pass show api/huggingface)")
        print()
        if not prompt_yn("Continue anyway?"):
            sys.exit(0)

    # Pre-flight: check parecord works
    print("Checking audio capture...")
    try:
        subprocess.run(
            ["parecord", "--help"],
            capture_output=True, check=False, timeout=5,
        )
        print("  parecord: OK")
    except FileNotFoundError:
        print("  parecord: NOT FOUND")
        print("  Install with: sudo apt install pulseaudio-utils")
        sys.exit(1)

    # Initialize speaker identifier (loads pyannote model)
    print()
    print("Loading pyannote embedding model (first load downloads ~80MB)...")
    identifier = SpeakerIdentifier()

    # Verify model loaded by attempting a dummy extraction
    dummy = np.zeros(SAMPLE_RATE, dtype=np.float32)  # 1s silence
    test_emb = identifier.extract_embedding(dummy, SAMPLE_RATE)
    if test_emb is None:
        print()
        print("ERROR: Could not load pyannote embedding model.")
        print("Check that HF_TOKEN is set and has access to pyannote/embedding.")
        sys.exit(1)
    embedding_dim = test_emb.shape[-1]
    print(f"  Model loaded. Embedding dimension: {embedding_dim}")

    # Record samples
    embeddings: list[np.ndarray] = []
    sample_num = 0

    while sample_num < args.samples:
        print()
        print(f"--- Sample {sample_num + 1} of {args.samples} ---")
        print(f"Speak naturally for {args.duration} seconds when recording starts.")
        print("Read something aloud or talk about your day — varied speech is best.")
        print()
        input("Press ENTER to start recording...")

        print(f"  Recording for {args.duration}s...")
        audio = record_audio(args.duration)

        ok, msg = check_audio_quality(audio, SAMPLE_RATE)
        print(f"  Quality check: {msg}")

        if not ok:
            print("  Discarding sample.")
            if not prompt_yn("  Retry this sample?"):
                print("Enrollment cancelled.")
                sys.exit(1)
            continue

        # Extract embedding
        print("  Extracting embedding...")
        embedding = identifier.extract_embedding(audio, SAMPLE_RATE)
        if embedding is None:
            print("  ERROR: Embedding extraction returned None. Skipping.")
            continue

        embeddings.append(embedding.flatten())
        sample_num += 1
        print(f"  Sample {sample_num} captured.")

    # Average embeddings for robustness
    print()
    print(f"Averaging {len(embeddings)} embeddings...")
    stacked = np.stack(embeddings)
    averaged = np.mean(stacked, axis=0)

    # Report inter-sample consistency
    if len(embeddings) > 1:
        from agents.hapax_voice.speaker_id import _cosine_similarity
        sims = []
        for i in range(len(embeddings)):
            for j in range(i + 1, len(embeddings)):
                sims.append(_cosine_similarity(embeddings[i], embeddings[j]))
        min_sim = min(sims)
        avg_sim = sum(sims) / len(sims)
        print(f"  Inter-sample similarity: min={min_sim:.3f}, avg={avg_sim:.3f}")
        if min_sim < 0.6:
            print("  WARNING: Low inter-sample similarity. Samples may include")
            print("  different speakers or noisy recordings. Consider re-enrolling.")

    # Save
    args.output.parent.mkdir(parents=True, exist_ok=True)
    identifier.enroll(averaged, args.output)

    print()
    print("=" * 60)
    print(f"  Enrollment complete.")
    print(f"  Saved to: {args.output}")
    print("=" * 60)

    # Verify by loading it back
    loaded = np.load(args.output)
    verify_sim = _cosine_similarity(
        averaged / (np.linalg.norm(averaged) or 1.0),
        loaded,
    )
    print(f"  Verification (reload similarity): {verify_sim:.4f}")


if __name__ == "__main__":
    main()
