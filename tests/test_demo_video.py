"""Tests for video assembly pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PIL", reason="Pillow not installed")
pytest.importorskip("moviepy", reason="moviepy not installed")

from agents.demo_pipeline.title_cards import generate_title_card  # noqa: E402


class TestAssembleVideo:
    @pytest.fixture
    def scene_dir(self, tmp_path) -> Path:
        """Create fake scene assets."""
        ss_dir = tmp_path / "screenshots"
        ss_dir.mkdir()

        from PIL import Image

        for name in ["01-dashboard", "02-chat"]:
            img = Image.new("RGB", (1920, 1080), (40, 40, 40))
            img.save(ss_dir / f"{name}.png")

        generate_title_card("Test Demo", tmp_path / "intro.png")
        generate_title_card("Thank You", tmp_path / "outro.png")

        return tmp_path

    def test_build_scene_clips_returns_list(self, scene_dir):
        from agents.demo_pipeline.video import _build_scene_clips

        screenshots = {
            "Dashboard": scene_dir / "screenshots" / "01-dashboard.png",
            "Chat": scene_dir / "screenshots" / "02-chat.png",
        }
        durations = {"Dashboard": 5.0, "Chat": 4.0}

        clips = _build_scene_clips(screenshots, durations, audio_dir=None)
        assert len(clips) == 2

    def test_build_scene_clips_with_title_dir(self, scene_dir):
        from agents.demo_pipeline.video import SCENE_TITLE_DURATION, _build_scene_clips

        screenshots = {
            "Dashboard": scene_dir / "screenshots" / "01-dashboard.png",
            "Chat": scene_dir / "screenshots" / "02-chat.png",
        }
        durations = {"Dashboard": 5.0, "Chat": 4.0}
        title_dir = scene_dir / "scene-titles"

        clips = _build_scene_clips(screenshots, durations, audio_dir=None, title_dir=title_dir)
        # 2 scenes * 2 clips each (title + screenshot) = 4
        assert len(clips) == 4
        # First clip is a scene title card
        assert clips[0].duration == SCENE_TITLE_DURATION
        # Scene title images were generated
        assert (title_dir / "title-01-dashboard.png").exists()
        assert (title_dir / "title-02-chat.png").exists()

    def test_title_card_clip_default(self, scene_dir):
        from agents.demo_pipeline.video import _title_clip

        clip = _title_clip(scene_dir / "intro.png", duration=3.0)
        assert clip.duration == 3.0

    def test_title_card_clip_with_audio(self, scene_dir):
        """Title clip uses audio duration when audio_path is provided."""
        from unittest.mock import MagicMock, patch

        from agents.demo_pipeline.video import _title_clip

        with patch("agents.demo_pipeline.video.AudioFileClip") as mock_audio_cls:
            mock_audio = MagicMock()
            mock_audio.duration = 7.5
            mock_audio_cls.return_value = mock_audio

            # Create a fake audio file
            audio = scene_dir / "narration.wav"
            audio.write_bytes(b"RIFF" + b"\x00" * 100)

            clip = _title_clip(scene_dir / "intro.png", audio_path=audio)
            assert clip.duration == 7.5

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_assemble_produces_mp4(self, scene_dir):
        """End-to-end: assemble a short video and verify the output file."""
        from agents.demo_pipeline.video import assemble_video

        output = scene_dir / "test.mp4"
        screenshots = {
            "Dashboard": scene_dir / "screenshots" / "01-dashboard.png",
        }
        result_path, duration = await assemble_video(
            intro_card=scene_dir / "intro.png",
            outro_card=scene_dir / "outro.png",
            screenshots=screenshots,
            durations={"Dashboard": 1.0},
            audio_dir=None,
            output_path=output,
        )
        assert result_path.exists()
        assert result_path.stat().st_size > 1000
        assert duration > 0
