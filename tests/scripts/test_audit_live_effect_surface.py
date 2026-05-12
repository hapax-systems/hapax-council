from __future__ import annotations

import json
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
    assert payload["summary"]["preset_family_count"] >= 5
    assert payload["summary"]["hero_effect_count"] == 8
    assert payload["summary"]["transition_primitive_count"] == 5
    assert "legacy_studio_fx" in payload["surfaces"]
    assert "reverie_imagination" in payload["surfaces"]
    assert "ward_fx" in payload["surfaces"]
    assert "layouts" in payload["surfaces"]
    assert "preset_family_selector" in payload["surfaces"]
    assert "noise_overlay" in payload["surfaces"]["presets"]["high_risk_node_usage"]
    assert "glitch_block" in payload["surfaces"]["presets"]["high_risk_node_usage"]
    assert not payload["surfaces"]["preset_family_selector"]["missing_presets"]
    assert "legacy_studio_fx_must_be_classified_live_dormant_or_retired" in payload["coverage_gaps"]


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
