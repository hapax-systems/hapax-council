#!/usr/bin/env python3
"""Generate a Quake WAD2 file with procedural Screwm migration textures.

WAD2 format:
  Header: magic "WAD2", num_entries, dir_offset
  Entry directory: 32 bytes each (offset, disksize, size, type, compression, name[16])
  Texture data: MIPTEX header + 4 mipmap levels + palette
"""

import argparse
import struct
import zlib
from pathlib import Path

WARD_COUNT = 35
WARD_CODES = [
    "TOKEN",
    "ALBUM",
    "STREAM",
    "SIERP",
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
    "M8",
    "DECK",
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
    "SCOPE",
]

TEXTURES = {
    "city4_2": {"color": (100, 80, 55), "noise": 12, "pattern": "stone_blocks"},
    "ground1_6": {"color": (60, 55, 50), "noise": 8, "pattern": "worn_stone"},
    "sky4": {"color": (25, 22, 30), "noise": 5, "pattern": "dark_ceiling"},
    "metal5_2": {"color": (85, 80, 75), "noise": 10, "pattern": "brushed_metal"},
    "scroom": {"color": (44, 38, 34), "noise": 4, "pattern": "scroom"},
    # R&D / Gruvbox tower bands, bottom to top.
    "r_percep": {"color": (108, 74, 45), "noise": 12, "pattern": "stone_blocks"},
    "r_cognit": {"color": (78, 86, 74), "noise": 10, "pattern": "carved_stone"},
    "r_comm": {"color": (58, 88, 78), "noise": 11, "pattern": "metal_grate"},
    "r_express": {"color": (84, 54, 72), "noise": 12, "pattern": "dark_ornate"},
    "r_ground": {"color": (128, 104, 58), "noise": 9, "pattern": "polished_stone"},
    # Research / Solarized tower bands, bottom to top.
    "s_percep": {"color": (48, 68, 78), "noise": 10, "pattern": "stone_blocks"},
    "s_cognit": {"color": (70, 86, 92), "noise": 9, "pattern": "carved_stone"},
    "s_comm": {"color": (52, 88, 88), "noise": 10, "pattern": "metal_grate"},
    "s_express": {"color": (62, 58, 88), "noise": 10, "pattern": "dark_ornate"},
    "s_ground": {"color": (92, 86, 72), "noise": 8, "pattern": "polished_stone"},
    # In-scroom drift carriers. These are physical materials, not overlay strokes.
    "drift_c": {"color": (80, 180, 170), "noise": 0, "pattern": "drift_line", "drift": 214},
    "drift_a": {"color": (210, 150, 74), "noise": 0, "pattern": "drift_line", "drift": 198},
    "drift_r": {"color": (205, 82, 120), "noise": 0, "pattern": "drift_line", "drift": 186},
    "drift_g": {"color": (120, 180, 86), "noise": 0, "pattern": "drift_line", "drift": 202},
}

TEX_SIZE = 64

for ward_idx in range(1, WARD_COUNT + 1):
    TEXTURES[f"w{ward_idx:02d}"] = {
        "color": (120, 105, 70),
        "noise": 0,
        "pattern": "ward_panel",
        "label": ward_idx,
        "code": WARD_CODES[ward_idx - 1],
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


def ward_panel_index(x, y, label, code):
    """High-contrast in-engine ward anchor texture with identity baked in."""
    if x < 2 or y < 2 or x >= TEX_SIZE - 2 or y >= TEX_SIZE - 2:
        return 232
    if x < 5 or y < 5 or x >= TEX_SIZE - 5 or y >= TEX_SIZE - 5:
        return 90
    if y in (12, 13, 48, 49):
        return 176
    if x in (12, 13, 50, 51):
        return 62

    # Diagonal scan-strata give every pane motion-read even as a baked texture.
    base = 34 + ((x * 3 + y * 5 + label * 11) % 28)
    if (x + y + label * 3) % 17 == 0:
        base = 118

    text = f"{label:02d}"
    scale = 5
    start_x = 17
    start_y = 20
    digit_w = 3 * scale
    gap = 4
    for digit_idx, char in enumerate(text):
        glyph_x = x - start_x - digit_idx * (digit_w + gap)
        glyph_y = y - start_y
        if 0 <= glyph_x < digit_w and 0 <= glyph_y < 5 * scale:
            col = glyph_x // scale
            row = glyph_y // scale
            if digit_is_lit(char, col, row):
                return 236
            if (glyph_x % scale in (0, scale - 1)) or (glyph_y % scale in (0, scale - 1)):
                return max(base, 76)

    short_code = code[:7].upper()
    code_scale = 2
    code_width = len(short_code) * 3 * code_scale + max(0, len(short_code) - 1) * code_scale
    if text_pixel_lit(x, y, short_code, (TEX_SIZE - code_width) // 2, 43, code_scale):
        return 212

    return base


def generate_pixel_data(
    color, noise, width, height, seed=0, pattern="stone_blocks", label=0, code="", drift=0
):
    """Generate Quake-style texture with visible material character."""
    import random

    random.seed(seed)
    pixels = bytearray()
    palette = []

    for i in range(256):
        t = i / 255.0
        r = max(0, min(255, int(color[0] * (0.3 + t * 0.7))))
        g = max(0, min(255, int(color[1] * (0.3 + t * 0.7))))
        b = max(0, min(255, int(color[2] * (0.3 + t * 0.7))))
        palette.extend([r, g, b])

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

            elif pattern == "scroom":
                base = 34 + random.randint(-5, 7)
                diag_a = abs(((x + y // 2) % 32) - 16)
                diag_b = abs(((x - y // 2) % 32) - 16)
                if diag_a < 2 or diag_b < 2:
                    base += 34
                if x % 16 == 0 or y % 16 == 0:
                    base += 22
                if (x * 7 + y * 11 + seed) % 101 < 3:
                    base += 54

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
                pixels.append(ward_panel_index(x, y, int(label), str(code)))
                continue

            # Add surface noise
            random.seed(seed + y * width + x)
            base += random.randint(-noise, noise)
            idx = max(10, min(245, base))
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
        pixels, palette = generate_pixel_data(
            params["color"],
            params["noise"],
            TEX_SIZE,
            TEX_SIZE,
            seed=texture_seed(name),
            pattern=params.get("pattern", "stone_blocks"),
            label=params.get("label", 0),
            code=params.get("code", ""),
            drift=params.get("drift", 0),
        )
        miptex = make_miptex(name, TEX_SIZE, TEX_SIZE, pixels, palette)
        textures_data[name] = (miptex, palette)
        print(f"  {name}: {TEX_SIZE}x{TEX_SIZE}, {len(miptex)} bytes")

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
