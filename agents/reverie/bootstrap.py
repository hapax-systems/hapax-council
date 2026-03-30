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
from pathlib import Path

log = logging.getLogger(__name__)

PRESET_DIR = Path(__file__).resolve().parent.parent.parent / "presets"
VOCABULARY_PRESET = "reverie_vocabulary.json"
PIPELINE_DIR = Path("/dev/shm/hapax-imagination/pipeline")


def write_vocabulary_plan() -> bool:
    """Compile and write the permanent visual vocabulary to SHM.

    Returns True if successful, False otherwise.
    """
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
