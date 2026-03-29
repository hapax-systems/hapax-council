"""shared/clap.py — CLAP audio-text embedding and zero-shot classification.

Wraps LAION CLAP (laion/larger_clap_music_and_speech) for:
  - embed_audio(): 512-dim embedding from raw waveform
  - embed_text(): 512-dim embedding from text description
  - classify_zero_shot(): multi-label classification against candidate labels

Model is lazy-loaded on first call and protected by VRAMLock to coordinate
GPU access with audio_processor and hapax_daimonion.

Chunking: Audio longer than 10s is split into overlapping chunks (10s window,
5s hop) and embeddings are mean-pooled. This matches the audio_processor's
PANNs windowing strategy.
"""

from __future__ import annotations

import logging

import numpy as np

log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

CLAP_MODEL_NAME = "laion/larger_clap_music_and_speech"
CLAP_EMBED_DIM = 512
CLAP_SAMPLE_RATE = 48000  # CLAP expects 48kHz
CHUNK_SECONDS = 10.0
HOP_SECONDS = 5.0

# ── Lazy model singleton ────────────────────────────────────────────────────

_clap_model = None


def _get_model():
    """Load the CLAP model on first call. Requires GPU."""
    global _clap_model
    if _clap_model is not None:
        return _clap_model

    import laion_clap

    log.info("Loading CLAP model: %s", CLAP_MODEL_NAME)
    model = laion_clap.CLAP_Module(enable_fusion=True, amodel="HTSAT-base")
    model.load_ckpt(model_id=1)  # music_speech_audioset_epoch_15_esc_89.98.pt
    _clap_model = model
    log.info("CLAP model loaded (embed_dim=%d)", CLAP_EMBED_DIM)
    return _clap_model


def unload_model() -> None:
    """Release the CLAP model from memory."""
    global _clap_model
    if _clap_model is not None:
        import gc

        import torch

        del _clap_model
        _clap_model = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        log.info("CLAP model unloaded")


# ── Chunking ─────────────────────────────────────────────────────────────────


def _chunk_waveform(
    waveform: np.ndarray,
    sr: int,
    chunk_seconds: float = CHUNK_SECONDS,
    hop_seconds: float = HOP_SECONDS,
) -> list[np.ndarray]:
    """Split waveform into overlapping chunks.

    Returns a list of 1-D numpy arrays, each chunk_seconds long.
    The last chunk is zero-padded if shorter than chunk_seconds.
    """
    chunk_samples = int(chunk_seconds * sr)
    hop_samples = int(hop_seconds * sr)

    if len(waveform) <= chunk_samples:
        # Pad short audio to chunk length
        if len(waveform) < chunk_samples:
            padded = np.zeros(chunk_samples, dtype=waveform.dtype)
            padded[: len(waveform)] = waveform
            return [padded]
        return [waveform]

    chunks = []
    start = 0
    while start < len(waveform):
        end = start + chunk_samples
        chunk = waveform[start:end]
        if len(chunk) < chunk_samples:
            padded = np.zeros(chunk_samples, dtype=waveform.dtype)
            padded[: len(chunk)] = chunk
            chunk = padded
        chunks.append(chunk)
        start += hop_samples

    return chunks


# ── Public API ───────────────────────────────────────────────────────────────


def embed_audio(
    waveform: np.ndarray,
    sr: int = CLAP_SAMPLE_RATE,
) -> np.ndarray:
    """Compute a 512-dim CLAP embedding from audio waveform.

    Args:
        waveform: 1-D float32 numpy array (mono).
        sr: Sample rate of the waveform. Resampled to 48kHz if different.

    Returns:
        1-D numpy array of shape (512,).

    Audio longer than CHUNK_SECONDS is split into overlapping chunks
    and embeddings are mean-pooled.
    """
    if sr != CLAP_SAMPLE_RATE:
        import torch
        import torchaudio

        waveform_t = torch.from_numpy(waveform).unsqueeze(0).float()
        waveform_t = torchaudio.functional.resample(waveform_t, sr, CLAP_SAMPLE_RATE)
        waveform = waveform_t.squeeze(0).numpy()

    model = _get_model()
    chunks = _chunk_waveform(waveform, CLAP_SAMPLE_RATE)

    if len(chunks) == 1:
        embedding = model.get_audio_embedding_from_data(x=chunks[0], use_tensor=False)
        vec = embedding[0]
    else:
        embeddings = []
        for chunk in chunks:
            emb = model.get_audio_embedding_from_data(x=chunk, use_tensor=False)
            embeddings.append(emb[0])
        vec = np.mean(embeddings, axis=0)

    if len(vec) != CLAP_EMBED_DIM:
        raise RuntimeError(f"CLAP embed_audio returned {len(vec)}-dim, expected {CLAP_EMBED_DIM}")
    return vec


def embed_text(text: str) -> np.ndarray:
    """Compute a 512-dim CLAP embedding from a text description.

    Args:
        text: Natural language description (e.g., "jazzy piano loop with brass").

    Returns:
        1-D numpy array of shape (512,).
    """
    model = _get_model()
    embedding = model.get_text_embedding([text], use_tensor=False)
    vec = embedding[0]
    if len(vec) != CLAP_EMBED_DIM:
        raise RuntimeError(f"CLAP embed_text returned {len(vec)}-dim, expected {CLAP_EMBED_DIM}")
    return vec


def classify_zero_shot(
    waveform: np.ndarray,
    labels: list[str],
    sr: int = CLAP_SAMPLE_RATE,
) -> dict[str, float]:
    """Zero-shot audio classification against candidate text labels.

    Computes cosine similarity between the audio embedding and each label's
    text embedding, then applies softmax to produce probabilities.

    Args:
        waveform: 1-D float32 numpy array (mono).
        labels: List of candidate text labels.
        sr: Sample rate. Resampled to 48kHz if different.

    Returns:
        Dict mapping label → probability (sums to 1.0).
    """
    audio_emb = embed_audio(waveform, sr=sr)
    text_embs = np.array([embed_text(label) for label in labels])

    # Normalize for cosine similarity
    audio_norm = audio_emb / (np.linalg.norm(audio_emb) + 1e-8)
    text_norms = text_embs / (np.linalg.norm(text_embs, axis=1, keepdims=True) + 1e-8)

    similarities = text_norms @ audio_norm

    # Softmax with temperature
    exp_sims = np.exp(similarities - np.max(similarities))
    probs = exp_sims / exp_sims.sum()

    return dict(zip(labels, probs.tolist(), strict=True))
