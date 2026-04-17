"""Tests for the LRR Phase 9 §3.3 research-aware chat reactor.

Covers the ``ReactorSensitivity`` profile, working-mode resolution, and
the two-window A/B behaviour the ``audience-engagement-ab`` drill needs
(default window = ambient matching, research window = ``!fx``-prefixed
explicit syntax + longer cooldown).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.studio_compositor import chat_reactor
from agents.studio_compositor.chat_reactor import (
    DEFAULT_SENSITIVITY,
    RESEARCH_MODE_SENSITIVITY,
    PresetReactor,
    ReactorSensitivity,
    resolve_sensitivity_for_working_mode,
)


@pytest.fixture
def preset_dir(tmp_path):
    d = tmp_path / "presets"
    d.mkdir()
    for name in ("halftone_preset", "neon", "datamosh"):
        (d / f"{name}.json").write_text(
            json.dumps({"name": name, "nodes": {"r": {"type": "colorgrade"}}, "edges": []}),
            encoding="utf-8",
        )
    return d


class TestSensitivityProfiles:
    def test_default_cooldown_and_no_prefix(self):
        assert DEFAULT_SENSITIVITY.cooldown_seconds == 30.0
        assert DEFAULT_SENSITIVITY.require_trigger_prefix is None

    def test_research_mode_longer_cooldown_with_prefix(self):
        assert RESEARCH_MODE_SENSITIVITY.cooldown_seconds == 90.0
        assert RESEARCH_MODE_SENSITIVITY.require_trigger_prefix == "!fx"


class TestResolveSensitivity:
    def test_research_maps_to_research_mode(self):
        assert resolve_sensitivity_for_working_mode("research") is RESEARCH_MODE_SENSITIVITY

    def test_rnd_maps_to_default(self):
        assert resolve_sensitivity_for_working_mode("rnd") is DEFAULT_SENSITIVITY

    def test_unknown_maps_to_default(self):
        assert resolve_sensitivity_for_working_mode("") is DEFAULT_SENSITIVITY
        assert resolve_sensitivity_for_working_mode("anything-else") is DEFAULT_SENSITIVITY


class TestReactorSensitivityIntegration:
    def test_default_reactor_matches_ambient(self, preset_dir: Path, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(chat_reactor, "FX_CURRENT_FILE", tmp_path / "fx-current.txt")
        reactor = PresetReactor(
            preset_dir=preset_dir,
            mutation_file=tmp_path / "graph.json",
            sensitivity=DEFAULT_SENSITIVITY,
        )
        # Ambient mention anywhere in the message — matches.
        assert reactor.match("let's try halftone for the next drop") == "halftone_preset"

    def test_research_mode_requires_fx_prefix(self, preset_dir: Path, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(chat_reactor, "FX_CURRENT_FILE", tmp_path / "fx-current.txt")
        reactor = PresetReactor(
            preset_dir=preset_dir,
            mutation_file=tmp_path / "graph.json",
            sensitivity=RESEARCH_MODE_SENSITIVITY,
        )
        # Same text as before — research mode ignores it without the prefix.
        assert reactor.match("let's try halftone for the next drop") is None

    def test_research_mode_honors_fx_prefix(self, preset_dir: Path, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(chat_reactor, "FX_CURRENT_FILE", tmp_path / "fx-current.txt")
        reactor = PresetReactor(
            preset_dir=preset_dir,
            mutation_file=tmp_path / "graph.json",
            sensitivity=RESEARCH_MODE_SENSITIVITY,
        )
        assert reactor.match("!fx halftone") == "halftone_preset"
        assert reactor.match("  !FX neon  ") == "neon"  # case-insensitive + leading WS

    def test_research_mode_does_not_match_prefix_itself(
        self, preset_dir: Path, tmp_path: Path, monkeypatch
    ):
        monkeypatch.setattr(chat_reactor, "FX_CURRENT_FILE", tmp_path / "fx-current.txt")
        reactor = PresetReactor(
            preset_dir=preset_dir,
            mutation_file=tmp_path / "graph.json",
            sensitivity=RESEARCH_MODE_SENSITIVITY,
        )
        # "!fx" alone (no preset keyword after) must not latch anything.
        assert reactor.match("!fx") is None

    def test_cooldown_from_sensitivity_takes_effect(
        self, preset_dir: Path, tmp_path: Path, monkeypatch
    ):
        monkeypatch.setattr(chat_reactor, "FX_CURRENT_FILE", tmp_path / "fx-current.txt")
        research_reactor = PresetReactor(
            preset_dir=preset_dir,
            mutation_file=tmp_path / "graph.json",
            sensitivity=RESEARCH_MODE_SENSITIVITY,
        )
        default_reactor = PresetReactor(
            preset_dir=preset_dir,
            mutation_file=tmp_path / "graph.json",
            sensitivity=DEFAULT_SENSITIVITY,
        )
        assert research_reactor._cooldown == 90.0
        assert default_reactor._cooldown == 30.0

    def test_explicit_cooldown_kwarg_overrides_profile(
        self, preset_dir: Path, tmp_path: Path, monkeypatch
    ):
        monkeypatch.setattr(chat_reactor, "FX_CURRENT_FILE", tmp_path / "fx-current.txt")
        reactor = PresetReactor(
            preset_dir=preset_dir,
            mutation_file=tmp_path / "graph.json",
            sensitivity=RESEARCH_MODE_SENSITIVITY,
            cooldown=5.0,
        )
        # Cooldown overridden, but prefix from RESEARCH_MODE_SENSITIVITY still active.
        assert reactor._cooldown == 5.0
        assert reactor.sensitivity.require_trigger_prefix == "!fx"

    def test_sensitivity_property_reflects_state(
        self, preset_dir: Path, tmp_path: Path, monkeypatch
    ):
        monkeypatch.setattr(chat_reactor, "FX_CURRENT_FILE", tmp_path / "fx-current.txt")
        reactor = PresetReactor(
            preset_dir=preset_dir,
            mutation_file=tmp_path / "graph.json",
            sensitivity=RESEARCH_MODE_SENSITIVITY,
        )
        assert reactor.sensitivity == ReactorSensitivity(
            cooldown_seconds=90.0, require_trigger_prefix="!fx"
        )


class TestBackwardCompatibility:
    def test_no_kwargs_defaults_to_ambient(self, preset_dir: Path, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(chat_reactor, "FX_CURRENT_FILE", tmp_path / "fx-current.txt")
        reactor = PresetReactor(preset_dir=preset_dir, mutation_file=tmp_path / "graph.json")
        assert reactor._cooldown == 30.0
        assert reactor.sensitivity.require_trigger_prefix is None
        assert reactor.match("halftone") == "halftone_preset"

    def test_legacy_cooldown_kwarg_still_works(self, preset_dir: Path, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(chat_reactor, "FX_CURRENT_FILE", tmp_path / "fx-current.txt")
        reactor = PresetReactor(
            preset_dir=preset_dir, mutation_file=tmp_path / "graph.json", cooldown=12.0
        )
        assert reactor._cooldown == 12.0
        # Default sensitivity → no prefix required → still ambient.
        assert reactor.sensitivity.require_trigger_prefix is None
