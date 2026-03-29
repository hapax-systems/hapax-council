#!/usr/bin/env python3
"""Write a clean plan.json to /dev/shm for the hapax-imagination binary.

Usage:
    uv run python scripts/write_test_plan.py [preset_name]
    uv run python scripts/write_test_plan.py ambient    # default
    uv run python scripts/write_test_plan.py ghost
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from agents.effect_graph.types import EffectGraph
from agents.effect_graph.wgsl_compiler import compile_to_wgsl_plan, write_wgsl_pipeline

PLAN_DIR = Path("/dev/shm/hapax-imagination/pipeline")


def main() -> None:
    preset_name = sys.argv[1] if len(sys.argv) > 1 else "ambient"
    preset_path = Path(f"presets/{preset_name}.json")
    if not preset_path.exists():
        print(f"Preset not found: {preset_path}")
        print(f"Available: {', '.join(p.stem for p in sorted(Path('presets').glob('*.json')))}")
        sys.exit(1)

    graph = EffectGraph.model_validate(json.loads(preset_path.read_text()))
    plan = compile_to_wgsl_plan(graph)

    # Write plan + copy shaders to pipeline dir
    write_wgsl_pipeline(plan, output_dir=PLAN_DIR, nodes_dir=Path("agents/shaders/nodes"))

    passes = len(plan.get("passes", []))
    has_content = any(p["node_id"] == "content_layer" for p in plan.get("passes", []))
    print(
        f"Wrote {preset_name} plan: {passes} passes, content_layer={'yes' if has_content else 'no'}"
    )
    print(f"Pipeline dir: {PLAN_DIR}")


if __name__ == "__main__":
    main()
