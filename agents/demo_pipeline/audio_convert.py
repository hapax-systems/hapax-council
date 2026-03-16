"""WAV-to-MP3 audio conversion using ffmpeg (via imageio_ffmpeg)."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


def get_ffmpeg_path() -> str:
    """Get the ffmpeg binary path bundled with imageio_ffmpeg (via MoviePy)."""
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def wav_to_mp3(
    wav_path: str | Path,
    mp3_path: str | Path | None = None,
    bitrate: str = "128k",
) -> Path:
    """Convert a WAV file to MP3 using ffmpeg.

    Args:
        wav_path: Path to the input WAV file.
        mp3_path: Path for the output MP3 file. If None, uses wav_path with .mp3 extension.
        bitrate: MP3 bitrate (default: 128k).

    Returns:
        Path to the created MP3 file.

    Raises:
        FileNotFoundError: If the input WAV file does not exist.
        subprocess.CalledProcessError: If ffmpeg exits with a non-zero return code.
    """
    wav_path = Path(wav_path)
    if not wav_path.exists():
        msg = f"WAV file not found: {wav_path}"
        raise FileNotFoundError(msg)

    if mp3_path is None:
        mp3_path = wav_path.with_suffix(".mp3")
    else:
        mp3_path = Path(mp3_path)

    ffmpeg = get_ffmpeg_path()
    cmd = [ffmpeg, "-y", "-i", str(wav_path), "-b:a", bitrate, str(mp3_path)]
    log.info("Converting %s -> %s", wav_path.name, mp3_path.name)

    result = subprocess.run(cmd, capture_output=True, text=True)  # noqa: S603
    if result.returncode != 0:
        log.error("ffmpeg stderr: %s", result.stderr)
        raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)

    if not mp3_path.exists():
        log.error("ffmpeg returned 0 but output file not created: %s", mp3_path)
        msg = f"ffmpeg did not create output file: {mp3_path}"
        raise FileNotFoundError(msg)

    log.info(
        "Converted %s (%.1f KB -> %.1f KB)",
        wav_path.name,
        wav_path.stat().st_size / 1024,
        mp3_path.stat().st_size / 1024,
    )
    return mp3_path


def convert_all_wav_to_mp3(
    audio_dir: str | Path,
    output_dir: str | Path | None = None,
) -> dict[str, Path]:
    """Batch-convert all WAV files in a directory to MP3.

    Args:
        audio_dir: Directory containing WAV files.
        output_dir: Directory for output MP3 files. If None, MP3s are placed next to WAVs.

    Returns:
        Dict mapping file stem to the output MP3 path.
    """
    audio_dir = Path(audio_dir)
    results: dict[str, Path] = {}

    for wav_file in sorted(audio_dir.glob("*.wav")):
        if output_dir is not None:
            mp3_path = Path(output_dir) / f"{wav_file.stem}.mp3"
            mp3_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            mp3_path = None

        results[wav_file.stem] = wav_to_mp3(wav_file, mp3_path)

    log.info("Batch converted %d WAV files to MP3", len(results))
    return results
