"""Tests for illustration generation pipeline."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from agents.demo_models import IllustrationSpec


class TestIllustrationSpecDefaults:
    def test_default_negative_prompt_excludes_text(self):
        spec = IllustrationSpec(prompt="test")
        assert "text" in spec.negative_prompt
        assert "words" in spec.negative_prompt

    def test_default_aspect_ratio(self):
        spec = IllustrationSpec(prompt="test")
        assert spec.aspect_ratio == "16:9"


class TestBuildPrompt:
    def test_combines_prompt_and_style(self):
        from agents.demo_pipeline.illustrations import _build_prompt

        spec = IllustrationSpec(
            prompt="A sunrise over connected systems",
            style="warm minimal illustration, soft colors",
        )
        result = _build_prompt(spec)
        assert "sunrise" in result
        assert "warm minimal" in result

    def test_prompt_without_style(self):
        from agents.demo_pipeline.illustrations import _build_prompt

        spec = IllustrationSpec(prompt="Abstract data flow")
        result = _build_prompt(spec)
        assert "Abstract data flow" in result

    def test_includes_negative_prompt(self):
        from agents.demo_pipeline.illustrations import _build_prompt

        spec = IllustrationSpec(prompt="Test image")
        result = _build_prompt(spec)
        assert "Do NOT include" in result


class TestGenerateIllustrations:
    async def test_empty_specs_returns_empty(self, tmp_path):
        from agents.demo_pipeline.illustrations import generate_illustrations

        paths = await generate_illustrations([], tmp_path)
        assert paths == []

    @patch("agents.demo_pipeline.illustrations._generate_single", new_callable=AsyncMock)
    async def test_calls_generate_for_each_spec(self, mock_gen, tmp_path):
        from agents.demo_pipeline.illustrations import generate_illustrations

        fake_path = tmp_path / "test.png"
        fake_path.write_bytes(b"fake png")
        mock_gen.return_value = fake_path

        specs = [
            ("01-intro", IllustrationSpec(prompt="Test 1")),
            ("02-concept", IllustrationSpec(prompt="Test 2")),
        ]
        paths = await generate_illustrations(specs, tmp_path)
        assert mock_gen.call_count == 2
        assert len(paths) == 2

    @patch("agents.demo_pipeline.illustrations._generate_single", new_callable=AsyncMock)
    async def test_fallback_on_failure(self, mock_gen, tmp_path):
        from agents.demo_pipeline.illustrations import generate_illustrations

        mock_gen.return_value = None

        specs = [("01-intro", IllustrationSpec(prompt="Test"))]
        paths = await generate_illustrations(specs, tmp_path)
        assert len(paths) == 1
        assert paths[0] is None

    @patch("agents.demo_pipeline.illustrations._generate_single", new_callable=AsyncMock)
    async def test_progress_callback(self, mock_gen, tmp_path):
        from agents.demo_pipeline.illustrations import generate_illustrations

        mock_gen.return_value = tmp_path / "test.png"
        (tmp_path / "test.png").write_bytes(b"fake")

        progress_msgs = []
        specs = [("01-test", IllustrationSpec(prompt="Test"))]
        await generate_illustrations(specs, tmp_path, on_progress=progress_msgs.append)
        assert any("illustration" in msg.lower() for msg in progress_msgs)


class TestLoadIllustrationStyle:
    def test_loads_style_for_known_audience(self):
        from agents.demo_pipeline.illustrations import load_illustration_style

        style = load_illustration_style("family")
        assert isinstance(style, str)

    def test_unknown_audience_returns_empty(self):
        from agents.demo_pipeline.illustrations import load_illustration_style

        style = load_illustration_style("nonexistent-audience")
        assert style == ""
