"""Tests for Gruvbox title card generation."""

from __future__ import annotations

import warnings

import pytest

pytest.importorskip("PIL", reason="Pillow not installed")

from PIL import Image  # noqa: E402

from agents.demo_pipeline.title_cards import generate_scene_title, generate_title_card  # noqa: E402


class TestGenerateTitleCard:
    def test_creates_image(self, tmp_path):
        path = generate_title_card("Hello World", tmp_path / "title.png")
        assert path.exists()
        img = Image.open(path)
        assert img.size == (1920, 1080)

    def test_custom_subtitle(self, tmp_path):
        path = generate_title_card("Demo Title", tmp_path / "title.png", subtitle="For my partner")
        assert path.exists()

    def test_custom_size(self, tmp_path):
        path = generate_title_card("Small", tmp_path / "small.png", size=(1280, 720))
        img = Image.open(path)
        assert img.size == (1280, 720)

    def test_output_reopens_without_decompression_bomb_warning(self, tmp_path):
        path = generate_title_card("Safe", tmp_path / "safe.png")
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            img = Image.open(path)
            assert img.size == (1920, 1080)

    def test_rejects_implausibly_large_size(self, tmp_path):
        with pytest.raises(ValueError, match="pixel budget"):
            generate_title_card("Too Large", tmp_path / "huge.png", size=(10000, 10000))


class TestGenerateSceneTitle:
    def test_creates_image(self, tmp_path):
        path = generate_scene_title("Dashboard Overview", tmp_path / "scene-title.png")
        assert path.exists()
        img = Image.open(path)
        assert img.size == (1920, 1080)

    def test_custom_size(self, tmp_path):
        path = generate_scene_title("Chat View", tmp_path / "scene.png", size=(1280, 720))
        img = Image.open(path)
        assert img.size == (1280, 720)
