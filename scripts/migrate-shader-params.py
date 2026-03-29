#!/usr/bin/env python3
"""Migrate GLSL-transpiled WGSL shaders to remove ghost system uniforms.

Ghost fields (u_time, u_width, u_height) in struct Params are relics of
GLSL-to-WGSL transpilation via naga. The Params buffer is only filled at
pipeline load time, so global.u_time always reads 0.0.

This script:
1. Removes ghost fields from struct Params
2. Replaces naga-pattern `let _eNN = global.u_time;` with direct shared uniform refs
3. Replaces direct `global.u_*` references with shared uniforms
4. Cleans up double-blank-lines left by removals
"""

import re
from pathlib import Path

SHADER_DIR = Path(__file__).resolve().parent.parent / "agents" / "shaders" / "nodes"

# Ghost uniforms and their shared-uniform replacements
GHOST_MAP = {
    "u_time": "uniforms.time",
    "u_width": "uniforms.resolution.x",
    "u_height": "uniforms.resolution.y",
}

GHOST_FIELD_RE = re.compile(r"^\s+u_(time|width|height)\s*:\s*f32\s*,?\s*$")


def migrate_shader(path: Path) -> bool:
    """Migrate a single .wgsl file. Returns True if modified."""
    text = path.read_text()
    original = text

    # --- Step 1: Remove ghost fields from struct Params ---
    lines = text.split("\n")
    new_lines: list[str] = []
    in_params = False
    params_fields: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("struct Params"):
            in_params = True
            new_lines.append(line)
            continue
        if in_params:
            if stripped == "}":
                in_params = False
                # If all fields were ghosts, add _pad
                if not params_fields:
                    new_lines.append("    _pad: f32,")
                new_lines.append(line)
                continue
            if GHOST_FIELD_RE.match(line):
                # Skip ghost field
                continue
            else:
                if stripped and not stripped.startswith("//"):
                    params_fields.append(stripped)
                new_lines.append(line)
                continue
        new_lines.append(line)

    text = "\n".join(new_lines)

    # --- Step 2: Handle naga _eNN pattern ---
    # Find all `let _eNN = global.u_time;` (and u_width, u_height)
    naga_pattern = re.compile(
        r"^\s*let\s+(_e\d+)\s*=\s*global\.(u_time|u_width|u_height)\s*;\s*$",
        re.MULTILINE,
    )

    replacements: dict[str, str] = {}  # _eNN -> replacement expression
    for m in naga_pattern.finditer(text):
        var_name = m.group(1)
        ghost_field = m.group(2)
        replacements[var_name] = GHOST_MAP[ghost_field]

    # Remove the `let _eNN = global.u_*;` lines
    text = naga_pattern.sub("", text)

    # Replace all occurrences of each _eNN variable with word-boundary matching
    for var_name, replacement in replacements.items():
        text = re.sub(rf"\b{re.escape(var_name)}\b", replacement, text)

    # --- Step 3: Handle any remaining direct references ---
    for ghost_field, replacement in GHOST_MAP.items():
        text = text.replace(f"global.{ghost_field}", replacement)

    # --- Step 4: Clean up double-blank-lines ---
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")

    if text != original:
        path.write_text(text)
        return True
    return False


def main() -> None:
    wgsl_files = sorted(SHADER_DIR.glob("*.wgsl"))
    migrated = 0
    for f in wgsl_files:
        if migrate_shader(f):
            print(f"  migrated: {f.name}")
            migrated += 1
        else:
            print(f"  unchanged: {f.name}")
    print(f"\n{migrated}/{len(wgsl_files)} shaders migrated.")


if __name__ == "__main__":
    main()
