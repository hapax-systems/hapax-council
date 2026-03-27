"""Voice generation pipeline — Chatterbox TTS API and Voxtral TTS."""

from __future__ import annotations

import logging
import wave
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Literal

import httpx
import numpy as np

log = logging.getLogger(__name__)

TTS_URL = "http://localhost:4123"
MAX_TTS_WORKERS = 1  # Sequential to avoid GPU VRAM contention on long demos
VOICE_SAMPLE_PATH = Path(__file__).resolve().parent.parent.parent / "profiles" / "voice-sample.wav"

VOXTRAL_VOICE_ID = "jessica"
VOXTRAL_SAMPLE_RATE = 24000


def check_tts_available() -> bool:
    """Check if the Chatterbox TTS API is reachable."""
    try:
        response = httpx.get(f"{TTS_URL}/docs", timeout=3)
        return response.status_code == 200
    except Exception:
        return False


def check_voxtral_available() -> bool:
    """Check if Mistral API key is available for Voxtral TTS."""
    import subprocess

    try:
        result = subprocess.run(
            ["pass", "show", "api/mistral"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except Exception:
        return False


def generate_voice_segment_voxtral(
    text: str,
    output_path: Path,
    voice_id: str = VOXTRAL_VOICE_ID,
) -> None:
    """Generate a single voice segment using Mistral Voxtral TTS API."""
    import base64
    import os

    output_path.parent.mkdir(parents=True, exist_ok=True)

    from mistralai import Mistral

    api_key = os.environ.get("MISTRAL_API_KEY", "")
    if not api_key:
        raise RuntimeError("MISTRAL_API_KEY is not set")

    client = Mistral(api_key=api_key)

    chunks: list[bytes] = []
    with client.audio.speech.complete(
        model="voxtral-mini-tts-2603",
        input=text,
        voice_id=voice_id,
        response_format="pcm",
        stream=True,
    ) as stream:
        for event in stream:
            if event.event == "speech.audio.delta":
                raw = base64.b64decode(event.data.audio_data)
                f32 = np.frombuffer(raw, dtype="<f4")
                f32 = np.clip(f32, -1.0, 1.0)
                pcm = (f32 * 32767).astype(np.int16)
                chunks.append(pcm.tobytes())

    if not chunks:
        raise RuntimeError(f"Voxtral produced no audio for text: {text[:80]!r}")

    pcm_data = b"".join(chunks)
    with wave.open(str(output_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(VOXTRAL_SAMPLE_RATE)
        wf.writeframes(pcm_data)

    log.info("Generated voice segment (voxtral): %s (%d bytes)", output_path.name, len(pcm_data))


def check_elevenlabs_available() -> bool:
    """Check if ElevenLabs API key is available."""
    try:
        import subprocess

        result = subprocess.run(
            ["pass", "show", "elevenlabs/api-key"], capture_output=True, text=True
        )
        return result.returncode == 0 and len(result.stdout.strip()) > 10
    except Exception:
        return False


def generate_voice_segment_elevenlabs(
    text: str,
    output_path: Path,
    voice_id: str = "pFZP5JQG7iQjIQuC4Bku",  # "Lily" — soft, velvety
    model_id: str = "eleven_multilingual_v2",
) -> None:
    """Generate a voice segment using ElevenLabs API."""
    import subprocess

    output_path.parent.mkdir(parents=True, exist_ok=True)

    api_key = subprocess.run(
        ["pass", "show", "elevenlabs/api-key"], capture_output=True, text=True
    ).stdout.strip()

    response = httpx.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
        headers={
            "xi-api-key": api_key,
            "Content-Type": "application/json",
        },
        json={
            "text": text,
            "model_id": model_id,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
                "style": 0.3,
            },
        },
        timeout=180,
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"ElevenLabs TTS failed (HTTP {response.status_code}): {response.text[:200]}"
        )

    # ElevenLabs returns mp3 by default — convert to WAV for pipeline compatibility
    mp3_path = output_path.with_suffix(".mp3")
    mp3_path.write_bytes(response.content)

    import shutil
    import subprocess as sp

    if shutil.which("ffmpeg"):
        sp.run(
            ["ffmpeg", "-y", "-i", str(mp3_path), "-ar", "24000", "-ac", "1", str(output_path)],
            capture_output=True,
        )
        mp3_path.unlink(missing_ok=True)
    else:
        # No ffmpeg — just rename mp3 to wav (playback may fail)
        mp3_path.rename(output_path)

    log.info(
        "Generated voice segment (elevenlabs): %s (%d bytes)",
        output_path.name,
        output_path.stat().st_size,
    )


def get_wav_duration(path: Path) -> float:
    """Get the duration of a WAV file in seconds."""
    with wave.open(str(path), "rb") as wf:
        return wf.getnframes() / wf.getframerate()


def generate_voice_segment(
    text: str,
    output_path: Path,
    voice_sample: Path | None = None,
    voice_bytes: bytes | None = None,
    exaggeration: float = 0.3,
    cfg_weight: float = 0.7,
) -> None:
    """Generate a single voice segment via Chatterbox TTS API."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sample = voice_sample or VOICE_SAMPLE_PATH

    if voice_bytes or sample.exists():
        sample_data = voice_bytes or sample.read_bytes()
        response = httpx.post(
            f"{TTS_URL}/v1/audio/speech/upload",
            data={
                "input": text,
                "exaggeration": str(exaggeration),
                "cfg_weight": str(cfg_weight),
            },
            files={"voice_file": ("voice-sample.wav", sample_data, "audio/wav")},
            timeout=180,
        )
    else:
        log.warning("No voice sample at %s — using default TTS voice", sample)
        response = httpx.post(
            f"{TTS_URL}/v1/audio/speech",
            json={
                "input": text,
                "exaggeration": exaggeration,
                "cfg_weight": cfg_weight,
            },
            timeout=180,
        )

    if response.status_code != 200:
        raise RuntimeError(
            f"TTS failed (HTTP {response.status_code}): {response.text[:200]}. "
            f"Is Chatterbox running? Start with: "
            f"cd ~/llm-stack && docker compose --profile tts up -d chatterbox"
        )

    output_path.write_bytes(response.content)
    log.info("Generated voice segment: %s (%d bytes)", output_path.name, len(response.content))


def generate_all_voice_segments(
    segments: list[tuple[str, str]],
    output_dir: Path,
    voice_sample: Path | None = None,
    on_progress: Callable[[str], None] | None = None,
    backend: Literal["chatterbox", "voxtral", "elevenlabs", "auto"] = "chatterbox",
) -> list[Path]:
    """Generate WAV files for all segments.

    Args:
        segments: List of (name, text) tuples.
        output_dir: Directory to save WAV files.
        voice_sample: Path to voice sample for Chatterbox cloning.
        on_progress: Optional progress callback.
        backend: TTS backend — "chatterbox" (default), "voxtral", "elevenlabs", or "auto".
    """
    # Resolve backend
    resolved_backend = backend
    if backend == "auto":
        if check_elevenlabs_available():
            resolved_backend = "elevenlabs"
        elif check_tts_available():
            resolved_backend = "chatterbox"
        elif check_voxtral_available():
            resolved_backend = "voxtral"
        else:
            raise RuntimeError(
                "No TTS backend available. Set up ElevenLabs (pass insert elevenlabs/api-key), "
                "start Chatterbox, or configure Voxtral (pass insert api/mistral)."
            )
    # else: backend == "chatterbox", use_kokoro stays False

    if voice_sample is None:
        voice_sample = VOICE_SAMPLE_PATH

    # Pre-read voice sample bytes once for Chatterbox
    voice_bytes: bytes | None = None
    if resolved_backend == "chatterbox" and voice_sample and voice_sample.exists():
        voice_bytes = voice_sample.read_bytes()

    log.info("Using TTS backend: %s", resolved_backend)
    output_dir.mkdir(parents=True, exist_ok=True)

    def _generate_one(i: int, name: str, text: str) -> tuple[int, Path]:
        import time as _time

        output_path = output_dir / f"{name}.wav"
        gen_start = _time.monotonic()
        if resolved_backend == "elevenlabs":
            generate_voice_segment_elevenlabs(text, output_path)
        elif resolved_backend == "voxtral":
            generate_voice_segment_voxtral(text, output_path)
        else:
            generate_voice_segment(
                text,
                output_path,
                voice_sample=voice_sample,
                voice_bytes=voice_bytes,
            )
        gen_elapsed = _time.monotonic() - gen_start

        # Emit TTS timing as span attributes if tracing is active
        try:
            from opentelemetry.trace import get_current_span

            span = get_current_span()
            if span.is_recording():
                audio_dur = get_wav_duration(output_path) if output_path.exists() else 0
                span.set_attribute(f"tts.segment.{name}.gen_seconds", round(gen_elapsed, 2))
                span.set_attribute(f"tts.segment.{name}.audio_seconds", round(audio_dur, 2))
                span.set_attribute(f"tts.segment.{name}.word_count", len(text.split()))
        except Exception:
            pass

        return i, output_path

    with ThreadPoolExecutor(max_workers=MAX_TTS_WORKERS) as pool:
        futures = {
            pool.submit(_generate_one, i, name, text): (i, name)
            for i, (name, text) in enumerate(segments, 1)
        }
        results: dict[int, Path] = {}
        for future in as_completed(futures):
            i, name = futures[future]
            idx, path = future.result()
            results[idx] = path
            if on_progress:
                on_progress(f"Voice {idx}/{len(segments)}: {name}")

    # Return in original order
    return [results[i] for i in sorted(results)]
