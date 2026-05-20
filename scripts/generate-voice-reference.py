#!/usr/bin/env python3
"""Generate Chatterbox voice reference from Kokoro with formant processing.

Pipeline: Kokoro af_heart → +3 semitone pitch shift → 1.5–3 kHz bandpass → normalize
Output: profiles/voice-sample.wav (24 kHz, mono, 16-bit PCM)
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import numpy as np

SAMPLE_RATE = 24000
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "profiles" / "voice-sample.wav"
REFERENCE_TEXT = (
    "The signal arrives before the meaning. "
    "Structure precedes interpretation. "
    "What you hear is not a voice but a carrier wave "
    "shaped by the space it passes through."
)


def synthesize_kokoro(text: str) -> np.ndarray:
    from kokoro import KPipeline

    pipeline = KPipeline(lang_code="a", device="cpu")
    chunks: list[np.ndarray] = []
    for _g, _p, audio in pipeline(text, voice="af_heart", speed=0.95):
        if audio is not None:
            if hasattr(audio, "numpy"):
                audio = audio.numpy()
            chunks.append(np.asarray(audio, dtype=np.float32))
    if not chunks:
        raise RuntimeError("Kokoro produced no audio")
    return np.concatenate(chunks)


def write_wav(path: Path, audio: np.ndarray, rate: int) -> None:
    from scipy.io import wavfile

    pcm = (audio * 32768).clip(-32768, 32767).astype(np.int16)
    wavfile.write(str(path), rate, pcm)


def apply_sox_processing(input_path: Path, output_path: Path) -> None:
    subprocess.run(
        [
            "sox",
            str(input_path),
            str(output_path),
            "pitch",
            "300",
            "sinc",
            "1500-3000",
            "norm",
            "-1",
        ],
        check=True,
        capture_output=True,
    )


def main() -> None:
    print("Synthesizing reference text with Kokoro af_heart...")
    raw_audio = synthesize_kokoro(REFERENCE_TEXT)
    print(f"  {len(raw_audio)} samples ({len(raw_audio) / SAMPLE_RATE:.1f}s)")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        raw_path = Path(tmp.name)

    write_wav(raw_path, raw_audio, SAMPLE_RATE)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    print("Applying formant processing: pitch +3 semitones, bandpass 1.5-3kHz, normalize...")
    apply_sox_processing(raw_path, OUTPUT_PATH)

    raw_path.unlink(missing_ok=True)
    print(f"  Output: {OUTPUT_PATH}")
    print(f"  Size: {OUTPUT_PATH.stat().st_size} bytes")


if __name__ == "__main__":
    main()
