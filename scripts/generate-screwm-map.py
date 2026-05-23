#!/usr/bin/env python3
"""Generate Quake .map files for the Screwm tower interior.

Sealed rectangular room with interior decoration. Uses only axis-aligned
box brushes to guarantee qbsp seals the map (no vis leaks).

Supports two working modes per hapax design language §2:
  --mode rnd       Gruvbox Hard Dark (warm brown, amber lights)
  --mode research  Solarized Dark (cool blue-grey, white lights)

Default generates both BSPs: screwm-rnd.bsp and screwm-research.bsp.
"""

import argparse
import math
import subprocess
import sys
from pathlib import Path

UNITS_PER_METER = 32
TOWER_RADIUS_M = 7.8
TOWER_FLOOR_M = -2.0
TOWER_CEIL_M = 13.0
WALL_THICK = 16
AOA_HEIGHT_M = 5.5

TR = int(TOWER_RADIUS_M * UNITS_PER_METER)
FLOOR_Z = int(TOWER_FLOOR_M * UNITS_PER_METER)
CEIL_Z = int(TOWER_CEIL_M * UNITS_PER_METER)
AOA_Z = int(AOA_HEIGHT_M * UNITS_PER_METER)
EXT = TR + WALL_THICK + 32

MODE_PRESETS = {
    "rnd": {
        "wall_tex": "city4_2",
        "floor_tex": "ground1_6",
        "ceil_tex": "sky4",
        "ramp_tex": "metal5_2",
        "fog": "0.02 0.11 0.08 0.06",
        "lights": [
            (1.0, 0.71, 0.39),
            (0.90, 0.65, 0.30),
            (0.78, 0.39, 0.60),
            (0.70, 0.85, 0.35),
            (1.0, 0.50, 0.25),
        ],
        "aoa_light": (1.0, 0.78, 0.50),
        "message": "The Screwm [R&D]",
    },
    "research": {
        "wall_tex": "city4_2",
        "floor_tex": "ground1_6",
        "ceil_tex": "sky4",
        "ramp_tex": "metal5_2",
        "fog": "0.02 0.04 0.08 0.12",
        "lights": [
            (0.40, 0.65, 0.80),
            (0.30, 0.55, 0.75),
            (0.50, 0.40, 0.70),
            (0.35, 0.70, 0.55),
            (0.60, 0.45, 0.45),
        ],
        "aoa_light": (0.50, 0.65, 0.80),
        "message": "The Screwm [Research]",
    },
}


def fmt_plane(p1, p2, p3, tex):
    return (
        f"( {p1[0]} {p1[1]} {p1[2]} ) "
        f"( {p2[0]} {p2[1]} {p2[2]} ) "
        f"( {p3[0]} {p3[1]} {p3[2]} ) "
        f"{tex} 0 0 0 1 1"
    )


def box_brush(x1, y1, z1, x2, y2, z2, tex):
    mn = [min(x1, x2), min(y1, y2), min(z1, z2)]
    mx = [max(x1, x2), max(y1, y2), max(z1, z2)]
    if mx[0] - mn[0] < 1 or mx[1] - mn[1] < 1 or mx[2] - mn[2] < 1:
        return None
    planes = [
        fmt_plane((mn[0], mn[1], mn[2]), (mn[0], mx[1], mn[2]), (mn[0], mn[1], mx[2]), tex),
        fmt_plane((mx[0], mn[1], mn[2]), (mx[0], mn[1], mx[2]), (mx[0], mx[1], mn[2]), tex),
        fmt_plane((mn[0], mn[1], mn[2]), (mn[0], mn[1], mx[2]), (mx[0], mn[1], mn[2]), tex),
        fmt_plane((mn[0], mx[1], mn[2]), (mx[0], mx[1], mn[2]), (mn[0], mx[1], mx[2]), tex),
        fmt_plane((mn[0], mn[1], mn[2]), (mx[0], mn[1], mn[2]), (mn[0], mx[1], mn[2]), tex),
        fmt_plane((mn[0], mn[1], mx[2]), (mn[0], mx[1], mx[2]), (mx[0], mn[1], mx[2]), tex),
    ]
    return "{\n" + "\n".join(planes) + "\n}"


def sealed_room(preset):
    brushes = []
    wt = preset["wall_tex"]
    ft = preset["floor_tex"]
    ct = preset["ceil_tex"]
    brushes.append(box_brush(-EXT, -EXT, FLOOR_Z - WALL_THICK, EXT, EXT, FLOOR_Z, ft))
    brushes.append(box_brush(-EXT, -EXT, CEIL_Z, EXT, EXT, CEIL_Z + WALL_THICK, ct))
    brushes.append(box_brush(-EXT, -EXT, FLOOR_Z, -EXT + WALL_THICK, EXT, CEIL_Z, wt))
    brushes.append(box_brush(EXT - WALL_THICK, -EXT, FLOOR_Z, EXT, EXT, CEIL_Z, wt))
    brushes.append(box_brush(-EXT, -EXT, FLOOR_Z, EXT, -EXT + WALL_THICK, CEIL_Z, wt))
    brushes.append(box_brush(-EXT, EXT - WALL_THICK, FLOOR_Z, EXT, EXT, CEIL_Z, wt))
    return [b for b in brushes if b]


def pillar_columns(preset):
    """8 pillars along walls at 45° intervals — Tower of Babel columns."""
    brushes = []
    wt = preset["wall_tex"]
    pillar_size = 24
    for i in range(8):
        angle = i * (math.pi / 4) + math.pi / 8
        px = int((TR - 32) * math.cos(angle))
        py = int((TR - 32) * math.sin(angle))
        b = box_brush(
            px - pillar_size,
            py - pillar_size,
            FLOOR_Z,
            px + pillar_size,
            py + pillar_size,
            CEIL_Z,
            wt,
        )
        if b:
            brushes.append(b)
    return brushes


def level_ledges(preset):
    """Stepped ledges at each level boundary — architectural strata."""
    brushes = []
    rt = preset["ramp_tex"]
    ledge_depth = 32
    ledge_height = 12

    for level in range(5):
        frac = level / 4
        z = FLOOR_Z + int((CEIL_Z - FLOOR_Z) * frac)
        # Ledge on each wall (4 walls = 4 ledges per level)
        for wall in range(4):
            if wall == 0:
                b = box_brush(
                    -EXT + WALL_THICK,
                    -EXT + WALL_THICK,
                    z,
                    EXT - WALL_THICK,
                    -EXT + WALL_THICK + ledge_depth,
                    z + ledge_height,
                    rt,
                )
            elif wall == 1:
                b = box_brush(
                    EXT - WALL_THICK - ledge_depth,
                    -EXT + WALL_THICK,
                    z,
                    EXT - WALL_THICK,
                    EXT - WALL_THICK,
                    z + ledge_height,
                    rt,
                )
            elif wall == 2:
                b = box_brush(
                    -EXT + WALL_THICK,
                    EXT - WALL_THICK - ledge_depth,
                    z,
                    EXT - WALL_THICK,
                    EXT - WALL_THICK,
                    z + ledge_height,
                    rt,
                )
            else:
                b = box_brush(
                    -EXT + WALL_THICK,
                    -EXT + WALL_THICK,
                    z,
                    -EXT + WALL_THICK + ledge_depth,
                    EXT - WALL_THICK,
                    z + ledge_height,
                    rt,
                )
            if b:
                brushes.append(b)
    return brushes


def central_pedestal(preset):
    """Low pedestal at tower center for AoA to float above."""
    rt = preset["ramp_tex"]
    pedestal_size = 48
    pedestal_height = 16
    b = box_brush(
        -pedestal_size,
        -pedestal_size,
        FLOOR_Z,
        pedestal_size,
        pedestal_size,
        FLOOR_Z + pedestal_height,
        rt,
    )
    return [b] if b else []


def ramp_shelves(preset):
    brushes = []
    ramp_w = 96
    ramp_d = 48
    rt = preset["ramp_tex"]
    for i in range(4):
        angle = i * (math.pi / 2) + math.pi / 8
        frac = (i + 1) / 5
        z = FLOOR_Z + int((CEIL_Z - FLOOR_Z) * frac)
        cx = int((TR * 0.7) * math.cos(angle))
        cy = int((TR * 0.7) * math.sin(angle))
        b = box_brush(cx - ramp_w, cy - ramp_d, z, cx + ramp_w, cy + ramp_d, z + 8, rt)
        if b:
            brushes.append(b)
    return brushes


def lights(preset):
    entities = []
    # Central lights at each level (near AoA axis)
    for i in range(5):
        frac = i / 4
        z = min(FLOOR_Z + int((CEIL_Z - FLOOR_Z) * frac) + 32, CEIL_Z - 16)
        angle = i * (2 * math.pi / 5)
        x = int(TR * 0.3 * math.cos(angle))
        y = int(TR * 0.3 * math.sin(angle))
        r, g, b = preset["lights"][i]
        entities.append(
            "{\n"
            f'"classname" "light"\n'
            f'"origin" "{x} {y} {z}"\n'
            f'"light" "300"\n'
            f'"_color" "{r} {g} {b}"\n'
            "}"
        )

    # Wall-mounted lights at each pillar (8 pillars × 3 vertical positions)
    for pillar in range(8):
        angle = pillar * (math.pi / 4) + math.pi / 8
        px = int((TR - 48) * math.cos(angle))
        py = int((TR - 48) * math.sin(angle))
        for level in range(3):
            frac = (level + 1) / 4
            z = FLOOR_Z + int((CEIL_Z - FLOOR_Z) * frac)
            light_idx = min(level + 1, 4)
            r, g, b = preset["lights"][light_idx]
            entities.append(
                "{\n"
                f'"classname" "light"\n'
                f'"origin" "{px} {py} {z}"\n'
                f'"light" "150"\n'
                f'"_color" "{r} {g} {b}"\n'
                "}"
            )

    # AoA center light (brighter, warm)
    ar, ag, ab = preset["aoa_light"]
    entities.append(
        "{\n"
        '"classname" "light"\n'
        f'"origin" "0 0 {AOA_Z}"\n'
        '"light" "350"\n'
        f'"_color" "{ar} {ag} {ab}"\n'
        "}"
    )
    return entities


def generate_map(preset):
    lines = []
    lines.append(f"// Screwm Tower — {preset['message']}")
    lines.append("")

    worldspawn_brushes = (
        sealed_room(preset)
        + pillar_columns(preset)
        + level_ledges(preset)
        + central_pedestal(preset)
        + ramp_shelves(preset)
    )

    lines.append("{")
    lines.append('"classname" "worldspawn"')
    lines.append(f'"message" "{preset["message"]}"')
    lines.append(f'"fog" "{preset["fog"]}"')
    for brush in worldspawn_brushes:
        lines.append(brush)
    lines.append("}")
    lines.append("")

    lines.append(
        f'{{\n"classname" "info_player_start"\n"origin" "0 0 {FLOOR_Z + 48}"\n"angle" "90"\n}}'
    )
    lines.append("")

    for light in lights(preset):
        lines.append(light)
        lines.append("")

    return "\n".join(lines)


def compile_map(map_path: Path, output_dir: Path):
    bsp_name = map_path.stem
    cmds = [
        ["qbsp", str(map_path)],
        ["light", "-extra", "-lit", str(output_dir / f"{bsp_name}.bsp")],
        ["vis", str(output_dir / f"{bsp_name}.bsp")],
    ]
    for cmd in cmds:
        print(f"  {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(output_dir))
        if result.returncode != 0:
            print(f"    WARNING: {cmd[0]} returned {result.returncode}")
        else:
            print(f"    OK")


def main():
    parser = argparse.ArgumentParser(description="Generate Screwm tower BSP maps")
    parser.add_argument("--mode", choices=["rnd", "research", "both"], default="both")
    parser.add_argument("--compile", action="store_true")
    args = parser.parse_args()

    output_dir = Path(__file__).parent.parent / "assets" / "quake" / "maps"
    output_dir.mkdir(parents=True, exist_ok=True)

    modes = ["rnd", "research"] if args.mode == "both" else [args.mode]

    for mode in modes:
        preset = MODE_PRESETS[mode]
        map_content = generate_map(preset)
        map_name = f"screwm-{mode}"
        map_path = output_dir / f"{map_name}.map"
        map_path.write_text(map_content)
        print(f"Generated {map_path} ({len(map_content)} bytes)")

        if args.compile:
            compile_map(map_path, output_dir)
            bsp_path = output_dir / f"{map_name}.bsp"
            if bsp_path.exists():
                print(f"  BSP: {bsp_path} ({bsp_path.stat().st_size} bytes)")

    # Also generate the default screwm.map (rnd mode) for backward compat
    if args.mode == "both":
        default_content = generate_map(MODE_PRESETS["rnd"])
        default_path = output_dir / "screwm.map"
        default_path.write_text(default_content)
        if args.compile:
            compile_map(default_path, output_dir)


if __name__ == "__main__":
    main()
