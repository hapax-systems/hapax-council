"""Tests for the HTML player generator module."""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from agents.demo_models import DemoScene, DemoScript, ScreenshotSpec
from agents.demo_pipeline.html_player import (
    _audio_to_base64,
    _make_title_card_background,
    _png_to_jpeg_base64,
    generate_html_player,
)


def _make_script(
    *,
    title: str = "Test Demo",
    audience: str = "family",
    scene_count: int = 1,
) -> DemoScript:
    """Build a minimal DemoScript for tests."""
    scenes = []
    for i in range(scene_count):
        scenes.append(
            DemoScene(
                title=f"Scene {i + 1}",
                narration=f"Narration for scene {i + 1}",
                duration_hint=5.0,
                key_points=[f"Point {i + 1}a", f"Point {i + 1}b"],
                screenshot=ScreenshotSpec(url="http://localhost:5173"),
            )
        )
    return DemoScript(
        title=title,
        audience=audience,
        scenes=scenes,
        intro_narration="Welcome to the demo",
        outro_narration="Thanks for watching",
    )


def _create_png(path: Path, mode: str = "RGB", size: tuple[int, int] = (100, 80)) -> Path:
    """Create a tiny PNG test image."""
    img = Image.new(mode, size, (200, 100, 50) if mode == "RGB" else (200, 100, 50, 128))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path


# ── _png_to_jpeg_base64 ────────────────────────────────────────


class TestPngToJpegBase64:
    def test_returns_data_uri(self, tmp_path: Path) -> None:
        png = _create_png(tmp_path / "shot.png")
        result = _png_to_jpeg_base64(png)
        assert result.startswith("data:image/jpeg;base64,")
        # Base64 payload should be non-trivial
        payload = result.split(",", 1)[1]
        assert len(payload) > 50

    def test_handles_rgba(self, tmp_path: Path) -> None:
        png = _create_png(tmp_path / "rgba.png", mode="RGBA")
        result = _png_to_jpeg_base64(png)
        assert result.startswith("data:image/jpeg;base64,")


# ── _make_title_card_background ──────────────────────────────────


class TestMakeTitleCardBackground:
    def test_returns_data_uri(self) -> None:
        result = _make_title_card_background()
        assert isinstance(result, str)
        assert result.startswith("data:image/jpeg;base64,")


# ── generate_html_player ───────────────────────────────────────


class TestGenerateHtmlPlayerBasic:
    """Basic HTML generation without audio."""

    def test_creates_html_file(self, tmp_path: Path) -> None:
        script = _make_script()
        png = _create_png(tmp_path / "screenshots" / "shot.png")
        screenshot_map = {"Scene 1": png}
        out = tmp_path / "output" / "player.html"

        result = generate_html_player(script, screenshot_map, output_path=out)

        assert result == out
        assert out.exists()

    def test_html_contains_title(self, tmp_path: Path) -> None:
        script = _make_script(title="My Cool Demo")
        out = tmp_path / "player.html"
        generate_html_player(script, {}, output_path=out)

        html = out.read_text()
        assert "My Cool Demo" in html

    def test_html_contains_scene_titles(self, tmp_path: Path) -> None:
        script = _make_script(scene_count=2)
        out = tmp_path / "player.html"
        generate_html_player(script, {}, output_path=out)

        html = out.read_text()
        assert "Scene 1" in html
        assert "Scene 2" in html

    def test_html_contains_base64_images(self, tmp_path: Path) -> None:
        script = _make_script()
        png = _create_png(tmp_path / "shot.png")
        out = tmp_path / "player.html"
        generate_html_player(script, {"Scene 1": png}, output_path=out)

        html = out.read_text()
        assert "data:image/jpeg;base64," in html

    def test_html_contains_gruvbox_colors(self, tmp_path: Path) -> None:
        script = _make_script()
        out = tmp_path / "player.html"
        generate_html_player(script, {}, output_path=out)

        html = out.read_text()
        assert "#282828" in html
        assert "#ebdbb2" in html
        assert "#fabd2f" in html

    def test_has_intro_and_outro_title_slides(self, tmp_path: Path) -> None:
        script = _make_script()
        out = tmp_path / "player.html"
        generate_html_player(script, {}, output_path=out)

        html = out.read_text()
        # Intro narration should appear
        assert "Welcome to the demo" in html
        # Outro narration
        assert "Thanks for watching" in html
        # "Thank You" outro title
        assert "Thank You" in html

    def test_audience_label_resolved(self, tmp_path: Path) -> None:
        script = _make_script(audience="technical-peer")
        out = tmp_path / "player.html"
        generate_html_player(script, {}, output_path=out)

        html = out.read_text()
        assert "Technical Peers" in html

    def test_on_progress_called(self, tmp_path: Path) -> None:
        script = _make_script()
        out = tmp_path / "player.html"
        messages: list[str] = []
        generate_html_player(script, {}, output_path=out, on_progress=messages.append)

        assert len(messages) == 2
        assert "Building" in messages[0]
        assert str(out) in messages[1]


class TestGenerateHtmlPlayerWithAudio:
    """HTML generation with audio files present."""

    def test_audio_data_uris_in_html(self, tmp_path: Path) -> None:
        script = _make_script(scene_count=1)
        audio_dir = tmp_path / "audio"
        audio_dir.mkdir()

        # Create fake MP3 files matching the naming convention
        (audio_dir / "00-intro.mp3").write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 100)
        (audio_dir / "01-scene-1.mp3").write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 100)
        (audio_dir / "99-outro.mp3").write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 100)

        out = tmp_path / "player.html"
        generate_html_player(script, {}, audio_dir=audio_dir, output_path=out)

        html = out.read_text()
        assert "data:audio/mpeg;base64," in html

    def test_partial_audio_some_scenes_without(self, tmp_path: Path) -> None:
        script = _make_script(scene_count=2)
        audio_dir = tmp_path / "audio"
        audio_dir.mkdir()

        # Only intro audio, no scene or outro audio
        (audio_dir / "00-intro.mp3").write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 50)

        out = tmp_path / "player.html"
        generate_html_player(script, {}, audio_dir=audio_dir, output_path=out)

        html = out.read_text()
        # Should still generate valid HTML
        assert "data:audio/mpeg;base64," in html
        assert out.exists()


class TestGenerateHtmlPlayerNoAudioFallback:
    """HTML generation with no audio at all."""

    def test_no_audio_data_in_html(self, tmp_path: Path) -> None:
        script = _make_script()
        out = tmp_path / "player.html"
        generate_html_player(script, {}, audio_dir=None, output_path=out)

        html = out.read_text()
        assert "data:audio" not in html

    def test_nonexistent_audio_dir(self, tmp_path: Path) -> None:
        script = _make_script()
        out = tmp_path / "player.html"
        generate_html_player(
            script, {}, audio_dir=tmp_path / "no-such-dir", output_path=out
        )

        html = out.read_text()
        assert "data:audio" not in html
        assert out.exists()


class TestGenerateHtmlPlayerKeyPoints:
    """Verify key points appear in the generated HTML."""

    def test_key_points_in_html(self, tmp_path: Path) -> None:
        script = _make_script(scene_count=1)
        out = tmp_path / "player.html"
        generate_html_player(script, {}, output_path=out)

        html = out.read_text()
        assert "Point 1a" in html
        assert "Point 1b" in html

    def test_multiple_scenes_key_points(self, tmp_path: Path) -> None:
        script = _make_script(scene_count=3)
        out = tmp_path / "player.html"
        generate_html_player(script, {}, output_path=out)

        html = out.read_text()
        for i in range(1, 4):
            assert f"Point {i}a" in html
            assert f"Point {i}b" in html
