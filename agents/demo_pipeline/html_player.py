"""Self-contained HTML player generation from DemoScript + screenshots + audio."""

from __future__ import annotations

import base64
import logging
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from PIL import Image, ImageDraw

from agents.demo_models import DemoScript
from agents.demo_pipeline.slides import AUDIENCE_LABELS
from agents.demo_pipeline.title_cards import ACCENT_COLOR, BG_COLOR

log = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"


def _png_to_jpeg_base64(png_path: Path, quality: int = 85) -> str:
    """Convert a PNG screenshot to a JPEG base64 data URI (~4x smaller).

    RGBA images are composited onto a #282828 background before conversion.
    """
    img = Image.open(png_path)
    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, BG_COLOR)
        bg.paste(img, mask=img.split()[3])
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def _audio_to_base64(mp3_path: Path) -> str:
    """Read an MP3 file and return a data URI."""
    data = mp3_path.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:audio/mpeg;base64,{b64}"


def _video_to_base64(mp4_path: Path) -> str:
    """Read an MP4 video file and return a data URI."""
    data = mp4_path.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:video/mp4;base64,{b64}"


def _make_title_card_background(
    size: tuple[int, int] = (1920, 1080),
) -> str:
    """Generate a solid Gruvbox dark background as base64 JPEG data URI.

    The HTML template renders the actual title text via CSS overlay —
    this just provides the dark background image for the slide container.
    """
    img = Image.new("RGB", size, BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Subtle accent line in the center for visual interest
    line_y = size[1] // 2 + 80
    line_w = min(400, size[0] // 3)
    draw.line(
        [(size[0] // 2 - line_w // 2, line_y), (size[0] // 2 + line_w // 2, line_y)],
        fill=ACCENT_COLOR,
        width=3,
    )

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def _find_audio(audio_dir: Path, prefix: str) -> Path | None:
    """Find an MP3 file in *audio_dir* whose name starts with *prefix*.

    Returns the first match or ``None``.
    """
    for p in sorted(audio_dir.glob(f"{prefix}-*.mp3")):
        return p
    # Also check exact name (e.g. "00-intro.mp3")
    exact = audio_dir / f"{prefix}.mp3"
    if exact.exists():
        return exact
    return None


def generate_html_player(
    script: DemoScript,
    screenshot_map: dict[str, Path],
    audio_dir: Path | None = None,
    output_path: Path | None = None,
    on_progress: callable | None = None,
    audience_display_name: str | None = None,
) -> Path:
    """Build a self-contained HTML player from a DemoScript.

    Args:
        script: The demo script with scenes, narration, etc.
        screenshot_map: Mapping of scene title -> PNG screenshot path.
        audio_dir: Directory containing ``{NN}-{slug}.mp3`` voice files.
        output_path: Where to write the HTML file. Defaults to cwd / ``player.html``.
        on_progress: Optional callback for status messages.

    Returns:
        Path to the generated HTML file.
    """
    if on_progress:
        on_progress("Building HTML player...")

    audience_label = audience_display_name or AUDIENCE_LABELS.get(
        script.audience, script.audience.replace("-", " ").title()
    )

    scenes: list[dict] = []
    scene_id = 0

    # ── Intro title card ────────────────────────────────────────
    intro_image = _make_title_card_background()
    intro_audio: str | None = None
    if audio_dir and audio_dir.is_dir():
        mp3 = _find_audio(audio_dir, "00")
        if mp3:
            intro_audio = _audio_to_base64(mp3)

    # Use duration_hint of 5s for intro if no audio
    intro_duration = 5.0
    scenes.append(
        {
            "id": scene_id,
            "title": script.title,
            "narration": script.intro_narration,
            "key_points": [],
            "image_data": intro_image,
            "audio_data": intro_audio,
            "duration": intro_duration,
            "is_title_slide": True,
        }
    )
    scene_id += 1

    # ── Content scenes ──────────────────────────────────────────
    for i, demo_scene in enumerate(script.scenes, start=1):
        # Visual — may be image (png) or video (mp4)
        visual_path = screenshot_map.get(demo_scene.title)
        is_video = False
        if visual_path and visual_path.exists():
            if visual_path.suffix == ".mp4":
                image_data = _video_to_base64(visual_path)
                is_video = True
            else:
                image_data = _png_to_jpeg_base64(visual_path)
        else:
            # Generate a placeholder background
            image_data = _make_title_card_background()

        # Audio
        scene_audio: str | None = None
        if audio_dir and audio_dir.is_dir():
            mp3 = _find_audio(audio_dir, f"{i:02d}")
            if mp3:
                scene_audio = _audio_to_base64(mp3)

        scenes.append(
            {
                "id": scene_id,
                "title": demo_scene.title,
                "narration": demo_scene.narration,
                "key_points": demo_scene.key_points,
                "slide_table": demo_scene.slide_table,
                "image_data": image_data,
                "audio_data": scene_audio,
                "duration": demo_scene.duration_hint,
                "is_title_slide": False,
                "is_video": is_video,
            }
        )
        scene_id += 1

    # ── Outro title card ────────────────────────────────────────
    outro_image = _make_title_card_background()
    outro_audio: str | None = None
    if audio_dir and audio_dir.is_dir():
        mp3 = _find_audio(audio_dir, "99")
        if mp3:
            outro_audio = _audio_to_base64(mp3)

    outro_duration = 5.0
    scenes.append(
        {
            "id": scene_id,
            "title": "Thank You",
            "narration": script.outro_narration,
            "key_points": [],
            "image_data": outro_image,
            "audio_data": outro_audio,
            "duration": outro_duration,
            "is_title_slide": True,
        }
    )

    total_duration = sum(s["duration"] for s in scenes)
    generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ── Render template ─────────────────────────────────────────
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=True)
    template = env.get_template("player.html.j2")
    html = template.render(
        title=script.title,
        audience=audience_label,
        scenes=scenes,
        total_duration=total_duration,
        generated_at=generated_at,
    )

    # ── Write output ────────────────────────────────────────────
    if output_path is None:
        output_path = Path.cwd() / "player.html"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")

    if on_progress:
        on_progress(f"HTML player written to {output_path}")
    log.info(
        "HTML player written to %s (%d scenes, %.0fs)", output_path, len(scenes), total_duration
    )
    return output_path
