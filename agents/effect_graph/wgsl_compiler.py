"""WGSL execution plan compiler -- compiles EffectGraph into plan.json for the Rust dynamic pipeline."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from .compiler import ExecutionPlan, ExecutionStep, GraphCompiler
from .registry import ShaderRegistry
from .types import EffectGraph

log = logging.getLogger(__name__)

# Nodes that require compute dispatches instead of render passes.
# These are temporal nodes that run multi-step simulation each frame.
COMPUTE_NODES: set[str] = {
    "fluid_sim",
    "reaction_diffusion",
}

# Default steps per frame for compute nodes (can be overridden by params).
DEFAULT_STEPS_PER_FRAME: dict[str, int] = {
    "fluid_sim": 4,
    "reaction_diffusion": 8,
}

DEFAULT_OUTPUT_DIR = Path("/dev/shm/hapax-imagination/pipeline/")
DEFAULT_NODES_DIR = Path(__file__).resolve().parent.parent / "shaders" / "nodes"


def compile_to_wgsl_plan(graph: EffectGraph) -> dict[str, Any]:
    """Compile an EffectGraph into a WGSL execution plan dict.

    Uses GraphCompiler for topological ordering, then maps each ExecutionStep
    to a pass descriptor suitable for the Rust wgpu dynamic pipeline.

    Returns ``{"version": 1, "passes": [...]}``.
    """
    registry = ShaderRegistry(DEFAULT_NODES_DIR)
    compiler = GraphCompiler(registry)
    plan: ExecutionPlan = compiler.compile(graph)

    passes: list[dict[str, Any]] = []
    steps = [s for s in plan.steps if s.node_type != "output"]

    for i, step in enumerate(steps):
        is_last = i == len(steps) - 1
        pass_type = "compute" if step.node_type in COMPUTE_NODES else "render"

        # Collect input texture names from edges
        inputs: list[str] = []
        for edge in step.input_edges:
            if edge.is_layer_source:
                inputs.append(edge.source_node)  # e.g. "@live"
            else:
                # Find the index of the source node in steps to reference its output
                src_idx = _step_index(steps, edge.source_node)
                if src_idx is not None:
                    inputs.append(f"layer_{src_idx}")
                else:
                    inputs.append(edge.source_node)

        output = "final" if is_last else f"layer_{i}"

        # Get param ordering from WGSL Params struct (authoritative for buffer layout)
        from .wgsl_transpiler import extract_wgsl_param_names

        wgsl_path = DEFAULT_NODES_DIR / f"{step.node_type}.wgsl"
        if wgsl_path.exists():
            param_order = extract_wgsl_param_names(wgsl_path)
        else:
            node_def = registry.get(step.node_type)
            param_order = list(node_def.params.keys()) if node_def else []

        # Resolve enum/string params to float indices for the GPU uniform buffer.
        node_def = registry.get(step.node_type)
        uniforms: dict[str, float] = {}
        for key, value in step.params.items():
            if isinstance(value, (int, float)):
                uniforms[key] = float(value)
            elif isinstance(value, bool):
                uniforms[key] = 1.0 if value else 0.0
            elif isinstance(value, str) and node_def and key in node_def.params:
                enum_vals = node_def.params[key].enum_values or []
                uniforms[key] = float(enum_vals.index(value)) if value in enum_vals else 0.0
            # Skip non-numeric values without a known enum mapping

        # content_layer needs 4 content texture slot inputs for the compositing shader
        if step.node_type == "content_layer":
            inputs.extend(f"content_slot_{j}" for j in range(4))

        # Temporal nodes need their previous output as an accumulation input
        is_temporal = step.temporal
        if is_temporal:
            inputs.append(f"@accum_{step.node_id}")

        descriptor: dict[str, Any] = {
            "node_id": step.node_id,
            "shader": f"{step.node_type}.wgsl",
            "type": pass_type,
            "inputs": inputs,
            "output": output,
            "uniforms": uniforms,
            "param_order": param_order,
        }

        if is_temporal:
            descriptor["temporal"] = True

        if pass_type == "compute":
            descriptor["steps_per_frame"] = DEFAULT_STEPS_PER_FRAME.get(step.node_type, 1)

        passes.append(descriptor)

    return {"version": 1, "passes": passes}


def write_wgsl_pipeline(
    plan: dict[str, Any],
    output_dir: Path | None = None,
    nodes_dir: Path | None = None,
) -> Path:
    """Write plan.json and copy required .wgsl shader files to output_dir.

    Args:
        plan: The WGSL execution plan dict from ``compile_to_wgsl_plan``.
        output_dir: Target directory. Defaults to ``/dev/shm/hapax-imagination/pipeline/``.
        nodes_dir: Source directory for ``.wgsl`` files. Defaults to ``agents/shaders/nodes/``.

    Returns:
        Path to the written ``plan.json``.
    """
    if output_dir is None:
        output_dir = DEFAULT_OUTPUT_DIR
    if nodes_dir is None:
        nodes_dir = DEFAULT_NODES_DIR

    output_dir.mkdir(parents=True, exist_ok=True)

    plan_path = output_dir / "plan.json"
    plan_path.write_text(json.dumps(plan, indent=2))

    # Copy each required .wgsl file
    for p in plan.get("passes", []):
        shader_name = p.get("shader", "")
        src = nodes_dir / shader_name
        if src.is_file():
            shutil.copy2(src, output_dir / shader_name)
        else:
            log.warning("WGSL shader not found: %s", src)

    return plan_path


def _step_index(steps: list[ExecutionStep], node_id: str) -> int | None:
    """Find the index of a step by node_id."""
    for i, s in enumerate(steps):
        if s.node_id == node_id:
            return i
    return None
