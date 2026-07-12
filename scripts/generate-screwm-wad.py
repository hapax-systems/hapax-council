#!/usr/bin/env python3
"""Generate a Quake WAD2 file with procedural Screwm migration textures.

WAD2 format:
  Header: magic "WAD2", num_entries, dir_offset
  Entry directory: 32 bytes each (offset, disksize, size, type, compression, name[16])
  Texture data: MIPTEX header + 4 mipmap levels + palette
"""

import argparse
import json
import struct
import zlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MEDIA_MOUNT_CONTRACTS_PATH = REPO_ROOT / "config" / "screwm-quake-media-mounts.json"
TEX_SIZE = 64
WARD_COUNT = 36
WARD_CODES = [
    "TOKEN",
    "ALBUM",
    "STREAM",
    "AOAO",
    "REV",
    "ACT",
    "STANCE",
    "GEM",
    "GROUND",
    "IMP",
    "RECR",
    "THINK",
    "PRESS",
    "VAR",
    "HERE",
    "DURF",
    "CODE",
    "BOPIR",
    "BRMIR",
    "EGRESS",
    "BANNER",
    "PRECED",
    "HIST",
    "INSTR",
    "CBIP",
    "CHAT",
    "CHRON",
    "STATE",
    "POLY",
    "QUERY",
    "POSTER",
    "TUFTE",
    "ASCII",
    "SEG",
    "BSYIR",
    "IRDUAL",
]

WARD_TEXTURE_TYPES = [
    "token_path",
    "album_cover",
    "stream_status",
    "aoa_oarb_state",
    "reverie_field",
    "activity_banner",
    "stance_chip",
    "gem_facets",
    "provenance_ticker",
    "impingement_cascade",
    "recruitment_cells",
    "thinking_dot",
    "pressure_bar",
    "variety_log",
    "here_counter",
    "durf_grid",
    "code_diff",
    "hardware_grid",
    "hardware_grid",
    "egress_footer",
    "programme_banner",
    "precedent_ticker",
    "history_corridor",
    "instrument_dashboard",
    "cbip_density",
    "chat_keywords",
    "chronicle_ticker",
    "programme_state",
    "hardware_grid",
    "query_card",
    "poster_field",
    "tufte_bars",
    "ascii_schema",
    "segment_page",
    "hardware_grid",
    "ir_dual",
]

WARD_ACCENT_INDICES = [214, 198, 186, 202, 176]

CAMERA_SOURCE_TEXTURES = [
    ("cam_bop", "BRIOOP", 198),
    ("cam_brm", "BRIORM", 202),
    ("cam_bsy", "BRIOSYN", 186),
    ("cam_cdk", "C920DSK", 214),
    ("cam_crm", "C920RM", 202),
    ("cam_cov", "C920OVH", 214),
]

SPEECH_WAVE_TEXTURES = [
    ("speech_wave", "VOICE", 198),
]

LEGACY_SLOT_TEXTURES = [
    ("slot_aoa", "OARB", 214),
    ("slot_album", "ALBUM", 186),
    ("slot_rev", "REVERIE", 202),
    ("slot_voice", "VOICE", 198),
]

AOA_PANE_TEXTURES = [
    ("aoa_root", "ROOT", 214),
    ("aoa_tri", "TRI", 202),
    ("aoa_data", "DATA", 198),
    ("aoa_glyph", "GLYPH", 186),
    ("aoa_edge", "EDGE", 214),
    ("aoa_lod", "LOD", 202),
    ("aoa_priv", "PRIV", 198),
    ("aoa_src", "SRC", 186),
    ("aoa_comp", "COMP", 214),
    ("aoa_gate", "GATE", 202),
]
AOA_SPHERE_TEXTURES = [
    ("aoa_media_sphere", "MEDIA", 236),
]

LOCAL_EFFECT_TEXTURES = [
    ("fx_mirr", "MIRR", 214, "mirror"),
    ("fx_kale", "KALEI", 186, "kaleidoscope"),
    ("fx_warp", "WARP", 202, "warp"),
    ("fx_fish", "FISH", 214, "fisheye"),
    ("fx_xfrm", "XFRM", 198, "transform"),
    ("fx_disp", "DISP", 186, "displacement"),
    ("fx_dros", "DROST", 214, "droste"),
    ("fx_tunn", "TUNNL", 202, "tunnel"),
    ("fx_tile", "TILE", 198, "tile"),
    ("fx_drif", "DRIFT", 202, "drift"),
    ("fx_brea", "BRETH", 198, "breathing"),
]

TEXTURES = {
    # Legacy texture names remain only as compatibility handles. Their content
    # is now abstract Scroom information-surface material, not stone/metal/sky.
    "city4_2": {
        "color": (4, 4, 6),
        "noise": 0,
        "pattern": "hard_void",
        "palette": "scroom",
        "size": 128,
    },
    "ground1_6": {
        "color": (4, 4, 6),
        "noise": 0,
        "pattern": "hard_void",
        "palette": "scroom",
        "size": 128,
    },
    "sky4": {
        "color": (4, 4, 6),
        "noise": 0,
        "pattern": "hard_void",
        "palette": "scroom",
        "size": 128,
    },
    "metal5_2": {
        "color": (4, 4, 6),
        "noise": 0,
        "pattern": "hard_void",
        "palette": "scroom",
        "size": 128,
    },
    "scroom": {
        "color": (4, 4, 6),
        "noise": 0,
        "pattern": "hard_void",
        "palette": "scroom",
        "size": 128,
    },
    "void_floor": {
        "color": (0, 0, 0),
        "noise": 0,
        "pattern": "hidden_void_shell",
        "palette": "scroom",
        "size": 128,
    },
    "void_ceil": {
        "color": (0, 0, 0),
        "noise": 0,
        "pattern": "hidden_void_shell",
        "palette": "scroom",
        "size": 128,
    },
    "void_wall": {
        "color": (0, 0, 0),
        "noise": 0,
        "pattern": "hidden_void_shell",
        "palette": "scroom",
        "size": 128,
    },
    "skip": {
        "color": (0, 0, 0),
        "noise": 0,
        "pattern": "hidden_void_shell",
        "palette": "scroom",
        "size": 128,
    },
    "geom_mark": {
        "color": (4, 4, 6),
        "noise": 0,
        "pattern": "geometry_signal_mark",
        "palette": "scroom",
        "size": 128,
        "accent": 214,
    },
    "hex_floor": {
        "color": (4, 4, 6),
        "noise": 0,
        "pattern": "geometry_signal_mark",
        "palette": "scroom",
        "size": 128,
        "accent": 214,
    },
    "hex_ceil": {
        "color": (4, 4, 6),
        "noise": 0,
        "pattern": "geometry_signal_mark",
        "palette": "scroom",
        "size": 128,
        "accent": 198,
    },
    "hex_wall": {
        "color": (4, 4, 6),
        "noise": 0,
        "pattern": "geometry_signal_mark",
        "palette": "scroom",
        "size": 128,
        "accent": 186,
    },
    "stipple_floor": {
        "color": (4, 4, 6),
        "noise": 0,
        "pattern": "geometry_signal_mark",
        "palette": "scroom",
        "size": 128,
        "accent": 202,
    },
    "stipple_ceil": {
        "color": (4, 4, 6),
        "noise": 0,
        "pattern": "geometry_signal_mark",
        "palette": "scroom",
        "size": 128,
        "accent": 198,
    },
    "stipple_wall": {
        "color": (4, 4, 6),
        "noise": 0,
        "pattern": "geometry_signal_mark",
        "palette": "scroom",
        "size": 128,
        "accent": 214,
    },
    "cmp_wall": {
        "color": (4, 4, 6),
        "noise": 0,
        "pattern": "compositor_wall",
        "palette": "scroom",
        "size": 256,
    },
    # R&D / Research band handles: procedural signal surfaces, never scenic materials.
    "r_percep": {
        "color": (38, 46, 62),
        "noise": 1,
        "pattern": "signal_panel",
        "palette": "scroom",
        "size": 128,
    },
    "r_cognit": {
        "color": (38, 46, 62),
        "noise": 1,
        "pattern": "signal_panel",
        "palette": "scroom",
        "size": 128,
    },
    "r_comm": {
        "color": (38, 46, 62),
        "noise": 1,
        "pattern": "signal_panel",
        "palette": "scroom",
        "size": 128,
    },
    "r_express": {
        "color": (38, 46, 62),
        "noise": 1,
        "pattern": "signal_panel",
        "palette": "scroom",
        "size": 128,
    },
    "r_ground": {
        "color": (38, 46, 62),
        "noise": 1,
        "pattern": "signal_panel",
        "palette": "scroom",
        "size": 128,
    },
    "s_percep": {
        "color": (34, 44, 62),
        "noise": 1,
        "pattern": "signal_panel",
        "palette": "scroom",
        "size": 128,
    },
    "s_cognit": {
        "color": (34, 44, 62),
        "noise": 1,
        "pattern": "signal_panel",
        "palette": "scroom",
        "size": 128,
    },
    "s_comm": {
        "color": (34, 44, 62),
        "noise": 1,
        "pattern": "signal_panel",
        "palette": "scroom",
        "size": 128,
    },
    "s_express": {
        "color": (34, 44, 62),
        "noise": 1,
        "pattern": "signal_panel",
        "palette": "scroom",
        "size": 128,
    },
    "s_ground": {
        "color": (34, 44, 62),
        "noise": 1,
        "pattern": "signal_panel",
        "palette": "scroom",
        "size": 128,
    },
    # In-scroom drift carriers. These are physical materials, not overlay strokes.
    "drift_c": {"color": (80, 180, 170), "noise": 0, "pattern": "drift_line", "drift": 214},
    "drift_a": {"color": (210, 150, 74), "noise": 0, "pattern": "drift_line", "drift": 198},
    "drift_r": {"color": (205, 82, 120), "noise": 0, "pattern": "drift_line", "drift": 186},
    "drift_g": {"color": (120, 180, 86), "noise": 0, "pattern": "drift_line", "drift": 202},
}


def load_media_mount_contracts(path=MEDIA_MOUNT_CONTRACTS_PATH):
    return json.loads(path.read_text(encoding="utf-8"))


MEDIA_MOUNT_CONTRACTS = load_media_mount_contracts()
MEDIA_MOUNTS_BY_TEXTURE = {
    mount["texture"]: mount for mount in MEDIA_MOUNT_CONTRACTS["mounts"] if "texture" in mount
}
ACTIVE_WARD_TEXTURES = {
    name for name in MEDIA_MOUNTS_BY_TEXTURE if name.startswith("w") and name[1:].isdigit()
}
WARD_ATLAS_MOUNT = MEDIA_MOUNTS_BY_TEXTURE.get("ward_atlas")

if WARD_ATLAS_MOUNT:
    atlas_width, atlas_height = WARD_ATLAS_MOUNT.get("texture_size", [2048, 2304])
    TEXTURES["ward_atlas"] = {
        "color": (36, 46, 56),
        "noise": 0,
        "pattern": "live_media",
        "code": "WARD",
        "accent": 214,
        "width": int(atlas_width),
        "height": int(atlas_height),
    }

for ward_idx in range(1, WARD_COUNT + 1):
    texture_name = f"w{ward_idx:02d}"
    if texture_name not in ACTIVE_WARD_TEXTURES:
        continue
    mount = MEDIA_MOUNTS_BY_TEXTURE.get(texture_name)
    texture_width, texture_height = mount.get("texture_size", [TEX_SIZE, TEX_SIZE])
    TEXTURES[texture_name] = {
        "color": (120, 105, 70),
        "noise": 0,
        "pattern": "live_media",
        "label": ward_idx,
        "code": WARD_CODES[ward_idx - 1],
        "ward_type": WARD_TEXTURE_TYPES[ward_idx - 1],
        "accent": WARD_ACCENT_INDICES[(ward_idx - 1) % len(WARD_ACCENT_INDICES)],
        "width": int(texture_width),
        "height": int(texture_height),
    }

for tex_name, code, accent in CAMERA_SOURCE_TEXTURES:
    mount = MEDIA_MOUNTS_BY_TEXTURE.get(tex_name, {})
    texture_width, texture_height = mount.get("texture_size", [TEX_SIZE, TEX_SIZE])
    TEXTURES[tex_name] = {
        "color": (74, 88, 84),
        "noise": 0,
        "pattern": "source_portal",
        "code": code,
        "accent": accent,
        "width": int(texture_width),
        "height": int(texture_height),
    }

for tex_name, code, accent in SPEECH_WAVE_TEXTURES:
    mount = MEDIA_MOUNTS_BY_TEXTURE.get(tex_name, {})
    texture_width, texture_height = mount.get("texture_size", [512, 128])
    TEXTURES[tex_name] = {
        "color": (46, 70, 82),
        "noise": 0,
        "pattern": "live_media",
        "code": code,
        "accent": accent,
        "width": int(texture_width),
        "height": int(texture_height),
    }

for tex_name, code, accent in LEGACY_SLOT_TEXTURES:
    TEXTURES[tex_name] = {
        "color": (62, 76, 72),
        "noise": 0,
        "pattern": "legacy_slot",
        "code": code,
        "accent": accent,
    }

for tex_name, code, accent in AOA_PANE_TEXTURES:
    TEXTURES[tex_name] = {
        "color": (56, 70, 74),
        "noise": 0,
        "pattern": "aoa_pane",
        "code": code,
        "accent": accent,
    }

for tex_name, code, accent in AOA_SPHERE_TEXTURES:
    mount = MEDIA_MOUNTS_BY_TEXTURE.get("aoa_media_sphere", {})
    texture_width, texture_height = mount.get("texture_size", [256, 128])
    TEXTURES[tex_name] = {
        "color": (76, 68, 74),
        "noise": 0,
        "pattern": "aoa_sphere",
        "code": code,
        "accent": accent,
        "width": int(texture_width),
        "height": int(texture_height),
    }

for tex_name, code, accent, effect in LOCAL_EFFECT_TEXTURES:
    TEXTURES[tex_name] = {
        "color": (52, 60, 64),
        "noise": 0,
        "pattern": "effect_lens",
        "code": code,
        "accent": accent,
        "effect": effect,
    }


TINY_FONT = {
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"),
    "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"),
    "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "111"),
    "A": ("111", "101", "111", "101", "101"),
    "B": ("110", "101", "110", "101", "110"),
    "C": ("111", "100", "100", "100", "111"),
    "D": ("110", "101", "101", "101", "110"),
    "E": ("111", "100", "110", "100", "111"),
    "F": ("111", "100", "110", "100", "100"),
    "G": ("111", "100", "101", "101", "111"),
    "H": ("101", "101", "111", "101", "101"),
    "I": ("111", "010", "010", "010", "111"),
    "J": ("001", "001", "001", "101", "111"),
    "K": ("101", "101", "110", "101", "101"),
    "L": ("100", "100", "100", "100", "111"),
    "M": ("101", "111", "111", "101", "101"),
    "N": ("101", "111", "111", "111", "101"),
    "O": ("111", "101", "101", "101", "111"),
    "P": ("111", "101", "111", "100", "100"),
    "Q": ("111", "101", "101", "111", "001"),
    "R": ("111", "101", "111", "110", "101"),
    "S": ("111", "100", "111", "001", "111"),
    "T": ("111", "010", "010", "010", "010"),
    "U": ("101", "101", "101", "101", "111"),
    "V": ("101", "101", "101", "101", "010"),
    "W": ("101", "101", "111", "111", "101"),
    "X": ("101", "101", "010", "101", "101"),
    "Y": ("101", "101", "010", "010", "010"),
    "Z": ("111", "001", "010", "100", "111"),
}


def digit_is_lit(char, col, row):
    """Return true when the tiny ward-panel font lights a cell."""
    glyph = TINY_FONT.get(char)
    if not glyph:
        return False
    return glyph[row][col] == "1"


def text_pixel_lit(x, y, text, start_x, start_y, scale):
    """Return true when a small all-caps ward label covers this pixel."""
    glyph_w = 3 * scale
    glyph_h = 5 * scale
    gap = scale

    for char_idx, char in enumerate(text):
        glyph_x = x - start_x - char_idx * (glyph_w + gap)
        glyph_y = y - start_y
        if 0 <= glyph_x < glyph_w and 0 <= glyph_y < glyph_h:
            col = glyph_x // scale
            row = glyph_y // scale
            return digit_is_lit(char, col, row)
    return False


def line_near(x, y, x1, y1, x2, y2, radius=1.35):
    """Return true when a pixel is near a 2D segment."""
    dx = x2 - x1
    dy = y2 - y1
    length_sq = dx * dx + dy * dy
    if length_sq <= 0:
        return (x - x1) * (x - x1) + (y - y1) * (y - y1) <= radius * radius
    t = ((x - x1) * dx + (y - y1) * dy) / length_sq
    t = max(0.0, min(1.0, t))
    px = x1 + t * dx
    py = y1 + t * dy
    return (x - px) * (x - px) + (y - py) * (y - py) <= radius * radius


def lerp_color(a, b, t):
    """Interpolate two RGB colors."""
    return tuple(int(a[idx] + (b[idx] - a[idx]) * t) for idx in range(3))


def build_scroom_palette():
    """Palette for abstract dynamic information surfaces.

    The bands intentionally encode signal roles rather than material identity:
    dark substrate, cool alignment, magenta drift, amber attention, acid
    liveness, and white-hot terminal glyphs.
    """
    bands = (
        (0, 48, (4, 6, 12), (19, 21, 34)),
        (48, 88, (20, 24, 42), (52, 44, 76)),
        (88, 128, (22, 68, 92), (86, 214, 220)),
        (128, 168, (72, 34, 78), (226, 82, 174)),
        (168, 208, (88, 58, 18), (246, 184, 70)),
        (208, 236, (38, 82, 62), (142, 248, 170)),
        (236, 256, (186, 196, 202), (255, 248, 218)),
    )
    palette = []
    for idx in range(256):
        if idx == 0:
            palette.extend((0, 0, 0))
            continue
        for start, end, left, right in bands:
            if start <= idx < end:
                span = max(1, end - start - 1)
                t = (idx - start) / span
                wave = 0.06 if idx % 2 else -0.02
                color = lerp_color(left, right, max(0.0, min(1.0, t + wave)))
                palette.extend(color)
                break
    return bytes(palette)


def build_monochrome_palette(color):
    """Single-hue palette for legacy placeholders and media mount canaries."""
    palette = []
    for i in range(256):
        t = i / 255.0
        r = max(0, min(255, int(color[0] * (0.3 + t * 0.7))))
        g = max(0, min(255, int(color[1] * (0.3 + t * 0.7))))
        b = max(0, min(255, int(color[2] * (0.3 + t * 0.7))))
        palette.extend([r, g, b])
    return bytes(palette)


def ward_symbol_index(x, y, label, ward_type, accent):
    """Ward-specific glyph grammar from the pre-Quake Screwm inventory."""
    dark_accent = max(58, accent - 118)
    mid_accent = max(90, accent - 76)

    if ward_type == "token_path":
        if line_near(x, y, 24, 52, 32, 34, 1.8) or line_near(x, y, 32, 34, 40, 12, 1.8):
            return accent
        if abs(x - 32) <= 2 and 14 <= y <= 51:
            return mid_accent
        if (x - 40) * (x - 40) + (y - 12) * (y - 12) <= 18:
            return 245
        if (x - 24) * (x - 24) + (y - 52) * (y - 52) <= 22:
            return dark_accent

    elif ward_type == "album_cover":
        if 13 <= x <= 50 and 12 <= y <= 48:
            if x in (13, 14, 49, 50) or y in (12, 13, 47, 48):
                return accent
            if line_near(x, y, 16, 45, 47, 15, 1.2):
                return 245
            if (x + y + label) % 11 < 2:
                return mid_accent

    elif ward_type == "stream_status":
        if y in (17, 18, 30, 31, 43, 44) and 8 <= x <= 56:
            return accent
        if x in (12, 18, 24) and 14 <= y <= 47:
            return 245
        if 30 <= x <= 54 and y in (22, 36, 50):
            return mid_accent

    elif ward_type == "aoa_oarb_state":
        edges = [
            (32, 9, 12, 51),
            (12, 51, 52, 51),
            (52, 51, 32, 9),
            (22, 30, 42, 30),
            (22, 30, 32, 51),
            (42, 30, 32, 51),
            (27, 40, 37, 40),
        ]
        if any(line_near(x, y, *edge, radius=1.25) for edge in edges):
            return accent
        if (x - 32) * (x - 32) + (y - 35) * (y - 35) <= 10:
            return 245

    elif ward_type == "reverie_field":
        dx = x - 32
        dy = y - 32
        ring = dx * dx + dy * dy
        if 260 <= ring <= 340 or 590 <= ring <= 710:
            return accent
        if (x * 7 + y * 13 + label * 17) % 31 < 4:
            return mid_accent

    elif ward_type == "activity_banner":
        if 8 <= x <= 56 and y in (14, 15, 48, 49):
            return accent
        if 13 <= y <= 25 and 12 <= x <= 52:
            return mid_accent
        if x in (18, 27, 36, 45) and 30 <= y <= 45:
            return 245

    elif ward_type == "stance_chip":
        if 12 <= x <= 52 and 18 <= y <= 44:
            if x in (12, 13, 51, 52) or y in (18, 19, 43, 44):
                return accent
            if abs(x - 26) <= 1 or abs(y - 31) <= 1:
                return 245

    elif ward_type == "gem_facets":
        facets = [(32, 8, 52, 32), (52, 32, 32, 56), (32, 56, 12, 32), (12, 32, 32, 8)]
        if any(line_near(x, y, *edge, radius=1.2) for edge in facets):
            return accent
        if line_near(x, y, 12, 32, 52, 32, 1.0) or line_near(x, y, 32, 8, 32, 56, 1.0):
            return 245

    elif ward_type in {"provenance_ticker", "precedent_ticker", "chronicle_ticker"}:
        if y in (9, 10, 53, 54) and 5 <= x <= 59:
            return accent
        if y in (18, 31, 44) and 6 <= x <= 58:
            return mid_accent
        if 14 <= y <= 48 and (y + label) % 5 == 0:
            return dark_accent
        if 14 <= y <= 48 and (x + label * 7) % 16 < 7 and y in (23, 35, 47):
            return 245
        for offset in (0, 18, 36, 54):
            if line_near(x, y, offset, 50, offset + 10, 32, 1.0) or line_near(
                x, y, offset + 10, 32, offset, 14, 1.0
            ):
                return accent

    elif ward_type == "impingement_cascade":
        for row in range(5):
            y0 = 13 + row * 8
            if y0 <= y <= y0 + 4 and 10 <= x <= 54:
                fill = 10 + row * 8 + (label % 7)
                return accent if x <= fill else dark_accent

    elif ward_type == "recruitment_cells":
        for col in range(3):
            x0 = 10 + col * 15
            if x0 <= x <= x0 + 11 and 17 <= y <= 45:
                if x in (x0, x0 + 11) or y in (17, 45):
                    return accent
                if (x + y + col) % 6 < 2:
                    return mid_accent

    elif ward_type == "thinking_dot":
        r = (x - 32) * (x - 32) + (y - 32) * (y - 32)
        if 90 <= r <= 122 or 190 <= r <= 230:
            return accent
        if r <= 42:
            return 245

    elif ward_type == "pressure_bar":
        if 12 <= x <= 52 and 28 <= y <= 36:
            if x in (12, 52) or y in (28, 36):
                return 245
            return accent if x < 40 else mid_accent
        if x % 5 == 0 and 24 <= y <= 40:
            return dark_accent

    elif ward_type == "variety_log":
        for col in range(6):
            x0 = 8 + col * 9
            if x0 <= x <= x0 + 6 and 21 <= y <= 42:
                return accent if (col + label) % 2 else mid_accent

    elif ward_type == "here_counter":
        if (x - 23) * (x - 23) + (y - 30) * (y - 30) <= 48:
            return accent
        if (x - 42) * (x - 42) + (y - 30) * (y - 30) <= 48:
            return mid_accent
        if 21 <= x <= 44 and 39 <= y <= 43:
            return 245

    elif ward_type == "durf_grid":
        if 10 <= x <= 54 and 10 <= y <= 54 and (x % 8 in (0, 1) or y % 8 in (0, 1)):
            return accent
        if (x + y + label) % 13 == 0:
            return 245

    elif ward_type == "code_diff":
        if 10 <= x <= 55 and y in (14, 22, 30, 38, 46):
            return accent if y in (14, 30, 46) else mid_accent
        if x in (12, 16) and 12 <= y <= 48:
            return 245

    elif ward_type == "hardware_grid":
        if 11 <= x <= 53 and 13 <= y <= 47:
            if x in (11, 53) or y in (13, 47):
                return accent
            if x % 7 == 0 or y % 7 == 0:
                return dark_accent
            if (x * y + label) % 37 < 3:
                return 245

    elif ward_type in {"egress_footer", "programme_banner", "segment_page"}:
        if 9 <= x <= 55 and y in (18, 19, 44, 45):
            return accent
        if 13 <= x <= 51 and 24 <= y <= 38:
            return mid_accent
        if x in (17, 24, 31, 38, 45) and 24 <= y <= 38:
            return 245

    elif ward_type == "history_corridor":
        if 12 <= x <= 52 and y in (14, 24, 34, 44, 54):
            return accent
        if x in (18, 31, 44) and 14 <= y <= 54:
            return mid_accent

    elif ward_type == "instrument_dashboard":
        if x in (14, 32, 50) and 12 <= y <= 52:
            return dark_accent
        if y in (18, 32, 46) and 10 <= x <= 54:
            return dark_accent
        if line_near(x, y, 12, 48, 52, 18, 1.2):
            return accent
        if (x - 46) * (x - 46) + (y - 20) * (y - 20) <= 10:
            return 245

    elif ward_type in {"cbip_density", "ir_dual"}:
        if ward_type == "ir_dual" and (abs(x - 24) <= 1 or abs(x - 40) <= 1):
            return 245
        if 10 <= x <= 54 and 12 <= y <= 52 and (x * 5 + y * 11 + label) % 17 < 5:
            return accent
        if (x + y) % 9 == 0:
            return mid_accent

    elif ward_type == "chat_keywords":
        for cx, cy in ((22, 24), (42, 24), (30, 42)):
            if (x - cx) * (x - cx) + (y - cy) * (y - cy) <= 38:
                return accent

    elif ward_type == "programme_state":
        for row in range(3):
            y0 = 16 + row * 12
            if 12 <= x <= 52 and y0 <= y <= y0 + 7:
                return accent if row == 1 else mid_accent

    elif ward_type == "query_card":
        if (x - 32) * (x - 32) + (y - 25) * (y - 25) <= 92 and x > 26:
            return accent
        if 30 <= x <= 34 and 39 <= y <= 44:
            return 245

    elif ward_type == "poster_field":
        if line_near(x, y, 10, 50, 54, 14, 1.4):
            return accent
        if 12 <= x <= 52 and y in (18, 27, 36, 45):
            return mid_accent

    elif ward_type == "tufte_bars":
        for col, height in enumerate((20, 34, 13, 42, 27)):
            x0 = 14 + col * 8
            if x0 <= x <= x0 + 4 and 52 - height <= y <= 52:
                return accent if col % 2 else mid_accent

    elif ward_type == "ascii_schema":
        if x in (14, 32, 50) and 14 <= y <= 50:
            return accent
        if y in (14, 32, 50) and 14 <= x <= 50:
            return accent
        if (x, y) in ((23, 23), (41, 23), (23, 41), (41, 41)):
            return 245

    elif ward_type == "scope_wave":
        wave_y = 32 + int(10 * __import__("math").sin((x + label) * 0.32))
        if abs(y - wave_y) <= 1 and 8 <= x <= 56:
            return accent
        if y in (20, 32, 44) and 10 <= x <= 54:
            return dark_accent

    return None


def ward_panel_index(x, y, label, code, ward_type):
    """Optional legacy/generated ward modulation; not a default ward identity."""
    accent = WARD_ACCENT_INDICES[(int(label) - 1) % len(WARD_ACCENT_INDICES)]

    if x < 2 or y < 2 or x >= TEX_SIZE - 2 or y >= TEX_SIZE - 2:
        return 245
    if x < 5 or y < 5 or x >= TEX_SIZE - 5 or y >= TEX_SIZE - 5:
        return accent
    if y in (12, 13, 48, 49):
        return accent
    if x in (12, 13, 50, 51):
        return max(72, accent - 96)

    # Diagonal scan-strata give every pane motion-read even as a baked texture.
    base = 18 + ((x * 3 + y * 5 + label * 11) % 18)
    if (x + y + label * 3) % 17 == 0:
        base = max(118, accent - 74)

    symbol = ward_symbol_index(x, y, label, ward_type, accent)
    if symbol is not None:
        return symbol

    text = f"{label:02d}"
    scale = 2
    start_x = 7
    start_y = 7
    digit_w = 3 * scale
    gap = 2
    for digit_idx, char in enumerate(text):
        glyph_x = x - start_x - digit_idx * (digit_w + gap)
        glyph_y = y - start_y
        if 0 <= glyph_x < digit_w and 0 <= glyph_y < 5 * scale:
            col = glyph_x // scale
            row = glyph_y // scale
            if digit_is_lit(char, col, row):
                return 245
            if (glyph_x % scale in (0, scale - 1)) or (glyph_y % scale in (0, scale - 1)):
                return 10

    short_code = code[:7].upper()
    code_scale = 2
    code_width = len(short_code) * 3 * code_scale + max(0, len(short_code) - 1) * code_scale
    if text_pixel_lit(x, y, short_code, (TEX_SIZE - code_width) // 2, 43, code_scale):
        return 245

    return base


def source_portal_index(x, y, code, accent, width=TEX_SIZE, height=TEX_SIZE):
    """Borderless quiet fallback for a camera/source live texture.

    A stale camera must not become a fake framed plaque. Until live pixels
    arrive, the receiver only carries a dim source-bound drift/noise field.
    """
    drift_a = abs(((x * 5 + y * 2 + len(code) * 17) % 233) - 116)
    drift_b = abs(((x - y * 3 + accent) % 251) - 125)
    if drift_a < 1:
        return max(72, accent - 128)
    if drift_b < 1:
        return max(58, accent - 150)
    if (x * 13 + y * 7 + len(code) * 19) % 787 == 0:
        return max(96, accent - 96)
    return 0 if (x + y + len(code)) % 5 else 1


def legacy_slot_index(x, y, code, accent):
    """Large Sierpinski-era content slot texture with baked identity."""
    if x < 2 or y < 2 or x >= TEX_SIZE - 2 or y >= TEX_SIZE - 2:
        return 245
    if x < 5 or y < 5 or x >= TEX_SIZE - 5 or y >= TEX_SIZE - 5:
        return accent
    if y in (9, 10, 53, 54):
        return max(72, accent - 96)
    if x in (9, 10, 53, 54):
        return max(86, accent - 82)
    if y % 6 in (0, 1):
        return max(48, accent - 128)
    if (x * 3 + y * 7 + len(code) * 5) % 29 < 3:
        return max(110, accent - 52)

    short_code = code[:7].upper()
    scale = 3 if len(short_code) <= 5 else 2
    text_width = len(short_code) * 3 * scale + max(0, len(short_code) - 1) * scale
    if text_pixel_lit(x, y, short_code, (TEX_SIZE - text_width) // 2, 24, scale):
        return 245

    # A quiet center trace keeps the slot from reading as a blank label tile.
    dx = abs(x - 32)
    dy = abs(y - 32)
    if dx <= 1 or dy <= 1:
        return max(82, accent - 108)
    if dx + dy in (20, 21, 22):
        return max(96, accent - 80)

    return 22 + ((x * 11 + y * 5 + len(code) * 13) % 22)


def aoa_pane_index(x, y, code, accent):
    """AoA pane-local payload texture from the current Scroom tetrix contract."""
    dark_accent = max(62, accent - 116)
    mid_accent = max(92, accent - 72)

    if x < 2 or y < 2 or x >= TEX_SIZE - 2 or y >= TEX_SIZE - 2:
        return 245
    if x < 5 or y < 5 or x >= TEX_SIZE - 5 or y >= TEX_SIZE - 5:
        return accent

    # Pane-local triangular mask: this is content bound to the AoA volume,
    # not a free floating screen tile.
    edges = (
        (32, 9, 12, 52),
        (12, 52, 52, 52),
        (52, 52, 32, 9),
        (22, 31, 42, 31),
        (22, 31, 32, 52),
        (42, 31, 32, 52),
    )
    if any(line_near(x, y, *edge, radius=1.25) for edge in edges):
        return accent

    # Sparse pane diagnostics: LOD/privacy/source gates from the current
    # AoA pane binding metadata.
    if y in (15, 27, 39, 51) and 10 <= x <= 54:
        return mid_accent
    if x in (18, 32, 46) and 18 <= y <= 50:
        return dark_accent
    if (x * 5 + y * 9 + len(code) * 17) % 43 < 4:
        return 245

    short_code = code[:5].upper()
    scale = 2
    text_width = len(short_code) * 3 * scale + max(0, len(short_code) - 1) * scale
    if text_pixel_lit(x, y, short_code, (TEX_SIZE - text_width) // 2, 24, scale):
        return 245

    dx = x - 32
    dy = y - 35
    ring = dx * dx + dy * dy
    if 280 <= ring <= 360:
        return mid_accent

    return 20 + ((x * 7 + y * 13 + len(code) * 11) % 24)


def aoa_sphere_index(x, y, code, accent, width=TEX_SIZE, height=TEX_SIZE):
    """Attendant sphere/YT media-face texture for the central AoA."""
    dark_accent = max(120, accent - 90)
    mid_accent = max(172, accent - 46)
    cx = width // 2
    cy = height // 2
    radius_px = max(1, min(width, height) // 2)
    dx = (x - cx) / radius_px
    dy = (y - cy) / radius_px
    radius = dx * dx + dy * dy

    if x < 2 or y < 2 or x >= width - 2 or y >= height - 2:
        return 245
    if 0.80 <= radius <= 1.02:
        return 245 if (x + y) % 3 == 0 else accent
    if 0.42 <= radius <= 0.52 or 0.14 <= radius <= 0.20:
        return 245 if (x * y) % 5 == 0 else mid_accent
    if radius > 1.02:
        return 8 + ((x * 5 + y * 11) % 10)

    # Media identity is intentionally baked as mount provenance, not UI chrome.
    scale = 4 if width <= 256 else 8
    text_width = len(code[:5]) * 3 * scale + max(0, len(code[:5]) - 1) * scale
    if text_pixel_lit(x, y, code[:5].upper(), (width - text_width) // 2, cy - 2 * scale, scale):
        return 245
    if y % max(7, height // 36) in (0, 1) and radius < 0.86:
        return dark_accent
    if abs(x - cx) <= 1 or abs(y - cy) <= 1:
        return accent
    if (x * 7 + y * 13) % 31 < 4:
        return 245
    if radius < 0.78 and (x * 3 + y * 5) % 11 < 3:
        return mid_accent

    return 86 + ((x * 9 + y * 5 + len(code) * 17) % 58)


def live_media_placeholder_index(x, y, code, accent, width=TEX_SIZE, height=TEX_SIZE):
    """Borderless quiet fallback for a runtime-replaced media texture."""
    drift_a = abs(((x * 7 + y * 3 + len(code) * 11) % 257) - 128)
    drift_b = abs(((x * 2 - y * 5 + accent) % 263) - 131)
    if drift_a < 1:
        return max(78, accent - 126)
    if drift_b < 1:
        return max(58, accent - 154)
    if (x * 11 + y * 5 + len(code) * 23) % 997 == 0:
        return max(116, accent - 74)
    return 0 if (x * 3 + y + len(code)) % 7 else 1


def effect_lens_index(x, y, code, accent, effect):
    """Entity-local spatial effect lens texture from scene_quad.wgsl."""
    dark_accent = max(60, accent - 116)
    mid_accent = max(92, accent - 74)

    if x < 2 or y < 2 or x >= TEX_SIZE - 2 or y >= TEX_SIZE - 2:
        return 245
    if x < 5 or y < 5 or x >= TEX_SIZE - 5 or y >= TEX_SIZE - 5:
        return accent
    if x in (12, 13, 50, 51) or y in (12, 13, 50, 51):
        return dark_accent

    dx = x - 32
    dy = y - 32
    radius = dx * dx + dy * dy
    if 540 <= radius <= 720:
        return mid_accent

    if effect == "mirror":
        if x in (31, 32) and 12 <= y <= 52:
            return accent
        if abs((63 - x) - y) <= 1:
            return mid_accent
    elif effect == "kaleidoscope":
        for edge in ((32, 8, 12, 52), (32, 8, 52, 52), (12, 52, 52, 52), (32, 8, 32, 52)):
            if line_near(x, y, *edge, radius=1.1):
                return accent
    elif effect == "warp":
        wave_y = 32 + int(8 * __import__("math").sin(x * 0.32))
        if abs(y - wave_y) <= 1:
            return accent
        if y % 11 in (0, 1):
            return dark_accent
    elif effect == "fisheye":
        if 140 <= radius <= 210:
            return accent
        if radius <= 52:
            return 245
    elif effect == "transform":
        if line_near(x, y, 17, 45, 47, 17, 1.3) or line_near(x, y, 17, 17, 47, 45, 1.3):
            return accent
        if x in (19, 45) or y in (19, 45):
            return mid_accent
    elif effect == "displacement":
        if (x * 7 + y * 13) % 17 < 4:
            return accent
        if (x + y) % 9 == 0:
            return 245
    elif effect == "droste":
        if 120 <= radius <= 170 or 300 <= radius <= 360 or 560 <= radius <= 630:
            return accent
    elif effect == "tunnel":
        angle_band = (abs(dx) + abs(dy)) % 12
        if angle_band < 2 and radius > 72:
            return accent
        if radius <= 36:
            return 245
    elif effect == "tile":
        if x % 16 in (0, 1) or y % 16 in (0, 1):
            return accent
        if (x // 16 + y // 16) % 2 == 0:
            return mid_accent
    elif effect == "drift":
        if (x + y) % 13 < 2 or (x * 3 - y * 2) % 19 < 3:
            return accent
    elif effect == "breathing":
        if 180 <= radius <= 240 or 420 <= radius <= 500:
            return accent
        if radius <= 72:
            return mid_accent

    short_code = code[:5].upper()
    scale = 2
    text_width = len(short_code) * 3 * scale + max(0, len(short_code) - 1) * scale
    if text_pixel_lit(x, y, short_code, (TEX_SIZE - text_width) // 2, 42, scale):
        return 245

    return 20 + ((x * 11 + y * 7 + len(effect) * 13) % 24)


def generate_pixel_data(
    color,
    noise,
    width,
    height,
    seed=0,
    pattern="void_substrate",
    label=0,
    code="",
    ward_type="",
    drift=0,
    accent=0,
    effect="",
    palette_mode="monochrome",
):
    """Generate procedural Scroom information-surface texture data."""
    import random

    random.seed(seed)
    pixels = bytearray()
    palette = (
        build_scroom_palette() if palette_mode == "scroom" else build_monochrome_palette(color)
    )

    for y in range(height):
        for x in range(width):
            base = 140

            if pattern == "stone_blocks":
                row = y // 16
                col_offset = 16 if row % 2 else 0
                mortar_h = y % 16 < 2
                mortar_v = (x + col_offset) % 32 < 2
                if mortar_h or mortar_v:
                    base = 40
                else:
                    block_id = row * 4 + ((x + col_offset) // 32)
                    random.seed(seed + block_id * 97)
                    base = 160 + random.randint(-40, 40)

            elif pattern == "worn_stone":
                base = 80 + random.randint(-15, 15)
                if (x + y * 3) % 47 < 2:
                    base -= 50

            elif pattern == "dark_ceiling":
                base = 35 + random.randint(-8, 8)

            elif pattern == "brushed_metal":
                grain = (x * 7 + seed) % 11
                base = 170 + grain - 5 + random.randint(-10, 10)

            elif pattern == "carved_stone":
                base = 118 + random.randint(-18, 18)
                if x % 24 < 2 or y % 24 < 2:
                    base -= 44
                if (x * 3 + y * 5 + seed) % 61 < 3:
                    base += 24

            elif pattern == "metal_grate":
                base = 105 + random.randint(-18, 18)
                if x % 16 < 2 or y % 16 < 2:
                    base = 172 + random.randint(-14, 14)
                if (x + y) % 32 < 3:
                    base -= 34

            elif pattern == "dark_ornate":
                base = 82 + random.randint(-15, 15)
                arch = abs((x % 32) - 16) + abs((y % 32) - 16)
                if arch < 8:
                    base += 38
                if x % 32 < 2 or y % 32 < 2:
                    base -= 32

            elif pattern == "polished_stone":
                base = 126 + random.randint(-14, 14)
                if y % 12 < 2:
                    base -= 24
                if (x * 5 + y + seed) % 79 < 4:
                    base += 34

            elif pattern == "void_substrate":
                base = random.randint(0, 2)
                if (x * 17 + y * 29 + seed) % 233 < 3:
                    base = 4 + ((x + y + seed) % 4)
                if (x * 7 + y * 13 + seed) % 521 == 0:
                    base = 214

            elif pattern == "hard_void":
                # Hard reset for the room substrate: sealed BSP should read as
                # absence until a declared ward, AoA, drift line, or live
                # receiver claims the visual field.
                base = 0

            elif pattern == "hidden_void_shell":
                # Compile-time BSP carrier only. Floor and ceiling visibility is
                # generated by Hapax world geometry, not this WAD texture.
                base = 0

            elif pattern == "geometry_signal_mark":
                # Luminous implementation handle. The visible hex/stipple
                # pattern is still created by brush geometry; these pixels
                # only give the grid/dot carrier a restrained signal face.
                accent_idx = int(accent) if accent else 214
                dim_idx = 8 + (accent_idx % 12)
                mid_idx = 48 + (accent_idx % 28)
                rim = min(x, y, width - 1 - x, height - 1 - y)
                shimmer = abs(((x * 5 + y * 3 + seed) % 127) - 63)
                thread_a = abs(((x * 2 + y + seed) % 64) - 32)
                thread_b = abs(((x - y * 2 + seed) % 73) - 36)
                base = 0
                if rim <= 1:
                    base = mid_idx if (x + y + seed) % 3 == 0 else dim_idx
                elif thread_a <= 1 or thread_b <= 1:
                    base = accent_idx if shimmer < 4 else mid_idx
                elif thread_a <= 2 or thread_b <= 2 or shimmer <= 1:
                    base = mid_idx
                elif (x * 11 + y * 7 + seed) % 263 == 0:
                    base = accent_idx

            elif pattern == "scroom":
                base = random.randint(0, 2)
                diag_a = abs(((x + y * 2) % 96) - 48)
                diag_b = abs(((x * 2 - y) % 96) - 48)
                if diag_a < 1:
                    base = 10
                elif diag_b < 1:
                    base = 12
                elif x % 32 == 0 or y % 32 == 0:
                    base = 4
                elif (x * 7 + y * 11 + seed) % 149 < 3:
                    base = 214

            elif pattern == "compositor_floor":
                # Dark walkable signal field: enough albedo for room volume,
                # with sparse path rhythm. This is not scenic material.
                base = 52
                path_a = line_near(
                    x, y, width * 0.12, height * 0.82, width * 0.48, height * 0.58, 1.4
                )
                path_b = line_near(
                    x, y, width * 0.48, height * 0.58, width * 0.82, height * 0.30, 1.4
                )
                if path_a or path_b:
                    base = 132
                elif abs(((x * 2 + y + seed) % 127) - 63) < 1:
                    base = 88
                elif (x * 7 + y * 11 + seed) % 389 < 2:
                    base = 204

            elif pattern == "compositor_ceiling":
                # Overhead canopy signal: visible height without wallpaper.
                # Only broad seams and rare glints are baked; moving light does
                # the expressive work.
                base = 42
                if y in (height // 3, (height * 2) // 3):
                    base = 66
                elif x in (0, width - 1):
                    base = 58

            elif pattern == "compositor_wall":
                # Boundary receiver: visible enclosure without fourth-wall
                # content. The sparse seams are orientation cues, not a grid.
                base = 44
                vertical = x in (0, width - 1)
                horizon = y in (height // 3, (height * 2) // 3)
                if vertical:
                    base = 62
                elif horizon:
                    base = 56

            elif pattern == "signal_panel":
                base = 8 + random.randint(0, 5)
                if x % 32 == 0 or y % 32 == 0:
                    base = 86
                if (x + y) % 41 < 2:
                    base = 136
                if (x * 3 - y * 5 + seed) % 67 < 3:
                    base = 178
                if (x * 11 + y * 7 + seed) % 191 == 0:
                    base = 241

            elif pattern == "drift_line":
                drift_idx = int(drift) if drift else 206
                edge = min(x, y, width - 1 - x, height - 1 - y)
                if edge < 2:
                    base = 245
                elif x in (31, 32) or y in (31, 32):
                    base = drift_idx
                elif (x * 5 + y * 3 + seed) % 23 < 5:
                    base = max(120, drift_idx - 34)
                else:
                    base = max(76, drift_idx - 70)

            elif pattern == "ward_panel":
                pixels.append(ward_panel_index(x, y, int(label), str(code), str(ward_type)))
                continue

            elif pattern == "source_portal":
                pixels.append(
                    source_portal_index(
                        x,
                        y,
                        str(code),
                        int(accent) if accent else 214,
                        width,
                        height,
                    )
                )
                continue

            elif pattern == "legacy_slot":
                pixels.append(legacy_slot_index(x, y, str(code), int(accent) if accent else 214))
                continue

            elif pattern == "aoa_pane":
                pixels.append(aoa_pane_index(x, y, str(code), int(accent) if accent else 214))
                continue

            elif pattern == "aoa_sphere":
                pixels.append(
                    aoa_sphere_index(
                        x,
                        y,
                        str(code),
                        int(accent) if accent else 214,
                        width,
                        height,
                    )
                )
                continue

            elif pattern == "live_media":
                pixels.append(
                    live_media_placeholder_index(
                        x,
                        y,
                        str(code),
                        int(accent) if accent else 214,
                        width,
                        height,
                    )
                )
                continue

            elif pattern == "effect_lens":
                pixels.append(
                    effect_lens_index(
                        x,
                        y,
                        str(code),
                        int(accent) if accent else 214,
                        str(effect),
                    )
                )
                continue

            # Add surface noise
            random.seed(seed + y * width + x)
            base += random.randint(-noise, noise)
            min_index = 0 if palette_mode == "scroom" else 10
            idx = max(min_index, min(245, base))
            pixels.append(idx)

    return bytes(pixels), bytes(palette)


def make_miptex(name, width, height, pixels, palette):
    """Create MIPTEX structure with 4 mipmap levels."""
    name_bytes = name.encode("ascii")[:15].ljust(16, b"\x00")

    mip0 = pixels
    mip1 = bytearray()
    for y in range(0, height, 2):
        for x in range(0, width, 2):
            mip1.append(pixels[y * width + x])
    mip1 = bytes(mip1)

    mip2 = bytearray()
    for y in range(0, height, 4):
        for x in range(0, width, 4):
            mip2.append(pixels[y * width + x])
    mip2 = bytes(mip2)

    mip3 = bytearray()
    for y in range(0, height, 8):
        for x in range(0, width, 8):
            mip3.append(pixels[y * width + x])
    mip3 = bytes(mip3)

    header_size = 40
    off0 = header_size
    off1 = off0 + len(mip0)
    off2 = off1 + len(mip1)
    off3 = off2 + len(mip2)

    header = struct.pack(
        "<16sII4I",
        name_bytes,
        width,
        height,
        off0,
        off1,
        off2,
        off3,
    )

    return header + mip0 + mip1 + mip2 + mip3


def texture_seed(name):
    """Return a deterministic texture seed across Python processes."""
    return zlib.crc32(name.encode("ascii")) & 0xFFFFFFFF


def write_wad(textures_data, output_path):
    """Write WAD2 file."""
    entries = []
    data_parts = []
    data_offset = 12

    for name, (miptex, _palette) in textures_data.items():
        entries.append(
            {
                "name": name,
                "offset": data_offset,
                "size": len(miptex),
            }
        )
        data_parts.append(miptex)
        data_offset += len(miptex)

    dir_offset = data_offset

    with open(output_path, "wb") as f:
        f.write(b"WAD2")
        f.write(struct.pack("<ii", len(entries), dir_offset))

        for part in data_parts:
            f.write(part)

        for entry in entries:
            name_bytes = entry["name"].encode("ascii")[:15].ljust(16, b"\x00")
            f.write(
                struct.pack(
                    "<iiiBBh16s",
                    entry["offset"],
                    entry["size"],
                    entry["size"],
                    0x44,
                    0,
                    0,
                    name_bytes,
                )
            )


def main():
    parser = argparse.ArgumentParser(description="Generate Screwm Quake WAD2 textures")
    parser.add_argument(
        "--no-deploy",
        action="store_true",
        help="only write assets/quake/maps/screwm.wad; do not copy into ~/.darkplaces",
    )
    args = parser.parse_args()

    textures_data = {}
    for name, params in TEXTURES.items():
        texture_width = int(params.get("width", params.get("size", TEX_SIZE)))
        texture_height = int(params.get("height", params.get("size", TEX_SIZE)))
        pixels, palette = generate_pixel_data(
            params["color"],
            params["noise"],
            texture_width,
            texture_height,
            seed=texture_seed(name),
            pattern=params.get("pattern", "void_substrate"),
            label=params.get("label", 0),
            code=params.get("code", ""),
            ward_type=params.get("ward_type", ""),
            drift=params.get("drift", 0),
            accent=params.get("accent", 0),
            effect=params.get("effect", ""),
            palette_mode=params.get("palette", "monochrome"),
        )
        miptex = make_miptex(name, texture_width, texture_height, pixels, palette)
        textures_data[name] = (miptex, palette)
        print(f"  {name}: {texture_width}x{texture_height}, {len(miptex)} bytes")

    output_dir = Path(__file__).parent.parent / "assets" / "quake" / "maps"
    output_dir.mkdir(parents=True, exist_ok=True)
    wad_path = output_dir / "screwm.wad"
    write_wad(textures_data, wad_path)
    print(f"WAD: {wad_path} ({wad_path.stat().st_size} bytes)")

    if args.no_deploy:
        return

    dp_wad = Path.home() / ".darkplaces" / "screwm" / "screwm.wad"
    import shutil

    shutil.copy2(wad_path, dp_wad)
    print(f"Deployed to {dp_wad}")


if __name__ == "__main__":
    main()
