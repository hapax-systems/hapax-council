"""Video assembly pipeline — screenshots + audio -> MP4."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path

from moviepy import ImageClip, VideoFileClip, AudioFileClip, concatenate_videoclips, vfx

log = logging.getLogger(__name__)

CROSSFADE_DURATION = 0.5
TITLE_DURATION = 3.0
SCENE_TITLE_DURATION = 1.5
FPS = 24


def _title_clip(
    image_path: Path,
    duration: float = TITLE_DURATION,
    audio_path: Path | None = None,
) -> ImageClip:
    """Create a clip from a title card image, optionally with narration audio."""
    clip = ImageClip(str(image_path))
    if audio_path and audio_path.exists():
        audio = AudioFileClip(str(audio_path))
        return clip.with_duration(audio.duration).with_audio(audio)
    return clip.with_duration(duration)


def _build_scene_clips(
    screenshots: dict[str, Path],
    durations: dict[str, float],
    audio_dir: Path | None = None,
    title_dir: Path | None = None,
) -> list[ImageClip]:
    """Build video clips for each scene — image + optional audio."""
    clips = []
    for title, img_path in screenshots.items():
        if not img_path.exists():
            log.warning("Screenshot missing: %s", img_path)
            continue

        # Insert scene title card if title_dir provided
        if title_dir:
            from agents.demo_pipeline.title_cards import generate_scene_title

            title_path = title_dir / f"title-{img_path.stem}.png"
            generate_scene_title(title, title_path)
            clips.append(ImageClip(str(title_path)).with_duration(SCENE_TITLE_DURATION))

        # Use VideoFileClip for mp4 screencasts, ImageClip for static images
        if img_path.suffix == ".mp4":
            clip = VideoFileClip(str(img_path))
        else:
            clip = ImageClip(str(img_path))

        # Try to attach audio
        audio_name = img_path.stem  # e.g., "01-dashboard"
        audio_path = audio_dir / f"{audio_name}.wav" if audio_dir else None

        if audio_path and audio_path.exists():
            audio = AudioFileClip(str(audio_path))
            if img_path.suffix == ".mp4":
                # For video clips: loop if shorter than audio, trim if longer
                if clip.duration < audio.duration:
                    clip = clip.with_effects([vfx.Loop(duration=audio.duration)])
                clip = clip.subclipped(0, audio.duration)
            clip = clip.with_duration(audio.duration).with_audio(audio)
        else:
            # Fall back to duration hint
            target_dur = durations.get(title, 5.0)
            if img_path.suffix == ".mp4" and clip.duration < target_dur:
                clip = clip.with_effects([vfx.Loop(duration=target_dur)])
            clip = clip.with_duration(target_dur)

        clips.append(clip)
    return clips


def _close_clips(*clip_lists: list) -> None:
    """Safely close all MoviePy clips to release file handles and memory."""
    for clips in clip_lists:
        for clip in clips:
            try:
                if hasattr(clip, "audio") and clip.audio is not None:
                    clip.audio.close()
                clip.close()
            except Exception:
                pass


async def assemble_video(
    intro_card: Path,
    outro_card: Path,
    screenshots: dict[str, Path],
    durations: dict[str, float],
    audio_dir: Path | None,
    output_path: Path,
    on_progress: Callable[[str], None] | None = None,
) -> tuple[Path, float]:
    """Assemble final video from title cards, screenshots, and audio.

    Returns:
        Tuple of (output_path, duration_seconds).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)
        else:
            log.info(msg)

    progress("Building video clips...")

    all_clips: list = []
    final = None
    actual_duration = 0.0

    try:
        # Intro (with narration audio if available)
        intro_audio = audio_dir / "00-intro.wav" if audio_dir else None
        if intro_card.exists():
            all_clips.append(_title_clip(intro_card, audio_path=intro_audio))

        # Scene clips (with scene title cards)
        title_dir = output_path.parent / "scene-titles"
        scene_clips = _build_scene_clips(screenshots, durations, audio_dir, title_dir=title_dir)
        all_clips.extend(scene_clips)

        # Outro (with narration audio if available)
        outro_audio = audio_dir / "99-outro.wav" if audio_dir else None
        if outro_card.exists():
            all_clips.append(_title_clip(outro_card, audio_path=outro_audio))

        if not all_clips:
            raise ValueError("No clips to assemble — check screenshots and title cards")

        progress(f"Concatenating {len(all_clips)} clips with {CROSSFADE_DURATION}s crossfades...")

        # Apply crossfade to all clips except the first
        faded_clips = [all_clips[0]]
        for clip in all_clips[1:]:
            faded_clips.append(clip.with_effects([vfx.CrossFadeIn(CROSSFADE_DURATION)]))

        final = concatenate_videoclips(
            faded_clips,
            padding=-CROSSFADE_DURATION,
            method="compose",
        )

        actual_duration = final.duration
        progress(f"Rendering MP4 ({actual_duration:.1f}s)...")

        await asyncio.to_thread(
            final.write_videofile,
            str(output_path),
            fps=FPS,
            codec="libx264",
            audio_codec="aac",
            preset="medium",
            threads=4,
            logger=None,
        )

        progress(f"Video complete: {output_path}")
        return output_path, actual_duration

    finally:
        if final is not None:
            try:
                final.close()
            except Exception:
                pass
        _close_clips(all_clips)
