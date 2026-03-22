"""Tests for screenshot capture pipeline."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("playwright", reason="playwright not installed")

from agents.demo_models import ScreenshotSpec  # noqa: E402
from agents.demo_pipeline.screenshots import (  # noqa: E402
    _resolve_selector,
    capture_screenshots,
    validate_screenshot_specs,
)


class TestCaptureScreenshots:
    @pytest.fixture
    def output_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / "screenshots"
        d.mkdir()
        return d

    @pytest.fixture
    def specs(self) -> list[tuple[str, ScreenshotSpec]]:
        return [
            (
                "01-dashboard",
                ScreenshotSpec(url="http://localhost:5173"),
            ),
            (
                "02-chat",
                ScreenshotSpec(
                    url="http://localhost:5173/chat",
                    wait_for="Send a message",
                ),
            ),
        ]

    @patch("agents.demo_pipeline.screenshots._preflight_check")
    @patch("agents.demo_pipeline.screenshots.async_playwright")
    async def test_captures_screenshots(self, mock_pw, mock_preflight, specs, output_dir):
        mock_page = AsyncMock()
        mock_browser = AsyncMock()
        mock_browser.new_page.return_value = mock_page
        mock_context = AsyncMock()
        mock_context.chromium.launch.return_value = mock_browser
        mock_pw.return_value.__aenter__.return_value = mock_context

        progress = []
        paths = await capture_screenshots(
            specs, output_dir, on_progress=lambda msg: progress.append(msg)
        )

        assert len(paths) == 2
        assert mock_page.goto.call_count == 2
        assert mock_page.screenshot.call_count == 2
        assert len(progress) == 2

    @patch("agents.demo_pipeline.screenshots._preflight_check")
    @patch("agents.demo_pipeline.screenshots.async_playwright")
    async def test_sets_viewport(self, mock_pw, mock_preflight, output_dir):
        mock_page = AsyncMock()
        mock_browser = AsyncMock()
        mock_browser.new_page.return_value = mock_page
        mock_context = AsyncMock()
        mock_context.chromium.launch.return_value = mock_browser
        mock_pw.return_value.__aenter__.return_value = mock_context

        specs = [
            (
                "wide",
                ScreenshotSpec(
                    url="http://localhost:5173", viewport_width=2560, viewport_height=1440
                ),
            ),
        ]
        await capture_screenshots(specs, output_dir)
        mock_page.set_viewport_size.assert_called_with({"width": 2560, "height": 1440})


class TestScreenshotRetry:
    @patch("agents.demo_pipeline.screenshots._preflight_check", new_callable=AsyncMock)
    @patch("agents.demo_pipeline.screenshots.async_playwright")
    async def test_retries_on_failure(self, mock_pw, mock_preflight, tmp_path):
        mock_page = AsyncMock()
        # First goto fails, second succeeds
        mock_page.goto.side_effect = [Exception("timeout"), None]
        mock_page.screenshot = AsyncMock()
        mock_browser = AsyncMock()
        mock_browser.new_page.return_value = mock_page
        mock_context = AsyncMock()
        mock_context.chromium.launch.return_value = mock_browser
        mock_pw.return_value.__aenter__.return_value = mock_context

        specs = [("test", ScreenshotSpec(url="http://localhost:5173"))]
        await capture_screenshots(specs, tmp_path, max_retries=2)
        assert mock_page.goto.call_count == 2

    @patch("agents.demo_pipeline.screenshots._preflight_check", new_callable=AsyncMock)
    @patch("agents.demo_pipeline.screenshots.async_playwright")
    async def test_raises_after_max_retries(self, mock_pw, mock_preflight, tmp_path):
        mock_page = AsyncMock()
        mock_page.goto.side_effect = Exception("persistent failure")
        mock_browser = AsyncMock()
        mock_browser.new_page.return_value = mock_page
        mock_context = AsyncMock()
        mock_context.chromium.launch.return_value = mock_browser
        mock_pw.return_value.__aenter__.return_value = mock_context

        specs = [("test", ScreenshotSpec(url="http://localhost:5173"))]
        with pytest.raises(Exception, match="persistent failure"):
            await capture_screenshots(specs, tmp_path, max_retries=2)
        # 1 initial + 2 retries = 3 attempts
        assert mock_page.goto.call_count == 3

    @patch("agents.demo_pipeline.screenshots._preflight_check", new_callable=AsyncMock)
    @patch("agents.demo_pipeline.screenshots.async_playwright")
    async def test_no_retry_when_max_retries_zero(self, mock_pw, mock_preflight, tmp_path):
        mock_page = AsyncMock()
        mock_page.goto.side_effect = Exception("fail")
        mock_browser = AsyncMock()
        mock_browser.new_page.return_value = mock_page
        mock_context = AsyncMock()
        mock_context.chromium.launch.return_value = mock_browser
        mock_pw.return_value.__aenter__.return_value = mock_context

        specs = [("test", ScreenshotSpec(url="http://localhost:5173"))]
        with pytest.raises(Exception, match="fail"):
            await capture_screenshots(specs, tmp_path, max_retries=0)
        assert mock_page.goto.call_count == 1


class TestResolveSelector:
    def test_known_route_dashboard(self):
        spec = ScreenshotSpec(url="http://localhost:5173/")
        assert _resolve_selector(spec) == "[data-region='ground']"

    def test_known_route_chat(self):
        spec = ScreenshotSpec(url="http://localhost:5173/chat")
        assert _resolve_selector(spec) == "textarea"

    def test_known_route_overrides_wait_for(self):
        """Known route selector takes priority over LLM-generated wait_for."""
        spec = ScreenshotSpec(url="http://localhost:5173/", wait_for="Overall")
        assert _resolve_selector(spec) == "[data-region='ground']"

    def test_unknown_route_uses_wait_for(self):
        spec = ScreenshotSpec(url="http://example.com/page", wait_for="Submit")
        assert _resolve_selector(spec) == "text=Submit"

    def test_unknown_route_no_wait_for(self):
        spec = ScreenshotSpec(url="http://example.com/page")
        assert _resolve_selector(spec) is None

    def test_css_selector_passthrough(self):
        spec = ScreenshotSpec(url="http://example.com", wait_for="#main-content")
        assert _resolve_selector(spec) == "#main-content"

    def test_port_8051_also_matched(self):
        spec = ScreenshotSpec(url="http://localhost:8051/")
        assert _resolve_selector(spec) == "[data-region='ground']"


class TestGracefulDegradation:
    @patch("agents.demo_pipeline.screenshots._preflight_check", new_callable=AsyncMock)
    @patch("agents.demo_pipeline.screenshots.async_playwright")
    async def test_selector_timeout_captures_anyway(self, mock_pw, mock_preflight, tmp_path):
        """When wait_for selector times out, screenshot is still captured."""
        from agents.demo_pipeline.screenshots import PlaywrightTimeoutError

        mock_page = AsyncMock()
        mock_page.wait_for_selector.side_effect = PlaywrightTimeoutError("timeout")
        mock_browser = AsyncMock()
        mock_browser.new_page.return_value = mock_page
        mock_context = AsyncMock()
        mock_context.chromium.launch.return_value = mock_browser
        mock_pw.return_value.__aenter__.return_value = mock_context

        specs = [("01-dashboard", ScreenshotSpec(url="http://localhost:5173/"))]
        paths = await capture_screenshots(specs, tmp_path)

        # Screenshot should still be taken despite selector timeout
        assert len(paths) == 1
        assert mock_page.screenshot.call_count == 1


class TestValidateScreenshotSpecs:
    def test_valid_urls_unchanged(self):
        specs = [("dash", ScreenshotSpec(url="http://localhost:5173/"))]
        result = validate_screenshot_specs(specs)
        assert result[0][1].url == "http://localhost:5173/"

    def test_wrong_port_rewritten(self):
        specs = [("dash", ScreenshotSpec(url="http://localhost:8080/"))]
        result = validate_screenshot_specs(specs)
        assert result[0][1].url == "http://localhost:5173/"

    def test_unknown_route_rewritten_to_root(self):
        specs = [("page", ScreenshotSpec(url="http://localhost:5173/unknown/page"))]
        result = validate_screenshot_specs(specs)
        assert result[0][1].url == "http://localhost:5173/"

    def test_route_with_chat_substring_matches_chat(self):
        specs = [("page", ScreenshotSpec(url="http://localhost:5173/chat/history"))]
        result = validate_screenshot_specs(specs)
        assert result[0][1].url == "http://localhost:5173/chat"

    def test_external_urls_unchanged(self):
        specs = [("ext", ScreenshotSpec(url="http://example.com/page"))]
        result = validate_screenshot_specs(specs)
        assert result[0][1].url == "http://example.com/page"

    def test_chat_route_gets_default_actions(self):
        specs = [("chat", ScreenshotSpec(url="http://localhost:5173/chat"))]
        result = validate_screenshot_specs(specs)
        assert len(result[0][1].actions) > 0
        assert any("type" in a for a in result[0][1].actions)
        # Chat actions type but don't send (no "press Enter") to avoid "Thinking..." state
        assert any("wait" in a for a in result[0][1].actions)

    def test_chat_route_overrides_llm_actions(self):
        """LLM actions are unreliable for known routes, so we always override."""
        specs = [
            (
                "chat",
                ScreenshotSpec(
                    url="http://localhost:5173/chat", actions=["type('What')", "press('Enter')"]
                ),
            )
        ]
        result = validate_screenshot_specs(specs)
        # Should replace LLM actions with known-good defaults
        assert "click textarea" in result[0][1].actions[0]

    def test_chat_variants_cycle(self):
        """Multiple chat screenshots get different questions."""
        import agents.demo_pipeline.screenshots as ss_mod

        # Reset variant index
        ss_mod._chat_variant_index = 0
        specs = [
            ("chat1", ScreenshotSpec(url="http://localhost:5173/chat")),
            ("chat2", ScreenshotSpec(url="http://localhost:5173/chat")),
        ]
        result = validate_screenshot_specs(specs)
        # Extract the typed questions
        q1 = [a for a in result[0][1].actions if a.startswith("type ")][0]
        q2 = [a for a in result[1][1].actions if a.startswith("type ")][0]
        assert q1 != q2, "Different chat screenshots should get different questions"

    def test_dashboard_no_default_actions(self):
        specs = [("dash", ScreenshotSpec(url="http://localhost:5173/"))]
        result = validate_screenshot_specs(specs)
        assert result[0][1].actions == []

    def test_wrong_port_and_chat_route(self):
        """Wrong port + chat route should fix both port AND inject actions."""
        specs = [("chat", ScreenshotSpec(url="http://localhost:3000/chat"))]
        result = validate_screenshot_specs(specs)
        assert "5173" in result[0][1].url
        assert len(result[0][1].actions) > 0
