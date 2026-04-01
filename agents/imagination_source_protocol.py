"""Content source protocol writer for imagination fragments.

Writes per-fragment content to sources/ for the Rust ContentSourceManager.
Resolved images are converted to RGBA. Text narratives rendered via Pillow.
Each fragment produces one source; previous sources cleaned up on write.
"""

from __future__ import annotations

import json
import logging
import shutil
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

    If resolved_paths contains images, the first is converted to RGBA.
    Otherwise the narrative text is rendered to RGBA via Pillow.
    """
    if sources_dir is None:
        sources_dir = SOURCES_DIR

    source_id = f"imagination-{fragment.id}"
    source_dir = sources_dir / source_id

    # Clean up previous imagination sources
    if sources_dir.exists():
        for old in sources_dir.iterdir():
            if old.is_dir() and old.name.startswith("imagination-") and old.name != source_id:
                shutil.rmtree(old, ignore_errors=True)

    source_dir.mkdir(parents=True, exist_ok=True)

    # Try resolved image first, fall back to text rendering
    rgba_data, width, height = _resolve_to_rgba(resolved_paths, fragment.narrative)

    tmp_frame = source_dir / "frame.tmp"
    tmp_frame.write_bytes(rgba_data)
    tmp_frame.rename(source_dir / "frame.rgba")

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


def _resolve_to_rgba(resolved_paths: list[Path], narrative: str) -> tuple[bytes, int, int]:
    """Convert the best available content to RGBA bytes."""
    # Try each resolved image path
    for path in resolved_paths:
        result = _jpeg_to_rgba(path)
        if result is not None:
            return result

    # Fall back to text rendering
    return _render_text_to_rgba(narrative)


def _jpeg_to_rgba(path: Path) -> tuple[bytes, int, int] | None:
    """Convert a JPEG file to raw RGBA bytes. Returns None on failure."""
    if not path.exists():
        return None
    try:
        from PIL import Image

        img = Image.open(path).convert("RGBA")
        return img.tobytes("raw", "RGBA"), img.width, img.height
    except Exception:
        log.debug("Failed to convert %s to RGBA", path, exc_info=True)
        return None


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
