"""Tests for WGSL execution plan compiler."""

from __future__ import annotations

import json
from pathlib import Path

from agents.effect_graph.types import EffectGraph
from agents.effect_graph.wgsl_compiler import compile_to_wgsl_plan, write_wgsl_pipeline

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _single_node_graph(node_type: str = "bloom", params: dict | None = None) -> EffectGraph:
    """Minimal graph: @live -> node -> output."""
    return EffectGraph(
        name="test-single",
        nodes={
            "n1": {"type": node_type, "params": params or {"intensity": 0.5}},
            "out": {"type": "output"},
        },
        edges=[["@live", "n1"], ["n1", "out"]],
    )


def _chain_graph() -> EffectGraph:
    """Two-node chain: @live -> bloom -> colorgrade -> output."""
    return EffectGraph(
        name="test-chain",
        nodes={
            "bloom1": {"type": "bloom", "params": {"intensity": 0.8}},
            "grade1": {"type": "colorgrade", "params": {"brightness": 1.2}},
            "out": {"type": "output"},
        },
        edges=[["@live", "bloom1"], ["bloom1", "grade1"], ["grade1", "out"]],
    )


def _main_passes(plan: dict) -> list[dict]:
    """Phase 5a v2 plan accessor: return the ``main`` target's passes.

    Most existing tests assert against the single ``main`` target's
    passes; this helper keeps the assertions readable instead of
    repeating ``plan["targets"]["main"]["passes"]`` everywhere.
    """
    return plan["targets"]["main"]["passes"]


# ---------------------------------------------------------------------------
# compile_to_wgsl_plan
# ---------------------------------------------------------------------------


class TestCompileToWgslPlan:
    """Phase 5a: plan shape is v2 with a ``targets`` dict.

    Single-output graphs default to a one-key targets dict named
    ``"main"`` — the existing assertions are reachable through the
    ``_main_passes`` helper without changing their semantics.
    """

    def test_single_node_produces_one_pass(self):
        plan = compile_to_wgsl_plan(_single_node_graph())
        assert plan["version"] == 2
        assert len(_main_passes(plan)) == 1

    def test_single_node_shader_name(self):
        plan = compile_to_wgsl_plan(_single_node_graph())
        assert _main_passes(plan)[0]["shader"] == "bloom.wgsl"

    def test_single_node_type_is_render(self):
        plan = compile_to_wgsl_plan(_single_node_graph())
        assert _main_passes(plan)[0]["type"] == "render"

    def test_chain_preserves_topological_order(self):
        plan = compile_to_wgsl_plan(_chain_graph())
        passes = _main_passes(plan)
        assert len(passes) == 2
        assert passes[0]["node_id"] == "bloom1"
        assert passes[1]["node_id"] == "grade1"

    def test_chain_wiring(self):
        plan = compile_to_wgsl_plan(_chain_graph())
        passes = _main_passes(plan)
        # bloom1 reads from @live
        assert "@live" in passes[0]["inputs"]
        # grade1 reads from bloom1's output (layer_0)
        assert "layer_0" in passes[1]["inputs"]

    def test_last_pass_output_is_final(self):
        plan = compile_to_wgsl_plan(_single_node_graph())
        assert _main_passes(plan)[-1]["output"] == "final"

    def test_chain_last_pass_output_is_final(self):
        plan = compile_to_wgsl_plan(_chain_graph())
        passes = _main_passes(plan)
        assert passes[-1]["output"] == "final"
        assert passes[0]["output"] == "layer_0"

    def test_uniforms_from_params(self):
        plan = compile_to_wgsl_plan(_single_node_graph(params={"intensity": 0.7, "radius": 3}))
        uniforms = _main_passes(plan)[0]["uniforms"]
        assert uniforms["intensity"] == 0.7
        assert uniforms["radius"] == 3

    def test_temporal_node_type(self):
        """fluid_sim is a temporal render pass (transpiled from GLSL fragment shader)."""
        graph = EffectGraph(
            name="test-temporal",
            nodes={
                "fs": {"type": "fluid_sim", "params": {"viscosity": 0.001}},
                "out": {"type": "output"},
            },
            edges=[["@live", "fs"], ["fs", "out"]],
        )
        plan = compile_to_wgsl_plan(graph)
        passes = _main_passes(plan)
        assert passes[0]["type"] == "render"
        assert passes[0].get("temporal") is True
        assert "@accum_fs" in passes[0]["inputs"]

    def test_reaction_diffusion_is_temporal(self):
        """reaction_diffusion should compile as a temporal render pass with @accum_ input."""
        graph = EffectGraph(
            name="test-rd",
            nodes={
                "rd": {
                    "type": "reaction_diffusion",
                    "params": {"feed_rate": 0.055, "kill_rate": 0.062},
                },
                "out": {"type": "output"},
            },
            edges=[["@live", "rd"], ["rd", "out"]],
        )
        plan = compile_to_wgsl_plan(graph)
        passes = _main_passes(plan)
        assert len(passes) == 1
        p = passes[0]
        assert p["node_id"] == "rd"
        assert p["shader"] == "reaction_diffusion.wgsl"
        assert p["type"] == "render"
        assert p.get("temporal") is True
        assert "@accum_rd" in p["inputs"]

    def test_single_node_emits_backend_field(self):
        """Phase 3a: every pass descriptor must include a backend key.

        Defaults to ``wgsl_render`` for shader nodes — the only backend
        wired in Phase 3a. Future sub-phases add cairo/text/image_file.
        """
        plan = compile_to_wgsl_plan(_single_node_graph())
        assert _main_passes(plan)[0]["backend"] == "wgsl_render"

    def test_chain_all_passes_emit_backend(self):
        """Every pass in a multi-node chain must carry the backend key."""
        plan = compile_to_wgsl_plan(_chain_graph())
        for pass_desc in _main_passes(plan):
            assert pass_desc["backend"] == "wgsl_render", (
                f"pass {pass_desc.get('node_id')} missing backend"
            )

    def test_temporal_node_emits_backend(self):
        """Temporal passes (like reaction_diffusion) also carry the backend."""
        graph = EffectGraph(
            name="test-rd-backend",
            nodes={
                "rd": {"type": "reaction_diffusion", "params": {}},
                "out": {"type": "output"},
            },
            edges=[["@live", "rd"], ["rd", "out"]],
        )
        plan = compile_to_wgsl_plan(graph)
        assert _main_passes(plan)[0]["backend"] == "wgsl_render"

    def test_reaction_diffusion_params(self):
        """R-D pass should include feed_rate and kill_rate in uniforms."""
        graph = EffectGraph(
            name="test-rd-params",
            nodes={
                "rd": {
                    "type": "reaction_diffusion",
                    "params": {
                        "feed_rate": 0.04,
                        "kill_rate": 0.06,
                        "diffusion_a": 1.0,
                        "diffusion_b": 0.5,
                        "speed": 1.5,
                    },
                },
                "out": {"type": "output"},
            },
            edges=[["@live", "rd"], ["rd", "out"]],
        )
        plan = compile_to_wgsl_plan(graph)
        u = _main_passes(plan)[0]["uniforms"]
        assert u["feed_rate"] == 0.04
        assert u["kill_rate"] == 0.06
        assert u["speed"] == 1.0

    # ----- Phase 5a: multi-target shape -----

    def test_v2_plan_has_targets_dict(self):
        plan = compile_to_wgsl_plan(_single_node_graph())
        assert "targets" in plan
        assert isinstance(plan["targets"], dict)
        assert "passes" not in plan  # v1 flat list is gone

    def test_single_output_default_target_name_is_main(self):
        plan = compile_to_wgsl_plan(_single_node_graph())
        assert list(plan["targets"].keys()) == ["main"]

    def test_explicit_target_name_via_params(self):
        graph = EffectGraph(
            name="hud-only",
            nodes={
                "b": {"type": "bloom", "params": {}},
                "o": {"type": "output", "params": {"target": "hud"}},
            },
            edges=[["@live", "b"], ["b", "o"]],
        )
        plan = compile_to_wgsl_plan(graph)
        assert list(plan["targets"].keys()) == ["hud"]
        assert len(plan["targets"]["hud"]["passes"]) == 1

    def test_multi_output_emits_multi_target_plan(self):
        """Two output nodes → two separate targets, each with its own
        topo-sorted pass list. Shared subgraphs duplicate (Phase 5b
        will dedupe)."""
        graph = EffectGraph(
            name="multi",
            nodes={
                "noise": {"type": "noise_overlay", "params": {}},
                "a_color": {"type": "colorgrade", "params": {"brightness": 1.2}},
                "b_blur": {"type": "bloom", "params": {"intensity": 0.5}},
                "main_out": {"type": "output", "params": {"target": "main"}},
                "hud_out": {"type": "output", "params": {"target": "hud"}},
            },
            edges=[
                ["@live", "noise"],
                ["noise", "a_color"],
                ["a_color", "main_out"],
                ["noise", "b_blur"],
                ["b_blur", "hud_out"],
            ],
        )
        plan = compile_to_wgsl_plan(graph)
        assert set(plan["targets"].keys()) == {"main", "hud"}
        main_passes = plan["targets"]["main"]["passes"]
        hud_passes = plan["targets"]["hud"]["passes"]
        # main: noise → a_color (2 passes)
        # hud:  noise → b_blur  (2 passes)
        assert [p["node_id"] for p in main_passes] == ["noise", "a_color"]
        assert [p["node_id"] for p in hud_passes] == ["noise", "b_blur"]
        # Both targets' last pass writes to "final" (per-target namespace).
        assert main_passes[-1]["output"] == "final"
        assert hud_passes[-1]["output"] == "final"


# ---------------------------------------------------------------------------
# write_wgsl_pipeline
# ---------------------------------------------------------------------------


class TestWriteWgslPipeline:
    def test_creates_plan_json(self, tmp_path: Path):
        plan = compile_to_wgsl_plan(_single_node_graph())
        plan_path = write_wgsl_pipeline(plan, output_dir=tmp_path, nodes_dir=tmp_path)
        assert plan_path == tmp_path / "plan.json"
        assert plan_path.exists()
        loaded = json.loads(plan_path.read_text())
        assert loaded["version"] == 2
        assert "targets" in loaded
        assert "passes" not in loaded

    def test_copies_wgsl_files(self, tmp_path: Path):
        nodes_dir = tmp_path / "nodes"
        nodes_dir.mkdir()
        out_dir = tmp_path / "out"

        # Create a fake .wgsl source
        (nodes_dir / "bloom.wgsl").write_text("// bloom shader")

        plan = compile_to_wgsl_plan(_single_node_graph())
        write_wgsl_pipeline(plan, output_dir=out_dir, nodes_dir=nodes_dir)

        assert (out_dir / "bloom.wgsl").exists()
        assert (out_dir / "bloom.wgsl").read_text() == "// bloom shader"

    def test_missing_wgsl_does_not_crash(self, tmp_path: Path):
        nodes_dir = tmp_path / "nodes"
        nodes_dir.mkdir()
        out_dir = tmp_path / "out"

        plan = compile_to_wgsl_plan(_single_node_graph())
        # Should not raise even though bloom.wgsl doesn't exist in nodes_dir
        write_wgsl_pipeline(plan, output_dir=out_dir, nodes_dir=nodes_dir)
        assert (out_dir / "plan.json").exists()
