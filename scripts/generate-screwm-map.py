#!/usr/bin/env python3
"""Generate a Quake .map file for the Screwm tower interior.

Octagonal tower with spiral ramp shelves, central void for AoA,
colored lighting, and fog. Outputs standard Quake .map format
compatible with ericw-tools (qbsp/light/vis).

Quake coordinate system: 1 meter = 32 units.
Tower dimensions match scene.rs: radius 7.8m, height 15m (y=-2 to y=13).
"""

import math
import subprocess
import sys
from pathlib import Path

UNITS_PER_METER = 32
TOWER_RADIUS_M = 7.8
TOWER_FLOOR_M = -2.0
TOWER_CEIL_M = 13.0
WALL_THICKNESS_M = 0.5
NUM_SIDES = 8
RAMP_COUNT = 4
RAMP_WIDTH_M = 3.0
RAMP_DEPTH_M = 1.5
AOA_HEIGHT_M = 5.5

TR = int(TOWER_RADIUS_M * UNITS_PER_METER)
TF = int(TOWER_FLOOR_M * UNITS_PER_METER)
TC = int(TOWER_CEIL_M * UNITS_PER_METER)
WT = int(WALL_THICKNESS_M * UNITS_PER_METER)
RW = int(RAMP_WIDTH_M * UNITS_PER_METER)
RD = int(RAMP_DEPTH_M * UNITS_PER_METER)
AOA_Y = int(AOA_HEIGHT_M * UNITS_PER_METER)

WALL_TEX = "city4_2"
FLOOR_TEX = "ground1_6"
CEIL_TEX = "sky4"
RAMP_TEX = "metal5_2"
TRIM_TEX = "wbrick1_5"


def fmt_plane(p1, p2, p3, tex, x_off=0, y_off=0, rot=0, x_scale=1, y_scale=1):
    return (
        f"( {p1[0]} {p1[1]} {p1[2]} ) "
        f"( {p2[0]} {p2[1]} {p2[2]} ) "
        f"( {p3[0]} {p3[1]} {p3[2]} ) "
        f"{tex} {x_off} {y_off} {rot} {x_scale} {y_scale}"
    )


def box_brush(x1, y1, z1, x2, y2, z2, tex=WALL_TEX):
    mn = [min(x1, x2), min(y1, y2), min(z1, z2)]
    mx = [max(x1, x2), max(y1, y2), max(z1, z2)]
    planes = [
        fmt_plane((mn[0], mn[1], mn[2]), (mn[0], mn[1], mx[2]), (mn[0], mx[1], mn[2]), tex),
        fmt_plane((mx[0], mn[1], mn[2]), (mx[0], mx[1], mn[2]), (mx[0], mn[1], mx[2]), tex),
        fmt_plane((mn[0], mn[1], mn[2]), (mx[0], mn[1], mn[2]), (mn[0], mn[1], mx[2]), tex),
        fmt_plane((mn[0], mx[1], mn[2]), (mn[0], mx[1], mx[2]), (mx[0], mx[1], mn[2]), tex),
        fmt_plane((mn[0], mn[1], mn[2]), (mn[0], mx[1], mn[2]), (mx[0], mn[1], mn[2]), tex),
        fmt_plane((mn[0], mn[1], mx[2]), (mx[0], mn[1], mx[2]), (mn[0], mx[1], mx[2]), tex),
    ]
    return "{\n" + "\n".join(planes) + "\n}"


def wedge_brush(inner_pts, outer_pts, y_bot, y_top, tex=WALL_TEX):
    """Create a brush from 4 XZ points (inner pair, outer pair) extruded vertically."""
    i0, i1 = inner_pts
    o0, o1 = outer_pts
    planes = []
    planes.append(
        fmt_plane((i0[0], y_bot, i0[1]), (i0[0], y_top, i0[1]), (i1[0], y_bot, i1[1]), tex)
    )
    planes.append(
        fmt_plane((o0[0], y_bot, o0[1]), (o1[0], y_bot, o1[1]), (o0[0], y_top, o0[1]), tex)
    )
    planes.append(
        fmt_plane((i0[0], y_bot, i0[1]), (o0[0], y_bot, o0[1]), (i0[0], y_top, i0[1]), tex)
    )
    planes.append(
        fmt_plane((i1[0], y_bot, i1[1]), (i1[0], y_top, i1[1]), (o1[0], y_bot, o1[1]), tex)
    )
    planes.append(
        fmt_plane((i0[0], y_bot, i0[1]), (i1[0], y_bot, i1[1]), (o0[0], y_bot, o0[1]), tex)
    )
    planes.append(
        fmt_plane((i0[0], y_top, i0[1]), (o0[0], y_top, o0[1]), (i1[0], y_top, i1[1]), tex)
    )
    return "{\n" + "\n".join(planes) + "\n}"


def generate_wall_panels():
    brushes = []
    for i in range(NUM_SIDES):
        angle_start = i * (2 * math.pi / NUM_SIDES)
        angle_end = (i + 1) * (2 * math.pi / NUM_SIDES)

        ix0 = int(TR * math.cos(angle_start))
        iz0 = int(TR * math.sin(angle_start))
        ix1 = int(TR * math.cos(angle_end))
        iz1 = int(TR * math.sin(angle_end))

        ox0 = int((TR + WT) * math.cos(angle_start))
        oz0 = int((TR + WT) * math.sin(angle_start))
        ox1 = int((TR + WT) * math.cos(angle_end))
        oz1 = int((TR + WT) * math.sin(angle_end))

        inner = [(ix0, iz0), (ix1, iz1)]
        outer = [(ox0, oz0), (ox1, oz1)]
        brushes.append(wedge_brush(inner, outer, TF, TC, WALL_TEX))
    return brushes


def generate_floor():
    ext = TR + WT + 32
    return box_brush(-ext, TF - WT, -ext, ext, TF, ext, FLOOR_TEX)


def generate_ceiling():
    ext = TR + WT + 32
    return box_brush(-ext, TC, -ext, ext, TC + WT, ext, CEIL_TEX)


def generate_ramps():
    brushes = []
    for i in range(RAMP_COUNT):
        angle = i * (2 * math.pi / RAMP_COUNT) + math.pi / 8
        level_frac = (i + 1) / (RAMP_COUNT + 1)
        y = TF + int((TC - TF) * level_frac)

        cx = int((TR - RD / 2) * math.cos(angle))
        cz = int((TR - RD / 2) * math.sin(angle))

        perp_x = int(RW / 2 * math.cos(angle + math.pi / 2))
        perp_z = int(RW / 2 * math.sin(angle + math.pi / 2))

        rad_x = int(RD / 2 * math.cos(angle))
        rad_z = int(RD / 2 * math.sin(angle))

        x1 = cx - perp_x - rad_x
        z1 = cz - perp_z - rad_z
        x2 = cx + perp_x + rad_x
        z2 = cz + perp_z + rad_z

        mn_x, mx_x = min(x1, x2), max(x1, x2)
        mn_z, mx_z = min(z1, z2), max(z1, z2)

        brushes.append(box_brush(mn_x, y, mn_z, mx_x, y + 8, mx_z, RAMP_TEX))
    return brushes


def generate_lights():
    entities = []
    colors = [
        (255, 180, 100),
        (100, 200, 255),
        (200, 100, 255),
        (100, 255, 150),
        (255, 100, 100),
    ]
    for i in range(5):
        frac = i / 4
        y = TF + int((TC - TF) * frac) + 32
        angle = i * (2 * math.pi / 5)
        x = int(TR * 0.4 * math.cos(angle))
        z = int(TR * 0.4 * math.sin(angle))
        r, g, b = colors[i]
        entities.append(
            "{\n"
            f'"classname" "light"\n'
            f'"origin" "{x} {y} {z}"\n'
            f'"light" "300"\n'
            f'"_color" "{r} {g} {b}"\n'
            "}"
        )
    entities.append(
        "{\n"
        '"classname" "light"\n'
        f'"origin" "0 {AOA_Y} 0"\n'
        '"light" "200"\n'
        '"_color" "255 200 150"\n'
        "}"
    )
    return entities


def generate_aoa_entity():
    return (
        "{\n"
        '"classname" "misc_model"\n'
        f'"origin" "0 {AOA_Y} 0"\n'
        '"model" "progs/aoa.mdl"\n'
        '"angles" "0 0 0"\n'
        "}"
    )


def generate_fog_entity():
    return '{\n"classname" "worldspawn"\n"fog" "0.015 0.08 0.06 0.12"\n"message" "The Screwm"\n}'


def generate_info_player():
    return f'{{\n"classname" "info_player_start"\n"origin" "0 {TF + 64} 0"\n"angle" "90"\n}}'


def generate_map():
    lines = []

    lines.append("// Screwm Tower — procedurally generated")
    lines.append("// DarkPlaces compatible, Quake .map format")
    lines.append("")

    worldspawn_brushes = []
    worldspawn_brushes.append(generate_floor())
    worldspawn_brushes.append(generate_ceiling())
    worldspawn_brushes.extend(generate_wall_panels())
    worldspawn_brushes.extend(generate_ramps())

    lines.append("{")
    lines.append('"classname" "worldspawn"')
    lines.append('"message" "The Screwm"')
    lines.append('"fog" "0.015 0.08 0.06 0.12"')
    lines.append('"wad" "screwm.wad"')
    for brush in worldspawn_brushes:
        lines.append(brush)
    lines.append("}")
    lines.append("")

    lines.append(generate_info_player())
    lines.append("")

    for light in generate_lights():
        lines.append(light)
        lines.append("")

    lines.append(generate_aoa_entity())

    return "\n".join(lines)


def compile_map(map_path: Path, output_dir: Path):
    bsp_name = map_path.stem
    cmds = [
        ["qbsp", str(map_path)],
        ["light", "-extra", "-lit", str(output_dir / f"{bsp_name}.bsp")],
        ["vis", str(output_dir / f"{bsp_name}.bsp")],
    ]
    for cmd in cmds:
        print(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(output_dir))
        if result.returncode != 0:
            print(f"Warning: {cmd[0]} returned {result.returncode}")
            print(result.stderr[:500])
        else:
            print(f"  OK")


def main():
    output_dir = Path(__file__).parent.parent / "assets" / "quake" / "maps"
    output_dir.mkdir(parents=True, exist_ok=True)

    map_content = generate_map()
    map_path = output_dir / "screwm.map"
    map_path.write_text(map_content)
    print(f"Generated {map_path} ({len(map_content)} bytes)")

    if "--compile" in sys.argv:
        compile_map(map_path, output_dir)
        bsp_path = output_dir / "screwm.bsp"
        if bsp_path.exists():
            print(f"BSP compiled: {bsp_path} ({bsp_path.stat().st_size} bytes)")
        else:
            print("BSP compilation failed — check qbsp/light/vis output above")


if __name__ == "__main__":
    main()
