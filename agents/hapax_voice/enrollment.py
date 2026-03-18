"""Voice enrollment — multi-sample speaker embedding for operator identification.

Records multiple voice samples at varied energy/pitch, extracts embeddings
via pyannote, averages them for a robust operator voice profile. Also
captures face embedding from the BRIO camera for consistent ReID.

Usage:
    python -m agents.hapax_voice.enrollment
    # Follow the prompts — speak naturally for each sample
    # Takes ~2 minutes total

Output:
    ~/.local/share/hapax-voice/speaker_embedding.npy  (pyannote, averaged)
    ~/.local/share/hapax-voice/operator_face.npy      (insightface, refreshed)
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

ENROLLMENT_DIR = Path.home() / ".local" / "share" / "hapax-voice"
SPEAKER_EMBEDDING_PATH = ENROLLMENT_DIR / "speaker_embedding.npy"
FACE_EMBEDDING_PATH = ENROLLMENT_DIR / "operator_face.npy"
SAMPLE_RATE = 16000
SAMPLE_DURATION_S = 5  # seconds per sample


def record_audio(duration_s: float, source: str | None = None) -> np.ndarray:
    """Record audio from the default or specified mic."""
    import pyaudio

    pa = pyaudio.PyAudio()
    device_idx = None

    if source:
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            if source in str(info.get("name", "")):
                device_idx = i
                break

    stream = pa.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=SAMPLE_RATE,
        input=True,
        input_device_index=device_idx,
        frames_per_buffer=1024,
    )

    frames = []
    num_frames = int(SAMPLE_RATE / 1024 * duration_s)
    for _ in range(num_frames):
        data = stream.read(1024, exception_on_overflow=False)
        frames.append(data)

    stream.stop_stream()
    stream.close()
    pa.terminate()

    audio = b"".join(frames)
    samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
    return samples


def extract_speaker_embedding(audio: np.ndarray) -> np.ndarray | None:
    """Extract speaker embedding via pyannote."""
    try:
        from agents.hapax_voice.speaker_id import SpeakerIdentifier

        # Use a temporary identifier just for embedding extraction
        identifier = SpeakerIdentifier.__new__(SpeakerIdentifier)
        identifier._model = None
        identifier._enrollment_embedding = None

        # Load model
        from pyannote.audio import Inference, Model

        model = Model.from_pretrained(
            "pyannote/embedding",
            use_auth_token=True,
        )
        inference = Inference(model, window="whole")

        # Create a temporary wav-like input
        import torch

        waveform = torch.from_numpy(audio).unsqueeze(0)
        embedding = inference({"waveform": waveform, "sample_rate": SAMPLE_RATE})
        return np.array(embedding)

    except Exception as e:
        log.warning("Failed to extract speaker embedding: %s", e)

        # Fallback: use the existing SpeakerIdentifier
        try:
            from agents.hapax_voice.speaker_id import SpeakerIdentifier

            si = SpeakerIdentifier.__new__(SpeakerIdentifier)
            si._model = None
            si._enrollment_embedding = None
            emb = si.extract_embedding(audio, SAMPLE_RATE)
            return emb
        except Exception:
            return None


def enroll_face() -> bool:
    """Capture and save operator face embedding from BRIO camera."""
    try:
        import cv2

        from agents.hapax_voice.face_detector import FaceDetector

        shm = Path("/dev/shm/hapax-compositor/brio-operator.jpg")
        if not shm.exists():
            print("  No BRIO frame available — skipping face enrollment")
            return False

        det = FaceDetector(min_confidence=0.3)
        raw = shm.read_bytes()
        arr = np.frombuffer(raw, dtype=np.uint8)
        image = cv2.imdecode(arr, cv2.IMREAD_COLOR)

        success = det.enroll_operator(image)
        if success:
            print("  Face enrolled from BRIO camera")
        else:
            print("  No face detected in BRIO frame — try facing the camera")
        return success

    except Exception as e:
        print(f"  Face enrollment failed: {e}")
        return False


PROMPTS = [
    "Speak naturally — tell me about what you're working on today.",
    "Now a bit quieter — like you're thinking out loud to yourself.",
    "Now louder — like you're calling across the room.",
    "Read this sentence: 'Hey Hapax, what's the weather like today?'",
    "Say any numbers — count from one to twenty at your normal pace.",
    "Just ramble — talk about anything for a few seconds.",
    "Whisper something — any sentence, very quiet.",
    "Normal voice again — describe what's on your desk right now.",
    "Speak quickly — like you're excited about something.",
    "Last one — say 'Hapax' a few different ways. Slow, fast, loud, quiet.",
]


def main() -> None:
    """Interactive enrollment session."""
    print()
    print("═══════════════════════════════════════════════════")
    print("  HAPAX VOICE ENROLLMENT")
    print("  Multi-sample speaker embedding + face capture")
    print("═══════════════════════════════════════════════════")
    print()
    print("  Mic: Blue Yeti (default source)")
    print(f"  Samples: {len(PROMPTS)} × {SAMPLE_DURATION_S}s each")
    print(f"  Total: ~{len(PROMPTS) * (SAMPLE_DURATION_S + 3)}s")
    print()

    ENROLLMENT_DIR.mkdir(parents=True, exist_ok=True)

    # Face enrollment first (while mic warms up)
    print("── Face Enrollment ─────────────────────────────────")
    print("  Look at the BRIO camera...")
    enroll_face()
    print()

    # Voice enrollment
    print("── Voice Enrollment ────────────────────────────────")
    print("  I'll record 10 samples. Each one is 5 seconds.")
    print("  Speak into the Blue Yeti for each prompt.")
    print()

    embeddings = []

    for i, prompt in enumerate(PROMPTS):
        print(f"  [{i + 1}/{len(PROMPTS)}] {prompt}")
        input("  Press Enter when ready, then speak...")

        print(f"  Recording {SAMPLE_DURATION_S}s...", end="", flush=True)
        audio = record_audio(SAMPLE_DURATION_S)

        # Check audio level
        rms = np.sqrt(np.mean(audio**2))
        if rms < 0.005:
            print(f" ⚠ Very quiet (RMS={rms:.4f}) — try again?")
        else:
            print(f" ✓ (RMS={rms:.3f})")

        # Extract embedding
        emb = extract_speaker_embedding(audio)
        if emb is not None:
            embeddings.append(emb)
            print(f"  Embedding extracted ({emb.shape})")
        else:
            print("  ⚠ Failed to extract embedding — skipping this sample")

        print()

    if not embeddings:
        print("ERROR: No embeddings extracted. Check pyannote/HF_TOKEN.")
        sys.exit(1)

    # Average embeddings
    avg_embedding = np.mean(embeddings, axis=0)

    # Normalize
    norm = np.linalg.norm(avg_embedding)
    if norm > 0:
        avg_embedding = avg_embedding / norm

    # Save
    np.save(SPEAKER_EMBEDDING_PATH, avg_embedding)
    print("═══════════════════════════════════════════════════")
    print(f"  ✓ Speaker embedding saved: {SPEAKER_EMBEDDING_PATH}")
    print(f"    Averaged from {len(embeddings)} samples")
    print(f"    Shape: {avg_embedding.shape}")
    print(f"  ✓ Face embedding: {FACE_EMBEDDING_PATH}")
    print("═══════════════════════════════════════════════════")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    main()
