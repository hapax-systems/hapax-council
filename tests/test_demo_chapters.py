"""Tests for MP4 chapter marker injection."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("moviepy", reason="moviepy not installed")

from agents.demo_models import DemoScene, DemoScript, ScreenshotSpec  # noqa: E402
from agents.demo_pipeline.chapters import (  # noqa: E402
    build_chapter_list_from_script,
    generate_ffmetadata,
    inject_chapters,
)


def _make_script(num_scenes: int = 2, duration_hint: float = 5.0) -> DemoScript:
    """Helper to build a DemoScript with N scenes."""
    scenes = [
        DemoScene(
            title=f"Scene {i}",
            narration=f"Narration for scene {i}.",
            duration_hint=duration_hint,
            key_points=[f"Point {i}"],
            screenshot=ScreenshotSpec(url=f"http://localhost:8080/page-{i}"),
        )
        for i in range(1, num_scenes + 1)
    ]
    return DemoScript(
        title="Test Demo",
        audience="developer",
        scenes=scenes,
        intro_narration="Welcome to the demo.",
        outro_narration="Thanks for watching.",
    )


class TestGenerateFFMetadata:
    """Tests for generate_ffmetadata."""

    def test_format_structure(self) -> None:
        """Verify INI structure, TIMEBASE, and correct ms values."""
        chapters = [
            ("Introduction", 0.0, 3.0),
            ("Dashboard Overview", 2.5, 8.0),
            ("Outro", 7.5, 10.5),
        ]
        result = generate_ffmetadata(chapters)

        # Must start with ffmetadata header
        assert result.startswith(";FFMETADATA1\n")

        # Check each chapter block
        assert "[CHAPTER]" in result
        assert result.count("[CHAPTER]") == 3

        # Check TIMEBASE present in every chapter
        assert result.count("TIMEBASE=1/1000") == 3

        # Verify ms conversion for first chapter
        assert "START=0" in result
        assert "END=3000" in result

        # Verify ms conversion for second chapter
        assert "START=2500" in result
        assert "END=8000" in result

        # Verify titles
        assert "title=Introduction" in result
        assert "title=Dashboard Overview" in result
        assert "title=Outro" in result

    def test_ends_with_newline(self) -> None:
        """Output should end with a trailing newline."""
        result = generate_ffmetadata([("Ch1", 0.0, 1.0)])
        assert result.endswith("\n")

    def test_empty_chapters(self) -> None:
        """Empty chapter list produces just the header."""
        result = generate_ffmetadata([])
        assert result == ";FFMETADATA1\n"


class TestBuildChapterList:
    """Tests for build_chapter_list_from_script."""

    def test_basic_two_scenes(self) -> None:
        """2 scenes with duration_hint, verify 4 chapters and correct ranges."""
        script = _make_script(num_scenes=2, duration_hint=5.0)

        # No audio dir — uses duration_hint fallback
        chapters = build_chapter_list_from_script(script, audio_dir=None)

        # Should have 4 chapters: intro + 2 scenes + outro
        assert len(chapters) == 4

        titles = [c[0] for c in chapters]
        assert titles == ["Introduction", "Scene 1", "Scene 2", "Outro"]

        # Intro: 0 -> TITLE_DURATION (3.0)
        assert chapters[0] == ("Introduction", 0.0, 3.0)

        # Scene 1: starts at 3.0 - 0.5 (crossfade) = 2.5
        # Scene title: 1.5s, then screenshot crossfades in: -0.5 + 5.0 = 4.5
        # Total scene duration from start: 1.5 + 4.5 = 6.0
        # Scene 1 end: 2.5 + 6.0 = 8.5
        assert chapters[1][0] == "Scene 1"
        assert chapters[1][1] == pytest.approx(2.5)
        assert chapters[1][2] == pytest.approx(8.5)

        # Scene 2 starts with crossfade from previous clip
        assert chapters[2][0] == "Scene 2"

        # Outro: last chapter
        assert chapters[3][0] == "Outro"

        # Timeline should be monotonically non-decreasing for starts
        for i in range(1, len(chapters)):
            assert chapters[i][1] >= chapters[i - 1][1]

        # Each chapter end >= its start
        for title, start, end in chapters:
            assert end > start, f"Chapter '{title}' has end <= start"

    def test_no_audio_dir_uses_duration_hint(self) -> None:
        """When audio_dir is None, all durations come from duration_hint."""
        script = _make_script(num_scenes=1, duration_hint=7.0)
        chapters = build_chapter_list_from_script(script, audio_dir=None)

        assert len(chapters) == 3  # intro + 1 scene + outro

        # Intro uses TITLE_DURATION (3.0)
        assert chapters[0][2] - chapters[0][1] == pytest.approx(3.0)

        # Outro uses TITLE_DURATION (3.0)
        assert chapters[2][2] - chapters[2][1] == pytest.approx(3.0)

    @patch("demo.pipeline.chapters._get_wav_duration")
    def test_with_audio_durations(self, mock_dur: MagicMock) -> None:
        """When audio files exist, their durations are used."""
        script = _make_script(num_scenes=1, duration_hint=5.0)
        audio_dir = Path("/fake/audio")

        # Map calls: intro=4.0, scene=8.0, outro=2.0
        def duration_side_effect(path: Path) -> float | None:
            name = path.name
            if name == "00-intro.wav":
                return 4.0
            if name == "01-scene-1.wav":
                return 8.0
            if name == "99-outro.wav":
                return 2.0
            return None

        mock_dur.side_effect = duration_side_effect

        chapters = build_chapter_list_from_script(script, audio_dir=audio_dir)
        assert len(chapters) == 3

        # Intro uses audio duration (4.0) not TITLE_DURATION
        assert chapters[0] == ("Introduction", 0.0, 4.0)

        # Outro uses audio duration (2.0) not TITLE_DURATION
        assert chapters[2][2] - chapters[2][1] == pytest.approx(2.0)


class TestInjectChapters:
    """Tests for inject_chapters."""

    @patch("demo.pipeline.chapters.get_ffmpeg_path")
    @patch("subprocess.run")
    def test_smoke(self, mock_run: MagicMock, mock_ffmpeg: MagicMock, tmp_path: Path) -> None:
        """Mock subprocess.run, verify ffmpeg called with correct args."""
        mock_ffmpeg.return_value = "/usr/bin/ffmpeg"
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        video = tmp_path / "demo.mp4"
        video.write_bytes(b"fake video data")
        output = tmp_path / "demo-chapters.mp4"

        chapters = [
            ("Introduction", 0.0, 3.0),
            ("Scene 1", 2.5, 8.0),
            ("Outro", 7.5, 10.5),
        ]

        result = inject_chapters(video, chapters, output_path=output)

        assert result == output
        mock_run.assert_called_once()

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "/usr/bin/ffmpeg"
        assert "-y" in cmd
        assert "-i" in cmd
        assert str(video) in cmd
        assert "-map_metadata" in cmd
        assert "1" in cmd
        assert "-codec" in cmd
        assert "copy" in cmd
        assert str(output) in cmd

    @patch("demo.pipeline.chapters.get_ffmpeg_path")
    @patch("subprocess.run")
    def test_in_place_replacement(
        self, mock_run: MagicMock, mock_ffmpeg: MagicMock, tmp_path: Path
    ) -> None:
        """When output_path is None, replaces the original file."""
        mock_ffmpeg.return_value = "/usr/bin/ffmpeg"

        video = tmp_path / "demo.mp4"
        video.write_bytes(b"fake video data")
        chaptered = video.with_suffix(".chaptered.mp4")

        def fake_run(cmd: list, **kwargs) -> MagicMock:  # noqa: ARG001, ANN003
            # Simulate ffmpeg creating the output file
            Path(cmd[-1]).write_bytes(b"chaptered video data")
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = fake_run

        chapters = [("Introduction", 0.0, 3.0)]
        result = inject_chapters(video, chapters, output_path=None)

        # Should return original path (replaced in-place)
        assert result == video
        # Temp chaptered file should be cleaned up (renamed to original)
        assert not chaptered.exists()

    @patch("demo.pipeline.chapters.get_ffmpeg_path")
    @patch("subprocess.run")
    def test_ffmpeg_failure_raises(
        self, mock_run: MagicMock, mock_ffmpeg: MagicMock, tmp_path: Path
    ) -> None:
        """CalledProcessError raised when ffmpeg fails."""
        import subprocess as sp

        mock_ffmpeg.return_value = "/usr/bin/ffmpeg"
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")

        video = tmp_path / "demo.mp4"
        video.write_bytes(b"fake")
        output = tmp_path / "out.mp4"

        with pytest.raises(sp.CalledProcessError):
            inject_chapters(video, [("Ch", 0.0, 1.0)], output_path=output)
