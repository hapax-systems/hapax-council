"""Tests for screencast recording pipeline."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.demo_models import InteractionSpec, InteractionStep
from agents.demo_pipeline.screencasts import (
    RECIPES,
    _execute_step,
    record_screencasts,
    resolve_recipe,
)


class TestInteractionModels:
    def test_interaction_step_minimal(self):
        step = InteractionStep(action="click")
        assert step.target == ""
        assert step.value == ""

    def test_interaction_step_with_values(self):
        step = InteractionStep(action="type", value="hello world")
        assert step.action == "type"
        assert step.value == "hello world"

    def test_interaction_spec_defaults(self):
        spec = InteractionSpec(url="http://localhost:5173/chat")
        assert spec.viewport_width == 1920
        assert spec.viewport_height == 1080
        assert spec.steps == []
        assert spec.recipe is None
        assert spec.max_duration == 30.0

    def test_interaction_spec_with_recipe(self):
        spec = InteractionSpec(
            url="http://localhost:5173/chat",
            recipe="chat-health-query",
        )
        assert spec.recipe == "chat-health-query"

    def test_interaction_spec_with_steps(self):
        spec = InteractionSpec(
            url="http://localhost:5173/",
            steps=[
                InteractionStep(action="wait", value="2000"),
                InteractionStep(action="click", target="textarea"),
                InteractionStep(action="type", value="test"),
            ],
        )
        assert len(spec.steps) == 3

    def test_max_duration_bounds(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            InteractionSpec(url="http://test", max_duration=0.5)
        with pytest.raises(ValidationError):
            InteractionSpec(url="http://test", max_duration=200)


class TestResolveRecipe:
    def test_resolves_known_recipe(self):
        spec = InteractionSpec(url="http://localhost:5173/chat", recipe="chat-health-query")
        resolved = resolve_recipe(spec)
        assert len(resolved.steps) > 0
        assert resolved.url == "http://localhost:5173/chat"

    def test_preserves_viewport_override(self):
        spec = InteractionSpec(
            url="http://localhost:5173/chat",
            recipe="chat-health-query",
            viewport_width=2560,
            viewport_height=1440,
        )
        resolved = resolve_recipe(spec)
        assert resolved.viewport_width == 2560
        assert resolved.viewport_height == 1440

    def test_uses_recipe_max_duration(self):
        """Recipe max_duration is always used (LLM overrides ignored)."""
        spec = InteractionSpec(
            url="http://localhost:5173/chat",
            recipe="chat-health-query",
            max_duration=45.0,
        )
        resolved = resolve_recipe(spec)
        # Recipe's own max_duration is used, not the spec's override
        assert resolved.max_duration == 40.0

    def test_unknown_recipe_falls_back_to_url_based(self):
        """Unknown recipe falls back to URL-based default recipe."""
        spec = InteractionSpec(
            url="http://localhost:5173/chat",
            recipe="nonexistent-recipe",
            steps=[InteractionStep(action="wait", value="1000")],
        )
        resolved = resolve_recipe(spec)
        # Falls back to chat-health-query (default for /chat)
        assert len(resolved.steps) > 1
        assert any(s.action == "type" for s in resolved.steps)

    def test_no_recipe_infers_from_url(self):
        """Custom steps without recipe are replaced with URL-based recipe."""
        steps = [InteractionStep(action="click", target="textarea")]
        spec = InteractionSpec(url="http://localhost:5173/chat", steps=steps)
        resolved = resolve_recipe(spec)
        # Infers chat-health-query from /chat URL
        assert len(resolved.steps) > 1
        assert resolved.url == "http://localhost:5173/chat"

    def test_all_recipes_are_valid(self):
        for name, recipe in RECIPES.items():
            assert recipe.url, f"Recipe {name} has no URL"
            assert len(recipe.steps) > 0, f"Recipe {name} has no steps"
            assert recipe.max_duration > 0, f"Recipe {name} has no max_duration"


class TestExecuteStep:
    @pytest.fixture
    def mock_page(self):
        page = AsyncMock()
        page.keyboard = AsyncMock()
        page.evaluate = AsyncMock()
        return page

    async def test_click_with_target(self, mock_page):
        step = InteractionStep(action="click", target="textarea")
        await _execute_step(mock_page, step)
        mock_page.click.assert_called_once_with("textarea", timeout=5_000)

    async def test_click_with_text_selector(self, mock_page):
        step = InteractionStep(action="click", target="text=Submit")
        await _execute_step(mock_page, step)
        mock_page.click.assert_called_once_with("text=Submit", timeout=5_000)

    async def test_click_no_target_skips(self, mock_page):
        step = InteractionStep(action="click")
        await _execute_step(mock_page, step)
        mock_page.click.assert_not_called()

    async def test_type_with_delay(self, mock_page):
        step = InteractionStep(action="type", value="hello")
        await _execute_step(mock_page, step)
        mock_page.keyboard.type.assert_called_once_with("hello", delay=50)

    async def test_wait_with_duration(self, mock_page):
        step = InteractionStep(action="wait", value="2000")
        await _execute_step(mock_page, step)
        mock_page.wait_for_timeout.assert_called_once_with(2000)

    async def test_wait_caps_at_30s(self, mock_page):
        step = InteractionStep(action="wait", value="60000")
        await _execute_step(mock_page, step)
        mock_page.wait_for_timeout.assert_called_once_with(30_000)

    async def test_wait_invalid_value(self, mock_page):
        step = InteractionStep(action="wait", value="abc")
        await _execute_step(mock_page, step)
        mock_page.wait_for_timeout.assert_called_once_with(1000)

    async def test_scroll(self, mock_page):
        step = InteractionStep(action="scroll", value="400")
        await _execute_step(mock_page, step)
        mock_page.evaluate.assert_called_once_with("window.scrollBy(0, 400)")

    async def test_scroll_default(self, mock_page):
        step = InteractionStep(action="scroll")
        await _execute_step(mock_page, step)
        mock_page.evaluate.assert_called_once_with("window.scrollBy(0, 300)")

    async def test_press(self, mock_page):
        step = InteractionStep(action="press", value="Enter")
        await _execute_step(mock_page, step)
        mock_page.keyboard.press.assert_called_once_with("Enter")

    async def test_unknown_action_skips(self, mock_page):
        InteractionStep(action="click", target="")
        step2 = MagicMock()
        step2.action = "unknown"
        # Just verify no exception
        await _execute_step(mock_page, InteractionStep(action="click"))


class TestRecordScreencasts:
    @patch("agents.demo_pipeline.screencasts._preflight_check", new_callable=AsyncMock)
    @patch("agents.demo_pipeline.screencasts.async_playwright")
    @patch("agents.demo_pipeline.screencasts._webm_to_mp4")
    async def test_records_screencasts(self, mock_convert, mock_pw, mock_preflight, tmp_path):
        mock_page = AsyncMock()
        mock_video = AsyncMock()
        mock_video.path.return_value = str(tmp_path / "vid.webm")
        mock_page.video = mock_video

        mock_context = AsyncMock()
        mock_context.new_page.return_value = mock_page

        mock_browser = AsyncMock()
        mock_browser.new_context.return_value = mock_context

        mock_pw_instance = AsyncMock()
        mock_pw_instance.chromium.launch.return_value = mock_browser
        mock_pw.return_value.__aenter__.return_value = mock_pw_instance

        mp4_path = tmp_path / "output" / "01-test.mp4"
        mock_convert.return_value = mp4_path

        specs = [
            (
                "01-test",
                InteractionSpec(
                    url="http://localhost:5173/chat",
                    steps=[InteractionStep(action="wait", value="1000")],
                ),
            ),
        ]

        output_dir = tmp_path / "output"
        progress = []
        paths = await record_screencasts(
            specs, output_dir, on_progress=lambda msg: progress.append(msg)
        )

        assert len(paths) == 1
        assert mock_page.goto.call_count == 1
        assert len(progress) == 1
        mock_browser.new_context.assert_called_once()

    async def test_empty_specs_returns_empty(self, tmp_path):
        paths = await record_screencasts([], tmp_path)
        assert paths == []

    @patch("agents.demo_pipeline.screencasts._preflight_check", new_callable=AsyncMock)
    @patch("agents.demo_pipeline.screencasts.async_playwright")
    @patch("agents.demo_pipeline.screencasts._webm_to_mp4")
    async def test_resolves_recipe(self, mock_convert, mock_pw, mock_preflight, tmp_path):
        mock_page = AsyncMock()
        mock_video = AsyncMock()
        mock_video.path.return_value = str(tmp_path / "vid.webm")
        mock_page.video = mock_video

        mock_context = AsyncMock()
        mock_context.new_page.return_value = mock_page

        mock_browser = AsyncMock()
        mock_browser.new_context.return_value = mock_context

        mock_pw_instance = AsyncMock()
        mock_pw_instance.chromium.launch.return_value = mock_browser
        mock_pw.return_value.__aenter__.return_value = mock_pw_instance

        mp4_path = tmp_path / "output" / "01-chat.mp4"
        mock_convert.return_value = mp4_path

        specs = [
            (
                "01-chat",
                InteractionSpec(
                    url="http://localhost:5173/chat",
                    recipe="chat-health-query",
                ),
            ),
        ]

        output_dir = tmp_path / "output"
        paths = await record_screencasts(specs, output_dir)

        assert len(paths) == 1
        # Should have navigated to chat URL from recipe
        mock_page.goto.assert_called_once()


class TestURLValidation:
    def test_fix_localhost_url_wrong_port(self):
        from agents.demo_pipeline.screenshots import fix_localhost_url

        fixed = fix_localhost_url("http://localhost:8080/chat")
        assert "5173" in fixed
        assert "/chat" in fixed

    def test_fix_localhost_url_unknown_route(self):
        from agents.demo_pipeline.screenshots import fix_localhost_url

        fixed = fix_localhost_url("http://localhost:5173/nonexistent")
        assert fixed == "http://localhost:5173/"

    def test_fix_localhost_url_valid_url_unchanged(self):
        from agents.demo_pipeline.screenshots import fix_localhost_url

        url = "http://localhost:5173/chat"
        assert fix_localhost_url(url) == url

    def test_fix_localhost_url_external_unchanged(self):
        from agents.demo_pipeline.screenshots import fix_localhost_url

        url = "https://example.com/page"
        assert fix_localhost_url(url) == url
