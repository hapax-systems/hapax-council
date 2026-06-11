"""Resident STT with cache-aware streaming support.

The daemon keeps one STT model resident and exposes two contracts:

* ``transcribe(bytes) -> str`` for legacy full-utterance callers.
* ``accept_stream_frame(...)`` plus ``pop_stream_final()`` for streaming
  partial hypotheses and endpointed finals.

NeMo/Nemotron/Parakeet models use the cache-aware ``conformer_stream_step``
path. Faster-Whisper remains as a configured fallback for degraded installs.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import wave
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any, Protocol

import numpy as np

log = logging.getLogger(__name__)

# Dedicated executor for STT. Streaming cache state is mutable, so all stream
# steps and fallback transcriptions are serialized through one worker.
_stt_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stt")

DEFAULT_STREAMING_MODEL = "nvidia/nemotron-speech-streaming-en-0.6b"
DEFAULT_SAMPLE_RATE = 16000
DEFAULT_FRAME_MS = 30
DEFAULT_CHUNK_MS = 480
DEFAULT_PRE_ROLL_MS = 1500
DEFAULT_ENDPOINT_SILENCE_MS = 600
DEFAULT_MIN_UTTERANCE_MS = 180
DEFAULT_MAX_UTTERANCE_MS = 30000

_SPEECH_START_PROB = 0.15
_SPEECH_END_PROB = 0.10
_SPEECH_START_FRAMES = 3


@dataclass(frozen=True)
class StreamingSTTConfig:
    """Runtime tuning for streaming ASR endpointing."""

    sample_rate: int = DEFAULT_SAMPLE_RATE
    frame_ms: int = DEFAULT_FRAME_MS
    chunk_ms: int = DEFAULT_CHUNK_MS
    pre_roll_ms: int = DEFAULT_PRE_ROLL_MS
    endpoint_silence_ms: int = DEFAULT_ENDPOINT_SILENCE_MS
    min_utterance_ms: int = DEFAULT_MIN_UTTERANCE_MS
    max_utterance_ms: int = DEFAULT_MAX_UTTERANCE_MS
    speech_start_prob: float = _SPEECH_START_PROB
    speech_end_prob: float = _SPEECH_END_PROB
    speech_start_frames: int = _SPEECH_START_FRAMES

    @property
    def frame_bytes(self) -> int:
        return int(self.sample_rate * self.frame_ms / 1000) * 2

    @property
    def chunk_bytes(self) -> int:
        return int(self.sample_rate * self.chunk_ms / 1000) * 2

    @property
    def pre_roll_frames(self) -> int:
        return max(1, self.pre_roll_ms // self.frame_ms)

    @property
    def endpoint_silence_frames(self) -> int:
        return max(1, self.endpoint_silence_ms // self.frame_ms)

    @property
    def min_utterance_bytes(self) -> int:
        return int(self.sample_rate * self.min_utterance_ms / 1000) * 2

    @property
    def max_utterance_bytes(self) -> int:
        return int(self.sample_rate * self.max_utterance_ms / 1000) * 2


@dataclass(frozen=True)
class StreamingSTTEvent:
    """A partial or final streaming ASR hypothesis."""

    text: str
    is_final: bool
    reason: str
    audio_ms: int
    step: int
    stable_prefix: str = ""
    barge_in: bool = False
    audio_bytes: bytes = field(default=b"", repr=False)


class _STTBackend(Protocol):
    supports_streaming: bool

    def load(self) -> None: ...

    def reset_stream(self) -> None: ...

    def stream_step(self, audio_bytes: bytes, sample_rate: int) -> str: ...

    def transcribe_sync(
        self,
        audio_bytes: bytes,
        sample_rate: int,
        language: str,
        speculative: bool,
    ) -> str: ...


def _normalize_model_name(model_name: str) -> str:
    if not model_name:
        return DEFAULT_STREAMING_MODEL
    if model_name == "nemo-parakeet-tdt-0.6b-v3":
        return "nvidia/parakeet-tdt-0.6b-v3"
    return model_name


def _uses_whisper_backend(model_name: str) -> bool:
    lowered = model_name.lower()
    return "whisper" in lowered or "distil" in lowered


def _extract_text(value: Any) -> str:
    """Best-effort text extraction from NeMo hypotheses or plain strings."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("text", "transcript", "pred_text"):
            text = value.get(key)
            if text:
                return str(text).strip()
        return ""
    if isinstance(value, (list, tuple)):
        if not value:
            return ""
        return _extract_text(value[0])
    for attr in ("text", "transcript", "pred_text"):
        text = getattr(value, attr, None)
        if text:
            return str(text).strip()
    return str(value).strip()


def _stable_prefix(previous: str, current: str) -> str:
    """Return the common word prefix between adjacent partial hypotheses."""
    previous_words = previous.split()
    current_words = current.split()
    stable: list[str] = []
    for left, right in zip(previous_words, current_words, strict=False):
        if left != right:
            break
        stable.append(right)
    return " ".join(stable)


class _WhisperBackend:
    supports_streaming = False

    def __init__(self, model_name: str, device: str, compute_type: str) -> None:
        self._model_name = model_name
        self._device = device
        self._compute_type = compute_type
        self._model: Any | None = None

    def load(self) -> None:
        from faster_whisper import WhisperModel

        log.info(
            "Loading Whisper model %s on %s (%s)...",
            self._model_name,
            self._device,
            self._compute_type,
        )
        self._model = WhisperModel(
            self._model_name,
            device=self._device,
            compute_type=self._compute_type,
        )
        log.info("Whisper model loaded: %s", self._model_name)

    def reset_stream(self) -> None:
        return

    def stream_step(self, audio_bytes: bytes, sample_rate: int) -> str:
        del audio_bytes, sample_rate
        return ""

    def transcribe_sync(
        self,
        audio_bytes: bytes,
        sample_rate: int,
        language: str,
        speculative: bool,
    ) -> str:
        if self._model is None:
            return ""
        audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

        segments, info = self._model.transcribe(
            audio,
            language=language,
            beam_size=2,
            vad_filter=False,
            word_timestamps=not speculative,
            initial_prompt=(
                "Hey Hapax, what's going on? "
                "Hapax, can you check that for me? "
                "Thanks Hapax. "
                "Hey Hapax, what do you think about this? "
                "Hapax, tell me about the studio session."
            ),
        )

        all_words: list[dict[str, float | str]] = []
        text_parts: list[str] = []
        for seg in segments:
            text_parts.append(seg.text)
            if not speculative and seg.words:
                for word in seg.words:
                    all_words.append({"word": word.word, "start": word.start, "end": word.end})

        text = " ".join(text_parts).strip()
        if text:
            level = log.debug if speculative else log.info
            level(
                'STT: "%s" (%.1fs audio, lang=%s)',
                text,
                len(audio) / sample_rate,
                info.language,
            )
            if not speculative:
                _extract_prosody(audio, sample_rate, all_words)
        return text


class _NeMoStreamingBackend:
    supports_streaming = True

    def __init__(self, model_name: str, device: str, compute_type: str) -> None:
        self._model_name = model_name
        self._device_name = device
        self._compute_type = compute_type
        self._model: Any | None = None
        self._torch: Any | None = None
        self._cache_last_channel: Any | None = None
        self._cache_last_time: Any | None = None
        self._cache_last_channel_len: Any | None = None
        self._cache_pre_encode: Any | None = None
        self._pre_encode_cache_size: int = 0
        self._previous_hypotheses: Any | None = None
        self._pred_out_stream: Any | None = None

    def load(self) -> None:
        import torch
        from nemo.collections.asr.models import ASRModel

        self._torch = torch
        model_name = _normalize_model_name(self._model_name)
        log.info("Loading NeMo streaming ASR model %s on %s...", model_name, self._device_name)

        if Path(model_name).exists() or model_name.endswith(".nemo"):
            map_location = torch.device(self._device_name if torch.cuda.is_available() else "cpu")
            model = ASRModel.restore_from(restore_path=model_name, map_location=map_location)
        else:
            model = ASRModel.from_pretrained(model_name=model_name)

        model.eval()
        if self._device_name.startswith("cuda") and torch.cuda.is_available():
            model.to(torch.device(self._device_name))

        self._configure_low_latency_decoding(model)
        self._model = model
        self.reset_stream()
        log.info("NeMo streaming ASR model loaded: %s", model_name)

    def _configure_low_latency_decoding(self, model: Any) -> None:
        try:
            from omegaconf import open_dict

            decoding_cfg = model.cfg.decoding
            with open_dict(decoding_cfg):
                decoding_cfg.strategy = "greedy"
                decoding_cfg.preserve_alignments = False
                if hasattr(model, "joint"):
                    decoding_cfg.greedy.max_symbols = 10
                    decoding_cfg.fused_batch_size = -1
            model.change_decoding_strategy(decoding_cfg)
        except Exception:
            log.debug("NeMo greedy decoding configuration skipped", exc_info=True)

    def reset_stream(self) -> None:
        if self._model is None:
            return
        torch = self._torch
        if torch is None:
            return

        self._cache_last_channel, self._cache_last_time, self._cache_last_channel_len = (
            self._model.encoder.get_initial_cache_state(batch_size=1)
        )
        self._previous_hypotheses = None
        self._pred_out_stream = None

        streaming_cfg = getattr(self._model.encoder, "streaming_cfg", None)
        cache_size = 0
        if streaming_cfg is not None:
            raw_size = getattr(streaming_cfg, "pre_encode_cache_size", 0)
            if isinstance(raw_size, (list, tuple)):
                cache_size = int(raw_size[-1])
            else:
                cache_size = int(raw_size or 0)
        self._pre_encode_cache_size = max(0, cache_size)

        features = int(getattr(getattr(self._model.cfg, "preprocessor", object()), "features", 0))
        if self._pre_encode_cache_size > 0 and features > 0:
            self._cache_pre_encode = torch.zeros(
                (1, features, self._pre_encode_cache_size),
                device=self._model.device,
            )
        else:
            self._cache_pre_encode = None

    def stream_step(self, audio_bytes: bytes, sample_rate: int) -> str:
        if self._model is None or self._torch is None:
            return ""
        torch = self._torch

        audio_data = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        if audio_data.size == 0:
            return ""

        audio_signal = torch.as_tensor(
            audio_data,
            dtype=torch.float32,
            device=self._model.device,
        ).unsqueeze(0)
        signal_length = torch.tensor([audio_signal.shape[-1]], device=self._model.device)

        del sample_rate  # The daemon captures at the model's configured 16 kHz rate.
        with torch.no_grad():
            processed_signal, processed_signal_length = self._model.preprocessor(
                input_signal=audio_signal,
                length=signal_length,
            )
            if self._cache_pre_encode is not None:
                processed_signal = torch.cat([self._cache_pre_encode, processed_signal], dim=-1)
                processed_signal_length = processed_signal_length + self._cache_pre_encode.shape[-1]
                self._cache_pre_encode = processed_signal[
                    :, :, -self._pre_encode_cache_size :
                ].detach()

            (
                self._pred_out_stream,
                transcribed_texts,
                self._cache_last_channel,
                self._cache_last_time,
                self._cache_last_channel_len,
                self._previous_hypotheses,
            ) = self._model.conformer_stream_step(
                processed_signal=processed_signal,
                processed_signal_length=processed_signal_length,
                cache_last_channel=self._cache_last_channel,
                cache_last_time=self._cache_last_time,
                cache_last_channel_len=self._cache_last_channel_len,
                keep_all_outputs=False,
                previous_hypotheses=self._previous_hypotheses,
                previous_pred_out=self._pred_out_stream,
                drop_extra_pre_encoded=None,
                return_transcription=True,
            )

        return _extract_text(transcribed_texts)

    def transcribe_sync(
        self,
        audio_bytes: bytes,
        sample_rate: int,
        language: str,
        speculative: bool,
    ) -> str:
        del language, speculative
        if self._model is None:
            return ""

        audio = np.frombuffer(audio_bytes, dtype=np.int16)
        if audio.size == 0:
            return ""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as handle:
            with wave.open(handle.name, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(sample_rate)
                wav.writeframes(audio.tobytes())
            try:
                result = self._model.transcribe([handle.name], batch_size=1)
            except TypeError:
                result = self._model.transcribe(paths2audio_files=[handle.name], batch_size=1)
        return _extract_text(result)


class StreamingSTTSession:
    """VAD-gated streaming endpoint state for one continuous microphone stream."""

    def __init__(
        self,
        backend: _STTBackend,
        *,
        config: StreamingSTTConfig | None = None,
    ) -> None:
        self._backend = backend
        self._config = config or StreamingSTTConfig()
        self._pre_roll: deque[bytes] = deque(maxlen=self._config.pre_roll_frames)
        self._chunk_buffer = bytearray()
        self._utterance = bytearray()
        self._speech_active = False
        self._consecutive_speech = 0
        self._consecutive_silence = 0
        self._last_partial = ""
        self._last_emitted_partial = ""
        self._step = 0

    @property
    def latest_partial(self) -> str:
        return self._last_partial

    def accept_audio(
        self,
        frame: bytes,
        *,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        vad_probability: float | None = None,
        is_speaking: bool = False,
    ) -> list[StreamingSTTEvent]:
        cfg = self._config
        events: list[StreamingSTTEvent] = []
        self._pre_roll.append(frame)
        speech_prob = 1.0 if vad_probability is None else float(vad_probability)

        if not self._speech_active:
            if speech_prob >= cfg.speech_start_prob:
                self._consecutive_speech += 1
            else:
                self._consecutive_speech = 0
            if self._consecutive_speech >= cfg.speech_start_frames:
                pre_roll = list(self._pre_roll)
                self._start_utterance()
                for pre_frame in pre_roll:
                    events.extend(self._append_active_frame(pre_frame, sample_rate, is_speaking))
                self._pre_roll.clear()
            return events

        events.extend(self._append_active_frame(frame, sample_rate, is_speaking))

        if speech_prob < cfg.speech_end_prob:
            self._consecutive_silence += 1
        else:
            self._consecutive_silence = 0

        if (
            self._consecutive_silence >= cfg.endpoint_silence_frames
            and len(self._utterance) >= cfg.min_utterance_bytes
        ):
            final = self._finalize("silence_endpoint", sample_rate, is_speaking)
            if final is not None:
                events.append(final)
        elif len(self._utterance) >= cfg.max_utterance_bytes:
            final = self._finalize("max_duration", sample_rate, is_speaking)
            if final is not None:
                events.append(final)

        return events

    def flush(self, *, sample_rate: int = DEFAULT_SAMPLE_RATE) -> StreamingSTTEvent | None:
        if not self._speech_active:
            return None
        return self._finalize("flush", sample_rate, is_speaking=False)

    def reset(self) -> None:
        self._backend.reset_stream()
        self._pre_roll.clear()
        self._chunk_buffer.clear()
        self._utterance.clear()
        self._speech_active = False
        self._consecutive_speech = 0
        self._consecutive_silence = 0
        self._last_partial = ""
        self._last_emitted_partial = ""

    def _start_utterance(self) -> None:
        self._backend.reset_stream()
        self._chunk_buffer.clear()
        self._utterance.clear()
        self._speech_active = True
        self._consecutive_silence = 0
        self._last_partial = ""
        self._last_emitted_partial = ""

    def _append_active_frame(
        self,
        frame: bytes,
        sample_rate: int,
        is_speaking: bool,
    ) -> list[StreamingSTTEvent]:
        self._utterance.extend(frame)
        self._chunk_buffer.extend(frame)

        events: list[StreamingSTTEvent] = []
        while len(self._chunk_buffer) >= self._config.chunk_bytes:
            chunk = bytes(self._chunk_buffer[: self._config.chunk_bytes])
            del self._chunk_buffer[: self._config.chunk_bytes]
            text = self._backend.stream_step(chunk, sample_rate).strip()
            self._step += 1
            if text:
                self._last_partial = text
                if text != self._last_emitted_partial:
                    events.append(
                        StreamingSTTEvent(
                            text=text,
                            is_final=False,
                            reason="partial",
                            audio_ms=self._audio_ms(sample_rate),
                            step=self._step,
                            stable_prefix=_stable_prefix(self._last_emitted_partial, text),
                            barge_in=is_speaking,
                        )
                    )
                    self._last_emitted_partial = text
        return events

    def _finalize(
        self,
        reason: str,
        sample_rate: int,
        is_speaking: bool,
    ) -> StreamingSTTEvent | None:
        if self._chunk_buffer:
            text = self._backend.stream_step(bytes(self._chunk_buffer), sample_rate).strip()
            self._step += 1
            self._chunk_buffer.clear()
            if text:
                self._last_partial = text

        audio = bytes(self._utterance)
        text = self._last_partial.strip()
        if not text:
            text = self._backend.transcribe_sync(
                audio,
                sample_rate,
                "en",
                False,
            ).strip()

        audio_ms = self._audio_ms(sample_rate)
        self.reset()
        if not text:
            return None
        return StreamingSTTEvent(
            text=text,
            is_final=True,
            reason=reason,
            audio_ms=audio_ms,
            step=self._step,
            stable_prefix=text,
            barge_in=is_speaking,
            audio_bytes=audio,
        )

    def _audio_ms(self, sample_rate: int) -> int:
        return round(len(self._utterance) / 2 / sample_rate * 1000)


class ResidentSTT:
    """Resident ASR model facade for full-utterance and streaming callers."""

    def __init__(
        self,
        model: str = DEFAULT_STREAMING_MODEL,
        device: str = "cuda",
        compute_type: str = "float16",
        streaming_config: StreamingSTTConfig | None = None,
    ) -> None:
        self._model_name = _normalize_model_name(model)
        self._device = device
        self._compute_type = compute_type
        self._backend: _STTBackend | None = None
        self._streaming_config = streaming_config or StreamingSTTConfig()
        self._stream_session: StreamingSTTSession | None = None
        self._stream_finals: deque[StreamingSTTEvent] = deque(maxlen=16)

    @property
    def is_loaded(self) -> bool:
        return self._backend is not None

    @property
    def supports_streaming(self) -> bool:
        return bool(self._backend and self._backend.supports_streaming)

    @property
    def latest_partial(self) -> str:
        if self._stream_session is None:
            return ""
        return self._stream_session.latest_partial

    def load(self) -> None:
        """Load the configured ASR backend. Call once at daemon startup."""
        try:
            if _uses_whisper_backend(self._model_name):
                backend: _STTBackend = _WhisperBackend(
                    self._model_name,
                    self._device,
                    self._compute_type,
                )
            else:
                backend = _NeMoStreamingBackend(
                    self._model_name,
                    self._device,
                    self._compute_type,
                )
            backend.load()
            self._backend = backend
            if backend.supports_streaming:
                self._stream_session = StreamingSTTSession(
                    backend,
                    config=self._streaming_config,
                )
        except Exception:
            log.exception("Failed to load STT model %s - STT unavailable", self._model_name)
            self._backend = None
            self._stream_session = None

    async def transcribe(
        self,
        audio_bytes: bytes,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        language: str = "en",
        _speculative: bool = False,
    ) -> str:
        """Transcribe PCM audio bytes in the legacy full-utterance path."""
        if self._backend is None:
            return ""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            _stt_executor,
            self._transcribe_sync,
            audio_bytes,
            sample_rate,
            language,
            _speculative,
        )

    def _transcribe_sync(
        self,
        audio_bytes: bytes,
        sample_rate: int,
        language: str,
        speculative: bool = False,
    ) -> str:
        try:
            assert self._backend is not None
            return self._backend.transcribe_sync(audio_bytes, sample_rate, language, speculative)
        except Exception:
            log.exception("STT transcription failed")
            return ""

    async def accept_stream_frame(
        self,
        frame: bytes,
        *,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        vad_probability: float | None = None,
        is_speaking: bool = False,
    ) -> list[StreamingSTTEvent]:
        """Feed one PCM frame to the streaming ASR session.

        Returns newly emitted partial/final events and stores finals for CPAL
        to poll through ``pop_stream_final``.
        """
        if self._stream_session is None:
            return []

        loop = asyncio.get_running_loop()
        events = await loop.run_in_executor(
            _stt_executor,
            partial(
                self._stream_session.accept_audio,
                frame,
                sample_rate=sample_rate,
                vad_probability=vad_probability,
                is_speaking=is_speaking,
            ),
        )
        for event in events:
            if event.is_final:
                self._stream_finals.append(event)
            self._publish_stream_event(event)
        return events

    def pop_stream_final(self) -> StreamingSTTEvent | None:
        if not self._stream_finals:
            return None
        return self._stream_finals.popleft()

    def _publish_stream_event(self, event: StreamingSTTEvent) -> None:
        try:
            shm_dir = Path(os.environ.get("HAPAX_DAIMONION_SHM", "/dev/shm/hapax-daimonion"))
            shm_dir.mkdir(parents=True, exist_ok=True)
            target = shm_dir / ("stt-final.txt" if event.is_final else "stt-partial.txt")
            tmp = target.with_suffix(target.suffix + ".tmp")
            tmp.write_text(event.text + "\n", encoding="utf-8")
            os.replace(tmp, target)
        except Exception:
            log.debug("streaming STT SHM publish failed", exc_info=True)


def _extract_prosody(
    audio: np.ndarray,
    sample_rate: int,
    word_timestamps: list[dict[str, float | str]],
) -> None:
    """Extract and publish prosodic features (best-effort, never blocks)."""
    try:
        from shared.prosody import extract_prosody, write_prosody

        features = extract_prosody(audio, sample_rate, word_timestamps)
        write_prosody(features)
    except Exception:
        log.debug("Prosody extraction failed (non-fatal)", exc_info=True)
