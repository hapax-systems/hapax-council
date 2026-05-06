"""Pins the additive M8/music-reactive effect-graph preset variation."""

from __future__ import annotations

import json
from pathlib import Path

from agents.effect_graph.audio_visual_modulation import (
    AudioVisualizerRegister,
    AudioVisualSourceRole,
    PublicClaimPolicy,
)
from agents.effect_graph.compiler import GraphCompiler
from agents.effect_graph.modulator import UniformModulator
from agents.effect_graph.registry import ShaderRegistry
from agents.effect_graph.types import EffectGraph

REPO_ROOT = Path(__file__).resolve().parents[2]
PRESET_PATH = REPO_ROOT / "presets" / "m8_music_reactive_transport.json"
NODES_DIR = REPO_ROOT / "agents" / "shaders" / "nodes"

PROHIBITED_FLASH_PARAMS = {"active", "brightness", "color_a", "intensity", "opacity"}


def _load_preset() -> EffectGraph:
    return EffectGraph(**json.loads(PRESET_PATH.read_text(encoding="utf-8")))


def test_m8_music_reactive_transport_preset_compiles_within_slots() -> None:
    graph = _load_preset()
    compiler = GraphCompiler(ShaderRegistry(NODES_DIR))
    plan = compiler.compile(graph)

    shader_steps = [
        step for step in plan.steps if step.node_type != "output" and step.shader_source
    ]

    assert graph.name == "M8 Music Reactive Transport"
    assert len(shader_steps) <= 8
    assert graph.nodes["out"].type == "output"


def test_m8_music_reactive_transport_uses_namespaced_nonflashing_modulations() -> None:
    graph = _load_preset()

    assert graph.modulations
    assert {binding.source.split(".", 1)[0] for binding in graph.modulations} == {"music"}
    assert all(binding.param not in PROHIBITED_FLASH_PARAMS for binding in graph.modulations)
    assert all("waveform" not in binding.node for binding in graph.modulations)


def test_m8_music_reactive_transport_governor_allows_tonal_and_spatial_music() -> None:
    graph = _load_preset()
    modulator = UniformModulator()
    modulator.replace_all(graph.modulations)

    updates = modulator.tick(
        {
            "mixer_bass": 0.72,
            "mixer_energy": 0.54,
            "mixer_high": 0.31,
            "spectral_centroid": 0.63,
        }
    )

    assert set(updates) == {(binding.node, binding.param) for binding in graph.modulations}
    assert len(modulator.last_modulation_decisions) == len(graph.modulations)
    for decision in modulator.last_modulation_decisions:
        assert decision.allowed is True
        assert decision.fallback_used is True
        assert decision.source_role is AudioVisualSourceRole.PROGRAMME_MUSIC
        assert decision.register is not AudioVisualizerRegister.WAVEFORM
        assert decision.public_claim_policy is PublicClaimPolicy.NO_CLAIM_AUTHORITY
        assert "source:audio-reactivity:programme_music" in decision.source_refs
        assert "health:scrim:anti_visualizer" in decision.health_refs
