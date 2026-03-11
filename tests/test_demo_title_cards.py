"""Tests for Gruvbox title card generation."""

from __future__ import annotations

from PIL import Image

from agents.demo_pipeline.title_cards import generate_scene_title, generate_title_card


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
