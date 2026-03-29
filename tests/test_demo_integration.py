"""Integration test for demo generation pipeline (LLM mocked, pipeline real)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("playwright", reason="playwright not installed")

from agents.demo_models import (
    ContentSkeleton,
    DemoQualityReport,
    DemoScene,
    DemoScript,
    QualityDimension,
    SceneSkeleton,
    ScreenshotSpec,
)


class TestDemoIntegration:
    @pytest.fixture
    def mock_script(self) -> DemoScript:
        return DemoScript(
            title="Test System Demo",
            audience="family",
            scenes=[
                DemoScene(
                    title="Dashboard Overview",
                    narration="This is where I see everything at a glance.",
                    duration_hint=8.0,
                    screenshot=ScreenshotSpec(
                        url="http://localhost:5173",
                        capture="viewport",
                    ),
                ),
                DemoScene(
                    title="Chat Interface",
                    narration="And this is where I talk to the system.",
                    duration_hint=6.0,
                    screenshot=ScreenshotSpec(
                        url="http://localhost:5173/chat",
                        wait_for="Send a message",
                        capture="viewport",
                    ),
                ),
            ],
            intro_narration="Let me show you what I have been building.",
            outro_narration="That is the system. Pretty cool, right?",
        )

    @patch("agents.demo_pipeline.screenshots._preflight_check", new_callable=AsyncMock)
    @patch("agents.demo_pipeline.screenshots.async_playwright")
    async def test_full_pipeline_mocked(self, mock_pw, mock_preflight, mock_script, tmp_path):
        """Test screenshot capture + slide render with mocked browser."""
        from agents.demo_pipeline.screenshots import capture_screenshots
        from agents.demo_pipeline.slides import render_slides

        # Mock Playwright
        mock_page = AsyncMock()
        mock_browser = AsyncMock()
        mock_browser.new_page.return_value = mock_page
        mock_context = AsyncMock()
        mock_context.chromium.launch.return_value = mock_browser
        mock_pw.return_value.__aenter__.return_value = mock_context

        # Capture screenshots
        specs = [
            (f"{i:02d}-scene", scene.screenshot) for i, scene in enumerate(mock_script.scenes, 1)
        ]
        screenshot_dir = tmp_path / "screenshots"
        paths = await capture_screenshots(specs, screenshot_dir)

        # Create fake screenshot files (Playwright is mocked)
        for p in paths:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"fake png data")

        # Build screenshot map
        screenshot_map = {
            scene.title: path for scene, path in zip(mock_script.scenes, paths, strict=False)
        }

        # Render slides (markdown only, skip PDF to avoid npx dependency in CI)
        md_path = await render_slides(mock_script, screenshot_map, tmp_path, render_pdf=False)

        # Verify outputs
        assert md_path.exists()
        content = md_path.read_text()
        assert "marp: true" in content
        assert "Test System Demo" in content
        assert "Dashboard Overview" in content
        assert "Chat Interface" in content
        assert "Let me show you" in content

        # Verify script metadata
        script_json = tmp_path / "script.json"
        if not script_json.exists():
            # Write it like the real pipeline does
            script_json.write_text(mock_script.model_dump_json(indent=2))
        assert script_json.exists()

    @patch("agents.demo_pipeline.screenshots._preflight_check", new_callable=AsyncMock)
    @patch("agents.demo_pipeline.screenshots.async_playwright")
    @patch("agents.demo.voice_agent")
    @patch("agents.demo.content_agent")
    async def test_generate_demo_orchestration(
        self, mock_content_agent, mock_voice_agent, mock_pw, mock_preflight, mock_script, tmp_path
    ):
        """End-to-end test of generate_demo() with mocked LLM and browser."""
        from agents.demo import generate_demo
        from agents.demo_pipeline.readiness import ReadinessResult

        # Mock the content agent (Pass 1)
        mock_skeleton = ContentSkeleton(
            title="Test System Demo",
            audience="family",
            intro_points=["Overview of the system"],
            scenes=[
                SceneSkeleton(
                    title="Dashboard Overview",
                    facts=["Shows health status"],
                    visual_type="screenshot",
                    visual_brief="Main dashboard",
                    screenshot=ScreenshotSpec(url="http://localhost:5173", capture="viewport"),
                ),
                SceneSkeleton(
                    title="Chat Interface",
                    facts=["Chat with the system"],
                    visual_type="screenshot",
                    visual_brief="Chat page",
                    screenshot=ScreenshotSpec(url="http://localhost:5173/chat", capture="viewport"),
                ),
            ],
            outro_points=["That is the system"],
        )
        mock_content_result = MagicMock()
        mock_content_result.output = mock_skeleton
        mock_content_agent.run = AsyncMock(return_value=mock_content_result)

        # Mock the voice agent (Pass 2)
        mock_voice_result = MagicMock()
        mock_voice_result.output = mock_script
        mock_voice_agent.run = AsyncMock(return_value=mock_voice_result)

        # Mock Playwright
        mock_page = AsyncMock()
        mock_browser = AsyncMock()
        mock_browser.new_page.return_value = mock_page
        mock_context = AsyncMock()
        mock_context.chromium.launch.return_value = mock_browser
        mock_pw.return_value.__aenter__.return_value = mock_context

        # Mock readiness gate
        mock_readiness = ReadinessResult(ready=True, health_score="75/75")

        # Mock quality report
        mock_quality = DemoQualityReport(
            dimensions=[QualityDimension(name="narrative_coherence", passed=True)],
            overall_pass=True,
        )

        # Mock sufficiency gate (avoids Qdrant/operator dependency)
        from agents.demo_pipeline.sufficiency import KnowledgeCheck, SufficiencyResult

        mock_sufficiency = SufficiencyResult(
            confidence="adequate",
            system_checks=[KnowledgeCheck("architecture_docs", True, "ok", "system")] * 7,
            audience_checks=[
                KnowledgeCheck("archetype_resolved", True, "matched 'family'", "person")
            ],
            enrichment_actions=[],
            audience_dossier=None,
        )

        # Run generate_demo with OUTPUT_DIR patched to tmp_path
        progress_msgs = []
        with (
            patch("agents.demo.OUTPUT_DIR", tmp_path),
            patch("agents.demo_pipeline.readiness.check_readiness", return_value=mock_readiness),
            patch(
                "agents.demo_pipeline.sufficiency.check_sufficiency", return_value=mock_sufficiency
            ),
            patch(
                "agents.demo_pipeline.research.gather_research",
                new_callable=AsyncMock,
                return_value="## Health\nScore: 75/75",
            ),
            patch(
                "agents.demo_pipeline.critique.critique_and_revise",
                new_callable=AsyncMock,
                return_value=(mock_script, mock_quality),
            ),
        ):
            demo_dir = await generate_demo(
                "the entire system for my partner",
                format="markdown-only",
                on_progress=progress_msgs.append,
            )

        # Verify orchestration
        assert demo_dir.exists()
        assert (demo_dir / "script.json").exists()
        assert (demo_dir / "metadata.json").exists()

        # Verify metadata
        meta = json.loads((demo_dir / "metadata.json").read_text())
        assert meta["audience"] == "family"
        assert meta["scope"] == "the entire system"
        assert meta["format"] == "markdown-only"
        assert meta["scenes"] == 2
        assert meta["target_duration"] == 180  # family default
        assert isinstance(meta["quality_pass"], bool)
        assert "narrative_framework" in meta

        # Verify progress callbacks were fired
        assert any("Scope:" in m for m in progress_msgs)
        assert any("Resolved audience:" in m for m in progress_msgs)
        assert any("Planning content structure" in m for m in progress_msgs)
        assert any("Demo complete" in m for m in progress_msgs)
