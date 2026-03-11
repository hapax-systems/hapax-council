# Wake Word Training Improvements Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Improve the hapax wake word model quality by adding real voice recordings, post-synthesis audio augmentation, and better training methodology.

**Architecture:** Extend the existing `scripts/train_wake_word.py` pipeline with three new capabilities: (1) a recording script to capture real operator utterances, (2) an audio augmentation stage using the already-installed `audiomentations` library applied during feature extraction, and (3) training improvements (more positive samples, better validation). The model architecture and ONNX export format remain unchanged — `(batch, 96)` input, which is correct for openwakeword custom models. No changes to `wake_word.py` inference code.

**Tech Stack:** Python, audiomentations (v0.43.1, already installed), PyAudio (already installed), openwakeword, torch, onnxruntime

**Current state of training data:**
- 3510 positive features (3498 piper-sample-generator + 12 chatterbox)
- 57 TTS-generated negative clips
- 17GB pre-computed negative features (2000 hours, from HuggingFace)
- Model: DNN `(batch, 96)` — LayerNorm — Linear/ReLU x 2 — Sigmoid — ONNX
- Training script: `scripts/train_wake_word.py` (1282 lines)
- Inference: `agents/hapax_voice/wake_word.py` (119 lines)

---

### Task 1: Voice Recording Script

Create a simple interactive script to record the operator saying "hapax" ~50 times.

**Files:**
- Create: `scripts/record_wake_word.py`
- Test: manual (interactive recording tool — no unit test needed)

**Step 1: Create the recording script**

```python
#!/usr/bin/env python3
"""Record real wake word utterances for training.

Interactive script: press Enter to record each utterance, 'q' to quit.
Saves 16kHz mono int16 WAV files to data/wake-word-training/positive/real/.

Usage:
    cd ~/projects/hapax-council
    uv run python scripts/record_wake_word.py
    uv run python scripts/record_wake_word.py --count 50  # target count
    uv run python scripts/record_wake_word.py --output-dir /path/to/dir
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
import wave
from pathlib import Path

import numpy as np
import pyaudio

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
CHANNELS = 1
FORMAT = pyaudio.paInt16
CHUNK = 1024
RECORD_SECONDS = 2.0  # Each utterance recording length
OUTPUT_DIR = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "wake-word-training"
    / "positive"
    / "real"
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
    parser.add_argument("--duration", type=float, default=RECORD_SECONDS, help="Seconds per recording")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR, help="Output directory")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    existing = len(list(args.output_dir.glob("*.wav")))

    pa = pyaudio.PyAudio()
    print(f"\n=== Wake Word Recording Tool ===")
    print(f"Say 'hapax' after each prompt. {args.duration}s recording window.")
    print(f"Target: {args.count} recordings (existing: {existing})")
    print(f"Output: {args.output_dir}")
    print(f"Press Enter to record, 'q' to quit, 's' to skip/discard last.\n")

    idx = existing
    last_path: Path | None = None

    try:
        while idx < existing + args.count:
            response = input(f"  [{idx + 1}] Press Enter to record ('q' quit, 's' skip last): ").strip()
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

            # Show peak amplitude as simple quality indicator
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
```

**Step 2: Test the script runs without errors**

Run: `cd ~/projects/hapax-council && uv run python scripts/record_wake_word.py --count 2 --duration 1.0`
Expected: Interactive prompt, records 2 short clips, saves to `data/wake-word-training/positive/real/`

**Step 3: Commit**

```bash
git add scripts/record_wake_word.py
git commit -m "feat(voice): add interactive wake word recording script"
```

---

### Task 2: Add Audio Augmentation to Feature Extraction

Add a post-synthesis augmentation stage that creates multiple augmented variants of each positive sample before feature extraction. This uses `audiomentations` which is already installed.

**Files:**
- Modify: `scripts/train_wake_word.py:722-823` (extract_features_from_clips)
- Create: `tests/hapax_voice/test_wake_word_augmentation.py`

**Step 1: Write the failing test**

```python
"""Tests for wake word audio augmentation pipeline."""
from __future__ import annotations

import numpy as np
import pytest


def test_build_augmentation_pipeline_returns_compose():
    """build_augmentation_pipeline returns an audiomentations Compose."""
    from scripts.train_wake_word import build_augmentation_pipeline

    pipeline = build_augmentation_pipeline()
    assert pipeline is not None
    from audiomentations import Compose
    assert isinstance(pipeline, Compose)


def test_augment_clips_increases_sample_count():
    """augment_clips produces more clips than input."""
    from scripts.train_wake_word import augment_clips

    clips = [np.random.randint(-1000, 1000, size=8000, dtype=np.int16) for _ in range(3)]
    augmented = augment_clips(clips, n_augmented_per_clip=4)
    # originals (3) + augmented (3 * 4 = 12) = 15
    assert len(augmented) == 15


def test_augment_clips_preserves_dtype():
    """Augmented clips are int16 at 16kHz."""
    from scripts.train_wake_word import augment_clips

    clips = [np.random.randint(-1000, 1000, size=8000, dtype=np.int16)]
    augmented = augment_clips(clips, n_augmented_per_clip=2)
    for clip in augmented:
        assert clip.dtype == np.int16


def test_augment_clips_zero_augments_returns_originals():
    """With n_augmented_per_clip=0, returns originals only."""
    from scripts.train_wake_word import augment_clips

    clips = [np.random.randint(-1000, 1000, size=8000, dtype=np.int16) for _ in range(5)]
    augmented = augment_clips(clips, n_augmented_per_clip=0)
    assert len(augmented) == 5
```

**Step 2: Run tests to verify they fail**

Run: `cd ~/projects/hapax-council && uv run pytest tests/hapax_voice/test_wake_word_augmentation.py -v`
Expected: FAIL with `ImportError` (functions don't exist yet)

**Step 3: Implement augmentation functions**

Add these two functions to `scripts/train_wake_word.py` after the `load_wav_16k` function (after line 218), before the TTS generators section:

```python
# ---------------------------------------------------------------------------
# Audio Augmentation
# ---------------------------------------------------------------------------

def build_augmentation_pipeline():
    """Build an audiomentations augmentation pipeline for wake word samples.

    Applies realistic acoustic variations: noise, room reverb, speed/pitch
    changes, and volume shifts. Each augmentation has a probability < 1.0
    so not every transform fires on every sample.
    """
    from audiomentations import (
        AddGaussianNoise,
        Compose,
        Gain,
        PitchShift,
        TimeStretch,
    )

    return Compose([
        AddGaussianNoise(min_amplitude=0.002, max_amplitude=0.015, p=0.5),
        TimeStretch(min_rate=0.85, max_rate=1.15, p=0.5),
        PitchShift(min_semitones=-3, max_semitones=3, p=0.4),
        Gain(min_gain_db=-6, max_gain_db=6, p=0.3),
    ])


def augment_clips(
    clips: list[np.ndarray],
    n_augmented_per_clip: int = 4,
    sample_rate: int = SAMPLE_RATE,
) -> list[np.ndarray]:
    """Augment a list of int16 audio clips.

    Returns originals + n_augmented_per_clip augmented variants per clip.
    """
    if n_augmented_per_clip == 0:
        return list(clips)

    pipeline = build_augmentation_pipeline()
    result = list(clips)  # Keep originals

    for clip in clips:
        # audiomentations expects float32 in [-1, 1]
        clip_float = clip.astype(np.float32) / 32768.0
        for _ in range(n_augmented_per_clip):
            augmented = pipeline(samples=clip_float, sample_rate=sample_rate)
            aug_int16 = np.clip(augmented * 32768, -32768, 32767).astype(np.int16)
            result.append(aug_int16)

    return result
```

**Step 4: Run tests to verify they pass**

Run: `cd ~/projects/hapax-council && uv run pytest tests/hapax_voice/test_wake_word_augmentation.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add scripts/train_wake_word.py tests/hapax_voice/test_wake_word_augmentation.py
git commit -m "feat(voice): add audio augmentation pipeline for wake word training"
```

---

### Task 3: Wire Augmentation into Feature Extraction

Modify `extract_features_from_clips` to augment positive clips before extracting features. This multiplies the effective positive sample count.

**Files:**
- Modify: `scripts/train_wake_word.py:722-823` (extract_features_from_clips)
- Modify: `scripts/train_wake_word.py:1108-1126` (run_full_pipeline extract step)

**Step 1: Write the failing test**

Add to `tests/hapax_voice/test_wake_word_augmentation.py`:

```python
def test_extract_features_accepts_augment_param():
    """extract_features_from_clips accepts augment_positive parameter."""
    import inspect
    from scripts.train_wake_word import extract_features_from_clips

    sig = inspect.signature(extract_features_from_clips)
    assert "augment_positive" in sig.parameters
```

**Step 2: Run test to verify it fails**

Run: `cd ~/projects/hapax-council && uv run pytest tests/hapax_voice/test_wake_word_augmentation.py::test_extract_features_accepts_augment_param -v`
Expected: FAIL (parameter doesn't exist yet)

**Step 3: Add augment_positive parameter to extract_features_from_clips**

Modify `extract_features_from_clips` signature (line 722) to add the parameter:

```python
def extract_features_from_clips(
    clips_dir: Path,
    output_path: Path,
    batch_size: int = 64,
    augment_positive: bool = False,
    n_augmented_per_clip: int = 4,
) -> np.ndarray:
```

After loading all WAV files and before feature extraction (after line 747, before line 748), add:

```python
    # Load all clips into memory for augmentation
    if augment_positive:
        log.info("Loading clips for augmentation ...")
        raw_clips = []
        for wav_path in wav_files:
            try:
                audio = load_wav_16k(wav_path)
                raw_clips.append(audio)
            except Exception as e:
                log.warning("Failed to load %s: %s", wav_path.name, e)

        log.info("Augmenting %d clips (x%d variants each) ...", len(raw_clips), n_augmented_per_clip)
        augmented_clips = augment_clips(raw_clips, n_augmented_per_clip=n_augmented_per_clip)
        log.info("Total clips after augmentation: %d", len(augmented_clips))
    else:
        augmented_clips = None
```

Then modify the main feature-extraction loop to use augmented clips when available. Replace the loop starting at line 752:

```python
    if augmented_clips is not None:
        total_clips = len(augmented_clips)
    else:
        total_clips = len(wav_files)

    for i in range(total_clips):
        if (i + 1) % 100 == 0:
            log.info("  Processing clip %d/%d ...", i + 1, total_clips)

        try:
            if augmented_clips is not None:
                audio = augmented_clips[i]
            else:
                audio = load_wav_16k(wav_files[i])
            # ... rest of feature extraction stays the same (pad/trim, melspec, embedding)
```

Finally, update the `run_full_pipeline` call at line 1110 to pass `augment_positive=True` for positive extraction:

```python
        pos_features = extract_features_from_clips(
            POSITIVE_DIR,
            FEATURES_DIR / "positive_features.npy",
            augment_positive=True,
            n_augmented_per_clip=4,
        )
```

**Step 4: Run test to verify it passes**

Run: `cd ~/projects/hapax-council && uv run pytest tests/hapax_voice/test_wake_word_augmentation.py -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add scripts/train_wake_word.py tests/hapax_voice/test_wake_word_augmentation.py
git commit -m "feat(voice): wire augmentation into feature extraction pipeline"
```

---

### Task 4: Add Real Voice Sample Weighting to Training

Real voice samples should be weighted higher than TTS samples during training. Modify the training loop to support sample weighting.

**Files:**
- Modify: `scripts/train_wake_word.py:830-1032` (train_model function)
- Modify: `scripts/train_wake_word.py:1108-1136` (run_full_pipeline)

**Step 1: Write the failing test**

Add to `tests/hapax_voice/test_wake_word_augmentation.py`:

```python
def test_train_model_accepts_real_weight_param():
    """train_model accepts real_sample_weight parameter."""
    import inspect
    from scripts.train_wake_word import train_model

    sig = inspect.signature(train_model)
    assert "real_sample_weight" in sig.parameters
```

**Step 2: Run test to verify it fails**

Run: `cd ~/projects/hapax-council && uv run pytest tests/hapax_voice/test_wake_word_augmentation.py::test_train_model_accepts_real_weight_param -v`
Expected: FAIL

**Step 3: Implement real sample weighting**

Add the parameter to `train_model` (line 830):

```python
def train_model(
    steps: int = 50000,
    learning_rate: float = 0.0001,
    max_negative_weight: int = 1500,
    n_per_class: int = 512,
    hidden_dim: int = 64,
    n_blocks: int = 2,
    real_sample_weight: float = 3.0,
) -> None:
```

After loading `pos_features` and reshaping (around line 885), add:

```python
    # Load real voice features if available and build sampling weights
    real_features_path = FEATURES_DIR / "real_features.npy"
    if real_features_path.exists():
        real_features = np.load(str(real_features_path))
        if real_features.ndim == 3:
            real_features = real_features.mean(axis=1)
        log.info("Real voice features: %s (weight: %.1fx)", real_features.shape, real_sample_weight)
        n_tts = len(pos_features)
        pos_features = np.concatenate([pos_features, real_features], axis=0)
        sample_weights = np.ones(len(pos_features), dtype=np.float64)
        sample_weights[n_tts:] = real_sample_weight
        sample_weights /= sample_weights.sum()
    else:
        sample_weights = None
        log.info("No real voice features found -- using TTS-only positive data")
```

Update the train/val split (around line 896) to also split the weights:

```python
    val_pos = pos_features[indices[:n_val]]
    train_pos = pos_features[indices[n_val:]]
    if sample_weights is not None:
        train_weights = sample_weights[indices[n_val:]]
        train_weights /= train_weights.sum()
    else:
        train_weights = None
```

Modify positive sampling in the training loop (around line 954):

```python
        if train_weights is not None:
            pos_idx = np.random.choice(len(train_pos), size=n_per_class, p=train_weights)
        else:
            pos_idx = np.random.randint(0, len(train_pos), size=n_per_class)
```

**Step 4: Add real feature extraction to the pipeline**

In `run_full_pipeline` (around line 1118), add after positive feature extraction:

```python
        # Extract real voice features separately (for weighted sampling)
        real_dir = POSITIVE_DIR / "real"
        if real_dir.exists() and any(real_dir.rglob("*.wav")):
            extract_features_from_clips(
                real_dir,
                FEATURES_DIR / "real_features.npy",
                augment_positive=True,
                n_augmented_per_clip=8,  # More augmentation for scarce real samples
            )
```

**Step 5: Run tests**

Run: `cd ~/projects/hapax-council && uv run pytest tests/hapax_voice/test_wake_word_augmentation.py -v`
Expected: All 6 tests PASS

**Step 6: Commit**

```bash
git add scripts/train_wake_word.py tests/hapax_voice/test_wake_word_augmentation.py
git commit -m "feat(voice): add weighted sampling for real voice features in training"
```

---

### Task 5: Increase Positive Sample Target and Add CLI Flags

Bump the default positive target from 5000 to 10000 and add CLI flags for augmentation control.

**Files:**
- Modify: `scripts/train_wake_word.py:531` (generate_positive_samples default)
- Modify: `scripts/train_wake_word.py:1155-1255` (CLI argument parser)
- Modify: `scripts/train_wake_word.py:1080-1148` (run_full_pipeline)

**Step 1: Modify defaults and add CLI flags**

In `generate_positive_samples` (line 531), change default:
```python
def generate_positive_samples(
    target_count: int = 10000,
    ...
```

In `parse_args` (line 1155), update the default and add new flags in the `hparams` group:

```python
    hparams.add_argument(
        "--num-positive", type=int, default=10000,
        help="Target number of positive samples (default: 10000)",
    )
    hparams.add_argument(
        "--no-augment", action="store_true",
        help="Disable audio augmentation during feature extraction",
    )
    hparams.add_argument(
        "--augment-per-clip", type=int, default=4,
        help="Number of augmented variants per clip (default: 4)",
    )
    hparams.add_argument(
        "--real-weight", type=float, default=3.0,
        help="Sampling weight multiplier for real voice samples (default: 3.0)",
    )
```

Wire the new flags through `run_full_pipeline`:

For feature extraction:
```python
        pos_features = extract_features_from_clips(
            POSITIVE_DIR,
            FEATURES_DIR / "positive_features.npy",
            augment_positive=not args.no_augment,
            n_augmented_per_clip=args.augment_per_clip,
        )
```

For real features:
```python
        real_dir = POSITIVE_DIR / "real"
        if real_dir.exists() and any(real_dir.rglob("*.wav")):
            extract_features_from_clips(
                real_dir,
                FEATURES_DIR / "real_features.npy",
                augment_positive=not args.no_augment,
                n_augmented_per_clip=args.augment_per_clip * 2,
            )
```

For training:
```python
        train_model(
            steps=args.steps,
            learning_rate=args.lr,
            max_negative_weight=args.max_neg_weight,
            hidden_dim=args.hidden_dim,
            n_blocks=args.n_blocks,
            real_sample_weight=args.real_weight,
        )
```

**Step 2: Verify**

Run: `cd ~/projects/hapax-council && uv run python scripts/train_wake_word.py --help`
Expected: Shows new flags (`--no-augment`, `--augment-per-clip`, `--real-weight`) and updated defaults

**Step 3: Commit**

```bash
git add scripts/train_wake_word.py
git commit -m "feat(voice): add augmentation CLI flags, bump positive target to 10k"
```

---

### Task 6: Record Real Utterances and Retrain

This is the hands-on task: record real voice samples, then run the full training pipeline.

**Files:**
- No code changes -- uses scripts from Tasks 1-5

**Step 1: Record ~50 real utterances**

Run: `cd ~/projects/hapax-council && uv run python scripts/record_wake_word.py --count 50`

Follow the interactive prompts. Tips:
- Vary your distance from the mic (30cm, 60cm, 1m)
- Vary volume (normal, quiet, loud)
- Vary speed (fast "hapax", slow "haaapax")
- Some with background noise (music playing, fan on)

**Step 2: Verify recordings**

Run: `ls data/wake-word-training/positive/real/ | wc -l`
Expected: ~50 files

**Step 3: Run full training pipeline with augmentation**

Run: `cd ~/projects/hapax-council && uv run python scripts/train_wake_word.py --all --num-positive 10000`

This runs: generate, download, extract (with augmentation), train.
Expected: Completes with model at `~/.local/share/hapax-voice/hapax_wake_word.onnx`

Watch for:
- Augmentation log: "Augmenting N clips (x4 variants each)"
- Real features log: "Real voice features: (N, 96) (weight: 3.0x)"
- Validation accuracy should reach >= 0.95

**Step 4: Verify model loads in the daemon**

Run: `systemctl --user restart hapax-voice && sleep 3 && journalctl --user -u hapax-voice --since "3 seconds ago" --no-pager | grep -i "wake word"`

Expected: "Wake word model loaded from ~/.local/share/hapax-voice/hapax_wake_word.onnx"

**Step 5: Test wake word detection**

Say "hapax" near the mic and check logs:
Run: `journalctl --user -u hapax-voice -f | grep -i "wake word"`
Expected: "Wake word detected (score=X.XXX)" with score > 0.5

**Step 6: Verify data/ is gitignored**

```bash
cd ~/projects/hapax-council && git status data/
```
If data/ is tracked, add it to `.gitignore`.

---

### Task 7: Variation Recording Sessions (Optional Enhancement)

Record additional sessions with specific acoustic conditions for maximum robustness.

**Files:**
- No code changes

**Step 1: Record from different positions**

```bash
# Session 1: Close mic (30cm)
uv run python scripts/record_wake_word.py --count 15 --output-dir data/wake-word-training/positive/real/

# Session 2: Medium distance (1m) -- move back from mic
uv run python scripts/record_wake_word.py --count 15 --output-dir data/wake-word-training/positive/real/

# Session 3: With background music playing
uv run python scripts/record_wake_word.py --count 10 --output-dir data/wake-word-training/positive/real/

# Session 4: Whispered / quiet
uv run python scripts/record_wake_word.py --count 10 --output-dir data/wake-word-training/positive/real/
```

**Step 2: Retrain with expanded real data**

```bash
cd ~/projects/hapax-council
uv run python scripts/train_wake_word.py --extract-features --train
```

**Step 3: Verify improved detection**

```bash
systemctl --user restart hapax-voice
journalctl --user -u hapax-voice -f | grep -i "wake word"
```

Say "hapax" at various distances and volumes. All should trigger detection.
Say phonetically similar words ("happy", "relax", "attacks"). None should trigger.
