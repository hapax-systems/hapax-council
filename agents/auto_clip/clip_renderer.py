"""Render vertical 9:16 Shorts from raw horizontal clips."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

from agents.auto_clip.segment_detection import DecoderChannel

log = logging.getLogger(__name__)

OUTPUT_WIDTH = 1080
OUTPUT_HEIGHT = 1920
V5_BYLINE = "hapax.github.io | CC-BY-4.0"

CHANNEL_ACCENT: dict[DecoderChannel, str] = {
    DecoderChannel.VISUAL: "0xE78A4E",
    DecoderChannel.SONIC: "0x7DAEA3",
    DecoderChannel.LINGUISTIC: "0xD3869B",
    DecoderChannel.TYPOGRAPHIC: "0xA9B665",
    DecoderChannel.STRUCTURAL: "0xEA6962",
    DecoderChannel.MARKER_AS_MEMBERSHIP: "0xD8A657",
}


@dataclass(frozen=True)
class RenderedClip:
    path: Path
    width: int
    height: int
    decoder_channel: DecoderChannel
    has_watermark: bool


def _build_filter_graph(
    hook_text: str,
    channel: DecoderChannel,
) -> str:
    accent = CHANNEL_ACCENT.get(channel, "0xEBDBB2")
    safe_hook = hook_text.replace("'", "’").replace(":", "\\:")
    safe_byline = V5_BYLINE.replace(":", "\\:")
    channel_label = channel.value.replace("_", " ").upper()

    filters = [
        f"scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:force_original_aspect_ratio=decrease",
        f"pad={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=0x1D2021",
        f"drawtext=text='{safe_hook}':fontsize=42:fontcolor={accent}"
        ":x=(w-text_w)/2:y=h*0.12:enable='lt(t,4)'",
        f"drawtext=text='{channel_label}':fontsize=28:fontcolor={accent}:x=(w-text_w)/2:y=h*0.06",
        f"drawtext=text='{safe_byline}':fontsize=20:fontcolor=0x928374:x=(w-text_w)/2:y=h-60",
    ]
    return ",".join(filters)


def render_clip(
    raw_clip: Path,
    output_dir: Path,
    clip_id: str,
    hook_text: str,
    decoder_channel: DecoderChannel,
    suggested_title: str,
) -> RenderedClip | None:
    output_path = output_dir / f"{clip_id}_short.mp4"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    vf = _build_filter_graph(hook_text, decoder_channel)

    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-i",
        str(raw_clip),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "22",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        "-metadata",
        f"title={suggested_title}",
        "-metadata",
        f"comment={V5_BYLINE}",
        str(output_path),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if result.returncode != 0:
            log.warning("ffmpeg render failed: %s", result.stderr[:500])
            return None
        if not output_path.is_file() or output_path.stat().st_size < 1:
            return None
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        log.warning("ffmpeg render error: %s", exc)
        return None

    return RenderedClip(
        path=output_path,
        width=OUTPUT_WIDTH,
        height=OUTPUT_HEIGHT,
        decoder_channel=decoder_channel,
        has_watermark=True,
    )
