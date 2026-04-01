"""Content source protocol writer for imagination fragments.

Renders text to RGBA and writes the per-fragment directory format
under sources/ for the Rust ContentSourceManager.
"""

from __future__ import annotations

import json
import logging
import textwrap
from pathlib import Path

from agents.imagination import ImaginationFragment

log = logging.getLogger(__name__)

SOURCES_DIR = Path("/dev/shm/hapax-imagination/sources")
TEXT_WIDTH = 640
TEXT_HEIGHT = 360


def write_source_protocol(
    fragment: ImaginationFragment,
    resolved_paths: list[Path],
    sources_dir: Path | None = None,
) -> None:
    """Write content using the source protocol.

    Creates a directory per fragment in sources/ with manifest.json + frame.rgba.
    Text is rendered to an RGBA buffer via Pillow.
    """
    if sources_dir is None:
        sources_dir = SOURCES_DIR

    source_id = f"imagination-{fragment.id}"
    source_dir = sources_dir / source_id

    # Clean up previous imagination sources (replaced by this one)
    import shutil

    if sources_dir.exists():
        for old in sources_dir.iterdir():
            if old.is_dir() and old.name.startswith("imagination-") and old.name != source_id:
                shutil.rmtree(old, ignore_errors=True)

    source_dir.mkdir(parents=True, exist_ok=True)

    rgba_data, width, height = _render_text_to_rgba(fragment.narrative)

    frame_path = source_dir / "frame.rgba"
    tmp_frame = source_dir / "frame.tmp"
    tmp_frame.write_bytes(rgba_data)
    tmp_frame.rename(frame_path)

    manifest = {
        "source_id": source_id,
        "content_type": "rgba",
        "width": width,
        "height": height,
        "opacity": fragment.salience,
        "layer": 1,
        "blend_mode": "screen",
        "z_order": 10,
        "ttl_ms": 0,
        "tags": ["imagination"],
    }

    tmp = source_dir / "manifest.tmp"
    tmp.write_text(json.dumps(manifest))
    tmp.rename(source_dir / "manifest.json")


def _render_text_to_rgba(
    text: str,
    width: int = TEXT_WIDTH,
    height: int = TEXT_HEIGHT,
) -> tuple[bytes, int, int]:
    """Render text to an RGBA byte buffer using Pillow."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("/usr/share/fonts/TTF/JetBrainsMono-Regular.ttf", 18)
    except OSError:
        try:
            font = ImageFont.truetype("/usr/share/fonts/TTF/DejaVuSans.ttf", 18)
        except OSError:
            font = ImageFont.load_default()

    wrapped = textwrap.fill(text, width=50)
    lines = wrapped.split("\n")

    line_height = 24
    total_height = len(lines) * line_height
    y_start = max(0, (height - total_height) // 2)

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        text_width = bbox[2] - bbox[0]
        x = max(0, (width - text_width) // 2)
        y = y_start + i * line_height
        draw.text((x, y), line, fill=(255, 255, 255, 180), font=font)

    return img.tobytes("raw", "RGBA"), width, height
