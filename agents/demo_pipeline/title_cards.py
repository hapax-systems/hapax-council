"""Gruvbox-styled title card generation with Pillow."""

from __future__ import annotations

import os
import tempfile
from io import BytesIO
from pathlib import Path
from struct import unpack

from PIL import Image, ImageDraw, ImageFont

# Gruvbox dark palette
BG_COLOR = (40, 40, 40)  # #282828
FG_COLOR = (235, 219, 178)  # #ebdbb2
ACCENT_COLOR = (250, 189, 47)  # #fabd2f (yellow)
SUBTLE_COLOR = (168, 153, 132)  # #a89984 (gray)
MAX_TITLE_CARD_PIXELS = 7680 * 4320
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_IHDR_LENGTH = b"\x00\x00\x00\r"


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


def _validate_canvas_size(size: tuple[int, int]) -> tuple[int, int]:
    if not isinstance(size, tuple) or len(size) != 2:
        raise ValueError("title card size must be a (width, height) tuple")
    width, height = size
    if isinstance(width, bool) or isinstance(height, bool):
        raise ValueError("title card dimensions must be integer pixels")
    if not isinstance(width, int) or not isinstance(height, int):
        raise ValueError("title card dimensions must be integer pixels")
    if width <= 0 or height <= 0:
        raise ValueError("title card dimensions must be positive")
    if width * height > MAX_TITLE_CARD_PIXELS:
        raise ValueError(f"title card size {width}x{height} exceeds the supported pixel budget")
    return width, height


def _png_dimensions_from_bytes(data: bytes) -> tuple[int, int]:
    if len(data) < 33 or not data.startswith(PNG_SIGNATURE):
        raise RuntimeError("title card encoder did not produce a valid PNG header")
    if data[8:12] != PNG_IHDR_LENGTH:
        raise RuntimeError("title card encoder produced a PNG with an invalid IHDR length")
    if data[12:16] != b"IHDR":
        raise RuntimeError("title card encoder produced a PNG without an IHDR header")
    return unpack(">II", data[16:24])


def _verify_png_dimensions(data: bytes, expected_size: tuple[int, int]) -> None:
    dimensions = _png_dimensions_from_bytes(data)
    if dimensions != expected_size:
        raise RuntimeError(f"title card encoder produced {dimensions}, expected {expected_size}")


def _save_png_verified(img: Image.Image, output_path: Path) -> None:
    encoded = BytesIO()
    img.save(encoded, format="PNG")
    data = encoded.getvalue()
    _verify_png_dimensions(data, img.size)

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "wb",
            delete=False,
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
        ) as tmp:
            tmp.write(data)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_path = Path(tmp.name)
        _verify_png_dimensions(tmp_path.read_bytes(), img.size)
        os.replace(tmp_path, output_path)
        tmp_path = None
        _verify_png_dimensions(output_path.read_bytes(), img.size)
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def generate_title_card(
    title: str,
    output_path: Path,
    subtitle: str | None = None,
    size: tuple[int, int] = (1920, 1080),
) -> Path:
    """Generate a Gruvbox-styled title card image with sans-serif typography."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    size = _validate_canvas_size(size)

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

    _save_png_verified(img, output_path)
    return output_path


def generate_scene_title(
    title: str,
    output_path: Path,
    size: tuple[int, int] = (1920, 1080),
) -> Path:
    """Generate a brief scene title overlay card."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    size = _validate_canvas_size(size)
    img = Image.new("RGB", size, BG_COLOR)
    draw = ImageDraw.Draw(img)
    font = _get_font(52)
    bbox = draw.textbbox((0, 0), title, font=font)
    x = (size[0] - (bbox[2] - bbox[0])) // 2
    y = (size[1] - (bbox[3] - bbox[1])) // 2
    draw.text((x, y), title, fill=FG_COLOR, font=font)
    _save_png_verified(img, output_path)
    return output_path
