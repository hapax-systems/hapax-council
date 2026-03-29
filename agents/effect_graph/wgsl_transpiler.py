"""GLSL ES 1.0 → WGSL transpiler via naga CLI.

GStreamer glshader nodes use GLSL ES 1.0 (fragment shaders). Naga's GLSL frontend
requires GLSL 4.50 desktop. This module adapts ES 1.0 → GLSL 450, then invokes
naga to produce WGSL for the wgpu pipeline.

Key transformations:
  - #version 100 → #version 450
  - Remove #ifdef GL_ES / precision / #endif blocks
  - varying → layout(location=N) in
  - uniform sampler2D → split texture2D + sampler (naga requirement)
  - scalar/vector uniforms → UBO struct
  - texture2D() → texture(sampler2D(...))
  - gl_FragColor → layout(location=0) out vec4 fragColor
"""

from __future__ import annotations

import logging
import re
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def adapt_glsl(source: str) -> str:
    """Adapt GLSL ES 1.0 fragment shader source to GLSL 4.50 for naga.

    Performs regex-based multi-pass rewriting:
      Pass 1: Collect sampler2D uniform names and scalar/vector uniform declarations.
      Pass 2: Rewrite source with all substitutions.
    """
    lines = source.split("\n")

    # --- Pass 1: collect uniforms ---
    sampler_names: list[str] = []
    scalar_uniforms: list[tuple[str, str]] = []  # (type, name)

    for line in lines:
        stripped = line.strip()
        # Match: uniform sampler2D <name>;
        m = re.match(r"uniform\s+sampler2D\s+(\w+)\s*;", stripped)
        if m:
            sampler_names.append(m.group(1))
            continue
        # Match: uniform <type> <name>; with optional trailing comment
        m = re.match(r"uniform\s+(float|int|vec[234]|ivec[234]|mat[234])\s+(\w+)\s*;", stripped)
        if m:
            scalar_uniforms.append((m.group(1), m.group(2)))

    # --- Pass 2: rewrite ---
    out_lines: list[str] = []
    in_gl_es_block = False
    version_emitted = False

    for line in lines:
        stripped = line.strip()

        # Replace #version 100
        if stripped.startswith("#version"):
            if not version_emitted:
                out_lines.append("#version 450")
                out_lines.append("layout(location=0) out vec4 fragColor;")
                version_emitted = True
            continue

        # Remove #ifdef GL_ES ... #endif block
        if stripped == "#ifdef GL_ES":
            in_gl_es_block = True
            continue
        if in_gl_es_block:
            if stripped == "#endif":
                in_gl_es_block = False
            continue

        # Remove standalone precision declarations
        if re.match(r"precision\s+(lowp|mediump|highp)\s+\w+\s*;", stripped):
            continue

        # varying → layout in
        m = re.match(r"varying\s+(vec[234]|float|int)\s+(\w+)\s*;", stripped)
        if m:
            out_lines.append(f"layout(location=0) in {m.group(1)} {m.group(2)};")
            continue

        # Remove original uniform sampler2D lines (will emit split versions)
        if re.match(r"uniform\s+sampler2D\s+\w+\s*;", stripped):
            continue

        # Remove original scalar uniform lines (will emit UBO)
        if re.match(r"uniform\s+(float|int|vec[234]|ivec[234]|mat[234])\s+\w+\s*;", stripped):
            continue

        # Replace gl_FragColor with fragColor
        line = line.replace("gl_FragColor", "fragColor")

        out_lines.append(line)

    # --- Insert declarations after layout in line ---
    # Find insertion point: after the last layout(location=...) in line, before first function/void
    insert_idx = 0
    for i, l in enumerate(out_lines):
        if "layout(location=" in l:
            insert_idx = i + 1

    declarations: list[str] = []

    # Emit split texture + sampler for each sampler2D
    binding = 0
    for name in sampler_names:
        declarations.append(f"layout(set=0, binding={binding}) uniform texture2D {name};")
        declarations.append(f"layout(set=0, binding={binding + 1}) uniform sampler {name}_sampler;")
        binding += 2

    # Emit UBO for scalar uniforms
    if scalar_uniforms:
        declarations.append("layout(set=1, binding=0) uniform Params {")
        for utype, uname in scalar_uniforms:
            declarations.append(f"    {utype} {uname};")
        declarations.append("};")

    if declarations:
        out_lines = out_lines[:insert_idx] + declarations + out_lines[insert_idx:]

    result = "\n".join(out_lines)

    # --- Pass 3: rewrite texture2D calls ---
    # texture2D(name, uv) → texture(sampler2D(name, name_sampler), uv)
    for name in sampler_names:
        # Handle texture2D(name, <expr>) where expr can be complex
        # Use a function to handle nested parens
        result = _rewrite_texture2d_calls(result, name)

    return result


def _rewrite_texture2d_calls(source: str, sampler_name: str) -> str:
    """Replace texture2D(sampler_name, ...) with texture(sampler2D(sampler_name, sampler_name_sampler), ...)."""
    pattern = f"texture2D\\(\\s*{re.escape(sampler_name)}\\s*,"
    replacement = f"texture(sampler2D({sampler_name}, {sampler_name}_sampler),"
    return re.sub(pattern, replacement, source)


def transpile_glsl_to_wgsl(glsl_source: str) -> str:
    """Adapt GLSL ES 1.0 source to GLSL 450 and transpile to WGSL via naga CLI.

    Returns the WGSL source string.
    Raises RuntimeError if naga fails.
    """
    adapted = adapt_glsl(glsl_source)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".glsl", delete=False) as glsl_f:
        glsl_f.write(adapted)
        glsl_path = Path(glsl_f.name)

    wgsl_path = glsl_path.with_suffix(".wgsl")

    try:
        result = subprocess.run(
            [
                "naga",
                "--input-kind",
                "glsl",
                "--shader-stage",
                "fragment",
                str(glsl_path),
                str(wgsl_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"naga failed (exit {result.returncode}):\n{result.stderr}\n"
                f"--- adapted GLSL ---\n{adapted}"
            )
        return wgsl_path.read_text()
    finally:
        glsl_path.unlink(missing_ok=True)
        wgsl_path.unlink(missing_ok=True)


def transpile_node(frag_path: Path, output_dir: Path) -> Path:
    """Transpile a single .frag file to .wgsl.

    Returns the path to the output .wgsl file.
    """
    glsl_source = frag_path.read_text()
    wgsl_source = transpile_glsl_to_wgsl(glsl_source)
    output_path = output_dir / frag_path.with_suffix(".wgsl").name
    output_path.write_text(wgsl_source)
    return output_path


def transpile_all_nodes(nodes_dir: Path, output_dir: Path | None = None) -> dict:
    """Batch-transpile all .frag files in a directory to .wgsl.

    Args:
        nodes_dir: Directory containing .frag files.
        output_dir: Where to write .wgsl files. Defaults to nodes_dir.

    Returns:
        Dict with keys: total, success, failed, failures (list of {file, error}).
    """
    if output_dir is None:
        output_dir = nodes_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    frag_files = sorted(nodes_dir.glob("*.frag"))
    results: dict = {
        "total": len(frag_files),
        "success": 0,
        "failed": 0,
        "failures": [],
    }

    for frag in frag_files:
        try:
            transpile_node(frag, output_dir)
            results["success"] += 1
            logger.info("OK: %s", frag.name)
        except Exception as e:
            results["failed"] += 1
            results["failures"].append({"file": frag.name, "error": str(e)})
            logger.warning("FAILED: %s — %s", frag.name, e)

    return results
