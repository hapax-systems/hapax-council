"""Tests for Marp slide generation."""
from __future__ import annotations

from pathlib import Path

from agents.demo_models import DemoScene, DemoScript, ScreenshotSpec
from agents.demo_pipeline.slides import generate_marp_markdown, render_slides


class TestGenerateMarpMarkdown:
    def test_basic_structure(self):
        script = DemoScript(
            title="Test Demo",
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
        screenshots = {"Dashboard": Path("/tmp/01-dashboard.png")}
        md = generate_marp_markdown(script, screenshots)

        assert "marp: true" in md
        assert "# Test Demo" in md
        assert "Welcome." in md
        assert "Dashboard" in md
        assert "01-dashboard.png" in md
        assert "Goodbye." in md

    def test_speaker_notes(self):
        script = DemoScript(
            title="Test",
            audience="technical-peer",
            scenes=[
                DemoScene(
                    title="Arch",
                    narration="The architecture uses three tiers.",
                    duration_hint=10.0,
                    screenshot=ScreenshotSpec(url="http://localhost:5173"),
                ),
            ],
            intro_narration="Hi.",
            outro_narration="Bye.",
        )
        screenshots = {"Arch": Path("/tmp/arch.png")}
        md = generate_marp_markdown(script, screenshots)

        assert "<!--" in md
        assert "The architecture uses three tiers." in md

    def test_multiple_scenes(self):
        scenes = [
            DemoScene(
                title=f"Scene {i}",
                narration=f"Narration {i}.",
                duration_hint=5.0,
                screenshot=ScreenshotSpec(url="http://localhost:5173"),
            )
            for i in range(3)
        ]
        script = DemoScript(
            title="Multi",
            audience="family",
            scenes=scenes,
            intro_narration="Start.",
            outro_narration="End.",
        )
        screenshots = {f"Scene {i}": Path(f"/tmp/scene-{i}.png") for i in range(3)}
        md = generate_marp_markdown(script, screenshots)

        assert md.count("\n---\n") >= 4


    def test_key_points_rendered(self):
        script = DemoScript(
            title="Test", audience="technical-peer",
            scenes=[DemoScene(
                title="Dashboard", narration="Here.",
                duration_hint=5.0,
                key_points=["Health checks", "Auto-fix"],
                screenshot=ScreenshotSpec(url="http://localhost:5173"),
            )],
            intro_narration="Hi", outro_narration="Bye",
        )
        md = generate_marp_markdown(script, {"Dashboard": Path("screenshots/01.png")})
        assert "- Health checks" in md
        assert "- Auto-fix" in md

    def test_audience_label_humanized(self):
        script = DemoScript(
            title="Test", audience="technical-peer",
            scenes=[DemoScene(
                title="Test Scene", narration="Test.",
                duration_hint=5.0,
                screenshot=ScreenshotSpec(url="http://localhost:5173"),
            )],
            intro_narration="Hi", outro_narration="Bye",
        )
        md = generate_marp_markdown(script, {})
        assert "Technical Peers" in md
        assert "technical-peer" not in md.split("footer")[1]


class TestRenderSlides:
    async def test_writes_markdown_file(self, tmp_path: Path):
        script = DemoScript(
            title="Render Test",
            audience="family",
            scenes=[
                DemoScene(
                    title="Dash",
                    narration="Dashboard view.",
                    duration_hint=5.0,
                    screenshot=ScreenshotSpec(url="http://localhost:5173"),
                ),
            ],
            intro_narration="Hello.",
            outro_narration="Done.",
        )
        screenshot_dir = tmp_path / "screenshots"
        screenshot_dir.mkdir()
        fake_img = screenshot_dir / "01-dash.png"
        fake_img.write_bytes(b"fake png")

        screenshot_map = {"Dash": fake_img}

        md_path = await render_slides(
            script, screenshot_map, tmp_path, render_pdf=False
        )

        assert md_path.exists()
        assert md_path.suffix == ".md"
        content = md_path.read_text()
        assert "marp: true" in content
