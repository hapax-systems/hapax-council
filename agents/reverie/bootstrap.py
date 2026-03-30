"""Reverie bootstrap — write the quiescent substrate pipeline on startup.

The substrate is Reverie's idle state, analogous to Daimonion's mutual silence.
A self-generated procedural noise field with gentle drift, breathing, and vignette.
No external input (@live). Content layer present but dormant (opacity 0).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

PRESET_DIR = Path(__file__).resolve().parent.parent.parent / "presets"
SUBSTRATE_PRESET = "reverie_substrate.json"
PIPELINE_DIR = Path("/dev/shm/hapax-imagination/pipeline")


def write_substrate_plan() -> bool:
    """Compile and write the quiescent substrate plan to SHM.

    Returns True if successful, False otherwise.
    """
    preset_path = PRESET_DIR / SUBSTRATE_PRESET
    if not preset_path.is_file():
        log.error("Substrate preset not found: %s", preset_path)
        return False

    try:
        from agents.effect_graph.types import EffectGraph
        from agents.effect_graph.wgsl_compiler import compile_to_wgsl_plan, write_wgsl_pipeline

        raw = json.loads(preset_path.read_text())
        graph = EffectGraph(**raw)
        plan = compile_to_wgsl_plan(graph)
        write_wgsl_pipeline(plan)
        log.info(
            "Reverie substrate: %d passes written to %s",
            len(plan.get("passes", [])),
            PIPELINE_DIR / "plan.json",
        )
        return True
    except Exception:
        log.exception("Failed to write substrate plan")
        return False
