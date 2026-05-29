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
TOWER_RADIUS_M = 10.5
TOWER_FLOOR_M = -2.0
TOWER_CEIL_M = 13.0
WALL_THICK = 16
AOA_HEIGHT_M = 5.5
WARD_PANEL_COUNT = 36

TR = int(TOWER_RADIUS_M * UNITS_PER_METER)
FLOOR_Z = int(TOWER_FLOOR_M * UNITS_PER_METER)
CEIL_Z = int(TOWER_CEIL_M * UNITS_PER_METER)
AOA_X = 0
AOA_Y = -455
AOA_Z = int(AOA_HEIGHT_M * UNITS_PER_METER)
ROOM_X_EXT = 560
ROOM_Y_MIN = -860
ROOM_Y_MAX = 160
EXT = ROOM_X_EXT
REVIEW_ALCOVE_Y_MIN = ROOM_Y_MIN
REVIEW_WARD_Y = -455
REVIEW_DRIFT_Y = -500
ROOM_LEFT_X = -ROOM_X_EXT + WALL_THICK + 18
ROOM_RIGHT_X = ROOM_X_EXT - WALL_THICK - 18
ROOM_ENTRY_Y = ROOM_Y_MIN + WALL_THICK + 28
ROOM_FAR_Y = ROOM_Y_MAX - WALL_THICK - 24
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

WARD_DEPTH_PLANES = {
    "token_pole": "hero-presence",
    "album": "beyond-scrim",
    "stream_overlay": "surface-scrim",
    "sierpinski": "beyond-scrim",
    "reverie": "beyond-scrim",
    "activity_header": "surface-scrim",
    "stance_indicator": "surface-scrim",
    "gem": "beyond-scrim",
    "thinking_indicator": "surface-scrim",
    "whos_here": "surface-scrim",
    "durf": "beyond-scrim",
    "egress_footer": "surface-scrim",
    "programme_banner": "surface-scrim",
    "precedent_ticker": "surface-scrim",
    "chronicle_ticker": "surface-scrim",
    "programme_state": "surface-scrim",
    "segment_content": "surface-scrim",
}

WARD_DEPTH_STYLES = {
    "surface-scrim": {"layers": 0, "pad": 0, "y_step": 0, "x_shift": 0, "z_shift": 0},
    "near-surface": {"layers": 1, "pad": 7, "y_step": 12, "x_shift": 2, "z_shift": -2},
    "hero-presence": {"layers": 2, "pad": 9, "y_step": 14, "x_shift": -3, "z_shift": 3},
    "beyond-scrim": {"layers": 3, "pad": 11, "y_step": 16, "x_shift": 4, "z_shift": -4},
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
WARD_PANE_W = 48
WARD_PANE_H = 34
WARD_FRAME_PAD = 5
WARD_FRAME_T = 4
WARD_X_SPACING = 74
WARD_Z_SPACING = 54
WARD_Y_TOP = 62
WARD_Y_STEP = -36
WARD_TOP_Z = FLOOR_Z + 344
WARD_GLOW_TEX = ["drift_c", "drift_a", "drift_r", "drift_g"]
SPECIAL_WARD_POSITIONS = {
    36: (0, WARD_Y_TOP + 5 * WARD_Y_STEP, FLOOR_Z + 92),
}

GARDEN_CAMERA_STATIONS = [
    ("entry", (0, -780, 196), (0, -485, 188)),
    ("cognition-right", (315, -560, 186), (24, -455, 188)),
    ("far-programme", (0, -340, 176), (0, -485, 190)),
    ("perception-left", (-315, -560, 186), (-24, -455, 188)),
    ("borrowed-view", (0, -650, 214), (0, -455, 184)),
]

WARD_GARDEN_LAYOUT = {
    # No-front room arrangement from the last 3D Scroom grammar: dense but
    # deliberate clusters on multiple room boundaries, leaving the AoA volume
    # and walking space open. Left wall carries perception/music, right wall
    # carries cognition/instruments, far wall carries live programme/communication,
    # and entry/grounding sits on the approach path.
    1: (0, -700, 135, "y"),
    2: (-448, -650, 125, "x"),
    3: (-300, -220, 275, "y"),
    4: (-448, -560, 280, "x"),
    5: (-448, -470, 220, "x"),
    6: (448, -610, 300, "x"),
    7: (-210, -220, 195, "y"),
    8: (-448, -380, 290, "x"),
    9: (-110, -700, 95, "y"),
    10: (-120, -220, 310, "y"),
    11: (448, -520, 240, "x"),
    12: (-30, -220, 235, "y"),
    13: (60, -220, 155, "y"),
    14: (448, -430, 180, "x"),
    15: (150, -220, 275, "y"),
    16: (-448, -310, 170, "x"),
    17: (448, -340, 300, "x"),
    18: (-230, -700, 205, "y"),
    19: (-320, -700, 140, "y"),
    20: (110, -700, 95, "y"),
    21: (240, -220, 330, "y"),
    22: (220, -700, 175, "y"),
    23: (448, -620, 140, "x"),
    24: (448, -530, 330, "x"),
    25: (-448, -420, 110, "x"),
    26: (300, -220, 220, "y"),
    27: (320, -700, 250, "y"),
    28: (210, -220, 125, "y"),
    29: (-448, -610, 200, "x"),
    30: (448, -440, 260, "x"),
    31: (448, -350, 200, "x"),
    32: (448, -260, 140, "x"),
    33: (448, -265, 310, "x"),
    34: (0, -220, 330, "y"),
    35: (-448, -520, 330, "x"),
    36: (-448, -330, 90, "x"),
}

SOURCE_PANE_W = 62
SOURCE_PANE_H = 38
AOA_PAYLOAD_PANE_W = 28
AOA_PAYLOAD_PANE_H = 20
AOA_SPHERE_FACE_SIZE = 124
AOA_PAYLOAD_PANES = [
    ("root-pane", "aoa_root", "drift_c", -4, 108, 1.00),
    ("tri-texture", "aoa_tri", "drift_g", -72, 62, 0.92),
    ("data-glyph", "aoa_data", "drift_a", 72, 62, 0.92),
    ("signal-glyph", "aoa_glyph", "drift_r", -118, -6, 0.78),
    ("edge-accent", "aoa_edge", "drift_c", 118, -6, 0.78),
    ("lod-gate", "aoa_lod", "drift_g", -76, -74, 0.70),
    ("privacy-gate", "aoa_priv", "drift_a", 76, -74, 0.70),
    ("source-posture", "aoa_src", "drift_r", -176, 40, 0.58),
    ("composition", "aoa_comp", "drift_c", 176, 40, 0.58),
    ("payload-gate", "aoa_gate", "drift_g", 0, -112, 0.64),
]

SCROOM_SCENE_GRAPH_PANES = [
    # Larger media/source surfaces echo the 3D Scroom references. They are
    # room-mounted anchors, not a flat fourth-wall scene.
    ("hls", "brio-operator", "cam_bop", "drift_a", -325, -238, FLOOR_Z + 310, 72, 44),
    ("hls", "brio-room", "cam_brm", "drift_g", -212, -238, FLOOR_Z + 228, 64, 38),
    ("hls", "brio-synths", "cam_bsy", "drift_r", -318, -238, FLOOR_Z + 138, 64, 38),
    ("ir", "c920-desk", "cam_cdk", "drift_c", 205, -238, FLOOR_Z + 304, 64, 38),
    ("ir", "c920-room", "cam_crm", "drift_g", 320, -238, FLOOR_Z + 226, 64, 38),
    ("ir", "c920-overhead", "cam_cov", "drift_c", 245, -238, FLOOR_Z + 134, 64, 38),
    ("ir", "cbip-ir", "w36", "drift_g", -392, -700, FLOOR_Z + 260, 58, 36),
    ("ward-shelf", "programme-history", "w23", "drift_a", 382, -700, FLOOR_Z + 294, 58, 36),
    ("ward-shelf", "instrument-dashboard", "w24", "drift_c", 382, -700, FLOOR_Z + 218, 58, 36),
    ("ward-shelf", "interactive-query", "w30", "drift_a", 382, -700, FLOOR_Z + 142, 58, 36),
    ("mid-band", "chat-ambient", "w26", "drift_g", -60, -238, FLOOR_Z + 344, 52, 34),
    ("mid-band", "impingement", "w10", "drift_a", 70, -238, FLOOR_Z + 344, 52, 34),
    ("far-band", "variety-log", "w14", "drift_c", 352, -238, FLOOR_Z + 84, 48, 30),
    ("far-band", "scope-wave", "w35", "drift_r", -428, -700, FLOOR_Z + 92, 48, 30),
]
SCROOM_LIGHT_MARKER = (0, -455, FLOOR_Z + 390)
SCROOM_MATERIAL_BEAMS = []
SCROOM_GRID_X_LINES = []
SCROOM_GRID_Y_LINES = []
SCROOM_PATH_STONES = [
    ("entry", "drift_c", 0, -790, FLOOR_Z + 7, 120, 30),
    ("left-return", "drift_g", -260, -590, FLOOR_Z + 7, 104, 28),
    ("aoa-near", "drift_a", 0, -455, FLOOR_Z + 7, 128, 32),
    ("right-return", "drift_r", 260, -590, FLOOR_Z + 7, 104, 28),
    ("far-look", "drift_c", 0, -265, FLOOR_Z + 7, 112, 30),
]
SCROOM_GARDEN_ISLANDS = [
    ("entry-raked-bed", "scroom", 0, -790, FLOOR_Z + 2, 230, 80),
    ("left-raked-bed", "scroom", -290, -575, FLOOR_Z + 2, 178, 74),
    ("aoa-raked-bed", "scroom", 0, -455, FLOOR_Z + 2, 220, 92),
    ("right-raked-bed", "scroom", 290, -575, FLOOR_Z + 2, 178, 74),
    ("far-raked-bed", "scroom", 0, -265, FLOOR_Z + 2, 210, 72),
]
SCROOM_GARDEN_LANTERNS = [
    ("entry-lantern", "drift_c", 0, -742, FLOOR_Z + 18),
    ("left-lantern", "drift_g", -350, -540, FLOOR_Z + 18),
    ("aoa-lantern", "drift_a", -118, -420, FLOOR_Z + 18),
    ("right-lantern", "drift_r", 350, -540, FLOOR_Z + 18),
    ("far-lantern", "drift_c", 118, -286, FLOOR_Z + 18),
]
SCROOM_LOCAL_EFFECTS = [
    # Mirrors scene_quad.wgsl entity-local source-plane spatial effects.
    ("mirror", "fx_mirr", "drift_c", -250, -522, FLOOR_Z + 92),
    ("kaleidoscope", "fx_kale", "drift_r", -200, -522, FLOOR_Z + 92),
    ("warp", "fx_warp", "drift_g", -150, -522, FLOOR_Z + 92),
    ("fisheye", "fx_fish", "drift_c", -100, -522, FLOOR_Z + 92),
    ("transform", "fx_xfrm", "drift_a", -50, -522, FLOOR_Z + 92),
    ("displacement_map", "fx_disp", "drift_r", 0, -522, FLOOR_Z + 92),
    ("droste", "fx_dros", "drift_c", 50, -522, FLOOR_Z + 92),
    ("tunnel", "fx_tunn", "drift_g", 100, -522, FLOOR_Z + 92),
    ("tile", "fx_tile", "drift_a", 150, -522, FLOOR_Z + 92),
    ("drift", "fx_drif", "drift_g", 200, -522, FLOOR_Z + 92),
    ("breathing", "fx_brea", "drift_a", 250, -522, FLOOR_Z + 92),
]
SOURCE_ANCHORS = [
    {
        "role": "brio-operator",
        "texture": "cam_bop",
        "camera_class": "brio",
        "domain": "presence",
        "pos": (-385, -600, FLOOR_Z + 330),
        "facing": "x",
    },
    {
        "role": "brio-room",
        "texture": "cam_brm",
        "camera_class": "brio",
        "domain": "perception",
        "pos": (-420, -505, FLOOR_Z + 238),
        "facing": "x",
    },
    {
        "role": "brio-synths",
        "texture": "cam_bsy",
        "camera_class": "brio",
        "domain": "music",
        "pos": (-380, -660, FLOOR_Z + 150),
        "facing": "x",
    },
    {
        "role": "c920-desk",
        "texture": "cam_cdk",
        "camera_class": "c920",
        "domain": "cognition",
        "pos": (405, -370, FLOOR_Z + 314),
        "facing": "x",
    },
    {
        "role": "c920-room",
        "texture": "cam_crm",
        "camera_class": "c920",
        "domain": "perception",
        "pos": (430, -455, FLOOR_Z + 226),
        "facing": "x",
    },
    {
        "role": "c920-overhead",
        "texture": "cam_cov",
        "camera_class": "c920",
        "domain": "perception",
        "pos": (390, -300, FLOOR_Z + 132),
        "facing": "x",
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


def inward_x_normal(x):
    return 1 if x < 0 else -1


def inward_y_normal(y):
    return 1 if y < (ROOM_Y_MIN + ROOM_Y_MAX) // 2 else -1


def offset_span(center, direction, near, far):
    return tuple(sorted((center + direction * near, center + direction * far)))


def pane_light_origin(x, y, z, facing, distance):
    if facing == "x":
        return x + inward_x_normal(x) * distance, y, z
    return x, y + inward_y_normal(y) * distance, z


def framed_y_pane(comment_prefix, idx, name, tex, frame_tex, x, y, z, w, h):
    """Return a y-facing physical pane and four-bar frame."""
    brushes = []
    pane = box_brush(x - w // 2, y - 2, z - h // 2, x + w // 2, y + 2, z + h // 2, tex)
    if pane:
        brushes.append(f"// {comment_prefix} {idx:02d}: {name} {tex}\n{pane}")

    frame_pad = 5
    frame_y0, frame_y1 = offset_span(y, inward_y_normal(y), 4, 8)
    for frame_name, frame in (
        (
            "top",
            box_brush(
                x - w // 2 - frame_pad,
                frame_y0,
                z + h // 2 + 2,
                x + w // 2 + frame_pad,
                frame_y1,
                z + h // 2 + frame_pad,
                frame_tex,
            ),
        ),
        (
            "bottom",
            box_brush(
                x - w // 2 - frame_pad,
                frame_y0,
                z - h // 2 - frame_pad,
                x + w // 2 + frame_pad,
                frame_y1,
                z - h // 2 - 2,
                frame_tex,
            ),
        ),
        (
            "left",
            box_brush(
                x - w // 2 - frame_pad,
                frame_y0,
                z - h // 2 - frame_pad,
                x - w // 2 - 1,
                frame_y1,
                z + h // 2 + frame_pad,
                frame_tex,
            ),
        ),
        (
            "right",
            box_brush(
                x + w // 2 + 1,
                frame_y0,
                z - h // 2 - frame_pad,
                x + w // 2 + frame_pad,
                frame_y1,
                z + h // 2 + frame_pad,
                frame_tex,
            ),
        ),
    ):
        if frame:
            brushes.append(f"// {comment_prefix}-frame {idx:02d}: {name} {frame_name}\n{frame}")

    return brushes


def framed_x_pane(comment_prefix, idx, name, tex, frame_tex, x, y, z, w, h):
    """Return an x-facing physical pane and four-bar frame."""
    brushes = []
    pane = box_brush(x - 2, y - w // 2, z - h // 2, x + 2, y + w // 2, z + h // 2, tex)
    if pane:
        brushes.append(f"// {comment_prefix} {idx:02d}: {name} {tex}\n{pane}")

    frame_pad = 5
    frame_x0, frame_x1 = offset_span(x, inward_x_normal(x), 4, 8)
    for frame_name, frame in (
        (
            "top",
            box_brush(
                frame_x0,
                y - w // 2 - frame_pad,
                z + h // 2 + 2,
                frame_x1,
                y + w // 2 + frame_pad,
                z + h // 2 + frame_pad,
                frame_tex,
            ),
        ),
        (
            "bottom",
            box_brush(
                frame_x0,
                y - w // 2 - frame_pad,
                z - h // 2 - frame_pad,
                frame_x1,
                y + w // 2 + frame_pad,
                z - h // 2 - 2,
                frame_tex,
            ),
        ),
        (
            "left",
            box_brush(
                frame_x0,
                y - w // 2 - frame_pad,
                z - h // 2 - frame_pad,
                frame_x1,
                y - w // 2 - 1,
                z + h // 2 + frame_pad,
                frame_tex,
            ),
        ),
        (
            "right",
            box_brush(
                frame_x0,
                y + w // 2 + 1,
                z - h // 2 - frame_pad,
                frame_x1,
                y + w // 2 + frame_pad,
                z + h // 2 + frame_pad,
                frame_tex,
            ),
        ),
    ):
        if frame:
            brushes.append(f"// {comment_prefix}-frame {idx:02d}: {name} {frame_name}\n{frame}")

    return brushes


def framed_garden_pane(comment_prefix, idx, name, tex, frame_tex, x, y, z, w, h, facing):
    if facing == "x":
        return framed_x_pane(comment_prefix, idx, name, tex, frame_tex, x, y, z, w, h)
    return framed_y_pane(comment_prefix, idx, name, tex, frame_tex, x, y, z, w, h)


def ward_state_lamp(idx, anchor, glow_tex, x, y, z, w, h, facing):
    """Physical live-state receiver beside a ward pane.

    CSQC cannot rewrite BSP textures every frame, so each ward gets a small
    in-world lamp/spine next to its baked identity texture. Dynamic ward lights
    illuminate these receivers from live activity/presence scalars.
    """
    if facing == "x":
        lamp_x0, lamp_x1 = offset_span(x, inward_x_normal(x), 4, 12)
        lamp = box_brush(
            lamp_x0,
            y + w // 2 + 7,
            z - h // 2,
            lamp_x1,
            y + w // 2 + 13,
            z + h // 2,
            glow_tex,
        )
    else:
        lamp_y0, lamp_y1 = offset_span(y, inward_y_normal(y), 4, 12)
        lamp = box_brush(
            x + w // 2 + 7,
            lamp_y0,
            z - h // 2,
            x + w // 2 + 13,
            lamp_y1,
            z + h // 2,
            glow_tex,
        )
    return [f"// ward-state-lamp {idx:02d}: {anchor}\n{lamp}"] if lamp else []


def axis_beam_segments(comment_prefix, idx, name, tex, start, end, thickness=3):
    """Return orthogonal thin beam segments approximating a volumetric ray."""
    sx, sy, sz = start
    ex, ey, ez = end
    joints = ((sx, sy, sz), (ex, sy, sz), (ex, ey, sz), (ex, ey, ez))
    brushes = []

    for part_idx, (a, b) in enumerate(zip(joints[:-1], joints[1:], strict=True), start=1):
        ax, ay, az = a
        bx, by, bz = b
        if a == b:
            continue
        segment = box_brush(
            min(ax, bx) - thickness,
            min(ay, by) - thickness,
            min(az, bz) - thickness,
            max(ax, bx) + thickness,
            max(ay, by) + thickness,
            max(az, bz) + thickness,
            tex,
        )
        if segment:
            brushes.append(f"// {comment_prefix} {idx:02d}.{part_idx}: {name} {tex}\n{segment}")

    return brushes


def ward_anchor_position(idx):
    if idx in WARD_GARDEN_LAYOUT:
        x, y, z, _facing = WARD_GARDEN_LAYOUT[idx]
        return x, y, z
    if idx in SPECIAL_WARD_POSITIONS:
        return SPECIAL_WARD_POSITIONS[idx]
    col = (idx - 1) % WARD_COLUMNS
    row = (idx - 1) // WARD_COLUMNS
    x = int((col - (WARD_COLUMNS - 1) * 0.5) * WARD_X_SPACING)
    y = WARD_Y_TOP + row * WARD_Y_STEP
    z = int(WARD_TOP_Z - row * WARD_Z_SPACING)
    return x, y, z


def ward_review_position(idx):
    return ward_anchor_position(idx)


def ward_garden_facing(idx):
    if idx in WARD_GARDEN_LAYOUT:
        return WARD_GARDEN_LAYOUT[idx][3]
    return "y"


def ward_review_drift_midpoint(src, dst):
    x1, y1, z1 = ward_review_position(src)
    x2, y2, z2 = ward_review_position(dst)
    return (x1 + x2) // 2, (y1 + y2) // 2, (z1 + z2) // 2


def ward_domain(idx):
    return WARD_DOMAINS[WARD_ANCHORS[idx - 1]]


def ward_depth_plane(idx):
    return WARD_DEPTH_PLANES.get(WARD_ANCHORS[idx - 1], "near-surface")


def sealed_room(preset):
    brushes = []
    ft = preset.get("shell_tex", preset["floor_tex"])
    ct = preset.get("shell_tex", preset["ceil_tex"])
    wt = preset.get("shell_tex", preset["wall_tex"])
    brushes.append(box_brush(-EXT, ROOM_Y_MIN, FLOOR_Z - WALL_THICK, EXT, ROOM_Y_MAX, FLOOR_Z, ft))
    brushes.append(box_brush(-EXT, ROOM_Y_MIN, CEIL_Z, EXT, ROOM_Y_MAX, CEIL_Z + WALL_THICK, ct))
    brushes.append(
        box_brush(-EXT, ROOM_Y_MIN, FLOOR_Z, -EXT + WALL_THICK, ROOM_Y_MAX, CEIL_Z, wt)
    )
    brushes.append(box_brush(EXT - WALL_THICK, ROOM_Y_MIN, FLOOR_Z, EXT, ROOM_Y_MAX, CEIL_Z, wt))
    brushes.append(
        box_brush(-EXT, ROOM_Y_MIN, FLOOR_Z, EXT, ROOM_Y_MIN + WALL_THICK, CEIL_Z, wt)
    )
    brushes.append(box_brush(-EXT, ROOM_Y_MAX - WALL_THICK, FLOOR_Z, EXT, ROOM_Y_MAX, CEIL_Z, wt))
    return [b for b in brushes if b]


def pillar_columns(preset):
    """No free-standing columns in the reviewable scroom baseline."""
    return []


def level_ledges(preset):
    """Wall bands are deferred; the baseline must read as open space first."""
    return []


def central_lattice(preset):
    """Low, non-obstructing AoA floor mark under the authored foreground anchor."""
    brushes = []
    tex = preset.get("pedestal_tex", preset["ramp_tex"])
    mark_z = FLOOR_Z + 4
    for x1, y1, x2, y2 in (
        (-110, -5, 110, 5),
        (-5, -110, 5, 110),
        (-78, -78, -68, 78),
        (68, -78, 78, 78),
    ):
        b = box_brush(x1, y1, mark_z, x2, y2, mark_z + 4, tex)
        if b:
            shifted = box_brush(
                x1 + AOA_X,
                y1 + AOA_Y,
                mark_z,
                x2 + AOA_X,
                y2 + AOA_Y,
                mark_z + 4,
                tex,
            )
            if shifted:
                brushes.append(shifted)
    return brushes


def ward_review_panes(_preset):
    """No-front garden clumps for all in-scroom wards.

    The default Scroom is not a frontal board. Wards live as physical panes in
    semantic garden islands around the AoA and recurrent path; OBS feedback is
    obtained by moving through the garden, not by flattening it onto a wall.
    """
    brushes = []

    for idx, anchor in enumerate(WARD_ANCHORS, start=1):
        x, y, z = ward_review_position(idx)
        tex = f"w{idx:02d}"
        domain = ward_domain(idx)
        glow_tex = DOMAIN_GLOW_TEX[domain]

        brushes.extend(
            framed_garden_pane(
                "ward-garden-pane",
                idx,
                anchor,
                tex,
                glow_tex,
                x,
                y,
                z,
                WARD_PANE_W,
                WARD_PANE_H,
                ward_garden_facing(idx),
            )
        )
        brushes.extend(
            ward_state_lamp(
                idx,
                anchor,
                glow_tex,
                x,
                y,
                z,
                WARD_PANE_W,
                WARD_PANE_H,
                ward_garden_facing(idx),
            )
        )

    return brushes


def aoa_payload_panes(_preset):
    """Pane-local payload plaques around the current AoA/tetrix anchor.

    These mirror the latest Scroom AoA pane binding contract: root pane,
    tri-texture masked payloads, glyph modes, LOD/privacy/source gates, and
    composition posture live on the AoA object rather than as a flat overlay.
    """
    brushes = []

    for idx, (name, tex, frame_tex, dx, dz, _opacity) in enumerate(AOA_PAYLOAD_PANES, start=1):
        x = AOA_X + dx
        y = AOA_Y - 18
        z = AOA_Z + dz
        brushes.extend(
            framed_y_pane(
                "aoa-payload-pane",
                idx,
                name,
                tex,
                frame_tex,
                x,
                y,
                z,
                AOA_PAYLOAD_PANE_W,
                AOA_PAYLOAD_PANE_H,
            )
        )

    return brushes


def aoa_attendant_sphere_face(_preset):
    """Central media sphere face contained by the AoA/tetrix volume."""
    x = AOA_X
    y = AOA_Y - 132
    z = AOA_Z + 8
    brushes = framed_y_pane(
        "aoa-attendant-sphere",
        1,
        "yt-media-face",
        "yt_sphere",
        "drift_a",
        x,
        y,
        z,
        AOA_SPHERE_FACE_SIZE,
        AOA_SPHERE_FACE_SIZE,
    )
    brushes.extend(
        framed_x_pane(
            "aoa-attendant-sphere-cross",
            1,
            "yt-media-face-side",
            "yt_sphere",
            "drift_c",
            x,
            y,
            z,
            AOA_SPHERE_FACE_SIZE,
            AOA_SPHERE_FACE_SIZE,
        )
    )
    for idx, ring in enumerate(
        (
            box_brush(x - 54, y - 10, z - 2, x + 54, y - 5, z + 2, "drift_c"),
            box_brush(x - 2, y - 10, z - 54, x + 2, y - 5, z + 54, "drift_g"),
            box_brush(x - 42, y - 11, z - 42, x - 34, y - 4, z + 42, "drift_r"),
            box_brush(x + 34, y - 11, z - 42, x + 42, y - 4, z + 42, "drift_r"),
        ),
        start=1,
    ):
        if ring:
            brushes.append(f"// aoa-attendant-sphere-ring {idx:02d}\n{ring}")
    return brushes


def scroom_scene_graph_bands(_preset):
    """Physicalized Scroom scene-graph bands from the pre-Quake renderer.

    The old 3D Scroom did not treat cameras, wards, and status panes as a
    flat board; it arranged them in deoccluded left/right/mid/far bands around
    the AoA. This brings that grammar into BSP geometry.
    """
    brushes = []

    for idx, (band, name, tex, frame_tex, x, y, z, w, h) in enumerate(
        SCROOM_SCENE_GRAPH_PANES, start=1
    ):
        brushes.extend(
            framed_y_pane(
                f"scroom-scene-{band}",
                idx,
                name,
                tex,
                frame_tex,
                x,
                y,
                z,
                w,
                h,
            )
        )
    return brushes


def scroom_material_field(_preset):
    """No-front garden floor marks and borrowed-view light marker."""
    brushes = []
    mx, my, mz = SCROOM_LIGHT_MARKER

    for idx, marker in enumerate(
        (
            box_brush(mx - 18, my - 3, mz - 3, mx + 18, my + 3, mz + 3, "drift_c"),
            box_brush(mx - 3, my - 18, mz - 3, mx + 3, my + 18, mz + 3, "drift_a"),
            box_brush(mx - 3, my - 3, mz - 18, mx + 3, my + 3, mz + 18, "drift_g"),
        ),
        start=1,
    ):
        if marker:
            brushes.append(f"// scroom-light-marker {idx:02d}\n{marker}")

    for idx, (name, tex, x, y, z, w, h) in enumerate(SCROOM_PATH_STONES, start=1):
        stone = box_brush(x - w // 2, y - h // 2, z, x + w // 2, y + h // 2, z + 4, tex)
        if stone:
            brushes.append(f"// scroom-garden-path-stone {idx:02d}: {name} {tex}\n{stone}")

    for idx, (name, tex, x, y, z, w, h) in enumerate(SCROOM_GARDEN_ISLANDS, start=1):
        island = box_brush(x - w // 2, y - h // 2, z, x + w // 2, y + h // 2, z + 3, tex)
        if island:
            brushes.append(f"// scroom-garden-island {idx:02d}: {name} {tex}\n{island}")

    for idx, (name, tex, x, y, z) in enumerate(SCROOM_GARDEN_LANTERNS, start=1):
        post = box_brush(x - 4, y - 4, z, x + 4, y + 4, z + 54, tex)
        cap = box_brush(x - 10, y - 10, z + 54, x + 10, y + 10, z + 62, tex)
        if post:
            brushes.append(f"// scroom-garden-lantern {idx:02d}: {name} post\n{post}")
        if cap:
            brushes.append(f"// scroom-garden-lantern-cap {idx:02d}: {name} cap\n{cap}")

    return brushes


def scroom_room_grid(_preset):
    """Luminous room grid on floor, ceiling, and walls.

    The previous 3D Scroom read as a room because every boundary carried a
    navigational grid. These beams establish scale and orientation without
    making a front-facing theater.
    """
    brushes = []
    tex_cycle = ("drift_c", "drift_g", "drift_a", "drift_r")
    inner_x = ROOM_X_EXT - WALL_THICK - 18
    y_min = ROOM_Y_MIN + WALL_THICK + 18
    y_max = ROOM_Y_MAX - WALL_THICK - 18
    floor_z = FLOOR_Z + 5
    ceil_z = CEIL_Z - 8

    for idx, x in enumerate(range(-480, 481, 160), start=1):
        tex = tex_cycle[idx % len(tex_cycle)]
        floor = box_brush(x - 3, y_min, floor_z, x + 3, y_max, floor_z + 5, tex)
        ceiling = box_brush(x - 3, y_min, ceil_z, x + 3, y_max, ceil_z + 5, tex)
        if floor:
            brushes.append(f"// scroom-room-floor-grid-x {idx:02d}\n{floor}")
        if ceiling:
            brushes.append(f"// scroom-room-ceiling-grid-x {idx:02d}\n{ceiling}")

    for idx, y in enumerate((-800, -640, -455, -300, -140, 40), start=1):
        tex = tex_cycle[(idx + 1) % len(tex_cycle)]
        floor = box_brush(-inner_x, y - 3, floor_z, inner_x, y + 3, floor_z + 5, tex)
        ceiling = box_brush(-inner_x, y - 3, ceil_z, inner_x, y + 3, ceil_z + 5, tex)
        if floor:
            brushes.append(f"// scroom-room-floor-grid-y {idx:02d}\n{floor}")
        if ceiling:
            brushes.append(f"// scroom-room-ceiling-grid-y {idx:02d}\n{ceiling}")

    for side_idx, x in enumerate((-inner_x, inner_x), start=1):
        for idx, y in enumerate((-760, -610, -455, -300, -145), start=1):
            tex = tex_cycle[(idx + side_idx) % len(tex_cycle)]
            wall = box_brush(x - 3, y - 3, FLOOR_Z + 20, x + 3, y + 3, CEIL_Z - 28, tex)
            if wall:
                brushes.append(f"// scroom-room-side-grid-v {side_idx:02d}.{idx:02d}\n{wall}")
        for idx, z in enumerate((FLOOR_Z + 92, FLOOR_Z + 188, FLOOR_Z + 284, FLOOR_Z + 380), start=1):
            tex = tex_cycle[(idx + side_idx + 1) % len(tex_cycle)]
            wall = box_brush(x - 3, y_min, z - 3, x + 3, y_max, z + 3, tex)
            if wall:
                brushes.append(f"// scroom-room-side-grid-h {side_idx:02d}.{idx:02d}\n{wall}")

    for wall_idx, y in enumerate((ROOM_ENTRY_Y, ROOM_FAR_Y), start=1):
        for idx, x in enumerate(range(-400, 401, 160), start=1):
            tex = tex_cycle[(idx + wall_idx) % len(tex_cycle)]
            wall = box_brush(x - 3, y - 3, FLOOR_Z + 20, x + 3, y + 3, CEIL_Z - 28, tex)
            if wall:
                brushes.append(f"// scroom-room-end-grid-v {wall_idx:02d}.{idx:02d}\n{wall}")
        for idx, z in enumerate((FLOOR_Z + 104, FLOOR_Z + 224, FLOOR_Z + 344), start=1):
            tex = tex_cycle[(idx + wall_idx + 2) % len(tex_cycle)]
            wall = box_brush(-inner_x, y - 3, z - 3, inner_x, y + 3, z + 3, tex)
            if wall:
                brushes.append(f"// scroom-room-end-grid-h {wall_idx:02d}.{idx:02d}\n{wall}")

    return brushes


def scroom_local_effect_lenses(_preset):
    """Physical entity-local effect rail from scene_quad.wgsl.

    The old Scroom renderer explicitly restored these spatial effects as
    source-plane-local operations, not output-plane overlays. In Quake we bind
    them to small in-world lenses under the scene graph so the scroom contains
    the effect vocabulary even before runtime texture mutation exists.
    """
    brushes = []

    for idx, (name, tex, frame_tex, x, y, z) in enumerate(SCROOM_LOCAL_EFFECTS, start=1):
        brushes.extend(
            framed_y_pane("scroom-local-effect-lens", idx, name, tex, frame_tex, x, y, z, 36, 28)
        )

    return brushes


def ward_review_drift_paths(_preset):
    """Small luminous stepping stones showing drift links through the garden."""
    brushes = []
    t = 4

    for link_idx, (src, dst, tex) in enumerate(DRIFT_LINKS, start=1):
        x, y, z = ward_review_drift_midpoint(src, dst)
        z = max(FLOOR_Z + 18, z)
        stone = box_brush(x - t, y - t, z - t, x + t, y + t, z + t, tex)
        if stone:
            brushes.append(
                f"// ward-garden-drift-stone {link_idx:02d}: "
                f"{src:02d}->{dst:02d} {tex}\n{stone}"
            )

    return brushes


def ward_depth_echo_panes(_preset):
    """Depth is carried by paths/lightfields in the garden baseline."""
    return []


def ward_scrim_panes(_preset):
    """The duplicate deep ward lattice is disabled in the open scroom baseline."""
    return []


def source_constellation_panes(_preset):
    """Physical source/camera anchors inside the scroom.

    These are not live video textures. They are the in-engine constellation
    points for the six camera feeds that existed in the last non-Quake Screwm.
    Live video remains blocked by DarkPlaces runtime texture limitations, but
    the scroom now has stable places for those sources to inhabit.
    """
    brushes = []

    for idx, source in enumerate(SOURCE_ANCHORS, start=1):
        role = source["role"]
        tex = source["texture"]
        domain = source["domain"]
        glow_tex = DOMAIN_GLOW_TEX[domain]
        x, y, z = source["pos"]
        brushes.extend(
            framed_garden_pane(
                "source-garden-anchor",
                idx,
                role,
                tex,
                glow_tex,
                x,
                y,
                z,
                SOURCE_PANE_W,
                SOURCE_PANE_H,
                source.get("facing", "y"),
            )
        )

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
    """The duplicate deep drift lattice is disabled in the open scroom baseline."""
    return []


def central_pedestal(preset):
    """Low pedestal under the current authored AoA anchor."""
    rt = preset.get("pedestal_tex", preset["ramp_tex"])
    pedestal_size = 48
    pedestal_height = 16
    b = box_brush(
        AOA_X - pedestal_size,
        AOA_Y - pedestal_size,
        FLOOR_Z,
        AOA_X + pedestal_size,
        AOA_Y + pedestal_size,
        FLOOR_Z + pedestal_height,
        rt,
    )
    return [b] if b else []


def ramp_shelves(preset):
    return []


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
        y = AOA_Y + int(TR * 0.3 * math.sin(angle))
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
        py = AOA_Y + int((TR - 48) * math.sin(angle))
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
        f'"origin" "{AOA_X} {AOA_Y} {AOA_Z}"\n'
        f'"light" "{aoa_light_value}"\n'
        f'"_color" "{ar} {ag} {ab}"\n'
        "}"
    )

    # Review fill lights live inside the scroom corridor. They keep the fixed
    # POV critiqueable without turning the scene into a flat/fullbright level.
    review_fill = int(level_light * 0.72)
    for idx, (_name, (x, y, z), _target) in enumerate(GARDEN_CAMERA_STATIONS, start=1):
        scale = (0.70, 0.82, 0.90, 0.82, 0.74)[idx - 1]
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
        lx, ly, lz = pane_light_origin(x, y, z, ward_garden_facing(idx), 18)
        r, g, b = DOMAIN_LIGHT_COLOR[ward_domain(idx)]
        entities.append(
            f"// ward-light {idx:02d}: {anchor}\n"
            "{\n"
            '"classname" "light"\n'
            f'"origin" "{lx} {ly} {lz}"\n'
            f'"light" "{base}"\n'
            f'"_color" "{r} {g} {b}"\n'
            "}"
        )
    return entities


def ward_review_lights(preset):
    """Baked lights for the no-front garden ward clumps.

    The OBS feedback path should see the same in-world ward positions as the
    dynamic CSQC lightfield, not a separate flat review wall.
    """
    entities = []
    base = int(preset.get("wall_light", 100) * 1.35)

    for idx, anchor in enumerate(WARD_ANCHORS, start=1):
        x, y, z = ward_review_position(idx)
        lx, ly, lz = pane_light_origin(x, y, z, ward_garden_facing(idx), 42)
        r, g, b = DOMAIN_LIGHT_COLOR[ward_domain(idx)]
        entities.append(
            f"// ward-garden-light {idx:02d}: {anchor}\n"
            "{\n"
            '"classname" "light"\n'
            f'"origin" "{lx} {ly} {lz}"\n'
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
        lx, ly, lz = pane_light_origin(x, y, z, source.get("facing", "y"), 18)
        r, g, b = DOMAIN_LIGHT_COLOR[source["domain"]]
        entities.append(
            f"// source-light {idx:02d}: {source['role']}\n"
            "{\n"
            '"classname" "light"\n'
            f'"origin" "{lx} {ly} {lz}"\n'
            f'"light" "{base}"\n'
            f'"_color" "{r} {g} {b}"\n'
            "}"
        )
    return entities


def aoa_payload_lights(preset):
    """Baked light support for current AoA pane-local payload plaques."""
    entities = []
    base = int(preset.get("wall_light", 100) * 0.92)

    for idx, (name, _tex, frame_tex, dx, dz, _opacity) in enumerate(AOA_PAYLOAD_PANES, start=1):
        x = AOA_X + dx
        y = AOA_Y - 42
        z = AOA_Z + dz
        lx, ly, lz = pane_light_origin(x, y, z, "y", 22)
        color_key = {
            "drift_c": "token",
            "drift_g": "perception",
            "drift_a": "director",
            "drift_r": "music",
        }.get(frame_tex, "perception")
        r, g, b = DOMAIN_LIGHT_COLOR[color_key]
        entities.append(
            f"// aoa-payload-light {idx:02d}: {name}\n"
            "{\n"
            '"classname" "light"\n'
            f'"origin" "{lx} {ly} {lz}"\n'
            f'"light" "{base}"\n'
            f'"_color" "{r} {g} {b}"\n'
            "}"
        )

    return entities


def aoa_attendant_sphere_lights(preset):
    """Baked light support for the visible AoA sphere/media face."""
    base = int(preset.get("aoa_light_value", 260) * 0.68)
    ar, ag, ab = preset["aoa_light"]
    x = AOA_X
    y = AOA_Y - 132
    z = AOA_Z + 8
    lx, ly, lz = pane_light_origin(x, y, z, "y", 36)
    return [
        "// aoa-attendant-sphere-light 01: yt-media-face\n"
        "{\n"
        '"classname" "light"\n'
        f'"origin" "{lx} {ly} {lz}"\n'
        f'"light" "{base}"\n'
        f'"_color" "{ar} {ag} {ab}"\n'
        "}"
    ]


def scroom_scene_graph_lights(preset):
    """Baked lights for the embodied old Scroom scene-graph bands."""
    entities = []
    base = int(preset.get("wall_light", 100) * 0.76)

    band_domain = {
        "hls": "presence",
        "ir": "perception",
        "ward-shelf": "director",
        "mid-band": "communication",
        "far-band": "cognition",
    }
    for idx, (band, name, _tex, _frame_tex, x, y, z, _w, _h) in enumerate(
        SCROOM_SCENE_GRAPH_PANES, start=1
    ):
        lx, ly, lz = pane_light_origin(x, y, z, "y", 30)
        r, g, b = DOMAIN_LIGHT_COLOR[band_domain[band]]
        entities.append(
            f"// scroom-scene-light {idx:02d}: {band} {name}\n"
            "{\n"
            '"classname" "light"\n'
            f'"origin" "{lx} {ly} {lz}"\n'
            f'"light" "{base}"\n'
            f'"_color" "{r} {g} {b}"\n'
            "}"
        )

    return entities


def scroom_local_effect_lights(preset):
    """Baked support lights for entity-local effect lenses."""
    entities = []
    base = int(preset.get("wall_light", 100) * 0.62)
    effect_domain = {
        "drift_c": "token",
        "drift_g": "perception",
        "drift_a": "director",
        "drift_r": "music",
    }

    for idx, (name, _tex, frame_tex, x, y, z) in enumerate(SCROOM_LOCAL_EFFECTS, start=1):
        r, g, b = DOMAIN_LIGHT_COLOR[effect_domain[frame_tex]]
        entities.append(
            f"// scroom-local-effect-light {idx:02d}: {name}\n"
            "{\n"
            '"classname" "light"\n'
            f'"origin" "{x} {y - 24} {z}"\n'
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
        + sectioned_brushes("aoa-attendant-sphere", aoa_attendant_sphere_face(preset))
        + sectioned_brushes("aoa-payload-panes", aoa_payload_panes(preset))
        + sectioned_brushes("scroom-scene-graph-bands", scroom_scene_graph_bands(preset))
        + sectioned_brushes("scroom-material-field", scroom_material_field(preset))
        + sectioned_brushes("scroom-room-grid", scroom_room_grid(preset))
        + sectioned_brushes("scroom-local-effect-lenses", scroom_local_effect_lenses(preset))
        + sectioned_brushes("ward-depth-echo-planes", ward_depth_echo_panes(preset))
        + sectioned_brushes("ward-garden-clumps", ward_review_panes(preset))
        + sectioned_brushes("ward-garden-drift-stones", ward_review_drift_paths(preset))
        + sectioned_brushes("source-camera-constellation", source_constellation_panes(preset))
        + sectioned_brushes("ward-scrim-panes", ward_scrim_panes(preset))
        + sectioned_brushes("ward-drift-paths", ward_drift_paths(preset))
    )

    lines.append("{")
    lines.append('"classname" "worldspawn"')
    lines.append(f'"message" "{preset["message"]}"')
    lines.append('"wad" "screwm.wad"')
    lines.append(f'"fog" "{preset["fog"]}"')
    lines.append('"_minlight" "18"')
    lines.append('"_minlight_color" "0.16 0.19 0.22"')
    for brush in worldspawn_brushes:
        lines.append(brush)
    lines.append("}")
    lines.append("")

    lines.append(
        f'{{\n"classname" "info_player_start"\n"origin" "0 0 {FLOOR_Z + 48}"\n"angle" "90"\n}}'
    )
    lines.append("")

    for light in (
        lights(preset)
        + aoa_attendant_sphere_lights(preset)
        + aoa_payload_lights(preset)
        + scroom_scene_graph_lights(preset)
        + scroom_local_effect_lights(preset)
        + ward_review_lights(preset)
        + ward_lights(preset)
        + source_lights(preset)
    ):
        lines.append(light)
        lines.append("")

    return "\n".join(lines)


def compile_map(map_path: Path, output_dir: Path, *, full_vis: bool = False):
    bsp_name = map_path.stem
    vis_cmd = ["vis", str(output_dir / f"{bsp_name}.bsp")]
    if not full_vis:
        vis_cmd.insert(1, "-fast")
    cmds = [
        ["qbsp", str(map_path)],
        ["light", "-extra", "-lit", str(output_dir / f"{bsp_name}.bsp")],
        vis_cmd,
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
    parser.add_argument(
        "--full-vis",
        action="store_true",
        help="Run full vis instead of fast vis; useful for final BSP optimization, not visual iteration.",
    )
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
            compile_map(map_path, output_dir, full_vis=args.full_vis)
            bsp_path = output_dir / f"{map_name}.bsp"
            if bsp_path.exists():
                print(f"  BSP: {bsp_path} ({bsp_path.stat().st_size} bytes)")

    # Also generate the default screwm.map (rnd mode) for backward compat
    if args.mode == "both":
        default_content = generate_map(MODE_PRESETS["rnd"])
        default_path = output_dir / "screwm.map"
        default_path.write_text(default_content)
        if args.compile:
            compile_map(default_path, output_dir, full_vis=args.full_vis)


if __name__ == "__main__":
    main()
