"""agents/audio_perception/models.py — ML model loading with graceful fallback.

Each model loads independently. If any fails, the daemon continues with
whatever loaded. Partial ML beats no ML beats pure spectral heuristics.
"""

from __future__ import annotations

import logging
import time

import numpy as np

log = logging.getLogger(__name__)

SAMPLE_RATE = 48000
CLAP_SAMPLE_RATE = 48000
ESSENTIA_SAMPLE_RATE = 44100
PYANNOTE_SAMPLE_RATE = 16000

SCENE_LABELS = [
    "a person speaking or talking",
    "music playing",
    "silence or very quiet",
    "ambient noise or environmental sounds",
]
SCENE_MAP = {0: "speech", 1: "music", 2: "silence", 3: "ambient"}


def _resample(audio: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
    if from_rate == to_rate:
        return audio
    ratio = to_rate / from_rate
    n_out = int(len(audio) * ratio)
    indices = np.arange(n_out) / ratio
    indices_floor = np.floor(indices).astype(int)
    indices_floor = np.clip(indices_floor, 0, len(audio) - 2)
    frac = indices - indices_floor
    return audio[indices_floor] * (1 - frac) + audio[indices_floor + 1] * frac


class CLAPClassifier:
    """Zero-shot audio classification via LAION CLAP."""

    def __init__(self) -> None:
        import laion_clap

        self.model = laion_clap.CLAP_Module(enable_fusion=False, amodel="HTSAT-tiny")
        self.model.load_ckpt()
        self._text_embed = self.model.get_text_embedding(SCENE_LABELS, use_tensor=False)
        log.info("CLAP loaded (HTSAT-tiny)")

    def classify(self, audio_f32: np.ndarray) -> tuple[str, float]:
        resampled = _resample(audio_f32, SAMPLE_RATE, CLAP_SAMPLE_RATE)
        audio_embed = self.model.get_audio_embedding_from_data([resampled], use_tensor=False)
        sims = (audio_embed @ self._text_embed.T)[0]
        exp_sims = np.exp(sims - np.max(sims))
        probs = exp_sims / exp_sims.sum()
        best_idx = int(np.argmax(probs))
        return SCENE_MAP[best_idx], float(probs[best_idx])


class EssentiaAnalyzer:
    """Beat tracking and key detection via Essentia."""

    def __init__(self) -> None:
        import essentia.standard as es

        self._rhythm = es.RhythmExtractor2013(method="multifeature")
        self._key = es.KeyExtractor(profileType="edma", sampleRate=ESSENTIA_SAMPLE_RATE)
        self._rms = es.RMS()
        log.info("Essentia loaded (rhythm + key + RMS)")

    def analyze(self, audio_f32: np.ndarray) -> dict:
        result: dict = {}
        # RhythmExtractor2013 is documented by Essentia as requiring 44.1 kHz
        # input. Capture remains native 48 kHz; only model input is resampled.
        essentia_audio = _resample(audio_f32, SAMPLE_RATE, ESSENTIA_SAMPLE_RATE).astype(
            np.float32,
            copy=False,
        )
        try:
            bpm, _ticks, _conf, _estimates, _intervals = self._rhythm(essentia_audio)
            bpm_int = int(round(bpm))
            result["bpm"] = bpm_int if 40 <= bpm_int <= 240 else None
        except Exception:
            result["bpm"] = None

        try:
            key, scale, _strength = self._key(essentia_audio)
            result["key"] = f"{key} {scale}" if key else None
        except Exception:
            result["key"] = None

        try:
            rms = float(self._rms(audio_f32))
            result["rms_dbfs"] = max(-120.0, 20.0 * np.log10(rms)) if rms > 1e-10 else -120.0
        except Exception:
            result["rms_dbfs"] = -120.0

        return result


class PyannoteSegmenter:
    """Speaker segmentation via pyannote 3.x."""

    def __init__(self) -> None:
        from pyannote.audio import Model
        from pyannote.audio.pipelines import VoiceActivityDetection

        # HF_TOKEN env var is auto-read by huggingface-hub; avoid passing
        # token= explicitly since pyannote internally forwards it as the
        # deprecated use_auth_token kwarg which newer hf-hub rejects.
        self._seg_model = Model.from_pretrained("pyannote/segmentation-3.0")
        self._vad = VoiceActivityDetection(segmentation=self._seg_model)
        self._vad.instantiate({"min_duration_on": 0.2, "min_duration_off": 0.1})
        log.info("pyannote loaded (segmentation-3.0)")

    def segment(self, audio_f32: np.ndarray) -> str | None:
        import torch

        resampled = _resample(audio_f32, SAMPLE_RATE, PYANNOTE_SAMPLE_RATE)
        waveform = torch.from_numpy(resampled).unsqueeze(0).float()
        audio_dict = {"waveform": waveform, "sample_rate": PYANNOTE_SAMPLE_RATE}
        vad_result = self._vad(audio_dict)
        speech_regions = list(vad_result.itertracks())
        if not speech_regions:
            return None
        total_speech = sum(seg.end - seg.start for seg, _, _ in speech_regions)
        if total_speech < 0.3:
            return None
        return "spk_0"


def load_clap() -> CLAPClassifier | None:
    t0 = time.monotonic()
    try:
        clf = CLAPClassifier()
        log.info("CLAP ready (%.1fs)", time.monotonic() - t0)
        return clf
    except Exception:
        log.warning("CLAP unavailable — falling back to spectral analysis", exc_info=True)
        return None


def load_essentia() -> EssentiaAnalyzer | None:
    t0 = time.monotonic()
    try:
        analyzer = EssentiaAnalyzer()
        log.info("Essentia ready (%.1fs)", time.monotonic() - t0)
        return analyzer
    except Exception:
        log.warning("Essentia unavailable — falling back to autocorrelation", exc_info=True)
        return None


def load_pyannote() -> PyannoteSegmenter | None:
    t0 = time.monotonic()
    try:
        seg = PyannoteSegmenter()
        log.info("pyannote ready (%.1fs)", time.monotonic() - t0)
        return seg
    except Exception:
        log.warning("pyannote unavailable — speaker_id will be null", exc_info=True)
        return None
