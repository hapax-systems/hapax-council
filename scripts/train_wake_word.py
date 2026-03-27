#!/usr/bin/env python3
"""Train a custom OpenWakeWord model for the "Hapax" wake word.

This script automates the full pipeline:
  1. Generate synthetic positive samples ("Hapax") using multiple TTS engines
  2. Generate negative samples (non-wake-word speech) using the same TTS engines
  3. Download required datasets (negative features, augmentation data)
  4. Extract audio features using OpenWakeWord's embedding pipeline
  5. Train a small DNN classifier on the extracted features
  6. Export the trained model as ONNX for use with openwakeword

Usage:
    cd ~/projects/ai-agents
    uv run python scripts/train_wake_word.py --generate
    uv run python scripts/train_wake_word.py --train
    uv run python scripts/train_wake_word.py --all  # generate + train

    # Or step by step:
    uv run python scripts/train_wake_word.py --generate-positive
    uv run python scripts/train_wake_word.py --generate-negative
    uv run python scripts/train_wake_word.py --extract-features
    uv run python scripts/train_wake_word.py --train

Dependencies (install before running):
    uv pip install openwakeword onnxruntime torch torchaudio scipy datasets

    For Piper TTS sample generation (recommended, already in pyproject.toml):
        uv pip install piper-tts

    For Kokoro TTS (already in pyproject.toml):
        uv pip install kokoro

    Chatterbox TTS: must be running at localhost:4123
        cd ~/llm-stack && docker compose --profile tts up -d chatterbox

    piper-sample-generator (for high-diversity multi-speaker synthesis):
        git clone https://github.com/rhasspy/piper-sample-generator.git /tmp/piper-sample-generator
        Download a model: wget -P /tmp/piper-sample-generator/models/ \\
            https://huggingface.co/rhasspy/piper-sample-generator/resolve/v2.0.0/models/en_US-libritts_r-medium.pt

Notes:
    - The training pipeline requires OpenWakeWord's pre-trained feature extraction
      models (melspectrogram.onnx, embedding_model.onnx). These are downloaded
      automatically by openwakeword or can be fetched manually.
    - Minimum recommended: 5000+ positive samples, 1000+ hours negative features.
    - The official negative feature dataset (~2000 hours) is downloaded from HuggingFace.
    - Output model: ~/.local/share/hapax-voice/hapax_wake_word.onnx
"""

from __future__ import annotations

import argparse
import logging
import sys
import wave
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORK_DIR = PROJECT_ROOT / "data" / "wake-word-training"
POSITIVE_DIR = WORK_DIR / "positive"
NEGATIVE_DIR = WORK_DIR / "negative"
FEATURES_DIR = WORK_DIR / "features"
MODEL_OUTPUT_DIR = Path.home() / ".local" / "share" / "hapax-voice"
MODEL_OUTPUT_PATH = MODEL_OUTPUT_DIR / "hapax_wake_word.onnx"
VOICE_SAMPLE_PATH = PROJECT_ROOT / "profiles" / "voice-sample.wav"

# OpenWakeWord resource models (downloaded automatically)
OWW_MODELS_DIR = WORK_DIR / "oww-models"
MELSPEC_MODEL = OWW_MODELS_DIR / "melspectrogram.onnx"
EMBEDDING_MODEL = OWW_MODELS_DIR / "embedding_model.onnx"

# Piper sample generator
PIPER_GENERATOR_DIR = Path("/tmp/piper-sample-generator")
PIPER_GENERATOR_MODEL = PIPER_GENERATOR_DIR / "models" / "en_US-libritts_r-medium.pt"

# TTS endpoints
CHATTERBOX_URL = "http://localhost:4123"

# Audio constants
SAMPLE_RATE = 16000  # OpenWakeWord requires 16kHz
TARGET_WORD = "hapax"

# Wake word variations for TTS generation (phonetic spellings help TTS)
POSITIVE_PHRASES = [
    "hapax",
    "Hapax",
    "HAPAX",
    "hah packs",
    "hah_packs",
    "ha pax",
    "ha_pax",
]

# Negative phrases -- common words, phonetically similar words, and general speech
NEGATIVE_PHRASES = [
    # Phonetically similar (adversarial)
    "happy",
    "happen",
    "perhaps",
    "relax",
    "kayak",
    "attacks",
    "impacts",
    "hijack",
    "climax",
    "syntax",
    "Ajax",
    "hallux",
    "Halifax",
    "apex",
    "hat rack",
    "hay pack",
    "hub caps",
    "half back",
    # Common assistant wake words (should NOT trigger)
    "alexa",
    "hey siri",
    "okay google",
    "hey google",
    "hey jarvis",
    "computer",
    # Common short utterances
    "hello",
    "hey there",
    "thank you",
    "yes please",
    "no thanks",
    "good morning",
    "excuse me",
    "what time is it",
    "play music",
    "stop",
    "pause",
    "next",
    "help",
    "cancel",
    "never mind",
    "go ahead",
    "sounds good",
    "got it",
    "okay",
    "alright",
    "sure thing",
    "one moment",
    "hold on",
    "come here",
    "look at this",
    "what is that",
    "how are you",
    "goodbye",
    "see you later",
    "set a timer",
    "turn off the lights",
    "what is the weather",
    "remind me",
]


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def ensure_dir(path: Path) -> Path:
    """Create directory if it doesn't exist."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_wav(audio: np.ndarray, path: Path, sample_rate: int = SAMPLE_RATE) -> None:
    """Save int16 numpy audio as a WAV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(audio.astype(np.int16).tobytes())


def load_wav_16k(path: Path) -> np.ndarray:
    """Load a WAV file and resample to 16kHz mono int16."""
    try:
        import torchaudio

        waveform, sr = torchaudio.load(str(path))
        # Convert to mono
        if waveform.shape[0] > 1:
            waveform = waveform.mean(dim=0, keepdim=True)
        # Resample if needed
        if sr != SAMPLE_RATE:
            resampler = torchaudio.transforms.Resample(sr, SAMPLE_RATE)
            waveform = resampler(waveform)
        # Convert to int16
        audio = (waveform.squeeze().numpy() * 32767).astype(np.int16)
        return audio
    except Exception:
        # Fallback: scipy
        import scipy.io.wavfile as wavfile

        sr, audio = wavfile.read(str(path))
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if sr != SAMPLE_RATE:
            from scipy.signal import resample

            num_samples = int(len(audio) * SAMPLE_RATE / sr)
            audio = resample(audio, num_samples)
        if audio.dtype == np.float32 or audio.dtype == np.float64:
            audio = (audio * 32767).astype(np.int16)
        return audio.astype(np.int16)


# ---------------------------------------------------------------------------
# Audio Augmentation
# ---------------------------------------------------------------------------


def build_augmentation_pipeline() -> audiomentations.Compose:
    """Build an audiomentations augmentation pipeline for wake word samples.

    Applies realistic acoustic variations: noise, speed/pitch changes,
    and volume shifts. Each augmentation has a probability < 1.0
    so not every transform fires on every sample.
    """
    from audiomentations import (
        AddGaussianNoise,
        Compose,
        Gain,
        PitchShift,
        TimeStretch,
    )

    return Compose(
        [
            AddGaussianNoise(min_amplitude=0.002, max_amplitude=0.015, p=0.5),
            TimeStretch(min_rate=0.85, max_rate=1.15, p=0.5),
            PitchShift(min_semitones=-3, max_semitones=3, p=0.4),
            Gain(min_gain_db=-6, max_gain_db=6, p=0.3),
        ]
    )


def augment_clips(
    clips: list[np.ndarray],
    n_augmented_per_clip: int = 4,
    sample_rate: int = SAMPLE_RATE,
) -> list[np.ndarray]:
    """Augment a list of int16 audio clips.

    Returns originals + n_augmented_per_clip augmented variants per clip.
    """
    if n_augmented_per_clip < 0:
        raise ValueError(f"n_augmented_per_clip must be >= 0, got {n_augmented_per_clip}")
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


# ---------------------------------------------------------------------------
# TTS Generators
# ---------------------------------------------------------------------------

_kokoro_pipeline = None


def _get_kokoro_pipeline():
    """Lazy singleton for Kokoro pipeline (avoids re-init per sample)."""
    global _kokoro_pipeline
    if _kokoro_pipeline is None:
        import kokoro

        _kokoro_pipeline = kokoro.KPipeline(lang_code="a")
    return _kokoro_pipeline


# Carrier sentences that embed the wake word in natural context.
# Kokoro struggles with very short utterances (<10 tokens), so we
# synthesize the word in a sentence and trim to just the wake word.
_CARRIER_SENTENCES = [
    "The word is {word}.",
    "Please say {word} now.",
    "Hey {word}, are you there?",
    "Okay {word}, start listening.",
    "Can you hear me, {word}?",
]


def generate_with_kokoro(
    text: str,
    output_path: Path,
    voice: str = "af_heart",
    speed: float = 1.0,
) -> bool:
    """Generate a WAV file using Kokoro TTS (local, GPU-accelerated).

    For very short text (single words like 'hapax'), embeds in a carrier
    sentence and trims to extract just the wake word portion.

    Returns True on success, False on failure.
    """
    try:
        import kokoro  # noqa: F401
    except ImportError:
        log.warning("Kokoro not installed, skipping")
        return False

    try:
        pipeline = _get_kokoro_pipeline()

        # For short text, use a carrier sentence to avoid empty output
        is_short = len(text.split()) <= 2
        if is_short:
            import random

            carrier = random.choice(_CARRIER_SENTENCES).format(word=text)
            synth_text = carrier
        else:
            synth_text = text

        chunks = []
        for _g, _p, audio_tensor in pipeline(synth_text, voice=voice, speed=speed):
            audio_np = audio_tensor.cpu().numpy().astype(np.float32).squeeze()
            chunks.append(audio_np)

        if not chunks:
            return False

        audio = np.concatenate(chunks)

        if is_short:
            # Trim: take the middle portion (~1-2 seconds) which likely
            # contains the wake word. This isn't perfect alignment but
            # provides diverse wake word audio for training.
            total_len = len(audio)
            # Estimate wake word position: roughly in the middle-to-end
            # of the carrier sentence
            word_duration = int(0.8 * 24000 / speed)  # ~0.8s for the word
            center = total_len // 2
            start = max(0, center - word_duration)
            end = min(total_len, center + word_duration)
            audio = audio[start:end]

        # Kokoro outputs at 24kHz -- resample to 16kHz
        from scipy.signal import resample

        num_samples = int(len(audio) * SAMPLE_RATE / 24000)
        audio = resample(audio, num_samples)
        audio_int16 = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
        save_wav(audio_int16, output_path)
        return True
    except Exception as e:
        log.warning("Kokoro generation failed for %r: %s", text, e)
        return False


def generate_with_piper(
    text: str,
    output_path: Path,
    length_scale: float = 1.0,
    noise_scale: float = 0.667,
) -> bool:
    """Generate a WAV file using Piper TTS (local, CPU, fast).

    Returns True on success, False on failure.
    """
    try:
        from piper import PiperVoice
    except ImportError:
        log.warning("Piper TTS not installed, skipping")
        return False

    model_path = Path.home() / ".local" / "share" / "hapax-voice" / "piper-voice.onnx"
    if not model_path.exists():
        # Search common Piper model locations
        search_dirs = [
            Path.home() / ".local" / "share" / "piper-voices",
            Path.home() / "models" / "piper",
        ]
        found = False
        for piper_dir in search_dirs:
            if piper_dir.exists():
                onnx_files = list(piper_dir.rglob("*.onnx"))
                if onnx_files:
                    model_path = onnx_files[0]
                    found = True
                    break
        if not found:
            log.warning("No Piper voice model found at %s or %s", model_path, search_dirs)
            return False

    try:
        config_path = model_path.with_suffix(".onnx.json")
        voice = PiperVoice.load(
            str(model_path),
            config_path=str(config_path) if config_path.exists() else None,
        )

        # Piper synthesize yields AudioChunk objects with int16 audio
        from piper.config import SynthesisConfig

        syn_cfg = SynthesisConfig()
        syn_cfg.length_scale = length_scale
        syn_cfg.noise_scale = noise_scale

        chunks: list[bytes] = []
        piper_sr = None
        for chunk in voice.synthesize(text, syn_config=syn_cfg):
            chunks.append(chunk.audio_int16_bytes)
            if piper_sr is None:
                piper_sr = chunk.sample_rate

        if not chunks:
            return False

        raw_pcm = b"".join(chunks)
        audio = np.frombuffer(raw_pcm, dtype=np.int16)

        # Resample to 16kHz
        from scipy.signal import resample

        piper_sr = piper_sr or 22050
        num_samples = int(len(audio) * SAMPLE_RATE / piper_sr)
        audio_float = audio.astype(np.float64)
        audio_resampled = resample(audio_float, num_samples)
        audio_int16 = np.clip(audio_resampled, -32768, 32767).astype(np.int16)
        save_wav(audio_int16, output_path)
        return True
    except Exception as e:
        log.warning("Piper generation failed for %r: %s", text, e)
        return False


def generate_with_chatterbox(
    text: str,
    output_path: Path,
    exaggeration: float = 0.3,
    cfg_weight: float = 0.7,
) -> bool:
    """Generate a WAV file using Chatterbox TTS API (GPU, voice cloning).

    Returns True on success, False on failure.
    """
    try:
        import httpx
    except ImportError:
        log.warning("httpx not installed, skipping Chatterbox")
        return False

    # Check if Chatterbox is running
    try:
        r = httpx.get(f"{CHATTERBOX_URL}/docs", timeout=3)
        if r.status_code != 200:
            log.warning("Chatterbox not available at %s", CHATTERBOX_URL)
            return False
    except Exception:
        log.warning("Chatterbox not reachable at %s", CHATTERBOX_URL)
        return False

    try:
        # Use voice sample if available for voice cloning
        if VOICE_SAMPLE_PATH.exists():
            sample_data = VOICE_SAMPLE_PATH.read_bytes()
            response = httpx.post(
                f"{CHATTERBOX_URL}/v1/audio/speech/upload",
                data={
                    "input": text,
                    "exaggeration": str(exaggeration),
                    "cfg_weight": str(cfg_weight),
                },
                files={"voice_file": ("voice-sample.wav", sample_data, "audio/wav")},
                timeout=180,
            )
        else:
            response = httpx.post(
                f"{CHATTERBOX_URL}/v1/audio/speech",
                json={
                    "input": text,
                    "exaggeration": exaggeration,
                    "cfg_weight": cfg_weight,
                },
                timeout=180,
            )

        if response.status_code != 200:
            log.warning("Chatterbox returned %d", response.status_code)
            return False

        # Chatterbox returns WAV data -- save and resample to 16kHz
        output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = output_path.with_suffix(".tmp.wav")
        tmp_path.write_bytes(response.content)

        audio = load_wav_16k(tmp_path)
        save_wav(audio, output_path)
        tmp_path.unlink(missing_ok=True)
        return True
    except Exception as e:
        log.warning("Chatterbox generation failed for %r: %s", text, e)
        return False


def generate_with_piper_sample_generator(
    text: str,
    output_dir: Path,
    num_samples: int = 500,
    length_scales: tuple[float, ...] = (0.75, 1.0, 1.25),
    noise_scales: tuple[float, ...] = (0.667,),
    noise_scale_ws: tuple[float, ...] = (0.8,),
    max_speakers: int | None = None,
) -> int:
    """Generate many samples using piper-sample-generator (multi-speaker).

    This is the recommended method for large-scale synthetic data. It uses
    a multi-speaker TTS model (LibriTTS, 2000+ voices) with speaker
    interpolation for maximum diversity.

    Returns the number of generated samples.
    """
    if not PIPER_GENERATOR_DIR.exists():
        log.warning(
            "piper-sample-generator not found at %s. Clone it:\n"
            "  git clone https://github.com/rhasspy/piper-sample-generator.git %s",
            PIPER_GENERATOR_DIR,
            PIPER_GENERATOR_DIR,
        )
        return 0

    if not PIPER_GENERATOR_MODEL.exists():
        log.warning(
            "Piper sample generator model not found at %s. Download:\n"
            "  wget -P %s/models/ "
            "https://huggingface.co/rhasspy/piper-sample-generator/resolve/v2.0.0/"
            "models/en_US-libritts_r-medium.pt",
            PIPER_GENERATOR_MODEL,
            PIPER_GENERATOR_DIR,
        )
        return 0

    # Add piper-sample-generator to path
    if str(PIPER_GENERATOR_DIR) not in sys.path:
        sys.path.insert(0, str(PIPER_GENERATOR_DIR))

    try:
        from generate_samples import generate_samples
    except ImportError as e:
        log.warning("Could not import piper-sample-generator: %s", e)
        return 0

    ensure_dir(output_dir)

    try:
        generate_samples(
            text=[text],
            output_dir=str(output_dir),
            model=str(PIPER_GENERATOR_MODEL),
            max_samples=num_samples,
            batch_size=8,
            length_scales=length_scales,
            noise_scales=noise_scales,
            noise_scale_ws=noise_scale_ws,
            max_speakers=max_speakers,
            verbose=True,
        )
        generated = len(list(output_dir.glob("*.wav")))
        log.info("piper-sample-generator produced %d samples", generated)
        return generated
    except Exception as e:
        log.error("piper-sample-generator failed: %s", e)
        return 0


# ---------------------------------------------------------------------------
# Sample Generation Orchestration
# ---------------------------------------------------------------------------


def generate_positive_samples(
    target_count: int = 10000,
    use_chatterbox: bool = True,
    use_kokoro: bool = False,
    use_piper: bool = False,  # piper-tts removed — use Voxtral/chatterbox instead
    use_piper_generator: bool = True,
) -> int:
    """Generate positive samples of the wake word using available TTS engines.

    Strategy:
    - piper-sample-generator: bulk of samples (multi-speaker diversity, primary)
    - Piper: fast CPU generation with speed/noise variations
    - Chatterbox: voice-cloned samples for operator's voice (small count)
    - Kokoro: disabled by default (can't produce isolated short words reliably)

    Returns total number of generated samples.
    """
    ensure_dir(POSITIVE_DIR)
    total = 0
    idx = 0

    # 1. Piper sample generator -- primary source (multi-speaker, high diversity)
    if use_piper_generator:
        psg_dir = POSITIVE_DIR / "piper-sample-generator"
        ensure_dir(psg_dir)
        psg_count = int(target_count * 0.7)  # 70% from multi-speaker generator
        for phrase in POSITIVE_PHRASES[:3]:  # Use first 3 canonical spellings
            count = generate_with_piper_sample_generator(
                text=phrase,
                output_dir=psg_dir / phrase.replace(" ", "_"),
                num_samples=psg_count // 3,
            )
            total += count
        log.info("Piper sample generator: %d samples", total)

    # 2. Kokoro -- varied speeds
    if use_kokoro:
        kokoro_voices = ["af_heart", "af_bella", "am_adam", "am_michael"]
        speeds = [0.8, 0.9, 1.0, 1.1, 1.2]
        kokoro_count = 0
        for phrase in POSITIVE_PHRASES:
            for voice in kokoro_voices:
                for speed in speeds:
                    out = POSITIVE_DIR / f"kokoro_{idx:05d}.wav"
                    if generate_with_kokoro(phrase, out, voice=voice, speed=speed):
                        kokoro_count += 1
                        idx += 1
        total += kokoro_count
        log.info("Kokoro: %d samples", kokoro_count)

    # 3. Piper -- speed and noise variations
    if use_piper:
        piper_count = 0
        length_scales = [0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3]
        noise_scales = [0.4, 0.667, 0.9]
        for phrase in POSITIVE_PHRASES:
            for ls in length_scales:
                for ns in noise_scales:
                    out = POSITIVE_DIR / f"piper_{idx:05d}.wav"
                    if generate_with_piper(phrase, out, length_scale=ls, noise_scale=ns):
                        piper_count += 1
                        idx += 1
        total += piper_count
        log.info("Piper: %d samples", piper_count)

    # 4. Chatterbox -- voice-cloned, small batch (slow but high quality)
    if use_chatterbox:
        cb_count = 0
        exaggerations = [0.1, 0.3, 0.5, 0.7]
        cfg_weights = [0.5, 0.7, 0.9]
        for phrase in POSITIVE_PHRASES[:3]:
            for exag in exaggerations:
                for cfg in cfg_weights:
                    out = POSITIVE_DIR / f"chatterbox_{idx:05d}.wav"
                    if generate_with_chatterbox(phrase, out, exaggeration=exag, cfg_weight=cfg):
                        cb_count += 1
                        idx += 1
        total += cb_count
        log.info("Chatterbox: %d samples", cb_count)

    log.info("Total positive samples: %d", total)
    return total


def generate_negative_samples(
    use_kokoro: bool = False,
    use_piper: bool = False,  # piper-tts removed — use Voxtral/chatterbox instead
    use_chatterbox: bool = False,  # Chatterbox is slow, skip for negatives by default
) -> int:
    """Generate negative samples (non-wake-word speech).

    These supplement the large-scale negative feature dataset downloaded
    separately. Focus on phonetically similar words to reduce false accepts.
    """
    ensure_dir(NEGATIVE_DIR)
    total = 0
    idx = 0

    if use_kokoro:
        kokoro_voices = ["af_heart", "am_adam"]
        for phrase in NEGATIVE_PHRASES:
            for voice in kokoro_voices:
                out = NEGATIVE_DIR / f"kokoro_neg_{idx:05d}.wav"
                if generate_with_kokoro(phrase, out, voice=voice, speed=1.0):
                    total += 1
                    idx += 1

    if use_piper:
        for phrase in NEGATIVE_PHRASES:
            out = NEGATIVE_DIR / f"piper_neg_{idx:05d}.wav"
            if generate_with_piper(phrase, out, length_scale=1.0):
                total += 1
                idx += 1

    if use_chatterbox:
        for phrase in NEGATIVE_PHRASES[:10]:  # Limited set, Chatterbox is slow
            out = NEGATIVE_DIR / f"chatterbox_neg_{idx:05d}.wav"
            if generate_with_chatterbox(phrase, out):
                total += 1
                idx += 1

    log.info("Total negative samples: %d", total)
    return total


# ---------------------------------------------------------------------------
# Feature Extraction
# ---------------------------------------------------------------------------


def download_oww_models() -> None:
    """Download OpenWakeWord's pre-trained feature extraction models."""
    ensure_dir(OWW_MODELS_DIR)

    base_url = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1"
    models = [
        ("melspectrogram.onnx", MELSPEC_MODEL),
        ("embedding_model.onnx", EMBEDDING_MODEL),
    ]

    for name, path in models:
        if path.exists():
            log.info("Model already exists: %s", path)
            continue
        url = f"{base_url}/{name}"
        log.info("Downloading %s ...", url)
        import urllib.request

        urllib.request.urlretrieve(url, str(path))
        log.info("Saved to %s", path)


def download_negative_features() -> None:
    """Download pre-computed negative features from the OpenWakeWord project.

    These are ~2000 hours of negative audio pre-processed into feature vectors,
    essential for training a model with low false-accept rates.
    """
    features_file = FEATURES_DIR / "negative_features.npy"
    validation_file = FEATURES_DIR / "validation_set_features.npy"

    ensure_dir(FEATURES_DIR)

    if features_file.exists():
        log.info("Negative features already downloaded: %s", features_file)
    else:
        url = (
            "https://huggingface.co/datasets/davidscripka/openwakeword_features/resolve/main/"
            "openwakeword_features_ACAV100M_2000_hrs_16bit.npy"
        )
        log.info("Downloading negative features (~17GB) ...")
        log.info("URL: %s", url)
        import urllib.request

        urllib.request.urlretrieve(url, str(features_file))
        log.info("Saved to %s", features_file)

    if validation_file.exists():
        log.info("Validation features already downloaded: %s", validation_file)
    else:
        url = (
            "https://huggingface.co/datasets/davidscripka/openwakeword_features/resolve/main/"
            "validation_set_features.npy"
        )
        log.info("Downloading validation features ...")
        import urllib.request

        urllib.request.urlretrieve(url, str(validation_file))
        log.info("Saved to %s", validation_file)


def extract_features_from_clips(
    clips_dir: Path,
    output_path: Path,
    batch_size: int = 64,
    augment_positive: bool = False,
    n_augmented_per_clip: int = 4,
    exclude_dirs: list[str] | None = None,
) -> np.ndarray:
    """Extract OpenWakeWord features from a directory of WAV clips.

    Uses OWW's own streaming preprocessor to extract features, ensuring
    they match exactly what predict() produces at runtime. This avoids
    domain mismatch between training and inference features.

    Returns feature array of shape (n_windows, 16, 96).
    """
    from openwakeword.model import Model as OwwModel

    # Collect all WAV files
    wav_files = sorted(clips_dir.rglob("*.wav"))
    if exclude_dirs:
        wav_files = [f for f in wav_files if not any(excl in f.parts for excl in exclude_dirs)]
    if not wav_files:
        log.warning("No WAV files found in %s", clips_dir)
        return np.array([])

    log.info("Extracting features from %d clips in %s", len(wav_files), clips_dir)

    # Load and optionally augment clips
    if augment_positive:
        log.info("Loading clips for augmentation ...")
        raw_clips = []
        for wav_path in wav_files:
            try:
                audio = load_wav_16k(wav_path)
                raw_clips.append(audio)
            except Exception as e:
                log.warning("Failed to load %s: %s", wav_path.name, e)

        log.info(
            "Augmenting %d clips (x%d variants each) ...", len(raw_clips), n_augmented_per_clip
        )
        augmented_clips = augment_clips(raw_clips, n_augmented_per_clip=n_augmented_per_clip)
        log.info("Total clips after augmentation: %d", len(augmented_clips))
    else:
        augmented_clips = None

    # Use OWW's own preprocessor for feature extraction.
    # This is the exact same pipeline that runs during predict() at runtime.
    oww = OwwModel()
    chunk_size = 1280  # Same chunk size as runtime audio loop
    n_embed_frames = 16

    all_windows = []

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

            # Reset preprocessor state between clips so features don't
            # bleed across clips (mirrors a fresh detection at runtime).
            oww.reset()

            # Feed silence first to warm up the preprocessor buffers,
            # then feed the actual clip. This matches runtime behavior
            # where the preprocessor has been running on ambient audio
            # before the wake word is spoken.
            warmup = np.zeros(chunk_size * 10, dtype=np.int16)
            for start in range(0, len(warmup), chunk_size):
                oww.predict(warmup[start : start + chunk_size])

            # Feed the clip in runtime-sized chunks. Only capture features
            # from the later chunks where the wake word audio has had time
            # to propagate through the streaming preprocessor's buffers.
            n_clip_chunks = max(1, len(audio) // chunk_size)
            for ci, start in enumerate(range(0, len(audio), chunk_size)):
                chunk = audio[start : start + chunk_size]
                if len(chunk) < chunk_size:
                    chunk = np.pad(chunk, (0, chunk_size - len(chunk)))
                oww.predict(chunk)

                # Skip early chunks — the feature buffer still contains
                # mostly warmup silence. Only capture from the second half
                # of the clip onward, when the wake word dominates the
                # 16-frame feature window.
                if ci >= n_clip_chunks // 2:
                    feats = oww.preprocessor.get_features(n_embed_frames)
                    all_windows.append(feats[0])  # (16, 96)

        except Exception as e:
            clip_label = f"clip {i}" if augmented_clips is not None else wav_files[i].name
            log.warning("Failed to process %s: %s", clip_label, e)
            continue

    if not all_windows:
        log.error("No features extracted!")
        return np.array([])

    # Stack into (n_windows, 16, 96)
    features = np.array(all_windows, dtype=np.float32)
    log.info("Extracted features shape: %s", features.shape)  # Expected: (n, 16, 96)

    ensure_dir(output_path.parent)
    np.save(str(output_path), features)
    log.info("Saved features to %s", output_path)

    return features


# ---------------------------------------------------------------------------
# Model Training
# ---------------------------------------------------------------------------


def _generate_silence_negatives(
    oww_model: Model,
    n_synthetic: int = 200,
) -> np.ndarray:
    """Generate negative features from silence, synthetic noise, and ambient recordings.

    Uses OWW's streaming preprocessor to ensure features match runtime.

    Sources:
    1. Synthetic silence and Gaussian noise at various levels
    2. Real ambient recordings from data/wake-word-training/ambient/*.wav
    """
    chunk_size = 1280
    n_embed_frames = 16
    target_len = 24000  # 1.5s at 16kHz
    all_windows: list[np.ndarray] = []

    def _extract_via_oww(audio_int16: np.ndarray) -> None:
        """Feed audio through OWW preprocessor and capture feature windows."""
        oww_model.reset()
        for start in range(0, len(audio_int16), chunk_size):
            chunk = audio_int16[start : start + chunk_size]
            if len(chunk) < chunk_size:
                chunk = np.pad(chunk, (0, chunk_size - len(chunk)))
            oww_model.predict(chunk)
        # Capture final feature window
        feats = oww_model.preprocessor.get_features(n_embed_frames)
        all_windows.append(feats[0])

    # 1. Synthetic silence and noise
    rng = np.random.default_rng(42)
    for _i in range(n_synthetic):
        noise_level = rng.choice([0, 5, 10, 20, 40, 80, 150])
        if noise_level == 0:
            audio = np.zeros(target_len, dtype=np.int16)
        else:
            audio = (rng.standard_normal(target_len) * noise_level).astype(np.int16)
        _extract_via_oww(audio)
    log.info("Generated %d windows from %d synthetic clips", len(all_windows), n_synthetic)

    # 2. Real ambient recordings (chop into 1.5s segments)
    ambient_dir = WORK_DIR / "ambient"
    if ambient_dir.exists():
        ambient_files = sorted(ambient_dir.glob("*.wav"))
        n_ambient_feats = 0
        for wav_path in ambient_files:
            try:
                audio = load_wav_16k(wav_path)
                for start in range(0, len(audio) - target_len, target_len // 2):
                    segment = audio[start : start + target_len]
                    before = len(all_windows)
                    _extract_via_oww(segment)
                    n_ambient_feats += len(all_windows) - before
            except Exception as e:
                log.warning("Failed to process ambient file %s: %s", wav_path.name, e)
        log.info(
            "Generated %d features from %d ambient recordings",
            n_ambient_feats,
            len(ambient_files),
        )

    if not all_windows:
        return np.array([])

    features = np.array(all_windows, dtype=np.float32)
    log.info("Total silence/ambient negative windows: %s", features.shape)
    return features


def train_model(
    steps: int = 50000,
    learning_rate: float = 0.0001,
    max_negative_weight: int = 1500,
    n_per_class: int = 512,
    hidden_dim: int = 64,
    n_blocks: int = 2,
    real_sample_weight: float = 3.0,
) -> None:
    """Train an OpenWakeWord DNN model using extracted features.

    This implements the core training loop from openwakeword's train.py:
    - Small fully-connected DNN (LayerNorm + ReLU + Sigmoid)
    - Trained on positive features vs negative feature pool
    - Cosine learning rate schedule with warmup
    - Increasing negative weight schedule

    The trained model is exported as ONNX.
    """
    import torch
    import torch.nn as nn
    import torch.optim as optim

    # Load features
    pos_features_path = FEATURES_DIR / "positive_features.npy"

    if not pos_features_path.exists():
        log.error(
            "Positive features not found at %s. Run --extract-features first.",
            pos_features_path,
        )
        sys.exit(1)

    log.info("Loading features ...")
    pos_features = np.load(str(pos_features_path))
    log.info("Positive features: %s", pos_features.shape)

    # Features must be (n, 16, 96) — the OWW prediction window shape.
    # Reject old rank-2 features that predate this architecture.
    if pos_features.ndim != 3 or pos_features.shape[1:] != (16, 96):
        log.error(
            "Positive features have shape %s but expected (n, 16, 96). "
            "Re-run --extract-features to regenerate.",
            pos_features.shape,
        )
        sys.exit(1)

    # Load real voice features if available and build sampling weights
    real_features_path = FEATURES_DIR / "real_features.npy"
    if real_features_path.exists():
        real_features = np.load(str(real_features_path))
        if real_features.ndim != 3 or real_features.shape[1:] != (16, 96):
            log.warning(
                "Real features have shape %s, expected (n, 16, 96). Skipping.",
                real_features.shape,
            )
            sample_weights = None
        else:
            log.info(
                "Real voice features: %s (weight: %.1fx)", real_features.shape, real_sample_weight
            )
            n_tts = len(pos_features)
            pos_features = np.concatenate([pos_features, real_features], axis=0)
            sample_weights = np.ones(len(pos_features), dtype=np.float64)
            sample_weights[n_tts:] = real_sample_weight
            sample_weights /= sample_weights.sum()
    else:
        sample_weights = None
        log.info("No real voice features found -- using TTS-only positive data")

    # Build negative feature pool.
    # The OWW pre-computed negatives (17GB, ~5.6M windows of (16, 96)) are
    # memory-mapped to avoid loading them fully into RAM. Small supplemental
    # negatives (clips, silence, ambient) are loaded normally and sampled
    # alongside the pre-computed pool during training.
    neg_features_path = FEATURES_DIR / "negative_features.npy"
    neg_primary = None  # The large memory-mapped array
    neg_supplement_parts = []  # Small arrays loaded into RAM

    # 1. OWW pre-computed negatives (~2000 hours, ~5.6M windows) — memory-mapped
    if neg_features_path.exists():
        neg_primary = np.load(str(neg_features_path), mmap_mode="r")
        if neg_primary.ndim == 3 and neg_primary.shape[1:] == (16, 96):
            log.info("OWW pre-computed negatives (mmap): %s", neg_primary.shape)
        else:
            log.warning(
                "Pre-computed negatives shape %s != (n, 16, 96). Skipping.",
                neg_primary.shape,
            )
            neg_primary = None

    # 2. Self-extracted negative clip features
    neg_clip_path = FEATURES_DIR / "negative_clip_features.npy"
    if neg_clip_path.exists():
        neg_clips = np.load(str(neg_clip_path))
        if neg_clips.ndim == 3 and neg_clips.shape[1:] == (16, 96):
            neg_supplement_parts.append(neg_clips)
            log.info("Negative clip features: %d", len(neg_clips))
        else:
            log.warning(
                "Negative clip features shape %s != (n, 16, 96). Skipping.",
                neg_clips.shape,
            )

    # 3. Silence and ambient room noise negatives
    #    Use OWW's preprocessor (same as positive extraction) for consistency
    from openwakeword.model import Model as OwwModel

    _oww = OwwModel()
    silence_neg = _generate_silence_negatives(_oww)
    del _oww
    if len(silence_neg) > 0:
        neg_supplement_parts.append(silence_neg)

    neg_supplement = np.concatenate(neg_supplement_parts, axis=0) if neg_supplement_parts else None
    if neg_supplement is not None:
        log.info("Supplemental negatives: %d", len(neg_supplement))

    if neg_primary is None and neg_supplement is None:
        log.error(
            "No negative features available. Run --download-data and --extract-features first.",
        )
        sys.exit(1)

    neg_primary_size = len(neg_primary) if neg_primary is not None else 0
    neg_supplement_size = len(neg_supplement) if neg_supplement is not None else 0
    neg_total_size = neg_primary_size + neg_supplement_size
    log.info(
        "Total negative pool: %d (primary: %d, supplement: %d)",
        neg_total_size,
        neg_primary_size,
        neg_supplement_size,
    )

    # Flatten (n, 16, 96) → (n, 1536) for the DNN
    n_frames_per_window = pos_features.shape[1]  # 16
    embed_dim = pos_features.shape[2]  # 96
    flat_dim = n_frames_per_window * embed_dim  # 1536
    log.info("Model input: (%d, %d) → flat %d", n_frames_per_window, embed_dim, flat_dim)

    # Flatten positives in-place (reshape is a view, no copy)
    pos_flat = pos_features.reshape(len(pos_features), flat_dim)
    # Keep negatives in (n, 16, 96) to avoid doubling RAM (~17GB).
    # Flatten only the sampled batch each step.

    # Split positive into train/val
    n_val = max(100, int(len(pos_flat) * 0.1))
    indices = np.random.permutation(len(pos_flat))
    val_pos = pos_flat[indices[:n_val]]
    train_pos = pos_flat[indices[n_val:]]
    log.info("Train positive: %d, Val positive: %d", len(train_pos), len(val_pos))

    if sample_weights is not None:
        train_weights = sample_weights[indices[n_val:]]
        train_weights /= train_weights.sum()
    else:
        train_weights = None

    # Build model -- DNN that accepts OWW's (batch, 16, 96) input shape.
    # Flattens to (batch, 1536) then classifies with LayerNorm + FC blocks.
    class WakeWordDNN(nn.Module):
        """DNN for wake word detection, compatible with OWW predict().

        Accepts (batch, 16, 96) from OWW's streaming preprocessor.
        Flattens to (batch, 1536) then: LayerNorm → (Linear → ReLU) × n → Sigmoid.
        """

        def __init__(self, flat_dim: int, hidden_dim: int, n_blocks: int):
            super().__init__()
            layers = [nn.LayerNorm(flat_dim)]
            in_dim = flat_dim
            for _ in range(n_blocks):
                layers.append(nn.Linear(in_dim, hidden_dim))
                layers.append(nn.ReLU())
                in_dim = hidden_dim
            layers.append(nn.Linear(in_dim, 1))
            layers.append(nn.Sigmoid())
            self.net = nn.Sequential(*layers)

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            # Accept both (batch, 16, 96) and (batch, 1536)
            if x.ndim == 3:
                x = x.reshape(x.shape[0], -1)
            return self.net(x)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    log.info("Training on device: %s", device)

    model = WakeWordDNN(flat_dim, hidden_dim, n_blocks).to(device)
    optimizer = optim.Adam(model.parameters(), lr=learning_rate)
    criterion = nn.BCELoss(reduction="none")

    # Cosine LR schedule with warmup
    warmup_steps = min(1000, steps // 10)

    def lr_lambda(step: int) -> float:
        if step < warmup_steps:
            return step / warmup_steps
        progress = (step - warmup_steps) / (steps - warmup_steps)
        return 0.5 * (1 + np.cos(np.pi * progress))

    scheduler = optim.lr_scheduler.LambdaLR(optimizer, lr_lambda)

    # Training loop
    log.info("Starting training for %d steps ...", steps)
    best_val_accuracy = 0.0
    best_model_state = None

    def _sample_negatives(n: int) -> np.ndarray:
        """Sample n negatives from primary (mmap) + supplement pools.

        Returns (n, flat_dim) array. Uses batch indexing for speed.
        """
        indices = np.random.randint(0, neg_total_size, size=n)

        if neg_supplement is None:
            # All from primary (mmap) — batch read + reshape
            batch = np.array(neg_primary[indices], dtype=np.float32)
            return batch.reshape(n, flat_dim)

        if neg_primary is None:
            # All from supplement
            return neg_supplement[indices].reshape(n, flat_dim).astype(np.float32)

        # Split indices between primary and supplement pools
        primary_mask = indices < neg_primary_size
        result = np.empty((n, flat_dim), dtype=np.float32)

        if primary_mask.any():
            p_idx = indices[primary_mask]
            result[primary_mask] = np.array(
                neg_primary[p_idx],
                dtype=np.float32,
            ).reshape(-1, flat_dim)

        if (~primary_mask).any():
            s_idx = indices[~primary_mask] - neg_primary_size
            result[~primary_mask] = (
                neg_supplement[s_idx]
                .reshape(
                    -1,
                    flat_dim,
                )
                .astype(np.float32)
            )

        return result

    for step in range(steps):
        model.train()

        # Sample positive batch
        if train_weights is not None:
            pos_idx = np.random.choice(len(train_pos), size=n_per_class, p=train_weights)
        else:
            pos_idx = np.random.randint(0, len(train_pos), size=n_per_class)
        pos_batch = torch.tensor(train_pos[pos_idx], dtype=torch.float32, device=device)

        # Sample negative batch — flatten on-the-fly from mmap to avoid RAM blow-up
        neg_batch_np = _sample_negatives(n_per_class)
        neg_batch = torch.tensor(neg_batch_np, dtype=torch.float32, device=device)

        # Forward pass
        pos_pred = model(pos_batch)
        neg_pred = model(neg_batch)

        # Compute loss with increasing negative weight
        neg_weight_schedule = 1 + (max_negative_weight - 1) * (step / steps)
        pos_loss = criterion(pos_pred, torch.ones_like(pos_pred)).mean()
        neg_loss = criterion(neg_pred, torch.zeros_like(neg_pred)).mean()
        loss = pos_loss + neg_weight_schedule * neg_loss

        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        scheduler.step()

        # Logging
        if (step + 1) % 1000 == 0 or step == 0:
            with torch.no_grad():
                pos_acc = (pos_pred > 0.5).float().mean().item()
                neg_acc = (neg_pred < 0.5).float().mean().item()
                overall_acc = (pos_acc + neg_acc) / 2

            log.info(
                "Step %d/%d | Loss: %.4f | Pos Acc: %.3f | Neg Acc: %.3f | "
                "Overall: %.3f | LR: %.6f | Neg Weight: %.1f",
                step + 1,
                steps,
                loss.item(),
                pos_acc,
                neg_acc,
                overall_acc,
                scheduler.get_last_lr()[0],
                neg_weight_schedule,
            )

        # Validation every 5000 steps
        if (step + 1) % 5000 == 0:
            model.eval()
            with torch.no_grad():
                val_pos_t = torch.tensor(
                    val_pos,
                    dtype=torch.float32,
                    device=device,
                )
                val_pos_pred = model(val_pos_t)
                val_recall = (val_pos_pred > 0.5).float().mean().item()

                # Sample some negatives for validation
                val_neg_np = _sample_negatives(len(val_pos))
                val_neg_t = torch.tensor(val_neg_np, dtype=torch.float32, device=device)
                val_neg_pred = model(val_neg_t)
                val_specificity = (val_neg_pred < 0.5).float().mean().item()

                val_accuracy = (val_recall + val_specificity) / 2

            log.info(
                "  Validation | Recall: %.3f | Specificity: %.3f | Accuracy: %.3f",
                val_recall,
                val_specificity,
                val_accuracy,
            )

            if val_accuracy > best_val_accuracy:
                best_val_accuracy = val_accuracy
                best_model_state = {k: v.clone() for k, v in model.state_dict().items()}
                log.info("  New best validation accuracy: %.3f", best_val_accuracy)

    # Restore best model
    if best_model_state is not None:
        model.load_state_dict(best_model_state)
        log.info("Restored best model (val accuracy: %.3f)", best_val_accuracy)

    # Export to ONNX — pass (16, 96) shape so ONNX accepts rank-3 input
    export_to_onnx(model, n_frames_per_window, embed_dim, device)

    # Free GPU memory
    del model, best_model_state
    if device.type == "cuda":
        import torch

        torch.cuda.empty_cache()


def export_to_onnx(
    model: torch.nn.Module,
    n_frames: int,
    embed_dim: int,
    device: torch.device,
) -> None:
    """Export trained model to ONNX format compatible with openwakeword.

    The ONNX model accepts (batch, n_frames, embed_dim) — typically (1, 16, 96) —
    which is what OWW's predict() produces. The model's forward() flattens
    this internally before the DNN layers.
    """
    import torch

    model.eval()
    ensure_dir(MODEL_OUTPUT_DIR)

    # OWW predict() passes (1, 16, 96) to custom models
    dummy_input = torch.randn(1, n_frames, embed_dim, device=device)

    torch.onnx.export(
        model,
        dummy_input,
        str(MODEL_OUTPUT_PATH),
        input_names=["input"],
        output_names=["output"],
        dynamic_axes={
            "input": {0: "batch_size"},
            "output": {0: "batch_size"},
        },
        opset_version=11,
        do_constant_folding=True,
    )

    log.info("Model exported to %s", MODEL_OUTPUT_PATH)

    # Verify the exported model loads correctly with rank-3 input
    import onnxruntime as ort

    session = ort.InferenceSession(str(MODEL_OUTPUT_PATH), providers=["CPUExecutionProvider"])
    test_input = np.random.randn(1, n_frames, embed_dim).astype(np.float32)
    result = session.run(None, {"input": test_input})
    log.info(
        "ONNX verification -- input shape: %s, output shape: %s, sample output: %s",
        test_input.shape,
        result[0].shape,
        result[0],
    )


# ---------------------------------------------------------------------------
# Full Pipeline
# ---------------------------------------------------------------------------


def run_full_pipeline(args: argparse.Namespace) -> None:
    """Run the complete training pipeline end-to-end."""
    log.info("=== Hapax Wake Word Training Pipeline ===")
    log.info("Work directory: %s", WORK_DIR)
    log.info("Output model: %s", MODEL_OUTPUT_PATH)

    if args.all or args.generate or args.generate_positive:
        log.info("\n--- Step 1: Generate Positive Samples ---")
        generate_positive_samples(
            target_count=args.num_positive,
            use_chatterbox=not args.no_chatterbox,
            use_kokoro=args.kokoro,
            use_piper=not args.no_piper,
            use_piper_generator=not args.no_piper_generator,
        )

    if args.all or args.generate or args.generate_negative:
        log.info("\n--- Step 2: Generate Negative Samples ---")
        generate_negative_samples(
            use_kokoro=args.kokoro,
            use_piper=not args.no_piper,
            use_chatterbox=False,
        )

    if args.all or args.download_data:
        log.info("\n--- Step 3: Download Negative Features ---")
        download_negative_features()

    if args.all or args.extract_features:
        log.info("\n--- Step 4: Extract Features ---")
        pos_features = extract_features_from_clips(
            POSITIVE_DIR,
            FEATURES_DIR / "positive_features.npy",
            augment_positive=not args.no_augment,
            n_augmented_per_clip=args.augment_per_clip,
            exclude_dirs=["real"],
        )
        if len(pos_features) == 0:
            log.error("No positive features extracted. Check your samples.")
            sys.exit(1)

        # Extract real voice features separately (for weighted sampling)
        real_dir = POSITIVE_DIR / "real"
        if real_dir.exists() and any(real_dir.rglob("*.wav")):
            extract_features_from_clips(
                real_dir,
                FEATURES_DIR / "real_features.npy",
                augment_positive=not args.no_augment,
                n_augmented_per_clip=args.augment_per_clip * 2,
            )

        # Also extract features from negative clips (supplement the downloaded set)
        neg_clip_features_path = FEATURES_DIR / "negative_clip_features.npy"
        if any(NEGATIVE_DIR.rglob("*.wav")):
            neg_clip_features = extract_features_from_clips(
                NEGATIVE_DIR,
                neg_clip_features_path,
            )
            log.info("Extracted %d negative clip features", len(neg_clip_features))

    if args.all or args.train:
        log.info("\n--- Step 5: Train Model ---")
        train_model(
            steps=args.steps,
            learning_rate=args.lr,
            max_negative_weight=args.max_neg_weight,
            hidden_dim=args.hidden_dim,
            n_blocks=args.n_blocks,
            real_sample_weight=args.real_weight,
        )

    log.info("\n=== Pipeline Complete ===")
    log.info("Model saved to: %s", MODEL_OUTPUT_PATH)
    log.info(
        "Test with:\n"
        "  cd ~/projects/ai-agents\n"
        '  uv run python -c "\n'
        "    from agents.hapax_voice.wake_word import WakeWordDetector\n"
        "    d = WakeWordDetector(threshold=0.5)\n"
        "    d.load()\n"
        "    print('Model loaded successfully!' if d._model else 'Load failed')\n"
        '  "'
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train a custom OpenWakeWord model for the 'Hapax' wake word.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full pipeline (generate + download + extract + train):
  uv run python scripts/train_wake_word.py --all

  # Generate samples only:
  uv run python scripts/train_wake_word.py --generate

  # Download negative features + train only (if samples already exist):
  uv run python scripts/train_wake_word.py --download-data --extract-features --train

  # Quick test with fewer samples and steps:
  uv run python scripts/train_wake_word.py --all --num-positive 500 --steps 5000

  # Skip unavailable TTS engines:
  uv run python scripts/train_wake_word.py --generate --no-chatterbox --no-piper-generator
""",
    )

    # Pipeline stages
    stages = parser.add_argument_group("pipeline stages")
    stages.add_argument(
        "--all",
        action="store_true",
        help="Run the full pipeline (generate + download + extract + train)",
    )
    stages.add_argument(
        "--generate",
        action="store_true",
        help="Generate both positive and negative samples",
    )
    stages.add_argument(
        "--generate-positive",
        action="store_true",
        help="Generate positive samples only",
    )
    stages.add_argument(
        "--generate-negative",
        action="store_true",
        help="Generate negative samples only",
    )
    stages.add_argument(
        "--download-data",
        action="store_true",
        help="Download negative features and augmentation data",
    )
    stages.add_argument(
        "--extract-features",
        action="store_true",
        help="Extract features from generated audio clips",
    )
    stages.add_argument(
        "--train",
        action="store_true",
        help="Train the model (requires features to be extracted)",
    )

    # TTS engine selection
    tts = parser.add_argument_group("TTS engine selection")
    tts.add_argument(
        "--no-chatterbox",
        action="store_true",
        help="Skip Chatterbox TTS (default: use if available)",
    )
    tts.add_argument(
        "--kokoro",
        action="store_true",
        help="Include Kokoro TTS (off by default — can't produce short words reliably)",
    )
    tts.add_argument(
        "--no-piper",
        action="store_true",
        help="Skip Piper TTS",
    )
    tts.add_argument(
        "--no-piper-generator",
        action="store_true",
        help="Skip piper-sample-generator (multi-speaker bulk generation)",
    )

    # Training hyperparameters
    hparams = parser.add_argument_group("training hyperparameters")
    hparams.add_argument(
        "--num-positive",
        type=int,
        default=10000,
        help="Target number of positive samples (default: 10000)",
    )
    hparams.add_argument(
        "--no-augment",
        action="store_true",
        help="Disable audio augmentation during feature extraction",
    )
    hparams.add_argument(
        "--augment-per-clip",
        type=int,
        default=4,
        help="Number of augmented variants per clip (default: 4)",
    )
    hparams.add_argument(
        "--real-weight",
        type=float,
        default=3.0,
        help="Sampling weight multiplier for real voice samples (default: 3.0)",
    )
    hparams.add_argument(
        "--steps",
        type=int,
        default=50000,
        help="Number of training steps (default: 50000)",
    )
    hparams.add_argument(
        "--lr",
        type=float,
        default=0.0001,
        help="Learning rate (default: 0.0001)",
    )
    hparams.add_argument(
        "--max-neg-weight",
        type=int,
        default=1500,
        help="Maximum negative loss weight (default: 1500)",
    )
    hparams.add_argument(
        "--hidden-dim",
        type=int,
        default=64,
        help="Hidden layer dimension (default: 64)",
    )
    hparams.add_argument(
        "--n-blocks",
        type=int,
        default=2,
        help="Number of hidden blocks (default: 2)",
    )

    return parser.parse_args()


def main() -> None:
    from shared.log_setup import configure_logging

    configure_logging(agent="train-wake")

    args = parse_args()

    # Check that at least one stage is selected
    any_stage = (
        args.all
        or args.generate
        or args.generate_positive
        or args.generate_negative
        or args.download_data
        or args.extract_features
        or args.train
    )
    if not any_stage:
        log.error("No pipeline stage selected. Use --all or specify stages.")
        log.error("Run with --help for usage information.")
        sys.exit(1)

    run_full_pipeline(args)


if __name__ == "__main__":
    main()
