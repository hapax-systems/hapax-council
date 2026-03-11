#!/usr/bin/env python3
"""Record real wake word utterances for training.

Interactive script: press Enter to record each utterance, 'q' to quit.
Saves 16kHz mono int16 WAV files to data/wake-word-training/positive/real/.

Usage:
    cd ~/projects/ai-agents
    uv run python scripts/record_wake_word.py
    uv run python scripts/record_wake_word.py --count 50
    uv run python scripts/record_wake_word.py --output-dir /path/to/dir
"""

from __future__ import annotations

import argparse
import logging
import wave
from pathlib import Path

import numpy as np
import pyaudio

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
CHANNELS = 1
FORMAT = pyaudio.paInt16
CHUNK = 1024
RECORD_SECONDS = 2.0
OUTPUT_DIR = (
    Path(__file__).resolve().parent.parent / "data" / "wake-word-training" / "positive" / "real"
)


def record_one(pa: pyaudio.PyAudio, duration: float = RECORD_SECONDS) -> np.ndarray:
    """Record a single utterance and return int16 numpy array."""
    stream = pa.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=SAMPLE_RATE,
        input=True,
        frames_per_buffer=CHUNK,
    )
    frames: list[bytes] = []
    n_chunks = int(SAMPLE_RATE / CHUNK * duration)
    for _ in range(n_chunks):
        data = stream.read(CHUNK, exception_on_overflow=False)
        frames.append(data)
    stream.stop_stream()
    stream.close()
    return np.frombuffer(b"".join(frames), dtype=np.int16)


def save_wav(audio: np.ndarray, path: Path) -> None:
    """Save int16 audio as 16kHz mono WAV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio.tobytes())


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description="Record wake word utterances")
    parser.add_argument("--count", type=int, default=50, help="Target number of recordings")
    parser.add_argument(
        "--duration", type=float, default=RECORD_SECONDS, help="Seconds per recording"
    )
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR, help="Output directory")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    existing_files = list(args.output_dir.glob("real_*.wav"))
    existing = len(existing_files)
    if existing_files:
        start_idx = max(int(f.stem.split("_")[1]) for f in existing_files) + 1
    else:
        start_idx = 0

    pa = pyaudio.PyAudio()
    print("\n=== Wake Word Recording Tool ===")
    print(f"Say 'hapax' after each prompt. {args.duration}s recording window.")
    print(f"Target: {args.count} recordings (existing: {existing})")
    print(f"Output: {args.output_dir}")
    print("Press Enter to record, 'q' to quit, 's' to skip/discard last.\n")

    idx = start_idx
    last_path: Path | None = None

    try:
        while idx < start_idx + args.count:
            response = input(
                f"  [{idx + 1}] Press Enter to record ('q' quit, 's' skip last): "
            ).strip()
            if response.lower() == "q":
                break
            if response.lower() == "s" and last_path and last_path.exists():
                last_path.unlink()
                idx -= 1
                print(f"       Deleted {last_path.name}")
                last_path = None
                continue

            print("       Recording...", end="", flush=True)
            audio = record_one(pa, args.duration)
            out_path = args.output_dir / f"real_{idx:05d}.wav"
            save_wav(audio, out_path)
            last_path = out_path
            idx += 1

            peak = np.abs(audio).max()
            if peak < 500:
                quality = "(very quiet -- speak louder or move closer)"
            elif peak < 2000:
                quality = "(quiet)"
            else:
                quality = "(good)"
            print(f" saved {out_path.name}  peak={peak} {quality}")

    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        pa.terminate()

    total = len(list(args.output_dir.glob("*.wav")))
    print(f"\nDone. {total} recordings in {args.output_dir}")


if __name__ == "__main__":
    main()
