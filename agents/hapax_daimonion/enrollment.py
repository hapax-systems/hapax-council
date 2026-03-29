"""Voice enrollment — multi-sample speaker embedding for operator identification.

Records multiple voice samples at varied energy/pitch, extracts embeddings
via pyannote, averages them for a robust operator voice profile. Also
captures face embedding from the BRIO camera for consistent ReID.

Usage:
    python -m agents.hapax_daimonion.enrollment
    # Follow the prompts — speak naturally for each sample
    # Takes ~2 minutes total

Output:
    ~/.local/share/hapax-daimonion/speaker_embedding.npy  (pyannote, averaged)
    ~/.local/share/hapax-daimonion/operator_face.npy      (insightface, refreshed)
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

ENROLLMENT_DIR = Path.home() / ".local" / "share" / "hapax-daimonion"
SPEAKER_EMBEDDING_PATH = ENROLLMENT_DIR / "speaker_embedding.npy"
FACE_EMBEDDING_PATH = ENROLLMENT_DIR / "operator_face.npy"
SAMPLE_RATE = 16000
SAMPLE_DURATION_S = 5  # seconds per sample
ENROLLMENT_REPORT_PATH = ENROLLMENT_DIR / "enrollment_report.json"


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two vectors, handling zero norms."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def compute_pairwise_similarity(embeddings: list[np.ndarray]) -> dict[str, float]:
    """Compute pairwise cosine similarity statistics across all embedding pairs.

    Returns dict with keys: min, max, mean, stddev.
    """
    sims: list[float] = []
    n = len(embeddings)
    for i in range(n):
        for j in range(i + 1, n):
            sims.append(_cosine_similarity(embeddings[i], embeddings[j]))
    arr = np.array(sims)
    return {
        "min": float(arr.min()),
        "max": float(arr.max()),
        "mean": float(arr.mean()),
        "stddev": float(arr.std()),
    }


def detect_outliers(embeddings: list[np.ndarray], threshold: float = 0.50) -> list[int]:
    """Detect outlier embeddings by mean pairwise similarity below threshold.

    Returns list of indices where the embedding's mean similarity to all
    others falls below the threshold.
    """
    n = len(embeddings)
    outliers: list[int] = []
    for i in range(n):
        sims = [_cosine_similarity(embeddings[i], embeddings[j]) for j in range(n) if j != i]
        if np.mean(sims) < threshold:
            outliers.append(i)
    return outliers


def threshold_test(
    embeddings: list[np.ndarray],
    averaged: np.ndarray,
    accept_threshold: float = 0.60,
) -> dict[str, float | int]:
    """Test each embedding's similarity to the averaged embedding.

    Returns dict with keys: accept_threshold, samples_below_threshold,
    min_similarity_to_average.
    """
    sims = [_cosine_similarity(e, averaged) for e in embeddings]
    below = sum(1 for s in sims if s < accept_threshold)
    return {
        "accept_threshold": accept_threshold,
        "samples_below_threshold": below,
        "min_similarity_to_average": float(min(sims)),
    }


def write_stability_report(
    embeddings: list[np.ndarray],
    averaged: np.ndarray,
    report_path: Path | None = None,
    dropped_count: int = 0,
) -> None:
    """Compute and save a JSON enrollment stability report."""
    if report_path is None:
        report_path = ENROLLMENT_REPORT_PATH

    pairwise = compute_pairwise_similarity(embeddings)
    thresh = threshold_test(embeddings, averaged)

    report = {
        "timestamp": datetime.now(UTC).isoformat(),
        "sample_count": len(embeddings),
        "dropped_count": dropped_count,
        "pairwise": pairwise,
        "threshold": thresh,
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2))


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
        from agents.hapax_daimonion.speaker_id import SpeakerIdentifier

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
            from agents.hapax_daimonion.speaker_id import SpeakerIdentifier

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

        from agents.hapax_daimonion.face_detector import FaceDetector

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

    # ── Validation phase ─────────────────────────────────
    print("── Validation ──────────────────────────────────────")
    dropped_count = 0
    outlier_indices = detect_outliers(embeddings, threshold=0.50)
    if outlier_indices:
        print(f"  Found {len(outlier_indices)} potential outlier(s):")
        # Process in reverse so removal doesn't shift indices
        for idx in sorted(outlier_indices, reverse=True):
            answer = input(f"  Drop sample {idx + 1}? [y/N] ").strip().lower()
            if answer == "y":
                embeddings.pop(idx)
                dropped_count += 1
                print(f"  Dropped sample {idx + 1}")
        print()

    if not embeddings:
        print("ERROR: All embeddings dropped. Re-run enrollment.")
        sys.exit(1)

    # Average remaining embeddings
    avg_embedding = np.mean(embeddings, axis=0)

    # Normalize
    norm = np.linalg.norm(avg_embedding)
    if norm > 0:
        avg_embedding = avg_embedding / norm

    # Write stability report
    write_stability_report(embeddings, avg_embedding, dropped_count=dropped_count)
    print(f"  Stability report: {ENROLLMENT_REPORT_PATH}")

    # Print pairwise stats
    pairwise = compute_pairwise_similarity(embeddings)
    print(
        f"  Pairwise similarity: mean={pairwise['mean']:.3f} "
        f"stddev={pairwise['stddev']:.3f} "
        f"min={pairwise['min']:.3f} max={pairwise['max']:.3f}"
    )
    if pairwise["mean"] < 0.70:
        print("  ⚠ WARNING: Mean pairwise similarity < 0.70 — enrollment may be noisy")
    if pairwise["stddev"] > 0.10:
        print("  ⚠ WARNING: High stddev > 0.10 — inconsistent samples")

    # Print threshold test
    thresh = threshold_test(embeddings, avg_embedding, accept_threshold=0.60)
    print(
        f"  Threshold test: {thresh['samples_below_threshold']} samples below "
        f"{thresh['accept_threshold']:.2f}, min similarity={thresh['min_similarity_to_average']:.3f}"
    )
    print()

    # Save
    np.save(SPEAKER_EMBEDDING_PATH, avg_embedding)
    print("═══════════════════════════════════════════════════")
    print(f"  ✓ Speaker embedding saved: {SPEAKER_EMBEDDING_PATH}")
    print(f"    Averaged from {len(embeddings)} samples ({dropped_count} dropped)")
    print(f"    Shape: {avg_embedding.shape}")
    print(f"  ✓ Face embedding: {FACE_EMBEDDING_PATH}")
    print("═══════════════════════════════════════════════════")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    main()
