"""MP4 chapter marker injection via ffmpeg."""
from __future__ import annotations

import json
import logging
import re
import subprocess
import tempfile
from pathlib import Path

from agents.demo_models import DemoScript
from agents.demo_pipeline.audio_convert import get_ffmpeg_path
from agents.demo_pipeline.video import (
    CROSSFADE_DURATION,
    SCENE_TITLE_DURATION,
    TITLE_DURATION,
)

log = logging.getLogger(__name__)


def _get_ffprobe_path() -> str:
    """Derive ffprobe path from ffmpeg path (imageio_ffmpeg bundles both)."""
    ffmpeg = get_ffmpeg_path()
    return ffmpeg.replace("ffmpeg", "ffprobe")


def _get_wav_duration(wav_path: Path) -> float | None:
    """Get WAV file duration in seconds using ffprobe.

    Returns None if the file doesn't exist or ffprobe fails.
    """
    if not wav_path.exists():
        return None

    ffprobe = _get_ffprobe_path()
    cmd = [
        ffprobe,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        str(wav_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)  # noqa: S603
        if result.returncode != 0:
            log.warning("ffprobe failed for %s: %s", wav_path, result.stderr)
            return None
        data = json.loads(result.stdout)
        return float(data["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        log.warning("Could not parse ffprobe output for %s: %s", wav_path, exc)
        return None


def generate_ffmetadata(chapters: list[tuple[str, float, float]]) -> str:
    """Produce ffmetadata INI format with chapter markers.

    Args:
        chapters: List of (title, start_seconds, end_seconds) tuples.

    Returns:
        ffmetadata INI string with TIMEBASE=1/1000 and START/END in ms.
    """
    lines = [";FFMETADATA1"]
    for title, start_s, end_s in chapters:
        start_ms = int(start_s * 1000)
        end_ms = int(end_s * 1000)
        lines.append("")
        lines.append("[CHAPTER]")
        lines.append("TIMEBASE=1/1000")
        lines.append(f"START={start_ms}")
        lines.append(f"END={end_ms}")
        lines.append(f"title={title}")
    return "\n".join(lines) + "\n"


def build_chapter_list_from_script(
    script: DemoScript,
    audio_dir: Path | None = None,
) -> list[tuple[str, float, float]]:
    """Compute chapter boundaries matching video.py's assembly logic.

    Accounts for crossfade overlap: each non-first clip overlaps by
    CROSSFADE_DURATION with the previous clip.

    Args:
        script: The demo script with scenes.
        audio_dir: Directory containing WAV narration files. If None,
            duration_hint values are used for all scenes.

    Returns:
        List of (title, start_seconds, end_seconds) tuples.
    """
    chapters: list[tuple[str, float, float]] = []
    cursor = 0.0  # Current position in the timeline
    clip_index = 0  # Track which clip we're on for crossfade

    # --- Intro ---
    intro_duration = TITLE_DURATION
    if audio_dir:
        wav_dur = _get_wav_duration(audio_dir / "00-intro.wav")
        if wav_dur is not None:
            intro_duration = wav_dur

    intro_start = cursor
    cursor += intro_duration
    chapters.append(("Introduction", intro_start, cursor))
    clip_index += 1

    # --- Scenes ---
    for i, scene in enumerate(script.scenes, start=1):
        slug = re.sub(r"[^a-z0-9]+", "-", scene.title.lower()).strip("-")

        # Scene title card clip
        if clip_index > 0:
            cursor -= CROSSFADE_DURATION
        scene_chapter_start = cursor
        cursor += SCENE_TITLE_DURATION
        clip_index += 1

        # Screenshot clip
        cursor -= CROSSFADE_DURATION  # always after first clip at this point
        screenshot_duration = scene.duration_hint
        if audio_dir:
            wav_dur = _get_wav_duration(audio_dir / f"{i:02d}-{slug}.wav")
            if wav_dur is not None:
                screenshot_duration = wav_dur
        cursor += screenshot_duration
        clip_index += 1

        chapters.append((scene.title, scene_chapter_start, cursor))

    # --- Outro ---
    if clip_index > 0:
        cursor -= CROSSFADE_DURATION

    outro_duration = TITLE_DURATION
    if audio_dir:
        wav_dur = _get_wav_duration(audio_dir / "99-outro.wav")
        if wav_dur is not None:
            outro_duration = wav_dur

    outro_start = cursor
    cursor += outro_duration
    chapters.append(("Outro", outro_start, cursor))

    return chapters


def inject_chapters(
    video_path: Path,
    chapters: list[tuple[str, float, float]],
    output_path: Path | None = None,
) -> Path:
    """Inject chapter markers into an MP4 file using ffmpeg.

    Writes a temporary ffmetadata file and runs ffmpeg to copy the video
    stream while attaching chapter metadata.

    Args:
        video_path: Path to the input MP4.
        chapters: List of (title, start_seconds, end_seconds) tuples.
        output_path: Path for the output file. If None, replaces in-place
            via temp file + rename.

    Returns:
        Path to the output file with chapters embedded.

    Raises:
        subprocess.CalledProcessError: If ffmpeg exits with non-zero status.
    """
    metadata_content = generate_ffmetadata(chapters)
    replace_in_place = output_path is None

    if replace_in_place:
        output_path = video_path.with_suffix(".chaptered.mp4")

    ffmpeg = get_ffmpeg_path()

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, prefix="ffmeta_"
    ) as f:
        f.write(metadata_content)
        metadata_path = Path(f.name)

    try:
        cmd = [
            ffmpeg,
            "-y",
            "-i", str(video_path),
            "-i", str(metadata_path),
            "-map_metadata", "1",
            "-codec", "copy",
            str(output_path),
        ]
        log.info("Injecting %d chapters into %s", len(chapters), video_path.name)

        result = subprocess.run(cmd, capture_output=True, text=True)  # noqa: S603
        if result.returncode != 0:
            log.error("ffmpeg stderr: %s", result.stderr)
            raise subprocess.CalledProcessError(
                result.returncode, cmd, result.stdout, result.stderr
            )

        if replace_in_place:
            output_path.replace(video_path)
            log.info("Chapters injected in-place: %s", video_path)
            return video_path

        log.info("Chapters injected: %s", output_path)
        return output_path

    finally:
        metadata_path.unlink(missing_ok=True)
