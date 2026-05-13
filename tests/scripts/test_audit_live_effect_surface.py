from __future__ import annotations

import json
import runpy
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "audit-live-effect-surface.py"


def test_audit_live_effect_surface_covers_non_preset_surfaces() -> None:
    result = subprocess.run(
        [str(SCRIPT), "--no-runtime", "--strict"],
        text=True,
        capture_output=True,
        check=False,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["summary"]["preset_count"] >= 80
    assert payload["summary"]["shader_node_count"] >= 50
    assert payload["summary"]["live_surface_unclassified_node_type_count"] == 0
    assert payload["summary"]["live_surface_bounded_node_type_count"] >= 30
    assert payload["summary"]["preset_family_count"] >= 5
    assert payload["summary"]["palette_count"] >= 12
    assert payload["summary"]["palette_chain_count"] >= 1
    assert payload["summary"]["hero_effect_count"] == 8
    assert payload["summary"]["transition_primitive_count"] == 5
    assert payload["summary"]["layout_surface_effect_chain_slot_count"] > 0
    assert payload["summary"]["layout_assignment_effect_slot_count"] > 0
    assert payload["summary"]["cairo_source_registry_class_count"] >= 40
    assert payload["summary"]["legacy_studio_fx_effect_count"] >= 16
    assert "legacy_studio_fx" in payload["surfaces"]
    assert "legacy_studio_fx_registry" in payload["surfaces"]
    assert "reverie_imagination" in payload["surfaces"]
    assert "effect_orchestrators" in payload["surfaces"]
    assert "studio_compositor_package" in payload["surfaces"]
    assert "visual_sidecar_agents" in payload["surfaces"]
    assert "visual_output_bridges" in payload["surfaces"]
    assert "visual_output_branches" in payload["surfaces"]
    assert "visual_command_surfaces" in payload["surfaces"]
    assert "visual_systemd_units" in payload["surfaces"]
    assert "visual_plugins" in payload["surfaces"]
    assert "shared_visual_policy_models" in payload["surfaces"]
    assert "visual_manifests_configs" in payload["surfaces"]
    assert "logos_visual_ui" in payload["surfaces"]
    assert "homage_visuals" in payload["surfaces"]
    assert "palette_chains" in payload["surfaces"]
    assert "cairo_source_registry" in payload["surfaces"]
    assert "visual_scripts" in payload["surfaces"]
    assert "cairo_ward_implementations" in payload["surfaces"]
    assert "ward_fx" in payload["surfaces"]
    assert "layouts" in payload["surfaces"]
    assert "preset_family_selector" in payload["surfaces"]
    assert "live_surface_policy" in payload["surfaces"]
    assert "runtime_path_references" in payload["surfaces"]
    assert payload["summary"]["effect_orchestrator_file_count"] > 0
    assert payload["summary"]["studio_compositor_package_file_count"] > 0
    assert payload["summary"]["visual_sidecar_agent_file_count"] > 0
    assert payload["summary"]["visual_output_bridge_file_count"] > 0
    assert payload["summary"]["visual_output_branch_file_count"] > 0
    assert payload["summary"]["visual_command_surface_file_count"] > 0
    assert payload["summary"]["visual_systemd_unit_file_count"] > 0
    assert payload["summary"]["visual_plugin_file_count"] > 0
    assert payload["summary"]["shared_visual_policy_model_file_count"] > 0
    assert payload["summary"]["visual_script_file_count"] > 0
    assert payload["summary"]["logos_visual_ui_file_count"] > 0
    assert payload["summary"]["homage_visual_file_count"] > 0
    assert payload["summary"]["cairo_ward_implementation_file_count"] > 0
    assert payload["summary"]["runtime_visual_reference_path_count"] > 0
    assert payload["summary"]["runtime_visual_reference_uncurated_literal_path_count"] > 0
    assert (
        "/dev/shm/hapax-compositor/fx-current.txt"
        in payload["surfaces"]["runtime_path_references"]["literal_paths"]
    )
    assert (
        "/run/user/1000/hapax-compositor-commands.sock"
        in payload["surfaces"]["runtime_path_references"]["literal_paths"]
    )
    assert payload["surfaces"]["palette_chains"]["chain_count"] >= 1
    assert not payload["surfaces"]["palette_chains"]["missing_palette_refs"]
    assert not payload["surfaces"]["cairo_source_registry"]["layout_class_names_missing_registry"]
    assert "DURFCairoSource" in payload["surfaces"]["cairo_source_registry"]["registered_classes"]
    assert not payload["surfaces"]["legacy_studio_fx_registry"]["orphan_effect_modules"]
    assert not payload["surfaces"]["legacy_studio_fx_registry"]["missing_effect_modules"]
    assert "ghost" in payload["surfaces"]["legacy_studio_fx_registry"]["registered_effect_names"]
    assert "datamosh" in payload["surfaces"]["legacy_studio_fx_registry"]["registered_effect_names"]
    assert "grain_bump.wgsl" in payload["surfaces"]["shader_nodes"]["standalone_wgsl_files"]
    assert not payload["surfaces"]["live_surface_policy"]["unclassified_node_types"]
    assert "noise_overlay" in payload["surfaces"]["presets"]["high_risk_node_usage"]
    assert "glitch_block" in payload["surfaces"]["presets"]["high_risk_node_usage"]
    assert not payload["surfaces"]["preset_family_selector"]["missing_presets"]
    assert "legacy_studio_fx_must_be_classified_live_dormant_or_retired" in payload["coverage_gaps"]
    assert (
        "glfeedback_and_visual_output_bridges_need_live_exercise_proof" in payload["coverage_gaps"]
    )
    assert "visual_command_surfaces_can_mutate_layout_or_effect_state" in payload["coverage_gaps"]
    assert "visual_output_branches_need_viewer_truth_exercise_proof" in payload["coverage_gaps"]
    assert "visual_systemd_units_are_runtime_activation_surfaces" in payload["coverage_gaps"]
    assert (
        "visual_maintenance_scripts_can_mutate_or_restore_effect_state" in payload["coverage_gaps"]
    )
    assert (
        "shared_visual_policy_models_need_same_coverage_as_effect_code" in payload["coverage_gaps"]
    )
    assert (
        "standalone_wgsl_files_need_manifest_or_helper_classification" in payload["coverage_gaps"]
    )
    assert (
        "palette_scrim_chains_are_preset_like_visual_chains_and_need_live_policy_mapping"
        in payload["coverage_gaps"]
    )
    assert "runtime_visual_path_references_need_curated_policy_mapping" in payload["coverage_gaps"]


def test_audit_live_effect_surface_blocks_missing_governance_preset(tmp_path: Path) -> None:
    _write_minimal_repo(tmp_path)

    result = subprocess.run(
        [
            str(SCRIPT),
            "--repo-root",
            str(tmp_path),
            "--no-home-presets",
            "--no-runtime",
            "--strict",
        ],
        text=True,
        capture_output=True,
        check=False,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 10
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "visual_governance_missing_preset:missing" in payload["reasons"]


def test_audit_live_effect_surface_reads_all_imagination_plan_schemas() -> None:
    module = runpy.run_path(str(SCRIPT))
    iter_plan_passes = module["_iter_plan_passes"]

    rows = iter_plan_passes(
        {
            "steps": [{"shader": "legacy-step.wgsl"}],
            "passes": [{"shader": "legacy-pass.wgsl"}],
            "targets": {
                "main": {"passes": [{"shader": "target-main.wgsl"}]},
                "hud": {"passes": [{"shader": "target-hud.wgsl"}]},
            },
        }
    )

    assert [row["shader"] for row in rows] == [
        "legacy-step.wgsl",
        "legacy-pass.wgsl",
        "target-main.wgsl",
        "target-hud.wgsl",
    ]


def test_audit_live_effect_surface_discovers_uncurated_runtime_paths(tmp_path: Path) -> None:
    module = runpy.run_path(str(SCRIPT))
    scan_runtime_path_references = module["_scan_runtime_path_references"]

    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    (script_dir / "writer.py").write_text(
        "\n".join(
            [
                "KNOWN = '/dev/shm/hapax-compositor/fx-current.txt'",
                "UNCURATED = '/dev/shm/hapax-compositor/custom-visual-control.json'",
                "TEMPLATE = '/dev/shm/hapax-compositor/{role}.jpg'",
            ]
        ),
        encoding="utf-8",
    )

    payload = scan_runtime_path_references(tmp_path)

    assert "/dev/shm/hapax-compositor/fx-current.txt" in payload["literal_paths"]
    assert (
        "/dev/shm/hapax-compositor/custom-visual-control.json" in payload["uncurated_literal_paths"]
    )
    assert "/dev/shm/hapax-compositor/{role}.jpg" in payload["templated_paths"]


def _write_minimal_repo(root: Path) -> None:
    nodes = root / "agents" / "shaders" / "nodes"
    nodes.mkdir(parents=True)
    (nodes / "colorgrade.frag").write_text("void main() {}\n", encoding="utf-8")
    (nodes / "colorgrade.wgsl").write_text("@fragment fn main() {}\n", encoding="utf-8")
    (nodes / "colorgrade.json").write_text(
        json.dumps(
            {
                "node_type": "colorgrade",
                "backend": "wgsl_render",
                "glsl_fragment": "colorgrade.frag",
                "inputs": {"in": "frame"},
                "outputs": {"out": "frame"},
                "params": {},
                "temporal": False,
            }
        ),
        encoding="utf-8",
    )
    (nodes / "output.json").write_text(
        json.dumps(
            {
                "node_type": "output",
                "backend": "wgsl_render",
                "glsl_fragment": "",
                "inputs": {"in": "frame"},
                "outputs": {},
                "params": {},
                "temporal": False,
            }
        ),
        encoding="utf-8",
    )

    presets = root / "presets"
    presets.mkdir()
    (presets / "_default_modulations.json").write_text(
        json.dumps({"default_modulations": []}),
        encoding="utf-8",
    )
    (presets / "clean.json").write_text(
        json.dumps(
            {
                "name": "Clean",
                "nodes": {
                    "colorgrade": {"type": "colorgrade", "params": {}},
                    "out": {"type": "output", "params": {}},
                },
                "edges": [["@live", "colorgrade"], ["colorgrade", "out"]],
                "modulations": [],
            }
        ),
        encoding="utf-8",
    )

    governance = root / "agents" / "effect_graph"
    governance.mkdir(parents=True)
    (governance / "visual_governance.py").write_text(
        "\n".join(
            [
                "_STATE_MATRIX = {('nominal', 'low'): PresetFamily(presets=('missing', 'clean'))}",
                "_DEFAULT_FAMILY = PresetFamily(presets=('clean',))",
                "_GENRE_BIAS = {}",
            ]
        ),
        encoding="utf-8",
    )

    compositor = root / "agents" / "studio_compositor"
    compositor.mkdir(parents=True)
    (compositor / "transition_primitives.py").write_text(
        "\n".join(
            [
                "TRANSITION_NAMES = ('transition.cut.hard',)",
                "PRIMITIVES = {'transition.cut.hard': object()}",
            ]
        ),
        encoding="utf-8",
    )
