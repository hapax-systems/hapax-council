"""Integration test for the video assembly pipeline (no actual TTS or GPU)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PIL", reason="Pillow not installed")

from PIL import Image  # noqa: E402

from agents.demo_models import DemoScene, DemoScript, ScreenshotSpec  # noqa: E402
from agents.demo_pipeline.title_cards import generate_title_card  # noqa: E402
from agents.demo_pipeline.video import _build_scene_clips, _title_clip  # noqa: E402


class TestVideoIntegration:
    @pytest.fixture
    def demo_assets(self, tmp_path) -> tuple[DemoScript, dict[str, Path], Path]:
        """Create all assets needed for video assembly."""
        script = DemoScript(
            title="Integration Test Demo",
            audience="family",
            scenes=[
                DemoScene(
                    title="Dashboard",
                    narration="Here is the dashboard.",
                    duration_hint=5.0,
                    screenshot=ScreenshotSpec(url="http://localhost:5173"),
                ),
            ],
            intro_narration="Welcome.",
            outro_narration="Goodbye.",
        )

        # Create fake screenshot
        ss_dir = tmp_path / "screenshots"
        ss_dir.mkdir()
        img = Image.new("RGB", (1920, 1080), (40, 40, 40))
        ss_path = ss_dir / "01-dashboard.png"
        img.save(ss_path)

        screenshots = {"Dashboard": ss_path}
        return script, screenshots, tmp_path

    def test_title_cards_generated(self, tmp_path):
        intro = generate_title_card("Test", tmp_path / "intro.png", subtitle="For family")
        outro = generate_title_card("Thanks", tmp_path / "outro.png")
        assert intro.exists()
        assert outro.exists()

    def test_scene_clips_without_audio(self, demo_assets):
        script, screenshots, tmp_path = demo_assets
        durations = {s.title: s.duration_hint for s in script.scenes}
        clips = _build_scene_clips(screenshots, durations, audio_dir=None)
        assert len(clips) == 1
        assert clips[0].duration == 5.0

    def test_title_clip_duration(self, demo_assets):
        _, _, tmp_path = demo_assets
        card = generate_title_card("Title", tmp_path / "title.png")
        clip = _title_clip(card, duration=4.0)
        assert clip.duration == 4.0
