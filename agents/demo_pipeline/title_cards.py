"""Gruvbox-styled title card generation with Pillow."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Gruvbox dark palette
BG_COLOR = (40, 40, 40)          # #282828
FG_COLOR = (235, 219, 178)       # #ebdbb2
ACCENT_COLOR = (250, 189, 47)    # #fabd2f (yellow)
SUBTLE_COLOR = (168, 153, 132)   # #a89984 (gray)


def _get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Get a sans-serif font, falling back to default."""
    if bold:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        ]
    else:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        ]
    for name in candidates:
        if Path(name).exists():
            return ImageFont.truetype(name, size)
    return ImageFont.load_default(size=size)


def generate_title_card(
    title: str,
    output_path: Path,
    subtitle: str | None = None,
    size: tuple[int, int] = (1920, 1080),
) -> Path:
    """Generate a Gruvbox-styled title card image with sans-serif typography."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    img = Image.new("RGB", size, BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Title — light weight, larger size
    title_font = _get_font(80)
    bbox = draw.textbbox((0, 0), title, font=title_font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    title_y = size[1] // 2 - th - (40 if subtitle else 0)
    draw.text(
        ((size[0] - tw) // 2, title_y),
        title,
        fill=FG_COLOR,
        font=title_font,
    )

    # Accent line
    line_y = title_y + th + 24
    line_w = 80
    draw.line(
        [(size[0] // 2 - line_w // 2, line_y), (size[0] // 2 + line_w // 2, line_y)],
        fill=ACCENT_COLOR,
        width=3,
    )

    # Subtitle
    if subtitle:
        sub_font = _get_font(32)
        bbox = draw.textbbox((0, 0), subtitle, font=sub_font)
        sw = bbox[2] - bbox[0]
        draw.text(
            ((size[0] - sw) // 2, line_y + 24),
            subtitle,
            fill=SUBTLE_COLOR,
            font=sub_font,
        )

    img.save(output_path)
    return output_path


def generate_scene_title(
    title: str,
    output_path: Path,
    size: tuple[int, int] = (1920, 1080),
) -> Path:
    """Generate a brief scene title overlay card."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", size, BG_COLOR)
    draw = ImageDraw.Draw(img)
    font = _get_font(52)
    bbox = draw.textbbox((0, 0), title, font=font)
    x = (size[0] - (bbox[2] - bbox[0])) // 2
    y = (size[1] - (bbox[3] - bbox[1])) // 2
    draw.text((x, y), title, fill=FG_COLOR, font=font)
    img.save(output_path)
    return output_path
