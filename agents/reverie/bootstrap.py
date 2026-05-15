"""Reverie bootstrap — write the permanent visual vocabulary on startup.

The vocabulary graph defines which shaders Reverie runs — always the same
structure (noise_gen → colorgrade → drift → breathing → content_layer →
postprocess). There is no idle state. Parameters are driven by imagination
fragments through the uniform pipeline. The graph structure never changes;
only the uniforms change.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

log = logging.getLogger(__name__)

PRESET_DIR = Path(__file__).resolve().parent.parent.parent / "presets"
VOCABULARY_PRESET = "reverie_vocabulary.json"
PIPELINE_DIR = Path("/dev/shm/hapax-imagination/pipeline")
NODES_DIR = Path(__file__).resolve().parent.parent / "shaders" / "nodes"


def load_vocabulary() -> dict:
    """Load the vocabulary preset as a raw dict (for mixer to clone and mutate)."""
    preset_path = PRESET_DIR / VOCABULARY_PRESET
    return json.loads(preset_path.read_text())


def write_vocabulary_plan() -> bool:
    """Compile and write the permanent visual vocabulary to SHM.

    Returns True if successful, False otherwise.
    In 3D compositor mode (HAPAX_3D_COMPOSITOR=1), writes a @live-based
    plan instead of the noise-generator vocabulary so the wgpu scene
    renderer output flows through the shader chain.
    """
    import os
    if os.environ.get("HAPAX_3D_COMPOSITOR") == "1":
        return _write_3d_vocabulary_plan()

    preset_path = PRESET_DIR / VOCABULARY_PRESET
    if not preset_path.is_file():
        log.error("Vocabulary preset not found: %s", preset_path)
        return False

    try:
        from agents.effect_graph.types import EffectGraph
        from agents.effect_graph.wgsl_compiler import compile_to_wgsl_plan, write_wgsl_pipeline

        raw = json.loads(preset_path.read_text())
        graph = EffectGraph(**raw)
        plan = compile_to_wgsl_plan(graph)
        write_wgsl_pipeline(plan)
        log.info(
            "Reverie vocabulary: %d passes written to %s",
            len(plan.get("passes", [])),
            PIPELINE_DIR / "plan.json",
        )
        return True
    except Exception:
        log.exception("Failed to write vocabulary plan")
        return False


def _write_3d_vocabulary_plan() -> bool:
    """Write a @live-based shader plan for 3D compositor mode.

    Instead of noise_gen → procedural chain, uses the 3D scene output
    (@live) as the primary input and applies lightweight color grading,
    drift, and post-processing effects.
    """
    import os
    plan = {
        "version": 2,
        "targets": {
            "main": {
                "passes": [
                    {
                        "node_id": "color",
                        "shader": "colorgrade.wgsl",
                        "type": "render",
                        "backend": "wgsl_render",
                        "inputs": ["@live"],
                        "output": "layer_0",
                        "uniforms": {
                            "saturation": 1.1,
                            "brightness": 1.05,
                            "contrast": 1.0,
                            "sepia": 0.0,
                            "hue_rotate": 0.0,
                            "displacement": 0.0,
                            "chromatic_aberration": 0.002,
                            "slice_amplitude": 0.0,
                        },
                        "param_order": [
                            "saturation", "brightness", "contrast",
                            "sepia", "hue_rotate",
                        ],
                    },
                    {
                        "node_id": "drift",
                        "shader": "drift.wgsl",
                        "type": "render",
                        "backend": "wgsl_render",
                        "inputs": ["layer_0"],
                        "output": "layer_1",
                        "uniforms": {
                            "speed": 0.02,
                            "amplitude": 0.003,
                            "frequency": 0.8,
                            "coherence": 0.9,
                            "time": 0.0,
                            "width": float(os.environ.get("HAPAX_IMAGINATION_WIDTH", "1280")),
                            "height": float(os.environ.get("HAPAX_IMAGINATION_HEIGHT", "720")),
                        },
                        "param_order": [
                            "speed", "amplitude", "frequency", "coherence",
                        ],
                    },
                    {
                        "node_id": "fb",
                        "shader": "feedback.wgsl",
                        "type": "render",
                        "backend": "wgsl_render",
                        "inputs": ["layer_1", "@accum_fb"],
                        "output": "layer_2",
                        "uniforms": {
                            "decay": 0.15,
                            "zoom": 1.0,
                            "rotate": 0.0,
                            "blend_mode": 1.0,
                            "hue_shift": 0.0,
                            "trace_center_x": 0.5,
                            "trace_center_y": 0.5,
                            "trace_radius": 0.0,
                            "trace_strength": 0.0,
                        },
                        "param_order": [
                            "decay", "zoom", "rotate", "blend_mode", "hue_shift",
                            "trace_center_x", "trace_center_y",
                            "trace_radius", "trace_strength",
                        ],
                        "temporal": True,
                    },
                    {
                        "node_id": "post",
                        "shader": "postprocess.wgsl",
                        "type": "render",
                        "backend": "wgsl_render",
                        "inputs": ["layer_2"],
                        "output": "final",
                        "uniforms": {
                            "vignette_strength": 0.15,
                            "sediment_strength": 0.02,
                            "master_opacity": 1.0,
                            "anonymize": 0.0,
                        },
                        "param_order": [
                            "vignette_strength", "sediment_strength", "master_opacity",
                        ],
                    },
                ],
            },
        },
    }
    PIPELINE_DIR.mkdir(parents=True, exist_ok=True)
    for shader_path in NODES_DIR.glob("*.wgsl"):
        shutil.copy2(shader_path, PIPELINE_DIR / shader_path.name)
    plan_path = PIPELINE_DIR / "plan.json"
    plan_path.write_text(json.dumps(plan, indent=2))
    log.info("3D vocabulary: 4 passes (@live-based) written to %s", plan_path)
    return True
