from __future__ import annotations

import json
from pathlib import Path

from agents.effect_graph.registry import ShaderRegistry
from agents.effect_graph.types import EffectGraph, NodeInstance
from agents.studio_compositor.preset_policy import (
    autonomous_fx_mutations_enabled,
    evaluate_preset_graph_policy,
    evaluate_preset_policy,
)

NODES_DIR = Path(__file__).parent.parent.parent / "agents" / "shaders" / "nodes"
PRESETS_DIR = Path(__file__).parent.parent.parent / "presets"


def _registry() -> ShaderRegistry:
    return ShaderRegistry(NODES_DIR)


def _camera_legible_env() -> dict[str, str]:
    return {
        "HAPAX_CAMERA_LEGIBLE_FX_ONLY": "1",
        "HAPAX_CAMERA_LEGIBLE_PRESET_ALLOWLIST": "clean",
    }


def _graph(nodes: dict[str, NodeInstance], edges: list[list[str]]) -> EffectGraph:
    return EffectGraph(name="Clean", nodes=nodes, edges=edges)


def test_preset_policy_blocks_denylisted_display_or_file_names(monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_COMPOSITOR_PRESET_DENYLIST", "chrome_mirror_brushed")

    decision = evaluate_preset_policy("Chrome Mirror Brushed")

    assert decision.allowed is False
    assert decision.reason == "preset_denylisted"
    assert decision.matched == ("chrome_mirror_brushed",)


def test_preset_policy_honors_camera_legible_allowlist(monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_CAMERA_LEGIBLE_FX_ONLY", "1")
    monkeypatch.setenv("HAPAX_CAMERA_LEGIBLE_PRESET_ALLOWLIST", "clean")

    blocked = evaluate_preset_policy("Chrome Mirror Brushed")
    allowed = evaluate_preset_policy("Clean")

    assert blocked.allowed is False
    assert blocked.reason == "camera_legible_allowlist"
    assert allowed.allowed is True


def test_autonomous_fx_mutation_flag_false_values(monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_FX_AUTONOMOUS_MUTATIONS", "0")
    assert autonomous_fx_mutations_enabled() is False

    monkeypatch.setenv("HAPAX_FX_AUTONOMOUS_MUTATIONS", "disabled")
    assert autonomous_fx_mutations_enabled() is False

    monkeypatch.setenv("HAPAX_FX_AUTONOMOUS_MUTATIONS", "1")
    assert autonomous_fx_mutations_enabled() is True


def test_camera_legible_graph_policy_blocks_postprocess_anonymize() -> None:
    graph = _graph(
        {
            "post": NodeInstance(type="postprocess", params={"anonymize": 1.0}),
            "out": NodeInstance(type="output"),
        },
        [["@live", "post"], ["post", "out"]],
    )

    decision = evaluate_preset_graph_policy(
        graph,
        registry=_registry(),
        env=_camera_legible_env(),
    )

    assert decision.allowed is False
    assert decision.reason == "camera_legible_anonymize"
    assert decision.matched == ("post", "anonymize=1")


def test_camera_legible_graph_policy_blocks_full_frame_noise_nodes() -> None:
    graph = _graph(
        {
            "noise": NodeInstance(type="noise_overlay", params={"intensity": 0.02}),
            "out": NodeInstance(type="output"),
        },
        [["@live", "noise"], ["noise", "out"]],
    )

    decision = evaluate_preset_graph_policy(
        graph,
        registry=_registry(),
        env=_camera_legible_env(),
    )

    assert decision.allowed is False
    assert decision.reason == "camera_legible_full_frame_noise"
    assert decision.matched == ("noise", "noise_overlay")


def test_live_surface_graph_policy_is_on_by_default() -> None:
    graph = _graph(
        {
            "noise": NodeInstance(type="noise_overlay", params={"intensity": 0.02}),
            "out": NodeInstance(type="output"),
        },
        [["@live", "noise"], ["noise", "out"]],
    )

    decision = evaluate_preset_graph_policy(
        graph,
        registry=_registry(),
        env={},
    )

    assert decision.allowed is False
    assert decision.reason == "camera_legible_full_frame_noise"


def test_live_surface_graph_policy_can_be_disabled_for_offline_tools() -> None:
    graph = EffectGraph(
        name="Offline Tool Probe",
        nodes={
            "noise": NodeInstance(type="noise_overlay", params={"intensity": 0.02}),
            "out": NodeInstance(type="output"),
        },
        edges=[["@live", "noise"], ["noise", "out"]],
    )

    decision = evaluate_preset_graph_policy(
        graph,
        registry=_registry(),
        env={"HAPAX_LIVE_SURFACE_EFFECT_POLICY": "0"},
    )

    assert decision.allowed is True


def test_camera_legible_graph_policy_allows_neutral_content_slot_nodes() -> None:
    graph = _graph(
        {
            "content": NodeInstance(type="content_layer"),
            "out": NodeInstance(type="output"),
        },
        [["@live", "content"], ["content", "out"]],
    )

    decision = evaluate_preset_graph_policy(
        graph,
        registry=_registry(),
        env=_camera_legible_env(),
    )

    assert decision.allowed is True


def test_content_layer_manifest_declares_camera_legible_slot_contract() -> None:
    content_layer = _registry().get("content_layer")

    assert content_layer is not None
    assert content_layer.content_slot_policy == {
        "provider": "content_source_manager",
        "missing": "transparent_noop",
        "manager_required": True,
        "opacity_source": "family_filtered",
        "camera_legible_max_opacity": 0.35,
        "camera_geometry_policy": {"overlay_only": True, "destructive": False},
    }


def test_camera_legible_graph_policy_blocks_active_unbound_content_slots() -> None:
    graph = _graph(
        {
            "content": NodeInstance(
                type="content_layer",
                params={"salience": 0.2, "intensity": 0.1},
            ),
            "out": NodeInstance(type="output"),
        },
        [["@live", "content"], ["content", "out"]],
    )

    decision = evaluate_preset_graph_policy(
        graph,
        registry=_registry(),
        env=_camera_legible_env(),
    )

    assert decision.allowed is False
    assert decision.reason == "camera_legible_unbound_content_slots"
    assert decision.matched == ("content", "content_layer")


def test_camera_legible_graph_policy_blocks_content_slots_without_contract() -> None:
    graph = _graph(
        {
            "content": NodeInstance(type="sierpinski_content"),
            "out": NodeInstance(type="output"),
        },
        [["@live", "content"], ["content", "out"]],
    )

    decision = evaluate_preset_graph_policy(
        graph,
        registry=_registry(),
        env=_camera_legible_env(),
    )

    assert decision.allowed is False
    assert decision.reason == "camera_legible_content_slot_contract"
    assert decision.matched == ("content", "sierpinski_content")


def test_camera_legible_graph_policy_blocks_low_posterize_defaults() -> None:
    graph = _graph(
        {
            "posterize": NodeInstance(type="posterize"),
            "out": NodeInstance(type="output"),
        },
        [["@live", "posterize"], ["posterize", "out"]],
    )

    decision = evaluate_preset_graph_policy(
        graph,
        registry=_registry(),
        env=_camera_legible_env(),
    )

    assert decision.allowed is False
    assert decision.reason == "camera_legible_posterize_levels"
    assert decision.matched == ("posterize", "levels=4")


def test_clean_preset_satisfies_camera_legible_graph_policy() -> None:
    raw = json.loads((PRESETS_DIR / "clean.json").read_text())
    graph = EffectGraph(**raw)

    decision = evaluate_preset_graph_policy(
        graph,
        registry=_registry(),
        env=_camera_legible_env(),
    )

    assert "content_layer" not in {node.type for node in graph.nodes.values()}
    assert decision.allowed is True
