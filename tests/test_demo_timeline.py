"""Tests for the timeline-driven narrated demo pipeline."""

from __future__ import annotations

import struct
import wave
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from agents.demo_pipeline.timeline import (
    NarratedDemoResult,
    NarratedDemoScript,
    NarrationScene,
    render_narrated_demo,
)


class TestNarrationModels:
    """Test NarrationScene and NarratedDemoScript Pydantic models."""

    def test_minimal_script(self):
        script = NarratedDemoScript(
            title="Test Demo",
            scenes=[NarrationScene(narration="Hello.", recipe="terrain-overview")],
        )
        assert len(script.scenes) == 1
        assert script.intro_narration == ""
        assert script.outro_narration == ""

    def test_full_script(self):
        script = NarratedDemoScript(
            title="Full Demo",
            intro_narration="Welcome.",
            scenes=[
                NarrationScene(narration="Scene one.", recipe="terrain-overview", title="Overview"),
                NarrationScene(
                    narration="Scene two.",
                    recipe="terrain-investigation",
                    title="Investigation",
                    extra_padding=2.0,
                ),
            ],
            outro_narration="Goodbye.",
        )
        assert len(script.scenes) == 2
        assert script.scenes[1].extra_padding == 2.0

    def test_empty_scenes_rejected(self):
        with pytest.raises(Exception):
            NarratedDemoScript(title="Bad", scenes=[])

    def test_result_model(self):
        result = NarratedDemoResult(
            mp4_path="/tmp/demo.mp4",
            duration_seconds=30.0,
            chapter_markers=[("Intro", 0.0, 5.0), ("Scene 1", 5.0, 10.0)],
            scene_count=1,
        )
        assert result.scene_count == 1
        assert len(result.chapter_markers) == 2


class TestTerrainRecipesExist:
    """Verify terrain-aware recipes are registered."""

    def test_all_terrain_recipes_present(self):
        from agents.demo_pipeline.screencasts import RECIPES

        expected = [
            "terrain-overview",
            "terrain-investigation",
            "terrain-chat",
            "terrain-region-dive",
            "terrain-camera",
        ]
        for name in expected:
            assert name in RECIPES, f"Recipe '{name}' missing from RECIPES"

    def test_terrain_recipes_have_steps(self):
        from agents.demo_pipeline.screencasts import RECIPES

        for name in RECIPES:
            if name.startswith("terrain-"):
                recipe = RECIPES[name]
                assert len(recipe.steps) > 0, f"Recipe '{name}' has no steps"
                assert recipe.max_duration > 0, f"Recipe '{name}' has no max_duration"

    def test_url_to_default_recipe_returns_terrain(self):
        from agents.demo_pipeline.screencasts import _url_to_default_recipe

        assert _url_to_default_recipe("http://localhost:5173/") == "terrain-overview"
        assert _url_to_default_recipe("http://localhost:5173/terrain") == "terrain-overview"
        assert _url_to_default_recipe("http://localhost:5173/chat") == "terrain-chat"


class TestKokoroVoiceSegment:
    """Test Kokoro TTS voice segment generation."""

    def test_generate_voice_segment_kokoro(self, tmp_path: Path):
        """Mock KPipeline and verify WAV output."""
        fake_audio = np.zeros(12000, dtype=np.float32)
        mock_tensor = MagicMock()
        mock_tensor.cpu.return_value.numpy.return_value = fake_audio

        mock_pipeline_instance = MagicMock()
        mock_pipeline_instance.return_value = [("graphemes", "phonemes", mock_tensor)]

        with patch("agents.demo_pipeline.voice._kokoro_pipeline", mock_pipeline_instance):
            from agents.demo_pipeline.voice import generate_voice_segment_kokoro

            output = tmp_path / "test.wav"
            generate_voice_segment_kokoro("Hello world.", output)

            assert output.exists()
            with wave.open(str(output), "rb") as wf:
                assert wf.getnchannels() == 1
                assert wf.getsampwidth() == 2
                assert wf.getframerate() == 24000
                assert wf.getnframes() == 12000

    def test_get_wav_duration(self, tmp_path: Path):
        """Test WAV duration measurement."""
        from agents.demo_pipeline.voice import get_wav_duration

        output = tmp_path / "dur_test.wav"
        n_frames = 48000  # 2 seconds at 24kHz
        with wave.open(str(output), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(struct.pack(f"<{n_frames}h", *([0] * n_frames)))

        dur = get_wav_duration(output)
        assert abs(dur - 2.0) < 0.01


def _make_fake_wav(path: Path, duration_s: float = 1.0) -> Path:
    """Create a silent WAV file of the given duration."""
    n_frames = int(24000 * duration_s)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(struct.pack(f"<{n_frames}h", *([0] * n_frames)))
    return path


class TestRenderNarratedDemo:
    """Integration test for render_narrated_demo (all external calls mocked)."""

    @pytest.mark.asyncio
    async def test_two_scene_pipeline(self, tmp_path: Path):
        """End-to-end pipeline with mocked TTS, Playwright, and video assembly."""
        script = NarratedDemoScript(
            title="Test Demo",
            intro_narration="Welcome to the test.",
            scenes=[
                NarrationScene(
                    narration="This is scene one.",
                    recipe="terrain-overview",
                    title="Overview",
                    scene_type="screencast",
                ),
                NarrationScene(
                    narration="This is scene two.",
                    recipe="terrain-investigation",
                    title="Investigation",
                    scene_type="screencast",
                ),
            ],
            outro_narration="Thank you for watching.",
        )

        def fake_generate_segments(segments, output_dir, **kwargs):
            output_dir.mkdir(parents=True, exist_ok=True)
            paths = []
            for name, _text in segments:
                path = output_dir / f"{name}.wav"
                _make_fake_wav(path, duration_s=1.0)
                paths.append(path)
            return paths

        async def fake_record(specs, output_dir, **kwargs):
            output_dir.mkdir(parents=True, exist_ok=True)
            paths = []
            for name, _spec in specs:
                path = output_dir / f"{name}.mp4"
                path.write_bytes(b"\x00" * 100)
                paths.append(path)
            return paths

        mock_assemble = AsyncMock(return_value=(tmp_path / "output" / "demo.mp4", 45.0))
        mock_title = MagicMock(return_value=tmp_path / "card.png")

        with (
            patch(
                "agents.demo_pipeline.voice.generate_all_voice_segments",
                side_effect=fake_generate_segments,
            ) as mock_gen,
            patch(
                "agents.demo_pipeline.screencasts.record_screencasts",
                side_effect=fake_record,
            ) as mock_record,
            patch("agents.demo_pipeline.video.assemble_video", mock_assemble),
            patch("agents.demo_pipeline.title_cards.generate_title_card", mock_title),
        ):
            result = await render_narrated_demo(script, tmp_path / "output")

            # Audio generation: intro + 2 scenes + outro = 4 segments
            gen_call = mock_gen.call_args
            assert len(gen_call[0][0]) == 4

            # Both scenes are screencasts
            record_call = mock_record.call_args
            assert record_call is not None
            assert len(record_call[0][0]) == 2

            assert mock_assemble.called
            assert result.scene_count == 2
            assert result.duration_seconds == 45.0
            assert len(result.chapter_markers) == 4  # intro + 2 scenes + outro
