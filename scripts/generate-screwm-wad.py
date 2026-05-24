#!/usr/bin/env python3
"""Generate a Quake WAD2 file with procedural stone/metal textures.

WAD2 format:
  Header: magic "WAD2", num_entries, dir_offset
  Entry directory: 32 bytes each (offset, disksize, size, type, compression, name[16])
  Texture data: MIPTEX header + 4 mipmap levels + palette
"""

import argparse
import struct
import zlib
from pathlib import Path

TEXTURES = {
    "city4_2": {"color": (100, 80, 55), "noise": 12, "pattern": "stone_blocks"},
    "ground1_6": {"color": (60, 55, 50), "noise": 8, "pattern": "worn_stone"},
    "sky4": {"color": (25, 22, 30), "noise": 5, "pattern": "dark_ceiling"},
    "metal5_2": {"color": (85, 80, 75), "noise": 10, "pattern": "brushed_metal"},
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
}

TEX_SIZE = 64


def generate_pixel_data(color, noise, width, height, seed=0, pattern="stone_blocks"):
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
