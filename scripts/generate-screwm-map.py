#!/usr/bin/env python3
"""Generate a Quake .map file for the Screwm tower interior.

Sealed rectangular room with interior decoration. Uses only axis-aligned
box brushes to guarantee qbsp seals the map (no vis leaks).

Quake coordinate system: 1 meter = 32 units. Z is up in DarkPlaces.
Tower: radius 7.8m, height 15m.
"""

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

WALL_TEX = "city4_2"
FLOOR_TEX = "ground1_6"
CEIL_TEX = "sky4"
RAMP_TEX = "metal5_2"


def fmt_plane(p1, p2, p3, tex):
    return (
        f"( {p1[0]} {p1[1]} {p1[2]} ) "
        f"( {p2[0]} {p2[1]} {p2[2]} ) "
        f"( {p3[0]} {p3[1]} {p3[2]} ) "
        f"{tex} 0 0 0 1 1"
    )


def box_brush(x1, y1, z1, x2, y2, z2, tex=WALL_TEX):
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


def sealed_room():
    """6 axis-aligned slabs forming a sealed room. Guarantees vis works."""
    brushes = []
    brushes.append(box_brush(-EXT, -EXT, FLOOR_Z - WALL_THICK, EXT, EXT, FLOOR_Z, FLOOR_TEX))
    brushes.append(box_brush(-EXT, -EXT, CEIL_Z, EXT, EXT, CEIL_Z + WALL_THICK, CEIL_TEX))
    brushes.append(box_brush(-EXT, -EXT, FLOOR_Z, -EXT + WALL_THICK, EXT, CEIL_Z, WALL_TEX))
    brushes.append(box_brush(EXT - WALL_THICK, -EXT, FLOOR_Z, EXT, EXT, CEIL_Z, WALL_TEX))
    brushes.append(box_brush(-EXT, -EXT, FLOOR_Z, EXT, -EXT + WALL_THICK, CEIL_Z, WALL_TEX))
    brushes.append(box_brush(-EXT, EXT - WALL_THICK, FLOOR_Z, EXT, EXT, CEIL_Z, WALL_TEX))
    return [b for b in brushes if b]


def ramp_shelves():
    brushes = []
    ramp_w = 96
    ramp_d = 48
    for i in range(4):
        angle = i * (math.pi / 2) + math.pi / 8
        frac = (i + 1) / 5
        z = FLOOR_Z + int((CEIL_Z - FLOOR_Z) * frac)
        cx = int((TR * 0.7) * math.cos(angle))
        cy = int((TR * 0.7) * math.sin(angle))
        b = box_brush(cx - ramp_w, cy - ramp_d, z, cx + ramp_w, cy + ramp_d, z + 8, RAMP_TEX)
        if b:
            brushes.append(b)
    return brushes


def lights():
    entities = []
    colors = [
        (1.0, 0.71, 0.39),
        (0.39, 0.78, 1.0),
        (0.78, 0.39, 1.0),
        (0.39, 1.0, 0.59),
        (1.0, 0.39, 0.39),
    ]
    for i in range(5):
        frac = i / 4
        z = min(FLOOR_Z + int((CEIL_Z - FLOOR_Z) * frac) + 32, CEIL_Z - 16)
        angle = i * (2 * math.pi / 5)
        x = int(TR * 0.3 * math.cos(angle))
        y = int(TR * 0.3 * math.sin(angle))
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
        f'"origin" "0 0 {AOA_Z}"\n'
        '"light" "200"\n'
        '"_color" "1.0 0.78 0.59"\n'
        "}"
    )
    return entities


def generate_map():
    lines = []
    lines.append("// Screwm Tower — sealed room with interior decoration")
    lines.append("")

    worldspawn_brushes = sealed_room() + ramp_shelves()

    lines.append("{")
    lines.append('"classname" "worldspawn"')
    lines.append('"message" "The Screwm"')
    lines.append('"fog" "0.02 0.08 0.06 0.10"')
    for brush in worldspawn_brushes:
        lines.append(brush)
    lines.append("}")
    lines.append("")

    lines.append(
        f'{{\n"classname" "info_player_start"\n"origin" "0 0 {FLOOR_Z + 48}"\n"angle" "90"\n}}'
    )
    lines.append("")

    for light in lights():
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
        print(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(output_dir))
        if result.returncode != 0:
            print(f"  WARNING: {cmd[0]} returned {result.returncode}")
            if result.stderr:
                print(f"  {result.stderr[:300]}")
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
            print(f"BSP: {bsp_path} ({bsp_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
