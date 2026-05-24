#!/usr/bin/env python3
"""Generate Quake .map files for the Screwm migration scene.

Sealed BSP substrate with Screwm/AoA composition anchors. Uses only
axis-aligned box brushes to guarantee qbsp seals the map (no vis leaks).

Supports two working modes per hapax design language §2:
  --mode rnd       Gruvbox Hard Dark (warm brown, amber lights)
  --mode research  Solarized Dark (cool blue-grey, white lights)

Default generates both BSPs: screwm-rnd.bsp and screwm-research.bsp.
"""

import argparse
import math
import subprocess
from pathlib import Path

UNITS_PER_METER = 32
TOWER_RADIUS_M = 7.8
TOWER_FLOOR_M = -2.0
TOWER_CEIL_M = 13.0
WALL_THICK = 16
AOA_HEIGHT_M = 5.5
WARD_PANEL_COUNT = 36

TR = int(TOWER_RADIUS_M * UNITS_PER_METER)
FLOOR_Z = int(TOWER_FLOOR_M * UNITS_PER_METER)
CEIL_Z = int(TOWER_CEIL_M * UNITS_PER_METER)
AOA_Z = int(AOA_HEIGHT_M * UNITS_PER_METER)
EXT = TR + WALL_THICK + 32
LEVEL_BANDS = [
    ("perception", FLOOR_Z, FLOOR_Z + 96),
    ("cognition", FLOOR_Z + 96, FLOOR_Z + 192),
    ("communication", FLOOR_Z + 192, FLOOR_Z + 288),
    ("expression", FLOOR_Z + 288, FLOOR_Z + 384),
    ("grounding", FLOOR_Z + 384, CEIL_Z),
]

WARD_ANCHORS = [
    "token_pole",
    "album",
    "stream_overlay",
    "sierpinski",
    "reverie",
    "activity_header",
    "stance_indicator",
    "gem",
    "grounding_provenance_ticker",
    "impingement_cascade",
    "recruitment_candidate_panel",
    "thinking_indicator",
    "pressure_gauge",
    "activity_variety_log",
    "whos_here",
    "durf",
    "coding_session_reveal",
    "m8-display",
    "steamdeck-display",
    "egress_footer",
    "programme_banner",
    "precedent_ticker",
    "programme_history",
    "research_instrument_dashboard",
    "cbip_signal_density",
    "chat_ambient",
    "chronicle_ticker",
    "programme_state",
    "polyend_instrument_reveal",
    "interactive_lore_query",
    "constructivist_research_poster",
    "tufte_density",
    "ascii_schematic",
    "segment_content",
    "m8_oscilloscope",
    "cbip_dual_ir_displacement",
]

WARD_DOMAINS = {
    "token_pole": "token",
    "album": "music",
    "stream_overlay": "communication",
    "sierpinski": "perception",
    "reverie": "perception",
    "activity_header": "cognition",
    "stance_indicator": "presence",
    "gem": "perception",
    "grounding_provenance_ticker": "director",
    "impingement_cascade": "communication",
    "recruitment_candidate_panel": "cognition",
    "thinking_indicator": "presence",
    "pressure_gauge": "presence",
    "activity_variety_log": "cognition",
    "whos_here": "presence",
    "durf": "perception",
    "coding_session_reveal": "cognition",
    "m8-display": "music",
    "steamdeck-display": "music",
    "egress_footer": "director",
    "programme_banner": "director",
    "precedent_ticker": "director",
    "programme_history": "cognition",
    "research_instrument_dashboard": "cognition",
    "cbip_signal_density": "perception",
    "chat_ambient": "communication",
    "chronicle_ticker": "director",
    "programme_state": "director",
    "polyend_instrument_reveal": "music",
    "interactive_lore_query": "cognition",
    "constructivist_research_poster": "cognition",
    "tufte_density": "cognition",
    "ascii_schematic": "cognition",
    "segment_content": "communication",
    "m8_oscilloscope": "music",
    "cbip_dual_ir_displacement": "perception",
}

DOMAIN_GLOW_TEX = {
    "communication": "drift_g",
    "presence": "drift_a",
    "token": "drift_c",
    "music": "drift_r",
    "cognition": "drift_c",
    "director": "drift_a",
    "perception": "drift_g",
}

DOMAIN_LIGHT_COLOR = {
    "communication": (0.55, 0.95, 0.42),
    "presence": (1.00, 0.70, 0.28),
    "token": (0.45, 0.95, 0.88),
    "music": (1.00, 0.35, 0.65),
    "cognition": (0.40, 0.88, 1.00),
    "director": (1.00, 0.62, 0.23),
    "perception": (0.58, 0.88, 0.34),
}

WARD_COLUMNS = 7
WARD_PANE_W = 68
WARD_PANE_H = 50
WARD_X_SPACING = 74
WARD_Z_SPACING = 54
WARD_Y_TOP = 62
WARD_Y_STEP = -36
WARD_TOP_Z = FLOOR_Z + 344
WARD_GLOW_TEX = ["drift_c", "drift_a", "drift_r", "drift_g"]
SPECIAL_WARD_POSITIONS = {
    36: (0, WARD_Y_TOP + 5 * WARD_Y_STEP, FLOOR_Z + 92),
}

SOURCE_PANE_W = 58
SOURCE_PANE_H = 44
SOURCE_ANCHORS = [
    {
        "role": "brio-operator",
        "texture": "cam_bop",
        "camera_class": "brio",
        "domain": "presence",
        "pos": (-244, 112, FLOOR_Z + 350),
    },
    {
        "role": "brio-room",
        "texture": "cam_brm",
        "camera_class": "brio",
        "domain": "perception",
        "pos": (-244, 112, FLOOR_Z + 238),
    },
    {
        "role": "brio-synths",
        "texture": "cam_bsy",
        "camera_class": "brio",
        "domain": "music",
        "pos": (-244, 112, FLOOR_Z + 126),
    },
    {
        "role": "c920-desk",
        "texture": "cam_cdk",
        "camera_class": "c920",
        "domain": "cognition",
        "pos": (244, 112, FLOOR_Z + 350),
    },
    {
        "role": "c920-room",
        "texture": "cam_crm",
        "camera_class": "c920",
        "domain": "perception",
        "pos": (244, 112, FLOOR_Z + 238),
    },
    {
        "role": "c920-overhead",
        "texture": "cam_cov",
        "camera_class": "c920",
        "domain": "perception",
        "pos": (244, 112, FLOOR_Z + 126),
    },
]

MODE_PRESETS = {
    "rnd": {
        "wall_tex": "city4_2",
        "floor_tex": "ground1_6",
        "ceil_tex": "sky4",
        "shell_tex": "scroom",
        "ramp_tex": "metal5_2",
        "level_wall_tex": ["r_percep", "r_cognit", "r_comm", "r_express", "r_ground"],
        "level_ledge_tex": ["r_percep", "r_cognit", "r_comm", "r_express", "r_ground"],
        "pedestal_tex": "r_ground",
        "fog": "0.015 0.10 0.075 0.055",
        "level_light": 250,
        "wall_light": 105,
        "aoa_light_value": 290,
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
        "shell_tex": "scroom",
        "ramp_tex": "metal5_2",
        "level_wall_tex": ["s_percep", "s_cognit", "s_comm", "s_express", "s_ground"],
        "level_ledge_tex": ["s_percep", "s_cognit", "s_comm", "s_express", "s_ground"],
        "pedestal_tex": "s_ground",
        "fog": "0.014 0.035 0.07 0.10",
        "level_light": 220,
        "wall_light": 90,
        "aoa_light_value": 250,
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


def level_texture_bands(preset, key="level_wall_tex"):
    textures = preset.get(key) or [preset["wall_tex"]] * len(LEVEL_BANDS)
    return [
        (name, z1, z2, textures[min(idx, len(textures) - 1)])
        for idx, (name, z1, z2) in enumerate(LEVEL_BANDS)
    ]


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


def ward_anchor_position(idx):
    if idx in SPECIAL_WARD_POSITIONS:
        return SPECIAL_WARD_POSITIONS[idx]
    col = (idx - 1) % WARD_COLUMNS
    row = (idx - 1) // WARD_COLUMNS
    x = int((col - (WARD_COLUMNS - 1) * 0.5) * WARD_X_SPACING)
    y = WARD_Y_TOP + row * WARD_Y_STEP
    z = int(WARD_TOP_Z - row * WARD_Z_SPACING)
    return x, y, z


def ward_domain(idx):
    return WARD_DOMAINS[WARD_ANCHORS[idx - 1]]


def sealed_room(preset):
    brushes = []
    ft = preset.get("shell_tex", preset["floor_tex"])
    ct = preset.get("shell_tex", preset["ceil_tex"])
    wt = preset.get("shell_tex", preset["wall_tex"])
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
    pillar_size = 24
    for i in range(8):
        angle = i * (math.pi / 4) + math.pi / 8
        px = int((TR - 32) * math.cos(angle))
        py = int((TR - 32) * math.sin(angle))
        for _level, z1, z2, tex in level_texture_bands(preset):
            b = box_brush(
                px - pillar_size,
                py - pillar_size,
                z1,
                px + pillar_size,
                py + pillar_size,
                z2,
                tex,
            )
            if b:
                brushes.append(b)
    return brushes


def level_ledges(preset):
    """Stepped ledges at each level boundary — architectural strata."""
    brushes = []
    rt = preset["ramp_tex"]
    ledge_depth = 18
    ledge_height = 6

    for level in range(5):
        frac = level / 4
        z = FLOOR_Z + int((CEIL_Z - FLOOR_Z) * frac)
        level_tex = preset.get("level_ledge_tex", [rt] * 5)[level]
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
                    level_tex,
                )
            elif wall == 1:
                b = box_brush(
                    EXT - WALL_THICK - ledge_depth,
                    -EXT + WALL_THICK,
                    z,
                    EXT - WALL_THICK,
                    EXT - WALL_THICK,
                    z + ledge_height,
                    level_tex,
                )
            elif wall == 2:
                b = box_brush(
                    -EXT + WALL_THICK,
                    EXT - WALL_THICK - ledge_depth,
                    z,
                    EXT - WALL_THICK,
                    EXT - WALL_THICK,
                    z + ledge_height,
                    level_tex,
                )
            else:
                b = box_brush(
                    -EXT + WALL_THICK,
                    -EXT + WALL_THICK,
                    z,
                    -EXT + WALL_THICK + ledge_depth,
                    EXT - WALL_THICK,
                    z + ledge_height,
                    level_tex,
                )
            if b:
                brushes.append(b)
    return brushes


def central_lattice(preset):
    """Level rings and vertical rods in the scene core so the AoA has a structural field."""
    brushes = []
    outer = 96
    inner = 78
    rod_half = 3
    ring_height = 4

    for _level, z1, z2, tex in level_texture_bands(preset, "level_ledge_tex"):
        mid_z = z1 + int((z2 - z1) * 0.55)
        # Four ring segments around the central AoA sightline.
        segments = [
            (-outer, -outer, inner, -inner),
            (-outer, inner, inner, outer),
            (-outer, -inner, -inner, inner),
            (inner, -inner, outer, inner),
        ]
        for x1, y1, x2, y2 in segments:
            b = box_brush(x1, y1, mid_z, x2, y2, mid_z + ring_height, tex)
            if b:
                brushes.append(b)

        for x in (-outer, outer):
            for y in (-outer, outer):
                b = box_brush(
                    x - rod_half,
                    y - rod_half,
                    z1,
                    x + rod_half,
                    y + rod_half,
                    z2,
                    tex,
                )
                if b:
                    brushes.append(b)

    return brushes


def ward_scrim_panes(_preset):
    """Baked in-engine ward anchors held in the scroom volume.

    These are not HUD labels or fourth-wall overlays. They are physical ward
    panes and rails inside the DarkPlaces world: a 5x7 field plus the CBIP
    dual-IR displacement ward carried below it, moving from rear/high to
    near/low, so the camera looks into Screwm rather than at a flat wall.
    """
    brushes = []
    row_min_x = -224
    row_max_x = 224

    for idx, anchor in enumerate(WARD_ANCHORS, start=1):
        x, y, z = ward_anchor_position(idx)
        tex = f"w{idx:02d}"
        domain = ward_domain(idx)
        glow_tex = DOMAIN_GLOW_TEX[domain]
        brush = box_brush(
            x - WARD_PANE_W // 2,
            y - 2,
            z - WARD_PANE_H // 2,
            x + WARD_PANE_W // 2,
            y + 2,
            z + WARD_PANE_H // 2,
            tex,
        )
        if brush:
            brushes.append(
                f"// ward-anchor {idx:02d}: {anchor} domain={domain} pos={x},{y},{z}\n{brush}"
            )
        glow = box_brush(
            x - WARD_PANE_W // 2,
            y - 7,
            z - WARD_PANE_H // 2 - 7,
            x + WARD_PANE_W // 2,
            y - 3,
            z - WARD_PANE_H // 2 - 2,
            glow_tex,
        )
        if glow:
            brushes.append(f"// ward-glow {idx:02d}: {anchor} {glow_tex}\n{glow}")

    ward_rows = math.ceil(WARD_PANEL_COUNT / WARD_COLUMNS)
    for row in range(ward_rows):
        row_anchor_idx = min(row * WARD_COLUMNS + 1, WARD_PANEL_COUNT)
        _, y, z = ward_anchor_position(row_anchor_idx)
        rail = box_brush(row_min_x, y + 6, z - 4, row_max_x, y + 10, z + 4, "scroom")
        if rail:
            brushes.append(f"// ward-rail row {row + 1}: scroom carrier\n{rail}")

    for col in range(WARD_COLUMNS):
        x = int((col - (WARD_COLUMNS - 1) * 0.5) * WARD_X_SPACING)
        _, lowest_y, lowest_z = ward_anchor_position(WARD_PANEL_COUNT)
        z_low = lowest_z - WARD_PANE_H // 2
        z_high = WARD_TOP_Z + WARD_PANE_H // 2
        spine = box_brush(
            x - 3,
            lowest_y + 8,
            z_low,
            x + 3,
            WARD_Y_TOP + 10,
            z_high,
            "scroom",
        )
        if spine:
            brushes.append(f"// ward-spine col {col + 1}: scroom carrier\n{spine}")

    return brushes


def source_constellation_panes(_preset):
    """Physical source/camera anchors inside the scroom.

    These are not live video textures. They are the in-engine constellation
    points for the six camera feeds that existed in the last non-Quake Screwm.
    Live video remains blocked by DarkPlaces runtime texture limitations, but
    the scroom now has stable places for those sources to inhabit.
    """
    brushes = []
    tether_t = 5

    for idx, source in enumerate(SOURCE_ANCHORS, start=1):
        role = source["role"]
        tex = source["texture"]
        domain = source["domain"]
        glow_tex = DOMAIN_GLOW_TEX[domain]
        x, y, z = source["pos"]
        pane = box_brush(
            x - SOURCE_PANE_W // 2,
            y - 2,
            z - SOURCE_PANE_H // 2,
            x + SOURCE_PANE_W // 2,
            y + 2,
            z + SOURCE_PANE_H // 2,
            tex,
        )
        if pane:
            brushes.append(
                f"// source-anchor {idx:02d}: {role} "
                f"class={source['camera_class']} domain={domain} pos={x},{y},{z}\n{pane}"
            )

        glow = box_brush(
            x - SOURCE_PANE_W // 2,
            y - 7,
            z - SOURCE_PANE_H // 2 - 7,
            x + SOURCE_PANE_W // 2,
            y - 3,
            z - SOURCE_PANE_H // 2 - 2,
            glow_tex,
        )
        if glow:
            brushes.append(f"// source-glow {idx:02d}: {role} {glow_tex}\n{glow}")

        # Short material tether toward the ward field: source state belongs in
        # the same world volume rather than on the compositor's fourth wall.
        tether_end_x = int(x * 0.62)
        tether = box_brush(
            min(x, tether_end_x),
            y + 8 - tether_t,
            z - tether_t,
            max(x, tether_end_x),
            y + 8 + tether_t,
            z + tether_t,
            glow_tex,
        )
        if tether:
            brushes.append(f"// source-tether {idx:02d}: {role} {glow_tex}\n{tether}")

    return brushes


DRIFT_LINKS = [
    (1, 9, "drift_c"),
    (2, 10, "drift_a"),
    (3, 11, "drift_r"),
    (4, 12, "drift_g"),
    (5, 13, "drift_c"),
    (6, 14, "drift_a"),
    (7, 15, "drift_a"),
    (8, 16, "drift_g"),
    (15, 23, "drift_g"),
    (16, 24, "drift_c"),
    (17, 25, "drift_c"),
    (18, 26, "drift_r"),
    (19, 27, "drift_r"),
    (20, 28, "drift_a"),
    (21, 28, "drift_a"),
    (22, 30, "drift_a"),
    (24, 31, "drift_c"),
    (27, 34, "drift_a"),
    (4, 18, "drift_c"),
    (18, 32, "drift_g"),
    (29, 35, "drift_r"),
    (30, 33, "drift_c"),
    (31, 34, "drift_c"),
    (33, 36, "drift_c"),
    (34, 36, "drift_g"),
    (25, 36, "drift_r"),
    (32, 36, "drift_c"),
]


def ward_drift_paths(_preset):
    """Physical drift graph embedded in the scroom.

    Axis-aligned BSP brushes approximate the old overlay drift links as
    material rails through the ward field. This keeps drift inside the rendered
    world even when diagnostic CSQC lines are disabled.
    """
    brushes = []
    t = 5
    camera_forward_y = -10

    for link_idx, (src, dst, tex) in enumerate(DRIFT_LINKS, start=1):
        x1, y1, z1 = ward_anchor_position(src)
        x2, y2, z2 = ward_anchor_position(dst)
        y1 = y1 + camera_forward_y
        y2 = y2 + camera_forward_y
        parts = []
        if x1 != x2:
            parts.append(box_brush(min(x1, x2), y1 - t, z1 - t, max(x1, x2), y1 + t, z1 + t, tex))
        if y1 != y2:
            parts.append(box_brush(x2 - t, min(y1, y2), z1 - t, x2 + t, max(y1, y2), z1 + t, tex))
        if z1 != z2:
            parts.append(box_brush(x2 - t, y2 - t, min(z1, z2), x2 + t, y2 + t, max(z1, z2), tex))
        for part_idx, part in enumerate(parts, start=1):
            if part:
                brushes.append(
                    f"// ward-drift {link_idx:02d}.{part_idx}: {src:02d}->{dst:02d} {tex}\n{part}"
                )

    return brushes


def central_pedestal(preset):
    """Low pedestal at tower center for AoA to float above."""
    rt = preset.get("pedestal_tex", preset["ramp_tex"])
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
    ramp_w = 52
    ramp_d = 22
    for i in range(4):
        angle = i * (math.pi / 2) + math.pi / 8
        frac = (i + 1) / 5
        z = FLOOR_Z + int((CEIL_Z - FLOOR_Z) * frac)
        cx = int((TR * 0.7) * math.cos(angle))
        cy = int((TR * 0.7) * math.sin(angle))
        rt = preset.get("level_ledge_tex", [preset["ramp_tex"]] * 5)[i + 1]
        b = box_brush(cx - ramp_w, cy - ramp_d, z, cx + ramp_w, cy + ramp_d, z + 8, rt)
        if b:
            brushes.append(b)
    return brushes


def lights(preset):
    entities = []
    level_light = int(preset.get("level_light", 300))
    wall_light = int(preset.get("wall_light", 150))
    aoa_light_value = int(preset.get("aoa_light_value", 350))
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
            f'"light" "{level_light}"\n'
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
                f'"light" "{wall_light}"\n'
                f'"_color" "{r} {g} {b}"\n'
                "}"
            )

    # AoA center light (brighter, warm)
    ar, ag, ab = preset["aoa_light"]
    entities.append(
        "{\n"
        '"classname" "light"\n'
        f'"origin" "0 0 {AOA_Z}"\n'
        f'"light" "{aoa_light_value}"\n'
        f'"_color" "{ar} {ag} {ab}"\n'
        "}"
    )

    # Review fill lights live inside the scroom corridor. They keep the fixed
    # POV critiqueable without turning the scene into a flat/fullbright level.
    review_fill = int(level_light * 0.72)
    for idx, (x, y, z, scale) in enumerate(
        [
            (0, -144, 176, 1.00),
            (-148, -118, 214, 0.72),
            (148, -118, 214, 0.72),
        ],
        start=1,
    ):
        entities.append(
            f"// review-fill-light {idx}\n"
            "{\n"
            '"classname" "light"\n'
            f'"origin" "{x} {y} {z}"\n'
            f'"light" "{int(review_fill * scale)}"\n'
            f'"_color" "{ar} {ag} {ab}"\n'
            "}"
        )
    return entities


def ward_lights(preset):
    """Small baked lights at every in-scroom ward pane.

    Dynamic CSQC lights continue to carry live state; these baked lights make
    the full ward inventory reviewable in OBS even when live state is quiet.
    """
    entities = []
    base = int(preset.get("wall_light", 100) * 0.72)

    for idx, anchor in enumerate(WARD_ANCHORS, start=1):
        x, y, z = ward_anchor_position(idx)
        r, g, b = DOMAIN_LIGHT_COLOR[ward_domain(idx)]
        entities.append(
            f"// ward-light {idx:02d}: {anchor}\n"
            "{\n"
            '"classname" "light"\n'
            f'"origin" "{x} {y - 18} {z}"\n'
            f'"light" "{base}"\n'
            f'"_color" "{r} {g} {b}"\n'
            "}"
        )
    return entities


def source_lights(preset):
    """Baked source constellation lights; live camera state can modulate later."""
    entities = []
    base = int(preset.get("wall_light", 100) * 0.50)

    for idx, source in enumerate(SOURCE_ANCHORS, start=1):
        x, y, z = source["pos"]
        r, g, b = DOMAIN_LIGHT_COLOR[source["domain"]]
        entities.append(
            f"// source-light {idx:02d}: {source['role']}\n"
            "{\n"
            '"classname" "light"\n'
            f'"origin" "{x} {y - 18} {z}"\n'
            f'"light" "{base}"\n'
            f'"_color" "{r} {g} {b}"\n'
            "}"
        )
    return entities


def sectioned_brushes(section, brushes):
    return [f"// section: {section}", *brushes]


def generate_map(preset):
    lines = []
    lines.append(f"// Screwm Tower — {preset['message']}")
    lines.append("")

    worldspawn_brushes = (
        sectioned_brushes("sealed-scroom-shell", sealed_room(preset))
        + sectioned_brushes("tower-pillar-columns", pillar_columns(preset))
        + sectioned_brushes("tower-level-ledges", level_ledges(preset))
        + sectioned_brushes("central-aoa-lattice", central_lattice(preset))
        + sectioned_brushes("tower-ramp-shelves", ramp_shelves(preset))
        + sectioned_brushes("central-aoa-pedestal", central_pedestal(preset))
        + sectioned_brushes("source-camera-constellation", source_constellation_panes(preset))
        + sectioned_brushes("ward-scrim-panes", ward_scrim_panes(preset))
        + sectioned_brushes("ward-drift-paths", ward_drift_paths(preset))
    )

    lines.append("{")
    lines.append('"classname" "worldspawn"')
    lines.append(f'"message" "{preset["message"]}"')
    lines.append('"wad" "screwm.wad"')
    lines.append(f'"fog" "{preset["fog"]}"')
    for brush in worldspawn_brushes:
        lines.append(brush)
    lines.append("}")
    lines.append("")

    lines.append(
        f'{{\n"classname" "info_player_start"\n"origin" "0 0 {FLOOR_Z + 48}"\n"angle" "90"\n}}'
    )
    lines.append("")

    for light in lights(preset) + ward_lights(preset) + source_lights(preset):
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
            print("    OK")


def main():
    parser = argparse.ArgumentParser(description="Generate Screwm tower BSP maps")
    parser.add_argument("--mode", choices=["rnd", "research", "both"], default="both")
    parser.add_argument("--compile", action="store_true")
    args = parser.parse_args()

    if len(WARD_ANCHORS) != WARD_PANEL_COUNT:
        raise SystemExit(
            f"WARD_ANCHORS has {len(WARD_ANCHORS)} entries; expected {WARD_PANEL_COUNT}"
        )

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
