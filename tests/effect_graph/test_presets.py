"""Tests that preset JSON files parse into valid EffectGraph models."""

import json
from pathlib import Path

from agents.effect_graph.types import EffectGraph

PRESETS_DIR = Path(__file__).parent.parent.parent / "presets"


def _load(name: str) -> EffectGraph:
    return EffectGraph(**json.loads((PRESETS_DIR / f"{name}.json").read_text()))


def test_ghost_preset():
    g = _load("ghost")
    assert g.name == "Ghost"
    assert "trail" in g.nodes
    assert len(g.edges) == 3


def test_trails_preset():
    g = _load("trails")
    assert g.name == "Trails"
    assert len(g.modulations) == 2


def test_clean_preset():
    g = _load("clean")
    assert g.name == "Clean"
    assert g.transition_ms == 300
