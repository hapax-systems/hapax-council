from __future__ import annotations

import json
import re
from pathlib import Path

from agents.effect_graph.registry import ShaderRegistry
from agents.effect_graph.types import EffectGraph, NodeInstance
from agents.studio_compositor.preset_policy import (
    apply_live_surface_param_bounds,
    autonomous_fx_mutations_enabled,
    evaluate_preset_graph_policy,
    evaluate_preset_policy,
)
from shared.live_surface_effect_policy import (
    LIVE_SURFACE_GLSL_PENDING_SOURCE_BOUND_REPAIR_NODE_TYPES,
    live_surface_policy_kind,
    live_surface_unclassified_node_types,
)
from shared.live_surface_effect_policy import (
    apply_live_surface_param_bounds as apply_shared_live_surface_param_bounds,
)

NODES_DIR = Path(__file__).parent.parent.parent / "agents" / "shaders" / "nodes"
PRESETS_DIR = Path(__file__).parent.parent.parent / "presets"
EFFECT_DRIFT_RS = (
    Path(__file__).parent.parent.parent
    / "hapax-logos"
    / "crates"
    / "hapax-visual"
    / "src"
    / "effect_drift.rs"
)
SCENE_GRID_WGSL = (
    Path(__file__).parent.parent.parent
    / "hapax-logos"
    / "crates"
    / "hapax-visual"
    / "src"
    / "shaders"
    / "scene_grid.wgsl"
)


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


def test_live_surface_bounds_clamp_postprocess_anonymize() -> None:
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

    assert decision.allowed is True
    bounded = apply_live_surface_param_bounds("postprocess", {"anonymize": 1.0})
    assert bounded["anonymize"] == 0.5


def test_camera_legible_graph_policy_allows_bounded_bloom() -> None:
    graph = _graph(
        {
            "bloom": NodeInstance(type="bloom", params={"alpha": 0.5}),
            "out": NodeInstance(type="output"),
        },
        [["@live", "bloom"], ["bloom", "out"]],
    )

    decision = evaluate_preset_graph_policy(
        graph,
        registry=_registry(),
        env=_camera_legible_env(),
    )

    assert decision.allowed is True
    bounded = apply_live_surface_param_bounds("bloom", {"alpha": 0.5})
    assert bounded["alpha"] == 0.35


def test_camera_legible_graph_policy_blocks_unrepaired_glsl_pane_nodes() -> None:
    graph = _graph(
        {
            "halftone": NodeInstance(type="halftone", params={"dot_size": 6.0}),
            "out": NodeInstance(type="output"),
        },
        [["@live", "halftone"], ["halftone", "out"]],
    )

    decision = evaluate_preset_graph_policy(
        graph,
        registry=_registry(),
        env=_camera_legible_env(),
    )

    assert decision.allowed is False
    assert decision.reason == "camera_legible_glsl_pending_source_bound_repair"
    assert decision.matched == ("halftone", "halftone")
    bounded = apply_live_surface_param_bounds(
        "noise_overlay",
        {"intensity": 0.5, "animated": True},
    )
    assert bounded == {"intensity": 0.1, "animated": False}


def test_live_surface_graph_policy_allows_repaired_source_bound_nodes_by_default() -> None:
    graph = _graph(
        {
            "nightvision": NodeInstance(type="nightvision_tint", params={"green_intensity": 0.8}),
            "out": NodeInstance(type="output"),
        },
        [["@live", "nightvision"], ["nightvision", "out"]],
    )

    decision = evaluate_preset_graph_policy(
        graph,
        registry=_registry(),
        env={},
    )

    assert decision.allowed is True
    bounded = apply_live_surface_param_bounds("nightvision_tint", {"green_intensity": 0.8})
    assert bounded["green_intensity"] == 0.7


def test_live_surface_graph_policy_can_be_disabled_for_offline_tools() -> None:
    graph = EffectGraph(
        name="Offline Tool Probe",
        nodes={
            "noise": NodeInstance(type="noise_gen", params={"amplitude": 0.02}),
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


def test_live_surface_bounds_clamp_low_posterize_defaults() -> None:
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

    assert decision.allowed is True
    bounded = apply_live_surface_param_bounds("posterize", {"levels": 4.0})
    assert bounded["levels"] == 8.0


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


def test_live_surface_policy_classifies_every_shader_node() -> None:
    registry = _registry()

    assert live_surface_unclassified_node_types(set(registry.node_types)) == set()


def test_glsl_pending_repair_nodes_still_have_live_surface_bounds() -> None:
    assert LIVE_SURFACE_GLSL_PENDING_SOURCE_BOUND_REPAIR_NODE_TYPES
    assert {
        node
        for node in LIVE_SURFACE_GLSL_PENDING_SOURCE_BOUND_REPAIR_NODE_TYPES
        if live_surface_policy_kind(node) != "bounded"
    } == set()


def test_source_preserving_repaired_nodes_are_bounded_not_blocked() -> None:
    repaired_nodes = {
        "ascii",
        "blend",
        "breathing",
        "chroma_key",
        "circular_mask",
        "crossfade",
        "diff",
        "displacement_map",
        "droste",
        "edge_detect",
        "fluid_sim",
        "kaleidoscope",
        "luma_key",
        "mirror",
        "nightvision_tint",
        "noise_gen",
        "particle_system",
        "reaction_diffusion",
        "rutt_etra",
        "solid",
        "strobe",
        "syrup",
        "threshold",
        "tile",
        "tunnel",
        "waveform_render",
    }

    assert {node for node in repaired_nodes if live_surface_policy_kind(node) != "bounded"} == set()
    assert apply_shared_live_surface_param_bounds(
        "displacement_map", {"strength_x": 0.2, "strength_y": -0.2}
    ) == {"strength_x": 0.055, "strength_y": -0.055}
    assert apply_shared_live_surface_param_bounds("mirror", {"axis": 2.0, "position": 0.9}) == {
        "axis": 1.0,
        "position": 0.75,
    }


def test_rust_autonomous_drift_only_schedules_live_surface_bounded_nodes() -> None:
    source = EFFECT_DRIFT_RS.read_text()
    shader_table = source.split("pub static SHADERS:", 1)[1].split("pub static FEEDBACK_DEF", 1)[0]
    drift_nodes = set(re.findall(r'name: "([^"]+)"', shader_table))

    assert drift_nodes
    blocked = {
        node for node in drift_nodes if live_surface_policy_kind(node) == "blocked_pending_repair"
    }
    assert blocked == set()


def test_scene_grid_keeps_spatial_visibility_floor() -> None:
    source = SCENE_GRID_WGSL.read_text()

    assert "max(smoothstep(22.0, 1.5, dist), 0.26)" in source
    assert "major < 0.003" in source
    assert "alpha = 0.105;" in source
    assert "alpha = 0.088;" in source
    assert "var alpha = major * 0.50 * dist_fade" in source
