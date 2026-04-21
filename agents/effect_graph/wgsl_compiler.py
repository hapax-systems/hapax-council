"""WGSL execution plan compiler -- compiles EffectGraph into plan.json for the Rust dynamic pipeline."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from .compiler import ExecutionPlan, ExecutionStep, GraphCompiler
from .registry import ShaderRegistry
from .types import EffectGraph

log = logging.getLogger(__name__)

# NOTE: No WGSL compute shaders exist yet — all nodes were transpiled from GLSL
# fragment shaders via naga. reaction_diffusion and fluid_sim are temporal render
# passes, not compute dispatches. When true compute shaders are added, list them here.
COMPUTE_NODES: set[str] = set()

# Default steps per frame for compute nodes (can be overridden by params).
DEFAULT_STEPS_PER_FRAME: dict[str, int] = {}

DEFAULT_OUTPUT_DIR = Path("/dev/shm/hapax-imagination/pipeline/")
DEFAULT_NODES_DIR = Path(__file__).resolve().parent.parent / "shaders" / "nodes"

# Path to shared uniforms prepended by DynamicPipeline before compiling each shader.
_UNIFORMS_WGSL = (
    Path(__file__).resolve().parents[2]
    / "hapax-logos"
    / "crates"
    / "hapax-visual"
    / "src"
    / "shaders"
    / "uniforms.wgsl"
)


def validate_wgsl(source: str) -> bool:
    """Validate WGSL source. Returns True if parseable.

    Uses naga-cli for validation if available, otherwise falls back
    to basic struct/function syntax checks.
    """
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wgsl", mode="w", delete=False) as f:
            f.write(source)
            f.flush()
            tmp_path = f.name
        result = subprocess.run(
            ["naga", tmp_path],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except FileNotFoundError:
        # naga-cli not installed — skip validation (can't validate without tooling)
        return True
    except Exception:
        return False
    finally:
        if tmp_path is not None:
            Path(tmp_path).unlink(missing_ok=True)


def compile_to_wgsl_plan(graph: EffectGraph) -> dict[str, object]:
    """Compile an EffectGraph into a WGSL execution plan dict.

    Uses GraphCompiler for topological ordering, then maps each
    ExecutionStep to a pass descriptor suitable for the Rust wgpu
    dynamic pipeline.

    Phase 5a (Compositor Unification Epic): emits the v2 plan format
    with one entry per render target. Single-output graphs default to
    a single target named ``"main"``, so the on-disk shape becomes
    ``{"version": 2, "targets": {"main": {"passes": [...]}}}``. The
    Rust ``DynamicPipeline`` parses both v1 and v2 — v1 plans are
    wrapped into a synthetic ``main`` target at parse time.
    """
    registry = ShaderRegistry(DEFAULT_NODES_DIR)
    compiler = GraphCompiler(registry)
    plan: ExecutionPlan = compiler.compile(graph)

    targets: dict[str, dict[str, object]] = {}
    for target_name, steps in plan.targets.items():
        passes = _build_passes_for_target(registry, steps)
        targets[target_name] = {"passes": passes}

    return {"version": 2, "targets": targets}


def _build_passes_for_target(
    registry: ShaderRegistry,
    target_steps: list[ExecutionStep],
) -> list[dict[str, object]]:
    """Translate one target's ExecutionStep list into pass descriptors.

    Pulled out of compile_to_wgsl_plan() so multi-target plans can
    reuse the same per-step logic. The output texture name is keyed
    on this target's local step index — each target gets its own
    independent ``layer_0``, ``layer_1``, ... namespace and ``final``
    output, so two targets sharing a predecessor produce two distinct
    sets of layer textures (Phase 5b will deduplicate).
    """
    from .wgsl_transpiler import extract_wgsl_param_names

    passes: list[dict[str, object]] = []
    steps = [s for s in target_steps if s.node_type != "output"]

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

        # Shader-intensity cap (Phase 1 of 2026-04-21 pixel-sort
        # dominance amendment). Clamp per-family max_strength on the
        # declared parameter names so preset authoring cannot push a
        # single shader past the substrate-vs-foreground threshold.
        # Bounds file: presets/shader_intensity_bounds.json.
        from shared.shader_bounds import clamp_params as _clamp_shader_params

        uniforms, _was_clamped = _clamp_shader_params(step.node_type, uniforms)

        # Content compositing nodes need 4 content texture slot inputs.
        # Opt-in via the requires_content_slots flag in the node manifest JSON
        # (declarative — no hardcoded node type tuple).
        requires_content_slots = bool(node_def and node_def.requires_content_slots)
        if requires_content_slots:
            inputs.extend(f"content_slot_{j}" for j in range(4))

        # Temporal nodes need their previous output as an accumulation input
        is_temporal = step.temporal
        if is_temporal:
            inputs.append(f"@accum_{step.node_id}")

        # Backend dispatcher key from the node manifest. Defaults to
        # "wgsl_render" so older manifests continue to compile correctly.
        backend = node_def.backend if node_def else "wgsl_render"

        descriptor: dict[str, object] = {
            "node_id": step.node_id,
            "shader": f"{step.node_type}.wgsl",
            "type": pass_type,
            "backend": backend,
            "inputs": inputs,
            "output": output,
            "uniforms": uniforms,
            "param_order": param_order,
        }

        if requires_content_slots:
            descriptor["requires_content_slots"] = True
            # Slot-family routing tag — Rust runtime filters
            # ``content_slot_*`` bindings by SHM-path prefix matching
            # this family. yt-content-reverie-sierpinski-separation
            # design 2026-04-21 §1A. Always emitted alongside
            # requires_content_slots so the Rust deserializer never
            # has to handle "needs slots, no family declared".
            descriptor["slot_family"] = node_def.slot_family if node_def else "narrative"

        if is_temporal:
            descriptor["temporal"] = True

        if pass_type == "compute":
            descriptor["steps_per_frame"] = DEFAULT_STEPS_PER_FRAME.get(step.node_type, 1)

        passes.append(descriptor)

    return passes


def write_wgsl_pipeline(
    plan: dict[str, object],
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

    # Load shared uniforms once — DynamicPipeline prepends these before compilation.
    uniforms_prefix = ""
    if _UNIFORMS_WGSL.is_file():
        uniforms_prefix = _UNIFORMS_WGSL.read_text()
    else:
        log.warning(
            "Shared uniforms not found at %s; skipping prefix in validation", _UNIFORMS_WGSL
        )

    # Walk every pass across every target, validating + copying its
    # shader exactly once. Multiple targets sharing the same .wgsl
    # file de-dup at the filesystem-copy level (the validation runs
    # for each pass since uniforms differ, but the file write is
    # idempotent).
    #
    # Phase 5a accepts both v1 (flat ``passes`` list) and v2 (``targets``
    # dict) inputs so legacy callers and tests don't have to change
    # all at once.
    targets_in: dict[str, dict[str, object]] = plan.get("targets", {})  # type: ignore[assignment]
    flat_passes_in: list[dict[str, object]] = plan.get("passes", [])  # type: ignore[assignment]
    if not targets_in and flat_passes_in:
        targets_in = {"main": {"passes": flat_passes_in}}

    validated_targets: dict[str, dict[str, object]] = {}
    seen_shaders: set[str] = set()
    for target_name, target_body in targets_in.items():
        passes_in: list[dict[str, object]] = target_body.get("passes", [])  # type: ignore[assignment]
        valid_passes: list[dict[str, object]] = []
        for p in passes_in:
            shader_name = str(p.get("shader", ""))
            src = nodes_dir / shader_name
            if not src.is_file():
                log.warning("WGSL shader not found: %s", src)
                continue

            shader_source = src.read_text()
            combined = uniforms_prefix + "\n" + shader_source if uniforms_prefix else shader_source
            if not validate_wgsl(combined):
                log.error(
                    "WGSL validation failed for %s — shader will not be deployed", shader_name
                )
                continue

            if shader_name not in seen_shaders:
                shutil.copy2(src, output_dir / shader_name)
                seen_shaders.add(shader_name)
            valid_passes.append(p)
        validated_targets[target_name] = {"passes": valid_passes}

    # Rewrite plan with only the validated passes per target.
    validated_plan: dict[str, object] = dict(plan)
    validated_plan["targets"] = validated_targets
    # Drop the legacy v1 ``passes`` field if it was present — the v2
    # ``targets`` map is now authoritative.
    validated_plan.pop("passes", None)
    if "version" not in validated_plan:
        validated_plan["version"] = 2
    plan_path = output_dir / "plan.json"
    plan_path.write_text(json.dumps(validated_plan, indent=2))

    return plan_path


def _step_index(steps: list[ExecutionStep], node_id: str) -> int | None:
    """Find the index of a step by node_id."""
    for i, s in enumerate(steps):
        if s.node_id == node_id:
            return i
    return None
