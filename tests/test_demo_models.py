"""Tests for demo script data models."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from agents.demo_models import (
    AudiencePersona,
    DemoScene,
    DemoScript,
    ScreenshotSpec,
    load_personas,
)


class TestScreenshotSpec:
    def test_minimal(self):
        s = ScreenshotSpec(url="http://localhost:5173")
        assert s.viewport_width == 1920
        assert s.viewport_height == 1080
        assert s.actions == []
        assert s.capture == "viewport"

    def test_with_actions(self):
        s = ScreenshotSpec(
            url="http://localhost:5173/chat",
            actions=["click #input", "type 'hello'"],
            wait_for="Assistant",
            capture="fullpage",
        )
        assert len(s.actions) == 2


class TestDemoScene:
    def test_roundtrip(self):
        scene = DemoScene(
            title="Dashboard Overview",
            narration="This is the main dashboard.",
            duration_hint=8.0,
            screenshot=ScreenshotSpec(url="http://localhost:5173"),
        )
        data = json.loads(scene.model_dump_json())
        restored = DemoScene.model_validate(data)
        assert restored.title == scene.title

    def test_scene_with_key_points(self):
        scene = DemoScene(
            title="Dashboard",
            narration="Here's the dashboard.",
            duration_hint=5.0,
            key_points=["Health monitoring", "VRAM tracking"],
            screenshot=ScreenshotSpec(url="http://localhost:5173"),
        )
        assert len(scene.key_points) == 2

    def test_duration_hint_minimum(self):
        with pytest.raises(ValidationError):
            DemoScene(
                title="X",
                narration="Y",
                duration_hint=0.0,
                screenshot=ScreenshotSpec(url="http://localhost:5173"),
            )


class TestDemoScript:
    def test_full_script(self):
        script = DemoScript(
            title="System Demo",
            audience="family",
            scenes=[
                DemoScene(
                    title="Dashboard",
                    narration="Here is the dashboard.",
                    duration_hint=5.0,
                    screenshot=ScreenshotSpec(url="http://localhost:5173"),
                ),
            ],
            intro_narration="Welcome to the demo.",
            outro_narration="That is the system.",
        )
        assert len(script.scenes) == 1
        assert script.audience == "family"


class TestLoadPersonas:
    def test_loads_archetypes(self):
        personas = load_personas()
        assert "family" in personas
        assert "technical-peer" in personas
        assert "leadership" in personas
        assert "team-member" in personas

    def test_persona_fields(self):
        personas = load_personas()
        family = personas["family"]
        assert isinstance(family, AudiencePersona)
        assert "language" in family.vocabulary.lower() or family.vocabulary == "simple"
        assert len(family.show) > 0
        assert family.max_scenes > 0
