"""Visible Article 50 AI disclosure source for the Reverie wgpu surface."""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_REVERIE_SOURCES_DIR = Path("/dev/shm/hapax-imagination/sources")
DEFAULT_AI_DISCLOSURE_SOURCE_ID = "art50-ai-disclosure"
DEFAULT_OVERLAY_WIDTH = 1920
DEFAULT_OVERLAY_HEIGHT = 1080


def render_ai_disclosure_rgba(
    *,
    width: int = DEFAULT_OVERLAY_WIDTH,
    height: int = DEFAULT_OVERLAY_HEIGHT,
    text: str = "AI",
) -> bytes:
    """Render a transparent full-frame RGBA overlay with a visible AI badge."""

    if width < 160 or height < 90:
        raise ValueError("AI disclosure overlay must be at least 160x90")

    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    margin = max(18, min(width, height) // 48)
    badge_h = max(48, min(92, height // 11))
    badge_w = max(92, int(badge_h * 1.78))
    x1 = width - margin - badge_w
    y1 = margin
    x2 = width - margin
    y2 = y1 + badge_h

    draw.rounded_rectangle(
        (x1, y1, x2, y2),
        radius=max(6, badge_h // 8),
        fill=(12, 14, 18, 218),
        outline=(245, 245, 238, 230),
        width=max(2, badge_h // 22),
    )

    font = _load_badge_font(max(24, int(badge_h * 0.52)))
    label = text.strip()[:12] or "AI"
    text_box = draw.textbbox((0, 0), label, font=font)
    text_w = text_box[2] - text_box[0]
    text_h = text_box[3] - text_box[1]
    draw.text(
        (x1 + (badge_w - text_w) / 2, y1 + (badge_h - text_h) / 2 - badge_h * 0.04),
        label,
        fill=(255, 255, 248, 255),
        font=font,
    )

    return image.tobytes("raw", "RGBA")


def write_reverie_ai_disclosure_source(
    *,
    sources_dir: Path = DEFAULT_REVERIE_SOURCES_DIR,
    source_id: str = DEFAULT_AI_DISCLOSURE_SOURCE_ID,
    width: int = DEFAULT_OVERLAY_WIDTH,
    height: int = DEFAULT_OVERLAY_HEIGHT,
    opacity: float = 0.92,
    z_order: int = 900,
    ttl_ms: int = 0,
    text: str = "AI",
) -> Path:
    """Write the visible AI disclosure source protocol directory atomically."""

    rgba = render_ai_disclosure_rgba(width=width, height=height, text=text)
    source_dir = sources_dir / source_id
    source_dir.mkdir(parents=True, exist_ok=True)

    tmp_frame = source_dir / "frame.tmp"
    tmp_frame.write_bytes(rgba)
    tmp_frame.replace(source_dir / "frame.rgba")

    manifest = {
        "source_id": source_id,
        "content_type": "rgba",
        "width": width,
        "height": height,
        "opacity": opacity,
        "layer": 1,
        "blend_mode": "normal",
        "z_order": z_order,
        "ttl_ms": ttl_ms,
        "tags": ["art50", "ai-disclosure", "eu-ai-act"],
    }
    tmp_manifest = source_dir / "manifest.tmp"
    tmp_manifest.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    tmp_manifest.replace(source_dir / "manifest.json")
    return source_dir


def _load_badge_font(size: int):
    from PIL import ImageFont

    font_paths = (
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    )
    for path in font_paths:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


__all__ = [
    "DEFAULT_AI_DISCLOSURE_SOURCE_ID",
    "DEFAULT_OVERLAY_HEIGHT",
    "DEFAULT_OVERLAY_WIDTH",
    "DEFAULT_REVERIE_SOURCES_DIR",
    "render_ai_disclosure_rgba",
    "write_reverie_ai_disclosure_source",
]
