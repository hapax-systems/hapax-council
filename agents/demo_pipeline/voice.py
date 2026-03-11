"""Voice generation pipeline using Chatterbox TTS API."""
from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

TTS_URL = "http://localhost:4123"
MAX_TTS_WORKERS = 1  # Sequential to avoid GPU VRAM contention on long demos
VOICE_SAMPLE_PATH = Path(__file__).resolve().parent.parent.parent / "profiles" / "voice-sample.wav"


def check_tts_available() -> bool:
    """Check if the Chatterbox TTS API is reachable."""
    try:
        response = httpx.get(f"{TTS_URL}/docs", timeout=3)
        return response.status_code == 200
    except Exception:
        return False


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
) -> list[Path]:
    """Generate WAV files for all segments using parallel TTS calls."""
    if voice_sample is None:
        voice_sample = VOICE_SAMPLE_PATH

    # Pre-read voice sample bytes once to avoid repeated file I/O per segment
    voice_bytes: bytes | None = None
    if voice_sample and voice_sample.exists():
        voice_bytes = voice_sample.read_bytes()

    output_dir.mkdir(parents=True, exist_ok=True)

    def _generate_one(i: int, name: str, text: str) -> tuple[int, Path]:
        output_path = output_dir / f"{name}.wav"
        generate_voice_segment(
            text, output_path, voice_sample=voice_sample, voice_bytes=voice_bytes,
        )
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
